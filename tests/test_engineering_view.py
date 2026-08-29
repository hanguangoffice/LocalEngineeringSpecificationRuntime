from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from lesr.application.engineering_view import (
    TraceCoverageState,
    build_engineering_view,
)
from lesr.domain.evaluation import (
    ContextBundle,
    ContextCompleteness,
    GraphNode,
    GraphRelation,
    GraphSnapshot,
)
from lesr.domain.model import (
    CompositionMode,
    EffectiveModel,
    EffectiveModelCompiler,
    FacetDefinitionRevision,
    KindDefinitionRevision,
    NormativeProfileRevision,
    ProfileContribution,
    ProfileLayer,
    RelationTypeRevision,
)
from lesr.domain.presentation import (
    EngineeringArea,
    Hierarchy,
    PresentationMappingRevision,
    PresentationSelector,
    SelectorMatch,
    TraceMatrix,
    ViewMode,
)
from lesr.domain.semantic import (
    BindingMode,
    CoreRelationRole,
    CoreResourceClass,
    ProvenanceKind,
    RelationAssertion,
    RelationEndpoint,
    Revision,
    SemanticField,
)

NOW = datetime(2026, 8, 30, 10, 0, tzinfo=UTC)
UIDS = tuple(f"018f0000-0000-7000-8000-{index:012d}" for index in range(1, 80))


def definitions() -> tuple[
    FacetDefinitionRevision,
    FacetDefinitionRevision,
    KindDefinitionRevision,
    KindDefinitionRevision,
    KindDefinitionRevision,
    RelationTypeRevision,
    RelationTypeRevision,
]:
    intent_facet = FacetDefinitionRevision(
        revision_uid=UIDS[0],
        facet_uid=UIDS[1],
        name="intent_content",
    )
    evidence_facet = FacetDefinitionRevision(
        revision_uid=UIDS[2],
        facet_uid=UIDS[3],
        name="evidence_content",
    )
    goal_kind = KindDefinitionRevision(
        revision_uid=UIDS[4],
        kind_uid=UIDS[5],
        name="model_goal",
        core_class=CoreResourceClass.GOVERNED_OBJECT,
        required_facet_revision_uids=(intent_facet.revision_uid,),
    )
    component_kind = KindDefinitionRevision(
        revision_uid=UIDS[6],
        kind_uid=UIDS[7],
        name="model_component",
        core_class=CoreResourceClass.GOVERNED_OBJECT,
    )
    evidence_kind = KindDefinitionRevision(
        revision_uid=UIDS[8],
        kind_uid=UIDS[9],
        name="evaluation_result",
        core_class=CoreResourceClass.GOVERNED_OBJECT,
        required_facet_revision_uids=(evidence_facet.revision_uid,),
    )
    decomposition = RelationTypeRevision(
        revision_uid=UIDS[10],
        relation_type_uid=UIDS[11],
        predicate="contains",
        core_role=CoreRelationRole.COMPOSES,
        source_kind_or_facet=(goal_kind.name,),
        target_kind_or_facet=(component_kind.name,),
        allowed_bindings=(BindingMode.PINNED,),
        default_binding=BindingMode.PINNED,
        workflow_revision_uid=UIDS[12],
    )
    evaluation = RelationTypeRevision(
        revision_uid=UIDS[13],
        relation_type_uid=UIDS[14],
        predicate="evaluated_by",
        core_role=CoreRelationRole.VERIFIES,
        source_kind_or_facet=(goal_kind.name,),
        target_kind_or_facet=(evidence_kind.name,),
        allowed_bindings=(BindingMode.PINNED,),
        default_binding=BindingMode.PINNED,
        workflow_revision_uid=UIDS[15],
        formal_trace_categories=("evaluation",),
    )
    return (
        intent_facet,
        evidence_facet,
        goal_kind,
        component_kind,
        evidence_kind,
        decomposition,
        evaluation,
    )


