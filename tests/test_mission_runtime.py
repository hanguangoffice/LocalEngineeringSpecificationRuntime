from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier
from typing import Literal

import pytest
from pydantic import ValidationError

from lesr.adapters.mission_store import MissionConcurrencyError, MissionStore
from lesr.application.agent_broker import AgentReport
from lesr.application.mission_runtime import (
    MissionCoordinator,
    MissionPackagePlan,
    MissionPlan,
)
from lesr.domain.decision import (
    DecisionAction,
    DecisionAlternative,
    DecisionDisposition,
    DecisionPolicyFacts,
    DecisionPolicyResult,
    DecisionRequestFactoryResult,
    DecisionRequestNarrative,
    DecisionResolution,
    DecisionTarget,
    ImpactCompleteness,
    ImpactSummary,
    TriggeredPolicy,
    ValidationConclusion,
    ValidationSummary,
)
from lesr.domain.mission import (
    AgentRun,
    AgentRunState,
    Mission,
    MissionState,
    WorkPackage,
    WorkPackageState,
)

NOW = datetime(2026, 8, 30, 8, 0, tzinfo=UTC)


def branched_plan() -> MissionPlan:
    return MissionPlan(
        title="并行工程 Mission",
        objective="完成两条彼此独立的工程分支",
        initiated_by_actor_uid="local-user",
        configuration_uid="configuration-1",
        engineering_areas=("软件实现",),
        allowed_operations=("workspace.edit", "workspace.validate"),
        packages=(
            MissionPackagePlan(
                key="analysis-a",
                title="分析 A",
                objective="分析第一条分支",
                role="analysis",
            ),
            MissionPackagePlan(
                key="implement-a",
                title="实现 A",
                objective="实现第一条分支",
                role="implementation",
                depends_on=("analysis-a",),
            ),
            MissionPackagePlan(
                key="analysis-b",
                title="分析 B",
                objective="分析第二条分支",
                role="analysis",
            ),
            MissionPackagePlan(
                key="implement-b",
                title="实现 B",
                objective="实现第二条分支",
                role="implementation",
                depends_on=("analysis-b",),
            ),
        ),
    )


def single_package_plan() -> MissionPlan:
    return MissionPlan(
        title="单工作包 Mission",
        objective="验证领取与决策路由",
        initiated_by_actor_uid="local-user",
        engineering_areas=("软件实现",),
        allowed_operations=("workspace.edit", "workspace.validate"),
        packages=(
            MissionPackagePlan(
                key="implementation",
                title="实现",
                objective="完成实现",
                role="implementation",
            ),
        ),
    )


def package_by_title(mission: Mission, title: str) -> WorkPackage:
    return next(item for item in mission.work_packages if item.title == title)


def claim(
    coordinator: MissionCoordinator,
    mission: Mission,
    package: WorkPackage,
    *,
    at: datetime,
    identity: str = "agent-1",
) -> AgentRun:
    result = coordinator.claim(
        mission.mission_uid,
        package.work_package_uid,
        agent_identity=identity,
        provider="local-provider",
        model_identifier="configured-model",
        client="test-client",
        claimed_at=at,
    )
    run = result["agent_run"]
    assert isinstance(run, AgentRun)
    return run


def report(
    coordinator: MissionCoordinator,
    run: AgentRun,
    *,
    state: Literal[AgentRunState.COMPLETED, AgentRunState.FAILED],
    at: datetime,
) -> Mission:
    result = coordinator.report(
        AgentReport(
            mission_uid=run.mission_uid,
            work_package_uid=run.work_package_uid,
            agent_run_uid=run.agent_run_uid,
            state=state,
            result_summary="工作完成" if state is AgentRunState.COMPLETED else None,
            error_summary="执行失败" if state is AgentRunState.FAILED else None,
            reported_at=at,
        )
    )
    mission = result["mission"]
    assert isinstance(mission, Mission)
    return mission


def decision_facts(
    mission: Mission,
    package: WorkPackage,
    *,
    validation: ValidationConclusion = ValidationConclusion.PASSED,
    human_policy_codes: tuple[str, ...] = (),
) -> DecisionPolicyFacts:
    return DecisionPolicyFacts(
        mission_uid=mission.mission_uid,
        work_package_uid=package.work_package_uid,
        operation="workspace.edit",
        engineering_area="软件实现",
        prospective_work_packages=len(mission.work_packages),
        prospective_changed_resources=1,
        prospective_changed_relations=0,
        validation=ValidationSummary(
            conclusion=validation,
            summary="候选内容校验完成",
        ),
        impact=ImpactSummary(
            completeness=ImpactCompleteness.COMPLETE,
            summary="影响局限于当前工作包",
            affected_areas=("软件实现",),
        ),
        human_decision_policy_codes=human_policy_codes,
    )


