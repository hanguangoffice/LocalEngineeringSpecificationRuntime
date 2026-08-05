"""Immutable LESR 1.0 review, approval, apply and baseline governance."""

from __future__ import annotations

from collections import Counter
from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import Field, model_validator

from lesr.domain.approval import SignedApproval, TrustedActor, verify_approval
from lesr.domain.semantic import (
    FrozenModel,
    document_hash,
    semantic_hash,
    uuid7_candidate,
)


class ReviewComment(FrozenModel):
    schema_version: Literal["1.0"] = "1.0"
    resource_type: Literal["review_comment"] = "review_comment"
    comment_uid: str = Field(default_factory=uuid7_candidate)
    package_hash: str
    resource_uid: str
    location: str
    author_uid: str
    body: str = Field(min_length=1)
    created_at: datetime
    comment_hash: str = ""

    @model_validator(mode="after")
    def calculate_hash(self) -> ReviewComment:
        expected = document_hash(self.model_dump(mode="json"), "comment_hash")
        if self.comment_hash and self.comment_hash != expected:
            raise ValueError("comment_hash is invalid")
        object.__setattr__(self, "comment_hash", expected)
        return self


class CommentDisposition(StrEnum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"


class CommentResolution(FrozenModel):
    schema_version: Literal["1.0"] = "1.0"
    resource_type: Literal["comment_resolution"] = "comment_resolution"
    resolution_uid: str = Field(default_factory=uuid7_candidate)
    comment_hash: str
    actor_uid: str
    disposition: CommentDisposition
    rationale: str
    created_at: datetime
    resolution_hash: str = ""

    @model_validator(mode="after")
    def calculate_hash(self) -> CommentResolution:
        expected = document_hash(self.model_dump(mode="json"), "resolution_hash")
        if self.resolution_hash and self.resolution_hash != expected:
            raise ValueError("resolution_hash is invalid")
        object.__setattr__(self, "resolution_hash", expected)
        return self


class ConditionSatisfaction(FrozenModel):
    schema_version: Literal["1.0"] = "1.0"
    resource_type: Literal["condition_satisfaction"] = "condition_satisfaction"
    satisfaction_uid: str = Field(default_factory=uuid7_candidate)
    approval_uid: str
    condition_hash: str
    evidence_uids: tuple[str, ...]
    actor_uid: str
    satisfied_at: datetime
    satisfaction_hash: str = ""

    @model_validator(mode="after")
    def validate_and_hash(self) -> ConditionSatisfaction:
        if not self.evidence_uids:
            raise ValueError("condition satisfaction requires evidence")
        expected = document_hash(self.model_dump(mode="json"), "satisfaction_hash")
        if self.satisfaction_hash and self.satisfaction_hash != expected:
            raise ValueError("satisfaction_hash is invalid")
        object.__setattr__(self, "satisfaction_hash", expected)
        return self


class ApprovalRevocation(FrozenModel):
    schema_version: Literal["1.0"] = "1.0"
    resource_type: Literal["approval_revocation"] = "approval_revocation"
    revocation_uid: str = Field(default_factory=uuid7_candidate)
    approval_uid: str
    actor_uid: str
    reason: str = Field(min_length=1)
    revoked_at: datetime
    revocation_hash: str = ""

    @model_validator(mode="after")
    def calculate_hash(self) -> ApprovalRevocation:
        expected = document_hash(self.model_dump(mode="json"), "revocation_hash")
        if self.revocation_hash and self.revocation_hash != expected:
            raise ValueError("revocation_hash is invalid")
        object.__setattr__(self, "revocation_hash", expected)
        return self


class StageQuorum(FrozenModel):
    stage: str
    role: str
    minimum_count: int = Field(ge=1)


class ReviewPolicy(FrozenModel):
    stages: tuple[StageQuorum, ...]
    require_preparer_independence: bool = True
    require_comment_resolution: bool = True

    @model_validator(mode="after")
    def unique_stage_roles(self) -> ReviewPolicy:
        keys = [(item.stage, item.role) for item in self.stages]
        if len(keys) != len(set(keys)):
            raise ValueError("review stage/role quorum must be unique")
        return self


class ReviewPackage(FrozenModel):
    schema_version: Literal["1.0"] = "1.0"
    resource_type: Literal["review_package"] = "review_package"
    package_uid: str = Field(default_factory=uuid7_candidate)
    workspace_uid: str
    base_commit: str
    configuration_uid: str
    candidate_hash: str
    candidate_scope: tuple[str, ...]
    semantic_diff_hash: str
    graph_snapshot_hash: str
    context_bundle_hash: str
    impact_report_hash: str
    validation_hash: str
    finding_hashes: tuple[str, ...]
    comment_hashes: tuple[str, ...]
    review_policy: ReviewPolicy
    effective_model_hash: str
    prepared_by_actor_uid: str
    created_at: datetime
    subject_hash: str = ""
    package_hash: str = ""

    @model_validator(mode="after")
    def calculate_hash(self) -> ReviewPackage:
        if not self.candidate_scope:
            raise ValueError("review package candidate scope cannot be empty")
        subject_document = self.model_dump(mode="json")
        subject_document["comment_hashes"] = []
        subject_document.pop("subject_hash", None)
        subject_document.pop("package_hash", None)
        expected_subject = semantic_hash(subject_document)
        if self.subject_hash and self.subject_hash != expected_subject:
            raise ValueError("subject_hash is invalid")
        object.__setattr__(self, "subject_hash", expected_subject)
        expected = document_hash(self.model_dump(mode="json"), "package_hash")
        if self.package_hash and self.package_hash != expected:
            raise ValueError("package_hash is invalid")
        object.__setattr__(self, "package_hash", expected)
        return self


class GovernanceDecision(FrozenModel):
    allowed: bool
    reasons: tuple[str, ...]
    covered_scope: tuple[str, ...]
    quorum: tuple[tuple[str, str, int, int], ...]


class GovernanceEvaluator:
    """Pure decision function used unchanged by Service and Git transaction engine."""

    @staticmethod
    def evaluate(
        package: ReviewPackage,
        approvals: tuple[SignedApproval, ...],
        trust: tuple[TrustedActor, ...],
        comments: tuple[ReviewComment, ...],
        resolutions: tuple[CommentResolution, ...],
        satisfactions: tuple[ConditionSatisfaction, ...],
        revocations: tuple[ApprovalRevocation, ...],
        *,
        now: datetime,
    ) -> GovernanceDecision:
        reasons: list[str] = []
        trust_by_key = {item.key_uid: item for item in trust}
        revoked = {item.approval_uid for item in revocations if item.revoked_at <= now}
        resolved_comments = {item.comment_hash for item in resolutions}
        package_comments = {
            item.comment_hash
            for item in comments
            if item.package_hash == package.subject_hash
            and item.comment_hash in package.comment_hashes
        }
        if set(package.comment_hashes) != package_comments:
            reasons.append("REVIEW_COMMENT_EVIDENCE_MISSING")
        if (
            package.review_policy.require_comment_resolution
            and not package_comments <= resolved_comments
        ):
            reasons.append("OPEN_REVIEW_COMMENT")
        valid: list[SignedApproval] = []
        for approval in approvals:
            if approval.approval_uid in revoked:
                reasons.append(f"APPROVAL_REVOKED:{approval.approval_uid}")
                continue
            actor = trust_by_key.get(approval.key_uid)
            if actor is None:
                reasons.append(f"TRUST_NOT_FOUND:{approval.approval_uid}")
                continue
            try:
                verify_approval(
                    approval,
                    actor,
                    package_hash=package.package_hash,
                    effective_model_hash=package.effective_model_hash,
                    now=now,
                )
            except PermissionError as error:
                reasons.append(f"APPROVAL_INVALID:{approval.approval_uid}:{error}")
                continue
            if (
                package.review_policy.require_preparer_independence
                and approval.actor_uid == package.prepared_by_actor_uid
            ):
                reasons.append(f"PREPARER_SELF_APPROVAL:{approval.approval_uid}")
                continue
            condition_hashes = {semantic_hash({"condition": item}) for item in approval.conditions}
            satisfied = {
                item.condition_hash
                for item in satisfactions
                if item.approval_uid == approval.approval_uid
            }
            if not condition_hashes <= satisfied:
                reasons.append(f"CONDITION_UNSATISFIED:{approval.approval_uid}")
                continue
            valid.append(approval)
        covered: set[str] = set()
        counts: Counter[tuple[str, str]] = Counter()
        for approval in valid:
            raw_scope = approval.scope.get("resource_uids")
            if isinstance(raw_scope, list):
                covered.update(str(item) for item in raw_scope)
            stage = approval.approval_type
            counts[(stage, approval.actor_role)] += 1
        expected_scope = set(package.candidate_scope)
        if covered != expected_scope:
            reasons.append("PARTIAL_APPROVAL_SCOPE_INCOMPLETE")
        quorum: list[tuple[str, str, int, int]] = []
        for requirement in package.review_policy.stages:
            actual = counts[(requirement.stage, requirement.role)]
            quorum.append((requirement.stage, requirement.role, actual, requirement.minimum_count))
            if actual < requirement.minimum_count:
                reasons.append(
                    f"QUORUM_NOT_MET:{requirement.stage}:{requirement.role}:"
                    f"{actual}/{requirement.minimum_count}"
                )
        return GovernanceDecision(
            allowed=not reasons,
            reasons=tuple(reasons),
            covered_scope=tuple(sorted(covered)),
            quorum=tuple(quorum),
        )


class RevocationConsequence(FrozenModel):
    pre_apply_invalidates: bool
    assurance_finding: str | None
    revalidation_trigger: str | None


def revocation_consequence(*, already_applied: bool) -> RevocationConsequence:
    if not already_applied:
        return RevocationConsequence(
            pre_apply_invalidates=True,
            assurance_finding=None,
            revalidation_trigger=None,
        )
    return RevocationConsequence(
        pre_apply_invalidates=False,
        assurance_finding="APPROVAL_REVOKED_AFTER_APPLY",
        revalidation_trigger="REVALIDATE_APPLIED_SCOPE",
    )


class BaselineStatus(StrEnum):
    PREPARED = "prepared"
    APPROVED = "approved"
    APPLIED = "applied"
    TAG_PENDING = "tag_pending"
    COMPLETE = "complete"


class BaselinePreparation(FrozenModel):
    schema_version: Literal["1.0"] = "1.0"
    resource_type: Literal["baseline_preparation"] = "baseline_preparation"
    preparation_uid: str = Field(default_factory=uuid7_candidate)
    configuration_uid: str
    state_commit: str
    graph_snapshot_hash: str
    validation_run_hash: str
    impact_report_hash: str
    review_package_hash: str
    status: BaselineStatus
    preparation_hash: str = ""

    @model_validator(mode="after")
    def calculate_hash(self) -> BaselinePreparation:
        expected = document_hash(self.model_dump(mode="json"), "preparation_hash")
        if self.preparation_hash and self.preparation_hash != expected:
            raise ValueError("preparation_hash is invalid")
        object.__setattr__(self, "preparation_hash", expected)
        return self


class BaselineManifest(FrozenModel):
    schema_version: Literal["1.0"] = "1.0"
    resource_type: Literal["baseline_manifest"] = "baseline_manifest"
    baseline_uid: str = Field(default_factory=uuid7_candidate)
    state_commit: str
    manifest_commit: str | None = None
    configuration_uid: str
    exact_revision_uids: tuple[str, ...]
    exact_relation_revision_uids: tuple[str, ...]
    effective_model_hash: str
    deviation_revision_uids: tuple[str, ...]
    review_package_hash: str
    created_at: datetime
    tag_name: str | None = None
    tag_status: Literal["not_requested", "created", "pending_rebuild"] = "not_requested"
    manifest_hash: str = ""

    @model_validator(mode="after")
    def validate_and_hash(self) -> BaselineManifest:
        if self.manifest_commit is not None and self.manifest_commit == self.state_commit:
            raise ValueError("manifest commit must contain and therefore follow frozen state")
        expected = document_hash(self.model_dump(mode="json"), "manifest_hash")
        if self.manifest_hash and self.manifest_hash != expected:
            raise ValueError("manifest_hash is invalid")
        object.__setattr__(self, "manifest_hash", expected)
        return self


def prepare_baseline(
    *,
    configuration_uid: str,
    state_commit: str,
    graph_snapshot_hash: str,
    validation_run_hash: str,
    impact_report_hash: str,
    review_package_hash: str,
    configuration_complete: bool,
    validation_passed: bool,
    impact_complete: bool,
) -> BaselinePreparation:
    if not configuration_complete:
        raise ValueError("LESR-BASELINE-CONFIGURATION-INCOMPLETE")
    if not validation_passed:
        raise ValueError("LESR-BASELINE-VALIDATION-NOT-PASSED")
    if not impact_complete:
        raise ValueError("LESR-BASELINE-IMPACT-INCOMPLETE")
    return BaselinePreparation(
        configuration_uid=configuration_uid,
        state_commit=state_commit,
        graph_snapshot_hash=graph_snapshot_hash,
        validation_run_hash=validation_run_hash,
        impact_report_hash=impact_report_hash,
        review_package_hash=review_package_hash,
        status=BaselineStatus.PREPARED,
    )
