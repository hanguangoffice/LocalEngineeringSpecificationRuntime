"""Safe, atomic YAML persistence with snapshots and append-only audit records."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from lesr.domain.models import Artifact, AuditEvent, Relation
from lesr.errors import LESRError


class YamlRepository:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def initialize(self, project_id: str) -> None:
        for relative in (
            "artifacts",
            "relations",
            "attachments",
            "audit",
            ".lesr/versions",
            "profiles/core/schemas",
        ):
            (self.root / relative).mkdir(parents=True, exist_ok=True)
        config = self.root / "lesr.yaml"
        if not config.exists():
            self._atomic_write(config, yaml.safe_dump({"project": {"id": project_id, "version": "0.1.0"}}, allow_unicode=True, sort_keys=False))
        profile = self.root / "profiles/core/profile.yaml"
        if not profile.exists():
            self._atomic_write(profile, yaml.safe_dump({"id": "core", "name": "LESR Core", "version": "0.1.0", "artifact_types": []}, allow_unicode=True, sort_keys=False))

    def create_artifact(self, artifact: Artifact, *, actor: str) -> Artifact:
        path = self._artifact_path(artifact.id)
        if path.exists():
            raise LESRError("LESR-DUPLICATE-ID", "Artifact ID already exists", {"artifact_id": artifact.id})
        artifact.source_path = path.relative_to(self.root).as_posix()
        artifact.content_hash = self._hash_model(artifact)
        self._write_artifact(path, artifact)
        self._write_snapshot(artifact, actor=actor, change_id=None)
        self._audit("artifact.create", artifact, actor=actor, before_hash=None)
        return artifact

    def get_artifact(self, artifact_id: str) -> Artifact:
        path = self._artifact_path(artifact_id)
        if not path.exists():
            raise LESRError("LESR-ARTIFACT-NOT-FOUND", "Artifact does not exist", {"artifact_id": artifact_id})
        return Artifact.model_validate(self._read_yaml(path))

    def list_artifacts(self) -> list[Artifact]:
        artifacts_dir = self._safe_path(Path("artifacts"))
        if not artifacts_dir.exists():
            return []
        return [Artifact.model_validate(self._read_yaml(path)) for path in sorted(artifacts_dir.glob("*.yaml"))]

    def list_relations(self) -> list[Relation]:
        relations_dir = self._safe_path(Path("relations"))
        if not relations_dir.exists():
            return []
        return [Relation.model_validate(self._read_yaml(path)) for path in sorted(relations_dir.glob("*.yaml"))]

    def update_draft(self, artifact: Artifact, *, actor: str) -> Artifact:
        existing = self.get_artifact(artifact.id)
        if existing.status != "draft":
            raise LESRError("LESR-CHANGE-REQUIRED", "Only draft artifacts can be updated directly", {"artifact_id": artifact.id, "status": existing.status}, "create_change_request")
        artifact.version = existing.version + 1
        artifact.created_at = existing.created_at
        artifact.updated_at = datetime.now(UTC)
        artifact.source_path = existing.source_path
        before_hash = existing.content_hash
        artifact.content_hash = self._hash_model(artifact)
        self._write_artifact(self._artifact_path(artifact.id), artifact)
        self._write_snapshot(artifact, actor=actor, change_id=None)
        self._audit("artifact.update", artifact, actor=actor, before_hash=before_hash)
        return artifact

    def apply_controlled_update(self, artifact: Artifact, *, actor: str, change_id: str) -> Artifact:
        """Apply an approved change after a human confirmation, preserving history."""
        existing = self.get_artifact(artifact.id)
        artifact.version = existing.version + 1
        artifact.created_at = existing.created_at
        artifact.updated_at = datetime.now(UTC)
        artifact.source_path = existing.source_path
        before_hash = existing.content_hash
        artifact.content_hash = self._hash_model(artifact)
        self._write_artifact(self._artifact_path(artifact.id), artifact)
        self._write_snapshot(artifact, actor=actor, change_id=change_id)
        self._audit("change.apply", artifact, actor=actor, before_hash=before_hash)
        return artifact

    def add_relation(self, relation: Relation, *, actor: str) -> Relation:
        path = self._safe_path(Path("relations") / f"{relation.id}.yaml")
        if path.exists():
            raise LESRError("LESR-DUPLICATE-ID", "Relation ID already exists", {"relation_id": relation.id})
        self.get_artifact(relation.source_id)
        self.get_artifact(relation.target_id)
        self._atomic_write(path, yaml.safe_dump(relation.model_dump(mode="json"), allow_unicode=True, sort_keys=False))
        self._append_audit_raw("relation.create", "relation", relation.id, actor=actor, result=relation.model_dump(mode="json"))
        return relation

    def _artifact_path(self, artifact_id: str) -> Path:
        return self._safe_path(Path("artifacts") / f"{artifact_id}.yaml")

    def _safe_path(self, relative: Path) -> Path:
        candidate = (self.root / relative).resolve()
        if candidate != self.root and self.root not in candidate.parents:
            raise LESRError("LESR-PATH-INVALID", "Path is outside the project root", {"path": str(relative)})
        return candidate

    def _write_artifact(self, path: Path, artifact: Artifact) -> None:
        self._atomic_write(path, yaml.safe_dump(artifact.model_dump(mode="json"), allow_unicode=True, sort_keys=False))

    def _write_snapshot(self, artifact: Artifact, *, actor: str, change_id: str | None) -> None:
        path = self._safe_path(Path(".lesr/versions") / artifact.id / f"v{artifact.version:04d}.json")
        if path.exists():
            raise LESRError("LESR-VERSION-EXISTS", "Artifact version snapshot already exists", {"artifact_id": artifact.id, "version": artifact.version})
        snapshot = {"artifact": artifact.model_dump(mode="json"), "created_by": actor, "change_id": change_id}
        self._atomic_write(path, json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n")

    def _audit(self, operation: str, artifact: Artifact, *, actor: str, before_hash: str | None) -> None:
        self._append_audit_raw(operation, "artifact", artifact.id, actor=actor, before_hash=before_hash, after_hash=artifact.content_hash, result={"version": artifact.version})

    def _append_audit_raw(self, operation: str, target_type: str, target_id: str, *, actor: str, before_hash: str | None = None, after_hash: str | None = None, result: dict[str, Any] | None = None) -> None:
        event = AuditEvent(id=f"AUD-{uuid.uuid4().hex[:12].upper()}", actor=actor, operation=operation, target_type=target_type, target_id=target_id, before_hash=before_hash, after_hash=after_hash, result=result or {})
        path = self._safe_path(Path("audit") / "events.jsonl")
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(event.model_dump_json() + "\n")

    @staticmethod
    def _read_yaml(path: Path) -> dict[str, Any]:
        with path.open("r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle)
        if not isinstance(data, dict):
            raise LESRError("LESR-SCHEMA-INVALID", "Artifact YAML must contain an object", {"path": str(path)})
        return data

    @staticmethod
    def _hash_model(artifact: Artifact) -> str:
        data = artifact.model_dump(mode="json", exclude={"content_hash", "updated_at"})
        encoded = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return "sha256:" + hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def _atomic_write(path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent, text=True)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
