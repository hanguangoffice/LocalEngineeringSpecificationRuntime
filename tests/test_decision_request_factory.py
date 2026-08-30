from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from lesr.adapters.schemas import SchemaCatalog
from lesr.domain.catalog import RUNTIME_SCHEMA_CATALOG
from lesr.domain.decision import (
    DecisionAction,
    DecisionAlternative,
    DecisionDisposition,
    DecisionPolicy,
    DecisionPolicyFacts,
    DecisionRequest,
    DecisionRequestFactory,
    DecisionRequestNarrative,
    DecisionResolution,
    DecisionTarget,
    ImpactCompleteness,
    ImpactSummary,
    MandateLimits,
    MandateScope,
    MissionMandate,
    TriggeredPolicy,
    ValidationConclusion,
    ValidationSummary,
)

NOW = datetime(2026, 8, 30, 8, 0, tzinfo=UTC)
UIDS = tuple(f"018f2000-0000-7000-8000-{index:012d}" for index in range(1, 20))


def mandate() -> MissionMandate:
    return MissionMandate(
        mandate_uid=UIDS[0],
        mission_uid=UIDS[1],
        title="交付本地 GPU 项目管理器",
        issued_by_actor_uid=UIDS[2],
        scope=MandateScope(engineering_areas=("软件架构",)),
        allowed_operations=("workspace.edit",),
        limits=MandateLimits(),
        issued_at=NOW,
        expires_at=NOW + timedelta(days=30),
    )


def facts(**updates: object) -> DecisionPolicyFacts:
    value: dict[str, object] = {
        "mission_uid": UIDS[1],
        "work_package_uid": UIDS[3],
        "operation": "baseline.apply",
        "engineering_area": "软件架构",
        "prospective_work_packages": 2,
        "prospective_changed_resources": 4,
        "prospective_changed_relations": 3,
        "validation": ValidationSummary(
            conclusion=ValidationConclusion.PASSED,
            summary="接口与回归测试通过",
            evidence=("架构测试通过",),
        ),
        "impact": ImpactSummary(
            completeness=ImpactCompleteness.COMPLETE,
            summary="后续适配器工作采用统一边界",
            affected_areas=("软件架构",),
            affected_targets=("适配器接口",),
        ),
        "human_decision_policy_codes": ("RELEASE_COMMITMENT",),
    }
    value.update(updates)
    return DecisionPolicyFacts.model_validate(value)


def narrative(*policy_codes: str) -> DecisionRequestNarrative:
    return DecisionRequestNarrative(
        decision_type="发布边界选择",
        target=DecisionTarget(
            label="适配器接口",
            content_type="架构决策",
            engineering_key="ADR-0003",
        ),
        change_summary="冻结本里程碑的适配器边界并进入发布。",
        recommendation="采用当前边界发布。",
        alternatives=(
            DecisionAlternative(
                title="延后发布",
                summary="保留当前工作区并继续验证。",
                trade_off="交付推迟，但可获得更多兼容性证据。",
            ),
        ),
        triggered_policies=tuple(
            TriggeredPolicy(
                policy_code=code,
                title=code.replace("_", " ").title(),
                explanation="该政策要求由人决定当前里程碑是否继续。",
            )
            for code in policy_codes
        ),
        action=DecisionAction(
            operation="baseline.apply",
            label="按当前边界发布",
            result="发布已验证的工程基线。",
        ),
    )


def human_request() -> DecisionRequest:
    selected_facts = facts()
    result = DecisionPolicy.decide(mandate(), selected_facts, evaluated_at=NOW)
    created = DecisionRequestFactory.create(
        selected_facts,
        result,
        narrative("OPERATION_OUTSIDE_MANDATE", "RELEASE_COMMITMENT"),
        created_at=NOW,
    )
    assert created.decision_request is not None
    return created.decision_request


def test_factory_creates_request_only_for_human_decision_route() -> None:
    selected_facts = facts()
    result = DecisionPolicy.decide(mandate(), selected_facts, evaluated_at=NOW)

    created = DecisionRequestFactory.create(
        selected_facts,
        result,
        narrative("OPERATION_OUTSIDE_MANDATE", "RELEASE_COMMITMENT"),
        created_at=NOW,
    )

    assert created.disposition is DecisionDisposition.HUMAN_DECISION_NOW
    assert created.agent_correction_reasons == ()
    assert created.decision_request is not None
    request = created.decision_request
    assert request.engineering_area == selected_facts.engineering_area
    assert request.validation == selected_facts.validation
    assert request.impact == selected_facts.impact
    assert request.action.operation == selected_facts.operation