def decision_narrative() -> DecisionRequestNarrative:
    return DecisionRequestNarrative(
        decision_type="架构边界",
        target=DecisionTarget(
            label="适配器边界",
            content_type="架构决策",
            engineering_key="ADR-001",
        ),
        change_summary="确认项目特有逻辑保留在独立适配器目录。",
        recommendation="采用独立适配器边界。",
        alternatives=(
            DecisionAlternative(
                title="延后适配器",
                summary="本阶段只实现通用核心。",
                trade_off="交付范围缩小。",
            ),
        ),
        triggered_policies=(
            TriggeredPolicy(
                policy_code="ARCHITECTURE_BOUNDARY_CHANGED",
                title="架构边界变化",
                explanation="该选择约束后续工作包。",
            ),
        ),
        action=DecisionAction(
            operation="workspace.edit",
            label="确认采用该边界",
            result="当前工作包按该边界继续。",
        ),
    )


def test_create_builds_a_persisted_dag_and_rejects_cycles(tmp_path: Path) -> None:
    project = tmp_path / "project"
    coordinator = MissionCoordinator(MissionStore(project))
    created = coordinator.create(branched_plan(), created_at=NOW)

    assert created.state is MissionState.RUNNING
    assert {item.work_package_title for item in coordinator.assignments(created.mission_uid)} == {
        "分析 A",
        "分析 B",
    }
    assert MissionCoordinator(MissionStore(project)).inspect(created.mission_uid) == created
    assert coordinator.store.get_mandate(created.delegation_uid or "").mission_uid == (
        created.mission_uid
    )

    cyclic = MissionPlan(
        title="循环 Mission",
        objective="拒绝循环依赖",
        initiated_by_actor_uid="local-user",
        engineering_areas=("软件实现",),
        allowed_operations=("workspace.edit",),
        packages=(
            MissionPackagePlan(
                key="a",
                title="A",
                objective="A",
                role="analysis",
                depends_on=("b",),
            ),
            MissionPackagePlan(
                key="b",
                title="B",
                objective="B",
                role="analysis",
                depends_on=("a",),
            ),
        ),
    )
    with pytest.raises(ValidationError, match="cycle"):
        coordinator.create(cyclic, created_at=NOW)


def test_concurrent_claim_allows_exactly_one_agent_run(tmp_path: Path) -> None:
    project = tmp_path / "project"
    creator = MissionCoordinator(MissionStore(project))
    mission = creator.create(single_package_plan(), created_at=NOW)
    package = mission.work_packages[0]
    rendezvous = Barrier(2)

    class ContendedStore(MissionStore):
        def put_execution_state(
            self,
            updated: Mission,
            run: AgentRun,
            *,
            expected_mission: Mission,
        ) -> None:
            rendezvous.wait(timeout=5)
            super().put_execution_state(
                updated,
                run,
                expected_mission=expected_mission,
            )

    coordinators = (
        MissionCoordinator(ContendedStore(project)),
        MissionCoordinator(ContendedStore(project)),
    )

    def attempt(index: int) -> AgentRun | Exception:
        try:
            return claim(
                coordinators[index],
                mission,
                package,
                at=NOW + timedelta(seconds=1),
                identity=f"agent-{index}",
            )
        except Exception as error:  # noqa: BLE001 - concurrent loser is asserted below
            return error

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = tuple(executor.map(attempt, (0, 1)))

    winners = tuple(item for item in outcomes if isinstance(item, AgentRun))
    losers = tuple(item for item in outcomes if isinstance(item, Exception))
    assert len(winners) == 1
    assert len(losers) == 1
    assert isinstance(losers[0], MissionConcurrencyError)
    stored = MissionStore(project)
    assert stored.list_agent_runs(mission.mission_uid) == winners
    current = stored.get_mission(mission.mission_uid)
    current_package = current.work_packages[0]
    assert current_package.state is WorkPackageState.RUNNING
    assert current_package.agent_run_uids == (winners[0].agent_run_uid,)


