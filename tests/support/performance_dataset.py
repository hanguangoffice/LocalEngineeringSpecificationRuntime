from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from lesr.domain.evaluation import (
    GraphNode,
    GraphRelation,
    GraphSnapshot,
    SemanticEvaluator,
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


def uid(index: int) -> str:
    return f"018f0000-0000-7000-8000-{index:012d}"


@dataclass(frozen=True, slots=True)
class PerformanceDataset:
    object_count: int
    revisions: tuple[Revision, ...]
    snapshot: GraphSnapshot
    relation_type: RelationTypeRevision

    def evaluator(self) -> SemanticEvaluator:
        return SemanticEvaluator(self.snapshot, (self.relation_type,))


def build_dataset(
    object_count: int = 1_000,
    revision_count: int = 5_000,
    relation_count: int = 10_000,
) -> PerformanceDataset:
    if object_count % 2:
        raise ValueError("object_count must be even")
    revisions_per_object = revision_count // object_count
    if revisions_per_object < 1 or revisions_per_object * object_count != revision_count:
        raise ValueError("revision_count must be an object_count multiple")
    revisions: list[Revision] = []
    selected: list[Revision] = []
    for object_index in range(object_count):
        object_uid = uid(1 + object_index)
        kind = "software_requirement" if object_index < object_count // 2 else "test_case"
        parent: str | None = None
        for revision_number in range(1, revisions_per_object + 1):
            revision_uid = uid(100_001 + object_index * revisions_per_object + revision_number)
            revision = Revision(
                revision_uid=revision_uid,
                object_uid=object_uid,
                revision_number=revision_number,
                parent_revision_uid=parent,
                human_key=f"{'REQ' if kind == 'software_requirement' else 'TEST'}-{object_index:06d}",
                kind=kind,
                provenance_origin=ProvenanceKind.AUTHORED,
                created_at=NOW,
            )
            revisions.append(revision)
            parent = revision_uid
        selected.append(revisions[-1])
    relation_type = RelationTypeRevision(
        relation_type_uid=uid(200_001),
        revision_uid=uid(200_002),
        predicate="verified_by",
        core_role=CoreRelationRole.VERIFIES,
        source_kind_or_facet=("software_requirement",),
        target_kind_or_facet=("test_case",),
        allowed_bindings=(BindingMode.PINNED,),
        default_binding=BindingMode.PINNED,
        workflow_revision_uid=uid(200_003),
        formal_trace_categories=("verification",),
    )
    half = object_count // 2
    relations: list[GraphRelation] = []
    for index in range(relation_count):
        source = selected[index % half]
        target = selected[half + ((index * 17 + index // half) % half)]
        assertion = RelationAssertion(
            assertion_uid=uid(300_001 + index * 2),
            relation_revision_uid=uid(300_002 + index * 2),
            relation_type_revision_uid=relation_type.revision_uid,
            predicate=relation_type.predicate,
            core_role=relation_type.core_role,
            source=RelationEndpoint(
                binding=BindingMode.PINNED,
                object_uid=source.object_uid,
                revision_uid=source.revision_uid,
            ),
            target=RelationEndpoint(
                binding=BindingMode.PINNED,
                object_uid=target.object_uid,
                revision_uid=target.revision_uid,
            ),
            scope="performance-fixture",
            provenance_kind=ProvenanceKind.ASSERTED,
            formal_trace_categories=("verification",),
            created_at=NOW,
        )
        relations.append(
            GraphRelation(
                assertion=assertion,
                relation_type_revision_uid=relation_type.revision_uid,
                lifecycle_state="approved",
            )
        )
    snapshot = GraphSnapshot(
        snapshot_uid=uid(900_001),
        configuration_uid=uid(900_002),
        canonical_commit="a" * 40,
        effective_model_hash=semantic_hash({"performance_model": "complete"}),
        evaluation_time=NOW,
        nodes=tuple(
            GraphNode(revision=item, lifecycle_state="approved") for item in selected
        ),
        relations=tuple(relations),
    )
    return PerformanceDataset(object_count, tuple(revisions), snapshot, relation_type)
