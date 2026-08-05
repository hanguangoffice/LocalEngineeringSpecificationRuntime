"""P4: Git-backed canonical state and atomic semantic-transaction prototype."""

from __future__ import annotations

import json
import os
import re
import sqlite3
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Any

from prototypes.lesr_v1.p1_semantic import canonical_json, semantic_hash, uuid7_candidate


class OperationType(StrEnum):
    CREATE_LOGICAL_OBJECT = "create_logical_object"
    CREATE_REVISION = "create_revision"
    SET_DISPOSITION = "set_disposition"
    ASSERT_RELATION = "assert_relation"
    RETIRE_RELATION = "retire_relation"
    CREATE_RECORD = "create_record"
    RETRACT_RECORD = "retract_record"
    CREATE_DEVIATION = "create_deviation"
    REVOKE_DEVIATION = "revoke_deviation"
    UPDATE_PROFILE_BINDING = "update_profile_binding"
    CREATE_CONFIGURATION = "create_configuration"
    CREATE_BASELINE = "create_baseline"
    PROMOTE_FRAGMENT = "promote_fragment"
    SPLIT_OBJECT = "split_object"
    CONSOLIDATE_OBJECT = "consolidate_object"


class CheckpointStrategy(StrEnum):
    COMMIT_PER_CHECKPOINT = "commit_per_checkpoint"
    WORKSPACE_REF = "workspace_ref"


class CanonicalError(RuntimeError):
    pass


class ConcurrencyConflict(CanonicalError):
    pass


class IdempotencyConflict(CanonicalError):
    pass


class ApprovalError(CanonicalError):
    pass


class IntegrityError(CanonicalError):
    pass


class InjectedFailure(CanonicalError):
    pass


@dataclass(frozen=True, slots=True)
class SemanticOperation:
    operation_type: OperationType
    relative_path: str
    payload: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ApprovalAttestation:
    approval_uid: str
    package_hash: str
    actor: str
    actor_type: str
    approval_type: str


@dataclass(frozen=True, slots=True)
class SemanticTransaction:
    transaction_uid: str
    base_commit: str
    expected_revisions: tuple[tuple[str, str], ...]
    effective_model_hash: str
    review_package_hash: str
    operations: tuple[SemanticOperation, ...]
    approvals: tuple[ApprovalAttestation, ...]
    actor: str
    delegation_uid: str
    idempotency_key: str

    def hash(self) -> str:
        return semantic_hash(
            {
                "transaction_uid": self.transaction_uid,
                "base_commit": self.base_commit,
                "expected_revisions": self.expected_revisions,
                "effective_model_hash": self.effective_model_hash,
                "review_package_hash": self.review_package_hash,
                "operations": [
                    {
                        "operation_type": item.operation_type,
                        "relative_path": item.relative_path,
                        "payload": item.payload,
                    }
                    for item in self.operations
                ],
                "approvals": [
                    {
                        "approval_uid": item.approval_uid,
                        "package_hash": item.package_hash,
                        "actor": item.actor,
                        "actor_type": item.actor_type,
                        "approval_type": item.approval_type,
                    }
                    for item in self.approvals
                ],
                "actor": self.actor,
                "delegation_uid": self.delegation_uid,
                "idempotency_key": self.idempotency_key,
            }
        )


@dataclass(frozen=True, slots=True)
class ApplyResult:
    commit: str
    transaction_hash: str
    idempotent_replay: bool
    projection_stale: bool


@dataclass(frozen=True, slots=True)
class CheckpointResult:
    checkpoint_uid: str
    commit: str
    git_reference: str
    strategy: CheckpointStrategy


FaultInjector = Callable[[str], None]
ProjectionUpdater = Callable[[str], None]


