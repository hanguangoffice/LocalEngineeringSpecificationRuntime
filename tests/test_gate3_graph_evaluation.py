from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from lesr.domain.evaluation import (
    ConstraintEnvironment,
    ConstraintExpression,
    ContextCompleteness,
    CyclePolicy,
    Direction,
    GraphNode,
    GraphRelation,
    GraphSnapshot,
    ImpactCompleteness,
    RelationPath,
    RelationPathStep,
    RuleOperator,
    SemanticEvaluator,
    analyze_impact,
    evaluate_aggregate,
    evaluate_constraint,
    evaluate_path,
    plan_context,
)
from lesr.domain.model import RelationTypeRevision
from lesr.domain.semantic import (
    BindingMode,
    CoreRelationRole,
    ProvenanceKind,
    RelationAssertion,
    RelationEndpoint,
    Revision,
    semantic_hash,
)

NOW = datetime(2026, 8, 5, tzinfo=UTC)
UIDS = [f"018f0000-0000-7000-8000-{index:012d}" for index in range(1, 40)]
MODEL_HASH = semantic_hash({"model": "gate-3"})


def revision(object_index: int, revision_index: int, kind: str) -> Revision:
    return Revision(
        revision_uid=UIDS[revision_index],
        object_uid=UIDS[object_index],
        revision_number=1,
        human_key=f"{kind}-{object_index}",
        kind=kind,
        provenance_origin=ProvenanceKind.AUTHORED,
        created_at=NOW,
    )


REQ = revision(0, 1, "software_requirement")
TEST = revision(2, 3, "test_case")
DESIGN = revision(4, 5, "software_design")


def relation_type() -> RelationTypeRevision:
    return RelationTypeRevision(
        relation_type_uid=UIDS[6],
        revision_uid=UIDS[7],
        predicate="verified_by",
        core_role=CoreRelationRole.VERIFIES,
        source_kind_or_facet=("software_requirement",),
        target_kind_or_facet=("test_case",),
        allowed_bindings=(BindingMode.LOGICAL, BindingMode.PINNED),
        default_binding=BindingMode.PINNED,
        workflow_revision_uid=UIDS[8],
        formal_trace_categories=("verification",),
    )


def endpoint(value: Revision, binding: BindingMode = BindingMode.PINNED) -> RelationEndpoint:
    if binding is BindingMode.LOGICAL:
        return RelationEndpoint(binding=binding, object_uid=value.object_uid)
    if binding is BindingMode.FRAGMENT:
        return RelationEndpoint(
            binding=binding,
            object_uid=value.object_uid,
            revision_uid=value.revision_uid,
            fragment_path="/acceptance/1",
        )
    return RelationEndpoint(
        binding=binding,
        object_uid=value.object_uid,
        revision_uid=value.revision_uid,
    )


def assertion(
    *,
    source: Revision = REQ,
    target: Revision = TEST,
    provenance: ProvenanceKind = ProvenanceKind.ASSERTED,
    binding: BindingMode = BindingMode.PINNED,
    category: str = "verification",
    index: int = 9,
) -> RelationAssertion:
    return RelationAssertion(
        assertion_uid=UIDS[index],
        relation_revision_uid=UIDS[index + 1],
        predicate="verified_by",
        core_role=CoreRelationRole.VERIFIES,
        source=endpoint(source, binding),
        target=endpoint(target, binding),
        scope="project",
        provenance_kind=provenance,
        formal_trace_categories=(category,),
        created_at=NOW,
    )


def graph(
    relation: RelationAssertion | None = None,
    *,
    relation_state: str = "active",
    target_state: str = "approved",
    unresolved: tuple[str, ...] = (),
) -> tuple[GraphSnapshot, SemanticEvaluator]:
    relation = relation or assertion()
    snapshot = GraphSnapshot(
        snapshot_uid=UIDS[20],
        configuration_uid=UIDS[21],
        canonical_commit="a" * 40,
        effective_model_hash=MODEL_HASH,
        evaluation_time=NOW,
        nodes=(
            GraphNode(revision=REQ, lifecycle_state="approved"),
            GraphNode(revision=TEST, lifecycle_state=target_state),
            GraphNode(revision=DESIGN, lifecycle_state="approved"),
        ),
        relations=(
            GraphRelation(
                assertion=relation,
                relation_type_revision_uid=UIDS[7],
                lifecycle_state=relation_state,
            ),
        ),
        unresolved_external_endpoints=unresolved,
    )
    return snapshot, SemanticEvaluator(snapshot, (relation_type(),))


@pytest.mark.parametrize(
    ("relation", "relation_state", "target_state", "expected_reason"),
    [
        (
            assertion(provenance=ProvenanceKind.PROPOSED),
            "active",
            "approved",
            "PROVENANCE_NOT_FORMAL",
        ),
        (
            assertion(provenance=ProvenanceKind.INFERRED),
            "active",
            "approved",
            "PROVENANCE_NOT_FORMAL",
        ),
        (assertion(binding=BindingMode.FRAGMENT), "active", "approved", "FRAGMENT_BINDING"),
        (assertion(), "retired", "approved", "RELATION_RETIRED"),
        (assertion(source=TEST, target=REQ), "active", "approved", "SOURCE_KIND_OR_FACET_MISMATCH"),
        (
            assertion(source=REQ, target=DESIGN),
            "active",
            "approved",
            "TARGET_KIND_OR_FACET_MISMATCH",
        ),
        (assertion(category="safety"), "active", "approved", "CATEGORY_NOT_ASSERTED"),
        (assertion(), "active", "retired", "TARGET_RETIRED"),
    ],
)
def test_formal_trace_attack_matrix(
    relation: RelationAssertion,
    relation_state: str,
    target_state: str,
    expected_reason: str,
) -> None:
    _, evaluator = graph(relation, relation_state=relation_state, target_state=target_state)
    decision = evaluator.formal_trace_credit(evaluator.snapshot.relations[0], "verification")
    assert not decision.granted
    assert expected_reason in decision.reasons


