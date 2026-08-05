"""Repository-backed LESR capabilities over one exact Canonical Git commit."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from jsonschema.exceptions import ValidationError as JsonSchemaValidationError

from lesr.adapters.git import (
    ApprovalAttestation,
    CheckpointStrategy,
    GitCanonicalRepository,
    OperationType,
    SemanticOperation,
    SemanticTransaction,
)
from lesr.adapters.schemas import SchemaCatalog
from lesr.application.context import (
    ClosureStatus,
    ConfigurationDefinition,
    ConfigurationMembership,
    ContextPlanner,
    ContextPolicy,
    ContextRelation,
    ContextResource,
    EffectiveResolver,
    EffectiveRuleReference,
    EvaluationContext,
    RevisionDescriptor,
)
from lesr.application.contracts import (
    CapabilityDescriptor,
    CapabilityGroup,
    DomainErrorContract,
    DomainResult,
    ErrorCategory,
    LongTask,
    RiskClass,
    TaskState,
    WriteEnvelope,
)
from lesr.domain.approval import SignedApproval, TrustedActor, verify_approval
from lesr.domain.profiles import EffectiveModel, ProfileCompiler, ProfileRevision
from lesr.domain.rules import RuleDefinition
from lesr.domain.semantic import document_hash, semantic_hash, uuid7_candidate


class RepositoryDomainService:
    """Domain service that never inherits the adapter-only in-memory test double."""

    def __init__(self, project: Path) -> None:
        self.repository = GitCanonicalRepository(project)
        self.schemas = SchemaCatalog()
        self.repository.initialize()
        self.projection = project / ".lesr" / "projection.sqlite3"
        self.workspaces: dict[str, dict[str, Any]] = {}
        self.tasks: dict[str, LongTask] = {}
        self.reload()

    def reload(self) -> None:
        self.base = self.repository.current_commit()
        self.documents = self.repository.documents(self.base)
        self.by_type: dict[str, list[dict[str, Any]]] = {}
        self.by_uid: dict[str, dict[str, Any]] = {}
        for _, document in self.documents:
            resource_type = document.get("resource_type")
            if isinstance(resource_type, str):
                self.by_type.setdefault(resource_type, []).append(document)
            primary_field = _PRIMARY_UID_FIELDS.get(str(resource_type))
            uid = document.get(primary_field) if primary_field else None
            if isinstance(uid, str):
                self.by_uid[uid] = document
        self.workspaces = {
            str(item["workspace_uid"]): dict(item.get("working_state", {}))
            | {
                "workspace_uid": item["workspace_uid"],
                "base": item["base_commit"],
                "git_reference": item["git_reference"],
            }
            for item in self.repository.recover_workspaces()
        }
        self._ensure_projection()
        self._validate_configured_models()

    def capabilities(self) -> tuple[CapabilityDescriptor, ...]:
        return (
            CapabilityDescriptor(CapabilityGroup.RESOLVE, ("resolve",)),
            CapabilityDescriptor(CapabilityGroup.INSPECT, ("inspect",)),
            CapabilityDescriptor(CapabilityGroup.QUERY, ("query",)),
            CapabilityDescriptor(CapabilityGroup.CONTEXT, ("build_context",)),
            CapabilityDescriptor(
                CapabilityGroup.WORKSPACE, ("open_workspace", "propose_operation")
            ),
            CapabilityDescriptor(CapabilityGroup.GOVERNANCE, ("apply_transaction",)),
            CapabilityDescriptor(
                CapabilityGroup.COMPLIANCE,
                ("compile_effective_model", "verify_audit_chain"),
            ),
        )

    def resolve(self, identifier: str) -> DomainResult:
        matches = []
        for item in self.by_type.get("logical_object", []):
            aliases = {
                alias["value"]
                for alias in item.get("aliases", [])
                if isinstance(alias, dict) and isinstance(alias.get("value"), str)
            }
            if identifier in {item["entity_uid"], item["human_key"], *aliases}:
                matches.append(item)
        if not matches:
            return self._error(
                "LESR-NOT-FOUND",
                ErrorCategory.NOT_FOUND,
                f"identifier was not resolved: {identifier}",
                (identifier,),
                suggested="query",
            )
        if len(matches) != 1:
            return self._error(
                "LESR-IDENTIFIER-AMBIGUOUS",
                ErrorCategory.INDETERMINATE,
                "identifier is ambiguous",
                tuple(str(item["entity_uid"]) for item in matches),
            )
        logical = matches[0]
        revisions = sorted(
            (
                item
                for item in self.by_type.get("revision", [])
                if item["object_uid"] == logical["entity_uid"]
            ),
            key=lambda item: int(item["revision_number"]),
        )
        result: dict[str, Any] = {
            "uid": logical["entity_uid"],
            "human_key": logical["human_key"],
            "aliases": sorted(
                alias["value"] for alias in logical.get("aliases", [])
            ),
            "kind": logical["kind"],
            "canonical": logical,
            "resolution": "logical_object",
        }
        if len(revisions) == 1:
            result |= {
                "revision_uid": revisions[0]["revision_uid"],
                "revision": revisions[0],
                "revision_resolution": "only_available_revision",
            }
        elif len(revisions) > 1:
            result |= {
                "revision_uid": None,
                "revision_resolution": "indeterminate_context_required",
                "candidate_revision_uids": [item["revision_uid"] for item in revisions],
            }
        return DomainResult(result)

    def inspect(self, uid: str) -> DomainResult:
        document = self.by_uid.get(uid)
        if document is None:
            return self._error(
                "LESR-NOT-FOUND", ErrorCategory.NOT_FOUND, "resource not found", (uid,)
            )
        return DomainResult(document)

    def query(self, kind: str | None, cursor: str | None, page_size: int) -> DomainResult:
        if not 1 <= page_size <= 100:
            return self._error(
                "LESR-PAGE-SIZE-INVALID",
                ErrorCategory.VALIDATION,
                "page_size must be between 1 and 100",
            )
        try:
            offset = int(cursor or "0")
        except ValueError:
            return self._error(
                "LESR-CURSOR-INVALID", ErrorCategory.VALIDATION, "cursor is invalid"
            )
        with sqlite3.connect(self.projection) as connection:
            where = "WHERE kind = ? OR resource_type = ?" if kind else ""
            parameters: tuple[object, ...] = (kind, kind) if kind else ()
            total = int(
                connection.execute(
                    f"SELECT count(*) FROM resources {where}", parameters
                ).fetchone()[0]
            )
            rows = connection.execute(
                f"SELECT json FROM resources {where} ORDER BY uid LIMIT ? OFFSET ?",
                parameters + (page_size, offset),
            ).fetchall()
        items = [json.loads(row[0]) for row in rows]
        next_cursor = str(offset + page_size) if offset + page_size < total else None
        return DomainResult({"items": items, "next_cursor": next_cursor, "total": total})

    def build_context(
        self, task_type: str, target_uids: tuple[str, ...], token_budget: int
    ) -> DomainResult:
        configurations = self.by_type.get("configuration_snapshot", [])
        if len(configurations) != 1:
            return self._error(
                "LESR-CONTEXT-CONFIGURATION-REQUIRED",
                ErrorCategory.INDETERMINATE,
                "context requires exactly one explicit configuration snapshot",
                tuple(str(item["configuration_uid"]) for item in configurations),
                suggested="resolve",
            )
        configuration_doc = configurations[0]
        revisions = tuple(
            RevisionDescriptor(
                str(item["object_uid"]),
                str(item["revision_uid"]),
                int(item["revision_number"]),
                self._maturity(str(item["revision_uid"])),
            )
            for item in self.by_type.get("revision", [])
        )
        revision_by_uid = {item.revision_uid: item for item in revisions}
        memberships = tuple(
            ConfigurationMembership(revision_by_uid[uid].object_uid, uid)
            for uid in configuration_doc["revision_uids"]
            if uid in revision_by_uid
        )
        configuration = ConfigurationDefinition(
            str(configuration_doc["configuration_uid"]),
            str(configuration_doc["git_commit"]),
            memberships,
            tuple(str(item) for item in configuration_doc["profile_revision_uids"]),
            str(configuration_doc["effective_model_hash"]),
            tuple(str(item) for item in configuration_doc["active_deviation_revision_uids"]),
            ClosureStatus(str(configuration_doc["closure_status"])),
        )
        context = EvaluationContext(
            repository=str(self.repository.path),
            project=self.repository.path.name,
            operation=task_type,
            actor="context-reader",
            target_object_uids=target_uids,
            configuration_uid=configuration.configuration_uid,
        )
        resolution = EffectiveResolver().resolve(context, revisions, configuration)
        resources = tuple(
            ContextResource(
                str(item["object_uid"]),
                str(item["revision_uid"]),
                str(item["kind"]),
                str(item.get("human_key", item["revision_uid"])),
                max(1, len(json.dumps(item, ensure_ascii=False)) // 4),
                self._field(item, "/sensitivity", "internal"),
            )
            for item in self.by_type.get("revision", [])
        )
        relations = tuple(
            ContextRelation(
                str(item["source"].get("object_uid", "")),
                str(item["predicate"]),
                str(item["target"].get("object_uid", "")),
            )
            for item in self.by_type.get("relation_assertion_revision", [])
            if item["source"].get("object_uid") and item["target"].get("object_uid")
        )
        contract = ContextPlanner().build(
            task_type=task_type,
            resolution=resolution,
            resources=resources,
            relations=relations,
            rules=self._context_rules(configuration),
            policy=ContextPolicy(frozenset(), frozenset(item.predicate for item in relations)),
            token_budget=token_budget,
            configuration=configuration,
        )
        return DomainResult(asdict(contract))

    def open_workspace(self, request: WriteEnvelope) -> DomainResult:
        error = self._validate_write(request, "open_workspace", require_workspace=False)
        if error is not None:
            return error
        workspace = {
            "workspace_uid": request.workspace_uid,
            "base": request.expected_base,
            "state": "open",
            "delegation_uid": request.delegation_uid,
            "operations": [],
        }
        if request.dry_run:
            return DomainResult(workspace)
        checkpoint = self.repository.create_checkpoint(
            request.workspace_uid, workspace, CheckpointStrategy.WORKSPACE_REF
        )
        workspace |= {
            "checkpoint_uid": checkpoint.checkpoint_uid,
            "git_reference": checkpoint.git_reference,
        }
        self.workspaces[request.workspace_uid] = workspace
        return DomainResult(workspace)

    def propose_operation(self, request: WriteEnvelope) -> DomainResult:
        error = self._validate_write(request, "propose_operation", require_workspace=True)
        if error is not None:
            return error
        try:
            operation = self._operation(request.operation)
        except (JsonSchemaValidationError, KeyError, TypeError, ValueError) as exc:
            return self._error(
                "LESR-OPERATION-INVALID", ErrorCategory.VALIDATION, str(exc)
            )
        if request.dry_run:
            return DomainResult({"workspace_uid": request.workspace_uid, "operation": request.operation})
        self.workspaces[request.workspace_uid]["operations"].append(request.operation)
        checkpoint = self.repository.create_checkpoint(
            request.workspace_uid,
            self.workspaces[request.workspace_uid],
            CheckpointStrategy.WORKSPACE_REF,
        )
        return DomainResult(
            {
                "workspace_uid": request.workspace_uid,
                "operation_hash": semantic_hash(
                    {
                        "operation_type": operation.operation_type,
                        "resource": operation.payload,
                    }
                ),
                "checkpoint_uid": checkpoint.checkpoint_uid,
                "git_reference": checkpoint.git_reference,
            }
        )

    def apply_transaction(self, request: WriteEnvelope) -> DomainResult:
        error = self._validate_write(request, "apply_transaction", require_workspace=True)
        if error is not None:
            return error
        try:
            review_package = self._dict(request.operation["review_package"])
            self.schemas.validate("review-package.schema.json", review_package)
            package_hash = str(review_package["package_hash"])
            effective_model_hash = str(request.operation["effective_model_hash"])
            raw_operations = self._list(request.operation["operations"])
            operations = tuple(self._operation(item) for item in raw_operations)
            self._validate_review_package(
                request, review_package, package_hash, effective_model_hash, raw_operations
            )
            raw_approvals = request.operation.get("signed_approvals")
            if raw_approvals is None and "signed_approval" in request.operation:
                raw_approvals = [request.operation["signed_approval"]]
            approvals = tuple(
                SignedApproval.model_validate(item) for item in self._list(raw_approvals)
            )
            attestations, approval_operations = self._verify_approvals(
                approvals, review_package, package_hash, effective_model_hash, operations
            )
            expected = tuple(
                (str(item["revision_uid"]), str(item["content_hash"]))
                for item in self._list(request.operation.get("expected_revisions", []))
            )
        except (
            JsonSchemaValidationError,
            KeyError,
            TypeError,
            ValueError,
            PermissionError,
        ) as exc:
            return self._error(
                "LESR-APPROVAL-INVALID",
                ErrorCategory.AUTHORIZATION,
                str(exc),
                (request.workspace_uid,),
                suggested="approval.sign",
            )
        transaction = SemanticTransaction(
            transaction_uid=str(request.operation.get("transaction_uid") or uuid7_candidate()),
            base_commit=request.expected_base,
            expected_revisions=expected,
            effective_model_hash=effective_model_hash,
            review_package_hash=package_hash,
            operations=operations + approval_operations,
            approvals=attestations,
            actor=request.actor,
            delegation_uid=request.delegation_uid,
            idempotency_key=request.idempotency_key,
        )
        if request.dry_run:
            return DomainResult(
                {
                    "workspace_uid": request.workspace_uid,
                    "dry_run": True,
                    "transaction_hash": transaction.hash(),
                    "operation_count": len(operations),
                }
            )
        try:
            result = self.repository.apply(
                transaction, projection_updater=self._rebuild_projection
            )
        except RuntimeError as exc:
            return self._error(
                "LESR-APPLY-CONFLICT",
                ErrorCategory.CONFLICT,
                str(exc),
                (request.workspace_uid,),
                retryable=True,
                suggested="workspace.rebase",
            )
        applied_workspace = self.workspaces[request.workspace_uid] | {
            "state": "applied",
            "result_commit": result.commit,
        }
        self.repository.create_checkpoint(
            request.workspace_uid,
            applied_workspace,
            CheckpointStrategy.WORKSPACE_REF,
        )
        self.reload()
        return DomainResult(
            {
                "workspace_uid": request.workspace_uid,
                "result_commit": result.commit,
                "idempotent_replay": result.idempotent_replay,
                "projection_stale": result.projection_stale,
            }
        )

    def start_task(self, task_type: str, request: dict[str, Any]) -> DomainResult:
        if task_type == "verify_audit_chain":
            task_result: dict[str, Any] = {
                "valid": self.repository.verify_audit_chain(),
                "source_commit": self.base,
            }
        elif task_type == "compile_effective_model":
            configuration_uid = request.get("configuration_uid")
            configuration_doc = self.by_uid.get(str(configuration_uid))
            if (
                configuration_doc is None
                or configuration_doc.get("resource_type") != "configuration_snapshot"
            ):
                return self._error(
                    "LESR-CONFIGURATION-NOT-FOUND",
                    ErrorCategory.NOT_FOUND,
                    "configuration does not exist",
                    (str(configuration_uid),),
                )
            definition = ConfigurationDefinition(
                str(configuration_doc["configuration_uid"]),
                str(configuration_doc["git_commit"]),
                (),
                tuple(str(uid) for uid in configuration_doc["profile_revision_uids"]),
                str(configuration_doc["effective_model_hash"]),
            )
            model = self._compile_model(definition)
            task_result = {
                "effective_model_hash": (
                    model.effective_model_hash if model else definition.effective_model_hash
                ),
                "profile_revision_uids": list(definition.profile_revision_uids),
                "conflicts": list(model.conflicts if model else ()),
                "source_commit": self.base,
            }
        else:
            return self._error(
                "LESR-TASK-TYPE-UNSUPPORTED",
                ErrorCategory.VALIDATION,
                f"unsupported task type: {task_type}",
            )
        task = LongTask(
            f"TASK-{uuid7_candidate()}",
            task_type,
            TaskState.COMPLETED,
            request,
            task_result,
        )
        self.tasks[task.task_uid] = task
        return DomainResult(asdict(task))

    def task_status(self, task_uid: str) -> DomainResult:
        task = self.tasks.get(task_uid)
        return DomainResult(asdict(task)) if task else self._task_missing(task_uid)

    def cancel_task(self, task_uid: str) -> DomainResult:
        task = self.tasks.get(task_uid)
        if task is None:
            return self._task_missing(task_uid)
        if task.state is TaskState.COMPLETED:
            return self._error(
                "LESR-TASK-ALREADY-COMPLETE",
                ErrorCategory.CONFLICT,
                "completed task cannot be cancelled",
                (task_uid,),
            )
        return DomainResult(asdict(task))

    def task_result(self, task_uid: str) -> DomainResult:
        task = self.tasks.get(task_uid)
        return DomainResult(asdict(task)) if task else self._task_missing(task_uid)

    def _verify_approvals(
        self,
        approvals: tuple[SignedApproval, ...],
        package: dict[str, Any],
        package_hash: str,
        effective_model_hash: str,
        operations: tuple[SemanticOperation, ...],
    ) -> tuple[tuple[ApprovalAttestation, ...], tuple[SemanticOperation, ...]]:
        if not approvals:
            raise PermissionError("at least one signed human approval is required")
        required_roles = {str(item) for item in package["required_review_roles"]}
        approved_roles: set[str] = set()
        approving_actors: set[str] = set()
        attestations: list[ApprovalAttestation] = []
        approval_operations: list[SemanticOperation] = []
        affected = {
            str(uid)
            for operation in operations
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
            if uid is not None
        }
        for approval in approvals:
            trust_doc = next(
                (
                    item
                    for item in self.by_type.get("trusted_actor", [])
                    if item["actor_uid"] == approval.actor_uid
                    and item["key_uid"] == approval.key_uid
                ),
                None,
            )
            if trust_doc is None:
                raise PermissionError("approval key is not trusted by Canonical State")
            trust = TrustedActor.model_validate(trust_doc)
            verify_approval(
                approval,
                trust,
                package_hash=package_hash,
                effective_model_hash=effective_model_hash,
            )
            if approval.actor_uid == package["prepared_by_actor_uid"]:
                raise PermissionError("review-package preparer cannot approve their own package")
            if approval.conditions:
                raise PermissionError("approval conditions require an explicit satisfied-condition record")
            scope_uids = {
                str(item)
                for name in ("resource_uids", "revision_uids")
                for item in self._list(approval.scope.get(name, []))
            }
            if affected and not affected <= scope_uids:
                raise PermissionError("approval scope does not cover every affected resource")
            approved_roles.add(approval.actor_role)
            approving_actors.add(approval.actor_uid)
            attestations.append(
                ApprovalAttestation(
                    approval.approval_uid,
                    package_hash,
                    approval.actor_uid,
                    approval.actor_type,
                    approval.approval_type,
                )
            )
            payload = approval.model_dump(mode="json", exclude_none=True)
            self.schemas.validate("approval-attestation.schema.json", payload)
            approval_operations.append(
                SemanticOperation(
                    OperationType.RECORD_APPROVAL,
                    f"canonical/approvals/{approval.approval_uid}.json",
                    payload,
                )
            )
        missing_roles = required_roles - approved_roles
        if missing_roles:
            raise PermissionError("missing required review roles: " + ", ".join(sorted(missing_roles)))
        if len(approving_actors) < int(package["minimum_approval_count"]):
            raise PermissionError("minimum independent human approval count was not met")
        return tuple(attestations), tuple(approval_operations)

    def _validate_write(
        self, request: WriteEnvelope, operation: str, *, require_workspace: bool
    ) -> DomainResult | None:
        missing = [
            name
            for name, value in (
                ("workspace_uid", request.workspace_uid),
                ("expected_base", request.expected_base),
                ("idempotency_key", request.idempotency_key),
                ("actor", request.actor),
                ("delegation_uid", request.delegation_uid),
            )
            if not value
        ]
        if missing:
            return self._error(
                "LESR-WRITE-ENVELOPE-INVALID",
                ErrorCategory.VALIDATION,
                "missing write fields: " + ", ".join(missing),
            )
        if request.expected_base != self.base:
            return self._error(
                "LESR-BASE-CONFLICT",
                ErrorCategory.CONFLICT,
                "expected base is stale",
                (request.expected_base, self.base),
                retryable=True,
            )
        if require_workspace and request.workspace_uid not in self.workspaces:
            return self._error(
                "LESR-WORKSPACE-NOT-FOUND",
                ErrorCategory.NOT_FOUND,
                "workspace does not exist",
                (request.workspace_uid,),
                suggested="open_workspace",
            )
        delegation = self.by_uid.get(request.delegation_uid)
        if delegation is None or delegation.get("resource_type") != "delegation_grant":
            return self._error(
                "LESR-DELEGATION-INVALID",
                ErrorCategory.AUTHORIZATION,
                "delegation is not present in Canonical State",
                (request.delegation_uid,),
            )
        now = datetime.now(UTC)
        issued = datetime.fromisoformat(str(delegation["issued_at"]))
        expires = datetime.fromisoformat(str(delegation["expires_at"]))
        allowed = {str(item) for item in delegation["operations"]}
        if (
            delegation["principal_uid"] != request.actor
            or delegation["workspace_uid"] != request.workspace_uid
            or not self.repository.is_ancestor(
                str(delegation["base_commit"]), request.expected_base
            )
            or operation not in allowed
            or now < issued
            or now >= expires
        ):
            return self._error(
                "LESR-DELEGATION-SCOPE-DENIED",
                ErrorCategory.AUTHORIZATION,
                "delegation does not authorize this actor/workspace/base/operation",
                (request.delegation_uid,),
            )
        if delegation.get("stop_conditions"):
            return self._error(
                "LESR-DELEGATION-STOPPED",
                ErrorCategory.AUTHORIZATION,
                "delegation has active stop conditions",
                (request.delegation_uid,),
            )
        scope = self._dict(delegation.get("scope", {}))
        allowed_uids = {
            str(item)
            for name in ("resource_uids", "revision_uids")
            for item in self._list(scope.get(name, []))
        }
        proposed_resources: list[dict[str, Any]] = []
        if operation == "propose_operation" and isinstance(request.operation.get("resource"), dict):
            proposed_resources = [self._dict(request.operation["resource"])]
        elif operation == "apply_transaction":
            proposed_resources = [
                self._dict(item).get("resource", {})
                for item in self._list(request.operation.get("operations", []))
            ]
        affected = {
            str(uid)
            for resource in proposed_resources
            if isinstance(resource, dict)
            for uid in (
                resource.get("entity_uid"),
                resource.get("object_uid"),
                resource.get("revision_uid"),
                resource.get("relation_revision_uid"),
                resource.get("record_uid"),
                resource.get("profile_revision_uid"),
                resource.get("rule_revision_uid"),
                resource.get("configuration_uid"),
                resource.get("baseline_uid"),
            )
            if uid is not None
        }
        if affected and not affected <= allowed_uids:
            return self._error(
                "LESR-DELEGATION-SCOPE-DENIED",
                ErrorCategory.AUTHORIZATION,
                "delegation scope does not cover every affected resource",
                tuple(sorted(affected - allowed_uids)),
            )
        limits = self._dict(delegation.get("limits", {}))
        max_operations = limits.get("max_operations")
        existing_count = len(
            self.workspaces.get(request.workspace_uid, {}).get("operations", [])
        )
        if (
            isinstance(max_operations, int)
            and existing_count + len(proposed_resources) > max_operations
        ):
            return self._error(
                "LESR-DELEGATION-LIMIT-EXCEEDED",
                ErrorCategory.AUTHORIZATION,
                "delegation operation limit would be exceeded",
                (request.delegation_uid,),
            )
        max_risk = limits.get("max_risk_class")
        risk_order = {RiskClass.LOW: 0, RiskClass.MEDIUM: 1, RiskClass.HIGH: 2}
        try:
            maximum_risk = RiskClass(max_risk) if isinstance(max_risk, str) else None
        except ValueError:
            return self._error(
                "LESR-DELEGATION-INVALID",
                ErrorCategory.AUTHORIZATION,
                "delegation has an invalid risk-class limit",
                (request.delegation_uid,),
            )
        if maximum_risk is not None and risk_order[request.risk_class] > risk_order[maximum_risk]:
            return self._error(
                "LESR-DELEGATION-LIMIT-EXCEEDED",
                ErrorCategory.AUTHORIZATION,
                "delegation risk-class limit would be exceeded",
                (request.delegation_uid,),
            )
        return None

    def _operation(self, value: Any) -> SemanticOperation:
        item = self._dict(value)
        payload = self._dict(item["resource"])
        operation_type = OperationType(str(item["operation_type"]))
        schema_name = _RESOURCE_SCHEMAS.get(str(payload.get("resource_type")))
        if schema_name is None:
            raise ValueError(f"unsupported canonical resource type: {payload.get('resource_type')}")
        self.schemas.validate(schema_name, payload)
        return SemanticOperation(operation_type, _canonical_path(payload), payload)

    @staticmethod
    def _validate_review_package(
        request: WriteEnvelope,
        package: dict[str, Any],
        package_hash: str,
        effective_model_hash: str,
        raw_operations: list[Any],
    ) -> None:
        if document_hash(package, "package_hash") != package_hash:
            raise PermissionError("review package content hash is invalid")
        if package["workspace_uid"] != request.workspace_uid:
            raise PermissionError("review package does not bind the workspace")
        if package["base_commit"] != request.expected_base:
            raise PermissionError("review package does not bind the expected base")
        if package["effective_model_hash"] != effective_model_hash:
            raise PermissionError("review package does not bind the effective model")
        semantic_diff = package["semantic_diff"]
        if not isinstance(semantic_diff, dict):
            raise PermissionError("review package semantic diff is invalid")
        operation_hashes = [
            semantic_hash(
                {
                    "operation_type": item.get("operation_type"),
                    "resource": item.get("resource"),
                }
            )
            for raw in raw_operations
            for item in [RepositoryDomainService._dict(raw)]
        ]
        if semantic_diff.get("operation_hashes") != operation_hashes:
            raise PermissionError("review package does not bind the semantic operations")

    def _ensure_projection(self) -> None:
        try:
            with sqlite3.connect(self.projection) as connection:
                source = connection.execute(
                    "SELECT source_commit FROM projection_meta"
                ).fetchone()
            if source and source[0] == self.base:
                return
        except sqlite3.Error:
            pass
        self.repository.rebuild_projection(self.projection)

    def _compile_model(
        self, configuration: ConfigurationDefinition
    ) -> EffectiveModel | None:
        profile_uids = set(configuration.profile_revision_uids)
        profiles = tuple(
            ProfileRevision.model_validate(item)
            for item in self.by_type.get("profile_revision", [])
            if item["profile_revision_uid"] in profile_uids
        )
        if not profiles:
            return None
        referenced_rules = {
            uid for profile in profiles for uid in profile.rule_revision_uids
        }
        rules = tuple(
            RuleDefinition.model_validate(item)
            for item in self.by_type.get("rule_definition_revision", [])
            if item["rule_revision_uid"] in referenced_rules
        )
        return ProfileCompiler().compile(profiles, rules)

    def _context_rules(
        self, configuration: ConfigurationDefinition
    ) -> tuple[EffectiveRuleReference, ...]:
        model = self._compile_model(configuration)
        if model is None:
            return ()
        return tuple(
            EffectiveRuleReference(
                rule.rule_revision_uid,
                frozenset(rule.enforcement),
                frozenset(),
            )
            for rule in model.rules
        )

    def _validate_configured_models(self) -> None:
        for item in self.by_type.get("configuration_snapshot", []):
            definition = ConfigurationDefinition(
                str(item["configuration_uid"]),
                str(item["git_commit"]),
                (),
                tuple(str(uid) for uid in item["profile_revision_uids"]),
                str(item["effective_model_hash"]),
            )
            model = self._compile_model(definition)
            if model is not None and model.effective_model_hash != definition.effective_model_hash:
                raise ValueError(
                    f"configuration {definition.configuration_uid} effective_model_hash is stale"
                )

    def _rebuild_projection(self, _commit: str) -> None:
        self.repository.rebuild_projection(self.projection)

    def _maturity(self, revision_uid: str) -> str:
        records = [
            item
            for item in self.by_type.get("immutable_record", [])
            if item.get("record_type") == "lifecycle" and item.get("subject_uid") == revision_uid
        ]
        values = [self._field(item, "/to_state", "") for item in records]
        return values[-1] if values else "draft"

    @staticmethod
    def _field(document: dict[str, Any], path: str, default: str) -> str:
        return next(
            (str(item["value"]) for item in document.get("fields", []) if item.get("path") == path),
            default,
        )

    def _task_missing(self, task_uid: str) -> DomainResult:
        return self._error(
            "LESR-TASK-NOT-FOUND", ErrorCategory.NOT_FOUND, "task does not exist", (task_uid,)
        )

    @staticmethod
    def _dict(value: Any) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise TypeError("expected an object")
        return value

    @staticmethod
    def _list(value: Any) -> list[Any]:
        if not isinstance(value, list):
            raise TypeError("expected an array")
        return value

    @staticmethod
    def _error(
        code: str,
        category: ErrorCategory,
        message: str,
        resources: tuple[str, ...] = (),
        *,
        retryable: bool = False,
        suggested: str | None = None,
    ) -> DomainResult:
        return DomainResult(
            error=DomainErrorContract(
                code,
                category,
                message,
                resources,
                retryable=retryable,
                suggested_capability=suggested,
            )
        )


_PRIMARY_UID_FIELDS = {
    "logical_object": "entity_uid",
    "revision": "revision_uid",
    "relation_assertion_revision": "relation_revision_uid",
    "immutable_record": "record_uid",
    "profile_revision": "profile_revision_uid",
    "configuration_snapshot": "configuration_uid",
    "baseline_manifest": "baseline_uid",
    "trusted_actor": "key_uid",
    "delegation_grant": "delegation_uid",
    "approval_attestation": "approval_uid",
    "rule_definition_revision": "rule_revision_uid",
    "applied_change": "transaction_uid",
    "provenance_record": "provenance_uid",
    "audit_anchor": "anchor_uid",
}

_RESOURCE_SCHEMAS = {
    "logical_object": "logical-object.schema.json",
    "revision": "revision.schema.json",
    "relation_assertion_revision": "relation-assertion.schema.json",
    "immutable_record": "immutable-record.schema.json",
    "profile_revision": "profile.schema.json",
    "configuration_snapshot": "configuration.schema.json",
    "baseline_manifest": "baseline-manifest.schema.json",
    "rule_definition_revision": "rule-definition.schema.json",
}


def _canonical_path(resource: dict[str, Any]) -> str:
    resource_type = resource.get("resource_type")
    if resource_type == "logical_object":
        return f"canonical/objects/{resource['entity_uid']}.json"
    if resource_type == "revision":
        return f"canonical/revisions/{resource['revision_uid']}.json"
    if resource_type == "relation_assertion_revision":
        return (
            f"canonical/relations/{resource['assertion_uid']}/revisions/"
            f"{resource['relation_revision_uid']}.json"
        )
    if resource_type == "immutable_record":
        return f"canonical/records/{resource['record_type']}/{resource['record_uid']}.json"
    if resource_type == "profile_revision":
        return f"canonical/profiles/{resource['profile_revision_uid']}.json"
    if resource_type == "configuration_snapshot":
        return f"canonical/configurations/{resource['configuration_uid']}.json"
    if resource_type == "baseline_manifest":
        return f"canonical/baselines/{resource['baseline_uid']}.json"
    if resource_type == "rule_definition_revision":
        return f"canonical/rules/{resource['rule_revision_uid']}.json"
    raise ValueError(f"unsupported canonical resource type: {resource_type}")
