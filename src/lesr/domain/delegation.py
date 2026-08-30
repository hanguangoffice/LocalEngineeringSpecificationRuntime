"""Pure evaluation of scoped Delegation Grants for automatic execution.

A Delegation Grant authorizes an actor or Agent to execute bounded operations
without asking a human at every step.  It is not a human approval and cannot
stand in for a formal decision at an authority boundary.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import ClassVar, Literal, Self

from pydantic import Field, field_validator, model_validator

from lesr.domain.semantic import FrozenModel


def _require_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError("timestamp must be UTC")
    return value.astimezone(UTC)


def _unique(values: tuple[str, ...], name: str) -> tuple[str, ...]:
    if len(values) != len(set(values)):
        raise ValueError(f"{name} must be unique")
    return values


class PrincipalType(StrEnum):
    HUMAN = "human"
    AI = "ai"
    TOOL = "tool"
    SYSTEM = "system"


class DerivedImpactClass(StrEnum):
    """Impact class derived by trusted domain policy, never by an adapter."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class DelegationScope(FrozenModel):
    """Canonical scope shape already used by current Delegation Grant records.

    An empty UID collection means workspace-wide scope for that UID category.
    """

    resource_uids: tuple[str, ...] = ()
    revision_uids: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_scope(self) -> Self:
        _unique(self.resource_uids, "Delegation resource UIDs")
        _unique(self.revision_uids, "Delegation revision UIDs")
        return self


class DelegationLimits(FrozenModel):
    max_operations: int = Field(ge=1)
    max_risk_class: DerivedImpactClass


class DelegationStopCondition(FrozenModel):
    code: str = Field(min_length=1)
    description: str = Field(min_length=1)


class DelegationGrant(FrozenModel):
    """Typed view of the existing ``delegation-grant.schema.json`` document."""

    schema_version: Literal["1.0"] = "1.0"
    resource_type: Literal["delegation_grant"] = "delegation_grant"
    delegation_uid: str
    principal_uid: str
    principal_type: PrincipalType
    workspace_uid: str
    base_commit: str = Field(pattern=r"^[0-9a-f]{40,64}$")
    operations: tuple[str, ...] = Field(min_length=1)
    scope: DelegationScope
    limits: DelegationLimits
    issued_by: str
    issued_at: datetime
    expires_at: datetime
    stop_conditions: tuple[DelegationStopCondition, ...] = ()
    content_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")

    _utc_issued = field_validator("issued_at")(_require_utc)
    _utc_expires = field_validator("expires_at")(_require_utc)

    @model_validator(mode="after")
    def validate_grant(self) -> Self:
        _unique(self.operations, "Delegation operations")
        _unique(
            tuple(item.code for item in self.stop_conditions),
            "Delegation stop conditions",
        )
        if self.expires_at <= self.issued_at:
            raise ValueError("Delegation expires_at must follow issued_at")
        return self


class DelegatedOperation(FrozenModel):
    """Trusted facts aligned with the current WriteEnvelope.

    ``derived_impact_class`` must come from semantic policy and impact analysis;
    callers must not copy the client-supplied ``WriteEnvelope.risk_class``.
    ``grant_base_is_ancestor`` is supplied by the repository's ancestry query.
    """

    delegation_uid: str
    actor_uid: str
    actor_type: PrincipalType
    workspace_uid: str
    expected_base: str = Field(pattern=r"^[0-9a-f]{40,64}$")
    grant_base_is_ancestor: bool = False
    operation: str = Field(min_length=1)
    target_resource_uids: tuple[str, ...] = ()
    target_revision_uids: tuple[str, ...] = ()
    prospective_operation_count: int = Field(ge=1)
    derived_impact_class: DerivedImpactClass
    active_stop_condition_codes: tuple[str, ...] = ()
    evaluated_at: datetime

    _utc_evaluated = field_validator("evaluated_at")(_require_utc)

    @model_validator(mode="after")
    def validate_request(self) -> Self:
        _unique(self.target_resource_uids, "Delegated resource targets")
        _unique(self.target_revision_uids, "Delegated revision targets")
        _unique(self.active_stop_condition_codes, "Active stop conditions")
        return self


class DelegationReasonCode(StrEnum):
    AUTHORIZED = "AUTHORIZED"
    DELEGATION_ID_MISMATCH = "DELEGATION_ID_MISMATCH"
    PRINCIPAL_MISMATCH = "PRINCIPAL_MISMATCH"
    PRINCIPAL_TYPE_MISMATCH = "PRINCIPAL_TYPE_MISMATCH"
    WORKSPACE_MISMATCH = "WORKSPACE_MISMATCH"
    BASE_NOT_AUTHORIZED = "BASE_NOT_AUTHORIZED"
    OPERATION_NOT_ALLOWED = "OPERATION_NOT_ALLOWED"
    RESOURCE_SCOPE_EXCEEDED = "RESOURCE_SCOPE_EXCEEDED"
    REVISION_SCOPE_EXCEEDED = "REVISION_SCOPE_EXCEEDED"
    NOT_YET_ACTIVE = "NOT_YET_ACTIVE"
    EXPIRED = "EXPIRED"
    OPERATION_LIMIT_EXCEEDED = "OPERATION_LIMIT_EXCEEDED"
    DERIVED_IMPACT_LIMIT_EXCEEDED = "DERIVED_IMPACT_LIMIT_EXCEEDED"
    STOP_CONDITION_TRIGGERED = "STOP_CONDITION_TRIGGERED"


