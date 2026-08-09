"""Local-only persistent tasks and repository maintenance operations."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import Field

from lesr.adapters.git import GitCanonicalRepository, IntegrityError
from lesr.domain.catalog import RepositoryManifest
from lesr.domain.semantic import FrozenModel, canonical_json, semantic_hash, uuid7_candidate


class PersistentTaskState(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    CANCELLING = "cancelling"
    CANCELLED = "cancelled"
    FAILED = "failed"
    COMPLETED = "completed"
    INTERRUPTED = "interrupted"


class PersistentTask(FrozenModel):
    schema_version: Literal["1.0"] = "1.0"
    resource_type: Literal["task_record"] = "task_record"
    task_uid: str = Field(default_factory=uuid7_candidate)
    task_type: Literal["full_validation", "deep_trace", "migration", "backup", "large_impact"]
    state: PersistentTaskState
    progress: int = Field(ge=0, le=100)
    request_hash: str
    checkpoint_hash: str | None = None
    result_hash: str | None = None
    error: str | None = None
    created_at: datetime
    updated_at: datetime


class TaskStore:
    """Disposable runtime database; task progress never enters Canonical Git."""

    def __init__(self, project: Path) -> None:
        self.path = project / ".lesr" / "runtime.sqlite3"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def enqueue(self, task_type: str, request: dict[str, object]) -> PersistentTask:
        now = datetime.now(UTC)
        task = PersistentTask.model_validate(
            {
                "task_type": task_type,
                "state": PersistentTaskState.QUEUED,
                "progress": 0,
                "request_hash": semantic_hash(request),
                "created_at": now,
                "updated_at": now,
            }
        )
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO tasks VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                self._row(task),
            )
            connection.execute(
                "INSERT INTO task_requests VALUES (?, ?)",
                (task.task_uid, canonical_json(request)),
            )
        return task

    def claim_next(self) -> PersistentTask | None:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM tasks WHERE state = ? ORDER BY created_at, task_uid LIMIT 1",
                (PersistentTaskState.QUEUED.value,),
            ).fetchone()
            if row is None:
                return None
            now = datetime.now(UTC).isoformat()
            connection.execute(
                "UPDATE tasks SET state = ?, updated_at = ? WHERE task_uid = ?",
                (PersistentTaskState.RUNNING.value, now, row[0]),
            )
        return self.get(str(row[0]))

    def update_progress(
        self, task_uid: str, progress: int, checkpoint: dict[str, object] | None = None
    ) -> PersistentTask:
        task = self.get(task_uid)
        if task.state not in {PersistentTaskState.RUNNING, PersistentTaskState.CANCELLING}:
            raise ValueError("LESR-TASK-NOT-RUNNING")
        checkpoint_hash = (
            semantic_hash(checkpoint) if checkpoint is not None else task.checkpoint_hash
        )
        with self._connect() as connection:
            connection.execute(
                "UPDATE tasks SET progress = ?, checkpoint_hash = ?, updated_at = ? "
                "WHERE task_uid = ?",
                (progress, checkpoint_hash, datetime.now(UTC).isoformat(), task_uid),
            )
            if checkpoint is not None:
                connection.execute(
                    "INSERT OR REPLACE INTO task_checkpoints VALUES (?, ?)",
                    (task_uid, canonical_json(checkpoint)),
                )
        return self.get(task_uid)

    def request_cancel(self, task_uid: str) -> PersistentTask:
        task = self.get(task_uid)
        next_state = (
            PersistentTaskState.CANCELLED
            if task.state is PersistentTaskState.QUEUED
            else PersistentTaskState.CANCELLING
        )
        if task.state not in {PersistentTaskState.QUEUED, PersistentTaskState.RUNNING}:
            return task
        return self._set_state(task_uid, next_state)

    def cancellation_requested(self, task_uid: str) -> bool:
        return self.get(task_uid).state is PersistentTaskState.CANCELLING

    def finish(
        self,
        task_uid: str,
        result: dict[str, object] | None,
        *,
        error: str | None = None,
    ) -> PersistentTask:
        task = self.get(task_uid)
        if task.state is PersistentTaskState.CANCELLING:
            state = PersistentTaskState.CANCELLED
            result_hash = None
        elif error is not None:
            state = PersistentTaskState.FAILED
            result_hash = None
        else:
            state = PersistentTaskState.COMPLETED
            result_hash = semantic_hash(result or {})
        with self._connect() as connection:
            connection.execute(
                "UPDATE tasks SET state = ?, progress = ?, result_hash = ?, error = ?, "
                "updated_at = ? WHERE task_uid = ?",
                (
                    state.value,
                    100 if state is PersistentTaskState.COMPLETED else task.progress,
                    result_hash,
                    error,
                    datetime.now(UTC).isoformat(),
                    task_uid,
                ),
            )
            if result is not None:
                connection.execute(
                    "INSERT OR REPLACE INTO task_results VALUES (?, ?)",
                    (task_uid, canonical_json(result)),
                )
        return self.get(task_uid)

    def recover_after_restart(self) -> tuple[PersistentTask, ...]:
        with self._connect() as connection:
            connection.execute(
                "UPDATE tasks SET state = ?, updated_at = ? WHERE state IN (?, ?)",
                (
                    PersistentTaskState.INTERRUPTED.value,
                    datetime.now(UTC).isoformat(),
                    PersistentTaskState.RUNNING.value,
                    PersistentTaskState.CANCELLING.value,
                ),
            )
        return self.list(PersistentTaskState.INTERRUPTED)

    def resume(self, task_uid: str) -> PersistentTask:
        task = self.get(task_uid)
        if task.state is not PersistentTaskState.INTERRUPTED:
            raise ValueError("LESR-TASK-NOT-INTERRUPTED")
        return self._set_state(task_uid, PersistentTaskState.QUEUED)

    def get(self, task_uid: str) -> PersistentTask:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM tasks WHERE task_uid = ?", (task_uid,)
            ).fetchone()
        if row is None:
            raise KeyError(task_uid)
        return self._from_row(row)

    def request(self, task_uid: str) -> dict[str, object]:
        return self._json_record("task_requests", task_uid)

    def result(self, task_uid: str) -> dict[str, object] | None:
        try:
            return self._json_record("task_results", task_uid)
        except KeyError:
            return None

    def checkpoint(self, task_uid: str) -> dict[str, object] | None:
        try:
            return self._json_record("task_checkpoints", task_uid)
        except KeyError:
            return None

    def put_artifact(self, artifact_hash: str, value: dict[str, object]) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO runtime_artifacts VALUES (?, ?)",
                (artifact_hash, canonical_json(value)),
            )

    def artifact(self, artifact_hash: str) -> dict[str, object]:
        return self._json_record("runtime_artifacts", artifact_hash)

    def list(self, state: PersistentTaskState | None = None) -> tuple[PersistentTask, ...]:
        with self._connect() as connection:
            if state is None:
                rows = connection.execute("SELECT * FROM tasks ORDER BY created_at").fetchall()
            else:
                rows = connection.execute(
                    "SELECT * FROM tasks WHERE state = ? ORDER BY created_at",
                    (state.value,),
                ).fetchall()
        return tuple(self._from_row(row) for row in rows)

    def _set_state(self, task_uid: str, state: PersistentTaskState) -> PersistentTask:
        with self._connect() as connection:
            connection.execute(
                "UPDATE tasks SET state = ?, updated_at = ? WHERE task_uid = ?",
                (state.value, datetime.now(UTC).isoformat(), task_uid),
            )
        return self.get(task_uid)

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS tasks (
                    task_uid TEXT PRIMARY KEY, task_type TEXT NOT NULL, state TEXT NOT NULL,
                    progress INTEGER NOT NULL, request_hash TEXT NOT NULL,
                    checkpoint_hash TEXT, result_hash TEXT, error TEXT,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS task_requests (
                    task_uid TEXT PRIMARY KEY, value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS task_checkpoints (
                    task_uid TEXT PRIMARY KEY, value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS task_results (
                    task_uid TEXT PRIMARY KEY, value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS runtime_artifacts (
                    task_uid TEXT PRIMARY KEY, value TEXT NOT NULL
                );
                """
            )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path)

    def _json_record(self, table: str, task_uid: str) -> dict[str, object]:
        if table not in {
            "task_requests",
            "task_results",
            "task_checkpoints",
            "runtime_artifacts",
        }:
            raise ValueError("invalid task record table")
        with self._connect() as connection:
            row = connection.execute(
                f"SELECT value FROM {table} WHERE task_uid = ?",
                (task_uid,),
            ).fetchone()
        if row is None:
            raise KeyError(task_uid)
        value = json.loads(str(row[0]))
        if not isinstance(value, dict):
            raise IntegrityError("task record is not an object")
        return value

    @staticmethod
    def _row(task: PersistentTask) -> tuple[object, ...]:
        return (
            task.task_uid,
            task.task_type,
            task.state.value,
            task.progress,
            task.request_hash,
            task.checkpoint_hash,
            task.result_hash,
            task.error,
            task.created_at.isoformat(),
            task.updated_at.isoformat(),
        )

    @staticmethod
    def _from_row(row: tuple[object, ...]) -> PersistentTask:
        return PersistentTask.model_validate(
            {
                "task_uid": str(row[0]),
                "task_type": str(row[1]),
                "state": str(row[2]),
                "progress": int(str(row[3])),
                "request_hash": str(row[4]),
                "checkpoint_hash": str(row[5]) if row[5] is not None else None,
                "result_hash": str(row[6]) if row[6] is not None else None,
                "error": str(row[7]) if row[7] is not None else None,
                "created_at": datetime.fromisoformat(str(row[8])),
                "updated_at": datetime.fromisoformat(str(row[9])),
            }
        )


