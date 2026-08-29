"""Non-authoritative, Profile-driven presentation mappings for engineering views.

Presentation mappings only describe how an already resolved semantic graph is
organized for a human reader.  They do not create engineering facts, alter an
Effective Model, project lifecycle state, or grant Formal Trace Credit.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, model_validator

from lesr.domain.semantic import CoreResourceClass, FrozenModel, uuid7_candidate

RevisionUid = Annotated[
    str,
    Field(pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"),
]


class ViewMode(StrEnum):
    """Available representations of the same resolved engineering graph."""

    OVERVIEW = "overview"
    OUTLINE = "outline"
    HIERARCHY = "hierarchy"
    RELATION_GRAPH = "relation_graph"
    TRACE_MATRIX = "trace_matrix"
    DOCUMENT = "document"
    COVERAGE = "coverage"


class SelectorMatch(StrEnum):
    ANY = "any"
    ALL = "all"


class HierarchyDirection(StrEnum):
    SOURCE_TO_TARGET = "source_to_target"
    TARGET_TO_SOURCE = "target_to_source"


class PresentationSelector(FrozenModel):
    """Select semantic resources through exact definition Revision UIDs.

    Kind and Facet selectors identify objects.  Relation Type selectors identify
    relations, or narrow objects to those participating in those relations.  A
    renderer resolves the selector against an exact Configuration/Graph Snapshot;
    display labels and Human Keys are never treated as semantic selectors.
    """

    kind_definition_revision_uids: tuple[RevisionUid, ...] = ()
    facet_definition_revision_uids: tuple[RevisionUid, ...] = ()
    relation_type_revision_uids: tuple[RevisionUid, ...] = ()
    match: SelectorMatch = SelectorMatch.ANY

    @model_validator(mode="after")
    def validate_selector(self) -> PresentationSelector:
        groups = (
            self.kind_definition_revision_uids,
            self.facet_definition_revision_uids,
            self.relation_type_revision_uids,
        )
        if not any(groups):
            raise ValueError("presentation selector requires a Kind, Facet or Relation Type")
        if any(len(group) != len(set(group)) for group in groups):
            raise ValueError("presentation selector definition revisions must be unique")
        return self

    @property
    def selects_objects(self) -> bool:
        return bool(
            self.kind_definition_revision_uids or self.facet_definition_revision_uids
        )


class EngineeringArea(FrozenModel):
    """One Profile- or template-named area in an engineering overview."""

    area_key: str = Field(min_length=1, pattern=r"^[a-z][a-z0-9_.-]*$")
    label: str = Field(min_length=1)
    description: str | None = None
    selector: PresentationSelector
    order: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def area_selects_objects(self) -> EngineeringArea:
        if not self.selector.selects_objects:
            raise ValueError("engineering area requires a Kind or Facet selector")
        return self


class Hierarchy(FrozenModel):
    """A navigational hierarchy over explicitly selected Relation Types."""

    hierarchy_key: str = Field(min_length=1, pattern=r"^[a-z][a-z0-9_.-]*$")
    label: str = Field(min_length=1)
    root_selector: PresentationSelector
    member_selector: PresentationSelector
    relation_type_revision_uids: tuple[RevisionUid, ...] = Field(min_length=1)
    direction: HierarchyDirection = HierarchyDirection.SOURCE_TO_TARGET
    maximum_depth: int = Field(default=8, ge=1, le=16)

    @model_validator(mode="after")
    def validate_hierarchy(self) -> Hierarchy:
        if not self.root_selector.selects_objects or not self.member_selector.selects_objects:
            raise ValueError("hierarchy root and member selectors require Kind or Facet")
        if len(self.relation_type_revision_uids) != len(
            set(self.relation_type_revision_uids)
        ):
            raise ValueError("hierarchy Relation Type revisions must be unique")
        return self


class TraceMatrix(FrozenModel):
    """Rows, columns and relation semantics for a traceability matrix view."""

    matrix_key: str = Field(min_length=1, pattern=r"^[a-z][a-z0-9_.-]*$")
    label: str = Field(min_length=1)
    row_selector: PresentationSelector
    column_selector: PresentationSelector
    relation_type_revision_uids: tuple[RevisionUid, ...] = Field(min_length=1)
    require_formal_trace_credit: bool = False
    formal_trace_category: str | None = None

    @model_validator(mode="after")
    def validate_matrix(self) -> TraceMatrix:
        if not self.row_selector.selects_objects or not self.column_selector.selects_objects:
            raise ValueError("trace matrix row and column selectors require Kind or Facet")
        if len(self.relation_type_revision_uids) != len(
            set(self.relation_type_revision_uids)
        ):
            raise ValueError("trace matrix Relation Type revisions must be unique")
        if self.require_formal_trace_credit != (self.formal_trace_category is not None):
            raise ValueError(
                "formal_trace_category is required exactly when Formal Trace Credit is required"
            )
        return self


class PresentationMappingRevision(FrozenModel):
    """Versioned instructions for rendering, never a source of normative facts."""

    schema_version: Literal["1.0"] = "1.0"
    resource_type: Literal["presentation_mapping_revision"] = (
        "presentation_mapping_revision"
    )
    core_class: Literal[CoreResourceClass.PRESENTATION_RESOURCE] = (
        CoreResourceClass.PRESENTATION_RESOURCE
    )
    presentation_mapping_uid: RevisionUid = Field(default_factory=uuid7_candidate)
    revision_uid: RevisionUid = Field(default_factory=uuid7_candidate)
    revision_number: int = Field(default=1, ge=1)
    parent_revision_uid: RevisionUid | None = None
    name: str = Field(min_length=1)
    source_profile_revision_uids: tuple[RevisionUid, ...] = ()
    source_template_artifact_uids: tuple[str, ...] = ()
    engineering_areas: tuple[EngineeringArea, ...] = Field(min_length=1)
    hierarchies: tuple[Hierarchy, ...] = ()
    trace_matrices: tuple[TraceMatrix, ...] = ()
    view_modes: tuple[ViewMode, ...] = Field(min_length=1)
    default_view_mode: ViewMode
    creates_normative_facts: Literal[False] = False

    @model_validator(mode="after")
    def validate_mapping(self) -> PresentationMappingRevision:
        if not self.source_profile_revision_uids and not self.source_template_artifact_uids:
            raise ValueError("presentation mapping requires a Profile or template source")
        for values, label in (
            (self.source_profile_revision_uids, "source Profile revisions"),
            (self.source_template_artifact_uids, "source template artifacts"),
            (self.view_modes, "view modes"),
        ):
            if len(values) != len(set(values)):
                raise ValueError(f"presentation mapping {label} must be unique")
        for keys, label in (
            ((item.area_key for item in self.engineering_areas), "engineering area keys"),
            ((item.hierarchy_key for item in self.hierarchies), "hierarchy keys"),
            ((item.matrix_key for item in self.trace_matrices), "trace matrix keys"),
        ):
            materialized = tuple(keys)
            if len(materialized) != len(set(materialized)):
                raise ValueError(f"presentation mapping {label} must be unique")
        if self.default_view_mode not in self.view_modes:
            raise ValueError("default view mode must be enabled")
        if ViewMode.HIERARCHY in self.view_modes and not self.hierarchies:
            raise ValueError("hierarchy view mode requires a hierarchy definition")
        if ViewMode.TRACE_MATRIX in self.view_modes and not self.trace_matrices:
            raise ValueError("trace matrix view mode requires a trace matrix definition")
        if self.revision_number == 1 and self.parent_revision_uid is not None:
            raise ValueError("first presentation revision cannot have a parent revision")
        if self.revision_number > 1 and self.parent_revision_uid is None:
            raise ValueError("later presentation revisions require a parent revision")
        return self
