"""Runtime-only Mission mandate and automated decision-routing contracts.

The policy input is derived by trusted domain services from semantic diff,
validation, impact and the active engineering policy.  Adapters must not turn a
client supplied ``RiskClass`` into authority.  These operational records carry
no content hash and are not eligible for Canonical Git.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Literal, Self

from pydantic import Field, field_validator, model_validator

from lesr.domain.semantic import FrozenModel, uuid7_candidate


def _require_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError("timestamp must be UTC")
    return value.astimezone(UTC)


def _require_optional_utc(value: datetime | None) -> datetime | None:
    return _require_utc(value) if value is not None else None


def _unique(values: tuple[str, ...], name: str) -> tuple[str, ...]:
    if len(values) != len(set(values)):
        raise ValueError(f"{name} must be unique")
    return values


class DecisionDisposition(StrEnum):
    """The only four routes emitted by the background decision policy."""

    AUTO_EXECUTE = "AUTO_EXECUTE"
    BATCH_FOR_MILESTONE = "BATCH_FOR_MILESTONE"
    HUMAN_DECISION_NOW = "HUMAN_DECISION_NOW"
    BLOCK = "BLOCK"


class ValidationConclusion(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    INDETERMINATE = "indeterminate"


class ImpactCompleteness(StrEnum):
    COMPLETE = "complete"
    INCOMPLETE = "incomplete"
    INDETERMINATE = "indeterminate"


class MandateScope(FrozenModel):
    """The engineering boundary delegated by the Mission initiator."""

    configuration_uid: str | None = None
    engineering_areas: tuple[str, ...] = Field(min_length=1)
    resource_uids: tuple[str, ...] = ()
    allow_new_resources: bool = True

    @model_validator(mode="after")
    def validate_scope(self) -> Self:
        _unique(self.engineering_areas, "Mandate engineering areas")
        _unique(self.resource_uids, "Mandate resource UIDs")
        return self


class MandateLimits(FrozenModel):
    """Prospective cumulative limits for work performed under one mandate."""

    max_work_packages: int = Field(default=100, ge=1)
    max_changed_resources: int = Field(default=500, ge=1)
    max_changed_relations: int = Field(default=2000, ge=0)
    max_external_actions: int = Field(default=0, ge=0)
    max_destructive_actions: int = Field(default=0, ge=0)


class MissionMandate(FrozenModel):
    """Standing Mission authority used instead of approval for every small step."""

    schema_version: Literal["1.0"] = "1.0"
    resource_type: Literal["mission_mandate"] = "mission_mandate"
    persistence_scope: Literal["local_runtime"] = "local_runtime"
    canonical_git_eligible: Literal[False] = False
    mandate_uid: str = Field(default_factory=uuid7_candidate)
    mission_uid: str
    title: str = Field(min_length=1)
    issued_by_actor_uid: str = Field(min_length=1)
    scope: MandateScope
    allowed_operations: tuple[str, ...] = Field(min_length=1)
    limits: MandateLimits = Field(default_factory=MandateLimits)
    issued_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    expires_at: datetime
    revoked_at: datetime | None = None

    _utc_issued = field_validator("issued_at")(_require_utc)
    _utc_expires = field_validator("expires_at")(_require_utc)
    _utc_revoked = field_validator("revoked_at")(_require_optional_utc)

    @model_validator(mode="after")
    def validate_mandate(self) -> Self:
        _unique(self.allowed_operations, "Mandate operations")
        if self.expires_at <= self.issued_at:
            raise ValueError("MissionMandate expires_at must follow issued_at")
        if self.revoked_at is not None and self.revoked_at < self.issued_at:
            raise ValueError("MissionMandate revoked_at precedes issued_at")
        return self

    def is_active_at(self, instant: datetime) -> bool:
        selected = _require_utc(instant)
        return self.issued_at <= selected < self.expires_at and (
            self.revoked_at is None or selected < self.revoked_at
        )


class ValidationSummary(FrozenModel):
    conclusion: ValidationConclusion
    summary: str = Field(min_length=1)
    evidence: tuple[str, ...] = ()


class ImpactSummary(FrozenModel):
    completeness: ImpactCompleteness
    summary: str = Field(min_length=1)
    affected_areas: tuple[str, ...] = ()
    affected_targets: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_impact(self) -> Self:
        _unique(self.affected_areas, "Impact areas")
        _unique(self.affected_targets, "Impact targets")
        return self


class DecisionPolicyFacts(FrozenModel):
    """Trusted, backend-derived facts consumed by :class:`DecisionPolicy`.

    Counts are the prospective cumulative Mission usage after the proposed
    operation.  No client risk label is accepted by this contract.
    """

    mission_uid: str
    work_package_uid: str
    operation: str = Field(min_length=1)
    engineering_area: str = Field(min_length=1)
    target_resource_uids: tuple[str, ...] = ()
    new_resource_count: int = Field(default=0, ge=0)
    prospective_work_packages: int = Field(ge=1)
    prospective_changed_resources: int = Field(ge=0)
    prospective_changed_relations: int = Field(ge=0)
    prospective_external_actions: int = Field(default=0, ge=0)
    prospective_destructive_actions: int = Field(default=0, ge=0)
    validation: ValidationSummary
    impact: ImpactSummary
    blocking_policy_codes: tuple[str, ...] = ()
    human_decision_policy_codes: tuple[str, ...] = ()
    milestone_policy_codes: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_facts(self) -> Self:
        _unique(self.target_resource_uids, "Decision targets")
        _unique(self.blocking_policy_codes, "Blocking policies")
        _unique(self.human_decision_policy_codes, "Human-decision policies")
        _unique(self.milestone_policy_codes, "Milestone policies")
        return self


class DecisionPolicyResult(FrozenModel):
    disposition: DecisionDisposition
    mandate_uid: str
    mission_uid: str
    work_package_uid: str
    operation: str
    reasons: tuple[str, ...] = Field(min_length=1)


class DecisionTarget(FrozenModel):
    label: str = Field(min_length=1)
    content_type: str = Field(min_length=1)
    engineering_key: str | None = None


class DecisionAlternative(FrozenModel):
    title: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    trade_off: str = Field(min_length=1)


class TriggeredPolicy(FrozenModel):
    policy_code: str = Field(min_length=1)
    title: str = Field(min_length=1)
    explanation: str = Field(min_length=1)


class DecisionAction(FrozenModel):
    """The one operation the human decision would authorize."""

    operation: str = Field(min_length=1)
    label: str = Field(min_length=1)
    result: str = Field(min_length=1)


class DecisionRequest(FrozenModel):
    """A complete, human-readable request for one material decision."""

    schema_version: Literal["1.0"] = "1.0"
    resource_type: Literal["decision_request"] = "decision_request"
    persistence_scope: Literal["local_runtime"] = "local_runtime"
    canonical_git_eligible: Literal[False] = False
    decision_request_uid: str = Field(default_factory=uuid7_candidate)
    mission_uid: str
    work_package_uid: str
    mandate_uid: str
    disposition: Literal[DecisionDisposition.HUMAN_DECISION_NOW] = (
        DecisionDisposition.HUMAN_DECISION_NOW
    )
    decision_type: str = Field(min_length=1)
    engineering_area: str = Field(min_length=1)
    target: DecisionTarget
    change_summary: str = Field(min_length=1)
    impact: ImpactSummary
    validation: ValidationSummary
    recommendation: str = Field(min_length=1)
    alternatives: tuple[DecisionAlternative, ...] = Field(min_length=1)
    triggered_policies: tuple[TriggeredPolicy, ...] = Field(min_length=1)
    action: DecisionAction
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    _utc_created = field_validator("created_at")(_require_utc)

    @model_validator(mode="after")
    def validate_request(self) -> Self:
        _unique(
            tuple(item.title for item in self.alternatives),
            "Decision alternatives",
        )
        _unique(
            tuple(item.policy_code for item in self.triggered_policies),
            "Triggered policies",
        )
        return self


class DecisionRequestNarrative(FrozenModel):
    """Human-readable material paired with backend-derived policy evidence."""

    decision_type: str = Field(min_length=1)
    target: DecisionTarget
    change_summary: str = Field(min_length=1)
    recommendation: str = Field(min_length=1)
    alternatives: tuple[DecisionAlternative, ...] = Field(min_length=1)
    triggered_policies: tuple[TriggeredPolicy, ...] = Field(min_length=1)
    action: DecisionAction


class DecisionRequestFactoryResult(FrozenModel):
    """Routing result for the Agent; only one route contains a user request."""

    disposition: DecisionDisposition
    decision_request: DecisionRequest | None = None
    agent_correction_reasons: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_route(self) -> Self:
        if self.disposition is DecisionDisposition.HUMAN_DECISION_NOW:
            if self.decision_request is None or self.agent_correction_reasons:
                raise ValueError("human decision route requires only a DecisionRequest")
        elif self.disposition is DecisionDisposition.BLOCK:
            if self.decision_request is not None or not self.agent_correction_reasons:
                raise ValueError("blocked route must return correction reasons to the Agent")
        elif self.decision_request is not None or self.agent_correction_reasons:
            raise ValueError("automatic and milestone routes do not create DecisionRequests")
        return self


class DecisionRequestFactory:
    """Create a user-facing request only at a real human decision boundary."""

    @staticmethod
    def create(
        facts: DecisionPolicyFacts,
        result: DecisionPolicyResult,
        human_readable: DecisionRequestNarrative | None = None,
        *,
        created_at: datetime,
    ) -> DecisionRequestFactoryResult:
        DecisionRequestFactory._require_matching_policy_input(facts, result)
        created = _require_utc(created_at)
        if result.disposition is DecisionDisposition.BLOCK:
            return DecisionRequestFactoryResult(
                disposition=result.disposition,
                agent_correction_reasons=result.reasons,
            )
        if result.disposition is not DecisionDisposition.HUMAN_DECISION_NOW:
            return DecisionRequestFactoryResult(disposition=result.disposition)
        if human_readable is None:
            raise ValueError("human decision route requires human-readable request content")
        policy_codes = {item.policy_code for item in human_readable.triggered_policies}
        if policy_codes != set(result.reasons):
            raise ValueError("human-readable policies must explain every policy result reason")
        if human_readable.action.operation != facts.operation:
            raise ValueError("human-readable action must match the evaluated operation")
        request = DecisionRequest(
            mission_uid=facts.mission_uid,
            work_package_uid=facts.work_package_uid,
            mandate_uid=result.mandate_uid,
            decision_type=human_readable.decision_type,
            engineering_area=facts.engineering_area,
            target=human_readable.target,
            change_summary=human_readable.change_summary,
            impact=facts.impact,
            validation=facts.validation,
            recommendation=human_readable.recommendation,
            alternatives=human_readable.alternatives,
            triggered_policies=human_readable.triggered_policies,
            action=human_readable.action,
            created_at=created,
        )
        return DecisionRequestFactoryResult(
            disposition=result.disposition,
            decision_request=request,
        )

    @staticmethod
    def _require_matching_policy_input(
        facts: DecisionPolicyFacts,
        result: DecisionPolicyResult,
    ) -> None:
        if (
            facts.mission_uid,
            facts.work_package_uid,
            facts.operation,
        ) != (
            result.mission_uid,
            result.work_package_uid,
            result.operation,
        ):
            raise ValueError("DecisionPolicyFacts and DecisionPolicyResult do not match")


class DecisionResolution(FrozenModel):
    """Local record of one human choice; it is not a formal Approval."""

    schema_version: Literal["1.0"] = "1.0"
    resource_type: Literal["decision_resolution"] = "decision_resolution"
    persistence_scope: Literal["local_runtime"] = "local_runtime"
    canonical_git_eligible: Literal[False] = False
    formal_approval: Literal[False] = False
    decision_resolution_uid: str = Field(default_factory=uuid7_candidate)
    decision_request_uid: str = Field(min_length=1)
    selected_action: str | None = Field(default=None, min_length=1)
    selected_alternative: str | None = Field(default=None, min_length=1)
    decided_by_actor_uid: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    decided_at: datetime

    _utc_decided = field_validator("decided_at")(_require_utc)

    @model_validator(mode="after")
    def validate_selection(self) -> Self:
        if (self.selected_action is None) == (self.selected_alternative is None):
            raise ValueError("DecisionResolution must select exactly one action or alternative")
        return self

    @classmethod
    def from_request(
        cls,
        request: DecisionRequest,
        *,
        decided_by_actor_uid: str,
        reason: str,
        decided_at: datetime,
        selected_action: str | None = None,
        selected_alternative: str | None = None,
    ) -> Self:
        if selected_action is not None and selected_action != request.action.operation:
            raise ValueError("selected action does not belong to the DecisionRequest")
        alternatives = {item.title for item in request.alternatives}
        if selected_alternative is not None and selected_alternative not in alternatives:
            raise ValueError("selected alternative does not belong to the DecisionRequest")
        return cls(
            decision_request_uid=request.decision_request_uid,
            selected_action=selected_action,
            selected_alternative=selected_alternative,
            decided_by_actor_uid=decided_by_actor_uid,
            reason=reason,
            decided_at=decided_at,
        )


class DecisionPolicy:
    """Pure routing policy with no adapter-provided risk-class authority."""

    @staticmethod
    def decide(
        mandate: MissionMandate,
        facts: DecisionPolicyFacts,
        *,
        evaluated_at: datetime,
    ) -> DecisionPolicyResult:
        instant = _require_utc(evaluated_at)
        if mandate.mission_uid != facts.mission_uid:
            raise ValueError("Decision facts belong to another Mission")

        blocked = list(facts.blocking_policy_codes)
        if facts.validation.conclusion is not ValidationConclusion.PASSED:
            blocked.append(f"VALIDATION_{facts.validation.conclusion.value.upper()}")
        if facts.impact.completeness is not ImpactCompleteness.COMPLETE:
            blocked.append(f"IMPACT_{facts.impact.completeness.value.upper()}")
        if blocked:
            return DecisionPolicy._result(mandate, facts, DecisionDisposition.BLOCK, blocked)

        human: list[str] = list(facts.human_decision_policy_codes)
        if not mandate.is_active_at(instant):
            human.append("MANDATE_INACTIVE")
        if facts.operation not in mandate.allowed_operations:
            human.append("OPERATION_OUTSIDE_MANDATE")
        if facts.engineering_area not in mandate.scope.engineering_areas:
            human.append("ENGINEERING_AREA_OUTSIDE_MANDATE")
        allowed_targets = set(mandate.scope.resource_uids)
        if allowed_targets and not set(facts.target_resource_uids) <= allowed_targets:
            human.append("TARGET_OUTSIDE_MANDATE")
        if facts.new_resource_count and not mandate.scope.allow_new_resources:
            human.append("NEW_RESOURCE_OUTSIDE_MANDATE")
        usage = (
            (
                "WORK_PACKAGE_LIMIT_EXCEEDED",
                facts.prospective_work_packages,
                mandate.limits.max_work_packages,
            ),
            (
                "CHANGED_RESOURCE_LIMIT_EXCEEDED",
                facts.prospective_changed_resources,
                mandate.limits.max_changed_resources,
            ),
            (
                "CHANGED_RELATION_LIMIT_EXCEEDED",
                facts.prospective_changed_relations,
                mandate.limits.max_changed_relations,
            ),
            (
                "EXTERNAL_ACTION_LIMIT_EXCEEDED",
                facts.prospective_external_actions,
                mandate.limits.max_external_actions,
            ),
            (
                "DESTRUCTIVE_ACTION_LIMIT_EXCEEDED",
                facts.prospective_destructive_actions,
                mandate.limits.max_destructive_actions,
            ),
        )
        human.extend(code for code, actual, maximum in usage if actual > maximum)
        if human:
            return DecisionPolicy._result(
                mandate, facts, DecisionDisposition.HUMAN_DECISION_NOW, human
            )

        if facts.milestone_policy_codes:
            return DecisionPolicy._result(
                mandate,
                facts,
                DecisionDisposition.BATCH_FOR_MILESTONE,
                list(facts.milestone_policy_codes),
            )

        return DecisionPolicy._result(
            mandate,
            facts,
            DecisionDisposition.AUTO_EXECUTE,
            ["WITHIN_ACTIVE_MANDATE"],
        )

    @staticmethod
    def _result(
        mandate: MissionMandate,
        facts: DecisionPolicyFacts,
        disposition: DecisionDisposition,
        reasons: list[str],
    ) -> DecisionPolicyResult:
        return DecisionPolicyResult(
            disposition=disposition,
            mandate_uid=mandate.mandate_uid,
            mission_uid=facts.mission_uid,
            work_package_uid=facts.work_package_uid,
            operation=facts.operation,
            reasons=tuple(sorted(set(reasons))),
        )
