"""LESR v1 Git-backed canonical state and atomic semantic transactions."""

from __future__ import annotations

import json
import os
import re
import sqlite3
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Any

from jsonschema.exceptions import ValidationError as JsonSchemaValidationError

from lesr.adapters.schemas import SchemaCatalog
from lesr.domain.approval import SignedApproval, TrustedActor, verify_approval
from lesr.domain.catalog import RepositoryManifest, default_repository_manifest
from lesr.domain.model import (
    EffectiveModelCompiler,
    FacetDefinitionRevision,
    KindDefinitionRevision,
    NormativeProfileRevision,
    RelationTypeRevision,
    TailoringOverlay,
    WorkflowRevision,
)
from lesr.domain.profiles import ProfileCompiler, ProfileRevision
from lesr.domain.rules import (
    EnforcementEffect,
    EvaluationEnvironment,
    Quantity,
    RuleDefinition,
    RuleOutcome,
    UnitRegistry,
    ValueCell,
    evaluate_rule,
)
from lesr.domain.semantic import canonical_json, document_hash, semantic_hash, uuid7_candidate


class OperationType(StrEnum):
    CREATE_LOGICAL_OBJECT = "create_logical_object"
    CREATE_REVISION = "create_revision"
    SET_DISPOSITION = "set_disposition"
    ASSERT_RELATION = "assert_relation"
    RETIRE_RELATION = "retire_relation"
    CREATE_RECORD = "create_record"
    RETRACT_RECORD = "retract_record"
    CREATE_DEVIATION = "create_deviation"
    REVOKE_DEVIATION = "revoke_deviation"
    UPDATE_PROFILE_BINDING = "update_profile_binding"
    CREATE_CONFIGURATION = "create_configuration"
    CREATE_BASELINE = "create_baseline"
    PROMOTE_FRAGMENT = "promote_fragment"
    SPLIT_OBJECT = "split_object"
    CONSOLIDATE_OBJECT = "consolidate_object"
    REGISTER_TRUSTED_ACTOR = "register_trusted_actor"
    CREATE_DELEGATION = "create_delegation"
    RECORD_APPROVAL = "record_approval"
    CREATE_RULE = "create_rule"
    RECORD_VALIDATION_RUN = "record_validation_run"
    RECORD_VALIDATION_FINDING = "record_validation_finding"
    RECORD_REVIEW_PACKAGE = "record_review_package"
    RECORD_PROVENANCE = "record_provenance"
    RECORD_BASELINE_PREPARATION = "record_baseline_preparation"


class CheckpointStrategy(StrEnum):
    COMMIT_PER_CHECKPOINT = "commit_per_checkpoint"
    WORKSPACE_REF = "workspace_ref"


class CanonicalError(RuntimeError):
    pass


class ConcurrencyConflict(CanonicalError):
    pass


class IdempotencyConflict(CanonicalError):
    pass


class ApprovalError(CanonicalError):
    pass


class IntegrityError(CanonicalError):
    pass


class InjectedFailure(CanonicalError):
    pass


@dataclass(frozen=True, slots=True)
class SemanticOperation:
    operation_type: OperationType
    relative_path: str
    payload: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ApprovalAttestation:
    approval_uid: str
    package_hash: str
    actor: str
    actor_type: str
    approval_type: str


@dataclass(frozen=True, slots=True)
class SemanticTransaction:
    transaction_uid: str
    base_commit: str
    expected_revisions: tuple[tuple[str, str], ...]
    effective_model_hash: str
    review_package_hash: str
    operations: tuple[SemanticOperation, ...]
    approvals: tuple[ApprovalAttestation, ...]
    actor: str
    delegation_uid: str
    idempotency_key: str

    def hash(self) -> str:
        return semantic_hash(
            {
                "transaction_uid": self.transaction_uid,
                "base_commit": self.base_commit,
                "expected_revisions": self.expected_revisions,
                "effective_model_hash": self.effective_model_hash,
                "review_package_hash": self.review_package_hash,
                "operations": [
                    {
                        "operation_type": item.operation_type,
                        "relative_path": item.relative_path,
                        "payload": item.payload,
                    }
                    for item in self.operations
                ],
                "approvals": [
                    {
                        "approval_uid": item.approval_uid,
                        "package_hash": item.package_hash,
                        "actor": item.actor,
                        "actor_type": item.actor_type,
                        "approval_type": item.approval_type,
                    }
                    for item in self.approvals
                ],
                "actor": self.actor,
                "delegation_uid": self.delegation_uid,
                "idempotency_key": self.idempotency_key,
            }
        )


@dataclass(frozen=True, slots=True)
class ApplyResult:
    commit: str
    transaction_hash: str
    idempotent_replay: bool
    projection_stale: bool


@dataclass(frozen=True, slots=True)
class CheckpointResult:
    checkpoint_uid: str
    commit: str
    git_reference: str
    strategy: CheckpointStrategy


FaultInjector = Callable[[str], None]
ProjectionUpdater = Callable[[str], None]


def _definition_revision(
    value: dict[str, Any],
) -> (
    FacetDefinitionRevision
    | KindDefinitionRevision
    | RelationTypeRevision
    | WorkflowRevision
):
    resource_type = value.get("resource_type")
    if resource_type == "facet_definition_revision":
        return FacetDefinitionRevision.model_validate(value)
    if resource_type == "kind_definition_revision":
        return KindDefinitionRevision.model_validate(value)
    if resource_type == "relation_type_revision":
        return RelationTypeRevision.model_validate(value)
    if resource_type == "workflow_revision":
        return WorkflowRevision.model_validate(value)
    raise TypeError(f"unsupported definition revision: {resource_type}")

_RESOURCE_SCHEMAS = {
    "logical_object": "logical-object.schema.json",
    "revision": "revision.schema.json",
    "relation_assertion_revision": "relation-assertion.schema.json",
    "immutable_record": "immutable-record.schema.json",
    "profile_revision": "profile.schema.json",
    "normative_profile_revision": "normative-profile.schema.json",
    "configuration_snapshot": "configuration.schema.json",
    "baseline_manifest": "baseline-manifest.schema.json",
    "trusted_actor": "trusted-actor.schema.json",
    "delegation_grant": "delegation-grant.schema.json",
    "approval_attestation": "approval-attestation.schema.json",
    "rule_definition_revision": "rule-definition.schema.json",
    "applied_change": "applied-change.schema.json",
    "provenance_record": "provenance.schema.json",
    "audit_anchor": "audit-anchor.schema.json",
    "validation_run": "validation-run.schema.json",
    "validation_finding": "validation-finding.schema.json",
    "review_package": "review-package.schema.json",
    "facet_definition_revision": "facet-definition.schema.json",
    "kind_definition_revision": "kind-definition.schema.json",
    "relation_type_revision": "relation-type.schema.json",
    "workflow_revision": "workflow.schema.json",
    "baseline_preparation": "baseline-preparation.schema.json",
    "semantic_diff": "semantic-diff.schema.json",
    "graph_snapshot": "graph-snapshot.schema.json",
    "context_bundle": "context-bundle.schema.json",
    "impact_report": "impact-report.schema.json",
}

_OPERATION_RESOURCE_TYPES = {
    OperationType.CREATE_LOGICAL_OBJECT: frozenset({"logical_object"}),
    OperationType.CREATE_REVISION: frozenset({"revision"}),
    OperationType.SET_DISPOSITION: frozenset({"immutable_record"}),
    OperationType.ASSERT_RELATION: frozenset({"relation_assertion_revision"}),
    OperationType.RETIRE_RELATION: frozenset({"immutable_record"}),
    OperationType.CREATE_RECORD: frozenset(
        {
            "immutable_record",
            "facet_definition_revision",
            "kind_definition_revision",
            "relation_type_revision",
            "workflow_revision",
        }
    ),
    OperationType.RETRACT_RECORD: frozenset({"immutable_record"}),
    OperationType.CREATE_DEVIATION: frozenset({"revision", "immutable_record"}),
    OperationType.REVOKE_DEVIATION: frozenset({"immutable_record"}),
    OperationType.UPDATE_PROFILE_BINDING: frozenset(
        {"profile_revision", "normative_profile_revision"}
    ),
    OperationType.CREATE_CONFIGURATION: frozenset({"configuration_snapshot"}),
    OperationType.CREATE_BASELINE: frozenset({"baseline_manifest"}),
    OperationType.PROMOTE_FRAGMENT: frozenset({"logical_object", "revision", "immutable_record"}),
    OperationType.SPLIT_OBJECT: frozenset({"logical_object", "revision", "immutable_record"}),
    OperationType.CONSOLIDATE_OBJECT: frozenset({"logical_object", "revision", "immutable_record"}),
    OperationType.REGISTER_TRUSTED_ACTOR: frozenset({"trusted_actor"}),
    OperationType.CREATE_DELEGATION: frozenset({"delegation_grant"}),
    OperationType.RECORD_APPROVAL: frozenset({"approval_attestation"}),
    OperationType.CREATE_RULE: frozenset({"rule_definition_revision"}),
    OperationType.RECORD_VALIDATION_RUN: frozenset({"validation_run"}),
    OperationType.RECORD_VALIDATION_FINDING: frozenset({"validation_finding"}),
    OperationType.RECORD_REVIEW_PACKAGE: frozenset({"review_package"}),
    OperationType.RECORD_PROVENANCE: frozenset({"provenance_record"}),
    OperationType.RECORD_BASELINE_PREPARATION: frozenset({"baseline_preparation"}),
}


