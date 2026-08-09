from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from lesr.adapters.mcp import create_server
from lesr.adapters.web import LocalWebRuntime
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


def test_all_production_adapters_share_the_local_runtime(tmp_path: Path) -> None:
    runtime = LocalRuntimeService(tmp_path / "project")
    web = LocalWebRuntime(tmp_path / "project", runtime)
    mcp = create_server(runtime)
    assert web.domain is runtime
    assert mcp.name == "LESR v1"


def test_legacy_application_service_is_absent() -> None:
    assert not (Path(__file__).parents[1] / "src/lesr/application/service.py").exists()
