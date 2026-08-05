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

OBJECT_UID = "018f0000-0000-7000-8000-000000000101"
REVISION_UID = "018f0000-0000-7000-8000-000000000102"
ACTOR_UID = "018f0000-0000-7000-8000-000000000103"
DELEGATION_UID = "018f0000-0000-7000-8000-000000000104"
APPROVAL_UID = "018f0000-0000-7000-8000-000000000105"
TRANSACTION_UID = "018f0000-0000-7000-8000-000000000106"
STALE_TRANSACTION_UID = "018f0000-0000-7000-8000-000000000107"
DUPLICATE_TRANSACTION_UID = "018f0000-0000-7000-8000-000000000108"
PACKAGE_HASH = semantic_hash({"package": "reviewed"})
MODEL_HASH = semantic_hash({"model": "effective"})


def approval(package_hash: str = PACKAGE_HASH) -> ApprovalAttestation:
    return ApprovalAttestation(
        APPROVAL_UID, package_hash, ACTOR_UID, "human", "technical"
    )


def canonical_operations() -> tuple[SemanticOperation, ...]:
    logical: dict[str, object] = {
        "schema_version": "1.0",
        "resource_type": "logical_object",
        "entity_uid": OBJECT_UID,
        "namespace": "git-test",
        "human_key": "REQ-GIT-1",
        "kind": "software_requirement",
        "core_class": "governed_object",
        "facets": ["authored"],
        "aliases": [],
        "external_identities": [],
        "created_at": "2026-08-05T00:00:00Z",
    }
    raw_revision: dict[str, object] = {
        "schema_version": "1.0",
        "resource_type": "revision",
        "revision_uid": REVISION_UID,
        "object_uid": OBJECT_UID,
        "revision_number": 1,
        "parent_revision_uid": None,
        "human_key": "REQ-GIT-1",
        "kind": "software_requirement",
        "facets": ["authored"],
        "fields": [{"path": "/statement", "value": "The software shall reconnect."}],
        "fragments": [],
        "provenance_origin": "authored",
        "created_at": "2026-08-05T00:00:00Z",
    }
    revision = raw_revision | {"content_hash": semantic_hash(raw_revision)}
    return (
        SemanticOperation(
            OperationType.CREATE_LOGICAL_OBJECT,
            f"canonical/objects/{OBJECT_UID}.json",
            logical,
        ),
        SemanticOperation(
            OperationType.CREATE_REVISION,
            f"canonical/revisions/{REVISION_UID}.json",
            revision,
        ),
    )


def transaction(
    repository: GitCanonicalRepository,
    *,
    key: str = "KEY-1",
    transaction_uid: str = TRANSACTION_UID,
    operations: tuple[SemanticOperation, ...] | None = None,
) -> SemanticTransaction:
    return SemanticTransaction(
        transaction_uid,
        repository.current_commit(),
        (),
        MODEL_HASH,
        PACKAGE_HASH,
        operations or canonical_operations(),
        (approval(),),
        ACTOR_UID,
        DELEGATION_UID,
        key,
    )


def repository(tmp_path: Path) -> GitCanonicalRepository:
    result = GitCanonicalRepository(tmp_path / "repo")
    result.initialize()
    return result


def test_atomic_multi_resource_apply_and_idempotency(tmp_path: Path) -> None:
    repo = repository(tmp_path)
    plan = transaction(repo)
    result = repo.apply(plan)
    assert repo.verify_audit_chain(result.commit)
    assert all(
        repo.read_json(result.commit, operation.relative_path) is not None
        for operation in plan.operations
    )
    assert repo.read_json(
        result.commit, f"canonical/applied_changes/{TRANSACTION_UID}.json"
    ) is not None
    replay = repo.apply(plan)
    assert replay.idempotent_replay and replay.commit == result.commit
    with pytest.raises(IdempotencyConflict):
        repo.apply(replace(plan, effective_model_hash=semantic_hash({"model": "different"})))