def test_block_returns_agent_correction_without_user_request() -> None:
    selected_facts = facts(
        validation=ValidationSummary(
            conclusion=ValidationConclusion.FAILED,
            summary="接口测试失败",
        )
    )
    result = DecisionPolicy.decide(mandate(), selected_facts, evaluated_at=NOW)

    routed = DecisionRequestFactory.create(
        selected_facts,
        result,
        narrative("RELEASE_COMMITMENT"),
        created_at=NOW,
    )

    assert routed.disposition is DecisionDisposition.BLOCK
    assert routed.decision_request is None
    assert routed.agent_correction_reasons == ("VALIDATION_FAILED",)


def test_auto_and_milestone_routes_do_not_create_user_requests() -> None:
    automatic_facts = facts(
        operation="workspace.edit",
        human_decision_policy_codes=(),
    )
    automatic = DecisionPolicy.decide(mandate(), automatic_facts, evaluated_at=NOW)
    routed = DecisionRequestFactory.create(
        automatic_facts,
        automatic,
        created_at=NOW,
    )
    assert routed.disposition is DecisionDisposition.AUTO_EXECUTE
    assert routed.decision_request is None
    assert routed.agent_correction_reasons == ()


def test_factory_rejects_mismatched_policy_evidence_or_explanation() -> None:
    selected_facts = facts()
    result = DecisionPolicy.decide(mandate(), selected_facts, evaluated_at=NOW)
    with pytest.raises(ValueError, match="explain every policy"):
        DecisionRequestFactory.create(
            selected_facts,
            result,
            narrative("RELEASE_COMMITMENT"),
            created_at=NOW,
        )

    other_facts = facts(work_package_uid=UIDS[4])
    with pytest.raises(ValueError, match="do not match"):
        DecisionRequestFactory.create(
            other_facts,
            result,
            narrative("OPERATION_OUTSIDE_MANDATE", "RELEASE_COMMITMENT"),
            created_at=NOW,
        )

    wrong_action = narrative("OPERATION_OUTSIDE_MANDATE", "RELEASE_COMMITMENT").model_copy(
        update={
            "action": DecisionAction(
                operation="workspace.edit",
                label="继续编辑",
                result="返回工作区。",
            )
        }
    )
    with pytest.raises(ValueError, match="evaluated operation"):
        DecisionRequestFactory.create(
            selected_facts,
            result,
            wrong_action,
            created_at=NOW,
        )


def test_resolution_selects_exactly_one_request_choice_and_is_not_approval() -> None:
    request = human_request()
    selected_action = DecisionResolution.from_request(
        request,
        selected_action=request.action.operation,
        decided_by_actor_uid=UIDS[2],
        reason="当前验证证据足以支持发布。",
        decided_at=NOW,
    )
    selected_alternative = DecisionResolution.from_request(
        request,
        selected_alternative=request.alternatives[0].title,
        decided_by_actor_uid=UIDS[2],
        reason="先补充兼容性验证。",
        decided_at=NOW,
    )

    assert selected_action.selected_alternative is None
    assert selected_alternative.selected_action is None
    raw = selected_action.model_dump(mode="json")
    assert raw["formal_approval"] is False
    assert all("hash" not in key and "signature" not in key for key in raw)
    with pytest.raises(ValidationError, match="exactly one"):
        DecisionResolution(
            decision_request_uid=request.decision_request_uid,
            decided_by_actor_uid=UIDS[2],
            reason="缺少选择",
            decided_at=NOW,
        )
    with pytest.raises(ValueError, match="does not belong"):
        DecisionResolution.from_request(
            request,
            selected_alternative="不存在的方案",
            decided_by_actor_uid=UIDS[2],
            reason="错误选择",
            decided_at=NOW,
        )
    with pytest.raises(ValidationError):
        selected_action.reason = "changed"


def test_runtime_schemas_validate_request_and_resolution() -> None:
    request = human_request()
    resolution = DecisionResolution.from_request(
        request,
        selected_action=request.action.operation,
        decided_by_actor_uid=UIDS[2],
        reason="采用推荐方案。",
        decided_at=NOW,
    )
    catalog = SchemaCatalog(Path(__file__).resolve().parents[1] / "schemas" / "v1")

    catalog.validate("decision-request.schema.json", request.model_dump(mode="json"))
    catalog.validate(
        "decision-resolution.schema.json", resolution.model_dump(mode="json")
    )
    assert "decision-resolution.schema.json" in RUNTIME_SCHEMA_CATALOG
