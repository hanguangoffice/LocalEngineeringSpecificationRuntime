from __future__ import annotations

import pytest
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError
from pydantic import ValidationError

from lesr.adapters.schemas import SchemaCatalog
from lesr.domain.presentation import (
    EngineeringArea,
    Hierarchy,
    PresentationMappingRevision,
    PresentationSelector,
    TraceMatrix,
    ViewMode,
)
from lesr.domain.semantic import CoreResourceClass

UIDS = tuple(f"018f0000-0000-7000-8000-{index:012d}" for index in range(1, 20))


def object_selector(*kind_revision_uids: str) -> PresentationSelector:
    return PresentationSelector(kind_definition_revision_uids=kind_revision_uids)


def profile_mapping() -> PresentationMappingRevision:
    relation_uid = UIDS[4]
    return PresentationMappingRevision(
        presentation_mapping_uid=UIDS[0],
        revision_uid=UIDS[1],
        name="Local model engineering map",
        source_profile_revision_uids=(UIDS[2],),
        engineering_areas=(
            EngineeringArea(
                area_key="model-intent",
                label="模型目标与边界",
                selector=object_selector(UIDS[3]),
                order=10,
            ),
            EngineeringArea(
                area_key="evaluation-evidence",
                label="评估与证据",
                selector=object_selector(UIDS[5], UIDS[6]),
                order=20,
            ),
        ),
        hierarchies=(
            Hierarchy(
                hierarchy_key="model-breakdown",
                label="模型组成",
                root_selector=object_selector(UIDS[3]),
                member_selector=object_selector(UIDS[5]),
                relation_type_revision_uids=(relation_uid,),
            ),
        ),
        trace_matrices=(
            TraceMatrix(
                matrix_key="intent-to-evidence",
                label="目标到证据",
                row_selector=object_selector(UIDS[3]),
                column_selector=object_selector(UIDS[6]),
                relation_type_revision_uids=(relation_uid,),
                require_formal_trace_credit=True,
                formal_trace_category="evaluation",
            ),
        ),
        view_modes=(
            ViewMode.OVERVIEW,
            ViewMode.HIERARCHY,
            ViewMode.TRACE_MATRIX,
            ViewMode.COVERAGE,
        ),
        default_view_mode=ViewMode.OVERVIEW,
    )


def test_profile_driven_mapping_is_non_authoritative_and_schema_valid() -> None:
    mapping = profile_mapping()
    value = mapping.model_dump(mode="json")

    assert mapping.core_class is CoreResourceClass.PRESENTATION_RESOURCE
    assert mapping.creates_normative_facts is False
    assert "content_hash" not in value
    assert {item.area_key for item in mapping.engineering_areas} == {
        "model-intent",
        "evaluation-evidence",
    }
    SchemaCatalog().validate("presentation-mapping.schema.json", value)


def test_template_can_drive_a_domain_specific_view_without_a_profile_source() -> None:
    mapping = PresentationMappingRevision(
        presentation_mapping_uid=UIDS[7],
        revision_uid=UIDS[8],
        name="API contract map",
        source_template_artifact_uids=("openapi-contract", "arc42-building-block-view"),
        engineering_areas=(
            EngineeringArea(
                area_key="api-contract",
                label="接口契约",
                selector=PresentationSelector(
                    facet_definition_revision_uids=(UIDS[9],),
                    relation_type_revision_uids=(UIDS[10],),
                ),
            ),
        ),
        view_modes=(ViewMode.OVERVIEW, ViewMode.RELATION_GRAPH),
        default_view_mode=ViewMode.RELATION_GRAPH,
    )

    assert mapping.source_profile_revision_uids == ()
    SchemaCatalog().validate(
        "presentation-mapping.schema.json", mapping.model_dump(mode="json")
    )


def test_selectors_require_exact_definition_revision_uids_not_display_names() -> None:
    with pytest.raises(ValidationError, match="presentation selector requires"):
        PresentationSelector()

    with pytest.raises(ValidationError, match="string_pattern_mismatch"):
        PresentationSelector(kind_definition_revision_uids=("software_requirement",))


def test_mapping_requires_a_source_and_consistent_view_definitions() -> None:
    area = EngineeringArea(
        area_key="requirements",
        label="需求",
        selector=object_selector(UIDS[11]),
    )
    with pytest.raises(ValidationError, match="requires a Profile or template source"):
        PresentationMappingRevision(
            presentation_mapping_uid=UIDS[12],
            revision_uid=UIDS[13],
            name="Unbound view",
            engineering_areas=(area,),
            view_modes=(ViewMode.OVERVIEW,),
            default_view_mode=ViewMode.OVERVIEW,
        )
    with pytest.raises(ValidationError, match="hierarchy view mode requires"):
        PresentationMappingRevision(
            presentation_mapping_uid=UIDS[12],
            revision_uid=UIDS[13],
            name="Missing hierarchy",
            source_profile_revision_uids=(UIDS[14],),
            engineering_areas=(area,),
            view_modes=(ViewMode.HIERARCHY,),
            default_view_mode=ViewMode.HIERARCHY,
        )


def test_revision_lineage_replaces_a_presentation_hash() -> None:
    first = profile_mapping()
    second = first.model_copy(
        update={
            "revision_uid": UIDS[15],
            "revision_number": 2,
            "parent_revision_uid": first.revision_uid,
        }
    )

    assert second.presentation_mapping_uid == first.presentation_mapping_uid
    assert second.parent_revision_uid == first.revision_uid
    assert "content_hash" not in PresentationMappingRevision.model_fields

    with pytest.raises(ValidationError, match="later presentation revisions require"):
        PresentationMappingRevision(
            presentation_mapping_uid=UIDS[16],
            revision_uid=UIDS[17],
            revision_number=2,
            name="Broken lineage",
            source_profile_revision_uids=(UIDS[18],),
            engineering_areas=first.engineering_areas,
            view_modes=(ViewMode.OVERVIEW,),
            default_view_mode=ViewMode.OVERVIEW,
        )


def test_schema_forbids_a_presentation_view_from_claiming_normative_effect() -> None:
    value = profile_mapping().model_dump(mode="json")
    value["creates_normative_facts"] = True

    with pytest.raises(JsonSchemaValidationError):
        SchemaCatalog().validate("presentation-mapping.schema.json", value)
