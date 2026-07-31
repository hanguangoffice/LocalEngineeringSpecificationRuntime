from pathlib import Path

from lesr.domain.models import Artifact, Relation
from lesr.profiles.loader import ProfileLoader
from lesr.validators.service import ValidationService


def write_profile(root: Path) -> None:
    profile = root / "profiles" / "aspice-lite"
    (profile / "schemas").mkdir(parents=True)
    (profile / "profile.yaml").write_text("id: aspice-lite\nartifact_types: [software_requirement, test_specification]\ndefault_workflow: engineering\n", encoding="utf-8")
    (profile / "schemas" / "software_requirement.yaml").write_text("type: object\nrequired: [statement]\nproperties:\n  statement:\n    type: string\n    minLength: 10\n", encoding="utf-8")
    (profile / "relations.yaml").write_text("relations:\n  - type: verified_by\n    source_types: [software_requirement]\n    target_types: [test_specification]\n    min_count:\n      approved: 1\n", encoding="utf-8")
    (profile / "workflows.yaml").write_text("id: engineering\nstates: [draft, in_review, approved]\ntransitions:\n  - from: draft\n    to: in_review\n", encoding="utf-8")


def requirement(status: str = "draft", statement: str | None = "The software shall reconnect after a disconnect.") -> Artifact:
    return Artifact(id="REQ-SW-0001", artifact_type="software_requirement", title="Reconnect", status=status, statement=statement, profile_ids=["aspice-lite"])


def test_schema_workflow_and_relation_validation(tmp_path: Path) -> None:
    write_profile(tmp_path)
    profile = ProfileLoader(tmp_path).load("aspice-lite")
    service = ValidationService()
    findings = service.validate_artifact(requirement(status="approved"), [profile], [])
    assert {finding.validator_id for finding in findings} == {"traceability.required_relation"}
    schema_findings = service.validate_artifact(requirement(statement="short"), [profile], [])
    assert schema_findings[0].validator_id == "schema.json"
    assert service.can_transition(requirement(), "approved", [profile])[0].validator_id == "workflow.transition"


def test_relation_policy_validation(tmp_path: Path) -> None:
    write_profile(tmp_path)
    profile = ProfileLoader(tmp_path).load("aspice-lite")
    source = requirement()
    invalid_target = Artifact(id="DES-SW-0001", artifact_type="software_design", title="Design")
    relation = Relation(id="REL-000001", source_id=source.id, relation_type="verified_by", target_id=invalid_target.id)
    findings = ValidationService().validate_relation(relation, source, invalid_target, [profile])
    assert findings[0].validator_id == "relation.policy"
