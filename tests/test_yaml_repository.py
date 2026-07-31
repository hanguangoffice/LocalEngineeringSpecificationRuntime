from pathlib import Path

import pytest

from lesr.domain.models import Artifact, Relation
from lesr.errors import LESRError
from lesr.storage.yaml_repository import YamlRepository


def artifact() -> Artifact:
    return Artifact(id="REQ-SW-0001", artifact_type="software_requirement", title="Reconnect MQTT", statement="The client shall reconnect after an unexpected disconnect.")


def test_initialize_is_idempotent_and_create_writes_source_snapshot_and_audit(tmp_path: Path) -> None:
    repository = YamlRepository(tmp_path)
    repository.initialize("demo")
    repository.initialize("demo")
    saved = repository.create_artifact(artifact(), actor="tester")
    assert saved.source_path == "artifacts/REQ-SW-0001.yaml"
    assert saved.content_hash and saved.content_hash.startswith("sha256:")
    assert (tmp_path / saved.source_path).exists()
    assert (tmp_path / ".lesr/versions/REQ-SW-0001/v0001.json").exists()
    assert '"operation":"artifact.create"' in (tmp_path / "audit/events.jsonl").read_text(encoding="utf-8")


def test_draft_update_increments_version_and_preserves_snapshot(tmp_path: Path) -> None:
    repository = YamlRepository(tmp_path)
    repository.initialize("demo")
    created = repository.create_artifact(artifact(), actor="tester")
    created.title = "Controlled MQTT reconnect"
    updated = repository.update_draft(created, actor="tester")
    assert updated.version == 2
    assert (tmp_path / ".lesr/versions/REQ-SW-0001/v0001.json").exists()
    assert (tmp_path / ".lesr/versions/REQ-SW-0001/v0002.json").exists()


def test_direct_update_of_approved_artifact_is_denied(tmp_path: Path) -> None:
    repository = YamlRepository(tmp_path)
    repository.initialize("demo")
    approved = artifact()
    approved.status = "approved"
    created = repository.create_artifact(approved, actor="tester")
    with pytest.raises(LESRError) as error:
        repository.update_draft(created, actor="tester")
    assert error.value.code == "LESR-CHANGE-REQUIRED"


def test_relation_requires_existing_endpoints(tmp_path: Path) -> None:
    repository = YamlRepository(tmp_path)
    repository.initialize("demo")
    repository.create_artifact(artifact(), actor="tester")
    with pytest.raises(LESRError) as error:
        repository.add_relation(Relation(id="REL-000001", source_id="REQ-SW-0001", relation_type="derives_from", target_id="REQ-SYS-0001"), actor="tester")
    assert error.value.code == "LESR-ARTIFACT-NOT-FOUND"
