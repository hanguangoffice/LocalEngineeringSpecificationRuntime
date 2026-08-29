from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from lesr.application.runtime import LocalRuntimeService


def mission_plan() -> dict[str, object]:
    return {
        "title": "Telemetry console delivery",
        "objective": "Deliver a locally testable engineering console",
        "initiated_by_actor_uid": "local-owner",
        "engineering_areas": ["requirements", "architecture", "verification"],
        "allowed_operations": ["workspace.edit", "workspace.validate"],
        "packages": [
            {
                "key": "requirements",
                "title": "Clarify requirements",
                "objective": "Structure the accepted product requirements",
                "role": "requirements-agent",
            },
            {
                "key": "architecture",
                "title": "Design the solution",
                "objective": "Create an architecture from the structured requirements",
                "role": "architecture-agent",
                "depends_on": ["requirements"],
            },
        ],
    }


def test_public_mission_flow_persists_without_changing_canonical_git(
    tmp_path: Path,
) -> None:
    project = tmp_path / "agentic-project"
    runtime = LocalRuntimeService(project)
    canonical_before = runtime.repository.current_commit()

    created = runtime.create_mission(mission_plan())
    assert created.ok
    mission = created.value
    mission_uid = mission["mission_uid"]
    assert runtime.repository.current_commit() == canonical_before

    ready = runtime.ready_mission_work(mission_uid)
    assert ready.ok
    assert [item["work_package_title"] for item in ready.value] == [
        "Clarify requirements"
    ]
    work_package_uid = ready.value[0]["work_package_uid"]
    claimed = runtime.claim_mission_work(
        mission_uid,
        work_package_uid,
        "agent:requirements-1",
        "codex",
        "provider-default",
        "mcp",
    )
    assert claimed.ok
    run_uid = claimed.value["agent_run"]["agent_run_uid"]

    finished = runtime.report_mission_work(
        {
            "mission_uid": mission_uid,
            "work_package_uid": work_package_uid,
            "agent_run_uid": run_uid,
            "state": "completed",
            "result_summary": "Requirements are structured and ready for design.",
            "reported_at": datetime.now(UTC).isoformat(),
        }
    )
    assert finished.ok
    assert runtime.repository.current_commit() == canonical_before

    restarted = LocalRuntimeService(project)
    inspected = restarted.inspect_mission(mission_uid)
    assert inspected.ok
    by_title = {
        item["title"]: item["state"] for item in inspected.value["work_packages"]
    }
    assert by_title == {
        "Clarify requirements": "completed",
        "Design the solution": "ready",
    }
    assert restarted.list_decisions(mission_uid).value == ()


def test_public_mission_rejects_a_second_claim(tmp_path: Path) -> None:
    runtime = LocalRuntimeService(tmp_path / "agentic-project")
    mission = runtime.create_mission(mission_plan()).value
    mission_uid = mission["mission_uid"]
    work_package_uid = runtime.ready_mission_work(mission_uid).value[0][
        "work_package_uid"
    ]
    first = runtime.claim_mission_work(
        mission_uid,
        work_package_uid,
        "agent:first",
        "codex",
        "provider-default",
        "mcp",
    )
    second = runtime.claim_mission_work(
        mission_uid,
        work_package_uid,
        "agent:second",
        "codex",
        "provider-default",
        "mcp",
    )

    assert first.ok
    assert second.error is not None
    assert second.error.code == "LESR-MISSION-WORK-NOT-READY"
