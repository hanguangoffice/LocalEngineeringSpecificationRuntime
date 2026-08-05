from __future__ import annotations

from datetime import UTC, datetime

import pytest

from lesr.domain.merge import (
    ConflictResolution,
    ConflictType,
    ForeignDiff,
    ResolutionType,
    SemanticMergeEngine,
    SemanticState,
    begin_reconciliation,
)

NOW = datetime(2026, 8, 5, tzinfo=UTC)
UIDS = [f"018f0000-0000-7000-8000-{index:012d}" for index in range(1, 20)]


def state(
    *,
    title: str = "base",
    statement: str = "shall",
    kind: str = "requirement",
    human_key: str = "REQ-1",
) -> SemanticState:
    return SemanticState(
        object_uid=UIDS[0],
        human_key=human_key,
        kind=kind,
        facets=("traceability",),
        fields=(("statement", statement), ("title", title)),
    )


def test_three_way_merge_auto_merges_different_fields() -> None:
    base = state()
    ours = state(title="ours")
    theirs = state(statement="theirs")
    result = SemanticMergeEngine.merge(UIDS[1], base, ours, theirs)
    assert result.conflicts == ()
    assert dict(result.merged.fields) == {"statement": "theirs", "title": "ours"}
    assert result.approvals_invalidated
    assert result.rebuild_required == (
        "graph",
        "rule",
        "validation",
        "context",
        "impact",
        "review_package",
    )


def test_same_field_and_kind_changes_create_structured_conflicts() -> None:
    base = state()
    ours = state(title="ours", kind="software_requirement")
    theirs = state(title="theirs", kind="system_requirement")
    result = SemanticMergeEngine.merge(UIDS[1], base, ours, theirs)
    assert {item.conflict_type for item in result.conflicts} == {
        ConflictType.SAME_FIELD,
        ConflictType.KIND_FACET,
    }
    assert all(item.conflict_hash.startswith("sha256:") for item in result.conflicts)


def test_high_risk_conflict_requires_explicit_human_resolution() -> None:
    result = SemanticMergeEngine.merge(
        UIDS[1], state(), state(kind="software_requirement"), state(kind="system_requirement")
    )
    conflict = result.conflicts[0]
    automated = ConflictResolution(
        conflict_uid=conflict.conflict_uid,
        operation=ResolutionType.TAKE_OURS,
        actor_uid="agent",
        actor_type="ai",
        resolved_at=NOW,
    )
    with pytest.raises(ValueError, match="REQUIRES-HUMAN"):
        SemanticMergeEngine.resolve(result, (automated,))
    human = automated.model_copy(update={"actor_type": "human", "resolution_hash": ""})
    resolved = SemanticMergeEngine.resolve(result, (human,))
    assert resolved.conflicts == ()
    assert resolved.merged.kind == "software_requirement"


def test_foreign_git_change_only_opens_non_authoritative_reconciliation_workspace() -> None:
    diff = ForeignDiff(
        old_commit="a" * 40,
        foreign_commit="b" * 40,
        changed_paths=("canonical/revisions/foreign.json",),
        has_merge_commit=True,
    )
    workspace = begin_reconciliation(diff)
    assert workspace.foreign_diff_hash == diff.diff_hash
    assert workspace.authority_status == "not_authoritative_pending_reconciliation"