def effective_model(
    values: tuple[
        FacetDefinitionRevision,
        FacetDefinitionRevision,
        KindDefinitionRevision,
        KindDefinitionRevision,
        KindDefinitionRevision,
        RelationTypeRevision,
        RelationTypeRevision,
    ],
) -> tuple[NormativeProfileRevision, EffectiveModel]:
    profile = NormativeProfileRevision(
        profile_uid=UIDS[16],
        profile_revision_uid=UIDS[17],
        layer=ProfileLayer.PROJECT,
        authority=10,
        contributions=tuple(
            ProfileContribution(
                mode=CompositionMode.EXTEND,
                definition_revision_uid=item.revision_uid,
            )
            for item in values
        ),
    )
    return profile, EffectiveModelCompiler().compile((profile,), values)


def mapping(
    profile: NormativeProfileRevision,
    values: tuple[
        FacetDefinitionRevision,
        FacetDefinitionRevision,
        KindDefinitionRevision,
        KindDefinitionRevision,
        KindDefinitionRevision,
        RelationTypeRevision,
        RelationTypeRevision,
    ],
) -> PresentationMappingRevision:
    (
        intent_facet,
        evidence_facet,
        goal_kind,
        component_kind,
        evidence_kind,
        decomposition,
        evaluation,
    ) = values
    return PresentationMappingRevision(
        presentation_mapping_uid=UIDS[18],
        revision_uid=UIDS[19],
        name="模型工程视图",
        source_profile_revision_uids=(profile.profile_revision_uid,),
        engineering_areas=(
            EngineeringArea(
                area_key="intent",
                label="目标与边界",
                selector=PresentationSelector(
                    kind_definition_revision_uids=(goal_kind.revision_uid,),
                    facet_definition_revision_uids=(intent_facet.revision_uid,),
                    match=SelectorMatch.ALL,
                ),
                order=10,
            ),
            EngineeringArea(
                area_key="evidence",
                label="评估证据",
                selector=PresentationSelector(
                    kind_definition_revision_uids=(evidence_kind.revision_uid,),
                    facet_definition_revision_uids=(evidence_facet.revision_uid,),
                    match=SelectorMatch.ALL,
                ),
                order=20,
            ),
        ),
        hierarchies=(
            Hierarchy(
                hierarchy_key="breakdown",
                label="目标分解",
                root_selector=PresentationSelector(
                    kind_definition_revision_uids=(goal_kind.revision_uid,)
                ),
                member_selector=PresentationSelector(
                    kind_definition_revision_uids=(component_kind.revision_uid,)
                ),
                relation_type_revision_uids=(decomposition.revision_uid,),
            ),
        ),
        trace_matrices=(
            TraceMatrix(
                matrix_key="goal-evaluation",
                label="目标与评估覆盖",
                row_selector=PresentationSelector(
                    kind_definition_revision_uids=(goal_kind.revision_uid,)
                ),
                column_selector=PresentationSelector(
                    kind_definition_revision_uids=(evidence_kind.revision_uid,)
                ),
                relation_type_revision_uids=(evaluation.revision_uid,),
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


def revision(
    object_uid: str,
    revision_uid: str,
    human_key: str,
    kind: str,
    title: str,
    summary: str,
) -> Revision:
    return Revision(
        object_uid=object_uid,
        revision_uid=revision_uid,
        revision_number=1,
        human_key=human_key,
        kind=kind,
        fields=(
            SemanticField.from_value("title", title),
            SemanticField.from_value("statement", summary),
        ),
        provenance_origin=ProvenanceKind.AUTHORED,
        created_at=NOW,
    )


def endpoint(value: Revision) -> RelationEndpoint:
    return RelationEndpoint(
        binding=BindingMode.PINNED,
        object_uid=value.object_uid,
        revision_uid=value.revision_uid,
    )


def relation(
    source: Revision,
    target: Revision,
    relation_type: RelationTypeRevision,
    relation_index: int,
    *,
    provenance: ProvenanceKind = ProvenanceKind.ASSERTED,
) -> GraphRelation:
    return GraphRelation(
        assertion=RelationAssertion(
            assertion_uid=UIDS[relation_index],
            relation_revision_uid=UIDS[relation_index + 1],
            relation_type_revision_uid=relation_type.revision_uid,
            predicate=relation_type.predicate,
            core_role=relation_type.core_role,
            source=endpoint(source),
            target=endpoint(target),
            scope="project",
            provenance_kind=provenance,
            formal_trace_categories=relation_type.formal_trace_categories,
            created_at=NOW,
        ),
        relation_type_revision_uid=relation_type.revision_uid,
        lifecycle_state="active",
    )


def snapshot_and_context(
    model: EffectiveModel,
    values: tuple[
        FacetDefinitionRevision,
        FacetDefinitionRevision,
        KindDefinitionRevision,
        KindDefinitionRevision,
        KindDefinitionRevision,
        RelationTypeRevision,
        RelationTypeRevision,
    ],
    *,
    evaluation_provenance: ProvenanceKind = ProvenanceKind.ASSERTED,
) -> tuple[GraphSnapshot, ContextBundle]:
    _, _, goal_kind, component_kind, evidence_kind, decomposition, evaluation = values
    goal = revision(UIDS[20], UIDS[21], "GOAL-001", goal_kind.name, "离线推理", "本地完成推理")
    component = revision(
        UIDS[22], UIDS[23], "COMP-001", component_kind.name, "推理运行器", "执行模型"
    )
    evidence = revision(UIDS[24], UIDS[25], "EVAL-001", evidence_kind.name, "性能评估", "完成基准")
    snapshot = GraphSnapshot(
        snapshot_uid=UIDS[26],
        configuration_uid=UIDS[27],
        canonical_commit="a" * 40,
        effective_model_hash=model.model_hash,
        evaluation_time=NOW,
        nodes=(
            GraphNode(revision=goal, lifecycle_state="approved"),
            GraphNode(revision=component, lifecycle_state="draft", source="candidate"),
            GraphNode(revision=evidence, lifecycle_state="approved"),
        ),
        relations=(
            relation(goal, component, decomposition, 30),
            relation(
                goal,
                evidence,
                evaluation,
                32,
                provenance=evaluation_provenance,
            ),
        ),
        workspace_uid=UIDS[28],
        checkpoint_uid=UIDS[29],
        candidate_overlay_hash="sha256:" + "b" * 64,
    )
    context = ContextBundle(
        bundle_uid=UIDS[34],
        graph_snapshot_hash=snapshot.snapshot_hash,
        stage="manifest",
        mandatory=(goal.object_uid, evidence.object_uid),
        supporting=(component.object_uid,),
        selection_trace=(f"explicit:{goal.object_uid}",),
        omitted_candidates=(UIDS[35],),
        completeness=ContextCompleteness.INCOMPLETE_BUDGET,
    )
    return snapshot, context


def fixture(
    *,
    evaluation_provenance: ProvenanceKind = ProvenanceKind.ASSERTED,
) -> tuple[
    PresentationMappingRevision,
    EffectiveModel,
    tuple[
        FacetDefinitionRevision,
        FacetDefinitionRevision,
        KindDefinitionRevision,
        KindDefinitionRevision,
        KindDefinitionRevision,
        RelationTypeRevision,
        RelationTypeRevision,
    ],
    GraphSnapshot,
    ContextBundle,
]:
    values = definitions()
    profile, model = effective_model(values)
    selected_mapping = mapping(profile, values)
    snapshot, context = snapshot_and_context(
        model,
        values,
        evaluation_provenance=evaluation_provenance,
    )
    return selected_mapping, model, values, snapshot, context


def all_keys(value: Any) -> tuple[str, ...]:
    if isinstance(value, dict):
        return tuple(value) + tuple(key for item in value.values() for key in all_keys(item))
    if isinstance(value, list):
        return tuple(key for item in value for key in all_keys(item))
    return ()


def test_profile_mapping_builds_area_documents_without_technical_identifiers() -> None:
    selected_mapping, model, values, snapshot, context = fixture()
    view = build_engineering_view(
        selected_mapping,
        model,
        snapshot,
        values,
        context_bundle=context,
    )

    assert [area.label for area in view.areas] == ["目标与边界", "评估证据"]
    assert view.areas[0].items[0].human_key == "GOAL-001"
    assert view.areas[0].items[0].title == "离线推理"
    assert view.areas[0].items[0].summary == "本地完成推理"
    payload = view.model_dump(mode="json")
    assert not any(
        marker in key.casefold()
        for key in all_keys(payload)
        for marker in ("uid", "hash", "commit", "delegation")
    )
    serialized = view.model_dump_json()
    assert snapshot.canonical_commit not in serialized
    assert snapshot.snapshot_hash not in serialized
    assert model.model_hash not in serialized


def test_hierarchy_is_profile_driven_and_preserves_candidate_state() -> None:
    selected_mapping, model, values, snapshot, _ = fixture()
    view = build_engineering_view(selected_mapping, model, snapshot, values)

    hierarchy = view.hierarchies[0]
    assert hierarchy.label == "目标分解"
    assert hierarchy.roots[0].item.human_key == "GOAL-001"
    assert hierarchy.roots[0].children[0].item.human_key == "COMP-001"
    assert hierarchy.roots[0].children[0].item.is_candidate is True
    assert hierarchy.unplaced_items == ()


def test_trace_coverage_reuses_formal_trace_evaluation() -> None:
    selected_mapping, model, values, snapshot, context = fixture()
    view = build_engineering_view(
        selected_mapping,
        model,
        snapshot,
        values,
        context_bundle=context,
    )

    coverage = view.trace_coverage[0]
    assert coverage.covered_count == 1
    assert coverage.uncovered_count == 0
    assert coverage.rows[0].state is TraceCoverageState.COVERED
    assert coverage.rows[0].links[0].target.human_key == "EVAL-001"
    assert coverage.rows[0].links[0].formal_credit is True
    assert view.context is not None
    assert [item.human_key for item in view.context.mandatory_items] == [
        "EVAL-001",
        "GOAL-001",
    ]
    assert [item.human_key for item in view.context.supporting_items] == ["COMP-001"]
    assert view.context.omitted_count == 1
    assert view.context.completeness is ContextCompleteness.INCOMPLETE_BUDGET


def test_non_formal_relation_is_visible_as_a_coverage_gap() -> None:
    selected_mapping, model, values, snapshot, _ = fixture(
        evaluation_provenance=ProvenanceKind.PROPOSED
    )
    view = build_engineering_view(selected_mapping, model, snapshot, values)

    row = view.trace_coverage[0].rows[0]
    assert row.state is TraceCoverageState.UNCOVERED
    assert row.links == ()
    assert row.rejected_link_count == 1


def test_template_mapping_uses_the_same_graph_without_profile_specific_names() -> None:
    selected_mapping, model, values, snapshot, _ = fixture()
    _, _, goal_kind, _, _, _, _ = values
    template_mapping = PresentationMappingRevision(
        presentation_mapping_uid=UIDS[40],
        revision_uid=UIDS[41],
        name="通用目标模板",
        source_template_artifact_uids=("arc42-context",),
        engineering_areas=(
            EngineeringArea(
                area_key="goals",
                label="工程目标",
                selector=PresentationSelector(
                    kind_definition_revision_uids=(goal_kind.revision_uid,)
                ),
            ),
        ),
        view_modes=(ViewMode.OVERVIEW,),
        default_view_mode=ViewMode.OVERVIEW,
    )

    view = build_engineering_view(template_mapping, model, snapshot, values)

    assert view.mapping_name == "通用目标模板"
    assert view.areas[0].label == "工程目标"
    assert view.areas[0].items[0].human_key == "GOAL-001"
    assert "SYS" not in view.model_dump_json()
    assert "SWE" not in view.model_dump_json()
    assert selected_mapping.name != view.mapping_name


def test_view_rejects_mismatched_resolved_inputs_without_mutating_them() -> None:
    selected_mapping, model, values, snapshot, context = fixture()
    before_snapshot = snapshot.model_dump(mode="json")
    before_model = model.model_dump(mode="json")

    broken_snapshot = snapshot.model_copy(update={"effective_model_hash": "sha256:other"})
    with pytest.raises(ValueError, match="another Effective Model"):
        build_engineering_view(selected_mapping, model, broken_snapshot, values)

    foreign_context = context.model_copy(update={"graph_snapshot_hash": "sha256:other"})
    with pytest.raises(ValueError, match="another Graph Snapshot"):
        build_engineering_view(
            selected_mapping,
            model,
            snapshot,
            values,
            context_bundle=foreign_context,
        )

    assert snapshot.model_dump(mode="json") == before_snapshot
    assert model.model_dump(mode="json") == before_model
