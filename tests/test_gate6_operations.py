from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from lesr.adapters.git import GitCanonicalRepository, IntegrityError
from lesr.adapters.operations import (
    PersistentTaskState,
    RepositoryMaintenance,
    TaskStore,
    TaskWorker,
    plan_workspace_gc,
)
from lesr.application.runtime import LocalRuntimeService
from lesr.domain.catalog import CAPABILITIES, CapabilityAccess


def test_task_queue_persists_progress_cancel_and_restart_recovery(tmp_path: Path) -> None:
    store = TaskStore(tmp_path)
    first = store.enqueue("deep_trace", {"target": "REQ-1"})
    claimed = store.claim_next()
    assert claimed is not None and claimed.task_uid == first.task_uid
    progressed = store.update_progress(first.task_uid, 40, {"batch": 4})
    assert progressed.progress == 40
    assert progressed.checkpoint_hash is not None
    interrupted = TaskStore(tmp_path).recover_after_restart()
    assert interrupted[0].state is PersistentTaskState.INTERRUPTED
    resumed = store.resume(first.task_uid)
    assert resumed.state is PersistentTaskState.QUEUED
    store.claim_next()
    cancelling = store.request_cancel(first.task_uid)
    assert cancelling.state is PersistentTaskState.CANCELLING
    cancelled = store.finish(first.task_uid, None)
    assert cancelled.state is PersistentTaskState.CANCELLED


def test_runtime_task_database_is_outside_canonical_git(tmp_path: Path) -> None:
    repository = GitCanonicalRepository(tmp_path)
    commit = repository.initialize()
    TaskStore(tmp_path).enqueue("full_validation", {"scope": "all"})
    assert repository.current_commit() == commit
    assert all(not path.startswith(".lesr/") for path, _ in repository._tree_entries(commit))


def test_task_worker_executes_registered_handler_and_persists_result(tmp_path: Path) -> None:
    store = TaskStore(tmp_path)
    task = store.enqueue("deep_trace", {"target": "REQ-1"})
    worker = TaskWorker(
        store,
        {
            "deep_trace": lambda request, progress, cancelled: (
                progress(50, {"phase": "trace"})
                or {"target": request["target"], "cancelled": cancelled()}
            )
        },
    )
    completed = worker.run_next()
    assert completed is not None and completed.state is PersistentTaskState.COMPLETED
    assert store.result(task.task_uid) == {"cancelled": False, "target": "REQ-1"}


def test_runtime_worker_executes_migration_plan_and_backup_task_families(
    tmp_path: Path,
) -> None:
    domain = LocalRuntimeService(tmp_path / "project")
    migration = domain.start_task(
        "migration", {"target_version": "1.1.0", "dry_run": True}
    )
    assert migration.ok
    completed = domain.run_next_task()
    assert completed.value["state"] == "completed"
    migration_result = domain.task_result(migration.value["task_uid"])
    assert migration_result.value["status"] == "unsupported_until_step_registered"

    backup = domain.start_task(
        "backup", {"destination": str(tmp_path / "task-backup")}
    )
    assert backup.ok
    completed = domain.run_next_task()
    assert completed.value["state"] == "completed"
    backup_result = domain.task_result(backup.value["task_uid"])
    assert Path(backup_result.value["bundle"]).is_file()


def test_backup_restore_verifies_bundle_and_requires_empty_destination(tmp_path: Path) -> None:
    source = tmp_path / "source"
    repository = GitCanonicalRepository(source)
    commit = repository.initialize()
    backup = RepositoryMaintenance(source).backup(tmp_path / "backup")
    restored = tmp_path / "restored"
    assert RepositoryMaintenance.restore(backup.bundle.parent, restored) == commit
    assert GitCanonicalRepository(restored).require_v1_manifest(commit)
    with pytest.raises(ValueError, match="NOT-EMPTY"):
        RepositoryMaintenance.restore(backup.bundle.parent, restored)

    backup.bundle.write_bytes(backup.bundle.read_bytes() + b"tampered")
    with pytest.raises(IntegrityError, match="HASH-MISMATCH"):
        RepositoryMaintenance.restore(backup.bundle.parent, tmp_path / "tampered")


def test_migration_is_forward_only_and_dry_run_does_not_create_backup_ref(
    tmp_path: Path,
) -> None:
    repository = GitCanonicalRepository(tmp_path)
    repository.initialize()
    maintenance = RepositoryMaintenance(tmp_path)
    report = maintenance.migration_plan("1.1.0", dry_run=True)
    assert report["status"] == "unsupported_until_step_registered"
    assert repository._try_git("show-ref", str(report["backup_ref"])) is None
    with pytest.raises(ValueError, match="POST-1.0-FORWARD"):
        maintenance.migration_plan("2.0.0")


def test_gc_retains_30_days_20_recent_and_all_governance_references() -> None:
    now = datetime(2026, 8, 5, tzinfo=UTC)
    checkpoints = tuple(
        (f"cp-{index:02d}", now - timedelta(days=index + 20)) for index in range(30)
    )
    plan = plan_workspace_gc(
        checkpoints,
        ("cp-29",),
        now=now,
    )
    assert plan.dry_run
    assert plan.git_prune_requested is False
    assert "cp-29" in plan.retained_checkpoint_uids
    assert len(plan.retained_checkpoint_uids) >= 20


def test_shared_capabilities_never_offer_mcp_admin_or_private_signing() -> None:
    names = {item.name for item in CAPABILITIES}
    assert "approval.sign" not in names
    assert "shell" not in names and "sql" not in names and "file" not in names
    assert all(item.access is not CapabilityAccess.ADMIN for item in CAPABILITIES if item.mcp)
    assert {item.name for item in CAPABILITIES if item.access is CapabilityAccess.ADMIN} == {
        "backup",
        "gc",
        "migrate",
        "projection.rebuild",
        "restore",
    }
