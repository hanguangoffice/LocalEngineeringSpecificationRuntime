"""Repository-backed LESR capabilities over one exact Canonical Git commit."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

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
from lesr.domain.governance import (
    ValidationFinding,
    ValidationObservation,
    ValidationRun,
)
from lesr.domain.profiles import EffectiveModel, ProfileCompiler, ProfileRevision
from lesr.domain.rules import (
    EnforcementEffect,
    EvaluationEnvironment,
    Quantity,
    RuleDefinition,
    RuleOutcome,
    UnitRegistry,
    ValueCell,
    evaluate_rule,
)
from lesr.domain.semantic import (
    ImmutableRecord,
    LifecycleProjector,
    document_hash,
    semantic_hash,
    uuid7_candidate,
)


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
            CapabilityDescriptor(CapabilityGroup.QUERY, ("query", "traverse", "impact")),
            CapabilityDescriptor(CapabilityGroup.CONTEXT, ("build_context",)),
            CapabilityDescriptor(
                CapabilityGroup.WORKSPACE, ("open_workspace", "propose_operation")
            ),
            CapabilityDescriptor(
                CapabilityGroup.GOVERNANCE,
                (
                    "bootstrap_root_owner",
                    "initialize_configuration",
                    "prepare_review",
                    "apply_transaction",
                ),
            ),
            CapabilityDescriptor(
                CapabilityGroup.COMPLIANCE,
                ("compile_effective_model", "verify_audit_chain"),
            ),
        )

    @staticmethod
    def bootstrap_binding(
        base_commit: str,
        trust: dict[str, Any],
        delegation: dict[str, Any],
        governance_operations: tuple[dict[str, Any], ...] = (),
    ) -> tuple[str, str, dict[str, Any]]:
        resources = [
            RepositoryDomainService._dict(item.get("resource"))
            for item in governance_operations
        ]
        profiles = tuple(
            ProfileRevision.model_validate(item)
            for item in resources
            if item.get("resource_type") == "profile_revision"
        )
        rules = tuple(
            RuleDefinition.model_validate(item)
            for item in resources
            if item.get("resource_type") == "rule_definition_revision"
        )
        if resources and len(resources) != len(profiles) + len(rules):
            raise ValueError("bootstrap governance may contain only Rule and Profile revisions")
        model_hash = (
            ProfileCompiler().compile(profiles, rules).effective_model_hash
            if profiles
            else semantic_hash({"bootstrap_schema": "1.0"})
        )
        operation_hashes = [
            semantic_hash(
                {
                    "operation_type": item.get("operation_type"),
                    "resource": item.get("resource"),
                }
            )
            for item in governance_operations
        ]
        scope = {
            "base_commit": base_commit,
            "actor_uid": trust.get("actor_uid"),
            "key_uid": trust.get("key_uid"),
            "delegation_uid": delegation.get("delegation_uid"),
            "governance_operation_hashes": operation_hashes,
        }
        return (
            semantic_hash({"bootstrap": scope}),
            model_hash,
            scope,
        )

    def bootstrap_root_owner(
        self,
        trust: dict[str, Any],
        delegation: dict[str, Any],
        approval: dict[str, Any],
        idempotency_key: str,
        governance_operations: tuple[dict[str, Any], ...] = (),
    ) -> DomainResult:
        """One-time proof-of-possession bootstrap; unavailable after trust exists."""
        if self.by_type.get("trusted_actor"):
            return self._error(
                "LESR-BOOTSTRAP-ALREADY-COMPLETE",
                ErrorCategory.CONFLICT,
                "Canonical State already has a trusted root actor",
            )
        try:
            self.schemas.validate("trusted-actor.schema.json", trust)
            self.schemas.validate("delegation-grant.schema.json", delegation)
            self.schemas.validate("approval-attestation.schema.json", approval)
            trusted = TrustedActor.model_validate(trust)
            signed = SignedApproval.model_validate(approval)
            package_hash, model_hash, scope = self.bootstrap_binding(
                self.base, trust, delegation, governance_operations
            )
            if signed.scope != scope:
                raise PermissionError("bootstrap approval scope is invalid")
            verify_approval(
                signed,
                trusted,
                package_hash=package_hash,
                effective_model_hash=model_hash,
            )
            if (
                delegation["base_commit"] != self.base
                or delegation["issued_by"] != trusted.actor_uid
                or delegation["principal_uid"] != trusted.actor_uid
                or signed.actor_uid != trusted.actor_uid
            ):
                raise PermissionError("bootstrap trust and delegation identities differ")
            governance = tuple(self._operation(item) for item in governance_operations)
            transaction = SemanticTransaction(
                transaction_uid=uuid7_candidate(),
                base_commit=self.base,
                expected_revisions=(),
                effective_model_hash=model_hash,
                review_package_hash=package_hash,
                operations=(
                    SemanticOperation(
                        OperationType.REGISTER_TRUSTED_ACTOR,
                        f"canonical/trust/{trusted.actor_uid}/{trusted.key_uid}.json",
                        trust,
                    ),
                    SemanticOperation(
                        OperationType.CREATE_DELEGATION,
                        f"canonical/delegations/{delegation['delegation_uid']}.json",
                        delegation,
                    ),
                    SemanticOperation(
                        OperationType.RECORD_APPROVAL,
                        f"canonical/approvals/{signed.approval_uid}.json",
                        approval,
                    ),
                    SemanticOperation(
                        OperationType.RECORD_PROVENANCE,
                        f"canonical/provenance/{signed.provenance_uid}.json",
                        self._bootstrap_approval_provenance(signed),
                    ),
                ) + governance,
                approvals=(
                    ApprovalAttestation(
                        signed.approval_uid,
                        package_hash,
                        signed.actor_uid,
                        signed.actor_type,
                        signed.approval_type,
                    ),
                ),
                actor=trusted.actor_uid,
                delegation_uid=str(delegation["delegation_uid"]),
                idempotency_key=idempotency_key,
            )
            result = self.repository.apply(transaction, projection_updater=self._rebuild_projection)
        except (
            JsonSchemaValidationError,
            KeyError,
            TypeError,
            ValueError,
            PermissionError,
            RuntimeError,
        ) as exc:
            return self._error(
                "LESR-BOOTSTRAP-INVALID",
                ErrorCategory.AUTHORIZATION,
                str(exc),
            )
        self.reload()
        return DomainResult(
            {
                "result_commit": result.commit,
                "actor_uid": trusted.actor_uid,
                "delegation_uid": delegation["delegation_uid"],
            }
        )

    @staticmethod
    def _bootstrap_approval_provenance(approval: SignedApproval) -> dict[str, Any]:
        value: dict[str, Any] = {
            "schema_version": "1.0",
            "resource_type": "provenance_record",
            "provenance_uid": approval.provenance_uid,
            "subject_uid": approval.approval_uid,
            "kind": "asserted",
            "responsible_actor_uid": approval.actor_uid,
            "performed_by_actor_uid": approval.actor_uid,
            "on_behalf_of_actor_uid": None,
            "tool_uids": [],
            "tool_identity": "human-ed25519-bootstrap",
            "delegation_uid": None,
            "used_uids": [],
            "generated_uids": [approval.approval_uid],
            "review_package_uid": None,
            "validation_run_uids": [],
            "context_bundle_hash": None,
            "generated_at": approval.issued_at.isoformat().replace("+00:00", "Z"),
        }
        value["content_hash"] = document_hash(value, "content_hash")
        return value

    @staticmethod
    def initial_configuration_binding(
        base_commit: str, configuration: dict[str, Any]
    ) -> tuple[str, str, dict[str, Any]]:
        scope = {
            "base_commit": base_commit,
            "configuration_uid": configuration.get("configuration_uid"),
            "configuration_hash": semantic_hash(configuration),
        }
        return (
            semantic_hash({"initial_configuration": scope}),
            str(configuration.get("effective_model_hash")),
            scope,
        )

    def initialize_configuration(
        self,
        configuration: dict[str, Any],
        approval: dict[str, Any],
        actor_uid: str,
        delegation_uid: str,
        idempotency_key: str,
    ) -> DomainResult:
        """Create the first complete configuration after root governance bootstrap."""
        if self.by_type.get("configuration_snapshot"):
            return self._error(
                "LESR-CONFIGURATION-ALREADY-INITIALIZED",
                ErrorCategory.CONFLICT,
                "initial configuration already exists",
            )
        try:
            self.schemas.validate("configuration.schema.json", configuration)
            self.schemas.validate("approval-attestation.schema.json", approval)
            if configuration["git_commit"] != self.base:
                raise ValueError("initial configuration must pin the exact Canonical base")
            definition = self._configuration_definition(configuration)
            model = self._compile_model(definition)
            if model is None or model.effective_model_hash != definition.effective_model_hash:
                raise ValueError("initial configuration Effective Model is unavailable or stale")
            signed = SignedApproval.model_validate(approval)
            package_hash, model_hash, scope = self.initial_configuration_binding(
                self.base, configuration
            )
            trust_document = next(
                (
                    item
                    for item in self.by_type.get("trusted_actor", [])
                    if item["actor_uid"] == signed.actor_uid
                    and item["key_uid"] == signed.key_uid
                ),
                None,
            )
            if trust_document is None or signed.scope != scope:
                raise PermissionError("initial configuration approval scope is invalid")
            verify_approval(
                signed,
                TrustedActor.model_validate(trust_document),
                package_hash=package_hash,
                effective_model_hash=model_hash,
            )
            transaction = SemanticTransaction(
                transaction_uid=uuid7_candidate(),
                base_commit=self.base,
                expected_revisions=(),
                effective_model_hash=model_hash,
                review_package_hash=package_hash,
                operations=(
                    SemanticOperation(
                        OperationType.CREATE_CONFIGURATION,
                        f"canonical/configurations/{configuration['configuration_uid']}.json",
                        configuration,
                    ),
                    SemanticOperation(
                        OperationType.RECORD_APPROVAL,
                        f"canonical/approvals/{signed.approval_uid}.json",
                        approval,
                    ),
                    SemanticOperation(
                        OperationType.RECORD_PROVENANCE,
                        f"canonical/provenance/{signed.provenance_uid}.json",
                        self._bootstrap_approval_provenance(signed),
                    ),
                ),
                approvals=(
                    ApprovalAttestation(
                        signed.approval_uid,
                        package_hash,
                        signed.actor_uid,
                        signed.actor_type,
                        signed.approval_type,
                    ),
                ),
                actor=actor_uid,
                delegation_uid=delegation_uid,
                idempotency_key=idempotency_key,
            )
            result = self.repository.apply(
                transaction, projection_updater=self._rebuild_projection
            )
        except (
            JsonSchemaValidationError,
            KeyError,
            TypeError,
            ValueError,
            PermissionError,
            RuntimeError,
        ) as exc:
            return self._error(
                "LESR-CONFIGURATION-INITIALIZATION-INVALID",
                ErrorCategory.AUTHORIZATION,
                str(exc),
            )
        self.reload()
        return DomainResult(
            {
                "result_commit": result.commit,
                "configuration_uid": configuration["configuration_uid"],
                "effective_model_hash": model_hash,
            }
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

    def query(
        self,
        kind: str | None,
        cursor: str | None,
        page_size: int,
        text: str | None = None,
    ) -> DomainResult:
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
            conditions: list[str] = []
            values: list[object] = []
            if kind:
                conditions.append("(kind = ? OR resource_type = ?)")
                values.extend((kind, kind))
            if text:
                conditions.append(
                    "path IN (SELECT path FROM documents_fts WHERE documents_fts MATCH ?)"
                )
                values.append('"' + text.replace('"', '""') + '"')
            where = "WHERE " + " AND ".join(conditions) if conditions else ""
            parameters = tuple(values)
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

    def traverse(
        self, start_uid: str, predicate: str | None, max_depth: int
    ) -> DomainResult:
        if not 1 <= max_depth <= 16:
            return self._error(
                "LESR-RELATION-DEPTH-INVALID",
                ErrorCategory.VALIDATION,
                "max_depth must be between 1 and 16",
            )
        start = self.by_uid.get(start_uid)
        if start is None:
            return self._error(
                "LESR-NOT-FOUND",
                ErrorCategory.NOT_FOUND,
                "relation traversal start resource was not found",
                (start_uid,),
            )
        object_uid = str(start.get("object_uid", start.get("entity_uid", start_uid)))
        frontier = {object_uid}
        visited = {object_uid}
        paths: list[dict[str, Any]] = []
        for depth in range(1, max_depth + 1):
            following: set[str] = set()
            for relation in self.by_type.get("relation_assertion_revision", []):
                if predicate is not None and relation["predicate"] != predicate:
                    continue
                source = relation["source"].get("object_uid")
                target = relation["target"].get("object_uid")
                if source in frontier and target:
                    neighbour = str(target)
                    direction = "outgoing"
                elif target in frontier and source:
                    neighbour = str(source)
                    direction = "incoming"
                else:
                    continue
                paths.append(
                    {
                        "depth": depth,
                        "direction": direction,
                        "relation_revision_uid": relation["relation_revision_uid"],
                        "predicate": relation["predicate"],
                        "object_uid": neighbour,
                    }
                )
                if neighbour not in visited:
                    following.add(neighbour)
                    visited.add(neighbour)
            frontier = following
            if not frontier:
                break
        return DomainResult(
            {
                "start_object_uid": object_uid,
                "paths": paths,
                "visited_object_uids": sorted(visited),
            }
        )

    def impact(self, start_uid: str, max_depth: int) -> DomainResult:
        result = self.traverse(start_uid, None, max_depth)
        if not result.ok:
            return result
        value = self._dict(result.value)
        return DomainResult(
            value
            | {
                "analysis": "bounded_bidirectional_relation_impact",
                "affected_object_uids": sorted(
                    set(self._list(value["visited_object_uids"])) - {start_uid}
                ),
            }
        )

    def build_context(
        self,
        task_type: str,
        target_uids: tuple[str, ...],
        token_budget: int,
        configuration_uid: str = "",
        actor: str = "context-reader",
    ) -> DomainResult:
        if not configuration_uid:
            return self._error(
                "LESR-CONTEXT-CONFIGURATION-REQUIRED",
                ErrorCategory.INDETERMINATE,
                "context requires an explicit configuration UID; no current is inferred",
                suggested="resolve",
            )
        configuration_doc = self.by_uid.get(configuration_uid)
        if (
            configuration_doc is None
            or configuration_doc.get("resource_type") != "configuration_snapshot"
        ):
            return self._error(
                "LESR-CONTEXT-CONFIGURATION-NOT-FOUND",
                ErrorCategory.NOT_FOUND,
                "the explicit configuration is unavailable",
                (configuration_uid,),
                suggested="resolve",
            )
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
            actor=actor,
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
        configured_relation_uids = {
            str(uid) for uid in configuration_doc["relation_revision_uids"]
        }
        relations = tuple(
            ContextRelation(
                str(item["source"].get("object_uid", "")),
                str(item["predicate"]),
                str(item["target"].get("object_uid", "")),
            )
            for item in self.by_type.get("relation_assertion_revision", [])
            if item["relation_revision_uid"] in configured_relation_uids
            and item["source"].get("object_uid")
            and item["target"].get("object_uid")
        )
        model = self._compile_model(configuration)
        if model is None or model.effective_model_hash != configuration.effective_model_hash:
            return self._error(
                "LESR-CONTEXT-MODEL-INDETERMINATE",
                ErrorCategory.INDETERMINATE,
                "configuration Effective Model is unavailable or stale",
                (configuration_uid,),
            )
        exact_policies = [
            item
            for item in model.context_policies
            if item.task_type == task_type
        ]
        matching_policies = exact_policies or [
            item for item in model.context_policies if item.task_type == "*"
        ]
        if len(matching_policies) != 1:
            return self._error(
                "LESR-CONTEXT-POLICY-INDETERMINATE",
                ErrorCategory.INDETERMINATE,
                "effective Profile must define exactly one context policy for the task",
                (configuration_uid,),
            )
        context_policy = matching_policies[0]
        contract = ContextPlanner().build(
            task_type=task_type,
            resolution=resolution,
            resources=resources,
            relations=relations,
            rules=self._context_rules(configuration),
            policy=ContextPolicy(
                frozenset(context_policy.invariant_object_uids),
                frozenset(context_policy.mandatory_predicates),
                frozenset(context_policy.conditional_predicates),
                frozenset(context_policy.forbidden_sensitivities),
            ),
            token_budget=token_budget,
            configuration=configuration,
        )
        return DomainResult(asdict(contract))

    def open_workspace(self, request: WriteEnvelope) -> DomainResult:
        replay = self._workspace_idempotency(request, "open_workspace")
        if replay is not None:
            return replay
        error = self._validate_write(request, "open_workspace", require_workspace=False)
        if error is not None:
            return error
        workspace = {
            "workspace_uid": request.workspace_uid,
            "base": request.expected_base,
            "state": "open",
            "delegation_uid": request.delegation_uid,
            "operations": [],
            "idempotency": {
                request.idempotency_key: self._write_request_hash(
                    request, "open_workspace"
                )
            },
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
        replay = self._workspace_idempotency(request, "propose_operation")
        if replay is not None:
            return replay
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
        self.workspaces[request.workspace_uid].setdefault("idempotency", {})[
            request.idempotency_key
        ] = self._write_request_hash(request, "propose_operation")
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

    def _workspace_idempotency(
        self, request: WriteEnvelope, operation: str
    ) -> DomainResult | None:
        workspace = self.workspaces.get(request.workspace_uid)
        if workspace is None:
            return None
        idempotency = workspace.get("idempotency", {})
        if not isinstance(idempotency, dict) or request.idempotency_key not in idempotency:
            return None
        if idempotency[request.idempotency_key] != self._write_request_hash(
            request, operation
        ):
            return self._error(
                "LESR-IDEMPOTENCY-CONFLICT",
                ErrorCategory.CONFLICT,
                "idempotency key was used for a different workspace request",
                (request.workspace_uid,),
            )
        return DomainResult(
            {
                "workspace_uid": request.workspace_uid,
                "state": workspace.get("state"),
                "operation_count": len(workspace.get("operations", [])),
                "git_reference": workspace.get("git_reference"),
                "idempotent_replay": True,
            }
        )

    @staticmethod
    def _write_request_hash(request: WriteEnvelope, operation: str) -> str:
        return semantic_hash(
            {
                "operation": operation,
                "workspace_uid": request.workspace_uid,
                "expected_base": request.expected_base,
                "actor": request.actor,
                "delegation_uid": request.delegation_uid,
                "risk_class": request.risk_class,
                "payload": request.operation,
            }
        )

    def prepare_review(self, request: WriteEnvelope) -> DomainResult:
        """Validate the exact checkpointed candidate and derive all review gates."""
        error = self._validate_write(request, "prepare_review", require_workspace=True)
        if error is not None:
            return error
        try:
            configuration_uid = str(request.operation["configuration_uid"])
            configuration_doc = self._configuration_document(configuration_uid)
            configuration = self._configuration_definition(configuration_doc)
            if configuration.closure_status is not ClosureStatus.COMPLETE:
                raise ValueError("review requires a complete configuration closure")
            model = self._compile_model(configuration)
            if model is None:
                raise ValueError("configuration must select at least one Profile revision")
            if model.effective_model_hash != configuration.effective_model_hash:
                raise ValueError("configuration effective_model_hash is stale")
            raw_operations = self._workspace_operations(request.workspace_uid)
            operations = tuple(self._operation(item) for item in raw_operations)
            if not operations:
                raise ValueError("review candidate contains no semantic operations")
            candidate_hash = self._candidate_hash(raw_operations)
            findings, run = self._validate_candidate(
                request.workspace_uid,
                configuration,
                model,
                operations,
                candidate_hash,
            )
            policy = self._review_policy(model, "apply_transaction")
            package = self._derive_review_package(
                request,
                configuration,
                model,
                operations,
                candidate_hash,
                run,
                findings,
                policy,
            )
            self.schemas.validate("validation-run.schema.json", run.model_dump(mode="json"))
            for finding in findings:
                self.schemas.validate(
                    "validation-finding.schema.json", finding.model_dump(mode="json")
                )
            self.schemas.validate("review-package.schema.json", package)
        except (
            JsonSchemaValidationError,
            KeyError,
            TypeError,
            ValueError,
        ) as exc:
            return self._error(
                "LESR-REVIEW-PREPARATION-FAILED",
                ErrorCategory.INDETERMINATE,
                str(exc),
                (request.workspace_uid,),
                suggested="workspace.edit",
            )
        result = {
            "workspace_uid": request.workspace_uid,
            "review_package": package,
            "validation_run": run.model_dump(mode="json"),
            "findings": [item.model_dump(mode="json") for item in findings],
            "blocking": any(item.blocking and item.status == "open" for item in findings),
        }
        if request.dry_run:
            return DomainResult(result)
        workspace = self.workspaces[request.workspace_uid]
        workspace["review"] = result
        checkpoint = self.repository.create_checkpoint(
            request.workspace_uid, workspace, CheckpointStrategy.WORKSPACE_REF
        )
        result |= {
            "checkpoint_uid": checkpoint.checkpoint_uid,
            "git_reference": checkpoint.git_reference,
        }
        return DomainResult(result)

    def apply_transaction(self, request: WriteEnvelope) -> DomainResult:
        error = self._validate_write(
            request,
            "apply_transaction",
            require_workspace=True,
            check_base=False,
        )
        if error is not None:
            return error
        replay_record = self.repository.idempotency_record(request.idempotency_key)
        if replay_record is not None:
            review = self.workspaces.get(request.workspace_uid, {}).get("review", {})
            package = review.get("review_package", {}) if isinstance(review, dict) else {}
            requested_uid = request.operation.get("review_package_uid")
            requested_transaction_uid = request.operation.get("transaction_uid")
            transaction_uid = str(replay_record["transaction_uid"])
            change = self.repository.read_json(
                self.base, f"canonical/applied_changes/{transaction_uid}.json"
            )
            if (
                not isinstance(package, dict)
                or requested_uid != package.get("package_uid")
                or requested_transaction_uid != transaction_uid
                or change is None
                or change.get("review_package_hash") != package.get("package_hash")
            ):
                return self._error(
                    "LESR-IDEMPOTENCY-CONFLICT",
                    ErrorCategory.CONFLICT,
                    "idempotency key was used for a different apply request",
                    (request.workspace_uid,),
                )
            return DomainResult(
                {
                    "workspace_uid": request.workspace_uid,
                    "result_commit": replay_record["result_commit"],
                    "idempotent_replay": True,
                    "projection_stale": False,
                }
            )
        try:
            review = self._dict(self.workspaces[request.workspace_uid]["review"])
            review_package = self._dict(review["review_package"])
            requested_package_uid = str(request.operation["review_package_uid"])
            if requested_package_uid != review_package["package_uid"]:
                raise PermissionError("apply does not reference the checkpointed review package")
            self.schemas.validate("review-package.schema.json", review_package)
            package_hash = str(review_package["package_hash"])
            effective_model_hash = str(review_package["effective_model_hash"])
            raw_operations = self._workspace_operations(request.workspace_uid)
            operations = tuple(self._operation(item) for item in raw_operations)
            self._validate_review_package(
                request, review_package, package_hash, effective_model_hash, raw_operations
            )
            configuration_doc = self._configuration_document(
                str(review_package["configuration_uid"])
            )
            configuration = self._configuration_definition(configuration_doc)
            model = self._compile_model(configuration)
            if model is None or model.effective_model_hash != effective_model_hash:
                raise PermissionError("review package model is no longer effective")
            policy = self._review_policy(model, "apply_transaction")
            if (
                list(policy.required_roles) != review_package["required_review_roles"]
                or policy.minimum_approval_count
                != review_package["minimum_approval_count"]
                or policy.require_preparer_independence
                != review_package["preparer_independence_required"]
            ):
                raise PermissionError("review package governance policy is stale")
            stored_run = ValidationRun.model_validate(self._dict(review["validation_run"]))
            stored_findings = tuple(
                ValidationFinding.model_validate(self._dict(item))
                for item in self._list(review["findings"])
            )
            repeated_findings, repeated_run = self._validate_candidate(
                request.workspace_uid,
                configuration,
                model,
                operations,
                str(review_package["candidate_hash"]),
            )
            if self._validation_semantics(stored_run, stored_findings) != self._validation_semantics(
                repeated_run, repeated_findings
            ):
                raise PermissionError("candidate validation result is no longer reproducible")
            if tuple(review_package["validation_run_uids"]) != (
                stored_run.validation_run_uid,
            ):
                raise PermissionError("review package validation run is unavailable")
            if set(review_package["open_finding_uids"]) != {
                item.finding_uid for item in stored_findings if item.status == "open"
            }:
                raise PermissionError("review package finding set is incomplete")
            blocking = tuple(
                item.finding_uid
                for item in stored_findings
                if item.blocking and item.status == "open"
            )
            if blocking:
                raise PermissionError(
                    "blocking validation findings remain open: " + ", ".join(blocking)
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
            expected = self._expected_revisions(operations)
            governance_operations = self._governance_operations(
                review_package, stored_run, stored_findings
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
                suggested=None,
            )
        transaction = SemanticTransaction(
            transaction_uid=str(request.operation["transaction_uid"]),
            base_commit=request.expected_base,
            expected_revisions=expected,
            effective_model_hash=effective_model_hash,
            review_package_hash=package_hash,
            operations=operations + governance_operations + approval_operations,
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

    def _configuration_document(self, configuration_uid: str) -> dict[str, Any]:
        document = self.by_uid.get(configuration_uid)
        if document is None or document.get("resource_type") != "configuration_snapshot":
            raise ValueError(f"configuration is not present in Canonical State: {configuration_uid}")
        return document

    @staticmethod
    def _configuration_definition(document: dict[str, Any]) -> ConfigurationDefinition:
        return ConfigurationDefinition(
            str(document["configuration_uid"]),
            str(document["git_commit"]),
            (),
            tuple(str(uid) for uid in document["profile_revision_uids"]),
            str(document["effective_model_hash"]),
            tuple(str(uid) for uid in document["active_deviation_revision_uids"]),
            ClosureStatus(str(document["closure_status"])),
        )

    def _workspace_operations(self, workspace_uid: str) -> list[Any]:
        workspace = self.workspaces[workspace_uid]
        if workspace.get("base") != self.base:
            raise ValueError("workspace base is stale and must be rebased")
        return self._list(workspace.get("operations", []))

    @staticmethod
    def _candidate_hash(raw_operations: list[Any]) -> str:
        return semantic_hash(
            {
                "operations": [
                    {
                        "operation_type": RepositoryDomainService._dict(item).get(
                            "operation_type"
                        ),
                        "resource": RepositoryDomainService._dict(item).get("resource"),
                    }
                    for item in raw_operations
                ]
            }
        )

    @staticmethod
    def _review_policy(model: EffectiveModel, operation: str) -> Any:
        exact = [item for item in model.review_policies if item.operation == operation]
        fallback = [item for item in model.review_policies if item.operation == "*"]
        selected = exact or fallback
        if len(selected) != 1:
            raise ValueError(f"effective Profile must define one review policy for {operation}")
        return selected[0]

    def _validate_candidate(
        self,
        workspace_uid: str,
        configuration: ConfigurationDefinition,
        model: EffectiveModel,
        operations: tuple[SemanticOperation, ...],
        candidate_hash: str,
    ) -> tuple[tuple[ValidationFinding, ...], ValidationRun]:
        if candidate_hash != self._candidate_hash(
            [
                {
                    "operation_type": item.operation_type.value,
                    "resource": item.payload,
                }
                for item in operations
            ]
        ):
            raise ValueError("candidate hash does not bind the workspace operations")
        candidate_revisions = tuple(
            item.payload
            for item in operations
            if item.payload.get("resource_type") == "revision"
        )
        relation_uids = set(
            next(
                item["relation_revision_uids"]
                for item in self.by_type.get("configuration_snapshot", [])
                if item["configuration_uid"] == configuration.configuration_uid
            )
        )
        relations = tuple(
            item
            for item in self.by_type.get("relation_assertion_revision", [])
            if item["relation_revision_uid"] in relation_uids
        ) + tuple(
            item.payload
            for item in operations
            if item.payload.get("resource_type") == "relation_assertion_revision"
        )
        units = UnitRegistry(model.units)
        blocking_effects = set(
            self._review_policy(model, "apply_transaction").blocking_effects
        )
        run_uid = uuid7_candidate()
        observations: list[ValidationObservation] = []
        findings: list[ValidationFinding] = []
        conflicted_revisions = {
            uid
            for conflict in model.conflicts
            for uid in conflict.split(":")[:2]
        }
        for revision in candidate_revisions:
            fields = {
                str(item["path"]): ValueCell.present(self._rule_value(item.get("value")))
                for item in revision.get("fields", [])
                if isinstance(item, dict) and isinstance(item.get("path"), str)
            }
            object_uid = str(revision["object_uid"])
            relation_counts: dict[str, int] = {}
            for relation in relations:
                source = relation.get("source", {})
                target = relation.get("target", {})
                if (
                    isinstance(source, dict)
                    and isinstance(target, dict)
                    and object_uid
                    in {str(source.get("object_uid", "")), str(target.get("object_uid", ""))}
                ):
                    predicate = str(relation["predicate"])
                    relation_counts[predicate] = relation_counts.get(predicate, 0) + 1
            active_deviations = self._active_deviation_rules(
                configuration, revision, model
            )
            conflicted_rule_uids = frozenset(
                rule.rule_uid
                for rule in model.rules
                if rule.rule_revision_uid in conflicted_revisions
            )
            environment = EvaluationEnvironment(
                target_kind=str(revision["kind"]),
                fields=fields,
                relation_counts=relation_counts,
                operation="apply_transaction",
                active_deviation_rule_uids=frozenset(active_deviations),
                conflicted_rule_uids=conflicted_rule_uids,
            )
            for rule in model.rules:
                if rule.target_kind != environment.target_kind:
                    continue
                evaluated = evaluate_rule(rule, environment, units)
                explanation = self._evaluation_explanation(evaluated)
                observation = ValidationObservation(
                    rule_uid=rule.rule_uid,
                    rule_revision_uid=rule.rule_revision_uid,
                    target_uid=object_uid,
                    target_revision_uid=str(revision["revision_uid"]),
                    outcome=evaluated.outcome,
                    enforcement=evaluated.enforcement,
                    explanation=explanation,
                )
                observations.append(observation)
                if evaluated.outcome is RuleOutcome.SUPPRESSED_BY_DEVIATION:
                    findings.append(
                        ValidationFinding(
                            validation_run_uid=run_uid,
                            rule_uid=rule.rule_uid,
                            rule_revision_uid=rule.rule_revision_uid,
                            subject_uid=object_uid,
                            subject_revision_uid=str(revision["revision_uid"]),
                            outcome=evaluated.outcome,
                            enforcement=evaluated.enforcement,
                            blocking=False,
                            status="suppressed_by_deviation",
                            deviation_revision_uid=active_deviations[rule.rule_uid],
                            explanation=explanation,
                        )
                    )
                    continue
                if evaluated.outcome in {
                    RuleOutcome.PASS,
                    RuleOutcome.NOT_APPLICABLE,
                }:
                    continue
                blocking = evaluated.enforcement.value in blocking_effects or (
                    evaluated.outcome
                    in {
                        RuleOutcome.INDETERMINATE,
                        RuleOutcome.EVALUATOR_ERROR,
                        RuleOutcome.NOT_EVALUATED,
                    }
                    and evaluated.enforcement
                    not in {
                        EnforcementEffect.ALLOW,
                        EnforcementEffect.ALLOW_WITH_OBSERVATION,
                    }
                )
                findings.append(
                    ValidationFinding(
                        validation_run_uid=run_uid,
                        rule_uid=rule.rule_uid,
                        rule_revision_uid=rule.rule_revision_uid,
                        subject_uid=object_uid,
                        subject_revision_uid=str(revision["revision_uid"]),
                        outcome=evaluated.outcome,
                        enforcement=evaluated.enforcement,
                        blocking=blocking,
                        explanation=explanation,
                    )
                )
        outcome: Literal["pass", "fail", "indeterminate"]
        if any(item.blocking for item in findings):
            outcome = "fail"
        elif findings:
            outcome = "indeterminate"
        else:
            outcome = "pass"
        run = ValidationRun(
            validation_run_uid=run_uid,
            workspace_uid=workspace_uid,
            base_commit=self.base,
            configuration_uid=configuration.configuration_uid,
            effective_model_hash=model.effective_model_hash,
            candidate_hash=candidate_hash,
            observations=tuple(observations),
            finding_uids=tuple(item.finding_uid for item in findings),
            outcome=outcome,
        )
        return tuple(findings), run

    @staticmethod
    def _rule_value(value: Any) -> Any:
        if isinstance(value, dict) and set(value) == {"decimal", "unit"}:
            return Quantity(Decimal(str(value["decimal"])), str(value["unit"]))
        return value

    def _active_deviation_rules(
        self,
        configuration: ConfigurationDefinition,
        candidate: dict[str, Any],
        model: EffectiveModel,
    ) -> dict[str, str]:
        active: dict[str, str] = {}
        approvals = {
            str(item["record_uid"])
            for item in self.by_type.get("immutable_record", [])
        }
        by_revision = {
            str(item["revision_uid"]): item for item in self.by_type.get("revision", [])
        }
        for uid in configuration.active_deviation_revision_uids:
            deviation = by_revision.get(uid)
            if deviation is None or deviation.get("kind") != "deviation":
                raise ValueError(f"active deviation is not a deviation revision: {uid}")
            values = {
                str(item["path"]): item.get("value")
                for item in deviation.get("fields", [])
                if isinstance(item, dict)
            }
            if str(values.get("/approval_record_uid", "")) not in approvals:
                raise ValueError(f"active deviation has no canonical approval record: {uid}")
            valid_until = values.get("/valid_until")
            if not isinstance(valid_until, str) or datetime.fromisoformat(valid_until) <= datetime.now(UTC):
                raise ValueError(f"active deviation is expired or has no validity: {uid}")
            subject = str(values.get("/subject_uid", ""))
            if subject not in {str(candidate["object_uid"]), str(candidate["revision_uid"])}:
                continue
            rule_revision_uid = str(values.get("/rule_revision_uid", ""))
            rule = next(
                (item for item in model.rules if item.rule_revision_uid == rule_revision_uid),
                None,
            )
            if rule is None or not rule.deviation_allowed:
                raise ValueError(f"deviation does not reference a relaxable effective rule: {uid}")
            active[rule.rule_uid] = uid
        return active

    @staticmethod
    def _evaluation_explanation(evaluated: Any) -> dict[str, Any]:
        def node(value: Any) -> dict[str, Any] | None:
            if value is None:
                return None
            return {
                "node": value.node,
                "result": str(value.result),
                "reason": value.reason,
                "children": [node(child) for child in value.children],
            }

        return {
            "outcome": evaluated.outcome.value,
            "enforcement": evaluated.enforcement.value,
            "applicability": node(evaluated.applicability),
            "constraint": node(evaluated.constraint),
        }

    def _derive_review_package(
        self,
        request: WriteEnvelope,
        configuration: ConfigurationDefinition,
        model: EffectiveModel,
        operations: tuple[SemanticOperation, ...],
        candidate_hash: str,
        run: ValidationRun,
        findings: tuple[ValidationFinding, ...],
        policy: Any,
    ) -> dict[str, Any]:
        operation_hashes = [
            semantic_hash(
                {"operation_type": item.operation_type.value, "resource": item.payload}
            )
            for item in operations
        ]
        candidate_revisions = sorted(
            str(item.payload["revision_uid"])
            for item in operations
            if item.payload.get("resource_type") == "revision"
        )
        base_revisions = sorted(
            str(item.payload["parent_revision_uid"])
            for item in operations
            if item.payload.get("resource_type") == "revision"
            and item.payload.get("parent_revision_uid") is not None
        )
        relation_changes = [
            {
                "operation": item.operation_type.value,
                "relation_revision_uid": item.payload["relation_revision_uid"],
            }
            for item in operations
            if item.payload.get("resource_type") == "relation_assertion_revision"
        ]
        disposition_changes = [
            {
                "operation": item.operation_type.value,
                "record_uid": item.payload["record_uid"],
            }
            for item in operations
            if item.payload.get("resource_type") == "immutable_record"
            and item.payload.get("record_type") in {"disposition", "lifecycle"}
        ]
        validation_summary_hash = semantic_hash(
            {
                "run": run.content_hash,
                "findings": [item.content_hash for item in findings],
            }
        )
        package: dict[str, Any] = {
            "schema_version": "1.0",
            "resource_type": "review_package",
            "package_uid": uuid7_candidate(),
            "workspace_uid": request.workspace_uid,
            "base_commit": request.expected_base,
            "configuration_uid": configuration.configuration_uid,
            "candidate_hash": candidate_hash,
            "base_revision_uids": base_revisions,
            "candidate_revision_uids": candidate_revisions,
            "relation_changes": relation_changes,
            "disposition_changes": disposition_changes,
            "semantic_diff": {"operation_hashes": operation_hashes},
            "impact_analysis": {
                "affected_resource_uids": sorted(
                    self._affected_uids(operations)
                ),
                "candidate_operation_count": len(operations),
            },
            "validation_run_uids": [run.validation_run_uid],
            "validation_summary_hash": validation_summary_hash,
            "open_finding_uids": [
                item.finding_uid for item in findings if item.status == "open"
            ],
            "effective_model_hash": model.effective_model_hash,
            "evaluation_context_hash": semantic_hash(
                {
                    "configuration_uid": configuration.configuration_uid,
                    "configuration_commit": configuration.git_commit,
                    "effective_model_hash": model.effective_model_hash,
                    "candidate_hash": candidate_hash,
                }
            ),
            "prepared_by_actor_uid": request.actor,
            "required_review_roles": list(policy.required_roles),
            "minimum_approval_count": policy.minimum_approval_count,
            "preparer_independence_required": policy.require_preparer_independence,
            "created_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        }
        package["package_hash"] = document_hash(package, "package_hash")
        return package

    @staticmethod
    def _affected_uids(operations: tuple[SemanticOperation, ...]) -> set[str]:
        fields = (
            "entity_uid",
            "object_uid",
            "revision_uid",
            "relation_revision_uid",
            "record_uid",
            "profile_revision_uid",
            "rule_revision_uid",
            "configuration_uid",
            "baseline_uid",
        )
        return {
            str(value)
            for operation in operations
            for name in fields
            for value in [operation.payload.get(name)]
            if value is not None
        }

    @staticmethod
    def _validation_semantics(
        run: ValidationRun, findings: tuple[ValidationFinding, ...]
    ) -> str:
        return semantic_hash(
            {
                "candidate_hash": run.candidate_hash,
                "effective_model_hash": run.effective_model_hash,
                "outcome": run.outcome,
                "observations": [
                    item.model_dump(
                        mode="json", exclude={"observation_uid"}, exclude_none=True
                    )
                    for item in run.observations
                ],
                "findings": [
                    item.model_dump(
                        mode="json",
                        exclude={
                            "finding_uid",
                            "validation_run_uid",
                            "created_at",
                            "content_hash",
                        },
                        exclude_none=True,
                    )
                    for item in findings
                ],
            }
        )

    def _expected_revisions(
        self, operations: tuple[SemanticOperation, ...]
    ) -> tuple[tuple[str, str], ...]:
        expected: list[tuple[str, str]] = []
        for operation in operations:
            parent = operation.payload.get("parent_revision_uid")
            if not isinstance(parent, str):
                continue
            document = self.by_uid.get(parent)
            if document is None or document.get("resource_type") != "revision":
                raise ValueError(f"parent revision is unavailable: {parent}")
            expected.append((parent, str(document["content_hash"])))
        return tuple(expected)

    @staticmethod
    def _governance_operations(
        package: dict[str, Any],
        run: ValidationRun,
        findings: tuple[ValidationFinding, ...],
    ) -> tuple[SemanticOperation, ...]:
        values = [
            SemanticOperation(
                OperationType.RECORD_VALIDATION_RUN,
                f"canonical/validation/runs/{run.validation_run_uid}.json",
                run.model_dump(mode="json"),
            ),
            *(
                SemanticOperation(
                    OperationType.RECORD_VALIDATION_FINDING,
                    f"canonical/validation/findings/{item.finding_uid}.json",
                    item.model_dump(mode="json"),
                )
                for item in findings
            ),
            SemanticOperation(
                OperationType.RECORD_REVIEW_PACKAGE,
                f"canonical/review_packages/{package['package_uid']}.json",
                package,
            ),
        ]
        return tuple(values)

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
            if (
                package["preparer_independence_required"]
                and approval.actor_uid == package["prepared_by_actor_uid"]
            ):
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
            provenance: dict[str, Any] = {
                "schema_version": "1.0",
                "resource_type": "provenance_record",
                "provenance_uid": approval.provenance_uid,
                "subject_uid": approval.approval_uid,
                "kind": "asserted",
                "responsible_actor_uid": approval.actor_uid,
                "performed_by_actor_uid": approval.actor_uid,
                "on_behalf_of_actor_uid": None,
                "tool_uids": [],
                "tool_identity": "human-ed25519",
                "delegation_uid": None,
                "used_uids": [str(package["package_uid"])],
                "generated_uids": [approval.approval_uid],
                "review_package_uid": str(package["package_uid"]),
                "validation_run_uids": [
                    str(item) for item in package["validation_run_uids"]
                ],
                "context_bundle_hash": str(package["evaluation_context_hash"]),
                "generated_at": approval.issued_at.isoformat().replace("+00:00", "Z"),
            }
            provenance["content_hash"] = document_hash(provenance, "content_hash")
            self.schemas.validate("provenance.schema.json", provenance)
            approval_operations.append(
                SemanticOperation(
                    OperationType.RECORD_PROVENANCE,
                    f"canonical/provenance/{approval.provenance_uid}.json",
                    provenance,
                )
            )
        missing_roles = required_roles - approved_roles
        if missing_roles:
            raise PermissionError("missing required review roles: " + ", ".join(sorted(missing_roles)))
        if len(approving_actors) < int(package["minimum_approval_count"]):
            raise PermissionError("minimum independent human approval count was not met")
        return tuple(attestations), tuple(approval_operations)

    def _validate_write(
        self,
        request: WriteEnvelope,
        operation: str,
        *,
        require_workspace: bool,
        check_base: bool = True,
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
        if check_base and request.expected_base != self.base:
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
                suggested="workspace.open",
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
        elif operation in {"prepare_review", "apply_transaction"}:
            proposed_resources = [
                self._dict(item).get("resource", {})
                for item in self._list(
                    self.workspaces.get(request.workspace_uid, {}).get("operations", [])
                )
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
        existing_count = len(self.workspaces.get(request.workspace_uid, {}).get("operations", []))
        projected_count = (
            existing_count + len(proposed_resources)
            if operation == "propose_operation"
            else existing_count
        )
        if (
            isinstance(max_operations, int)
            and projected_count > max_operations
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
        if package["candidate_hash"] != RepositoryDomainService._candidate_hash(raw_operations):
            raise PermissionError("review package candidate hash is invalid")

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
            if model is None:
                raise ValueError(
                    f"configuration {definition.configuration_uid} has no effective Profile"
                )
            if model.effective_model_hash != definition.effective_model_hash:
                raise ValueError(
                    f"configuration {definition.configuration_uid} effective_model_hash is stale"
                )

    def _rebuild_projection(self, _commit: str) -> None:
        self.repository.rebuild_projection(self.projection)

    def _maturity(self, revision_uid: str) -> str:
        records = tuple(
            ImmutableRecord.model_validate(item)
            for item in self.by_type.get("immutable_record", [])
            if item.get("record_type") == "lifecycle" and item.get("subject_uid") == revision_uid
        )
        return LifecycleProjector.project("draft", records).status.value

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
    "validation_run": "validation_run_uid",
    "validation_finding": "finding_uid",
    "review_package": "package_uid",
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
    "validation_run": "validation-run.schema.json",
    "validation_finding": "validation-finding.schema.json",
    "review_package": "review-package.schema.json",
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
    if resource_type == "validation_run":
        return f"canonical/validation/runs/{resource['validation_run_uid']}.json"
    if resource_type == "validation_finding":
        return f"canonical/validation/findings/{resource['finding_uid']}.json"
    if resource_type == "review_package":
        return f"canonical/review_packages/{resource['package_uid']}.json"
    raise ValueError(f"unsupported canonical resource type: {resource_type}")
