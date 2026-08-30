from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from lesr.application.contracts import WriteEnvelope
from lesr.domain.decision import DecisionDisposition
from lesr.domain.semantic import SemanticField
from lesr.domain.workspace import WorkingCopy, WorkingCopyState
from tests.support.public_product import PublicProduct, bootstrap_public_product


def _write(
    product: PublicProduct,
    key: str,
    operation: dict[str, object],
) -> WriteEnvelope:
    return WriteEnvelope(
        workspace_uid=product.workspace_uid,
        expected_base=product.domain.base,
        idempotency_key=key,
        actor=product.actor_uid,
        delegation_uid=product.delegation_uid,
        dry_run=False,
        operation=operation,
    )


def _running_mission(product: PublicProduct) -> tuple[str, str]:
    created = product.domain.create_mission(
        {
            "title": "边缘遥测工程",
            "objective": "完成事件接口设计",
            "initiated_by_actor_uid": product.actor_uid,
            "configuration_uid": product.configuration_uid,
            "engineering_areas": ["软件实现"],
            "allowed_operations": ["workspace.validate", "workspace.submit"],
            "packages": [
                {
                    "key": "interface-design",
                    "title": "设计事件接口",
                    "objective": "整理接口并验证候选内容",
                    "role": "architecture",
                    "engineering_area": "软件实现",
                    "workspace_uid": product.workspace_uid,
                }
            ],
        }
    )
    assert created.ok, created.payload()
    mission_uid = str(created.value["mission_uid"])
    work_package_uid = str(created.value["work_packages"][0]["work_package_uid"])
    claimed = product.domain.claim_mission_work(
        mission_uid,
        work_package_uid,
        "architecture-agent",
        "configured-provider",
        "configured-model",
        "test-client",
    )
    assert claimed.ok, claimed.payload()
    return mission_uid, work_package_uid


def _workspace_with_design(product: PublicProduct) -> None:
    opened = product.domain.open_workspace(
        _write(
            product,
            "mission-evaluation-open",
            {"configuration_uid": product.configuration_uid},
        )
    )
    assert opened.ok, opened.payload()
    copy = WorkingCopy(
        workspace_uid=product.workspace_uid,
        object_uid="018f0000-0000-7000-8000-000000000998",
        base_revision_uid=None,
        human_key="DES-EVENT-001",
        kind="software_design",
        effective_model_hash=str(opened.value["effective_model_hash"]),
        delegation_uid=product.delegation_uid,
        draft_fields=(SemanticField(path="/statement", value="Define event interface"),),
    )
    edited = product.domain.propose_operation(
        _write(
            product,
            "mission-evaluation-edit",
            {
                "operation_type": "create_object",
                "working_copy": copy.model_dump(mode="json"),
            },
        )
    )
    assert edited.ok, edited.payload()


def _workspace_with_unverified_requirement(product: PublicProduct) -> None:
    opened = product.domain.open_workspace(
        _write(
            product,
            "mission-block-open",
            {"configuration_uid": product.configuration_uid},
        )
    )
    assert opened.ok, opened.payload()
    copy = WorkingCopy(
        workspace_uid=product.workspace_uid,
        object_uid="018f0000-0000-7000-8000-000000000997",
        base_revision_uid=None,
        human_key="REQ-EVENT-001",
        kind="software_requirement",
        effective_model_hash=str(opened.value["effective_model_hash"]),
        delegation_uid=product.delegation_uid,
        draft_fields=(
            SemanticField(path="/statement", value="Reconnect after link loss"),
            SemanticField(path="/safety_level", value="ASIL-B"),
        ),
    )
    edited = product.domain.propose_operation(
        _write(
            product,
            "mission-block-edit",
            {
                "operation_type": "create_object",
                "working_copy": copy.model_dump(mode="json"),
            },
        )
    )
    assert edited.ok, edited.payload()


