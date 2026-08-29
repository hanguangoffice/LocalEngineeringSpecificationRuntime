from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from lesr.adapters.mcp import create_server
from lesr.adapters.web import LocalWebRuntime
from lesr.application.contracts import DomainResult, WorkspaceAssessmentRequest
from lesr.application.runtime import LocalRuntimeService
from lesr.cli.main import app


def test_cli_exposes_only_v1_capability_groups() -> None:
    result = CliRunner().invoke(app, ["--help"])
    assert result.exit_code == 0
    for capability in (
        "resolve",
        "inspect",
        "query",
        "context",
        "workspace",
        "apply",
        "baseline",
        "projection",
        "mcp",
    ):
        assert capability in result.stdout
    assert "artifact-create" not in result.stdout
    assert "import-accept" not in result.stdout

    workspace_help = CliRunner().invoke(app, ["workspace", "--help"])
    assert workspace_help.exit_code == 0
    assert "validate" in workspace_help.stdout


def test_cli_workspace_validate_uses_read_only_assessment_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    received: list[tuple[Path, WorkspaceAssessmentRequest]] = []

    class StubRuntime:
        def __init__(self, project: Path) -> None:
            self.project = project

        def assess_workspace(self, request: WorkspaceAssessmentRequest) -> DomainResult:
            received.append((self.project, request))
            return DomainResult(
                {
                    "workspace_uid": request.workspace_uid,
                    "assessment_mode": "preview",
                }
            )

    monkeypatch.setattr("lesr.cli.main.LocalRuntimeService", StubRuntime)
    project = tmp_path / "project"
    result = CliRunner().invoke(
        app,
        [
            "workspace",
            "validate",
            str(project),
            "workspace-1",
            "2026-08-30T12:00:00Z",
            "--maximum-depth",
            "5",
        ],
    )

    assert result.exit_code == 0, result.stdout
    assert received == [
        (
            project,
            WorkspaceAssessmentRequest(
                workspace_uid="workspace-1",
                evaluation_time="2026-08-30T12:00:00Z",
                maximum_depth=5,
            ),
        )
    ]
    assert json.loads(result.stdout) == {
        "ok": True,
        "value": {
            "assessment_mode": "preview",
            "workspace_uid": "workspace-1",
        },
    }


def test_all_production_adapters_share_the_local_runtime(tmp_path: Path) -> None:
    runtime = LocalRuntimeService(tmp_path / "project")
    web = LocalWebRuntime(tmp_path / "project", runtime)
    mcp = create_server(runtime)
    assert web.domain is runtime
    assert mcp.name == "LESR v1"


def test_legacy_application_service_is_absent() -> None:
    assert not (Path(__file__).parents[1] / "src/lesr/application/service.py").exists()
