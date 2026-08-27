from __future__ import annotations

import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest

from lesr.adapters.git import (
    ApprovalError,
    CheckpointStrategy,
    ConcurrencyConflict,
    IdempotencyConflict,
    InjectedFailure,
    IntegrityError,
    OperationType,
    SemanticOperation,
    SemanticTransaction,
)
from lesr.domain.semantic import configuration_state_anchor, document_hash, semantic_hash
from tests.support.canonical_auth import CanonicalAuth, bootstrap_repository

OBJECT_UID = "018f0000-0000-7000-8000-000000000101"
REVISION_UID = "018f0000-0000-7000-8000-000000000102"
TRANSACTION_UID = "018f0000-0000-7000-8000-000000000106"
STALE_TRANSACTION_UID = "018f0000-0000-7000-8000-000000000107"
DUPLICATE_TRANSACTION_UID = "018f0000-0000-7000-8000-000000000108"
MODEL_HASH = semantic_hash({"model": "effective"})


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
    authorization: CanonicalAuth,
    *,
    key: str = "KEY-1",
    transaction_uid: str = TRANSACTION_UID,
    operations: tuple[SemanticOperation, ...] | None = None,
) -> SemanticTransaction:
    return authorization.transaction(
        transaction_uid=transaction_uid,
        idempotency_key=key,
        operations=operations or canonical_operations(),
    )


def repository(tmp_path: Path) -> CanonicalAuth:
    return bootstrap_repository(tmp_path / "repo")


def test_atomic_multi_resource_apply_and_idempotency(tmp_path: Path) -> None:
    authorization = repository(tmp_path)
    repo = authorization.repository
    plan = transaction(authorization)
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
        repo.apply(replace(plan, transaction_uid=DUPLICATE_TRANSACTION_UID))


def test_stale_base_and_immutable_overwrite_are_rejected(tmp_path: Path) -> None:
    authorization = repository(tmp_path)
    repo = authorization.repository
    stale = transaction(authorization, key="STALE", transaction_uid=STALE_TRANSACTION_UID)
    repo.apply(transaction(authorization))
    with pytest.raises(ConcurrencyConflict):
        repo.apply(stale)
    duplicate = transaction(authorization, key="DUP", transaction_uid=DUPLICATE_TRANSACTION_UID)
    with pytest.raises(IntegrityError, match="already exists"):
        repo.apply(duplicate)


@pytest.mark.parametrize("stage", ["after_stage", "before_commit", "before_ref"])
def test_failures_before_ref_leave_canonical_state_unchanged(
    tmp_path: Path, stage: str
) -> None:
    authorization = repository(tmp_path)
    repo = authorization.repository
    before = repo.current_commit()

    def inject(actual: str) -> None:
        if actual == stage:
            raise InjectedFailure(stage)

    with pytest.raises(InjectedFailure):
        repo.apply(transaction(authorization), fault_injector=inject)
    assert repo.current_commit() == before


def test_crash_after_ref_is_recovered_by_idempotent_retry(tmp_path: Path) -> None:
    authorization = repository(tmp_path)
    repo = authorization.repository
    plan = transaction(authorization)

    def inject(stage: str) -> None:
        if stage == "after_ref":
            raise InjectedFailure(stage)

    with pytest.raises(InjectedFailure):
        repo.apply(plan, fault_injector=inject)
    assert repo.apply(plan).idempotent_replay


def test_projection_failure_does_not_rollback_and_projection_rebuilds(tmp_path: Path) -> None:
    authorization = repository(tmp_path)
    repo = authorization.repository

    def projection_failure(commit: str) -> None:
        raise OSError(commit)

    result = repo.apply(transaction(authorization), projection_updater=projection_failure)
    assert result.projection_stale
    database = tmp_path / "projection.db"
    assert repo.rebuild_projection(database) == result.commit
    with sqlite3.connect(database) as connection:
        paths = {row[0] for row in connection.execute("SELECT path FROM documents")}
        assert connection.execute("SELECT count(*) FROM resources").fetchone()[0] >= 2
    assert f"canonical/revisions/{REVISION_UID}.json" in paths


def test_both_checkpoint_strategies_are_git_recoverable(tmp_path: Path) -> None:
    repo = repository(tmp_path).repository
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
    authorization = repository(tmp_path)
    repo = authorization.repository
    operations = canonical_operations()
    revision = dict(operations[1].payload)
    revision["fields"] = [{"path": "/statement", "value": "CAN 信号位"}]
    revision["content_hash"] = semantic_hash(
        {key: value for key, value in revision.items() if key != "content_hash"}
    )
    plan = transaction(
        authorization, operations=(operations[0], replace(operations[1], payload=revision))
    )
    result = repo.apply(plan)
    assert repo.read_json(result.commit, operations[1].relative_path) is not None
    assert repo.requires_reconciliation(("canonical/revisions/external.json",))
    assert not repo.requires_reconciliation(("README.md",))


