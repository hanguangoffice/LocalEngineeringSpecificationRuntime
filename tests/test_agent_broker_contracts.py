from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from lesr.application.agent_broker import (
    AgentAssignment,
    AgentBrokerPort,
    AgentClaim,
    AgentReport,
    apply_agent_report,
    build_agent_assignment,
    validate_agent_claim,
)
from lesr.domain.mission import (
    AgentRun,
    AgentRunEngine,
    AgentRunState,
    Mission,
    MissionEngine,
    WorkPackage,
)

NOW = datetime(2026, 8, 30, 8, 0, tzinfo=UTC)
MISSION_UID = "018f0000-0000-7000-8000-000000000001"
PACKAGE_UID = "018f0000-0000-7000-8000-000000000002"
RUN_UID = "018f0000-0000-7000-8000-000000000003"


def ready_mission() -> Mission:
    mission = Mission(
        mission_uid=MISSION_UID,
        title="本地工程实现",
        objective="完成本轮工程任务",
        initiated_by_actor_uid="local-user",
        configuration_uid="configuration:desktop",
        work_packages=(
            WorkPackage(
                work_package_uid=PACKAGE_UID,
                mission_uid=MISSION_UID,
                title="实现系统检测",
                objective="实现并验证 Windows 与 GPU 检测",
                role="implementation",
                workspace_uid="workspace:gpu-lab",
                created_at=NOW,
                updated_at=NOW,
            ),
        ),
        created_at=NOW,
        updated_at=NOW,
    )
    return MissionEngine.reconcile(mission, updated_at=NOW)


def assignment(mission: Mission | None = None) -> AgentAssignment:
    return build_agent_assignment(
        mission or ready_mission(),
        PACKAGE_UID,
        context_capability="context.plan",
        allowed_operations=("workspace.edit", "workspace.validate"),
    )


def claim(*, package_uid: str = PACKAGE_UID, run_uid: str = RUN_UID) -> AgentClaim:
    return AgentClaim(
        mission_uid=MISSION_UID,
        work_package_uid=package_uid,
        agent_run_uid=run_uid,
        agent_identity="configured-agent",
        claimed_at=NOW + timedelta(seconds=1),
    )


def running_agent_run(*, package_uid: str = PACKAGE_UID) -> AgentRun:
    queued = AgentRun(
        agent_run_uid=RUN_UID,
        mission_uid=MISSION_UID,
        work_package_uid=package_uid,
        role="implementation",
        provider="configured-provider",
        model_identifier="configured-model",
        client="lesr-agent-broker",
        created_at=NOW,
        updated_at=NOW,
    )
    return AgentRunEngine.start(queued, started_at=NOW + timedelta(seconds=2))


def test_ready_package_builds_provider_neutral_assignment_without_hashes() -> None:
    built = assignment()

    assert built.mission_title == "本地工程实现"
    assert built.work_package_title == "实现系统检测"
    assert built.objective == "实现并验证 Windows 与 GPU 检测"
    assert built.role == "implementation"
    assert built.configuration_uid == "configuration:desktop"
    assert built.workspace_uid == "workspace:gpu-lab"
    assert built.context_capability == "context.plan"
    assert built.allowed_operations == ("workspace.edit", "workspace.validate")
    keys = built.model_dump(mode="json")
    assert all("hash" not in key for key in keys)
    assert {"provider", "model", "sdk", "shell", "command"}.isdisjoint(keys)


def test_only_ready_package_can_be_assigned_or_claimed() -> None:
    mission = ready_mission()
    started = MissionEngine.start_package(
        mission,
        PACKAGE_UID,
        updated_at=NOW + timedelta(seconds=1),
    )
    with pytest.raises(ValueError, match="READY"):
        build_agent_assignment(
            started,
            PACKAGE_UID,
            context_capability="context.plan",
            allowed_operations=("workspace.edit",),
        )
    with pytest.raises(ValueError, match="READY"):
        validate_agent_claim(started, assignment(mission), claim())


