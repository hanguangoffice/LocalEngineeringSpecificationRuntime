"""MCP tools delegate to repositories and retrieval services only."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from lesr.changes.service import ChangeService
from lesr.context.service import ContextService
from lesr.profiles.loader import ProfileLoader
from lesr.retrieval.sqlite_index import SQLiteIndex
from lesr.storage.yaml_repository import YamlRepository
from lesr.validators.service import ValidationService


def create_server(project_root: Path) -> FastMCP:
    repository = YamlRepository(project_root)
    index = SQLiteIndex(project_root)
    server = FastMCP("LESR")

    @server.tool()
    def get_artifact(id: str) -> dict[str, Any]:
        """Get one source-of-truth Artifact by stable ID."""
        return repository.get_artifact(id).model_dump(mode="json")

    @server.tool()
    def list_artifacts(artifact_type: str | None = None, status: str | None = None, module: str | None = None) -> list[dict[str, object]]:
        """List structured artifacts from the rebuildable SQLite index."""
        return index.list_artifacts(artifact_type=artifact_type, status=status, module=module)

    @server.tool()
    def search_artifacts(query: str) -> list[dict[str, object]]:
        """Perform FTS5 search over the local structured index."""
        return index.search(query)

    @server.tool()
    def get_related_artifacts(id: str, depth: int = 1) -> list[dict[str, object]]:
        """Expand active traceability relations from an Artifact."""
        return index.related(id, depth)

    @server.tool()
    def build_task_context(task_type: str, target_artifact_ids: list[str], token_budget: int, profile_id: str = "aspice-lite") -> dict[str, Any]:
        """Build an explainable, budget-controlled context package."""
        profile_root = project_root / "profiles" / profile_id
        context = ContextService().build(task_type, [repository.get_artifact(item) for item in target_artifact_ids], repository.list_artifacts(), repository.list_relations(), profile_root, token_budget)
        return {"task_type": context.task_type, "token_estimate": context.token_estimate, "items": [{"artifact": item.artifact.model_dump(mode="json"), "section": item.section, "reason": item.reason} for item in context.items], "excluded": list(context.excluded)}

    @server.tool()
    def validate_artifact(id: str) -> list[dict[str, Any]]:
        """Run schema, workflow, and required-relation validation."""
        artifact = repository.get_artifact(id)
        profiles = [ProfileLoader(project_root).load(profile_id) for profile_id in artifact.profile_ids]
        return [finding.model_dump(mode="json") for finding in ValidationService().validate_artifact(artifact, profiles, repository.list_relations())]

    @server.tool()
    def propose_artifact_update(change_id: str, target_id: str, reason: str, patch: dict[str, Any], actor: str = "ai-agent") -> dict[str, Any]:
        """Propose, but do not apply, a controlled Artifact update."""
        return ChangeService(repository).propose_update(change_id, target_id, reason, patch, actor).model_dump(mode="json")

    @server.tool()
    def apply_change(change_id: str, confirmed_by: str) -> dict[str, Any]:
        """Apply a proposed change after explicit human confirmation."""
        return ChangeService(repository).apply(change_id, confirmed_by).model_dump(mode="json")

    @server.tool()
    def create_baseline(baseline_id: str, title: str, member_ids: list[str], confirmed_by: str) -> dict[str, Any]:
        """Create a manually confirmed, version-pinned baseline."""
        return ChangeService(repository).create_baseline(baseline_id, title, member_ids, confirmed_by).model_dump(mode="json")

    @server.tool()
    def compare_baselines(left_id: str, right_id: str) -> dict[str, list[dict[str, object]]]:
        """Compare version-pinned baseline members."""
        return ChangeService(repository).compare_baselines(left_id, right_id)

    return server