class GitCanonicalRepository:
    CANONICAL_REF = "refs/heads/canonical"

    def __init__(self, path: Path) -> None:
        self.path = path.resolve()

    def initialize(self) -> str:
        self.path.mkdir(parents=True, exist_ok=True)
        if not (self.path / ".git").exists():
            self._git("init", "--quiet")
            self._git("config", "user.name", "LESR Prototype")
            self._git("config", "user.email", "lesr-prototype@invalid.local")
        existing = self._try_git("rev-parse", "--verify", self.CANONICAL_REF)
        if existing is not None:
            return existing
        tree = self._git("mktree", input_text="")
        commit = self._commit_tree(tree, (), "Initialize LESR canonical state")
        self._git("update-ref", self.CANONICAL_REF, commit)
        return commit

    def current_commit(self) -> str:
        return self._git("rev-parse", "--verify", self.CANONICAL_REF)

    def apply(
        self,
        transaction: SemanticTransaction,
        *,
        projection_updater: ProjectionUpdater | None = None,
        fault_injector: FaultInjector | None = None,
    ) -> ApplyResult:
        self._validate_transaction(transaction)
        current = self.current_commit()
        transaction_hash = transaction.hash()
        idempotency_path = (
            f"canonical/idempotency/{self._safe_component(transaction.idempotency_key)}.json"
        )
        previous = self.read_json(current, idempotency_path)
        if previous is not None:
            if previous.get("transaction_hash") != transaction_hash:
                raise IdempotencyConflict(
                    "the idempotency key was already used for a different transaction"
                )
            return ApplyResult(current, transaction_hash, True, False)
        if current != transaction.base_commit:
            raise ConcurrencyConflict(
                f"canonical base changed: expected {transaction.base_commit}, got {current}"
            )
        self._verify_expected_revisions(current, transaction.expected_revisions)
        for operation in transaction.operations:
            safe_path = self._safe_path(operation.relative_path)
            if (
                operation.operation_type is OperationType.CREATE_REVISION
                and self.read_bytes(current, safe_path) is not None
            ):
                raise IntegrityError(f"historical revision already exists: {safe_path}")

        index_path = self.path / f".lesr-index-{uuid7_candidate()}.tmp"
        index_path.unlink(missing_ok=True)
        env = {"GIT_INDEX_FILE": str(index_path)}
        try:
            self._git("read-tree", current, extra_env=env)
            for operation in transaction.operations:
                content = (canonical_json(operation.payload) + "\n").encode("utf-8")
                self._stage_bytes(self._safe_path(operation.relative_path), content, env)
            change_record = self._change_record(transaction, transaction_hash)
            self._stage_json(
                f"canonical/applied_changes/{transaction.transaction_uid}.json",
                change_record,
                env,
            )
            self._stage_json(
                f"canonical/provenance/{transaction.transaction_uid}.json",
                {
                    "activity": "apply",
                    "transaction_uid": transaction.transaction_uid,
                    "initiated_by": transaction.actor,
                    "performed_by": transaction.actor,
                    "on_behalf_of": transaction.delegation_uid,
                    "persisted_by": "LESR Prototype",
                    "used": [transaction.base_commit, transaction.effective_model_hash],
                },
                env,
            )
            self._stage_json(
                f"canonical/audit/{transaction.transaction_uid}.json",
                {
                    "operation": "semantic_transaction.apply",
                    "target": transaction.transaction_uid,
                    "actor": transaction.actor,
                    "before_hash": transaction.base_commit,
                    "request_hash": transaction_hash,
                    "policy_decision": "approved",
                },
                env,
            )
            self._stage_json(
                idempotency_path,
                {
                    "idempotency_key": transaction.idempotency_key,
                    "transaction_uid": transaction.transaction_uid,
                    "transaction_hash": transaction_hash,
                },
                env,
            )
            self._inject(fault_injector, "after_stage")
            tree = self._git("write-tree", extra_env=env)
            self._inject(fault_injector, "before_commit")
            commit = self._commit_tree(
                tree,
                (current,),
                f"Apply semantic transaction {transaction.transaction_uid}",
            )
            self._inject(fault_injector, "before_ref")
            try:
                self._git("update-ref", self.CANONICAL_REF, commit, current)
            except CanonicalError as error:
                raise ConcurrencyConflict("canonical ref changed during apply") from error
            self._inject(fault_injector, "after_ref")
        finally:
            index_path.unlink(missing_ok=True)
        projection_stale = False
        if projection_updater is not None:
            try:
                projection_updater(commit)
            except (OSError, RuntimeError):
                projection_stale = True
        return ApplyResult(commit, transaction_hash, False, projection_stale)

    def create_checkpoint(
        self,
        workspace_uid: str,
        payload: dict[str, Any],
        strategy: CheckpointStrategy,
    ) -> CheckpointResult:
        workspace = self._safe_component(workspace_uid)
        checkpoint_uid = uuid7_candidate()
        if strategy is CheckpointStrategy.COMMIT_PER_CHECKPOINT:
            parent = self.current_commit()
            reference = f"refs/lesr/checkpoints/{workspace}/{checkpoint_uid}"
        else:
            reference = f"refs/heads/lesr-workspace/{workspace}"
            parent = self._try_git("rev-parse", "--verify", reference) or self.current_commit()
        index_path = self.path / f".lesr-index-{checkpoint_uid}.tmp"
        index_path.unlink(missing_ok=True)
        env = {"GIT_INDEX_FILE": str(index_path)}
        try:
            self._git("read-tree", parent, extra_env=env)
            checkpoint_path = (
                f"workspaces/{workspace}/checkpoints/{checkpoint_uid}.json"
            )
            self._stage_json(
                checkpoint_path,
                {
                    "checkpoint_uid": checkpoint_uid,
                    "workspace_uid": workspace_uid,
                    "base_commit": self.current_commit(),
                    "working_state": payload,
                },
                env,
            )
            tree = self._git("write-tree", extra_env=env)
            commit = self._commit_tree(tree, (parent,), f"Checkpoint {checkpoint_uid}")
            expected = parent if self._try_git("rev-parse", "--verify", reference) else None
            if expected is None:
                self._git("update-ref", reference, commit)
            else:
                self._git("update-ref", reference, commit, expected)
        finally:
            index_path.unlink(missing_ok=True)
        return CheckpointResult(checkpoint_uid, commit, reference, strategy)

    def rebuild_projection(self, database: Path) -> str:
        source_commit = self.current_commit()
        database.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(database) as connection:
            connection.executescript(
                "DROP TABLE IF EXISTS documents;"
                "CREATE TABLE documents (path TEXT PRIMARY KEY, json TEXT NOT NULL, "
                "source_commit TEXT NOT NULL);"
            )
            listing = self._git(
                "ls-tree", "-r", "--name-only", source_commit, "canonical"
            ).splitlines()
            rows: list[tuple[str, str, str]] = []
            for path in listing:
                if not path.endswith(".json"):
                    continue
                content = self.read_bytes(source_commit, path)
                if content is not None:
                    rows.append((path, content.decode("utf-8"), source_commit))
            connection.executemany("INSERT INTO documents VALUES (?, ?, ?)", rows)
        return source_commit

    def read_json(self, commit: str, path: str) -> dict[str, Any] | None:
        content = self.read_bytes(commit, path)
        if content is None:
            return None
        value = json.loads(content)
        if not isinstance(value, dict):
            raise IntegrityError(f"expected JSON object at {path}")
        return value

    def read_bytes(self, commit: str, path: str) -> bytes | None:
        result = subprocess.run(
            ["git", "-C", str(self.path), "show", f"{commit}:{path}"],
            check=False,
            capture_output=True,
        )
        if result.returncode != 0:
            return None
        return result.stdout

    def checkpoint_payload(self, checkpoint: CheckpointResult) -> dict[str, Any]:
        path = (
            f"workspaces/{self._safe_component('WS-' + checkpoint.checkpoint_uid)}/"
            f"checkpoints/{checkpoint.checkpoint_uid}.json"
        )
        listing = self._git(
            "ls-tree", "-r", "--name-only", checkpoint.commit, "workspaces"
        ).splitlines()
        actual = next(item for item in listing if item.endswith(f"/{checkpoint.checkpoint_uid}.json"))
        del path
        value = self.read_json(checkpoint.commit, actual)
        if value is None:
            raise IntegrityError("checkpoint payload is missing")
        return value

    @staticmethod
    def requires_reconciliation(changed_paths: tuple[str, ...]) -> bool:
        return any(path.replace("\\", "/").startswith("canonical/") for path in changed_paths)

    def _verify_expected_revisions(
        self, commit: str, expected_revisions: tuple[tuple[str, str], ...]
    ) -> None:
        for revision_uid, expected_hash in expected_revisions:
            path = f"canonical/revisions/{self._safe_component(revision_uid)}.json"
            revision = self.read_json(commit, path)
            if revision is None or revision.get("content_hash") != expected_hash:
                raise ConcurrencyConflict(f"expected revision changed or missing: {revision_uid}")

    @staticmethod
    def _validate_transaction(transaction: SemanticTransaction) -> None:
        if not transaction.operations:
            raise IntegrityError("a semantic transaction requires at least one operation")
        if not transaction.approvals:
            raise ApprovalError("a semantic transaction requires an approval attestation")
        for approval in transaction.approvals:
            if approval.package_hash != transaction.review_package_hash:
                raise ApprovalError("approval does not bind the review package hash")
            if approval.actor_type.casefold() == "ai":
                raise ApprovalError("AI cannot provide formal approval")
        if not transaction.delegation_uid:
            raise IntegrityError("delegation is required")

    @staticmethod
    def _change_record(
        transaction: SemanticTransaction, transaction_hash: str
    ) -> dict[str, Any]:
        return {
            "transaction_uid": transaction.transaction_uid,
            "transaction_hash": transaction_hash,
            "base_commit": transaction.base_commit,
            "expected_revisions": transaction.expected_revisions,
            "effective_model_hash": transaction.effective_model_hash,
            "review_package_hash": transaction.review_package_hash,
            "operations": [
                {
                    "type": item.operation_type,
                    "path": item.relative_path,
                    "payload_hash": semantic_hash(item.payload),
                }
                for item in transaction.operations
            ],
            "approval_uids": [item.approval_uid for item in transaction.approvals],
            "applied_at": datetime.now(UTC).isoformat(),
        }

    def _stage_json(self, path: str, value: dict[str, Any], env: dict[str, str]) -> None:
        self._stage_bytes(path, (canonical_json(value) + "\n").encode("utf-8"), env)

    def _stage_bytes(self, path: str, content: bytes, env: dict[str, str]) -> None:
        blob = self._git("hash-object", "-w", "--stdin", input_bytes=content)
        self._git(
            "update-index", "--add", "--cacheinfo", f"100644,{blob},{path}", extra_env=env
        )

    def _commit_tree(self, tree: str, parents: tuple[str, ...], message: str) -> str:
        arguments = ["commit-tree", tree]
        for parent in parents:
            arguments.extend(("-p", parent))
        return self._git(*arguments, input_text=message + "\n")

    @staticmethod
    def _inject(injector: FaultInjector | None, stage: str) -> None:
        if injector is not None:
            injector(stage)

    @staticmethod
    def _safe_component(value: str) -> str:
        if not re.fullmatch(r"[A-Za-z0-9._-]+", value):
            raise IntegrityError(f"unsafe identifier component: {value}")
        return value

    @staticmethod
    def _safe_path(value: str) -> str:
        path = PurePosixPath(value)
        if path.is_absolute() or ".." in path.parts or not value.startswith("canonical/"):
            raise IntegrityError(f"unsafe canonical path: {value}")
        return path.as_posix()

    def _try_git(self, *arguments: str) -> str | None:
        result = subprocess.run(
            ["git", "-C", str(self.path), *arguments],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        return result.stdout.strip() if result.returncode == 0 else None

    def _git(
        self,
        *arguments: str,
        input_text: str | None = None,
        input_bytes: bytes | None = None,
        extra_env: dict[str, str] | None = None,
    ) -> str:
        env = os.environ.copy()
        env.update(
            {
                "GIT_AUTHOR_NAME": "LESR Prototype",
                "GIT_AUTHOR_EMAIL": "lesr-prototype@invalid.local",
                "GIT_COMMITTER_NAME": "LESR Prototype",
                "GIT_COMMITTER_EMAIL": "lesr-prototype@invalid.local",
            }
        )
        if extra_env:
            env.update(extra_env)
        if input_text is not None and input_bytes is not None:
            raise ValueError("provide input_text or input_bytes, not both")
        payload = input_bytes if input_bytes is not None else input_text
        text_mode = input_bytes is None
        result = subprocess.run(
            ["git", "-C", str(self.path), *arguments],
            input=payload,
            check=False,
            capture_output=True,
            text=text_mode,
            encoding="utf-8" if text_mode else None,
            env=env,
        )
        if result.returncode != 0:
            stderr = result.stderr if isinstance(result.stderr, str) else result.stderr.decode()
            raise CanonicalError(f"git {' '.join(arguments)} failed: {stderr.strip()}")
        stdout = result.stdout if isinstance(result.stdout, str) else result.stdout.decode()
        return stdout.strip()
