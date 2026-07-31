from pathlib import Path

import pytest

from lesr.context.service import ContextService
from lesr.domain.models import Artifact, Relation
from lesr.errors import LESRError


def test_build_context_is_explainable_and_budgeted(tmp_path: Path) -> None:
    (tmp_path / "context-policy.yaml").write_text("task_types:\n  coding:\n    mandatory: [software_design]\n    exclude: [deprecated]\n", encoding="utf-8")
    requirement = Artifact(id="REQ-SW-0001", artifact_type="software_requirement", title="Reconnect", statement="Reconnect MQTT.")
    design = Artifact(id="DES-SW-0001", artifact_type="software_design", title="Design", statement="Use controlled backoff.")
    result = ContextService().build("coding", [requirement], [requirement, design], [Relation(id="REL-000001", source_id=requirement.id, relation_type="implemented_by", target_id=design.id)], tmp_path, 100)
    assert [item.artifact.id for item in result.items] == [design.id, requirement.id]
    assert result.items[0].reason.startswith("active")
    with pytest.raises(LESRError):
        ContextService().build("coding", [requirement], [requirement, design], [Relation(id="REL-000001", source_id=requirement.id, relation_type="implemented_by", target_id=design.id)], tmp_path, 1)