TaskHandler = Callable[
    [dict[str, object], Callable[[int, dict[str, object] | None], None], Callable[[], bool]],
    dict[str, object],
]


class TaskWorker:
    """Explicit local worker; callers decide when one queued task may consume resources."""

    def __init__(self, store: TaskStore, handlers: dict[str, TaskHandler]) -> None:
        self.store = store
        self.handlers = handlers

    def run_next(self) -> PersistentTask | None:
        task = self.store.claim_next()
        if task is None:
            return None
        handler = self.handlers.get(task.task_type)
        if handler is None:
            return self.store.finish(task.task_uid, None, error="LESR-TASK-HANDLER-UNAVAILABLE")

        def progress(value: int, checkpoint: dict[str, object] | None = None) -> None:
            self.store.update_progress(task.task_uid, value, checkpoint)

        def cancelled() -> bool:
            return self.store.cancellation_requested(task.task_uid)

        try:
            result = handler(self.store.request(task.task_uid), progress, cancelled)
            return self.store.finish(task.task_uid, result)
        except Exception as error:  # noqa: BLE001 - task failure is persisted, not hidden
            return self.store.finish(task.task_uid, None, error=str(error))


class BackupManifest(FrozenModel):
    schema_version: Literal["1.0"] = "1.0"
    canonical_commit: str
    repository_manifest_hash: str
    bundle_sha256: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class BackupResult:
    bundle: Path
    manifest: Path
    bundle_sha256: str