class GitCanonicalRepository:
    CANONICAL_REF = "refs/heads/lesr/canonical"

    def __init__(self, path: Path) -> None:
        self.path = path.resolve()
        self.schemas = SchemaCatalog()

    def initialize(self) -> str:
        self.path.mkdir(parents=True, exist_ok=True)
        if not (self.path / ".git").exists():
            self._git("init", "--quiet")
            self._git("config", "user.name", "LESR Runtime")
            self._git("config", "user.email", "lesr-runtime@invalid.local")
        existing = self._try_git("rev-parse", "--verify", self.CANONICAL_REF)
        if existing is not None:
            self.require_v1_manifest(existing)
            return existing
        manifest = default_repository_manifest().model_dump(mode="json")
        blob = self._git(
            "hash-object",
            "-w",
            "--stdin",
            input_bytes=(canonical_json(manifest) + "\n").encode("utf-8"),
        )
        tree = self._git(
            "mktree",
            input_bytes=f"100644 blob {blob}\t.repository-manifest.json\n".encode("ascii"),
        )
        commit = self._commit_tree(tree, (), "Initialize LESR canonical state")
        self._git("update-ref", self.CANONICAL_REF, commit)
        return commit

    def require_v1_manifest(self, commit: str | None = None) -> dict[str, Any]:
        """Reject pre-1.0 and malformed repositories at the authority boundary."""

        selected = commit or self.current_commit()
        value = self.read_json(selected, ".repository-manifest.json")
        if value is None:
            raise IntegrityError(
                "LESR-MANIFEST-MISSING: 0.5 repositories are incompatible with runtime 1.0"
            )
        try:
            self.schemas.validate("repository-manifest.schema.json", value)
            manifest = RepositoryManifest.model_validate(value)
        except (JsonSchemaValidationError, ValueError) as error:
            raise IntegrityError(f"LESR-MANIFEST-INVALID: {error}") from error
        return manifest.model_dump(mode="json")

    def current_commit(self) -> str:
        return self._git("rev-parse", "--verify", self.CANONICAL_REF)

    def apply_candidate(
        self,
        *,
        base_commit: str,
        candidate: Any,
        review_package: Any,
        approvals: tuple[SignedApproval, ...],
        trust: tuple[TrustedActor, ...],
        evaluation_time: datetime,
        actor_uid: str,
        delegation_uid: str,
        idempotency_key: str,
        comments: tuple[Any, ...] = (),
        resolutions: tuple[Any, ...] = (),
        satisfactions: tuple[Any, ...] = (),
        revocations: tuple[Any, ...] = (),
        evidence: dict[str, Any] | None = None,
        validation_recalculator: Callable[[], str] | None = None,
        projection_updater: ProjectionUpdater | None = None,
        fault_injector: FaultInjector | None = None,
    ) -> ApplyResult:
        """Atomically promote an evaluated 1.0 Candidate; governance is recomputed upstream."""

        from lesr.domain.review import (
            ApprovalRevocation,
            CommentResolution,
            ConditionSatisfaction,
            GovernanceEvaluator,
            ReviewComment,
            ReviewPackage,
        )
        from lesr.domain.workspace import CandidateRevisionSet

        selected_candidate = CandidateRevisionSet.model_validate(candidate)
        package = ReviewPackage.model_validate(review_package)
        if selected_candidate.candidate_hash != package.candidate_hash:
            raise IntegrityError("review package does not bind candidate")
        if selected_candidate.effective_model_hash != package.effective_model_hash:
            raise IntegrityError("review package does not bind effective model")
        if not approvals:
            raise ApprovalError("candidate apply requires human approval")
        decision = GovernanceEvaluator.evaluate(
            package,
            approvals,
            trust,
            tuple(ReviewComment.model_validate(item) for item in comments),
            tuple(CommentResolution.model_validate(item) for item in resolutions),
            tuple(ConditionSatisfaction.model_validate(item) for item in satisfactions),
            tuple(ApprovalRevocation.model_validate(item) for item in revocations),
            now=evaluation_time,
        )
        if not decision.allowed:
            raise ApprovalError("; ".join(decision.reasons))
        if validation_recalculator is None:
            raise IntegrityError("Git transaction boundary requires validation recalculation")
        if validation_recalculator() != package.validation_hash:
            raise IntegrityError("review package validation result changed before apply")
        frozen_evidence = evidence or {}
        self._verify_review_evidence(package, frozen_evidence)
        canonical_evidence = all(
            isinstance(frozen_evidence.get(name), dict)
            and frozen_evidence[name].get("resource_type") == name
            for name in (
                "semantic_diff",
                "graph_snapshot",
                "context_bundle",
                "impact_report",
            )
        ) and isinstance(frozen_evidence.get("validation", {}).get("validation_run"), dict)
        current = self.current_commit()
        if current != base_commit:
            raise ConcurrencyConflict(
                f"canonical base changed: expected {base_commit}, got {current}"
            )
        idempotency_hash = semantic_hash({"idempotency_key": idempotency_key})
        idempotency_path = f"canonical/idempotency/{idempotency_hash.removeprefix('sha256:')}.json"
        previous = self.read_json(current, idempotency_path)
        transaction_hash = semantic_hash(
            {
                "base_commit": package.base_commit,
                "candidate_hash": selected_candidate.candidate_hash,
                "review_package_hash": package.package_hash,
                "approval_uids": tuple(item.approval_uid for item in approvals),
                "actor_uid": actor_uid,
                "delegation_uid": delegation_uid,
                "idempotency_key_hash": idempotency_hash,
            }
        )
        if previous is not None:
            if previous.get("transaction_hash") != transaction_hash:
                raise IdempotencyConflict("idempotency key was used for another candidate")
            commits = self._git(
                "log",
                current,
                "--diff-filter=A",
                "--format=%H",
                "--reverse",
                "--",
                idempotency_path,
            ).splitlines()
            if not commits:
                raise IntegrityError("idempotency record has no introducing commit")
            return ApplyResult(commits[0], transaction_hash, True, False)
        transaction_uid = uuid7_candidate()
        applied_at = self._utc_now()
        index = self.path / ".git" / f"lesr-index-{uuid7_candidate()}"
        env = {"GIT_INDEX_FILE": str(index)}
        projection_stale = False
        try:
            self._git("read-tree", current, extra_env=env)
            self._inject(fault_injector, "staging")
            operation_hashes: list[str] = []
            for revision in selected_candidate.revisions:
                value = revision.model_dump(mode="json", exclude_none=True)
                path = f"canonical/revisions/{revision.revision_uid}.json"
                self._stage_json(path, value, env)
                operation_hashes.append(semantic_hash({"path": path, "value": value}))
                if revision.parent_revision_uid is None:
                    from lesr.domain.semantic import LogicalObject

                    logical = LogicalObject(
                        entity_uid=revision.object_uid,
                        namespace="project",
                        human_key=revision.human_key,
                        kind=revision.kind,
                        facets=revision.facets,
                        created_at=revision.created_at,
                    ).model_dump(mode="json", exclude_none=True)
                    object_path = f"canonical/objects/{revision.object_uid}.json"
                    self._stage_json(object_path, logical, env)
                    operation_hashes.append(semantic_hash({"path": object_path, "value": logical}))
            for relation in selected_candidate.relation_revisions:
                value = relation.model_dump(mode="json", exclude_none=True)
                path = f"canonical/relation_assertions/{relation.relation_revision_uid}.json"
                self._stage_json(path, value, env)
                operation_hashes.append(semantic_hash({"path": path, "value": value}))
            for record in selected_candidate.lifecycle_records:
                value = record.model_dump(mode="json", exclude_none=True)
                path = f"canonical/immutable_records/{record.record_uid}.json"
                self._stage_json(path, value, env)
                operation_hashes.append(semantic_hash({"path": path, "value": value}))
            evidence_paths = {
                "semantic_diff": ("semantic_diffs", "diff_uid"),
                "graph_snapshot": ("graph_snapshots", "snapshot_uid"),
                "context_bundle": ("context_bundles", "bundle_uid"),
                "impact_report": ("impact_reports", "report_uid"),
            }
            for evidence_name, (directory, uid_field) in evidence_paths.items():
                evidence_value = frozen_evidence.get(evidence_name)
                if (
                    not isinstance(evidence_value, dict)
                    or evidence_value.get("resource_type") != evidence_name
                    or uid_field not in evidence_value
                ):
                    continue
                path = f"canonical/{directory}/{evidence_value[uid_field]}.json"
                self._stage_json(path, evidence_value, env)
                operation_hashes.append(
                    semantic_hash({"path": path, "value": evidence_value})
                )
            validation = frozen_evidence.get("validation")
            if isinstance(validation, dict) and isinstance(
                validation.get("validation_run"), dict
            ):
                run = validation["validation_run"]
                path = f"canonical/validation/runs/{run['validation_run_uid']}.json"
                self._stage_json(path, run, env)
                operation_hashes.append(semantic_hash({"path": path, "value": run}))
            package_path = f"canonical/review_packages/{package.package_uid}.json"
            self._stage_json(package_path, package.model_dump(mode="json", exclude_none=True), env)
            operation_hashes.append(
                semantic_hash({"path": package_path, "value": package.package_hash})
            )
            for approval in approvals:
                self._stage_json(
                    f"canonical/approvals/{approval.approval_uid}.json",
                    approval.model_dump(mode="json", exclude_none=True),
                    env,
                )
                provenance = self._approval_provenance(approval)
                self._stage_json(
                    f"canonical/provenance/{approval.provenance_uid}.json",
                    provenance,
                    env,
                )
            for directory, records in (
                ("review_comments", comments),
                ("comment_resolutions", resolutions),
                ("condition_satisfactions", satisfactions),
                ("approval_revocations", revocations),
            ):
                for record in records:
                    value = record.model_dump(mode="json", exclude_none=True)
                    record_uid = next(
                        (
                            str(item)
                            for key, item in value.items()
                            if key.endswith("_uid") and key not in {"package_uid", "actor_uid"}
                        ),
                        semantic_hash(value).removeprefix("sha256:"),
                    )
                    self._stage_json(f"canonical/{directory}/{record_uid}.json", value, env)
            applied_change = {
                "schema_version": "1.0",
                "resource_type": "applied_change",
                "transaction_uid": transaction_uid,
                "transaction_hash": transaction_hash,
                "base_commit": base_commit,
                "candidate_hash": selected_candidate.candidate_hash,
                "effective_model_hash": package.effective_model_hash,
                "review_package_hash": package.package_hash,
                "operation_hashes": operation_hashes,
                "approval_uids": [item.approval_uid for item in approvals],
                "actor_uid": actor_uid,
                "delegation_uid": delegation_uid,
                "idempotency_key_hash": idempotency_hash,
                "applied_at": applied_at,
            }
            applied_change["content_hash"] = semantic_hash(applied_change)
            self._stage_json(
                f"canonical/applied_changes/{transaction_uid}.json",
                applied_change,
                env,
            )
            audit = {
                "schema_version": "1.0",
                "resource_type": "audit_anchor",
                "anchor_uid": transaction_uid,
                "transaction_uid": transaction_uid,
                "previous_anchor_hash": self._audit_tail(current),
                "event_hashes": [
                    transaction_hash,
                    package.package_hash,
                    *(semantic_hash(item.model_dump(mode="json")) for item in approvals),
                ],
                "created_at": applied_at,
            }
            audit["anchor_hash"] = semantic_hash(audit)
            self._stage_json(f"canonical/audit_anchors/{transaction_uid}.json", audit, env)
            idempotency = {
                "transaction_uid": transaction_uid,
                "transaction_hash": transaction_hash,
            }
            self._stage_json(idempotency_path, idempotency, env)
            self._inject(fault_injector, "write_tree")
            tree = self._git("write-tree", extra_env=env)
            commit = self._commit_tree(
                tree, (current,), f"Apply LESR Candidate {selected_candidate.candidate_uid}"
            )
            if canonical_evidence:
                self._validate_candidate(commit, ())
            self._inject(fault_injector, "update_ref")
            self._git("update-ref", self.CANONICAL_REF, commit, current)
            self._inject(fault_injector, "projection")
            if projection_updater is not None:
                try:
                    projection_updater(commit)
                except Exception:  # noqa: BLE001 - projection is explicitly non-authoritative
                    projection_stale = True
            return ApplyResult(commit, transaction_hash, False, projection_stale)
        finally:
            index.unlink(missing_ok=True)

    def _audit_tail(self, commit: str) -> str | None:
        anchors = [
            value
            for path, value in self.documents(commit)
            if path.startswith("canonical/audit_anchors/")
        ]
        if not anchors:
            return None
        hashes = {str(item["anchor_hash"]) for item in anchors}
        referenced = {
            str(item["previous_anchor_hash"])
            for item in anchors
            if item.get("previous_anchor_hash") is not None
        }
        tails = hashes - referenced
        if len(tails) != 1:
            raise IntegrityError("audit anchor chain has no unique tail")
        return next(iter(tails))

    def idempotency_record(self, idempotency_key: str) -> dict[str, Any] | None:
        current = self.current_commit()
        digest = semantic_hash({"idempotency_key": idempotency_key})
        path = f"canonical/idempotency/{digest.removeprefix('sha256:')}.json"
        value = self.read_json(current, path)
        if value is None:
            return None
        commits = self._git(
            "log", current, "--diff-filter=A", "--format=%H", "--reverse", "--", path
        ).splitlines()
        return value | {"result_commit": commits[0]}

    def is_ancestor(self, ancestor: str, descendant: str) -> bool:
        result = subprocess.run(
            ["git", "-C", str(self.path), "merge-base", "--is-ancestor", ancestor, descendant],
            check=False,
            capture_output=True,
        )
        return result.returncode == 0

    def apply(
        self,
        transaction: SemanticTransaction,
        *,
        projection_updater: ProjectionUpdater | None = None,
        fault_injector: FaultInjector | None = None,
        governance_validator: Callable[[], None] | None = None,
    ) -> ApplyResult:
        self._validate_transaction(transaction)
        current = self.current_commit()
        for operation in transaction.operations:
            self._safe_path(operation.relative_path)
            self._validate_operation(operation)
        transaction_hash = transaction.hash()
        idempotency_hash = semantic_hash({"idempotency_key": transaction.idempotency_key})
        idempotency_path = f"canonical/idempotency/{idempotency_hash.removeprefix('sha256:')}.json"
        previous = self.read_json(current, idempotency_path)
        if previous is not None:
            if previous.get("transaction_hash") != transaction_hash:
                raise IdempotencyConflict(
                    "the idempotency key was already used for a different transaction"
                )
            original_commit = self._git(
                "log",
                current,
                "--diff-filter=A",
                "--format=%H",
                "--reverse",
                "--",
                idempotency_path,
            ).splitlines()[0]
            return ApplyResult(original_commit, transaction_hash, True, False)
        if current != transaction.base_commit:
            raise ConcurrencyConflict(
                f"canonical base changed: expected {transaction.base_commit}, got {current}"
            )
        self._authorize_transaction(current, transaction)
        if governance_validator is None:
            self._validate_governance(current, transaction)
        else:
            governance_validator()
        for operation in transaction.operations:
            safe_path = self._safe_path(operation.relative_path)
            if self.read_bytes(current, safe_path) is not None:
                raise IntegrityError(f"immutable canonical resource already exists: {safe_path}")
        self._verify_expected_revisions(current, transaction.expected_revisions)
        state_operations = tuple(
            item
            for item in transaction.operations
            if item.operation_type
            not in {
                OperationType.RECORD_APPROVAL,
                OperationType.RECORD_PROVENANCE,
                OperationType.RECORD_VALIDATION_RUN,
                OperationType.RECORD_VALIDATION_FINDING,
                OperationType.RECORD_REVIEW_PACKAGE,
                OperationType.RECORD_BASELINE_PREPARATION,
            }
        )
        snapshot_operations = tuple(
            item
            for item in state_operations
            if item.operation_type
            in {OperationType.CREATE_CONFIGURATION, OperationType.CREATE_BASELINE}
        )
        if snapshot_operations:
            if len(state_operations) != 1:
                raise IntegrityError(
                    "configuration/baseline snapshot must be a dedicated semantic transaction"
                )
            if snapshot_operations[0].payload.get("git_commit") != current:
                raise IntegrityError("snapshot must pin the exact pre-snapshot canonical commit")
        self._validate_candidate(current, transaction.operations)

        index_path = self.path / f".lesr-index-{uuid7_candidate()}.tmp"
        index_path.unlink(missing_ok=True)
        env = {"GIT_INDEX_FILE": str(index_path)}
        try:
            self._git("read-tree", current, extra_env=env)
            for operation in transaction.operations:
                content = (canonical_json(operation.payload) + "\n").encode("utf-8")
                self._stage_bytes(self._safe_path(operation.relative_path), content, env)
            applied_at = self._utc_now()
            provenance_record = self._provenance_record(transaction, applied_at)
            audit_record = self._audit_record(
                current,
                transaction,
                transaction_hash,
                applied_at,
            )
            change_record = self._change_record(
                transaction,
                transaction_hash,
                idempotency_hash,
                applied_at,
            )
            for schema_name, record in (
                ("applied-change.schema.json", change_record),
                ("provenance.schema.json", provenance_record),
                ("audit-anchor.schema.json", audit_record),
            ):
                try:
                    self.schemas.validate(schema_name, record)
                except JsonSchemaValidationError as error:
                    raise IntegrityError(
                        f"generated canonical record is invalid: {error.message}"
                    ) from error
            self._stage_json(
                f"canonical/applied_changes/{transaction.transaction_uid}.json",
                change_record,
                env,
            )
            self._stage_json(
                f"canonical/provenance/{transaction.transaction_uid}.json",
                provenance_record,
                env,
            )
            self._stage_json(
                f"canonical/audit_anchors/{transaction.transaction_uid}.json",
                audit_record,
                env,
            )
            self._stage_json(
                idempotency_path,
                {
                    "idempotency_key_hash": idempotency_hash,
                    "transaction_uid": transaction.transaction_uid,
                    "transaction_hash": transaction_hash,
                },
                env,
            )
            self._inject(fault_injector, "after_stage")
            tree = self._git("write-tree", extra_env=env)
            self._inject(fault_injector, "before_commit")
            commit = self._commit_tree(
                tree,
                (current,),
                f"Apply semantic transaction {transaction.transaction_uid}",
            )
            self._inject(fault_injector, "before_ref")
            try:
                self._git("update-ref", self.CANONICAL_REF, commit, current)
            except CanonicalError as error:
                raise ConcurrencyConflict("canonical ref changed during apply") from error
            self._inject(fault_injector, "after_ref")
        finally:
            index_path.unlink(missing_ok=True)
        projection_stale = False
        if projection_updater is not None:
            try:
                projection_updater(commit)
            except (OSError, RuntimeError):
                projection_stale = True
        return ApplyResult(commit, transaction_hash, False, projection_stale)

    @staticmethod
    def _verify_review_evidence(package: Any, evidence: dict[str, Any]) -> None:
        required = {
            "semantic_diff": ("diff_hash", package.semantic_diff_hash),
            "graph_snapshot": ("snapshot_hash", package.graph_snapshot_hash),
            "context_bundle": ("bundle_hash", package.context_bundle_hash),
            "impact_report": ("report_hash", package.impact_report_hash),
            "validation": ("validation_hash", package.validation_hash),
        }
        for name, (field, expected) in required.items():
            value = evidence.get(name)
            if not isinstance(value, dict) or value.get(field) != expected:
                raise IntegrityError(f"review evidence does not bind {name}")
        validation = evidence["validation"]
        if tuple(validation.get("finding_hashes", ())) != tuple(package.finding_hashes):
            raise IntegrityError("review evidence finding hashes changed before apply")
        if validation.get("outcome") != "pass":
            raise ApprovalError("candidate validation is not complete and passing")

    @staticmethod
    def _approval_provenance(approval: SignedApproval) -> dict[str, Any]:
        value: dict[str, Any] = {
            "schema_version": "1.0",
            "resource_type": "provenance_record",
            "provenance_uid": approval.provenance_uid,
            "subject_uid": approval.approval_uid,
            "kind": "asserted",
            "responsible_actor_uid": approval.actor_uid,
            "performed_by_actor_uid": approval.actor_uid,
            "on_behalf_of_actor_uid": None,
            "tool_uids": [],
            "tool_identity": "human-ed25519",
            "delegation_uid": None,
            "used_uids": [],
            "generated_uids": [approval.approval_uid],
            "review_package_uid": None,
            "validation_run_uids": [],
            "context_bundle_hash": None,
            "generated_at": approval.issued_at.isoformat().replace("+00:00", "Z"),
        }
        value["content_hash"] = semantic_hash(value)
        return value

    def _validate_governance(self, current: str, transaction: SemanticTransaction) -> None:
        current_documents = [value for _, value in self.documents(current)]
        configurations = {
            str(value["configuration_uid"]): value
            for value in current_documents
            if value.get("resource_type") == "configuration_snapshot"
        }
        metadata_types = {
            "approval_attestation",
            "provenance_record",
            "validation_run",
            "validation_finding",
            "review_package",
            "baseline_preparation",
        }
        state_operations = tuple(
            item
            for item in transaction.operations
            if item.payload.get("resource_type") not in metadata_types
        )
        if not configurations:
            allowed = {
                "trusted_actor",
                "delegation_grant",
                "rule_definition_revision",
                "profile_revision",
                "normative_profile_revision",
                "facet_definition_revision",
                "kind_definition_revision",
                "relation_type_revision",
                "workflow_revision",
                "configuration_snapshot",
            }
            if any(item.payload.get("resource_type") not in allowed for item in state_operations):
                raise ApprovalError(
                    "engineering content cannot be applied before initial governance configuration"
                )
            return
        packages = [
            item.payload
            for item in transaction.operations
            if item.payload.get("resource_type") == "review_package"
        ]
        runs = {
            str(item.payload["validation_run_uid"]): item.payload
            for item in transaction.operations
            if item.payload.get("resource_type") == "validation_run"
        }
        findings = {
            str(item.payload["finding_uid"]): item.payload
            for item in transaction.operations
            if item.payload.get("resource_type") == "validation_finding"
        }
        if len(packages) != 1 or len(runs) != 1:
            raise ApprovalError(
                "configured transactions require one Validation Run and one Review Package"
            )
        package = packages[0]
        if (
            package.get("package_hash") != transaction.review_package_hash
            or package.get("effective_model_hash") != transaction.effective_model_hash
            or package.get("base_commit") != transaction.base_commit
            or package.get("configuration_uid") not in configurations
        ):
            raise ApprovalError("Review Package does not bind the semantic transaction")
        configuration = configurations[str(package["configuration_uid"])]
        if configuration["effective_model_hash"] != transaction.effective_model_hash:
            raise ApprovalError("transaction Effective Model is not Canonical Configuration")
        operation_hashes = [
            semantic_hash(
                {
                    "operation_type": item.operation_type.value,
                    "resource": item.payload,
                }
            )
            for item in state_operations
        ]
        candidate_hash = semantic_hash(
            {
                "operations": [
                    {
                        "operation_type": item.operation_type.value,
                        "resource": item.payload,
                    }
                    for item in state_operations
                ]
            }
        )
        if (
            package.get("semantic_diff", {}).get("operation_hashes") != operation_hashes
            or package.get("candidate_hash") != candidate_hash
        ):
            raise ApprovalError("Review Package does not bind the exact candidate operations")
        package_run_uids = {str(uid) for uid in package["validation_run_uids"]}
        if package_run_uids != set(runs):
            raise ApprovalError("Review Package validation run set is incomplete")
        for run in runs.values():
            if (
                run["base_commit"] != transaction.base_commit
                or run["configuration_uid"] != package["configuration_uid"]
                or run["effective_model_hash"] != transaction.effective_model_hash
                or run["candidate_hash"] != candidate_hash
                or set(run["finding_uids"]) - set(findings)
            ):
                raise ApprovalError("Validation Run does not bind the reviewed candidate")
        run = next(iter(runs.values()))
        if set(run["finding_uids"]) != set(findings) or any(
            finding["validation_run_uid"] != run["validation_run_uid"]
            for finding in findings.values()
        ):
            raise ApprovalError("Validation Run finding set is incomplete")
        expected_observations, expected_findings, expected_outcome = (
            self._recompute_rule_observations(current_documents, configuration, state_operations)
        )
        recorded_observations = sorted(
            (
                {
                    "rule_uid": str(item["rule_uid"]),
                    "rule_revision_uid": str(item["rule_revision_uid"]),
                    "target_uid": str(item["target_uid"]),
                    "target_revision_uid": item.get("target_revision_uid"),
                    "outcome": str(item["outcome"]),
                    "enforcement": str(item["enforcement"]),
                }
                for run in runs.values()
                for item in run["observations"]
            ),
            key=lambda item: (
                item["rule_revision_uid"],
                str(item["target_revision_uid"]),
            ),
        )
        if recorded_observations != expected_observations:
            raise ApprovalError("Validation Run rule observations are not reproducible")
        recorded_findings = sorted(
            (
                {
                    "rule_uid": str(item["rule_uid"]),
                    "rule_revision_uid": str(item["rule_revision_uid"]),
                    "subject_uid": str(item["subject_uid"]),
                    "subject_revision_uid": item.get("subject_revision_uid"),
                    "outcome": str(item["outcome"]),
                    "enforcement": str(item["enforcement"]),
                    "blocking": bool(item["blocking"]),
                    "status": str(item["status"]),
                    "deviation_revision_uid": item.get("deviation_revision_uid"),
                }
                for item in findings.values()
            ),
            key=lambda item: (
                item["rule_revision_uid"],
                str(item["subject_revision_uid"]),
            ),
        )
        if recorded_findings != expected_findings or run["outcome"] != expected_outcome:
            raise ApprovalError("Validation Run findings or outcome are not reproducible")
        expected_summary = semantic_hash(
            {
                "run": run["content_hash"],
                "findings": [findings[str(uid)]["content_hash"] for uid in run["finding_uids"]],
            }
        )
        if package["validation_summary_hash"] != expected_summary:
            raise ApprovalError("Review Package validation summary hash is invalid")
        open_finding_uids = {
            uid for uid, finding in findings.items() if finding["status"] == "open"
        }
        if set(package["open_finding_uids"]) != open_finding_uids:
            raise ApprovalError("Review Package finding set is incomplete")
        if any(
            finding["blocking"] and finding["status"] == "open" for finding in findings.values()
        ):
            raise ApprovalError("blocking validation findings remain open")
        signed = tuple(
            SignedApproval.model_validate(item.payload)
            for item in transaction.operations
            if item.payload.get("resource_type") == "approval_attestation"
        )
        roles = {item.actor_role for item in signed}
        actors = {item.actor_uid for item in signed}
        if not set(package["required_review_roles"]) <= roles:
            raise ApprovalError("Profile-derived review roles were not approved")
        if len(actors) < int(package["minimum_approval_count"]):
            raise ApprovalError("Review Package approval quorum was not met")
        if package["preparer_independence_required"] and package["prepared_by_actor_uid"] in actors:
            raise ApprovalError("Review Package preparer cannot approve their own package")

    @staticmethod
    def _recompute_rule_observations(
        current_documents: list[dict[str, Any]],
        configuration: dict[str, Any],
        state_operations: tuple[SemanticOperation, ...],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str]:
        profile_uids = {str(uid) for uid in configuration["profile_revision_uids"]}
        profiles = tuple(
            ProfileRevision.model_validate(item)
            for item in current_documents
            if item.get("resource_type") == "profile_revision"
            and item.get("profile_revision_uid") in profile_uids
        )
        rule_uids = {uid for profile in profiles for uid in profile.rule_revision_uids}
        rules = tuple(
            RuleDefinition.model_validate(item)
            for item in current_documents
            if item.get("resource_type") == "rule_definition_revision"
            and item.get("rule_revision_uid") in rule_uids
        )
        model = ProfileCompiler().compile(profiles, rules)
        relation_uids = {str(uid) for uid in configuration["relation_revision_uids"]}
        relations = tuple(
            item
            for item in current_documents
            if item.get("resource_type") == "relation_assertion_revision"
            and item.get("relation_revision_uid") in relation_uids
        ) + tuple(
            item.payload
            for item in state_operations
            if item.payload.get("resource_type") == "relation_assertion_revision"
        )
        candidates = tuple(
            item.payload
            for item in state_operations
            if item.payload.get("resource_type") == "revision"
        )
        conflicted_revisions = {
            uid for conflict in model.conflicts for uid in conflict.split(":")[:2]
        }
        observations: list[dict[str, Any]] = []
        expected_findings: list[dict[str, Any]] = []
        units = UnitRegistry(model.units)
        review_policies = [
            item for item in model.review_policies if item.operation == "apply_transaction"
        ] or [item for item in model.review_policies if item.operation == "*"]
        if len(review_policies) != 1:
            raise ApprovalError(
                "effective Profile must define one review policy for apply_transaction"
            )
        blocking_effects = set(review_policies[0].blocking_effects)
        immutable_record_uids = {
            str(item["record_uid"])
            for item in current_documents
            if item.get("resource_type") == "immutable_record"
        }
        revisions = {
            str(item["revision_uid"]): item
            for item in current_documents
            if item.get("resource_type") == "revision"
        }
        for revision in candidates:
            fields: dict[str, ValueCell] = {}
            for field in revision.get("fields", []):
                if not isinstance(field, dict) or not isinstance(field.get("path"), str):
                    continue
                value = field.get("value")
                if isinstance(value, dict) and set(value) == {"decimal", "unit"}:
                    value = Quantity(Decimal(str(value["decimal"])), str(value["unit"]))
                fields[str(field["path"])] = ValueCell.present(value)
            object_uid = str(revision["object_uid"])
            counts: dict[str, int] = {}
            for relation in relations:
                source = relation.get("source", {})
                target = relation.get("target", {})
                if not isinstance(source, dict) or not isinstance(target, dict):
                    continue
                if object_uid in {
                    str(source.get("object_uid", "")),
                    str(target.get("object_uid", "")),
                }:
                    predicate = str(relation["predicate"])
                    counts[predicate] = counts.get(predicate, 0) + 1
            active_deviations: dict[str, str] = {}
            for deviation_uid in configuration["active_deviation_revision_uids"]:
                deviation = revisions.get(str(deviation_uid))
                if deviation is None or deviation.get("kind") != "deviation":
                    raise ApprovalError(
                        f"active deviation is not a deviation revision: {deviation_uid}"
                    )
                deviation_fields = {
                    str(item["path"]): item.get("value")
                    for item in deviation.get("fields", [])
                    if isinstance(item, dict) and isinstance(item.get("path"), str)
                }
                if (
                    str(deviation_fields.get("/approval_record_uid", ""))
                    not in immutable_record_uids
                ):
                    raise ApprovalError(
                        f"active deviation has no canonical approval record: {deviation_uid}"
                    )
                valid_until = deviation_fields.get("/valid_until")
                if not isinstance(valid_until, str) or datetime.fromisoformat(
                    valid_until
                ) <= datetime.now(UTC):
                    raise ApprovalError(
                        f"active deviation is expired or has no validity: {deviation_uid}"
                    )
                if str(deviation_fields.get("/subject_uid", "")) not in {
                    object_uid,
                    str(revision["revision_uid"]),
                }:
                    continue
                deviation_rule_revision_uid = str(deviation_fields.get("/rule_revision_uid", ""))
                deviation_rule = next(
                    (
                        item
                        for item in model.rules
                        if item.rule_revision_uid == deviation_rule_revision_uid
                    ),
                    None,
                )
                if deviation_rule is None or not deviation_rule.deviation_allowed:
                    raise ApprovalError(
                        f"deviation does not reference a relaxable effective rule: {deviation_uid}"
                    )
                active_deviations[deviation_rule.rule_uid] = str(deviation_uid)
            environment = EvaluationEnvironment(
                target_kind=str(revision["kind"]),
                fields=fields,
                relation_counts=counts,
                operation="apply_transaction",
                active_deviation_rule_uids=frozenset(active_deviations),
                conflicted_rule_uids=frozenset(
                    item.rule_uid
                    for item in model.rules
                    if item.rule_revision_uid in conflicted_revisions
                ),
            )
            for rule in model.rules:
                if rule.target_kind != environment.target_kind:
                    continue
                evaluated = evaluate_rule(rule, environment, units)
                observations.append(
                    {
                        "rule_uid": rule.rule_uid,
                        "rule_revision_uid": rule.rule_revision_uid,
                        "target_uid": object_uid,
                        "target_revision_uid": str(revision["revision_uid"]),
                        "outcome": evaluated.outcome.value,
                        "enforcement": evaluated.enforcement.value,
                    }
                )
                if evaluated.outcome in {RuleOutcome.PASS, RuleOutcome.NOT_APPLICABLE}:
                    continue
                suppressed = evaluated.outcome is RuleOutcome.SUPPRESSED_BY_DEVIATION
                blocking = (
                    False
                    if suppressed
                    else (
                        evaluated.enforcement.value in blocking_effects
                        or (
                            evaluated.outcome
                            in {
                                RuleOutcome.INDETERMINATE,
                                RuleOutcome.EVALUATOR_ERROR,
                                RuleOutcome.NOT_EVALUATED,
                            }
                            and evaluated.enforcement
                            not in {
                                EnforcementEffect.ALLOW,
                                EnforcementEffect.ALLOW_WITH_OBSERVATION,
                            }
                        )
                    )
                )
                expected_findings.append(
                    {
                        "rule_uid": rule.rule_uid,
                        "rule_revision_uid": rule.rule_revision_uid,
                        "subject_uid": object_uid,
                        "subject_revision_uid": str(revision["revision_uid"]),
                        "outcome": evaluated.outcome.value,
                        "enforcement": evaluated.enforcement.value,
                        "blocking": blocking,
                        "status": "suppressed_by_deviation" if suppressed else "open",
                        "deviation_revision_uid": (
                            active_deviations[rule.rule_uid] if suppressed else None
                        ),
                    }
                )
        observation_key = lambda item: (
            item["rule_revision_uid"],
            str(item["target_revision_uid"]),
        )
        finding_key = lambda item: (
            item["rule_revision_uid"],
            str(item["subject_revision_uid"]),
        )
        outcome = (
            "fail"
            if any(item["blocking"] for item in expected_findings)
            else "indeterminate"
            if expected_findings
            else "pass"
        )
        return (
            sorted(observations, key=observation_key),
            sorted(expected_findings, key=finding_key),
            outcome,
        )

    def _authorize_transaction(self, current: str, transaction: SemanticTransaction) -> None:
        """Enforce trust at the transaction boundary, including one-time bootstrap."""
        current_documents = [value for _, value in self.documents(current)]
        current_trust = [
            value for value in current_documents if value.get("resource_type") == "trusted_actor"
        ]
        staged_trust = [
            item.payload
            for item in transaction.operations
            if item.payload.get("resource_type") == "trusted_actor"
        ]
        staged_delegations = [
            item.payload
            for item in transaction.operations
            if item.payload.get("resource_type") == "delegation_grant"
        ]
        staged_approvals = [
            item.payload
            for item in transaction.operations
            if item.payload.get("resource_type") == "approval_attestation"
        ]
        bootstrap = not current_trust
        if bootstrap:
            if len(staged_trust) != 1 or len(staged_delegations) != 1:
                raise ApprovalError(
                    "initial transaction must explicitly bootstrap one root trust and delegation"
                )
            allowed_bootstrap_types = {
                "trusted_actor",
                "delegation_grant",
                "approval_attestation",
                "rule_definition_revision",
                "profile_revision",
                "normative_profile_revision",
                "facet_definition_revision",
                "kind_definition_revision",
                "relation_type_revision",
                "workflow_revision",
                "provenance_record",
            }
            if any(
                item.payload.get("resource_type") not in allowed_bootstrap_types
                for item in transaction.operations
            ):
                raise ApprovalError("bootstrap transaction contains a forbidden resource type")
            trust_documents = staged_trust
            delegation_document = staged_delegations[0]
        else:
            trust_documents = current_trust
            matching = [
                value
                for value in current_documents
                if value.get("resource_type") == "delegation_grant"
                and value.get("delegation_uid") == transaction.delegation_uid
            ]
            if len(matching) != 1:
                raise ApprovalError("transaction delegation is not in Canonical State")
            delegation_document = matching[0]
        now = datetime.now(UTC)
        if (
            delegation_document.get("principal_uid") != transaction.actor
            or delegation_document.get("delegation_uid") != transaction.delegation_uid
            or not self.is_ancestor(
                str(delegation_document.get("base_commit")), transaction.base_commit
            )
            or "apply_transaction" not in delegation_document.get("operations", [])
            or now < datetime.fromisoformat(str(delegation_document["issued_at"]))
            or now >= datetime.fromisoformat(str(delegation_document["expires_at"]))
            or delegation_document.get("stop_conditions")
        ):
            raise ApprovalError("delegation does not authorize this semantic transaction")
        issuers = {str(value.get("actor_uid")) for value in trust_documents}
        if str(delegation_document.get("issued_by")) not in issuers:
            raise ApprovalError("delegation issuer is not trusted")
        signed = tuple(SignedApproval.model_validate(value) for value in staged_approvals)
        if {item.approval_uid for item in signed} != {
            item.approval_uid for item in transaction.approvals
        }:
            raise ApprovalError("signed approval resources do not match transaction attestations")
        for approval in signed:
            trust_value = next(
                (
                    value
                    for value in trust_documents
                    if value.get("actor_uid") == approval.actor_uid
                    and value.get("key_uid") == approval.key_uid
                ),
                None,
            )
            if trust_value is None:
                raise ApprovalError("approval key is not trusted by Canonical State")
            try:
                verify_approval(
                    approval,
                    TrustedActor.model_validate(trust_value),
                    package_hash=transaction.review_package_hash,
                    effective_model_hash=transaction.effective_model_hash,
                )
            except (PermissionError, ValueError) as error:
                raise ApprovalError(str(error)) from error

    def create_checkpoint(
        self,
        workspace_uid: str,
        payload: dict[str, Any],
        strategy: CheckpointStrategy,
    ) -> CheckpointResult:
        workspace = self._safe_component(workspace_uid)
        checkpoint_uid = uuid7_candidate()
        if strategy is CheckpointStrategy.COMMIT_PER_CHECKPOINT:
            parent = self.current_commit()
            reference = f"refs/lesr/checkpoints/{workspace}/{checkpoint_uid}"
        else:
            reference = f"refs/lesr/workspaces/{workspace}"
            parent = self._try_git("rev-parse", "--verify", reference) or self.current_commit()
        index_path = self.path / f".lesr-index-{checkpoint_uid}.tmp"
        index_path.unlink(missing_ok=True)
        env = {"GIT_INDEX_FILE": str(index_path)}
        try:
            self._git("read-tree", parent, extra_env=env)
            checkpoint_path = f"workspaces/{workspace}/checkpoints/{checkpoint_uid}.json"
            self._stage_json(
                checkpoint_path,
                {
                    "checkpoint_uid": checkpoint_uid,
                    "workspace_uid": workspace_uid,
                    "base_commit": self.current_commit(),
                    "working_state": payload,
                },
                env,
            )
            tree = self._git("write-tree", extra_env=env)
            commit = self._commit_tree(tree, (parent,), f"Checkpoint {checkpoint_uid}")
            expected = parent if self._try_git("rev-parse", "--verify", reference) else None
            if expected is None:
                self._git("update-ref", reference, commit)
            else:
                self._git("update-ref", reference, commit, expected)
        finally:
            index_path.unlink(missing_ok=True)
        return CheckpointResult(checkpoint_uid, commit, reference, strategy)

    def rebuild_projection(self, database: Path) -> str:
        source_commit = self.current_commit()
        database.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(database) as connection:
            connection.executescript(
                "DROP TABLE IF EXISTS projection_meta;"
                "DROP TABLE IF EXISTS documents;"
                "DROP TABLE IF EXISTS documents_fts;"
                "DROP TABLE IF EXISTS resources;"
                "DROP TABLE IF EXISTS aliases;"
                "DROP TABLE IF EXISTS relations;"
                "CREATE TABLE projection_meta (source_commit TEXT NOT NULL, "
                "schema_version TEXT NOT NULL, completeness TEXT NOT NULL);"
                "CREATE TABLE documents (path TEXT PRIMARY KEY, json TEXT NOT NULL, "
                "source_commit TEXT NOT NULL);"
                "CREATE VIRTUAL TABLE documents_fts USING fts5(path UNINDEXED, content);"
                "CREATE TABLE resources (uid TEXT NOT NULL, resource_type TEXT NOT NULL, "
                "object_uid TEXT, human_key TEXT, kind TEXT, revision_number INTEGER, path TEXT PRIMARY KEY, json TEXT NOT NULL);"
                "CREATE INDEX resources_uid_idx ON resources(uid);"
                "CREATE TABLE aliases (alias TEXT NOT NULL, uid TEXT NOT NULL, UNIQUE(alias, uid));"
                "CREATE TABLE relations (relation_revision_uid TEXT PRIMARY KEY, assertion_uid TEXT NOT NULL, "
                "predicate TEXT NOT NULL, source_object_uid TEXT, target_object_uid TEXT, path TEXT NOT NULL);"
            )
            rows: list[tuple[str, str, str]] = []
            resource_rows: list[tuple[object, ...]] = []
            alias_rows: list[tuple[str, str]] = []
            relation_rows: list[tuple[object, ...]] = []
            for path, blob in self._tree_entries(source_commit):
                if not path.startswith("canonical/"):
                    continue
                if not path.endswith(".json"):
                    continue
                content = self._read_blob(blob)
                rows.append((path, content.decode("utf-8"), source_commit))
                document = json.loads(content)
                if not isinstance(document, dict) or "resource_type" not in document:
                    continue
                uid = self._document_uid(document)
                if uid is not None:
                    resource_rows.append(
                        (
                            uid,
                            str(document["resource_type"]),
                            document.get("object_uid"),
                            document.get("human_key"),
                            document.get("kind"),
                            document.get("revision_number"),
                            path,
                            content.decode("utf-8"),
                        )
                    )
                if document.get("resource_type") == "logical_object" and uid is not None:
                    alias_rows.extend(
                        (str(alias["value"]), uid)
                        for alias in document.get("aliases", [])
                        if isinstance(alias, dict) and isinstance(alias.get("value"), str)
                    )
                if document.get("resource_type") == "relation_assertion_revision":
                    source = document.get("source", {})
                    target = document.get("target", {})
                    relation_rows.append(
                        (
                            document["relation_revision_uid"],
                            document["assertion_uid"],
                            document["predicate"],
                            source.get("object_uid") if isinstance(source, dict) else None,
                            target.get("object_uid") if isinstance(target, dict) else None,
                            path,
                        )
                    )
            connection.executemany("INSERT INTO documents VALUES (?, ?, ?)", rows)
            connection.executemany(
                "INSERT INTO resources VALUES (?, ?, ?, ?, ?, ?, ?, ?)", resource_rows
            )
            connection.executemany("INSERT INTO aliases VALUES (?, ?)", alias_rows)
            connection.executemany("INSERT INTO relations VALUES (?, ?, ?, ?, ?, ?)", relation_rows)
            connection.executemany(
                "INSERT INTO documents_fts VALUES (?, ?)",
                ((path, content) for path, content, _ in rows),
            )
            connection.execute(
                "INSERT INTO projection_meta VALUES (?, '1.0', 'complete')",
                (source_commit,),
            )
        return source_commit

    def query_projection(
        self,
        database: Path,
        *,
        kind: str | None,
        text: str | None,
        offset: int,
        page_size: int,
    ) -> tuple[tuple[dict[str, Any], ...], int]:
        """Query the disposable SQLite/FTS projection at the exact canonical commit."""

        source_commit = self.current_commit()
        rebuild = not database.exists()
        if not rebuild:
            try:
                with sqlite3.connect(database) as connection:
                    row = connection.execute(
                        "SELECT source_commit, schema_version, completeness FROM projection_meta"
                    ).fetchone()
                rebuild = row != (source_commit, "1.0", "complete")
            except sqlite3.Error:
                rebuild = True
        if rebuild:
            self.rebuild_projection(database)
        clauses: list[str] = []
        parameters: list[object] = []
        join = ""
        if kind:
            clauses.append("resources.kind = ?")
            parameters.append(kind)
        if text:
            join = " JOIN documents_fts ON documents_fts.path = resources.path"
            clauses.append("documents_fts MATCH ?")
            parameters.append('"' + text.replace('"', '""') + '"')
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        with sqlite3.connect(database) as connection:
            total = int(
                connection.execute(
                    f"SELECT COUNT(*) FROM resources{join}{where}",
                    parameters,
                ).fetchone()[0]
            )
            rows = connection.execute(
                f"SELECT resources.json FROM resources{join}{where} "
                "ORDER BY resources.uid, resources.path LIMIT ? OFFSET ?",
                (*parameters, page_size, offset),
            ).fetchall()
        return tuple(json.loads(str(row[0])) for row in rows), total

    def read_json(self, commit: str, path: str) -> dict[str, Any] | None:
        content = self.read_bytes(commit, path)
        if content is None:
            return None
        value = json.loads(content)
        if not isinstance(value, dict):
            raise IntegrityError(f"expected JSON object at {path}")
        return value

    def documents(self, commit: str | None = None) -> tuple[tuple[str, dict[str, Any]], ...]:
        """Read every Canonical JSON document from one exact commit."""
        selected = commit or self.current_commit()
        documents: list[tuple[str, dict[str, Any]]] = []
        for path, blob in self._tree_entries(selected):
            if path.startswith("canonical/") and path.endswith(".json"):
                value = json.loads(self._read_blob(blob))
                if not isinstance(value, dict):
                    raise IntegrityError(f"expected JSON object at {path}")
                documents.append((path, value))
        return tuple(documents)

    def read_bytes(self, commit: str, path: str) -> bytes | None:
        normalized = PurePosixPath(path).as_posix()
        blob = next(
            (blob for actual, blob in self._tree_entries(commit) if actual == normalized),
            None,
        )
        return self._read_blob(blob) if blob is not None else None

    def checkpoint_payload(self, checkpoint: CheckpointResult) -> dict[str, Any]:
        actual = next(
            path
            for path, _ in self._tree_entries(checkpoint.commit)
            if path.startswith("workspaces/")
            and path.endswith(f"/{checkpoint.checkpoint_uid}.json")
        )
        value = self.read_json(checkpoint.commit, actual)
        if value is None:
            raise IntegrityError("checkpoint payload is missing")
        return value

    def recover_workspaces(self) -> tuple[dict[str, Any], ...]:
        """Recover the newest checkpoint for every persistent workspace ref."""
        refs = self._try_git(
            "for-each-ref", "--format=%(refname) %(objectname)", "refs/lesr/workspaces/"
        )
        if not refs:
            return ()
        recovered: list[dict[str, Any]] = []
        for line in refs.splitlines():
            reference, commit = line.split(" ", 1)
            candidates = [
                path
                for path, _ in self._tree_entries(commit)
                if path.startswith("workspaces/") and "/checkpoints/" in path
            ]
            if not candidates:
                continue
            changed = {
                item
                for item in self._git(
                    "diff-tree", "--no-commit-id", "--name-only", "-r", commit
                ).splitlines()
                if item
            }
            newest = [item for item in candidates if item in changed]
            latest = newest[0] if len(newest) == 1 else max(candidates)
            payload = self.read_json(commit, latest)
            if payload is not None:
                recovered.append(payload | {"git_reference": reference})
        return tuple(recovered)

    def verify_audit_chain(self, commit: str | None = None) -> bool:
        anchors = [
            value
            for path, value in self.documents(commit or self.current_commit())
            if path.startswith("canonical/audit_anchors/")
        ]
        by_previous: dict[str | None, list[dict[str, Any]]] = {}
        for anchor in anchors:
            anchor_previous = anchor.get("previous_anchor_hash")
            key = str(anchor_previous) if anchor_previous is not None else None
            by_previous.setdefault(key, []).append(anchor)
        previous: str | None = None
        visited = 0
        while visited < len(anchors):
            candidates = by_previous.get(previous, [])
            if len(candidates) != 1:
                return False
            anchor = candidates[0]
            if anchor.get("anchor_hash") != document_hash(anchor, "anchor_hash"):
                return False
            previous = str(anchor["anchor_hash"])
            visited += 1
        return visited == len(anchors)

    @staticmethod
    def requires_reconciliation(changed_paths: tuple[str, ...]) -> bool:
        return any(path.replace("\\", "/").startswith("canonical/") for path in changed_paths)

    def _verify_expected_revisions(
        self, commit: str, expected_revisions: tuple[tuple[str, str], ...]
    ) -> None:
        for revision_uid, expected_hash in expected_revisions:
            path = f"canonical/revisions/{self._safe_component(revision_uid)}.json"
            revision = self.read_json(commit, path)
            if revision is None or revision.get("content_hash") != expected_hash:
                raise ConcurrencyConflict(f"expected revision changed or missing: {revision_uid}")

    def _validate_operation(self, operation: SemanticOperation) -> None:
        resource_type = operation.payload.get("resource_type")
        if not isinstance(resource_type, str):
            raise IntegrityError("semantic operation payload has no resource_type")
        allowed = _OPERATION_RESOURCE_TYPES.get(operation.operation_type, frozenset())
        if resource_type not in allowed:
            raise IntegrityError(f"{operation.operation_type} cannot create {resource_type}")
        schema_name = _RESOURCE_SCHEMAS.get(resource_type)
        if schema_name is None:
            raise IntegrityError(f"unsupported canonical resource type: {resource_type}")
        try:
            self.schemas.validate(schema_name, operation.payload)
        except JsonSchemaValidationError as error:
            raise IntegrityError(f"canonical schema validation failed: {error.message}") from error
        hash_field = {
            "baseline_manifest": "manifest_hash",
            "review_package": "package_hash",
        }.get(resource_type, "content_hash")
        if hash_field in operation.payload:
            expected_hash = document_hash(operation.payload, hash_field)
            if operation.payload[hash_field] != expected_hash:
                raise IntegrityError(f"canonical {hash_field} does not match document content")
        expected_path = self._resource_path(operation.payload)
        if self._safe_path(operation.relative_path) != expected_path:
            raise IntegrityError(
                f"canonical path does not match resource identity: expected {expected_path}"
            )

    def _validate_candidate(self, commit: str, operations: tuple[SemanticOperation, ...]) -> None:
        documents = {path: value for path, value in self.documents(commit)}
        documents.update((operation.relative_path, operation.payload) for operation in operations)
        operation_approval_provenance = {
            str(operation.payload["provenance_uid"])
            for operation in operations
            if operation.payload.get("resource_type") == "provenance_record"
        }
        for operation in operations:
            if (
                operation.payload.get("resource_type") == "approval_attestation"
                and str(operation.payload["provenance_uid"])
                not in operation_approval_provenance
            ):
                raise IntegrityError("transaction omits approval provenance record")
        object_documents = {
            str(value["entity_uid"]): value
            for value in documents.values()
            if value.get("resource_type") == "logical_object"
        }
        objects = set(object_documents)
        revision_documents = {
            str(value["revision_uid"]): value
            for value in documents.values()
            if value.get("resource_type") == "revision"
        }
        revisions = {uid: str(value["object_uid"]) for uid, value in revision_documents.items()}
        relation_documents = {
            str(value["relation_revision_uid"]): value
            for value in documents.values()
            if value.get("resource_type") == "relation_assertion_revision"
        }
        relation_revisions = set(relation_documents)
        record_documents = {
            str(value["record_uid"]): value
            for value in documents.values()
            if value.get("resource_type") == "immutable_record"
        }
        profile_documents = {
            str(value["profile_revision_uid"]): value
            for value in documents.values()
            if value.get("resource_type")
            in {"profile_revision", "normative_profile_revision"}
        }
        profiles = set(profile_documents)
        rule_documents = {
            str(value["rule_revision_uid"]): value
            for value in documents.values()
            if value.get("resource_type") == "rule_definition_revision"
        }
        rules = set(rule_documents)
        configurations = {
            str(value["configuration_uid"])
            for value in documents.values()
            if value.get("resource_type") == "configuration_snapshot"
        }
        validation_runs = {
            str(value["validation_run_uid"])
            for value in documents.values()
            if value.get("resource_type") == "validation_run"
        }
        findings = {
            str(value["finding_uid"])
            for value in documents.values()
            if value.get("resource_type") == "validation_finding"
        }
        provenance_uids = {
            str(value["provenance_uid"])
            for value in documents.values()
            if value.get("resource_type") == "provenance_record"
        }
        human_keys: dict[tuple[str, str], str] = {}
        unqualified_human_keys: dict[str, set[str]] = {}
        aliases: dict[str, str] = {}
        for object_uid, value in object_documents.items():
            key = (str(value["namespace"]), str(value["human_key"]))
            previous = human_keys.setdefault(key, object_uid)
            if previous != object_uid:
                raise IntegrityError("human key is not unique inside its namespace")
            unqualified_human_keys.setdefault(str(value["human_key"]), set()).add(object_uid)
            for alias in value.get("aliases", []):
                if not isinstance(alias, dict) or not isinstance(alias.get("value"), str):
                    continue
                alias_value = str(alias["value"])
                previous_alias = aliases.setdefault(alias_value, object_uid)
                if previous_alias != object_uid:
                    raise IntegrityError(f"alias is ambiguous: {alias_value}")
        for alias_value, object_uid in aliases.items():
            if unqualified_human_keys.get(alias_value, {object_uid}) != {object_uid}:
                raise IntegrityError(f"alias conflicts with a Human Key: {alias_value}")
        revision_numbers: set[tuple[str, int]] = set()
        for revision_uid, value in revision_documents.items():
            number_key = (str(value["object_uid"]), int(value["revision_number"]))
            if number_key in revision_numbers:
                raise IntegrityError("revision number is not unique for its logical object")
            revision_numbers.add(number_key)
            parent_uid = value.get("parent_revision_uid")
            if parent_uid is None:
                if value["revision_number"] != 1:
                    raise IntegrityError("root revision number must be one")
                continue
            parent = revision_documents.get(str(parent_uid))
            if (
                parent is None
                or parent["object_uid"] != value["object_uid"]
                or int(parent["revision_number"]) >= int(value["revision_number"])
            ):
                raise IntegrityError(f"revision parent lineage is invalid: {revision_uid}")
        relation_numbers: set[tuple[str, int]] = set()
        for relation_uid, value in relation_documents.items():
            number_key = (str(value["assertion_uid"]), int(value["revision_number"]))
            if number_key in relation_numbers:
                raise IntegrityError("relation revision number is not unique")
            relation_numbers.add(number_key)
            parent_uid = value.get("parent_relation_revision_uid")
            if parent_uid is None:
                if value["revision_number"] != 1:
                    raise IntegrityError("root relation revision number must be one")
                continue
            parent = relation_documents.get(str(parent_uid))
            if (
                parent is None
                or parent["assertion_uid"] != value["assertion_uid"]
                or int(parent["revision_number"]) >= int(value["revision_number"])
            ):
                raise IntegrityError(f"relation parent lineage is invalid: {relation_uid}")
        subject_uids = objects | set(revisions) | relation_revisions | set(configurations)
        for record_uid, value in record_documents.items():
            if str(value["subject_uid"]) not in subject_uids:
                raise IntegrityError(f"immutable record subject is unavailable: {record_uid}")
            supersedes = value.get("supersedes_record_uid")
            if supersedes is not None and str(supersedes) not in record_documents:
                raise IntegrityError(f"superseded immutable record is unavailable: {record_uid}")
        trusted_actor_uids = {
            str(value["actor_uid"])
            for value in documents.values()
            if value.get("resource_type") == "trusted_actor"
        }
        for value in documents.values():
            if value.get("resource_type") == "trusted_actor":
                revoked = value.get("revoked_by_record_uid")
                if revoked is not None and str(revoked) not in record_documents:
                    raise IntegrityError("trusted actor revocation record is unavailable")
            if (
                value.get("resource_type") == "delegation_grant"
                and str(value["issued_by"]) not in trusted_actor_uids
            ):
                raise IntegrityError("delegation issuer is not a trusted actor")
            if (
                value.get("resource_type") == "approval_attestation"
                and str(value["provenance_uid"]) not in provenance_uids
            ):
                raise IntegrityError(
                    "approval provenance is unavailable: "
                    f"{value['provenance_uid']} not in {sorted(provenance_uids)}; "
                    f"transaction provided {sorted(operation_approval_provenance)}"
                )
        for path, value in documents.items():
            resource_type = value.get("resource_type")
            if resource_type is None:
                if not path.startswith("canonical/idempotency/"):
                    raise IntegrityError(f"canonical document has no resource_type: {path}")
                continue
            schema_name = _RESOURCE_SCHEMAS.get(str(resource_type))
            if schema_name is None:
                raise IntegrityError(f"unsupported canonical resource type: {resource_type}")
            try:
                self.schemas.validate(schema_name, value)
            except JsonSchemaValidationError as error:
                raise IntegrityError(
                    f"canonical candidate contains invalid {path}: {error.message}"
                ) from error
            hash_field = {
                "baseline_manifest": "manifest_hash",
                "audit_anchor": "anchor_hash",
                "review_package": "package_hash",
            }.get(str(resource_type), "content_hash")
            if hash_field in value and value[hash_field] != document_hash(value, hash_field):
                raise IntegrityError(f"canonical candidate contains invalid hash: {path}")
            if resource_type == "revision" and value["object_uid"] not in objects:
                raise IntegrityError(f"revision references missing object: {value['object_uid']}")
            if resource_type == "relation_assertion_revision":
                for endpoint_name in ("source", "target"):
                    endpoint = value[endpoint_name]
                    if endpoint["binding"] != "external" and endpoint["object_uid"] not in objects:
                        raise IntegrityError(
                            f"relation {endpoint_name} references missing object: {endpoint['object_uid']}"
                        )
                    pinned = endpoint.get("revision_uid")
                    if pinned is not None and revisions.get(pinned) != endpoint.get("object_uid"):
                        raise IntegrityError(
                            f"relation {endpoint_name} references incompatible revision: {pinned}"
                        )
            if resource_type in {"configuration_snapshot", "baseline_manifest"}:
                missing_revisions = set(value.get("revision_uids", [])) - set(revisions)
                missing_relations = (
                    set(value.get("relation_revision_uids", [])) - relation_revisions
                )
                missing_profiles = set(value.get("profile_revision_uids", [])) - profiles
                if missing_revisions or missing_relations or missing_profiles:
                    raise IntegrityError(
                        "snapshot closure references unavailable canonical revisions"
                    )
                missing_deviations = set(
                    value.get("active_deviation_revision_uids", [])
                    or value.get("deviation_revision_uids", [])
                ) - set(revisions)
                if missing_deviations:
                    raise IntegrityError("snapshot references unavailable deviations")
            if resource_type in {"profile_revision", "normative_profile_revision"}:
                missing_rules = set(value.get("rule_revision_uids", [])) - rules
                if missing_rules:
                    raise IntegrityError("profile references unavailable rule revisions")
            if resource_type == "configuration_snapshot":
                try:
                    selected_documents = tuple(
                        profile_documents[str(uid)]
                        for uid in value["profile_revision_uids"]
                    )
                    if all(
                        item.get("resource_type") == "profile_revision"
                        for item in selected_documents
                    ):
                        legacy_profiles = tuple(
                            ProfileRevision.model_validate(item)
                            for item in selected_documents
                        )
                        referenced_rules = {
                            uid
                            for profile in legacy_profiles
                            for uid in profile.rule_revision_uids
                        }
                        selected_rules = tuple(
                            RuleDefinition.model_validate(rule_documents[uid])
                            for uid in referenced_rules
                        )
                        legacy_effective = ProfileCompiler().compile(
                            legacy_profiles, selected_rules
                        )
                        effective_hash = legacy_effective.effective_model_hash
                        has_conflicts = bool(legacy_effective.conflicts)
                    else:
                        selected_profiles = tuple(
                            NormativeProfileRevision.model_validate(item)
                            for item in selected_documents
                        )
                        referenced_rules = {
                            uid
                            for profile in selected_profiles
                            for uid in profile.rule_revision_uids
                        }
                        if referenced_rules - rules:
                            raise ValueError("Profile references unavailable Rule revisions")
                        definitions = tuple(
                            _definition_revision(document)
                            for document in documents.values()
                            if document.get("resource_type")
                            in {
                                "facet_definition_revision",
                                "kind_definition_revision",
                                "relation_type_revision",
                                "workflow_revision",
                            }
                        )
                        overlays = tuple(
                            TailoringOverlay.model_validate(document)
                            for document in documents.values()
                            if document.get("resource_type") == "tailoring_overlay"
                            and document.get("configuration_uid")
                            == value["configuration_uid"]
                        )
                        effective = EffectiveModelCompiler().compile(
                            selected_profiles,
                            definitions,
                            overlays=overlays,
                            deviation_revision_uids=tuple(
                                str(item)
                                for item in value["active_deviation_revision_uids"]
                            ),
                        )
                        effective_hash = effective.model_hash
                        has_conflicts = bool(effective.conflicts)
                except (TypeError, ValueError) as error:
                    raise IntegrityError(
                        f"configuration Effective Model is invalid: {error}"
                    ) from error
                if has_conflicts or effective_hash != value["effective_model_hash"]:
                    raise IntegrityError("configuration Effective Model hash is stale")
                for deviation_uid in value["active_deviation_revision_uids"]:
                    if revision_documents[str(deviation_uid)].get("kind") != "deviation":
                        raise IntegrityError("active deviation is not a deviation revision")
            if (
                resource_type == "baseline_manifest"
                and value["configuration_uid"] not in configurations
            ):
                raise IntegrityError("baseline references unavailable configuration")
            if (
                resource_type == "validation_finding"
                and value["validation_run_uid"] not in validation_runs
            ):
                raise IntegrityError("validation finding references unavailable validation run")
            if resource_type == "validation_run":
                if value["configuration_uid"] not in configurations:
                    raise IntegrityError("validation run references unavailable configuration")
                if set(value["finding_uids"]) - findings:
                    raise IntegrityError("validation run references unavailable findings")
            if resource_type == "review_package":
                if value["configuration_uid"] not in configurations:
                    raise IntegrityError("review package references unavailable configuration")
                if set(value.get("validation_run_uids", ())) - validation_runs:
                    raise IntegrityError("review package references unavailable validation runs")
                if set(value.get("open_finding_uids", ())) - findings:
                    raise IntegrityError("review package references unavailable findings")

    @staticmethod
    def _document_uid(document: dict[str, Any]) -> str | None:
        for name in (
            "entity_uid",
            "revision_uid",
            "relation_revision_uid",
            "record_uid",
            "profile_revision_uid",
            "configuration_uid",
            "baseline_uid",
            "actor_uid",
            "delegation_uid",
            "transaction_uid",
            "provenance_uid",
            "anchor_uid",
            "validation_run_uid",
            "finding_uid",
            "package_uid",
            "diff_uid",
            "snapshot_uid",
            "bundle_uid",
            "report_uid",
        ):
            value = document.get(name)
            if isinstance(value, str):
                return value
        return None

    @staticmethod
    def _resource_path(resource: dict[str, Any]) -> str:
        resource_type = resource["resource_type"]
        mapping = {
            "logical_object": f"canonical/objects/{resource.get('entity_uid')}.json",
            "revision": f"canonical/revisions/{resource.get('revision_uid')}.json",
            "immutable_record": f"canonical/records/{resource.get('record_type')}/{resource.get('record_uid')}.json",
            "profile_revision": f"canonical/profiles/{resource.get('profile_revision_uid')}.json",
            "normative_profile_revision": f"canonical/profiles/{resource.get('profile_revision_uid')}.json",
            "facet_definition_revision": f"canonical/definitions/{resource.get('revision_uid')}.json",
            "kind_definition_revision": f"canonical/definitions/{resource.get('revision_uid')}.json",
            "relation_type_revision": f"canonical/definitions/{resource.get('revision_uid')}.json",
            "workflow_revision": f"canonical/definitions/{resource.get('revision_uid')}.json",
            "configuration_snapshot": f"canonical/configurations/{resource.get('configuration_uid')}.json",
            "baseline_manifest": f"canonical/baselines/{resource.get('baseline_uid')}.json",
            "trusted_actor": f"canonical/trust/{resource.get('actor_uid')}/{resource.get('key_uid')}.json",
            "delegation_grant": f"canonical/delegations/{resource.get('delegation_uid')}.json",
            "approval_attestation": f"canonical/approvals/{resource.get('approval_uid')}.json",
            "rule_definition_revision": f"canonical/rules/{resource.get('rule_revision_uid')}.json",
            "validation_run": f"canonical/validation/runs/{resource.get('validation_run_uid')}.json",
            "validation_finding": f"canonical/validation/findings/{resource.get('finding_uid')}.json",
            "review_package": f"canonical/review_packages/{resource.get('package_uid')}.json",
            "baseline_preparation": f"canonical/baseline_preparations/{resource.get('preparation_uid')}.json",
            "provenance_record": f"canonical/provenance/{resource.get('provenance_uid')}.json",
            "semantic_diff": f"canonical/semantic_diffs/{resource.get('diff_uid')}.json",
            "graph_snapshot": f"canonical/graph_snapshots/{resource.get('snapshot_uid')}.json",
            "context_bundle": f"canonical/context_bundles/{resource.get('bundle_uid')}.json",
            "impact_report": f"canonical/impact_reports/{resource.get('report_uid')}.json",
        }
        if resource_type == "relation_assertion_revision":
            return (
                f"canonical/relations/{resource['assertion_uid']}/revisions/"
                f"{resource['relation_revision_uid']}.json"
            )
        try:
            return GitCanonicalRepository._safe_path(mapping[resource_type])
        except KeyError as error:
            raise IntegrityError(f"unsupported canonical resource type: {resource_type}") from error

    @staticmethod
    def _validate_transaction(transaction: SemanticTransaction) -> None:
        identifiers = {
            "transaction_uid": transaction.transaction_uid,
            "actor": transaction.actor,
            "delegation_uid": transaction.delegation_uid,
        }
        identifiers.update(
            {
                f"approval[{index}]": item.approval_uid
                for index, item in enumerate(transaction.approvals)
            }
        )
        for name, value in identifiers.items():
            if not re.fullmatch(
                r"[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}",
                value,
            ):
                raise IntegrityError(f"{name} must be a UUIDv7")
        for name, value in (
            ("effective_model_hash", transaction.effective_model_hash),
            ("review_package_hash", transaction.review_package_hash),
        ):
            if not re.fullmatch(r"sha256:[0-9a-f]{64}", value):
                raise IntegrityError(f"{name} must be a SHA-256 digest")
        if not transaction.operations:
            raise IntegrityError("a semantic transaction requires at least one operation")
        if not transaction.approvals:
            raise ApprovalError("a semantic transaction requires an approval attestation")
        for approval in transaction.approvals:
            if approval.package_hash != transaction.review_package_hash:
                raise ApprovalError("approval does not bind the review package hash")
            if approval.actor_type.casefold() == "ai":
                raise ApprovalError("AI cannot provide formal approval")
        if not transaction.delegation_uid:
            raise IntegrityError("delegation is required")

    @staticmethod
    def _change_record(
        transaction: SemanticTransaction,
        transaction_hash: str,
        idempotency_hash: str,
        applied_at: str,
    ) -> dict[str, Any]:
        return {
            "schema_version": "1.0",
            "resource_type": "applied_change",
            "transaction_uid": transaction.transaction_uid,
            "transaction_hash": transaction_hash,
            "base_commit": transaction.base_commit,
            "expected_revisions": [
                {"revision_uid": revision_uid, "content_hash": content_hash}
                for revision_uid, content_hash in transaction.expected_revisions
            ],
            "effective_model_hash": transaction.effective_model_hash,
            "review_package_hash": transaction.review_package_hash,
            "operation_hashes": [
                semantic_hash(
                    {
                        "operation_type": item.operation_type,
                        "relative_path": item.relative_path,
                        "payload": item.payload,
                    }
                )
                for item in transaction.operations
            ],
            "approval_uids": [item.approval_uid for item in transaction.approvals],
            "provenance_uids": [transaction.transaction_uid],
            "audit_anchor_uid": transaction.transaction_uid,
            "actor_uid": transaction.actor,
            "delegation_uid": transaction.delegation_uid,
            "idempotency_key_hash": idempotency_hash,
            "applied_at": applied_at,
        }

    @staticmethod
    def _provenance_record(transaction: SemanticTransaction, generated_at: str) -> dict[str, Any]:
        generated_fields = (
            "entity_uid",
            "revision_uid",
            "relation_revision_uid",
            "record_uid",
            "profile_revision_uid",
            "rule_revision_uid",
            "configuration_uid",
            "baseline_uid",
            "approval_uid",
            "validation_run_uid",
            "finding_uid",
            "package_uid",
        )
        used_fields = (
            "object_uid",
            "parent_revision_uid",
            "parent_relation_revision_uid",
            "subject_uid",
            "supersedes_record_uid",
        )
        package = next(
            (
                item.payload
                for item in transaction.operations
                if item.payload.get("resource_type") == "review_package"
            ),
            None,
        )
        record: dict[str, Any] = {
            "schema_version": "1.0",
            "resource_type": "provenance_record",
            "provenance_uid": transaction.transaction_uid,
            "subject_uid": transaction.transaction_uid,
            "kind": "generated",
            "responsible_actor_uid": transaction.actor,
            "performed_by_actor_uid": transaction.actor,
            "on_behalf_of_actor_uid": None,
            "tool_uids": [],
            "tool_identity": "lesr-runtime/1.0.0a3",
            "delegation_uid": transaction.delegation_uid,
            "used_uids": sorted(
                {
                    str(uid)
                    for operation in transaction.operations
                    for name in used_fields
                    for uid in [operation.payload.get(name)]
                    if isinstance(uid, str)
                }
            ),
            "generated_uids": sorted(
                {
                    str(uid)
                    for operation in transaction.operations
                    for name in generated_fields
                    for uid in [operation.payload.get(name)]
                    if isinstance(uid, str)
                }
                | {transaction.transaction_uid}
            ),
            "review_package_uid": package.get("package_uid") if package else None,
            "validation_run_uids": sorted(
                str(item.payload["validation_run_uid"])
                for item in transaction.operations
                if item.payload.get("resource_type") == "validation_run"
            ),
            "context_bundle_hash": package.get("evaluation_context_hash") if package else None,
            "generated_at": generated_at,
        }
        record["content_hash"] = semantic_hash(record)
        return record

    def _audit_record(
        self,
        commit: str,
        transaction: SemanticTransaction,
        transaction_hash: str,
        created_at: str,
    ) -> dict[str, Any]:
        previous_hash: str | None = None
        previous = [
            value
            for path, value in self.documents(commit)
            if path.startswith("canonical/audit_anchors/")
        ]
        if previous:
            hashes = {
                str(item["anchor_hash"])
                for item in previous
                if isinstance(item.get("anchor_hash"), str)
            }
            referenced = {
                str(item["previous_anchor_hash"])
                for item in previous
                if isinstance(item.get("previous_anchor_hash"), str)
            }
            tails = hashes - referenced
            if len(tails) != 1:
                raise IntegrityError("existing audit anchor chain has no unique tail")
            previous_hash = next(iter(tails))
        record: dict[str, Any] = {
            "schema_version": "1.0",
            "resource_type": "audit_anchor",
            "anchor_uid": transaction.transaction_uid,
            "transaction_uid": transaction.transaction_uid,
            "previous_anchor_hash": previous_hash,
            "event_hashes": [
                transaction_hash,
                *(
                    semantic_hash(
                        {
                            "approval_uid": approval.approval_uid,
                            "actor": approval.actor,
                            "approval_type": approval.approval_type,
                        }
                    )
                    for approval in transaction.approvals
                ),
            ],
            "created_at": created_at,
        }
        record["anchor_hash"] = semantic_hash(record)
        return record

    @staticmethod
    def _utc_now() -> str:
        return datetime.now(UTC).isoformat().replace("+00:00", "Z")

    def _stage_json(self, path: str, value: dict[str, Any], env: dict[str, str]) -> None:
        self._stage_bytes(path, (canonical_json(value) + "\n").encode("utf-8"), env)

    def _stage_bytes(self, path: str, content: bytes, env: dict[str, str]) -> None:
        blob = self._git("hash-object", "-w", "--stdin", input_bytes=content)
        entry = f"100644 {blob}\t".encode("ascii") + path.encode("utf-8") + b"\0"
        self._git("update-index", "-z", "--index-info", input_bytes=entry, extra_env=env)

    def _tree_entries(self, commit: str) -> tuple[tuple[str, str], ...]:
        result = subprocess.run(
            ["git", "-C", str(self.path), "ls-tree", "-r", "-z", commit],
            check=False,
            capture_output=True,
        )
        if result.returncode != 0:
            raise CanonicalError(
                f"git ls-tree failed: {result.stderr.decode('utf-8', errors='replace').strip()}"
            )
        entries: list[tuple[str, str]] = []
        for record in result.stdout.split(b"\0"):
            if not record:
                continue
            metadata, raw_path = record.split(b"\t", 1)
            _, object_type, object_id = metadata.split(b" ", 2)
            if object_type == b"blob":
                entries.append((raw_path.decode("utf-8"), object_id.decode("ascii")))
        return tuple(entries)

    def _read_blob(self, blob: str) -> bytes:
        result = subprocess.run(
            ["git", "-C", str(self.path), "cat-file", "blob", blob],
            check=False,
            capture_output=True,
        )
        if result.returncode != 0:
            raise CanonicalError(
                f"git cat-file failed: {result.stderr.decode('utf-8', errors='replace').strip()}"
            )
        return result.stdout

    def _commit_tree(self, tree: str, parents: tuple[str, ...], message: str) -> str:
        arguments = ["commit-tree", tree]
        for parent in parents:
            arguments.extend(("-p", parent))
        return self._git(*arguments, input_text=message + "\n")

    @staticmethod
    def _inject(injector: FaultInjector | None, stage: str) -> None:
        if injector is not None:
            injector(stage)

    @staticmethod
    def _safe_component(value: str) -> str:
        if not re.fullmatch(r"[A-Za-z0-9._-]+", value):
            raise IntegrityError(f"unsafe identifier component: {value}")
        return value

    @staticmethod
    def _safe_path(value: str) -> str:
        path = PurePosixPath(value)
        if path.is_absolute() or ".." in path.parts or not value.startswith("canonical/"):
            raise IntegrityError(f"unsafe canonical path: {value}")
        return path.as_posix()

    def _try_git(self, *arguments: str) -> str | None:
        result = subprocess.run(
            ["git", "-C", str(self.path), *arguments],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        return result.stdout.strip() if result.returncode == 0 else None

    def _git(
        self,
        *arguments: str,
        input_text: str | None = None,
        input_bytes: bytes | None = None,
        extra_env: dict[str, str] | None = None,
    ) -> str:
        env = os.environ.copy()
        env.update(
            {
                "GIT_AUTHOR_NAME": "LESR Runtime",
                "GIT_AUTHOR_EMAIL": "lesr-runtime@invalid.local",
                "GIT_COMMITTER_NAME": "LESR Runtime",
                "GIT_COMMITTER_EMAIL": "lesr-runtime@invalid.local",
            }
        )
        if extra_env:
            env.update(extra_env)
        if input_text is not None and input_bytes is not None:
            raise ValueError("provide input_text or input_bytes, not both")
        payload = input_bytes if input_bytes is not None else input_text
        text_mode = input_bytes is None
        result = subprocess.run(
            ["git", "-C", str(self.path), *arguments],
            input=payload,
            check=False,
            capture_output=True,
            text=text_mode,
            encoding="utf-8" if text_mode else None,
            env=env,
        )
        if result.returncode != 0:
            stderr = result.stderr if isinstance(result.stderr, str) else result.stderr.decode()
            raise CanonicalError(f"git {' '.join(arguments)} failed: {stderr.strip()}")
        stdout = result.stdout if isinstance(result.stdout, str) else result.stdout.decode()
        return stdout.strip()
