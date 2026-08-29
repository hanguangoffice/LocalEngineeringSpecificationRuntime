from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from lesr.adapters.mission_store import MissionStore
from lesr.adapters.operations import TaskStore
from lesr.domain.decision import (
    DecisionAction,
    DecisionAlternative,
    DecisionRequest,
    DecisionResolution,
    DecisionTarget,
    ImpactCompleteness,
    ImpactSummary,
    MandateScope,
    MissionMandate,
    TriggeredPolicy,
    ValidationConclusion,
    ValidationSummary,
)
from lesr.domain.mission import (
    AgentRun,
    AgentRunEngine,
    Mission,
    MissionEngine,
    WorkPackage,
)
from lesr.domain.semantic import canonical_json

NOW = datetime(2026, 8, 30, 2, 0, tzinfo=UTC)
UIDS = [f"018f2000-0000-7000-8000-{index:012d}" for index in range(1, 40)]


def work_package(mission_uid: str, index: int) -> WorkPackage:
    return WorkPackage(
        work_package_uid=UIDS[index],
        mission_uid=mission_uid,
        title=f"工作包 {index}",
        objective=f"完成工作包 {index}",
        role="engineering",
        created_at=NOW,
        updated_at=NOW,
    )


def mission(
    mission_index: int = 0,
    *,
    package_indexes: tuple[int, ...] = (1, 2),
) -> Mission:
    mission_uid = UIDS[mission_index]
    return Mission(
        mission_uid=mission_uid,
        title=f"Mission {mission_index}",
        objective="完成本地工程目标",
        initiated_by_actor_uid="local-user",
        work_packages=tuple(
            work_package(mission_uid, index) for index in package_indexes
        ),
        created_at=NOW,
        updated_at=NOW,
    )


def mandate(value: Mission) -> MissionMandate:
    return MissionMandate(
        mandate_uid=UIDS[10],
        mission_uid=value.mission_uid,
        title="本次 Mission 授权范围",
        issued_by_actor_uid="local-user",
        scope=MandateScope(engineering_areas=("软件实现",)),
        allowed_operations=("workspace.edit", "workspace.validate"),
        issued_at=NOW,
        expires_at=NOW + timedelta(days=7),
    )


def agent_run(value: Mission, package_index: int = 1) -> AgentRun:
    return AgentRun(
        agent_run_uid=UIDS[11],
        mission_uid=value.mission_uid,
        work_package_uid=UIDS[package_index],
        role="implementation",
        provider="local-agent-host",
        model_identifier="configured-model",
        client="lesr",
        created_at=NOW,
        updated_at=NOW,
    )


def decision_request(value: Mission, authority: MissionMandate) -> DecisionRequest:
    return DecisionRequest(
        decision_request_uid=UIDS[12],
        mission_uid=value.mission_uid,
        work_package_uid=UIDS[1],
        mandate_uid=authority.mandate_uid,
        decision_type="架构边界",
        engineering_area="软件实现",
        target=DecisionTarget(
            label="适配器边界",
            content_type="架构决策",
            engineering_key="ADR-001",
        ),
        change_summary="确认项目特有逻辑保留在适配器目录。",
        impact=ImpactSummary(
            completeness=ImpactCompleteness.COMPLETE,
            summary="影响三个适配器工作包。",
            affected_areas=("软件实现",),
        ),
        validation=ValidationSummary(
            conclusion=ValidationConclusion.PASSED,
            summary="边界测试通过。",
        ),
        recommendation="采用独立适配器边界。",
        alternatives=(
            DecisionAlternative(
                title="延后适配器",
                summary="当前只实现通用核心。",
                trade_off="交付范围缩小。",
            ),
        ),
        triggered_policies=(
            TriggeredPolicy(
                policy_code="ARCHITECTURE_BOUNDARY_CHANGED",
                title="架构边界变化",
                explanation="该决定约束后续工作包。",
            ),
        ),
        action=DecisionAction(
            operation="milestone.approve",
            label="确认架构边界",
            result="后续工作包按该边界执行。",
        ),
        created_at=NOW,
    )


def resolution(request: DecisionRequest, *, index: int = 13) -> DecisionResolution:
    return DecisionResolution(
        decision_resolution_uid=UIDS[index],
        decision_request_uid=request.decision_request_uid,
        selected_action=request.action.operation,
        decided_by_actor_uid="local-user",
        reason="该边界便于独立维护适配器。",
        decided_at=NOW + timedelta(minutes=5),
    )


def test_store_uses_runtime_database_without_changing_task_tables(tmp_path: Path) -> None:
    project = tmp_path / "project"
    task_store = TaskStore(project)
    with sqlite3.connect(task_store.path) as connection:
        before = connection.execute(
            "SELECT name, sql FROM sqlite_master "
            "WHERE type = 'table' AND name LIKE 'task_%' ORDER BY name"
        ).fetchall()

    store = MissionStore(project)

    assert store.path == project / ".lesr" / "runtime.sqlite3"
    assert not (project / ".git").exists()
    with sqlite3.connect(store.path) as connection:
        after = connection.execute(
            "SELECT name, sql FROM sqlite_master "
            "WHERE type = 'table' AND name LIKE 'task_%' ORDER BY name"
        ).fetchall()
        agentic_tables = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type = 'table' AND name LIKE 'agentic_%'"
            ).fetchall()
        }
        for table in agentic_tables:
            columns = connection.execute(f"PRAGMA table_info({table})").fetchall()
            assert all("hash" not in str(column[1]) for column in columns)
    assert after == before
    assert agentic_tables == {
        "agentic_agent_runs",
        "agentic_decision_requests",
        "agentic_decision_resolutions",
        "agentic_mandates",
        "agentic_missions",
        "agentic_work_packages",
    }


