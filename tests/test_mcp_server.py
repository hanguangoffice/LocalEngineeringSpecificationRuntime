import asyncio
from pathlib import Path

from lesr.mcp.server import create_server
from lesr.storage.yaml_repository import YamlRepository


def test_mcp_server_exposes_query_tools(tmp_path: Path) -> None:
    YamlRepository(tmp_path).initialize("demo")
    server = create_server(tmp_path)
    assert {tool.name for tool in asyncio.run(server.list_tools())} == {"get_artifact", "list_artifacts", "search_artifacts", "get_related_artifacts", "build_task_context", "validate_artifact", "propose_artifact_update", "apply_change", "create_baseline", "compare_baselines"}
