from pathlib import Path
from shutil import copytree

from lesr.changes.service import ChangeService
from lesr.retrieval.sqlite_index import SQLiteIndex
from lesr.storage.yaml_repository import YamlRepository


def test_home_control_index_trace_and_controlled_change(tmp_path: Path) -> None:
    project = tmp_path / "home-control"
    copytree(Path("examples/home-control"), project)
    repository = YamlRepository(project)
    index = SQLiteIndex(project)
    index.rebuild(repository.list_artifacts(), repository.list_relations())
    assert index.search("MQTT")[0]["id"] == "REQ-SW-0001"
    assert index.related("REQ-SW-0001")[0]["id"] == "REQ-SYS-0001"
    changes = ChangeService(repository)
    changes.propose_update("CHG-000001", "REQ-SW-0001", "Clarify", {"title": "Controlled MQTT reconnect"}, "agent")
    assert changes.apply("CHG-000001", "reviewer").version == 2