def test_stale_base_and_immutable_overwrite_are_rejected(tmp_path: Path) -> None:
    repo = repository(tmp_path)
    stale = transaction(repo, key="STALE", transaction_uid=STALE_TRANSACTION_UID)
    repo.apply(transaction(repo))
    with pytest.raises(ConcurrencyConflict):
        repo.apply(stale)
    duplicate = transaction(repo, key="DUP", transaction_uid=DUPLICATE_TRANSACTION_UID)
    with pytest.raises(IntegrityError, match="already exists"):
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
    assert repo.apply(plan).idempotent_replay


def test_projection_failure_does_not_rollback_and_projection_rebuilds(tmp_path: Path) -> None:
    repo = repository(tmp_path)

    def projection_failure(commit: str) -> None:
        raise OSError(commit)

    result = repo.apply(transaction(repo), projection_updater=projection_failure)
    assert result.projection_stale
    database = tmp_path / "projection.db"
    assert repo.rebuild_projection(database) == result.commit
    with sqlite3.connect(database) as connection:
        paths = {row[0] for row in connection.execute("SELECT path FROM documents")}
        assert connection.execute("SELECT count(*) FROM resources").fetchone()[0] >= 2
    assert f"canonical/revisions/{REVISION_UID}.json" in paths


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
    assert repo.recover_workspaces()[0]["workspace_uid"] == "WS-2"


def test_unicode_content_and_foreign_diff_reconciliation(tmp_path: Path) -> None:
    repo = repository(tmp_path)
    operations = canonical_operations()
    revision = dict(operations[1].payload)
    revision["fields"] = [{"path": "/statement", "value": "CAN 信号位"}]
    revision["content_hash"] = semantic_hash(
        {key: value for key, value in revision.items() if key != "content_hash"}
    )
    plan = transaction(
        repo, operations=(operations[0], replace(operations[1], payload=revision))
    )
    result = repo.apply(plan)
    assert repo.read_json(result.commit, operations[1].relative_path) is not None
    assert repo.requires_reconciliation(("canonical/revisions/external.json",))
    assert not repo.requires_reconciliation(("README.md",))


def test_path_escape_schema_bypass_and_ai_approval_are_rejected(tmp_path: Path) -> None:
    repo = repository(tmp_path)
    operations = canonical_operations()
    escaped = replace(operations[1], relative_path="canonical/../outside.json")
    with pytest.raises(IntegrityError, match="unsafe canonical path"):
        repo.apply(transaction(repo, key="ESC", operations=(operations[0], escaped)))
    bypass = replace(operations[1], payload={"resource_type": "revision"})
    with pytest.raises(IntegrityError, match="schema validation"):
        repo.apply(transaction(repo, key="SCHEMA", operations=(operations[0], bypass)))
    ai_attestation = replace(approval(), actor_type="ai")
    with pytest.raises(ApprovalError, match="AI cannot"):
        repo.apply(
            replace(
                transaction(repo, key="AI"),
                approvals=(ai_attestation,),
            )
        )


def test_snapshot_cannot_claim_a_commit_that_does_not_contain_its_closure(
    tmp_path: Path,
) -> None:
    repo = repository(tmp_path)
    operations = canonical_operations()
    configuration = {
        "schema_version": "1.0",
        "resource_type": "configuration_snapshot",
        "configuration_uid": "018f0000-0000-7000-8000-000000000109",
        "git_commit": repo.current_commit(),
        "revision_uids": [REVISION_UID],
        "relation_revision_uids": [],
        "profile_revision_uids": [],
        "active_deviation_revision_uids": [],
        "effective_model_hash": MODEL_HASH,
        "closure_status": "complete",
        "closure_reasons": [],
        "created_at": "2026-08-05T00:00:00Z",
    }
    snapshot = SemanticOperation(
        OperationType.CREATE_CONFIGURATION,
        f"canonical/configurations/{configuration['configuration_uid']}.json",
        configuration,
    )
    with pytest.raises(IntegrityError, match="dedicated"):
        repo.apply(
            transaction(
                repo,
                key="MIXED-SNAPSHOT",
                transaction_uid="018f0000-0000-7000-8000-000000000110",
                operations=operations + (snapshot,),
            )
        )
