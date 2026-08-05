"""LESR v1 Git-backed canonical state and atomic semantic transactions."""

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

from jsonschema.exceptions import ValidationError as JsonSchemaValidationError

from lesr.adapters.schemas import SchemaCatalog
from lesr.domain.semantic import canonical_json, document_hash, semantic_hash, uuid7_candidate


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
    REGISTER_TRUSTED_ACTOR = "register_trusted_actor"
    CREATE_DELEGATION = "create_delegation"
    RECORD_APPROVAL = "record_approval"
    CREATE_RULE = "create_rule"


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

_RESOURCE_SCHEMAS = {
    "logical_object": "logical-object.schema.json",
    "revision": "revision.schema.json",
    "relation_assertion_revision": "relation-assertion.schema.json",
    "immutable_record": "immutable-record.schema.json",
    "profile_revision": "profile.schema.json",
    "configuration_snapshot": "configuration.schema.json",
    "baseline_manifest": "baseline-manifest.schema.json",
    "trusted_actor": "trusted-actor.schema.json",
    "delegation_grant": "delegation-grant.schema.json",
    "approval_attestation": "approval-attestation.schema.json",
    "rule_definition_revision": "rule-definition.schema.json",
    "applied_change": "applied-change.schema.json",
    "provenance_record": "provenance.schema.json",
    "audit_anchor": "audit-anchor.schema.json",
}

_OPERATION_RESOURCE_TYPES = {
    OperationType.CREATE_LOGICAL_OBJECT: frozenset({"logical_object"}),
    OperationType.CREATE_REVISION: frozenset({"revision"}),
    OperationType.SET_DISPOSITION: frozenset({"immutable_record"}),
    OperationType.ASSERT_RELATION: frozenset({"relation_assertion_revision"}),
    OperationType.RETIRE_RELATION: frozenset({"immutable_record"}),
    OperationType.CREATE_RECORD: frozenset({"immutable_record"}),
    OperationType.RETRACT_RECORD: frozenset({"immutable_record"}),
    OperationType.CREATE_DEVIATION: frozenset({"revision", "immutable_record"}),
    OperationType.REVOKE_DEVIATION: frozenset({"immutable_record"}),
    OperationType.UPDATE_PROFILE_BINDING: frozenset({"profile_revision"}),
    OperationType.CREATE_CONFIGURATION: frozenset({"configuration_snapshot"}),
    OperationType.CREATE_BASELINE: frozenset({"baseline_manifest"}),
    OperationType.PROMOTE_FRAGMENT: frozenset({"logical_object", "revision", "immutable_record"}),
    OperationType.SPLIT_OBJECT: frozenset({"logical_object", "revision", "immutable_record"}),
    OperationType.CONSOLIDATE_OBJECT: frozenset({"logical_object", "revision", "immutable_record"}),
    OperationType.REGISTER_TRUSTED_ACTOR: frozenset({"trusted_actor"}),
    OperationType.CREATE_DELEGATION: frozenset({"delegation_grant"}),
    OperationType.RECORD_APPROVAL: frozenset({"approval_attestation"}),
    OperationType.CREATE_RULE: frozenset({"rule_definition_revision"}),
}