def test_real_workspace_evidence_routes_auto_batch_and_human_decisions(
    tmp_path: Path,
) -> None:
    product = bootstrap_public_product(tmp_path)
    _workspace_with_design(product)
    mission_uid, work_package_uid = _running_mission(product)
    evaluated_at = datetime.now(UTC).isoformat()

    automatic = product.domain.evaluate_mission_work(
        mission_uid,
        work_package_uid,
        product.workspace_uid,
        evaluated_at,
        "workspace.validate",
    )
    assert automatic.ok, automatic.payload()
    assert automatic.value["policy"]["disposition"] == DecisionDisposition.AUTO_EXECUTE
    assert automatic.value["workspace_assessment"]["candidate_frozen"] is False

    milestone = product.domain.evaluate_mission_work(
        mission_uid,
        work_package_uid,
        product.workspace_uid,
        evaluated_at,
        "workspace.submit",
    )
    assert milestone.ok, milestone.payload()
    assert milestone.value["policy"]["disposition"] == (
        DecisionDisposition.BATCH_FOR_MILESTONE
    )

    narrative = {
        "decision_type": "交付边界",
        "target": {
            "label": "边缘遥测接口",
            "content_type": "架构设计",
            "engineering_key": "DES-EVENT-001",
        },
        "change_summary": "决定是否把当前候选内容直接发布为基线。",
        "recommendation": "先完成工作包审阅，再发布基线。",
        "alternatives": [
            {
                "title": "继续发布",
                "summary": "按当前候选内容进入基线流程。",
                "trade_off": "缩短交付时间，但减少复核时间。",
            }
        ],
        "action": {
            "operation": "baseline.apply",
            "label": "先完成工作包审阅",
            "result": "工作包保持运行并补充审阅材料。",
        },
    }
    rejected_injection = product.domain.evaluate_mission_work(
        mission_uid,
        work_package_uid,
        product.workspace_uid,
        evaluated_at,
        "baseline.apply",
        narrative | {"triggered_policies": [{"policy_code": "CALLER_SELECTED"}]},
    )
    assert not rejected_injection.ok
    assert rejected_injection.error is not None
    assert rejected_injection.error.code == "LESR-MISSION-EVALUATION-INVALID"

    human = product.domain.evaluate_mission_work(
        mission_uid,
        work_package_uid,
        product.workspace_uid,
        evaluated_at,
        "baseline.apply",
        narrative,
    )
    assert human.ok, human.payload()
    assert human.value["policy"]["disposition"] == (
        DecisionDisposition.HUMAN_DECISION_NOW
    )
    request = human.value["route"]["decision_request"]
    assert [item["policy_code"] for item in request["triggered_policies"]] == [
        "OPERATION_OUTSIDE_MANDATE"
    ]
    assert product.domain.workspaces[product.workspace_uid].working_copies[0].state is (
        WorkingCopyState.EDITABLE
    )
    inbox = product.domain.list_decisions(mission_uid)
    assert inbox.ok
    assert [item["decision_request_uid"] for item in inbox.value] == [
        request["decision_request_uid"]
    ]


def test_mission_plan_rejects_package_outside_its_engineering_scope(
    tmp_path: Path,
) -> None:
    product = bootstrap_public_product(tmp_path)
    result = product.domain.create_mission(
        {
            "title": "越界任务",
            "objective": "验证工程范围",
            "initiated_by_actor_uid": product.actor_uid,
            "engineering_areas": ["软件实现"],
            "allowed_operations": ["workspace.validate"],
            "packages": [
                {
                    "key": "security",
                    "title": "威胁建模",
                    "objective": "分析威胁",
                    "role": "security",
                    "engineering_area": "信息安全",
                }
            ],
        }
    )
    assert not result.ok
    assert result.error is not None
    assert result.error.code == "LESR-MISSION-PLAN-INVALID"


def test_real_workspace_failure_routes_back_to_the_agent(tmp_path: Path) -> None:
    product = bootstrap_public_product(tmp_path)
    _workspace_with_unverified_requirement(product)
    mission_uid, work_package_uid = _running_mission(product)

    blocked = product.domain.evaluate_mission_work(
        mission_uid,
        work_package_uid,
        product.workspace_uid,
        datetime.now(UTC).isoformat(),
        "workspace.validate",
    )

    assert blocked.ok, blocked.payload()
    assert blocked.value["policy"]["disposition"] == DecisionDisposition.BLOCK
    assert blocked.value["route"]["decision_request"] is None
    assert blocked.value["route"]["agent_correction_reasons"] == [
        "VALIDATION_FAILED"
    ]
    assert product.domain.list_decisions(mission_uid).value == ()
    assert product.domain.workspaces[product.workspace_uid].working_copies[0].state is (
        WorkingCopyState.EDITABLE
    )
