"""Load local profiles without executing profile-supplied code."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from lesr.errors import LESRError


@dataclass(frozen=True, slots=True)
class RelationPolicy:
    relation_type: str
    source_types: tuple[str, ...] = ()
    target_types: tuple[str, ...] = ()
    minimum_by_status: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Workflow:
    workflow_id: str
    states: frozenset[str]
    transitions: dict[tuple[str, str], dict[str, Any]]


@dataclass(frozen=True, slots=True)
class Profile:
    profile_id: str
    root: Path
    artifact_types: frozenset[str]
    schemas: dict[str, dict[str, Any]]
    relation_policies: tuple[RelationPolicy, ...]
    workflows: dict[str, Workflow]
    default_workflow: str | None


class ProfileLoader:
    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root.resolve()

    def load(self, profile_id: str) -> Profile:
        root = (self.project_root / "profiles" / profile_id).resolve()
        profiles_root = (self.project_root / "profiles").resolve()
        if profiles_root not in root.parents or not (root / "profile.yaml").is_file():
            raise LESRError("LESR-PROFILE-LOAD-FAILED", "Profile was not found", {"profile_id": profile_id})
        raw = self._yaml(root / "profile.yaml")
        if raw.get("id") != profile_id:
            raise LESRError("LESR-PROFILE-LOAD-FAILED", "Profile ID does not match directory", {"profile_id": profile_id})
        schemas: dict[str, dict[str, Any]] = {}
        schemas_dir = root / "schemas"
        if schemas_dir.is_dir():
            for schema_file in schemas_dir.glob("*.yaml"):
                schemas[schema_file.stem] = self._yaml(schema_file)
        policies: list[RelationPolicy] = []
        relations_path = root / "relations.yaml"
        if relations_path.exists():
            for item in self._yaml(relations_path).get("relations", []):
                policies.append(RelationPolicy(item["type"], tuple(item.get("source_types", [])), tuple(item.get("target_types", [])), dict(item.get("min_count", {}))))
        workflows: dict[str, Workflow] = {}
        workflows_path = root / "workflows.yaml"
        if workflows_path.exists():
            workflow_data = self._yaml(workflows_path)
            candidates = workflow_data.get("workflows", [workflow_data])
            for item in candidates:
                if "id" not in item:
                    continue
                transitions = {(entry["from"], entry["to"]): entry for entry in item.get("transitions", [])}
                workflows[item["id"]] = Workflow(item["id"], frozenset(item.get("states", [])), transitions)
        return Profile(profile_id, root, frozenset(raw.get("artifact_types", [])), schemas, tuple(policies), workflows, raw.get("default_workflow"))

    @staticmethod
    def _yaml(path: Path) -> dict[str, Any]:
        with path.open(encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
        if not isinstance(data, dict):
            raise LESRError("LESR-PROFILE-LOAD-FAILED", "Profile file must contain a mapping", {"path": str(path)})
        return data
