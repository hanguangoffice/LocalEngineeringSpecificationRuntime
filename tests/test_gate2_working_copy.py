from __future__ import annotations

from datetime import UTC, datetime

import pytest

from lesr.domain.semantic import SemanticField, semantic_hash
from lesr.domain.workspace import (
    EditOperation,
    EditOperationType,
    WorkingCopy,
    WorkingCopyState,
    Workspace,
    WorkspaceCheckpoint,
    WorkspaceEngine,
)

NOW = datetime(2026, 8, 5, tzinfo=UTC)
UIDS = [f"018f0000-0000-7000-8000-{index:012d}" for index in range(1, 20)]
MODEL_HASH = semantic_hash({"model": "1.0"})


def workspace() -> Workspace:
    value = Workspace(
        workspace_uid=UIDS[0],
        base_commit="a" * 40,
        configuration_uid=UIDS[1],
        effective_model_hash=MODEL_HASH,
        delegation_uid=UIDS[2],
        actor_uid="author",
        created_at=NOW,
    )
    copy = WorkingCopy(
        workspace_uid=value.workspace_uid,
        object_uid=UIDS[3],
        base_revision_uid=UIDS[4],
        base_revision_number=3,
        human_key="REQ-001",
        kind="software_requirement",
        effective_model_hash=MODEL_HASH,
        delegation_uid=UIDS[2],
        draft_fields=(SemanticField(path="/title", value="Original"),),
    )
    return WorkspaceEngine.add_working_copy(value, copy)


def operation(path: str, value: str, index: int) -> EditOperation:
    return EditOperation(
        operation_uid=UIDS[index],
        operation_type=EditOperationType.SET_FIELD,
        object_uid=UIDS[3],
        actor_uid="author",
        occurred_at=NOW,
        path=path,
        value=value,
    )


def test_working_copy_supports_continuous_editing_and_stable_hash() -> None:
    first = WorkspaceEngine.edit(workspace(), operation("/title", "Edited", 5))
    second = WorkspaceEngine.edit(first, operation("/statement", "Shall reconnect", 6))
    copy = second.working_copies[0]
    assert {item.path: item.value for item in copy.draft_fields} == {
        "/statement": "Shall reconnect",
        "/title": "Edited",
    }
    assert len(copy.edit_log) == 2
    assert copy.working_state_hash.startswith("sha256:")


def test_workspace_rejects_a_second_active_copy_for_same_object() -> None:
    existing = workspace()
    with pytest.raises(ValueError, match="ALREADY-ACTIVE"):
        WorkspaceEngine.add_working_copy(existing, existing.working_copies[0])


def test_checkpoint_round_trip_restores_exact_state() -> None:
    edited = WorkspaceEngine.edit(workspace(), operation("/title", "Edited", 5))
    updated, checkpoint = WorkspaceEngine.checkpoint(
        edited, checkpoint_uid=UIDS[6], actor_uid="author", created_at=NOW
    )
    serialized = checkpoint.model_dump_json()
    restored_checkpoint = WorkspaceCheckpoint.model_validate_json(serialized)
    restored = WorkspaceEngine.restore(restored_checkpoint)
    assert restored == edited
    assert updated.checkpoint_uids == (UIDS[6],)
    assert checkpoint.git_ref == f"refs/lesr/workspaces/{edited.workspace_uid}"


def test_submit_freezes_candidate_without_promoting_it_to_canonical_state() -> None:
    edited = WorkspaceEngine.edit(workspace(), operation("/title", "Edited", 5))
    submission = WorkspaceEngine.submit(
        edited,
        checkpoint_uid=UIDS[6],
        actor_uid="author",
        submitted_at=NOW,
    )
    revision = submission.candidate.revisions[0]
    assert revision.parent_revision_uid == UIDS[4]
    assert revision.revision_number == 4
    assert submission.workspace.state is WorkingCopyState.SUBMITTED
    assert submission.workspace.working_copies[0].state is WorkingCopyState.SUBMITTED
    assert submission.candidate.workspace_uid == edited.workspace_uid
    assert submission.semantic_diff.scope == (UIDS[3],)
    with pytest.raises(ValueError, match="READ-ONLY"):
        WorkspaceEngine.edit(submission.workspace, operation("/title", "Late", 7))


def test_candidate_hash_fixes_checkpoint_and_effective_model() -> None:
    submission = WorkspaceEngine.submit(
        workspace(), checkpoint_uid=UIDS[6], actor_uid="author", submitted_at=NOW
    )
    assert submission.candidate.checkpoint_uid == UIDS[6]
    assert submission.candidate.effective_model_hash == MODEL_HASH
    assert submission.candidate.candidate_hash.startswith("sha256:")