def test_claim_must_match_assignment_and_broker_contract_is_provider_neutral() -> None:
    mission = ready_mission()
    offered = assignment(mission)
    accepted = validate_agent_claim(mission, offered, claim())
    assert accepted.agent_run_uid == RUN_UID

    with pytest.raises(ValueError, match="does not match"):
        validate_agent_claim(
            mission,
            offered,
            claim(package_uid="018f0000-0000-7000-8000-000000000099"),
        )

    class FakeBroker:
        def dispatch(self, value: AgentAssignment) -> AgentClaim:
            assert value == offered
            return accepted

        def collect_report(self, value: AgentClaim) -> AgentReport | None:
            assert value == accepted
            return None

    broker: AgentBrokerPort = FakeBroker()
    assert broker.dispatch(offered) == accepted
    assert broker.collect_report(accepted) is None


@pytest.mark.parametrize(
    ("state", "summary_field", "summary", "expected_state"),
    [
        (AgentRunState.COMPLETED, "result_summary", "实现与测试完成", AgentRunState.COMPLETED),
        (AgentRunState.FAILED, "error_summary", "依赖无法解析", AgentRunState.FAILED),
    ],
)
def test_terminal_report_projects_the_matching_agent_run(
    state: AgentRunState,
    summary_field: str,
    summary: str,
    expected_state: AgentRunState,
) -> None:
    offered = assignment()
    accepted = claim()
    running = running_agent_run()
    report = AgentReport.model_validate(
        {
            "mission_uid": MISSION_UID,
            "work_package_uid": PACKAGE_UID,
            "agent_run_uid": RUN_UID,
            "state": state,
            "reported_at": NOW + timedelta(seconds=3),
            summary_field: summary,
        }
    )

    projected = apply_agent_report(offered, accepted, running, report)

    assert projected.state is expected_state
    assert getattr(projected, summary_field) == summary


def test_report_must_match_run_and_have_a_valid_terminal_payload() -> None:
    offered = assignment()
    accepted = claim()
    running = running_agent_run()
    wrong_run_report = AgentReport(
        mission_uid=MISSION_UID,
        work_package_uid=PACKAGE_UID,
        agent_run_uid="018f0000-0000-7000-8000-000000000099",
        state=AgentRunState.COMPLETED,
        result_summary="不属于该运行",
        reported_at=NOW + timedelta(seconds=3),
    )
    with pytest.raises(ValueError, match="AgentRun"):
        apply_agent_report(offered, accepted, running, wrong_run_report)

    with pytest.raises(ValidationError, match="result summary"):
        AgentReport(
            mission_uid=MISSION_UID,
            work_package_uid=PACKAGE_UID,
            agent_run_uid=RUN_UID,
            state=AgentRunState.COMPLETED,
            reported_at=NOW + timedelta(seconds=3),
        )
    with pytest.raises(ValidationError, match="error summary"):
        AgentReport(
            mission_uid=MISSION_UID,
            work_package_uid=PACKAGE_UID,
            agent_run_uid=RUN_UID,
            state=AgentRunState.FAILED,
            reported_at=NOW + timedelta(seconds=3),
        )
    with pytest.raises(ValidationError):
        AgentReport.model_validate(
            {
                "mission_uid": MISSION_UID,
                "work_package_uid": PACKAGE_UID,
                "agent_run_uid": RUN_UID,
                "state": AgentRunState.RUNNING,
                "result_summary": "仍在运行",
                "reported_at": NOW + timedelta(seconds=3),
            }
        )


def test_agent_messages_are_frozen_runtime_only_and_require_utc() -> None:
    offered = assignment()
    accepted = claim()
    report = AgentReport(
        mission_uid=MISSION_UID,
        work_package_uid=PACKAGE_UID,
        agent_run_uid=RUN_UID,
        state=AgentRunState.COMPLETED,
        result_summary="完成",
        reported_at=NOW + timedelta(seconds=3),
    )
    for message in (offered, accepted, report):
        assert message.persistence_scope == "local_runtime"
        assert message.canonical_git_eligible is False
        assert all("hash" not in key for key in message.model_dump(mode="json"))
    with pytest.raises(ValidationError):
        offered.role = "review"
    with pytest.raises(ValidationError, match="UTC"):
        AgentClaim(
            mission_uid=MISSION_UID,
            work_package_uid=PACKAGE_UID,
            agent_run_uid=RUN_UID,
            agent_identity="configured-agent",
            claimed_at=datetime(2026, 8, 30, 8, 0),  # noqa: DTZ001
        )
