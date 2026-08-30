"""Read-only engineering views projected from resolved LESR semantics.

The projection consumes an exact Presentation Mapping, Effective Model and
Graph Snapshot.  It organizes those existing facts for a human reader; it does
not create semantic resources, grant trace credit, or mutate Canonical State.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import Field

from lesr.domain.evaluation import (
    ContextBundle,
    ContextCompleteness,
    GraphNode,
    GraphSnapshot,
    SemanticEvaluator,
)
from lesr.domain.model import (
    DefinitionRevision,
    EffectiveModel,
    FacetDefinitionRevision,
    KindDefinitionRevision,
    RelationTypeRevision,
)
from lesr.domain.presentation import (
    EngineeringArea,
    Hierarchy,
    HierarchyDirection,
    PresentationMappingRevision,
    PresentationSelector,
    SelectorMatch,
    TraceMatrix,
    ViewMode,
)
from lesr.domain.semantic import FrozenModel, JsonValue


class TraceCoverageState(StrEnum):
    COVERED = "covered"
    UNCOVERED = "uncovered"
    INDETERMINATE = "indeterminate"


class EngineeringItem(FrozenModel):
    """Human-facing summary of one selected Revision without technical identity."""

    human_key: str = Field(min_length=1)
    title: str = Field(min_length=1)
    kind_name: str = Field(min_length=1)
    lifecycle_state: str = Field(min_length=1)
    revision_number: int = Field(ge=1)
    is_candidate: bool = False
    summary: str | None = None
    fragment_count: int = Field(default=0, ge=0)


class EngineeringAreaNode(FrozenModel):
    """A mapping-defined engineering area with its document/item leaves."""

    area_key: str
    label: str
    description: str | None = None
    order: int = Field(ge=0)
    items: tuple[EngineeringItem, ...]

    @property
    def item_count(self) -> int:
        return len(self.items)


class EngineeringHierarchyNode(FrozenModel):
    item: EngineeringItem
    children: tuple[EngineeringHierarchyNode, ...] = ()
    truncated: bool = False
    cycle_detected: bool = False


class EngineeringHierarchyView(FrozenModel):
    hierarchy_key: str
    label: str
    roots: tuple[EngineeringHierarchyNode, ...]
    unplaced_items: tuple[EngineeringItem, ...] = ()


class EngineeringTraceLink(FrozenModel):
    target: EngineeringItem
    predicate: str = Field(min_length=1)
    lifecycle_state: str = Field(min_length=1)
    formal_credit: bool


class EngineeringTraceRow(FrozenModel):
    source: EngineeringItem
    state: TraceCoverageState
    links: tuple[EngineeringTraceLink, ...] = ()
    rejected_link_count: int = Field(default=0, ge=0)


class EngineeringTraceCoverage(FrozenModel):
    matrix_key: str
    label: str
    requires_formal_credit: bool
    rows: tuple[EngineeringTraceRow, ...]
    covered_count: int = Field(ge=0)
    uncovered_count: int = Field(ge=0)
    indeterminate_count: int = Field(ge=0)
    unresolved_external_count: int = Field(default=0, ge=0)

    @property
    def total_count(self) -> int:
        return len(self.rows)


class EngineeringContextSummary(FrozenModel):
    stage: Literal["manifest", "focused_read", "deep_trace"]
    completeness: ContextCompleteness
    mandatory_items: tuple[EngineeringItem, ...]
    supporting_items: tuple[EngineeringItem, ...]
    omitted_count: int = Field(ge=0)
    unavailable_count: int = Field(ge=0)


class EngineeringView(FrozenModel):
    """Transient human presentation of an exact resolved engineering graph."""

    schema_version: Literal["1.0"] = "1.0"
    resource_type: Literal["engineering_view"] = "engineering_view"
    persistence_scope: Literal["derived_read_model"] = "derived_read_model"
    canonical_git_eligible: Literal[False] = False
    mapping_name: str = Field(min_length=1)
    default_view_mode: ViewMode
    available_view_modes: tuple[ViewMode, ...]
    evaluation_time: datetime
    areas: tuple[EngineeringAreaNode, ...]
    hierarchies: tuple[EngineeringHierarchyView, ...]
    trace_coverage: tuple[EngineeringTraceCoverage, ...]
    context: EngineeringContextSummary | None = None
    creates_normative_facts: Literal[False] = False


def build_engineering_view(
    mapping: PresentationMappingRevision,
    effective_model: EffectiveModel,
    snapshot: GraphSnapshot,
    definition_revisions: tuple[DefinitionRevision, ...],
    *,
    context_bundle: ContextBundle | None = None,
) -> EngineeringView:
    """Project one immutable, non-authoritative engineering view."""

    projector = _EngineeringViewProjector(
        mapping,
        effective_model,
        snapshot,
        definition_revisions,
    )
    return projector.build(context_bundle)


class _EngineeringViewProjector:
    def __init__(
        self,
        mapping: PresentationMappingRevision,
        effective_model: EffectiveModel,
        snapshot: GraphSnapshot,
        definitions: tuple[DefinitionRevision, ...],
    ) -> None:
        self.mapping = mapping
        self.effective_model = effective_model
        self.snapshot = snapshot
        by_uid = {item.revision_uid: item for item in definitions}
        if len(by_uid) != len(definitions):
            raise ValueError("definition Revision UIDs must be unique")
        self.definitions = by_uid
        self.kind_definitions = {
            uid: item for uid, item in by_uid.items() if isinstance(item, KindDefinitionRevision)
        }
        self.facet_definitions = {
            uid: item for uid, item in by_uid.items() if isinstance(item, FacetDefinitionRevision)
        }
        self.relation_types = {
            uid: item for uid, item in by_uid.items() if isinstance(item, RelationTypeRevision)
        }
        self.node_by_object = {item.revision.object_uid: item for item in self.snapshot.nodes}
        self.item_by_object = {
            object_uid: self._item(node) for object_uid, node in self.node_by_object.items()
        }
        self._validate_inputs()

    def build(self, context_bundle: ContextBundle | None) -> EngineeringView:
        areas = tuple(
            self._area(area)
            for area in sorted(
                self.mapping.engineering_areas,
                key=lambda item: (item.order, item.area_key),
            )
        )
        hierarchies = tuple(self._hierarchy(item) for item in self.mapping.hierarchies)
        traces = tuple(self._trace_matrix(item) for item in self.mapping.trace_matrices)
        context = self._context(context_bundle) if context_bundle is not None else None
        return EngineeringView(
            mapping_name=self.mapping.name,
            default_view_mode=self.mapping.default_view_mode,
            available_view_modes=self.mapping.view_modes,
            evaluation_time=self.snapshot.evaluation_time,
            areas=areas,
            hierarchies=hierarchies,
            trace_coverage=traces,
            context=context,
        )

    def _validate_inputs(self) -> None:
        if self.snapshot.effective_model_hash != self.effective_model.model_hash:
            raise ValueError("Graph Snapshot belongs to another Effective Model")
        if self.mapping.source_profile_revision_uids and not set(
            self.mapping.source_profile_revision_uids
        ) <= set(self.effective_model.profile_revision_uids):
            raise ValueError("Presentation Mapping source Profile is not active")
        selected = set(self.effective_model.definition_revision_uids)
        referenced = _referenced_definition_uids(self.mapping)
        inactive = referenced - selected
        if inactive:
            raise ValueError("Presentation Mapping references an inactive definition Revision")
        unavailable = referenced - set(self.definitions)
        if unavailable:
            raise ValueError("Presentation Mapping definition Revision is unavailable")
        for uid in referenced:
            definition = self.definitions[uid]
            if uid in _kind_selector_uids(self.mapping) and not isinstance(
                definition, KindDefinitionRevision
            ):
                raise ValueError("Kind selector references another definition type")
            if uid in _facet_selector_uids(self.mapping) and not isinstance(
                definition, FacetDefinitionRevision
            ):
                raise ValueError("Facet selector references another definition type")
            if uid in _relation_selector_uids(self.mapping) and not isinstance(
                definition, RelationTypeRevision
            ):
                raise ValueError("Relation selector references another definition type")

    def _area(self, area: EngineeringArea) -> EngineeringAreaNode:
        selected = self._selected_nodes(area.selector)
        return EngineeringAreaNode(
            area_key=area.area_key,
            label=area.label,
            description=area.description,
            order=area.order,
            items=tuple(self.item_by_object[item.revision.object_uid] for item in selected),
        )

    def _hierarchy(self, hierarchy: Hierarchy) -> EngineeringHierarchyView:
        roots = self._selected_nodes(hierarchy.root_selector)
        members = {
            item.revision.object_uid for item in self._selected_nodes(hierarchy.member_selector)
        }
        adjacency: dict[str, set[str]] = defaultdict(set)
        allowed_types = set(hierarchy.relation_type_revision_uids)
        for relation in self.snapshot.relations:
            if (
                relation.relation_type_revision_uid not in allowed_types
                or relation.lifecycle_state.casefold() == "retired"
            ):
                continue
            source_uid = relation.assertion.source.object_uid
            target_uid = relation.assertion.target.object_uid
            if source_uid is None or target_uid is None:
                continue
            parent_uid, child_uid = (
                (source_uid, target_uid)
                if hierarchy.direction is HierarchyDirection.SOURCE_TO_TARGET
                else (target_uid, source_uid)
            )
            if child_uid in members and parent_uid in self.node_by_object:
                adjacency[parent_uid].add(child_uid)

        reached: set[str] = set()

        def branch(
            object_uid: str,
            *,
            depth: int,
            path: frozenset[str],
        ) -> EngineeringHierarchyNode:
            reached.add(object_uid)
            next_uids = tuple(
                sorted(
                    adjacency.get(object_uid, ()),
                    key=lambda uid: self.item_by_object[uid].human_key,
                )
            )
            if depth >= hierarchy.maximum_depth:
                return EngineeringHierarchyNode(
                    item=self.item_by_object[object_uid],
                    truncated=bool(next_uids),
                )
            children: list[EngineeringHierarchyNode] = []
            for child_uid in next_uids:
                if child_uid in path:
                    reached.add(child_uid)
                    children.append(
                        EngineeringHierarchyNode(
                            item=self.item_by_object[child_uid],
                            cycle_detected=True,
                        )
                    )
                    continue
                children.append(
                    branch(
                        child_uid,
                        depth=depth + 1,
                        path=path | {child_uid},
                    )
                )
            return EngineeringHierarchyNode(
                item=self.item_by_object[object_uid],
                children=tuple(children),
            )

        root_views = tuple(
            branch(
                node.revision.object_uid,
                depth=0,
                path=frozenset({node.revision.object_uid}),
            )
            for node in roots
        )
        root_uids = {item.revision.object_uid for item in roots}
        unplaced = tuple(
            self.item_by_object[uid]
            for uid in sorted(
                members - reached - root_uids,
                key=lambda value: self.item_by_object[value].human_key,
            )
        )
        return EngineeringHierarchyView(
            hierarchy_key=hierarchy.hierarchy_key,
            label=hierarchy.label,
            roots=root_views,
            unplaced_items=unplaced,
        )

    def _trace_matrix(self, matrix: TraceMatrix) -> EngineeringTraceCoverage:
        row_nodes = self._selected_nodes(matrix.row_selector)
        column_uids = {
            item.revision.object_uid for item in self._selected_nodes(matrix.column_selector)
        }
        evaluator = SemanticEvaluator(self.snapshot, tuple(self.relation_types.values()))
        allowed_types = set(matrix.relation_type_revision_uids)
        rows: list[EngineeringTraceRow] = []
        unresolved_external = 0
        for row_node in row_nodes:
            row_uid = row_node.revision.object_uid
            links: dict[str, EngineeringTraceLink] = {}
            rejected = 0
            row_indeterminate = False
            for relation in sorted(
                self.snapshot.relations,
                key=lambda item: item.assertion.relation_revision_uid,
            ):
                if relation.relation_type_revision_uid not in allowed_types:
                    continue
                assertion = relation.assertion
                if assertion.source.object_uid != row_uid:
                    continue
                if assertion.target.object_uid is None:
                    row_indeterminate = True
                    unresolved_external += 1
                    continue
                target_uid = assertion.target.object_uid
                if target_uid not in column_uids:
                    continue
                formal_credit = False
                if relation.lifecycle_state.casefold() == "retired":
                    rejected += 1
                    continue
                if matrix.require_formal_trace_credit:
                    assert matrix.formal_trace_category is not None
                    formal_credit = evaluator.formal_trace_credit(
                        relation,
                        matrix.formal_trace_category,
                    ).granted
                    if not formal_credit:
                        rejected += 1
                        continue
                relation_type = self.relation_types[relation.relation_type_revision_uid]
                links[target_uid] = EngineeringTraceLink(
                    target=self.item_by_object[target_uid],
                    predicate=relation_type.predicate,
                    lifecycle_state=relation.lifecycle_state,
                    formal_credit=formal_credit,
                )
            ordered_links = tuple(
                links[uid]
                for uid in sorted(links, key=lambda value: self.item_by_object[value].human_key)
            )
            state = (
                TraceCoverageState.COVERED
                if ordered_links
                else TraceCoverageState.INDETERMINATE
                if row_indeterminate
                else TraceCoverageState.UNCOVERED
            )
            rows.append(
                EngineeringTraceRow(
                    source=self.item_by_object[row_uid],
                    state=state,
                    links=ordered_links,
                    rejected_link_count=rejected,
                )
            )
        return EngineeringTraceCoverage(
            matrix_key=matrix.matrix_key,
            label=matrix.label,
            requires_formal_credit=matrix.require_formal_trace_credit,
            rows=tuple(rows),
            covered_count=sum(item.state is TraceCoverageState.COVERED for item in rows),
            uncovered_count=sum(item.state is TraceCoverageState.UNCOVERED for item in rows),
            indeterminate_count=sum(
                item.state is TraceCoverageState.INDETERMINATE for item in rows
            ),
            unresolved_external_count=unresolved_external,
        )

    def _context(self, bundle: ContextBundle) -> EngineeringContextSummary:
        if bundle.graph_snapshot_hash != self.snapshot.snapshot_hash:
            raise ValueError("Context Bundle belongs to another Graph Snapshot")
        by_reference: dict[str, EngineeringItem] = {}
        for node in self.snapshot.nodes:
            item = self.item_by_object[node.revision.object_uid]
            by_reference[node.revision.object_uid] = item
            by_reference[node.revision.revision_uid] = item
            by_reference.setdefault(node.revision.human_key, item)
        mandatory, missing_mandatory = _context_items(bundle.mandatory, by_reference)
        supporting, missing_supporting = _context_items(bundle.supporting, by_reference)
        return EngineeringContextSummary(
            stage=bundle.stage,
            completeness=bundle.completeness,
            mandatory_items=mandatory,
            supporting_items=supporting,
            omitted_count=len(bundle.omitted_candidates),
            unavailable_count=missing_mandatory + missing_supporting,
        )

    def _selected_nodes(self, selector: PresentationSelector) -> tuple[GraphNode, ...]:
        return tuple(
            sorted(
                (item for item in self.snapshot.nodes if self._matches(item, selector)),
                key=lambda item: (
                    item.revision.human_key,
                    item.revision.revision_number,
                ),
            )
        )

    def _matches(self, node: GraphNode, selector: PresentationSelector) -> bool:
        group_matches: list[bool] = []
        if selector.kind_definition_revision_uids:
            group_matches.append(
                any(
                    self._kind_matches(
                        node,
                        self.kind_definitions[uid],
                    )
                    for uid in selector.kind_definition_revision_uids
                )
            )
        if selector.facet_definition_revision_uids:
            group_matches.append(
                any(
                    self._facet_matches(
                        node,
                        self.facet_definitions[uid],
                    )
                    for uid in selector.facet_definition_revision_uids
                )
            )
        if selector.relation_type_revision_uids:
            object_uid = node.revision.object_uid
            allowed = set(selector.relation_type_revision_uids)
            group_matches.append(
                any(
                    relation.relation_type_revision_uid in allowed
                    and relation.lifecycle_state.casefold() != "retired"
                    and object_uid
                    in {
                        relation.assertion.source.object_uid,
                        relation.assertion.target.object_uid,
                    }
                    for relation in self.snapshot.relations
                )
            )
        return all(group_matches) if selector.match is SelectorMatch.ALL else any(group_matches)

    @staticmethod
    def _kind_matches(node: GraphNode, definition: KindDefinitionRevision) -> bool:
        return node.revision.kind in {
            definition.name,
            definition.kind_uid,
            definition.revision_uid,
        }

    def _facet_matches(self, node: GraphNode, definition: FacetDefinitionRevision) -> bool:
        aliases = {definition.name, definition.facet_uid, definition.revision_uid}
        if bool(set(node.revision.facets) & aliases):
            return True
        kind = self._kind_for_node(node)
        return bool(kind and definition.revision_uid in kind.required_facet_revision_uids)

    def _kind_for_node(self, node: GraphNode) -> KindDefinitionRevision | None:
        return next(
            (item for item in self.kind_definitions.values() if self._kind_matches(node, item)),
            None,
        )

    def _item(self, node: GraphNode) -> EngineeringItem:
        kind = self._kind_for_node(node)
        title = _first_text(node.revision.fields, ("title", "name", "summary"))
        summary = _first_text(
            node.revision.fields,
            ("summary", "statement", "description", "body", "text"),
        )
        display_title = title or node.revision.human_key
        if summary == display_title:
            summary = None
        return EngineeringItem(
            human_key=node.revision.human_key,
            title=display_title,
            kind_name=kind.name if kind is not None else node.revision.kind,
            lifecycle_state=node.lifecycle_state,
            revision_number=node.revision.revision_number,
            is_candidate=node.source == "candidate",
            summary=_excerpt(summary) if summary is not None else None,
            fragment_count=len(node.revision.fragments),
        )


def _first_text(
    fields: tuple[object, ...],
    names: tuple[str, ...],
) -> str | None:
    by_name: dict[str, JsonValue] = {}
    for raw in fields:
        path = getattr(raw, "path", None)
        value = getattr(raw, "value", None)
        if isinstance(path, str):
            by_name[path.strip("/").casefold()] = value
    for name in names:
        value = by_name.get(name)
        if isinstance(value, str) and value.strip():
            return " ".join(value.split())
    return None


def _excerpt(value: str, limit: int = 280) -> str:
    return value if len(value) <= limit else value[: limit - 1].rstrip() + "…"


def _context_items(
    references: tuple[str, ...],
    by_reference: dict[str, EngineeringItem],
) -> tuple[tuple[EngineeringItem, ...], int]:
    selected: dict[tuple[str, int], EngineeringItem] = {}
    missing = 0
    for reference in references:
        item = by_reference.get(reference)
        if item is None:
            missing += 1
            continue
        selected[(item.human_key, item.revision_number)] = item
    return tuple(selected[key] for key in sorted(selected)), missing


def _selectors(mapping: PresentationMappingRevision) -> tuple[PresentationSelector, ...]:
    return (
        *(item.selector for item in mapping.engineering_areas),
        *(item.root_selector for item in mapping.hierarchies),
        *(item.member_selector for item in mapping.hierarchies),
        *(item.row_selector for item in mapping.trace_matrices),
        *(item.column_selector for item in mapping.trace_matrices),
    )


def _kind_selector_uids(mapping: PresentationMappingRevision) -> set[str]:
    return {
        uid for selector in _selectors(mapping) for uid in selector.kind_definition_revision_uids
    }


def _facet_selector_uids(mapping: PresentationMappingRevision) -> set[str]:
    return {
        uid for selector in _selectors(mapping) for uid in selector.facet_definition_revision_uids
    }


def _relation_selector_uids(mapping: PresentationMappingRevision) -> set[str]:
    return {
        *(uid for selector in _selectors(mapping) for uid in selector.relation_type_revision_uids),
        *(
            uid
            for hierarchy in mapping.hierarchies
            for uid in hierarchy.relation_type_revision_uids
        ),
        *(uid for matrix in mapping.trace_matrices for uid in matrix.relation_type_revision_uids),
    }


def _referenced_definition_uids(mapping: PresentationMappingRevision) -> set[str]:
    return (
        _kind_selector_uids(mapping)
        | _facet_selector_uids(mapping)
        | _relation_selector_uids(mapping)
    )