def test_only_correctly_directed_formal_relation_receives_credit() -> None:
    _, evaluator = graph()
    assert evaluator.formal_trace_credit(evaluator.snapshot.relations[0], "verification").granted
    assert (
        evaluator.relation_count(
            REQ.object_uid,
            predicate="verified_by",
            direction=Direction.OUTGOING,
            formal_trace_category="verification",
        )
        == 1
    )
    assert (
        evaluator.relation_count(
            REQ.object_uid,
            predicate="verified_by",
            direction=Direction.INCOMING,
            formal_trace_category="verification",
        )
        == 0
    )


def test_bounded_path_honors_direction_alternative_binding_and_depth() -> None:
    _, evaluator = graph()
    path = RelationPath(
        steps=(
            RelationPathStep(
                predicates=("verified_by", "tested_by"),
                direction=Direction.OUTGOING,
                endpoint_kind_or_facet=("test_case",),
                bindings=(BindingMode.PINNED,),
                formal_trace_category="verification",
            ),
        ),
        maximum_depth=1,
        cycle_policy=CyclePolicy.SIMPLE_PATH,
    )
    result = evaluate_path(evaluator, REQ.object_uid, path)
    assert result.matches[0].object_uids == (REQ.object_uid, TEST.object_uid)
    assert not result.truncated


def test_real_aggregate_uses_values_and_preserves_unknown() -> None:
    total = evaluate_aggregate(RuleOperator.AGGREGATE_SUM, (Decimal("1.25"), Decimal("2.75")))
    assert total.observed == "4.00"
    unknown = evaluate_aggregate(RuleOperator.AGGREGATE_RATIO, (True, None, False))
    assert unknown.truth.value == "INDETERMINATE"


def test_rule_vocabulary_executes_field_relation_and_advisory_observation() -> None:
    _, evaluator = graph()
    environment = ConstraintEnvironment(
        target_uid=REQ.object_uid,
        fields=(("/priority", "high"),),
    )
    field = evaluate_constraint(
        evaluator,
        ConstraintExpression(
            operator=RuleOperator.FIELD_ENUM,
            field_path="/priority",
            expected=["high", "critical"],
        ),
        environment,
    )
    relation = evaluate_constraint(
        evaluator,
        ConstraintExpression(
            operator=RuleOperator.FORMAL_TRACE,
            predicate="verified_by",
            formal_trace_category="verification",
            minimum="1",
        ),
        environment,
    )
    advisory = evaluate_constraint(
        evaluator,
        ConstraintExpression(
            operator=RuleOperator.ADVISORY_AI_OBSERVATION,
            observation_key="ai-risk",
        ),
        environment,
    )
    assert field.truth.value == "TRUE"
    assert relation.truth.value == "TRUE"
    assert advisory.truth.value == "INDETERMINATE"


def test_context_missing_mandatory_relation_is_explicitly_incomplete() -> None:
    snapshot, _ = graph()
    empty_snapshot = snapshot.model_copy(update={"relations": (), "snapshot_hash": ""})
    evaluator = SemanticEvaluator(empty_snapshot, (relation_type(),))
    context = plan_context(
        evaluator,
        (REQ.object_uid,),
        ("verified_by",),
        token_limit=10,
        supporting_from_fts=(DESIGN.object_uid,),
    )
    assert context.completeness is ContextCompleteness.INCOMPLETE_MISSING_RELATION
    assert DESIGN.object_uid in context.supporting
    assert DESIGN.object_uid not in context.mandatory


def test_impact_never_claims_complete_when_external_or_depth_is_unknown() -> None:
    _, evaluator = graph(unresolved=("vendor:can:Signal@unknown",))
    external = analyze_impact(evaluator, (REQ.object_uid,), maximum_depth=4)
    assert external.completeness is ImpactCompleteness.INCOMPLETE_UNKNOWN_EXTERNAL

    _, complete_evaluator = graph()
    depth = analyze_impact(complete_evaluator, (REQ.object_uid,), maximum_depth=0)
    assert depth.completeness is ImpactCompleteness.INCOMPLETE_MAX_DEPTH


def test_candidate_overlay_requires_checkpoint_identity_and_hash() -> None:
    with pytest.raises(ValueError, match="candidate overlay"):
        GraphSnapshot(
            snapshot_uid=UIDS[20],
            configuration_uid=UIDS[21],
            canonical_commit="a" * 40,
            effective_model_hash=MODEL_HASH,
            evaluation_time=NOW,
            nodes=(GraphNode(revision=REQ, lifecycle_state="draft", source="candidate"),),
            relations=(),
        )