def test_runtime_records_round_trip_and_recover_after_restart(tmp_path: Path) -> None:
    project = tmp_path / "project"
    store = MissionStore(project)
    first = mission()
    second = mission(3, package_indexes=(4,))
    authority = mandate(first)
    run = agent_run(first)
    request = decision_request(first, authority)

    store.put_mission(second)
    store.put_mission(first)
    store.put_mission_mandate(authority)
    store.put_agent_run(run)
    store.put_decision_request(request)

    restarted = MissionStore(project)
    assert restarted.get_mission(first.mission_uid) == first
    assert restarted.list_missions() == (first, second)
    assert restarted.get_mandate(authority.mandate_uid) == authority
    assert restarted.get_agent_run(run.agent_run_uid) == run
    assert restarted.list_agent_runs(first.mission_uid) == (run,)
    assert restarted.list_agent_runs(work_package_uid=run.work_package_uid) == (run,)
    assert restarted.get_decision_request(request.decision_request_uid) == request
    assert restarted.list_decision_requests(first.mission_uid) == (request,)
    assert restarted.list_decision_requests(first.mission_uid, unresolved_only=True) == (
        request,
    )

    with sqlite3.connect(store.path) as connection:
        raw = str(
            connection.execute(
                "SELECT value FROM agentic_missions WHERE mission_uid = ?",
                (first.mission_uid,),
            ).fetchone()[0]
        )
    assert raw == canonical_json(first)
    assert "hash" not in raw


def test_mutable_runtime_state_updates_transactionally(tmp_path: Path) -> None:
    store = MissionStore(tmp_path / "project")
    original = mission()
    store.put_mission(original)
    updated = MissionEngine.reconcile(original, updated_at=NOW + timedelta(seconds=1))
    store.put_mission(updated)
    assert store.get_mission(original.mission_uid) == updated

    original_mandate = mandate(updated)
    store.put_mandate(original_mandate)
    revoked_mandate = MissionMandate.model_validate(
        original_mandate.model_dump(mode="python")
        | {"revoked_at": NOW + timedelta(minutes=1)}
    )
    store.put_mandate(revoked_mandate)
    assert store.get_mission_mandate(original_mandate.mandate_uid) == revoked_mandate

    queued = agent_run(updated)
    store.put_agent_run(queued)
    running = AgentRunEngine.start(queued, started_at=NOW + timedelta(seconds=2))
    store.put_agent_run(running)
    assert store.get_agent_run(queued.agent_run_uid) == running


def test_decision_resolution_is_separate_and_request_is_immutable(tmp_path: Path) -> None:
    store = MissionStore(tmp_path / "project")
    value = mission()
    authority = mandate(value)
    request = decision_request(value, authority)
    store.put_mission(value)
    store.put_mandate(authority)
    store.put_decision_request(request)

    with sqlite3.connect(store.path) as connection:
        before = str(
            connection.execute(
                "SELECT value FROM agentic_decision_requests "
                "WHERE decision_request_uid = ?",
                (request.decision_request_uid,),
            ).fetchone()[0]
        )

    recorded = resolution(request)
    assert store.record_decision_resolution(recorded) == recorded
    assert store.record_decision_resolution(recorded) == recorded
    assert (
        store.get_decision_resolution(recorded.decision_resolution_uid) == recorded
    )
    assert store.decision_resolution_for(request.decision_request_uid) == recorded
    assert store.list_decision_resolutions() == (recorded,)
    assert store.list_decision_requests(value.mission_uid, unresolved_only=True) == ()
    assert recorded.canonical_git_eligible is False
    assert all("hash" not in key for key in recorded.model_dump(mode="json"))
    restarted = MissionStore(tmp_path / "project")
    assert restarted.decision_resolution_for(request.decision_request_uid) == recorded

    with sqlite3.connect(store.path) as connection:
        after = str(
            connection.execute(
                "SELECT value FROM agentic_decision_requests "
                "WHERE decision_request_uid = ?",
                (request.decision_request_uid,),
            ).fetchone()[0]
        )
    assert after == before
    assert store.get_decision_request(request.decision_request_uid) == request

    changed = DecisionRequest.model_validate(
        request.model_dump(mode="python") | {"recommendation": "改变原始请求"}
    )
    with pytest.raises(ValueError, match="IMMUTABLE"):
        store.put_decision_request(changed)
    with pytest.raises(ValueError, match="ALREADY-RESOLVED"):
        store.record_decision_resolution(resolution(request, index=14))


def test_foreign_keys_reject_orphans_and_failed_update_rolls_back(tmp_path: Path) -> None:
    store = MissionStore(tmp_path / "project")
    value = mission()
    with pytest.raises(sqlite3.IntegrityError):
        store.put_mandate(mandate(value))

    store.put_mission(value)
    run = agent_run(value, package_index=2)
    store.put_agent_run(run)
    shortened = Mission.model_validate(
        value.model_dump(mode="python")
        | {
            "work_packages": (value.work_packages[0],),
            "updated_at": NOW + timedelta(minutes=1),
        }
    )

    with pytest.raises(sqlite3.IntegrityError):
        store.put_mission(shortened)

    assert store.get_mission(value.mission_uid) == value
    assert store.get_agent_run(run.agent_run_uid) == run
