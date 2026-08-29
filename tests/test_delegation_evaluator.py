from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from lesr.adapters.schemas import SchemaCatalog
from lesr.domain.delegation import (
    DelegatedOperation,
    DelegationDecision,
    DelegationEvaluator,
    DelegationGrant,
    DelegationLimits,
    DelegationReasonCode,
    DelegationScope,
    DelegationStopCondition,
    DerivedImpactClass,
    PrincipalType,
)

NOW = datetime(2026, 8, 30, 2, 0, tzinfo=UTC)
UIDS = [f"018f2000-0000-7000-8000-{index:012d}" for index in range(1, 20)]
BASE = "a" * 40
NEXT_BASE = "b" * 40


def grant(**updates: object) -> DelegationGrant:
    value: dict[str, object] = {
        "delegation_uid": UIDS[0],
        "principal_uid": UIDS[1],
        "principal_type": PrincipalType.AI,
        "workspace_uid": UIDS[2],
        "base_commit": BASE,
        "operations": ("workspace.edit", "workspace.checkpoint", "apply_transaction"),
        "scope": DelegationScope(
            resource_uids=(UIDS[3], UIDS[4]),
            revision_uids=(UIDS[5],),
        ),
        "limits": DelegationLimits(
            max_operations=20,
            max_risk_class=DerivedImpactClass.MEDIUM,
        ),
        "issued_by": UIDS[6],
        "issued_at": NOW - timedelta(hours=1),
        "expires_at": NOW + timedelta(days=7),
        "stop_conditions": (
            DelegationStopCondition(
                code="scope_changed",
                description="Mission scope changed after delegation.",
            ),
        ),
        "content_hash": "sha256:" + "0" * 64,
    }
    value.update(updates)
    return DelegationGrant.model_validate(value)


def operation(**updates: object) -> DelegatedOperation:
    value: dict[str, object] = {
        "delegation_uid": UIDS[0],
        "actor_uid": UIDS[1],
        "actor_type": PrincipalType.AI,
        "workspace_uid": UIDS[2],
        "expected_base": BASE,
        "operation": "workspace.edit",
        "target_resource_uids": (UIDS[3],),
        "target_revision_uids": (UIDS[5],),
        "prospective_operation_count": 4,
        "derived_impact_class": DerivedImpactClass.LOW,
        "evaluated_at": NOW,
    }
    value.update(updates)
    return DelegatedOperation.model_validate(value)


def reason_codes(value: DelegationDecision) -> tuple[DelegationReasonCode, ...]:
    return tuple(item.code for item in value.reasons)


def test_matching_delegation_authorizes_automatic_execution_not_human_approval() -> None:
    decision = DelegationEvaluator.evaluate(grant(), operation())
    assert decision.allowed
    assert decision.authorization_kind == "automatic_execution_delegation"
    assert decision.human_approval is False
    assert reason_codes(decision) == (DelegationReasonCode.AUTHORIZED,)
    assert not any("hash" in key or "signature" in key for key in decision.model_dump(mode="json"))


def test_descendant_base_is_authorized_by_repository_ancestry_fact() -> None:
    decision = DelegationEvaluator.evaluate(
        grant(),
        operation(expected_base=NEXT_BASE, grant_base_is_ancestor=True),
    )
    assert decision.allowed

    denied = DelegationEvaluator.evaluate(
        grant(),
        operation(expected_base=NEXT_BASE, grant_base_is_ancestor=False),
    )
    assert reason_codes(denied) == (DelegationReasonCode.BASE_NOT_AUTHORIZED,)


def test_evaluator_returns_all_structured_identity_scope_and_limit_denials() -> None:
    decision = DelegationEvaluator.evaluate(
        grant(),
        operation(
            delegation_uid=UIDS[7],
            actor_uid=UIDS[8],
            actor_type=PrincipalType.TOOL,
            workspace_uid=UIDS[9],
            expected_base=NEXT_BASE,
            operation="baseline.apply",
            target_resource_uids=(UIDS[10],),
            target_revision_uids=(UIDS[11],),
            prospective_operation_count=21,
            derived_impact_class=DerivedImpactClass.HIGH,
            active_stop_condition_codes=("scope_changed",),
        ),
    )
    assert set(reason_codes(decision)) == {
        DelegationReasonCode.DELEGATION_ID_MISMATCH,
        DelegationReasonCode.PRINCIPAL_MISMATCH,
        DelegationReasonCode.PRINCIPAL_TYPE_MISMATCH,
        DelegationReasonCode.WORKSPACE_MISMATCH,
        DelegationReasonCode.BASE_NOT_AUTHORIZED,
        DelegationReasonCode.OPERATION_NOT_ALLOWED,
        DelegationReasonCode.RESOURCE_SCOPE_EXCEEDED,
        DelegationReasonCode.REVISION_SCOPE_EXCEEDED,
        DelegationReasonCode.OPERATION_LIMIT_EXCEEDED,
        DelegationReasonCode.DERIVED_IMPACT_LIMIT_EXCEEDED,
        DelegationReasonCode.STOP_CONDITION_TRIGGERED,
    }
    assert all(item.message for item in decision.reasons)
    assert not decision.allowed


def test_expiry_and_not_yet_active_are_evaluated_at_explicit_time() -> None:
    not_yet = DelegationEvaluator.evaluate(
        grant(issued_at=NOW + timedelta(hours=1), expires_at=NOW + timedelta(hours=2)),
        operation(),
    )
    assert reason_codes(not_yet) == (DelegationReasonCode.NOT_YET_ACTIVE,)

    expired = DelegationEvaluator.evaluate(
        grant(expires_at=NOW),
        operation(),
    )
    assert reason_codes(expired) == (DelegationReasonCode.EXPIRED,)


def test_configured_stop_condition_only_denies_when_it_is_active() -> None:
    dormant = DelegationEvaluator.evaluate(
        grant(),
        operation(active_stop_condition_codes=("unrelated_runtime_signal",)),
    )
    assert dormant.allowed

    active = DelegationEvaluator.evaluate(
        grant(),
        operation(active_stop_condition_codes=("scope_changed",)),
    )
    assert reason_codes(active) == (DelegationReasonCode.STOP_CONDITION_TRIGGERED,)
    assert active.reasons[0].affected_values == ("scope_changed",)


def test_empty_canonical_scope_remains_workspace_wide() -> None:
    broad = grant(scope=DelegationScope())
    decision = DelegationEvaluator.evaluate(
        broad,
        operation(
            target_resource_uids=(UIDS[10],),
            target_revision_uids=(UIDS[11],),
        ),
    )
    assert decision.allowed


def test_client_risk_class_is_not_an_authoritative_delegation_input() -> None:
    raw = operation().model_dump(mode="json") | {"risk_class": "high"}
    with pytest.raises(ValidationError, match="risk_class"):
        DelegatedOperation.model_validate(raw)
    assert "risk_class" not in DelegatedOperation.model_fields
    assert "derived_impact_class" in DelegatedOperation.model_fields


def test_grant_matches_existing_schema_and_contracts_are_frozen_utc() -> None:
    active = grant()
    catalog = SchemaCatalog(Path(__file__).resolve().parents[1] / "schemas" / "v1")
    catalog.validate("delegation-grant.schema.json", active.model_dump(mode="json"))

    with pytest.raises(ValidationError):
        active.principal_uid = UIDS[12]
    with pytest.raises(ValidationError, match="UTC"):
        operation(evaluated_at=datetime(2026, 8, 30, 2, 0))  # noqa: DTZ001
    with pytest.raises(ValidationError, match="expires_at"):
        grant(expires_at=NOW - timedelta(hours=1))