def test_failure_propagates_only_on_its_branch_and_other_branch_completes(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    coordinator = MissionCoordinator(MissionStore(project))
    mission = coordinator.create(branched_plan(), created_at=NOW)
    root_a = package_by_title(mission, "分析 A")
    root_b = package_by_title(mission, "分析 B")
    run_a = claim(coordinator, mission, root_a, at=NOW + timedelta(seconds=1))
    mission = coordinator.inspect(mission.mission_uid)
    run_b = claim(coordinator, mission, root_b, at=NOW + timedelta(seconds=2))

    mission = report(
        coordinator,
        run_a,
        state=AgentRunState.FAILED,
        at=NOW + timedelta(seconds=3),
    )
    assert package_by_title(mission, "分析 A").state is WorkPackageState.FAILED
    assert package_by_title(mission, "实现 A").state is WorkPackageState.BLOCKED
    assert package_by_title(mission, "分析 B").state is WorkPackageState.RUNNING
    assert mission.state is MissionState.RUNNING

    mission = report(
        coordinator,
        run_b,
        state=AgentRunState.COMPLETED,
        at=NOW + timedelta(seconds=4),
    )
    child_b = package_by_title(mission, "实现 B")
    assert child_b.state is WorkPackageState.READY
    run_child = claim(
        coordinator,
        mission,
        child_b,
        at=NOW + timedelta(seconds=5),
    )
    final = report(
        coordinator,
        run_child,
        state=AgentRunState.COMPLETED,
        at=NOW + timedelta(seconds=6),
    )
    assert final.state is MissionState.FAILED
    assert package_by_title(final, "实现 B").state is WorkPackageState.COMPLETED
    assert MissionCoordinator(MissionStore(project)).inspect(final.mission_uid) == final
    assert {item.state for item in coordinator.store.list_agent_runs(final.mission_uid)} == {
        AgentRunState.COMPLETED,
        AgentRunState.FAILED,
    }


def test_decision_routes_auto_block_human_and_recovers_resolution(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    coordinator = MissionCoordinator(MissionStore(project))
    mission = coordinator.create(single_package_plan(), created_at=NOW)
    package = mission.work_packages[0]
    claim(coordinator, mission, package, at=NOW + timedelta(seconds=1))
    running = coordinator.inspect(mission.mission_uid)
    package = running.work_packages[0]

    automatic = coordinator.route_decision(
        running.mission_uid,
        package.work_package_uid,
        decision_facts(running, package),
        None,
        evaluated_at=NOW + timedelta(seconds=2),
    )
    automatic_policy = automatic["policy"]
    automatic_route = automatic["route"]
    assert isinstance(automatic_policy, DecisionPolicyResult)
    assert isinstance(automatic_route, DecisionRequestFactoryResult)
    assert automatic_policy.disposition is DecisionDisposition.AUTO_EXECUTE
    assert automatic_route.decision_request is None

    blocked = coordinator.route_decision(
        running.mission_uid,
        package.work_package_uid,
        decision_facts(
            running,
            package,
            validation=ValidationConclusion.INDETERMINATE,
        ),
        None,
        evaluated_at=NOW + timedelta(seconds=3),
    )
    blocked_policy = blocked["policy"]
    blocked_route = blocked["route"]
    assert isinstance(blocked_policy, DecisionPolicyResult)
    assert isinstance(blocked_route, DecisionRequestFactoryResult)
    assert blocked_policy.disposition is DecisionDisposition.BLOCK
    assert blocked_route.agent_correction_reasons == ("VALIDATION_INDETERMINATE",)
    assert coordinator.decision_inbox(running.mission_uid) == ()

    human = coordinator.route_decision(
        running.mission_uid,
        package.work_package_uid,
        decision_facts(
            running,
            package,
            human_policy_codes=("ARCHITECTURE_BOUNDARY_CHANGED",),
        ),
        decision_narrative(),
        evaluated_at=NOW + timedelta(seconds=4),
    )
    human_policy = human["policy"]
    human_route = human["route"]
    assert isinstance(human_policy, DecisionPolicyResult)
    assert isinstance(human_route, DecisionRequestFactoryResult)
    assert human_policy.disposition is DecisionDisposition.HUMAN_DECISION_NOW
    request = human_route.decision_request
    assert request is not None
    assert coordinator.inspect(running.mission_uid).work_packages[0].state is (
        WorkPackageState.WAITING_FOR_DECISION
    )

    restarted = MissionCoordinator(MissionStore(project))
    assert restarted.decision_inbox(running.mission_uid) == (request,)
    resolved = restarted.resolve_decision(
        request.decision_request_uid,
        actor_uid="local-user",
        reason="采用推荐边界",
        selected_action=request.action.operation,
        decided_at=NOW + timedelta(seconds=5),
    )
    resolution = resolved["resolution"]
    resumed = resolved["mission"]
    assert isinstance(resolution, DecisionResolution)
    assert isinstance(resumed, Mission)
    assert resumed.work_packages[0].state is WorkPackageState.RUNNING
    assert restarted.decision_inbox(running.mission_uid) == ()
    recovered = MissionCoordinator(MissionStore(project))
    assert recovered.inspect(running.mission_uid) == resumed
    assert recovered.store.decision_resolution_for(request.decision_request_uid) == (
        resolution
    )
