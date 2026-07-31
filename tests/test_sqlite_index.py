from pathlib import Path

from lesr.domain.models import Artifact, Relation
from lesr.retrieval.sqlite_index import SQLiteIndex


def test_rebuild_search_filter_and_related(tmp_path: Path) -> None:
    system = Artifact(id="REQ-SYS-0001", artifact_type="system_requirement", title="System availability", status="approved", module="communication", statement="The system shall remain available.")
    software = Artifact(id="REQ-SW-0001", artifact_type="software_requirement", title="MQTT reconnect", status="approved", module="communication", statement="The client shall reconnect MQTT after an unexpected disconnect.")
    relation = Relation(id="REL-000001", source_id=software.id, relation_type="derives_from", target_id=system.id)
    index = SQLiteIndex(tmp_path)
    index.rebuild([system, software], [relation])
    assert index.get(software.id)["title"] == "MQTT reconnect"
    assert [item["id"] for item in index.list_artifacts(status="approved", module="communication")] == sorted([system.id, software.id])
    assert index.search("MQTT")[0]["id"] == software.id
    assert index.related(software.id)[0]["id"] == system.id