class GitCanonicalRepository:
    CANONICAL_REF = "refs/heads/lesr/canonical"

    def __init__(self, path: Path) -> None:
        self.path = path.resolve()
        self.schemas = SchemaCatalog()

    def initialize(self) -> str:
        self.path.mkdir(parents=True, exist_ok=True)
        if not (self.path / ".git").exists():
            self._git("init", "--quiet")
            self._git("config", "user.name", "LESR Runtime")
            self._git("config", "user.email", "lesr-runtime@invalid.local")
        existing = self._try_git("rev-parse", "--verify", self.CANONICAL_REF)
        if existing is not None:
            return existing
        tree = self._git("mktree", input_text="")
        commit = self._commit_tree(tree, (), "Initialize LESR canonical state")
        self._git("update-ref", self.CANONICAL_REF, commit)
        return commit

    def current_commit(self) -> str:
        return self._git("rev-parse", "--verify", self.CANONICAL_REF)

    def is_ancestor(self, ancestor: str, descendant: str) -> bool:
        result = subprocess.run(
            ["git", "-C", str(self.path), "merge-base", "--is-ancestor", ancestor, descendant],
            check=False,
            capture_output=True,
        )
        return result.returncode == 0

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
        idempotency_hash = semantic_hash({"idempotency_key": transaction.idempotency_key})
        idempotency_path = (
            f"canonical/idempotency/{idempotency_hash.removeprefix('sha256:')}.json"
        )
        previous = self.read_json(current, idempotency_path)
        if previous is not None:
            if previous.get("transaction_hash") != transaction_hash:
                raise IdempotencyConflict(
                    "the idempotency key was already used for a different transaction"
                )
            original_commit = self._git(
                "log",
                current,
                "--diff-filter=A",
                "--format=%H",
                "--reverse",
                "--",
                idempotency_path,
            ).splitlines()[0]
            return ApplyResult(original_commit, transaction_hash, True, False)
        if current != transaction.base_commit:
            raise ConcurrencyConflict(
                f"canonical base changed: expected {transaction.base_commit}, got {current}"
            )
        self._verify_expected_revisions(current, transaction.expected_revisions)
        state_operations = tuple(
            item
            for item in transaction.operations
            if item.operation_type is not OperationType.RECORD_APPROVAL
        )
        snapshot_operations = tuple(
            item
            for item in state_operations
            if item.operation_type
            in {OperationType.CREATE_CONFIGURATION, OperationType.CREATE_BASELINE}
        )
        if snapshot_operations:
            if len(state_operations) != 1:
                raise IntegrityError(
                    "configuration/baseline snapshot must be a dedicated semantic transaction"
                )
            if snapshot_operations[0].payload.get("git_commit") != current:
                raise IntegrityError("snapshot must pin the exact pre-snapshot canonical commit")
        for operation in transaction.operations:
            safe_path = self._safe_path(operation.relative_path)
            self._validate_operation(operation)
            if self.read_bytes(current, safe_path) is not None:
                raise IntegrityError(f"immutable canonical resource already exists: {safe_path}")
        self._validate_candidate(current, transaction.operations)

        index_path = self.path / f".lesr-index-{uuid7_candidate()}.tmp"
        index_path.unlink(missing_ok=True)
        env = {"GIT_INDEX_FILE": str(index_path)}
        try:
            self._git("read-tree", current, extra_env=env)
            for operation in transaction.operations:
                content = (canonical_json(operation.payload) + "\n").encode("utf-8")
                self._stage_bytes(self._safe_path(operation.relative_path), content, env)
            applied_at = self._utc_now()
            provenance_record = self._provenance_record(transaction, applied_at)
            audit_record = self._audit_record(
                current,
                transaction,
                transaction_hash,
                applied_at,
            )
            change_record = self._change_record(
                transaction,
                transaction_hash,
                idempotency_hash,
                applied_at,
            )
            for schema_name, record in (
                ("applied-change.schema.json", change_record),
                ("provenance.schema.json", provenance_record),
                ("audit-anchor.schema.json", audit_record),
            ):
                try:
                    self.schemas.validate(schema_name, record)
                except JsonSchemaValidationError as error:
                    raise IntegrityError(
                        f"generated canonical record is invalid: {error.message}"
                    ) from error
            self._stage_json(
                f"canonical/applied_changes/{transaction.transaction_uid}.json",
                change_record,
                env,
            )
            self._stage_json(
                f"canonical/provenance/{transaction.transaction_uid}.json",
                provenance_record,
                env,
            )
            self._stage_json(
                f"canonical/audit_anchors/{transaction.transaction_uid}.json",
                audit_record,
                env,
            )
            self._stage_json(
                idempotency_path,
                {
                    "idempotency_key_hash": idempotency_hash,
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
            reference = f"refs/lesr/workspaces/{workspace}"
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
                "DROP TABLE IF EXISTS projection_meta;"
                "DROP TABLE IF EXISTS documents;"
                "DROP TABLE IF EXISTS documents_fts;"
                "DROP TABLE IF EXISTS resources;"
                "DROP TABLE IF EXISTS aliases;"
                "DROP TABLE IF EXISTS relations;"
                "CREATE TABLE projection_meta (source_commit TEXT NOT NULL, "
                "schema_version TEXT NOT NULL, completeness TEXT NOT NULL);"
                "CREATE TABLE documents (path TEXT PRIMARY KEY, json TEXT NOT NULL, "
                "source_commit TEXT NOT NULL);"
                "CREATE VIRTUAL TABLE documents_fts USING fts5(path UNINDEXED, content);"
                "CREATE TABLE resources (uid TEXT NOT NULL, resource_type TEXT NOT NULL, "
                "object_uid TEXT, human_key TEXT, kind TEXT, revision_number INTEGER, path TEXT PRIMARY KEY, json TEXT NOT NULL);"
                "CREATE INDEX resources_uid_idx ON resources(uid);"
                "CREATE TABLE aliases (alias TEXT NOT NULL, uid TEXT NOT NULL, UNIQUE(alias, uid));"
                "CREATE TABLE relations (relation_revision_uid TEXT PRIMARY KEY, assertion_uid TEXT NOT NULL, "
                "predicate TEXT NOT NULL, source_object_uid TEXT, target_object_uid TEXT, path TEXT NOT NULL);"
            )
            rows: list[tuple[str, str, str]] = []
            resource_rows: list[tuple[object, ...]] = []
            alias_rows: list[tuple[str, str]] = []
            relation_rows: list[tuple[object, ...]] = []
            for path, blob in self._tree_entries(source_commit):
                if not path.startswith("canonical/"):
                    continue
                if not path.endswith(".json"):
                    continue
                content = self._read_blob(blob)
                rows.append((path, content.decode("utf-8"), source_commit))
                document = json.loads(content)
                if not isinstance(document, dict) or "resource_type" not in document:
                    continue
                uid = self._document_uid(document)
                if uid is not None:
                    resource_rows.append(
                        (
                            uid,
                            str(document["resource_type"]),
                            document.get("object_uid"),
                            document.get("human_key"),
                            document.get("kind"),
                            document.get("revision_number"),
                            path,
                            content.decode("utf-8"),
                        )
                    )
                if document.get("resource_type") == "logical_object" and uid is not None:
                    alias_rows.extend(
                        (str(alias["value"]), uid)
                        for alias in document.get("aliases", [])
                        if isinstance(alias, dict) and isinstance(alias.get("value"), str)
                    )
                if document.get("resource_type") == "relation_assertion_revision":
                    source = document.get("source", {})
                    target = document.get("target", {})
                    relation_rows.append(
                        (
                            document["relation_revision_uid"],
                            document["assertion_uid"],
                            document["predicate"],
                            source.get("object_uid") if isinstance(source, dict) else None,
                            target.get("object_uid") if isinstance(target, dict) else None,
                            path,
                        )
                    )
            connection.executemany("INSERT INTO documents VALUES (?, ?, ?)", rows)
            connection.executemany("INSERT INTO resources VALUES (?, ?, ?, ?, ?, ?, ?, ?)", resource_rows)
            connection.executemany("INSERT INTO aliases VALUES (?, ?)", alias_rows)
            connection.executemany("INSERT INTO relations VALUES (?, ?, ?, ?, ?, ?)", relation_rows)
            connection.executemany(
                "INSERT INTO documents_fts VALUES (?, ?)",
                ((path, content) for path, content, _ in rows),
            )
            connection.execute(
                "INSERT INTO projection_meta VALUES (?, '1.0', 'complete')",
                (source_commit,),
            )
        return source_commit

    def read_json(self, commit: str, path: str) -> dict[str, Any] | None:
        content = self.read_bytes(commit, path)
        if content is None:
            return None
        value = json.loads(content)
        if not isinstance(value, dict):
            raise IntegrityError(f"expected JSON object at {path}")
        return value

    def documents(self, commit: str | None = None) -> tuple[tuple[str, dict[str, Any]], ...]:
        """Read every Canonical JSON document from one exact commit."""
        selected = commit or self.current_commit()
        documents: list[tuple[str, dict[str, Any]]] = []
        for path, blob in self._tree_entries(selected):
            if path.startswith("canonical/") and path.endswith(".json"):
                value = json.loads(self._read_blob(blob))
                if not isinstance(value, dict):
                    raise IntegrityError(f"expected JSON object at {path}")
                documents.append((path, value))
        return tuple(documents)

    def read_bytes(self, commit: str, path: str) -> bytes | None:
        normalized = PurePosixPath(path).as_posix()
        blob = next(
            (blob for actual, blob in self._tree_entries(commit) if actual == normalized),
            None,
        )
        return self._read_blob(blob) if blob is not None else None

    def checkpoint_payload(self, checkpoint: CheckpointResult) -> dict[str, Any]:
        actual = next(
            path
            for path, _ in self._tree_entries(checkpoint.commit)
            if path.startswith("workspaces/")
            and path.endswith(f"/{checkpoint.checkpoint_uid}.json")
        )
        value = self.read_json(checkpoint.commit, actual)
        if value is None:
            raise IntegrityError("checkpoint payload is missing")
        return value

    def recover_workspaces(self) -> tuple[dict[str, Any], ...]:
        """Recover the newest checkpoint for every persistent workspace ref."""
        refs = self._try_git("for-each-ref", "--format=%(refname) %(objectname)", "refs/lesr/workspaces/")
        if not refs:
            return ()
        recovered: list[dict[str, Any]] = []
        for line in refs.splitlines():
            reference, commit = line.split(" ", 1)
            candidates = [
                path
                for path, _ in self._tree_entries(commit)
                if path.startswith("workspaces/") and "/checkpoints/" in path
            ]
            if not candidates:
                continue
            latest = max(candidates)
            payload = self.read_json(commit, latest)
            if payload is not None:
                recovered.append(payload | {"git_reference": reference})
        return tuple(recovered)

    def verify_audit_chain(self, commit: str | None = None) -> bool:
        anchors = [
            value
            for path, value in self.documents(commit or self.current_commit())
            if path.startswith("canonical/audit_anchors/")
        ]
        by_previous: dict[str | None, list[dict[str, Any]]] = {}
        for anchor in anchors:
            anchor_previous = anchor.get("previous_anchor_hash")
            key = str(anchor_previous) if anchor_previous is not None else None
            by_previous.setdefault(key, []).append(anchor)
        previous: str | None = None
        visited = 0
        while visited < len(anchors):
            candidates = by_previous.get(previous, [])
            if len(candidates) != 1:
                return False
            anchor = candidates[0]
            if anchor.get("anchor_hash") != document_hash(anchor, "anchor_hash"):
                return False
            previous = str(anchor["anchor_hash"])
            visited += 1
        return visited == len(anchors)

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

    def _validate_operation(self, operation: SemanticOperation) -> None:
        resource_type = operation.payload.get("resource_type")
        if not isinstance(resource_type, str):
            raise IntegrityError("semantic operation payload has no resource_type")
        allowed = _OPERATION_RESOURCE_TYPES.get(operation.operation_type, frozenset())
        if resource_type not in allowed:
            raise IntegrityError(
                f"{operation.operation_type} cannot create {resource_type}"
            )
        schema_name = _RESOURCE_SCHEMAS.get(resource_type)
        if schema_name is None:
            raise IntegrityError(f"unsupported canonical resource type: {resource_type}")
        try:
            self.schemas.validate(schema_name, operation.payload)
        except JsonSchemaValidationError as error:
            raise IntegrityError(f"canonical schema validation failed: {error.message}") from error
        hash_field = "manifest_hash" if resource_type == "baseline_manifest" else "content_hash"
        if hash_field in operation.payload:
            expected_hash = document_hash(operation.payload, hash_field)
            if operation.payload[hash_field] != expected_hash:
                raise IntegrityError(f"canonical {hash_field} does not match document content")
        expected_path = self._resource_path(operation.payload)
        if self._safe_path(operation.relative_path) != expected_path:
            raise IntegrityError(
                f"canonical path does not match resource identity: expected {expected_path}"
            )

    def _validate_candidate(
        self, commit: str, operations: tuple[SemanticOperation, ...]
    ) -> None:
        documents = {path: value for path, value in self.documents(commit)}
        documents.update((operation.relative_path, operation.payload) for operation in operations)
        objects = {
            str(value["entity_uid"])
            for value in documents.values()
            if value.get("resource_type") == "logical_object"
        }
        revisions = {
            str(value["revision_uid"]): str(value["object_uid"])
            for value in documents.values()
            if value.get("resource_type") == "revision"
        }
        relation_revisions = {
            str(value["relation_revision_uid"])
            for value in documents.values()
            if value.get("resource_type") == "relation_assertion_revision"
        }
        profiles = {
            str(value["profile_revision_uid"])
            for value in documents.values()
            if value.get("resource_type") == "profile_revision"
        }
        rules = {
            str(value["rule_revision_uid"])
            for value in documents.values()
            if value.get("resource_type") == "rule_definition_revision"
        }
        configurations = {
            str(value["configuration_uid"])
            for value in documents.values()
            if value.get("resource_type") == "configuration_snapshot"
        }
        for path, value in documents.items():
            resource_type = value.get("resource_type")
            if resource_type is None:
                if not path.startswith("canonical/idempotency/"):
                    raise IntegrityError(f"canonical document has no resource_type: {path}")
                continue
            schema_name = _RESOURCE_SCHEMAS.get(str(resource_type))
            if schema_name is None:
                raise IntegrityError(f"unsupported canonical resource type: {resource_type}")
            try:
                self.schemas.validate(schema_name, value)
            except JsonSchemaValidationError as error:
                raise IntegrityError(
                    f"canonical candidate contains invalid {path}: {error.message}"
                ) from error
            hash_field = {
                "baseline_manifest": "manifest_hash",
                "audit_anchor": "anchor_hash",
            }.get(str(resource_type), "content_hash")
            if hash_field in value and value[hash_field] != document_hash(value, hash_field):
                raise IntegrityError(f"canonical candidate contains invalid hash: {path}")
            if resource_type == "revision" and value["object_uid"] not in objects:
                raise IntegrityError(f"revision references missing object: {value['object_uid']}")
            if resource_type == "relation_assertion_revision":
                for endpoint_name in ("source", "target"):
                    endpoint = value[endpoint_name]
                    if endpoint["binding"] != "external" and endpoint["object_uid"] not in objects:
                        raise IntegrityError(
                            f"relation {endpoint_name} references missing object: {endpoint['object_uid']}"
                        )
                    pinned = endpoint.get("revision_uid")
                    if pinned is not None and revisions.get(pinned) != endpoint.get("object_uid"):
                        raise IntegrityError(
                            f"relation {endpoint_name} references incompatible revision: {pinned}"
                        )
            if resource_type in {"configuration_snapshot", "baseline_manifest"}:
                missing_revisions = set(value.get("revision_uids", [])) - set(revisions)
                missing_relations = set(value.get("relation_revision_uids", [])) - relation_revisions
                missing_profiles = set(value.get("profile_revision_uids", [])) - profiles
                if missing_revisions or missing_relations or missing_profiles:
                    raise IntegrityError(
                        "snapshot closure references unavailable canonical revisions"
                    )
            if resource_type == "profile_revision":
                missing_rules = set(value.get("rule_revision_uids", [])) - rules
                if missing_rules:
                    raise IntegrityError("profile references unavailable rule revisions")
            if resource_type == "baseline_manifest" and value["configuration_uid"] not in configurations:
                raise IntegrityError("baseline references unavailable configuration")

    @staticmethod
    def _document_uid(document: dict[str, Any]) -> str | None:
        for name in (
            "entity_uid", "revision_uid", "relation_revision_uid", "record_uid",
            "profile_revision_uid", "configuration_uid", "baseline_uid", "actor_uid",
            "delegation_uid", "transaction_uid", "provenance_uid", "anchor_uid",
        ):
            value = document.get(name)
            if isinstance(value, str):
                return value
        return None

    @staticmethod
    def _resource_path(resource: dict[str, Any]) -> str:
        resource_type = resource["resource_type"]
        mapping = {
            "logical_object": f"canonical/objects/{resource.get('entity_uid')}.json",
            "revision": f"canonical/revisions/{resource.get('revision_uid')}.json",
            "immutable_record": f"canonical/records/{resource.get('record_type')}/{resource.get('record_uid')}.json",
            "profile_revision": f"canonical/profiles/{resource.get('profile_revision_uid')}.json",
            "configuration_snapshot": f"canonical/configurations/{resource.get('configuration_uid')}.json",
            "baseline_manifest": f"canonical/baselines/{resource.get('baseline_uid')}.json",
            "trusted_actor": f"canonical/trust/{resource.get('actor_uid')}/{resource.get('key_uid')}.json",
            "delegation_grant": f"canonical/delegations/{resource.get('delegation_uid')}.json",
            "approval_attestation": f"canonical/approvals/{resource.get('approval_uid')}.json",
            "rule_definition_revision": f"canonical/rules/{resource.get('rule_revision_uid')}.json",
        }
        if resource_type == "relation_assertion_revision":
            return (
                f"canonical/relations/{resource['assertion_uid']}/revisions/"
                f"{resource['relation_revision_uid']}.json"
            )
        try:
            return GitCanonicalRepository._safe_path(mapping[resource_type])
        except KeyError as error:
            raise IntegrityError(f"unsupported canonical resource type: {resource_type}") from error

    @staticmethod
    def _validate_transaction(transaction: SemanticTransaction) -> None:
        identifiers = {
            "transaction_uid": transaction.transaction_uid,
            "actor": transaction.actor,
            "delegation_uid": transaction.delegation_uid,
        }
        identifiers.update(
            {f"approval[{index}]": item.approval_uid for index, item in enumerate(transaction.approvals)}
        )
        for name, value in identifiers.items():
            if not re.fullmatch(
                r"[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}",
                value,
            ):
                raise IntegrityError(f"{name} must be a UUIDv7")
        for name, value in (
            ("effective_model_hash", transaction.effective_model_hash),
            ("review_package_hash", transaction.review_package_hash),
        ):
            if not re.fullmatch(r"sha256:[0-9a-f]{64}", value):
                raise IntegrityError(f"{name} must be a SHA-256 digest")
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
        transaction: SemanticTransaction,
        transaction_hash: str,
        idempotency_hash: str,
        applied_at: str,
    ) -> dict[str, Any]:
        return {
            "schema_version": "1.0",
            "resource_type": "applied_change",
            "transaction_uid": transaction.transaction_uid,
            "transaction_hash": transaction_hash,
            "base_commit": transaction.base_commit,
            "expected_revisions": [
                {"revision_uid": revision_uid, "content_hash": content_hash}
                for revision_uid, content_hash in transaction.expected_revisions
            ],
            "effective_model_hash": transaction.effective_model_hash,
            "review_package_hash": transaction.review_package_hash,
            "operation_hashes": [
                semantic_hash(
                    {
                        "operation_type": item.operation_type,
                        "relative_path": item.relative_path,
                        "payload": item.payload,
                    }
                )
                for item in transaction.operations
            ],
            "approval_uids": [item.approval_uid for item in transaction.approvals],
            "provenance_uids": [transaction.transaction_uid],
            "audit_anchor_uid": transaction.transaction_uid,
            "actor_uid": transaction.actor,
            "delegation_uid": transaction.delegation_uid,
            "idempotency_key_hash": idempotency_hash,
            "applied_at": applied_at,
        }

    @staticmethod
    def _provenance_record(
        transaction: SemanticTransaction, generated_at: str
    ) -> dict[str, Any]:
        record: dict[str, Any] = {
            "schema_version": "1.0",
            "resource_type": "provenance_record",
            "provenance_uid": transaction.transaction_uid,
            "subject_uid": transaction.transaction_uid,
            "kind": "generated",
            "responsible_actor_uid": transaction.actor,
            "tool_uids": ["018f0000-0000-7000-8000-000000000099"],
            "delegation_uid": transaction.delegation_uid,
            "source_uids": sorted(
                {
                    uid
                    for operation in transaction.operations
                    for uid in (
                        operation.payload.get("entity_uid"),
                        operation.payload.get("object_uid"),
                        operation.payload.get("revision_uid"),
                        operation.payload.get("relation_revision_uid"),
                        operation.payload.get("record_uid"),
                        operation.payload.get("profile_revision_uid"),
                        operation.payload.get("rule_revision_uid"),
                        operation.payload.get("configuration_uid"),
                        operation.payload.get("baseline_uid"),
                    )
                    if isinstance(uid, str)
                }
            ),
            "generated_at": generated_at,
        }
        record["content_hash"] = semantic_hash(record)
        return record

    def _audit_record(
        self,
        commit: str,
        transaction: SemanticTransaction,
        transaction_hash: str,
        created_at: str,
    ) -> dict[str, Any]:
        previous_hash: str | None = None
        previous = [
            value
            for path, value in self.documents(commit)
            if path.startswith("canonical/audit_anchors/")
        ]
        if previous:
            hashes = {
                str(item["anchor_hash"])
                for item in previous
                if isinstance(item.get("anchor_hash"), str)
            }
            referenced = {
                str(item["previous_anchor_hash"])
                for item in previous
                if isinstance(item.get("previous_anchor_hash"), str)
            }
            tails = hashes - referenced
            if len(tails) != 1:
                raise IntegrityError("existing audit anchor chain has no unique tail")
            previous_hash = next(iter(tails))
        record: dict[str, Any] = {
            "schema_version": "1.0",
            "resource_type": "audit_anchor",
            "anchor_uid": transaction.transaction_uid,
            "transaction_uid": transaction.transaction_uid,
            "previous_anchor_hash": previous_hash,
            "event_hashes": [
                transaction_hash,
                *(
                    semantic_hash(
                        {
                            "approval_uid": approval.approval_uid,
                            "actor": approval.actor,
                            "approval_type": approval.approval_type,
                        }
                    )
                    for approval in transaction.approvals
                ),
            ],
            "created_at": created_at,
        }
        record["anchor_hash"] = semantic_hash(record)
        return record

    @staticmethod
    def _utc_now() -> str:
        return datetime.now(UTC).isoformat().replace("+00:00", "Z")

    def _stage_json(self, path: str, value: dict[str, Any], env: dict[str, str]) -> None:
        self._stage_bytes(path, (canonical_json(value) + "\n").encode("utf-8"), env)

    def _stage_bytes(self, path: str, content: bytes, env: dict[str, str]) -> None:
        blob = self._git("hash-object", "-w", "--stdin", input_bytes=content)
        entry = f"100644 {blob}\t".encode("ascii") + path.encode("utf-8") + b"\0"
        self._git(
            "update-index", "-z", "--index-info", input_bytes=entry, extra_env=env
        )

    def _tree_entries(self, commit: str) -> tuple[tuple[str, str], ...]:
        result = subprocess.run(
            ["git", "-C", str(self.path), "ls-tree", "-r", "-z", commit],
            check=False,
            capture_output=True,
        )
        if result.returncode != 0:
            raise CanonicalError(
                f"git ls-tree failed: {result.stderr.decode('utf-8', errors='replace').strip()}"
            )
        entries: list[tuple[str, str]] = []
        for record in result.stdout.split(b"\0"):
            if not record:
                continue
            metadata, raw_path = record.split(b"\t", 1)
            _, object_type, object_id = metadata.split(b" ", 2)
            if object_type == b"blob":
                entries.append((raw_path.decode("utf-8"), object_id.decode("ascii")))
        return tuple(entries)

    def _read_blob(self, blob: str) -> bytes:
        result = subprocess.run(
            ["git", "-C", str(self.path), "cat-file", "blob", blob],
            check=False,
            capture_output=True,
        )
        if result.returncode != 0:
            raise CanonicalError(
                f"git cat-file failed: {result.stderr.decode('utf-8', errors='replace').strip()}"
            )
        return result.stdout

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
                "GIT_AUTHOR_NAME": "LESR Runtime",
                "GIT_AUTHOR_EMAIL": "lesr-runtime@invalid.local",
                "GIT_COMMITTER_NAME": "LESR Runtime",
                "GIT_COMMITTER_EMAIL": "lesr-runtime@invalid.local",
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