def test_path_escape_schema_bypass_and_ai_approval_are_rejected(tmp_path: Path) -> None:
    authorization = repository(tmp_path)
    repo = authorization.repository
    operations = canonical_operations()
    authorized = transaction(authorization, key="DIRECT-BYPASS")
    unsigned = replace(
        authorized,
        operations=tuple(
            item
            for item in authorized.operations
            if item.payload.get("resource_type")
            not in {"approval_attestation", "provenance_record"}
        ),
    )
    with pytest.raises(ApprovalError, match="signed approval resources"):
        repo.apply(unsigned)
    escaped = replace(operations[1], relative_path="canonical/../outside.json")
    with pytest.raises(IntegrityError, match="unsafe canonical path"):
        repo.apply(transaction(authorization, key="ESC", operations=(operations[0], escaped)))
    bypass = replace(operations[1], payload={"resource_type": "revision"})
    with pytest.raises(IntegrityError, match="schema validation"):
        repo.apply(transaction(authorization, key="SCHEMA", operations=(operations[0], bypass)))
    ai_plan = transaction(authorization, key="AI")
    ai_attestation = replace(ai_plan.approvals[0], actor_type="ai")
    with pytest.raises(ApprovalError, match="AI cannot"):
        repo.apply(
            replace(
                ai_plan,
                approvals=(ai_attestation,),
            )
        )


def test_git_boundary_recomputes_validation_outcome(tmp_path: Path) -> None:
    authorization = repository(tmp_path)
    repo = authorization.repository
    plan = transaction(authorization, key="FORGED-VALIDATION")
    operations: list[SemanticOperation] = []
    for operation in plan.operations:
        if operation.payload.get("resource_type") != "validation_run":
            operations.append(operation)
            continue
        forged = operation.payload | {"outcome": "fail"}
        forged["content_hash"] = document_hash(forged, "content_hash")
        operations.append(replace(operation, payload=forged))
    with pytest.raises(
        ApprovalError, match="Validation Run findings or outcome are not reproducible"
    ):
        repo.apply(replace(plan, operations=tuple(operations)))


def test_snapshot_cannot_claim_a_commit_that_does_not_contain_its_closure(
    tmp_path: Path,
) -> None:
    authorization = repository(tmp_path)
    repo = authorization.repository
    operations = canonical_operations()
    configuration = {
        "schema_version": "1.0",
        "resource_type": "configuration_snapshot",
        "configuration_uid": "018f0000-0000-7000-8000-000000000109",
        "base_commit": repo.current_commit(),
        "revision_uids": [REVISION_UID],
        "relation_revision_uids": [],
        "profile_revision_uids": [],
        "active_deviation_revision_uids": [],
        "effective_model_hash": MODEL_HASH,
        "closure_status": "complete",
        "closure_reasons": [],
        "created_at": "2026-08-05T00:00:00Z",
    }
    configuration["state_anchor"] = configuration_state_anchor(
        revision_uids=(REVISION_UID,),
        relation_revision_uids=(),
        profile_revision_uids=(),
        active_deviation_revision_uids=(),
        effective_model_hash=MODEL_HASH,
    )
    snapshot = SemanticOperation(
        OperationType.CREATE_CONFIGURATION,
        f"canonical/configurations/{configuration['configuration_uid']}.json",
        configuration,
    )
    with pytest.raises(IntegrityError, match="dedicated"):
        repo.apply(
            transaction(
                authorization,
                key="MIXED-SNAPSHOT",
                transaction_uid="018f0000-0000-7000-8000-000000000110",
                operations=operations + (snapshot,),
            )
        )


def test_candidate_closure_rejects_duplicate_keys_and_invalid_revision_lineage(
    tmp_path: Path,
) -> None:
    authorization = repository(tmp_path)
    repo = authorization.repository
    logical = canonical_operations()[0]
    duplicate_value = dict(logical.payload) | {
        "entity_uid": "018f0000-0000-7000-8000-000000000120"
    }
    duplicate = SemanticOperation(
        OperationType.CREATE_LOGICAL_OBJECT,
        f"canonical/objects/{duplicate_value['entity_uid']}.json",
        duplicate_value,
    )
    with pytest.raises(IntegrityError, match="human key"):
        repo.apply(
            transaction(
                authorization,
                key="DUPLICATE-HUMAN-KEY",
                transaction_uid="018f0000-0000-7000-8000-000000000121",
                operations=(logical, duplicate),
            )
        )
    revision = canonical_operations()[1]
    invalid_revision = dict(revision.payload) | {
        "revision_number": 2,
        "parent_revision_uid": None,
    }
    invalid_revision["content_hash"] = semantic_hash(
        {
            key: value
            for key, value in invalid_revision.items()
            if key != "content_hash"
        }
    )
    with pytest.raises(IntegrityError, match="root revision number"):
        repo.apply(
            transaction(
                authorization,
                key="INVALID-LINEAGE",
                transaction_uid="018f0000-0000-7000-8000-000000000122",
                operations=(logical, replace(revision, payload=invalid_revision)),
            )
        )
