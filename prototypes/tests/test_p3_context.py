from __future__ import annotations

from datetime import UTC, datetime

import pytest

from prototypes.lesr_v1.p3_context import (
    ClosureStatus,
    CompletenessStatus,
    ConfigurationDefinition,
    ConfigurationMembership,
    ContextContract,
    ContextPlanner,
    ContextPolicy,
    ContextRelation,
    ContextResource,
    EffectiveResolver,
    EffectiveRuleReference,
    EvaluationContext,
    ResolutionStatus,
    RevisionDescriptor,
)

NOW = datetime(2026, 8, 5, tzinfo=UTC)


def revisions() -> tuple[RevisionDescriptor, ...]:
    return (
        RevisionDescriptor("REQ", "REQ@1", 1, "approved"),
        RevisionDescriptor("REQ", "REQ@2", 2, "approved"),
        RevisionDescriptor("DES", "DES@1", 1, "approved"),
        RevisionDescriptor("RULE", "RULE@1", 1, "approved"),
        RevisionDescriptor("DEV", "DEV@1", 1, "approved"),
    )


def configuration() -> ConfigurationDefinition:
    return ConfigurationDefinition(
        configuration_uid="CFG-1",
        git_commit="a" * 40,
        memberships=(
            ConfigurationMembership("REQ", "REQ@2"),
            ConfigurationMembership("DES", "DES@1"),
            ConfigurationMembership("RULE", "RULE@1"),
            ConfigurationMembership("DEV", "DEV@1"),
        ),
        profile_revision_uids=("PROFILE@1",),
        effective_model_hash="sha256:model",
        active_deviation_revision_uids=("DEV@1",),
    )


def context(*, operation: str = "coding", budget_fallback: bool = False) -> EvaluationContext:
    return EvaluationContext(
        repository="repo",
        project="project",
        operation=operation,
        actor="USER-1",
        target_object_uids=("REQ",),
        evaluation_time=NOW,
        configuration_uid="CFG-1",
        allow_latest_approved_fallback=budget_fallback,
    )


def resources() -> tuple[ContextResource, ...]:
    return (
        ContextResource("REQ", "REQ@1", "requirement", "stale requirement", 5),
        ContextResource("REQ", "REQ@2", "requirement", "MQTT reconnect", 10),
        ContextResource("DES", "DES@1", "design", "reconnect design", 10),
        ContextResource("RULE", "RULE@1", "coding_rule", "mandatory rule", 10),
        ContextResource("DEV", "DEV@1", "deviation", "active deviation", 10),
    )


def build_contract(task_type: str, token_budget: int = 100) -> ContextContract:
    resolved = EffectiveResolver().resolve(context(), revisions(), configuration())
    return ContextPlanner().build(
        task_type=task_type,
        resolution=resolved,
        resources=resources(),
        relations=(ContextRelation("REQ", "realized_by", "DES"),),
        rules=(
            EffectiveRuleReference(
                "RULE@1", frozenset({"coding"}), frozenset({"RULE", "DEV"})
            ),
        ),
        policy=ContextPolicy(
            invariant_object_uids=frozenset({"RULE"}),
            mandatory_predicates=frozenset({"realized_by"}),
        ),
        token_budget=token_budget,
        configuration=configuration(),
    )


def test_configuration_membership_selects_exact_revision_and_excludes_stale() -> None:
    result = EffectiveResolver().resolve(context(), revisions(), configuration())
    assert result.selected == {
        "REQ": "REQ@2",
        "DES": "DES@1",
        "RULE": "RULE@1",
        "DEV": "DEV@1",
    }
    assert "REQ@1" in result.excluded_revisions
    contract = build_contract("mqtt_change")
    selected_revisions = {item.resource.revision_uid for item in contract.selections}
    assert "REQ@2" in selected_revisions
    assert "REQ@1" not in selected_revisions
    assert any(item.revision_uid == "REQ@1" for item in contract.negative_context)


def test_ambiguous_current_is_indeterminate() -> None:
    unresolved_context = EvaluationContext(
        repository="repo",
        project="project",
        operation="coding",
        actor="USER-1",
        target_object_uids=("REQ",),
        evaluation_time=NOW,
    )
    result = EffectiveResolver().resolve(unresolved_context, revisions(), None)
    assert result.objects[0].status is ResolutionStatus.INDETERMINATE
    assert result.closure_status is ClosureStatus.INDETERMINATE


def test_high_risk_operation_cannot_use_latest_approved_fallback() -> None:
    risky = context(operation="apply_transaction", budget_fallback=True)
    result = EffectiveResolver().resolve(risky, revisions(), None)
    assert result.selected == {}
    assert any("fallback forbidden" in item for item in result.conflicts)


@pytest.mark.parametrize(
    "task_type",
    ["mqtt_change", "can_signal_change", "requirement_change", "test_design", "deviation_review"],
)
def test_five_gate_tasks_have_zero_mandatory_misses(task_type: str) -> None:
    contract = build_contract(task_type)
    selected = {item.resource.object_uid for item in contract.selections}
    assert {"REQ", "DES", "RULE", "DEV"} <= selected
    assert contract.completeness is CompletenessStatus.COMPLETE_UNDER_MODEL
    assert contract.validation_obligations == ("RULE@1",)


def test_budget_shortage_is_explicit_and_never_drops_mandatory_context() -> None:
    contract = build_contract("mqtt_change", token_budget=1)
    selected = {item.resource.object_uid for item in contract.selections}
    assert {"REQ", "DES", "RULE", "DEV"} <= selected
    assert contract.completeness is CompletenessStatus.INCOMPLETE_BUDGET
