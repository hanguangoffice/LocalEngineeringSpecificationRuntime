"""Task context assembly using explicit IDs, relation expansion, and profile policy."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import cast

import yaml

from lesr.domain.models import Artifact, Relation
from lesr.errors import LESRError


@dataclass(frozen=True, slots=True)
class ContextItem:
    artifact: Artifact
    section: str
    reason: str
    token_estimate: int


@dataclass(frozen=True, slots=True)
class TaskContext:
    task_type: str
    items: tuple[ContextItem, ...]
    excluded: tuple[dict[str, str], ...]
    token_estimate: int


class ContextService:
    def build(self, task_type: str, targets: list[Artifact], all_artifacts: list[Artifact], relations: list[Relation], profile_root: Path, token_budget: int) -> TaskContext:
        policy = self._policy(profile_root, task_type)
        by_id = {artifact.id: artifact for artifact in all_artifacts}
        selected: dict[str, ContextItem] = {}
        for artifact in targets:
            selected[artifact.id] = self._item(artifact, "mandatory", "explicit target")
        for target in targets:
            for relation in relations:
                if relation.status != "active":
                    continue
                linked_id = relation.target_id if relation.source_id == target.id else relation.source_id if relation.target_id == target.id else None
                if linked_id and linked_id in by_id:
                    linked = by_id[linked_id]
                    if linked.status not in set(policy.get("exclude", [])):
                        section = "mandatory" if linked.artifact_type in set(policy.get("mandatory", [])) else "optional"
                        selected.setdefault(linked.id, self._item(linked, section, f"active {relation.relation_type} relation to {target.id}"))
        ordered = sorted(selected.values(), key=lambda item: (item.section != "mandatory", item.artifact.id))
        included: list[ContextItem] = []
        excluded: list[dict[str, str]] = []
        used = 0
        for item in ordered:
            if used + item.token_estimate <= token_budget or item.section == "mandatory":
                included.append(item); used += item.token_estimate
            else:
                excluded.append({"artifact_id": item.artifact.id, "reason": "token budget exceeded"})
        if used > token_budget and any(item.section == "mandatory" for item in included):
            raise LESRError("LESR-CONTEXT-BUDGET-EXCEEDED", "Mandatory context exceeds token budget", {"estimated": used, "budget": token_budget})
        return TaskContext(task_type, tuple(included), tuple(excluded), used)

    @staticmethod
    def _item(artifact: Artifact, section: str, reason: str) -> ContextItem:
        text = " ".join(filter(None, [artifact.title, artifact.statement, artifact.rationale]))
        return ContextItem(artifact, section, reason, max(1, len(text) // 4))

    @staticmethod
    def _policy(profile_root: Path, task_type: str) -> dict[str, list[str]]:
        path = profile_root / "context-policy.yaml"
        if not path.exists():
            return {}
        with path.open(encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
        return cast(dict[str, list[str]], data.get("task_types", {}).get(task_type, {}))
