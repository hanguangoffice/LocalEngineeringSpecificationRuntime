from __future__ import annotations

import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest

from lesr.adapters.git import (
    ApprovalAttestation,
    ApprovalError,
    CheckpointStrategy,
    ConcurrencyConflict,
    GitCanonicalRepository,
    IdempotencyConflict,
    InjectedFailure,
    IntegrityError,
    OperationType,
    SemanticOperation,
    SemanticTransaction,
)
from lesr.domain.semantic import semantic_hash


def approval(package_hash: str = "sha256:package") -> ApprovalAttestation:
    return ApprovalAttestation(
        approval_uid="APR-1",
        package_hash=package_hash,
        actor="reviewer",
        actor_type="human",
        approval_type="technical",
    )


def transaction(
    repository: GitCanonicalRepository,
    *,
    key: str = "KEY-1",
    transaction_uid: str = "TX-1",
    path: str = "canonical/revisions/REQ-1-at-1.json",
    payload: dict[str, object] | None = None,
) -> SemanticTransaction:
    value = payload or {
        "revision_uid": "REQ-1-at-1",
        "statement": "The software shall reconnect.",
        "content_hash": "sha256:req1",
    }
    return SemanticTransaction(
        transaction_uid=transaction_uid,
        base_commit=repository.current_commit(),
        expected_revisions=(),
        effective_model_hash="sha256:model",
        review_package_hash="sha256:package",
        operations=(SemanticOperation(OperationType.CREATE_REVISION, path, value),),
        approvals=(approval(),),
        actor="USER-1",
        delegation_uid="DEL-1",
        idempotency_key=key,
    )


def repository(tmp_path: Path) -> GitCanonicalRepository:
    result = GitCanonicalRepository(tmp_path / "repo")
    result.initialize()
    return result


def test_atomic_multi_resource_apply_and_idempotency(tmp_path: Path) -> None:
    repo = repository(tmp_path)
    plan = transaction(repo)
    plan = replace(
        plan,
        operations=plan.operations
        + (
            SemanticOperation(
                OperationType.ASSERT_RELATION,
                "canonical/relations/REL-1-at-1.json",
                {"relation_uid": "REL-1@1", "source": "REQ-1", "target": "DES-1"},
            ),
        ),
    )
    result = repo.apply(plan)
    assert repo.read_json(result.commit, plan.operations[0].relative_path) is not None
    assert repo.read_json(result.commit, plan.operations[1].relative_path) is not None
    assert repo.read_json(result.commit, "canonical/applied_changes/TX-1.json") is not None
    replay = repo.apply(plan)
    assert replay.idempotent_replay
    assert replay.commit == result.commit
    with pytest.raises(IdempotencyConflict):
        repo.apply(replace(plan, effective_model_hash="sha256:different"))


def test_stale_base_and_historical_revision_overwrite_are_rejected(tmp_path: Path) -> None:
    repo = repository(tmp_path)
    stale = transaction(repo, key="STALE", transaction_uid="TX-STALE")
    repo.apply(transaction(repo))
    with pytest.raises(ConcurrencyConflict):
        repo.apply(stale)
    duplicate = transaction(
        repo, key="DUP", transaction_uid="TX-DUP", path="canonical/revisions/REQ-1-at-1.json"
    )
    with pytest.raises(IntegrityError):
        repo.apply(duplicate)


@pytest.mark.parametrize("stage", ["after_stage", "before_commit", "before_ref"])
def test_failures_before_ref_leave_canonical_state_unchanged(
    tmp_path: Path, stage: str
) -> None:
    repo = repository(tmp_path)
    before = repo.current_commit()

    def inject(actual: str) -> None:
        if actual == stage:
            raise InjectedFailure(stage)

    with pytest.raises(InjectedFailure):
        repo.apply(transaction(repo), fault_injector=inject)
    assert repo.current_commit() == before


def test_crash_after_ref_is_recovered_by_idempotent_retry(tmp_path: Path) -> None:
    repo = repository(tmp_path)
    plan = transaction(repo)

    def inject(stage: str) -> None:
        if stage == "after_ref":
            raise InjectedFailure(stage)

    with pytest.raises(InjectedFailure):
        repo.apply(plan, fault_injector=inject)
    replay = repo.apply(plan)
    assert replay.idempotent_replay
    assert repo.current_commit() != plan.base_commit


def test_projection_failure_does_not_rollback_git_and_projection_rebuilds(
    tmp_path: Path,
) -> None:
    repo = repository(tmp_path)

    def projection_failure(commit: str) -> None:
        raise OSError(commit)

    result = repo.apply(transaction(repo), projection_updater=projection_failure)
    assert result.projection_stale
    database = tmp_path / "projection.db"
    assert repo.rebuild_projection(database) == result.commit
    with sqlite3.connect(database) as connection:
        paths = {row[0] for row in connection.execute("SELECT path FROM documents")}
    assert "canonical/revisions/REQ-1-at-1.json" in paths


def test_both_checkpoint_strategies_are_git_recoverable(tmp_path: Path) -> None:
    repo = repository(tmp_path)
    isolated = repo.create_checkpoint(
        "WS-1", {"draft": "one"}, CheckpointStrategy.COMMIT_PER_CHECKPOINT
    )
    workspace = repo.create_checkpoint(
        "WS-2", {"draft": "two"}, CheckpointStrategy.WORKSPACE_REF
    )
    assert repo.checkpoint_payload(isolated)["working_state"] == {"draft": "one"}
    assert repo.checkpoint_payload(workspace)["working_state"] == {"draft": "two"}
    assert isolated.git_reference != workspace.git_reference


def test_unicode_long_paths_and_foreign_diff_reconciliation(tmp_path: Path) -> None:
    repo = repository(tmp_path)
    long_name = "模块-" + "x" * 120
    plan = transaction(
        repo,
        path=f"canonical/revisions/{long_name}.json",
        payload={"title": "CAN 信号 λ", "content_hash": semantic_hash({"title": "CAN 信号 λ"})},
    )
    result = repo.apply(plan)
    assert repo.read_json(result.commit, plan.operations[0].relative_path) is not None
    assert repo.requires_reconciliation(("canonical/revisions/external.json",))
    assert not repo.requires_reconciliation(("README.md",))


def test_path_escape_and_ai_formal_approval_are_rejected(tmp_path: Path) -> None:
    repo = repository(tmp_path)
    escaped = transaction(
        repo,
        key="PATH-ESCAPE",
        transaction_uid="TX-PATH",
        path="canonical/../outside.json",
    )
    with pytest.raises(IntegrityError, match="unsafe canonical path"):
        repo.apply(escaped)
    ai_attestation = replace(approval(), actor_type="ai")
    with pytest.raises(ApprovalError, match="AI cannot"):
        repo.apply(
            replace(
                transaction(repo, key="AI-APPROVAL", transaction_uid="TX-AI"),
                approvals=(ai_attestation,),
            )
        )
