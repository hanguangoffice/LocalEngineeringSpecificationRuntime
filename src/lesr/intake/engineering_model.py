"""Translate one verified TemplatePack into an initial engineering model.

The catalog remains the authority for which upstream artifacts belong to a
pack.  This module only maps those exact artifact/source identities to LESR
Kind names and to a non-authoritative presentation layout.  It deliberately
does not invent lifecycle, trace or approval policy from a document title.
"""

from __future__ import annotations

from collections.abc import Mapping

from pydantic import Field, model_validator

from lesr.domain.model import KindDefinitionRevision
from lesr.domain.presentation import (
    EngineeringArea,
    PresentationMappingRevision,
    PresentationSelector,
    ViewMode,
)
from lesr.domain.semantic import FrozenModel
from lesr.intake.models import RequirementCategory, TemplatePack


class RequirementKindBinding(FrozenModel):
    category: RequirementCategory
    kind_name: str = Field(min_length=1, pattern=r"^[a-z][a-z0-9_]*$")


class EngineeringAreaPlan(FrozenModel):
    """One area whose name and scope come from a selected template artifact."""

    area_key: str = Field(min_length=1, pattern=r"^[a-z][a-z0-9_.-]*$")
    label: str = Field(min_length=1)
    description: str = Field(min_length=1)
    source_uid: str = Field(min_length=1)
    artifact_uid: str = Field(min_length=1)
    kind_names: tuple[str, ...] = Field(min_length=1)
    order: int = Field(ge=0)


class TemplateEngineeringModel(FrozenModel):
    """Semantic bootstrap plan derived from one selected TemplatePack."""

    pack_uid: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    source_uids: tuple[str, ...] = Field(min_length=1)
    artifact_uids: tuple[str, ...] = Field(min_length=1)
    kind_names: tuple[str, ...] = Field(min_length=1)
    category_bindings: tuple[RequirementKindBinding, ...] = Field(min_length=1)
    areas: tuple[EngineeringAreaPlan, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_plan(self) -> TemplateEngineeringModel:
        if len(self.kind_names) != len(set(self.kind_names)):
            raise ValueError("template engineering Kind names must be unique")
        if len(self.artifact_uids) != len(set(self.artifact_uids)):
            raise ValueError("template engineering artifacts must be unique")
        categories = tuple(item.category for item in self.category_bindings)
        if len(categories) != len(set(categories)):
            raise ValueError("requirement categories must have one Kind binding")
        enabled = set(self.kind_names)
        if any(item.kind_name not in enabled for item in self.category_bindings):
            raise ValueError("requirement category references a disabled Kind")
        if any(set(item.kind_names) - enabled for item in self.areas):
            raise ValueError("engineering area references a disabled Kind")
        return self

    def kind_for(self, category: RequirementCategory) -> str:
        try:
            return next(
                item.kind_name
                for item in self.category_bindings
                if item.category is category
            )
        except StopIteration as error:
            raise KeyError(category.value) from error


_REQUIREMENT_BINDINGS: tuple[RequirementKindBinding, ...] = (
    RequirementKindBinding(
        category=RequirementCategory.GOAL,
        kind_name="goal",
    ),
    RequirementKindBinding(
        category=RequirementCategory.FUNCTION,
        kind_name="functional_requirement",
    ),
    RequirementKindBinding(
        category=RequirementCategory.QUALITY,
        kind_name="quality_requirement",
    ),
    RequirementKindBinding(
        category=RequirementCategory.CONSTRAINT,
        kind_name="constraint_requirement",
    ),
    RequirementKindBinding(
        category=RequirementCategory.SAFETY,
        kind_name="safety_requirement",
    ),
    RequirementKindBinding(
        category=RequirementCategory.TEST,
        kind_name="test_case",
    ),
    RequirementKindBinding(
        category=RequirementCategory.DELIVERABLE,
        kind_name="deliverable",
    ),
    RequirementKindBinding(
        category=RequirementCategory.DEPENDENCY,
        kind_name="dependency",
    ),
)


# These capabilities are tied to exact catalog source identities.  A future
# source is unsupported until its engineering vocabulary is reviewed here.
_SOURCE_KIND_NAMES: Mapping[str, tuple[str, ...]] = {
    "github-spec-kit-2026-08-28": tuple(
        item.kind_name for item in _REQUIREMENT_BINDINGS
    )
    + ("evidence",),
    "arc42-zh-2026-07-07": ("design",),
    "madr-4.0.0": ("architecture_decision",),
    "swagger-petstore-v31-1.0.10": ("api_contract", "data_model"),
    "asyncapi-3.1.0": ("message_contract", "data_model"),
    "cookiecutter-data-science-2.3.0": ("data_asset", "model_asset"),
    "model-card-toolkit-2.0.0": ("model_asset", "evidence"),
    "owasp-threat-model-library-1.0.2": ("threat",),
    "nasa-fret-3.1.0": ("safety_requirement",),
}


def engineering_model_for(pack: TemplatePack) -> TemplateEngineeringModel:
    """Derive enabled Kinds and named areas from exact selected artifacts."""

    areas: list[EngineeringAreaPlan] = []
    enabled: list[str] = []
    for order, artifact in enumerate(pack.artifacts, start=1):
        if artifact.source_uid not in pack.source_uids:
            raise ValueError("template artifact source is not enabled by its pack")
        try:
            kinds = _SOURCE_KIND_NAMES[artifact.source_uid]
        except KeyError as error:
            raise ValueError(
                f"template source has no reviewed engineering mapping: {artifact.source_uid}"
            ) from error
        for kind_name in kinds:
            if kind_name not in enabled:
                enabled.append(kind_name)
        areas.append(
            EngineeringAreaPlan(
                area_key=artifact.artifact_uid,
                label=artifact.display_name,
                description=artifact.purpose,
                source_uid=artifact.source_uid,
                artifact_uid=artifact.artifact_uid,
                kind_names=kinds,
                order=order * 10,
            )
        )
    bindings = tuple(
        item for item in _REQUIREMENT_BINDINGS if item.kind_name in enabled
    )
    return TemplateEngineeringModel(
        pack_uid=pack.pack_uid,
        display_name=pack.display_name,
        source_uids=pack.source_uids,
        artifact_uids=tuple(item.artifact_uid for item in pack.artifacts),
        kind_names=tuple(enabled),
        category_bindings=bindings,
        areas=tuple(areas),
    )


def build_presentation_mapping(
    plan: TemplateEngineeringModel,
    kind_definitions: Mapping[str, KindDefinitionRevision],
    *,
    profile_revision_uids: tuple[str, ...],
) -> PresentationMappingRevision:
    """Bind a template layout to exact active Kind definition revisions."""

    missing = set(plan.kind_names) - set(kind_definitions)
    if missing:
        raise ValueError(
            "active engineering model is missing template Kinds: "
            + ", ".join(sorted(missing))
        )
    areas = tuple(
        EngineeringArea(
            area_key=item.area_key,
            label=item.label,
            description=item.description,
            selector=PresentationSelector(
                kind_definition_revision_uids=tuple(
                    kind_definitions[name].revision_uid for name in item.kind_names
                )
            ),
            order=item.order,
        )
        for item in plan.areas
    )
    return PresentationMappingRevision(
        name=f"{plan.display_name}工程结构",
        source_profile_revision_uids=profile_revision_uids,
        source_template_artifact_uids=plan.artifact_uids,
        engineering_areas=areas,
        view_modes=(ViewMode.OVERVIEW, ViewMode.OUTLINE, ViewMode.DOCUMENT),
        default_view_mode=ViewMode.OVERVIEW,
    )
