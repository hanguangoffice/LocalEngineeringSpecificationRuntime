"""Phase 4 services that keep proposed and applied changes separate."""

from __future__ import annotations

from typing import Any

from lesr.domain.models import Artifact
from lesr.errors import LESRError
from lesr.storage.yaml_repository import YamlRepository


class ChangeService:
    def __init__(self, repository: YamlRepository) -> None:
        self.repository = repository

    def propose_update(self, change_id: str, target_id: str, reason: str, patch: dict[str, Any], actor: str) -> Artifact:
        target = self.repository.get_artifact(target_id)
        change = Artifact(id=change_id, artifact_type="change_request", title=f"Change {target_id}", status="proposed", attributes={"reason": reason, "target_ids": [target_id], "patch": patch, "target_version": target.version, "impact": self.impact(target_id)})
        return self.repository.create_artifact(change, actor=actor)

    def impact(self, target_id: str) -> list[str]:
        related = self.repository.list_relations()
        affected = {target_id}
        changed = True
        while changed:
            changed = False
            for relation in related:
                if relation.source_id in affected and relation.target_id not in affected:
                    affected.add(relation.target_id); changed = True
                if relation.target_id in affected and relation.source_id not in affected:
                    affected.add(relation.source_id); changed = True
        return sorted(affected)

    def apply(self, change_id: str, confirmed_by: str) -> Artifact:
        if not confirmed_by:
            raise LESRError("LESR-HUMAN-CONFIRMATION-REQUIRED", "A human confirmer is required", {"change_id": change_id})
        change = self.repository.get_artifact(change_id)
        if change.status != "proposed":
            raise LESRError("LESR-CHANGE-INVALID", "Change is not proposed", {"change_id": change_id, "status": change.status})
        target = self.repository.get_artifact(change.attributes["target_ids"][0])
        patched = target.model_copy(update=change.attributes["patch"])
        saved = self.repository.apply_controlled_update(patched, actor=confirmed_by, change_id=change_id)
        change.status = "applied"
        self.repository.apply_controlled_update(change, actor=confirmed_by, change_id=change_id)
        return saved

    def create_baseline(self, baseline_id: str, title: str, member_ids: list[str], confirmed_by: str) -> Artifact:
        if not confirmed_by:
            raise LESRError("LESR-HUMAN-CONFIRMATION-REQUIRED", "A human confirmer is required", {"baseline_id": baseline_id})
        members = [{"artifact_id": item.id, "version": item.version} for item in (self.repository.get_artifact(member_id) for member_id in member_ids)]
        baseline = Artifact(id=baseline_id, artifact_type="baseline", title=title, status="released", attributes={"members": members})
        return self.repository.create_artifact(baseline, actor=confirmed_by)

    def compare_baselines(self, left_id: str, right_id: str) -> dict[str, list[dict[str, object]]]:
        left = {item["artifact_id"]: item["version"] for item in self.repository.get_artifact(left_id).attributes["members"]}
        right = {item["artifact_id"]: item["version"] for item in self.repository.get_artifact(right_id).attributes["members"]}
        return {"added": [{"artifact_id": key, "version": right[key]} for key in right.keys() - left.keys()], "removed": [{"artifact_id": key, "version": left[key]} for key in left.keys() - right.keys()], "changed": [{"artifact_id": key, "before": left[key], "after": right[key]} for key in left.keys() & right.keys() if left[key] != right[key]]}