class DelegationReason(FrozenModel):
    code: DelegationReasonCode
    message: str = Field(min_length=1)
    affected_values: tuple[str, ...] = ()


class DelegationDecision(FrozenModel):
    delegation_uid: str
    operation: str
    allowed: bool
    authorization_kind: Literal["automatic_execution_delegation"] = "automatic_execution_delegation"
    human_approval: Literal[False] = False
    reasons: tuple[DelegationReason, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_decision(self) -> Self:
        codes = tuple(item.code for item in self.reasons)
        if self.allowed and codes != (DelegationReasonCode.AUTHORIZED,):
            raise ValueError("allowed DelegationDecision requires only AUTHORIZED")
        if not self.allowed and DelegationReasonCode.AUTHORIZED in codes:
            raise ValueError("denied DelegationDecision cannot contain AUTHORIZED")
        return self


class DelegationEvaluator:
    """Evaluate all Delegation constraints and return every denial reason."""

    _IMPACT_ORDER: ClassVar[dict[DerivedImpactClass, int]] = {
        DerivedImpactClass.LOW: 0,
        DerivedImpactClass.MEDIUM: 1,
        DerivedImpactClass.HIGH: 2,
    }

    @classmethod
    def evaluate(
        cls,
        grant: DelegationGrant,
        request: DelegatedOperation,
    ) -> DelegationDecision:
        reasons: list[DelegationReason] = []

        def deny(
            code: DelegationReasonCode,
            message: str,
            *affected_values: str,
        ) -> None:
            reasons.append(
                DelegationReason(
                    code=code,
                    message=message,
                    affected_values=tuple(affected_values),
                )
            )

        if request.delegation_uid != grant.delegation_uid:
            deny(
                DelegationReasonCode.DELEGATION_ID_MISMATCH,
                "The request names another Delegation Grant.",
                request.delegation_uid,
            )
        if request.actor_uid != grant.principal_uid:
            deny(
                DelegationReasonCode.PRINCIPAL_MISMATCH,
                "The actor is not the delegated principal.",
                request.actor_uid,
            )
        if request.actor_type is not grant.principal_type:
            deny(
                DelegationReasonCode.PRINCIPAL_TYPE_MISMATCH,
                "The actor type does not match the delegated principal type.",
                request.actor_type.value,
            )
        if request.workspace_uid != grant.workspace_uid:
            deny(
                DelegationReasonCode.WORKSPACE_MISMATCH,
                "The request belongs to another Workspace.",
                request.workspace_uid,
            )
        if request.expected_base != grant.base_commit and not request.grant_base_is_ancestor:
            deny(
                DelegationReasonCode.BASE_NOT_AUTHORIZED,
                "The request base does not descend from the delegated base.",
                request.expected_base,
            )
        if request.operation not in grant.operations:
            deny(
                DelegationReasonCode.OPERATION_NOT_ALLOWED,
                "The operation is outside the Delegation Grant.",
                request.operation,
            )

        allowed_resources = set(grant.scope.resource_uids)
        outside_resources = sorted(set(request.target_resource_uids) - allowed_resources)
        if allowed_resources and outside_resources:
            deny(
                DelegationReasonCode.RESOURCE_SCOPE_EXCEEDED,
                "One or more resource targets are outside the delegated scope.",
                *outside_resources,
            )
        allowed_revisions = set(grant.scope.revision_uids)
        outside_revisions = sorted(set(request.target_revision_uids) - allowed_revisions)
        if allowed_revisions and outside_revisions:
            deny(
                DelegationReasonCode.REVISION_SCOPE_EXCEEDED,
                "One or more Revision targets are outside the delegated scope.",
                *outside_revisions,
            )

        if request.evaluated_at < grant.issued_at:
            deny(
                DelegationReasonCode.NOT_YET_ACTIVE,
                "The Delegation Grant is not active yet.",
            )
        if request.evaluated_at >= grant.expires_at:
            deny(DelegationReasonCode.EXPIRED, "The Delegation Grant has expired.")
        if request.prospective_operation_count > grant.limits.max_operations:
            deny(
                DelegationReasonCode.OPERATION_LIMIT_EXCEEDED,
                "The operation would exceed the delegated operation limit.",
                str(request.prospective_operation_count),
                str(grant.limits.max_operations),
            )
        if (
            cls._IMPACT_ORDER[request.derived_impact_class]
            > cls._IMPACT_ORDER[grant.limits.max_risk_class]
        ):
            deny(
                DelegationReasonCode.DERIVED_IMPACT_LIMIT_EXCEEDED,
                "Domain-derived impact exceeds the delegated limit.",
                request.derived_impact_class.value,
                grant.limits.max_risk_class.value,
            )

        configured_conditions = {item.code for item in grant.stop_conditions}
        triggered = sorted(configured_conditions.intersection(request.active_stop_condition_codes))
        if triggered:
            deny(
                DelegationReasonCode.STOP_CONDITION_TRIGGERED,
                "A configured Delegation stop condition is active.",
                *triggered,
            )

        if reasons:
            return DelegationDecision(
                delegation_uid=grant.delegation_uid,
                operation=request.operation,
                allowed=False,
                reasons=tuple(reasons),
            )
        return DelegationDecision(
            delegation_uid=grant.delegation_uid,
            operation=request.operation,
            allowed=True,
            reasons=(
                DelegationReason(
                    code=DelegationReasonCode.AUTHORIZED,
                    message="The operation is within the active Delegation Grant.",
                ),
            ),
        )
