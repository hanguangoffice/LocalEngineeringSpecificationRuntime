from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from lesr.adapters.schemas import SchemaCatalog
from lesr.domain.decision import (
    DecisionAction,
    DecisionAlternative,
    DecisionDisposition,
    DecisionPolicy,
    DecisionPolicyFacts,
    DecisionRequest,
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

NOW = datetime(2026, 8, 30, 1, 0, tzinfo=UTC)
UIDS = [f"018f1000-0000-7000-8000-{index:012d}" for index in range(1, 20)]


def mandate(**updates: object) -> MissionMandate:
    value: dict[str, object] = {
        "mandate_uid": UIDS[0],
        "mission_uid": UIDS[1],
        "title": "实现本地 GPU 项目管理器",
        "issued_by_actor_uid": "local-user",
        "scope": MandateScope(
            configuration_uid=UIDS[4],
            engineering_areas=("软件实现", "自动测试"),
            resource_uids=(UIDS[5],),
            allow_new_resources=True,
        ),
        "allowed_operations": (
            "workspace.edit",
            "workspace.checkpoint",
            "apply",
        ),
        "limits": MandateLimits(
            max_work_packages=20,
            max_changed_resources=100,
            max_changed_relations=200,
            max_external_actions=2,
            max_destructive_actions=0,
        ),
        "issued_at": NOW,
        "expires_at": NOW + timedelta(days=30),
    }
    value.update(updates)
    return MissionMandate.model_validate(value)


def facts(**updates: object) -> DecisionPolicyFacts:
    value: dict[str, object] = {
        "mission_uid": UIDS[1],
        "work_package_uid": UIDS[2],
        "operation": "workspace.edit",
        "engineering_area": "软件实现",
        "target_resource_uids": (UIDS[5],),
        "prospective_work_packages": 4,
        "prospective_changed_resources": 12,
        "prospective_changed_relations": 8,
        "validation": ValidationSummary(
            conclusion=ValidationConclusion.PASSED,
            summary="核心测试与规则校验通过",
            evidence=("87 项自动测试通过",),
        ),
        "impact": ImpactSummary(
            completeness=ImpactCompleteness.COMPLETE,
            summary="影响局限于本地进程管理模块",
            affected_areas=("软件实现",),
            affected_targets=("进程管理",),
        ),
    }
    value.update(updates)
    return DecisionPolicyFacts.model_validate(value)


def test_routine_work_auto_executes_under_an_active_mandate() -> None:
    decision = DecisionPolicy.decide(mandate(), facts(), evaluated_at=NOW)
    assert decision.disposition is DecisionDisposition.AUTO_EXECUTE
    assert decision.reasons == ("WITHIN_ACTIVE_MANDATE",)


def test_material_work_is_batched_until_a_real_milestone() -> None:
    decision = DecisionPolicy.decide(
        mandate(),
        facts(milestone_policy_codes=("ARCHITECTURE_BOUNDARY_CHANGED",)),
        evaluated_at=NOW,
    )
    assert decision.disposition is DecisionDisposition.BATCH_FOR_MILESTONE
    assert decision.reasons == ("ARCHITECTURE_BOUNDARY_CHANGED",)


def test_only_authority_or_mandate_boundaries_request_a_human_decision() -> None:
    decision = DecisionPolicy.decide(
        mandate(),
        facts(
            operation="baseline.apply",
            human_decision_policy_codes=("RELEASE_COMMITMENT",),
        ),
        evaluated_at=NOW,
    )
    assert decision.disposition is DecisionDisposition.HUMAN_DECISION_NOW
    assert decision.reasons == (
        "OPERATION_OUTSIDE_MANDATE",
        "RELEASE_COMMITMENT",
    )

    expired = DecisionPolicy.decide(
        mandate(expires_at=NOW + timedelta(seconds=1)),
        facts(),
        evaluated_at=NOW + timedelta(seconds=2),
    )
    assert expired.disposition is DecisionDisposition.HUMAN_DECISION_NOW
    assert expired.reasons == ("MANDATE_INACTIVE",)


def test_validation_or_impact_uncertainty_blocks_background_work_not_the_user() -> None:
    decision = DecisionPolicy.decide(
        mandate(),
        facts(
            validation=ValidationSummary(
                conclusion=ValidationConclusion.INDETERMINATE,
                summary="测试环境尚未建立",
            ),
            impact=ImpactSummary(
                completeness=ImpactCompleteness.INCOMPLETE,
                summary="仍需解析一项工程关系",
            ),
            human_decision_policy_codes=("RELEASE_COMMITMENT",),
        ),
        evaluated_at=NOW,
    )
    assert decision.disposition is DecisionDisposition.BLOCK
    assert decision.reasons == ("IMPACT_INCOMPLETE", "VALIDATION_INDETERMINATE")


def test_limits_and_scope_are_enforced_without_client_risk_authority() -> None:
    decision = DecisionPolicy.decide(
        mandate(),
        facts(
            engineering_area="系统需求",
            prospective_changed_resources=101,
            prospective_external_actions=3,
        ),
        evaluated_at=NOW,
    )
    assert decision.disposition is DecisionDisposition.HUMAN_DECISION_NOW
    assert decision.reasons == (
        "CHANGED_RESOURCE_LIMIT_EXCEEDED",
        "ENGINEERING_AREA_OUTSIDE_MANDATE",
        "EXTERNAL_ACTION_LIMIT_EXCEEDED",
    )

    raw = facts().model_dump(mode="json") | {"risk_class": "high"}
    with pytest.raises(ValidationError, match="risk_class"):
        DecisionPolicyFacts.model_validate(raw)
    assert "risk_class" not in DecisionPolicyFacts.model_fields


def test_mandate_and_decision_request_are_frozen_runtime_contracts_without_hashes() -> None:
    active = mandate()
    assert active.persistence_scope == "local_runtime"
    assert active.canonical_git_eligible is False
    assert all("hash" not in key for key in active.model_dump(mode="json"))
    with pytest.raises(ValidationError):
        active.title = "changed"

    request = DecisionRequest(
        decision_request_uid=UIDS[6],
        mission_uid=UIDS[1],
        work_package_uid=UIDS[2],
        mandate_uid=UIDS[0],
        decision_type="架构边界变更",
        engineering_area="软件架构",
        target=DecisionTarget(
            label="插件适配器边界",
            content_type="架构决策",
            engineering_key="ADR-0003",
        ),
        change_summary="把项目特有逻辑限制在独立适配器目录。",
        impact=ImpactSummary(
            completeness=ImpactCompleteness.COMPLETE,
            summary="影响适配器接口和三个后续实现工作包。",
            affected_areas=("软件架构", "软件实现"),
            affected_targets=("适配器接口", "插件目录"),
        ),
        validation=ValidationSummary(
            conclusion=ValidationConclusion.PASSED,
            summary="接口契约和回归测试通过。",
            evidence=("架构测试通过", "现有核心接口未变化"),
        ),
        recommendation="采用独立适配器边界，并在本里程碑一次确认。",
        alternatives=(
            DecisionAlternative(
                title="延后适配器工作",
                summary="本阶段只保留通用核心。",
                trade_off="交付范围缩小，但后续仍需重新评审接口。",
            ),
        ),
        triggered_policies=(
            TriggeredPolicy(
                policy_code="ARCHITECTURE_BOUNDARY_CHANGED",
                title="架构边界变化",
                explanation="该选择将约束多个实现工作包。",
            ),
        ),
        action=DecisionAction(
            operation="milestone.approve",
            label="确认采用该架构边界",
            result="当前里程碑内的后续适配器工作按该边界执行。",
        ),
        created_at=NOW,
    )
    raw = request.model_dump(mode="json")
    assert request.disposition is DecisionDisposition.HUMAN_DECISION_NOW
    assert "action" in raw and "actions" not in raw
    assert all("hash" not in key for key in raw)

    catalog = SchemaCatalog(Path(__file__).resolve().parents[1] / "schemas" / "v1")
    catalog.validate("mission-mandate.schema.json", active.model_dump(mode="json"))
    catalog.validate("decision-request.schema.json", raw)


def test_mandate_rejects_invalid_lifetime_and_decision_request_rejects_shortcuts() -> None:
    with pytest.raises(ValidationError, match="expires_at"):
        mandate(expires_at=NOW)
    with pytest.raises(ValidationError, match="UTC"):
        mandate(
            issued_at=datetime(2026, 8, 30),  # noqa: DTZ001 - contract rejects local time
            expires_at=datetime(2026, 8, 31),  # noqa: DTZ001 - contract rejects local time
        )
    with pytest.raises(ValidationError):
        DecisionRequest.model_validate(
            {
                "mission_uid": UIDS[1],
                "work_package_uid": UIDS[2],
                "mandate_uid": UIDS[0],
                "decision_type": "缺少完整内容",
                "engineering_area": "软件架构",
                "risk_class": "high",
                "actions": ["approve", "reject"],
            }
        )
