from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from lesr.adapters.schemas import SchemaCatalog
from lesr.domain.mission import (
    AgentRun,
    AgentRunEngine,
    AgentRunState,
    Mission,
    MissionEngine,
    MissionState,
    WorkPackage,
    WorkPackageState,
)

NOW = datetime(2026, 8, 30, 0, 0, tzinfo=UTC)
UIDS = [f"018f0000-0000-7000-8000-{index:012d}" for index in range(1, 30)]


def package(
    mission_uid: str,
    index: int,
    *,
    dependencies: tuple[str, ...] = (),
) -> WorkPackage:
    return WorkPackage(
        work_package_uid=UIDS[index],
        mission_uid=mission_uid,
        title=f"工作包 {index}",
        objective=f"完成工作包 {index}",
        role="engineering",
        dependency_uids=dependencies,
        created_at=NOW,
        updated_at=NOW,
    )


def branched_mission() -> Mission:
    mission_uid = UIDS[0]
    first_root = package(mission_uid, 1)
    first_child = package(mission_uid, 2, dependencies=(first_root.work_package_uid,))
    second_root = package(mission_uid, 3)
    second_child = package(mission_uid, 4, dependencies=(second_root.work_package_uid,))
    return Mission(
        mission_uid=mission_uid,
        title="并行工程任务",
        objective="验证分支局部失败",
        initiated_by_actor_uid="local-user",
        work_packages=(first_root, first_child, second_root, second_child),
        created_at=NOW,
        updated_at=NOW,
    )


def state_by_uid(mission: Mission) -> dict[str, WorkPackageState]:
    return {item.work_package_uid: item.state for item in mission.work_packages}


def test_mission_contract_is_frozen_and_explicitly_runtime_only() -> None:
    mission = MissionEngine.reconcile(branched_mission(), updated_at=NOW)
    assert mission.persistence_scope == "local_runtime"
    assert mission.canonical_git_eligible is False
    assert all(not item.canonical_git_eligible for item in mission.work_packages)
    assert all("hash" not in key for key in mission.model_dump(mode="json"))
    with pytest.raises(ValidationError):
        mission.state = MissionState.COMPLETED


def test_mission_rejects_unknown_dependencies_and_cycles() -> None:
    mission_uid = UIDS[0]
    with pytest.raises(ValidationError, match="unknown dependencies"):
        Mission(
            mission_uid=mission_uid,
            title="错误依赖",
            objective="拒绝未知节点",
            initiated_by_actor_uid="local-user",
            work_packages=(package(mission_uid, 1, dependencies=(UIDS[9],)),),
            created_at=NOW,
            updated_at=NOW,
        )
    first = package(mission_uid, 1, dependencies=(UIDS[2],))
    second = package(mission_uid, 2, dependencies=(UIDS[1],))
    with pytest.raises(ValidationError, match="cycle"):
        Mission(
            mission_uid=mission_uid,
            title="循环依赖",
            objective="拒绝循环",
            initiated_by_actor_uid="local-user",
            work_packages=(first, second),
            created_at=NOW,
            updated_at=NOW,
        )


def test_failure_blocks_only_dependants_while_independent_branch_continues() -> None:
    mission = MissionEngine.reconcile(branched_mission(), updated_at=NOW)
    assert mission.ready_work_package_uids == (UIDS[1], UIDS[3])

    mission = MissionEngine.start_package(
        mission, UIDS[1], updated_at=NOW + timedelta(seconds=1)
    )
    mission = MissionEngine.fail_package(
        mission,
        UIDS[1],
        "实现失败",
        updated_at=NOW + timedelta(seconds=2),
    )
    states = state_by_uid(mission)
    assert states[UIDS[1]] is WorkPackageState.FAILED
    assert states[UIDS[2]] is WorkPackageState.BLOCKED
    assert states[UIDS[3]] is WorkPackageState.READY
    assert mission.state is MissionState.RUNNING

    mission = MissionEngine.start_package(
        mission, UIDS[3], updated_at=NOW + timedelta(seconds=3)
    )
    mission = MissionEngine.complete_package(
        mission, UIDS[3], updated_at=NOW + timedelta(seconds=4)
    )
    assert state_by_uid(mission)[UIDS[4]] is WorkPackageState.READY
    mission = MissionEngine.start_package(
        mission, UIDS[4], updated_at=NOW + timedelta(seconds=5)
    )
    mission = MissionEngine.complete_package(
        mission, UIDS[4], updated_at=NOW + timedelta(seconds=6)
    )
    assert mission.state is MissionState.FAILED
    assert state_by_uid(mission)[UIDS[4]] is WorkPackageState.COMPLETED


def test_decision_wait_does_not_pause_an_independent_ready_branch() -> None:
    mission = MissionEngine.reconcile(branched_mission(), updated_at=NOW)
    mission = MissionEngine.start_package(
        mission, UIDS[1], updated_at=NOW + timedelta(seconds=1)
    )
    mission = MissionEngine.wait_for_decision(
        mission, UIDS[1], updated_at=NOW + timedelta(seconds=2)
    )
    assert mission.state is MissionState.RUNNING
    assert state_by_uid(mission)[UIDS[3]] is WorkPackageState.READY
    resumed = MissionEngine.resume_package(
        mission, UIDS[1], updated_at=NOW + timedelta(seconds=3)
    )
    assert state_by_uid(resumed)[UIDS[1]] is WorkPackageState.RUNNING


def test_agent_run_lifecycle_is_local_frozen_and_utc() -> None:
    run = AgentRun(
        agent_run_uid=UIDS[10],
        mission_uid=UIDS[0],
        work_package_uid=UIDS[1],
        role="verification",
        provider="local-agent-host",
        model_identifier="configured-model",
        client="lesr",
        created_at=NOW,
        updated_at=NOW,
    )
    running = AgentRunEngine.start(run, started_at=NOW + timedelta(seconds=1))
    completed = AgentRunEngine.complete(
        running,
        "验证通过",
        finished_at=NOW + timedelta(seconds=2),
    )
    assert completed.state is AgentRunState.COMPLETED
    assert completed.canonical_git_eligible is False
    assert "hash" not in completed.model_dump(mode="json")
    with pytest.raises(ValidationError, match="UTC"):
        AgentRun(
            mission_uid=UIDS[0],
            work_package_uid=UIDS[1],
            role="verification",
            provider="local-agent-host",
            model_identifier="configured-model",
            client="lesr",
            created_at=datetime(2026, 8, 30),  # noqa: DTZ001 - rejects naive time
            updated_at=datetime(2026, 8, 30),  # noqa: DTZ001 - rejects naive time
        )


def test_runtime_contracts_match_their_json_schemas() -> None:
    root = Path(__file__).resolve().parents[1] / "schemas" / "v1"
    catalog = SchemaCatalog(root)
    mission = MissionEngine.reconcile(branched_mission(), updated_at=NOW)
    run = AgentRun(
        agent_run_uid=UIDS[10],
        mission_uid=UIDS[0],
        work_package_uid=UIDS[1],
        role="engineering",
        provider="local-agent-host",
        model_identifier="configured-model",
        client="lesr",
        created_at=NOW,
        updated_at=NOW,
    )
    catalog.validate("mission.schema.json", mission.model_dump(mode="json"))
    for item in mission.work_packages:
        catalog.validate("work-package.schema.json", item.model_dump(mode="json"))
    catalog.validate("agent-run.schema.json", run.model_dump(mode="json"))
