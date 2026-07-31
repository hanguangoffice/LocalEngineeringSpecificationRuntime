from pathlib import Path

from lesr.changes.service import ChangeService
from lesr.domain.models import Artifact
from lesr.storage.yaml_repository import YamlRepository


def test_controlled_change_and_baseline(tmp_path: Path) -> None:
    repository = YamlRepository(tmp_path); repository.initialize("demo")
    source = Artifact(id="REQ-SW-0001", artifact_type="software_requirement", title="Reconnect", status="approved", statement="The client shall reconnect after disconnect.")
    repository.create_artifact(source, actor="user")
    service = ChangeService(repository)
    service.propose_update("CHG-000001", source.id, "Clarify timeout", {"title": "Controlled reconnect"}, "agent")
    assert service.apply("CHG-000001", "reviewer").version == 2
    baseline = service.create_baseline("BL-0.1", "MVP", [source.id], "reviewer")
    assert baseline.attributes["members"][0]["version"] == 2
    service.propose_update("CHG-000002", source.id, "Clarify", {"title": "Final reconnect"}, "agent")
    service.apply("CHG-000002", "reviewer")
    service.create_baseline("BL-0.2", "MVP 2", [source.id], "reviewer")
    assert service.compare_baselines("BL-0.1", "BL-0.2")["changed"][0]["after"] == 3
