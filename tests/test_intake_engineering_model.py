from __future__ import annotations

from pathlib import Path

from lesr.adapters.presentation_store import PresentationMappingStore
from lesr.domain.model import KindDefinitionRevision
from lesr.domain.semantic import CoreResourceClass
from lesr.intake.catalog import IntakeCatalog
from lesr.intake.engineering_model import (
    build_presentation_mapping,
    engineering_model_for,
)
from lesr.intake.models import RequirementCategory


def test_selected_artifacts_define_areas_and_enabled_kind_vocabulary() -> None:
    catalog = IntakeCatalog()
    rest_pack = catalog.pack("rest-api-service")
    event_pack = catalog.pack("event-driven-integration")
    rest = engineering_model_for(rest_pack)
    event = engineering_model_for(event_pack)

    assert [item.label for item in rest.areas] == [
        item.display_name for item in rest_pack.artifacts
    ]
    assert [item.description for item in rest.areas] == [
        item.purpose for item in rest_pack.artifacts
    ]
    assert "api_contract" in rest.kind_names
    assert "message_contract" not in rest.kind_names
    assert "message_contract" in event.kind_names
    assert "api_contract" not in event.kind_names
    assert {
        "goal",
        "functional_requirement",
        "quality_requirement",
        "constraint_requirement",
        "safety_requirement",
        "test_case",
        "evidence",
        "design",
        "architecture_decision",
    } <= set(rest.kind_names)
    assert all("SYS" not in item.label and "SWE" not in item.label for item in rest.areas)


def test_requirement_categories_map_to_corresponding_enabled_kinds() -> None:
    plan = engineering_model_for(IntakeCatalog().pack("software-standard"))

    assert plan.kind_for(RequirementCategory.GOAL) == "goal"
    assert plan.kind_for(RequirementCategory.FUNCTION) == "functional_requirement"
    assert plan.kind_for(RequirementCategory.QUALITY) == "quality_requirement"
    assert plan.kind_for(RequirementCategory.CONSTRAINT) == "constraint_requirement"
    assert plan.kind_for(RequirementCategory.SAFETY) == "safety_requirement"
    assert plan.kind_for(RequirementCategory.TEST) == "test_case"
    assert plan.kind_for(RequirementCategory.DELIVERABLE) == "deliverable"
    assert plan.kind_for(RequirementCategory.DEPENDENCY) == "dependency"


def test_presentation_mapping_uses_exact_kind_revisions_and_survives_restart(
    tmp_path: Path,
) -> None:
    plan = engineering_model_for(IntakeCatalog().pack("data-science-ml"))
    definitions = {
        name: KindDefinitionRevision(
            name=name,
            core_class=CoreResourceClass.GOVERNED_OBJECT,
            authority=100,
        )
        for name in plan.kind_names
    }
    profile_uid = "018f0000-0000-7000-8000-000000000001"
    mapping = build_presentation_mapping(
        plan,
        definitions,
        profile_revision_uids=(profile_uid,),
    )

    referenced = {
        uid
        for area in mapping.engineering_areas
        for uid in area.selector.kind_definition_revision_uids
    }
    assert referenced == {item.revision_uid for item in definitions.values()}
    assert not referenced & set(definitions)
    assert mapping.source_template_artifact_uids == plan.artifact_uids

    PresentationMappingStore(tmp_path).put(plan.pack_uid, mapping)
    reopened = PresentationMappingStore(tmp_path)
    restored = reopened.latest_for_pack(plan.pack_uid)
    assert restored == mapping
    assert reopened.get(mapping.revision_uid) == mapping
    assert reopened.list(plan.pack_uid) == (mapping,)
    assert not (tmp_path / ".git").exists()
