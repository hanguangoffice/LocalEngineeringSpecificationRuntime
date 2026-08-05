from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest
from pydantic import ValidationError

from lesr.domain.semantic import (
    Alias,
    BindingMode,
    CoreRelationRole,
    FragmentAddress,
    LifecycleEventType,
    LifecycleProjector,
    LifecycleRecord,
    LogicalObject,
    ProjectionStatus,
    ProvenanceKind,
    RelationAssertion,
    RelationEndpoint,
    Revision,
    SemanticField,
    canonical_json,
    semantic_hash,
    ulid_candidate,
    uuid7_candidate,
)
from tests.support.semantic_dataset import build_semantic_gate_dataset


def test_uid_candidates_are_valid_time_ordered_formats() -> None:
    early_uuid = uuid7_candidate(1_000)
    late_uuid = uuid7_candidate(2_000)
    assert UUID(early_uuid).version == 7
    assert early_uuid < late_uuid
    early_ulid = ulid_candidate(1_000)
    late_ulid = ulid_candidate(2_000)
    assert len(early_ulid) == 26
    assert early_ulid < late_ulid


def test_revision_is_deeply_immutable_and_hash_is_deterministic() -> None:
    logical = LogicalObject(namespace="demo", human_key="REQ-1", kind="requirement")
    revision = Revision(
        object_uid=logical.entity_uid,
        revision_number=1,
        human_key=logical.human_key,
        kind=logical.kind,
        fields=(SemanticField.from_value("statement", {"shall": True}),),
        provenance_origin=ProvenanceKind.AUTHORED,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    assert revision.content_hash == semantic_hash(
        revision.model_dump(mode="json", exclude={"content_hash"})
    )
    assert canonical_json(revision) == canonical_json(revision)
    with pytest.raises(ValidationError):
        revision.revision_number = 2


def test_alias_and_fragment_are_revision_scoped() -> None:
    alias = Alias(
        value="REQ-OLD-1",
        alias_type="former_human_key",
        valid_from=datetime(2026, 1, 1, tzinfo=UTC),
        introduced_by="CHG-1",
    )
    logical = LogicalObject(
        namespace="demo", human_key="REQ-NEW-1", kind="requirement", aliases=(alias,)
    )
    address = FragmentAddress(
        object_uid=logical.entity_uid,
        revision_uid=uuid7_candidate(),
        fragment_path="acceptance/max_interval",
    )
    assert "@" in address.as_uri("demo")
    assert "#acceptance/max_interval" in address.as_uri("demo")


def test_relation_bindings_and_formal_trace_are_explicit() -> None:
    source = LogicalObject(namespace="demo", human_key="TEST-1", kind="test_case")
    target = LogicalObject(namespace="demo", human_key="REQ-1", kind="requirement")
    relation = RelationAssertion(
        predicate="test_verifies_requirement",
        core_role=CoreRelationRole.VERIFIES,
        source=RelationEndpoint(binding=BindingMode.LOGICAL, object_uid=source.entity_uid),
        target=RelationEndpoint(binding=BindingMode.LOGICAL, object_uid=target.entity_uid),
        scope="demo",
        provenance_kind=ProvenanceKind.ASSERTED,
        formal_trace_categories=("verification",),
    )
    assert relation.grants_formal_trace()
    proposed = relation.model_copy(update={"provenance_kind": ProvenanceKind.PROPOSED})
    assert not proposed.grants_formal_trace()
    with pytest.raises(ValidationError):
        RelationEndpoint(binding=BindingMode.PINNED, object_uid=source.entity_uid)


def test_lifecycle_is_projected_from_immutable_records() -> None:
    revision_uid = uuid7_candidate()
    submitted = LifecycleRecord(
        subject_uid=revision_uid,
        actor="author",
        event_type=LifecycleEventType.REVISION_SUBMITTED,
        from_state="draft",
        to_state="in_review",
        workflow_revision_uid="WF-1",
        occurred_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    approved = LifecycleRecord(
        subject_uid=revision_uid,
        actor="reviewer",
        event_type=LifecycleEventType.REVISION_APPROVED,
        from_state="in_review",
        to_state="approved",
        workflow_revision_uid="WF-1",
        review_package_uid="RP-1",
        occurred_at=datetime(2026, 1, 2, tzinfo=UTC),
    )
    result = LifecycleProjector.project("draft", (submitted, approved))
    assert result.status is ProjectionStatus.APPROVED
    conflict = approved.model_copy(update={"from_state": "draft"})
    assert LifecycleProjector.project("draft", (submitted, conflict)).status is ProjectionStatus.INDETERMINATE


def test_gate_dataset_meets_the_baseline_shape() -> None:
    dataset = build_semantic_gate_dataset()
    counts: dict[str, int] = {}
    for item in dataset.logical_objects:
        counts[item.kind] = counts.get(item.kind, 0) + 1
    assert sum(counts[kind] for kind in ("software_requirement", "software_design", "test_case")) == 30
    assert counts["coding_rule"] == 20
    assert counts["can_signal"] == 20
    assert sum(counts[kind] for kind in ("change", "deviation", "evidence")) == 10
    assert all(relation.grants_formal_trace() for relation in dataset.relations)
