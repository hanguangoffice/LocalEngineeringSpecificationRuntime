from __future__ import annotations

import random
from datetime import UTC, datetime

from lesr.domain.model import (
    CompositionMode,
    EffectiveModelCompiler,
    FacetDefinitionRevision,
    FieldDefinition,
    KindDefinitionRevision,
    NormativeProfileRevision,
    ProfileContribution,
    ProfileLayer,
    RelationTypeRevision,
    WorkflowProjector,
    WorkflowRevision,
    WorkflowTransition,
)
from lesr.domain.semantic import (
    BindingMode,
    CoreRelationRole,
    CoreResourceClass,
    ImmutableRecord,
    SemanticField,
)

UIDS = [f"018f0000-0000-7000-8000-{index:012d}" for index in range(1, 40)]


def kernel() -> tuple[
    tuple[NormativeProfileRevision, ...],
    tuple[
        FacetDefinitionRevision | KindDefinitionRevision | WorkflowRevision | RelationTypeRevision,
        ...,
    ],
]:
    facet = FacetDefinitionRevision(facet_uid=UIDS[0], revision_uid=UIDS[1], name="traceability")
    workflow = WorkflowRevision(
        workflow_uid=UIDS[2],
        revision_uid=UIDS[3],
        states=("draft", "approved", "retired"),
        initial_state="draft",
        transitions=(
            WorkflowTransition(from_state="draft", to_state="approved", roles=("technical",)),
            WorkflowTransition(from_state="approved", to_state="retired", roles=("owner",)),
        ),
    )
    kind = KindDefinitionRevision(
        kind_uid=UIDS[4],
        revision_uid=UIDS[5],
        name="software_requirement",
        core_class=CoreResourceClass.GOVERNED_OBJECT,
        required_facet_revision_uids=(facet.revision_uid,),
    )
    relation = RelationTypeRevision(
        relation_type_uid=UIDS[6],
        revision_uid=UIDS[7],
        predicate="verified_by",
        core_role=CoreRelationRole.VERIFIES,
        source_kind_or_facet=("software_requirement",),
        target_kind_or_facet=("test_case",),
        allowed_bindings=(BindingMode.LOGICAL, BindingMode.PINNED),
        default_binding=BindingMode.PINNED,
        workflow_revision_uid=workflow.revision_uid,
        formal_trace_categories=("verification",),
    )
    definitions = (facet, workflow, kind, relation)
    foundation = NormativeProfileRevision(
        profile_uid=UIDS[8],
        profile_revision_uid=UIDS[9],
        layer=ProfileLayer.FOUNDATION,
        authority=100,
        contributions=tuple(
            ProfileContribution(
                mode=CompositionMode.EXTEND,
                definition_revision_uid=item.revision_uid,
            )
            for item in definitions
        ),
    )
    project = NormativeProfileRevision(
        profile_uid=UIDS[10],
        profile_revision_uid=UIDS[11],
        layer=ProfileLayer.PROJECT,
        authority=200,
    )
    return (foundation, project), definitions


def test_effective_model_is_independent_of_load_order() -> None:
    profiles, definitions = kernel()
    expected = EffectiveModelCompiler().compile(profiles, definitions)
    for seed in range(20):
        shuffled_profiles = list(profiles)
        shuffled_definitions = list(definitions)
        random.Random(seed).shuffle(shuffled_profiles)
        random.Random(seed + 100).shuffle(shuffled_definitions)
        actual = EffectiveModelCompiler().compile(
            tuple(shuffled_profiles), tuple(shuffled_definitions)
        )
        assert actual.model_hash == expected.model_hash
        assert actual.conflicts == expected.conflicts
        assert actual.composition_sources == expected.composition_sources


def test_replace_is_forbidden_without_all_three_authorizations() -> None:
    profiles, definitions = kernel()
    replacement = definitions[0].model_copy(
        update={"revision_uid": UIDS[12], "name": "replacement", "content_hash": ""}
    )
    replace = NormativeProfileRevision(
        profile_uid=UIDS[13],
        profile_revision_uid=UIDS[14],
        layer=ProfileLayer.PROJECT,
        authority=999,
        contributions=(
            ProfileContribution(
                mode=CompositionMode.REPLACE,
                definition_revision_uid=replacement.revision_uid,
                target_revision_uid=definitions[0].revision_uid,
            ),
        ),
    )
    model = EffectiveModelCompiler().compile(profiles + (replace,), definitions + (replacement,))
    assert [item.code for item in model.conflicts] == ["LESR-REPLACE-FORBIDDEN"]


def test_relation_type_contains_intrinsic_semantics_not_cardinality() -> None:
    _, definitions = kernel()
    relation = definitions[-1]
    assert isinstance(relation, RelationTypeRevision)
    assert "minimum" not in RelationTypeRevision.model_fields
    assert "maximum" not in RelationTypeRevision.model_fields
    assert relation.default_binding in relation.allowed_bindings


def test_lifecycle_projection_uses_exact_workflow_revision() -> None:
    _, definitions = kernel()
    workflow = definitions[1]
    assert isinstance(workflow, WorkflowRevision)
    record = ImmutableRecord(
        record_uid=UIDS[15],
        record_type="lifecycle",
        subject_uid=UIDS[5],
        actor_uid="reviewer",
        actor_type="human",
        occurred_at=datetime(2026, 8, 5, tzinfo=UTC),
        fields=(
            SemanticField(path="/from_state", value="draft"),
            SemanticField(path="/to_state", value="approved"),
            SemanticField(path="/workflow_revision_uid", value=workflow.revision_uid),
        ),
    )
    result = WorkflowProjector.project(workflow, (record,))
    assert result.state == "approved"
    assert result.conflicts == ()


def test_refine_cannot_relax_profile_owned_field_contract() -> None:
    base = FacetDefinitionRevision(
        revision_uid=UIDS[20],
        name="timing",
        authority=100,
        fields=(
            FieldDefinition(
                path="/deadline_ms",
                value_type="integer",
                required=True,
                maximum="100",
            ),
        ),
    )
    relaxed = base.model_copy(
        update={
            "revision_uid": UIDS[21],
            "fields": (
                FieldDefinition(
                    path="/deadline_ms",
                    value_type="integer",
                    required=False,
                    maximum="200",
                ),
            ),
            "content_hash": "",
        }
    )
    foundation = NormativeProfileRevision(
        profile_revision_uid=UIDS[22],
        layer=ProfileLayer.FOUNDATION,
        authority=100,
        contributions=(
            ProfileContribution(
                mode=CompositionMode.EXTEND,
                definition_revision_uid=base.revision_uid,
            ),
        ),
    )
    project = NormativeProfileRevision(
        profile_revision_uid=UIDS[23],
        layer=ProfileLayer.PROJECT,
        authority=200,
        contributions=(
            ProfileContribution(
                mode=CompositionMode.REFINE,
                definition_revision_uid=relaxed.revision_uid,
                target_revision_uid=base.revision_uid,
            ),
        ),
    )
    model = EffectiveModelCompiler().compile(
        (foundation, project), (base, relaxed)
    )
    assert [item.code for item in model.conflicts] == ["LESR-REFINE-NOT-NARROWER"]