class RepositoryMaintenance:
    def __init__(self, project: Path) -> None:
        self.project = project.resolve()
        self.repository = GitCanonicalRepository(self.project)

    def backup(self, destination: Path) -> BackupResult:
        commit = self.repository.current_commit()
        manifest_value = self.repository.require_v1_manifest(commit)
        destination.mkdir(parents=True, exist_ok=True)
        bundle = destination / "lesr-repository.bundle"
        result = subprocess.run(
            [
                "git",
                "-C",
                str(self.project),
                "bundle",
                "create",
                str(bundle),
                GitCanonicalRepository.CANONICAL_REF,
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise IntegrityError(f"backup bundle failed: {result.stderr.strip()}")
        digest = "sha256:" + hashlib.sha256(bundle.read_bytes()).hexdigest()
        backup_manifest = BackupManifest(
            canonical_commit=commit,
            repository_manifest_hash=str(manifest_value["manifest_hash"]),
            bundle_sha256=digest,
            created_at=datetime.now(UTC),
        )
        manifest_path = destination / "backup-manifest.json"
        manifest_path.write_text(
            canonical_json(backup_manifest) + "\n", encoding="utf-8", newline="\n"
        )
        return BackupResult(bundle, manifest_path, digest)

    @staticmethod
    def restore(source: Path, destination: Path) -> str:
        if destination.exists() and any(destination.iterdir()):
            raise ValueError("LESR-RESTORE-DESTINATION-NOT-EMPTY")
        manifest_path = source / "backup-manifest.json"
        bundle = source / "lesr-repository.bundle"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        actual = "sha256:" + hashlib.sha256(bundle.read_bytes()).hexdigest()
        if actual != manifest.get("bundle_sha256"):
            raise IntegrityError("LESR-BACKUP-HASH-MISMATCH")
        destination.mkdir(parents=True, exist_ok=True)
        result = subprocess.run(
            ["git", "clone", "--quiet", str(bundle), str(destination)],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise IntegrityError(f"restore clone failed: {result.stderr.strip()}")
        repository = GitCanonicalRepository(destination)
        repository._git(
            "update-ref",
            repository.CANONICAL_REF,
            str(manifest["canonical_commit"]),
        )
        repository.require_v1_manifest(str(manifest["canonical_commit"]))
        return str(manifest["canonical_commit"])

    def migration_plan(self, target_version: str, *, dry_run: bool = True) -> dict[str, object]:
        manifest = RepositoryManifest.model_validate(self.repository.require_v1_manifest())
        if not target_version.startswith("1."):
            raise ValueError("LESR-MIGRATION-ONLY-SUPPORTS-POST-1.0-FORWARD")
        current = manifest.canonical_format_version
        if target_version <= current:
            raise ValueError("LESR-MIGRATION-TARGET-NOT-FORWARD")
        commit = self.repository.current_commit()
        backup_ref = f"refs/lesr/backups/pre-migration-{uuid7_candidate()}"
        report = {
            "from_version": current,
            "to_version": target_version,
            "source_commit": commit,
            "backup_ref": backup_ref,
            "dry_run": dry_run,
            "steps": [],
            "status": "unsupported_until_step_registered",
        }
        if not dry_run:
            self.repository._git("update-ref", backup_ref, commit)
            raise ValueError("LESR-MIGRATION-STEP-NOT-REGISTERED")
        return report

    def workspace_gc(self, *, dry_run: bool = True, now: datetime | None = None) -> dict[str, object]:
        """Remove only stale Workspace/checkpoint refs; never invoke Git prune."""
        actual_now = now or datetime.now(UTC)
        raw = self.repository._try_git(
            "for-each-ref",
            "--format=%(refname)|%(creatordate:iso-strict)",
            "refs/lesr/workspaces/",
            "refs/lesr/checkpoints/",
        )
        refs: list[tuple[str, datetime]] = []
        for line in raw.splitlines() if raw else ():
            name, created = line.split("|", 1)
            refs.append((name, datetime.fromisoformat(created)))
        documents = [value for _, value in self.repository.documents()]
        referenced_workspaces = {
            str(value["workspace_uid"])
            for value in documents
            if value.get("resource_type") in {"review_package", "baseline_preparation"}
            and value.get("workspace_uid")
        }
        referenced_refs = tuple(
            name
            for name, _ in refs
            if any(f"/{uid}" in name for uid in referenced_workspaces)
        )
        plan = plan_workspace_gc(
            tuple(refs),
            referenced_refs,
            now=actual_now,
            dry_run=dry_run,
        )
        removed: list[str] = []
        if not dry_run:
            for reference in plan.removable_checkpoint_uids:
                self.repository._git("update-ref", "-d", reference)
                removed.append(reference)
        return plan.model_dump(mode="json") | {
            "removed_refs": removed,
            "git_prune_executed": False,
        }


class GCPlan(FrozenModel):
    generated_at: datetime
    dry_run: bool
    retain_after: datetime
    retained_checkpoint_uids: tuple[str, ...]
    removable_checkpoint_uids: tuple[str, ...]
    git_prune_requested: Literal[False] = False


def plan_workspace_gc(
    checkpoints: tuple[tuple[str, datetime], ...],
    referenced_uids: tuple[str, ...],
    *,
    now: datetime,
    dry_run: bool = True,
) -> GCPlan:
    cutoff = now - timedelta(days=30)
    recent_twenty = {
        uid for uid, _ in sorted(checkpoints, key=lambda item: item[1], reverse=True)[:20]
    }
    referenced = set(referenced_uids)
    retained = {
        uid
        for uid, created_at in checkpoints
        if created_at >= cutoff or uid in recent_twenty or uid in referenced
    }
    removable = {uid for uid, _ in checkpoints} - retained
    return GCPlan(
        generated_at=now,
        dry_run=dry_run,
        retain_after=cutoff,
        retained_checkpoint_uids=tuple(sorted(retained)),
        removable_checkpoint_uids=tuple(sorted(removable)),
    )
