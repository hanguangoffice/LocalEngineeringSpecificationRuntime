"""Repository-backed LESR v1 capability service."""

from __future__ import annotations

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
from lesr.application.contracts import (
    DomainResult,
    ErrorCategory,
    InMemoryDomainService,
    WriteEnvelope,
)
from lesr.domain.approval import SignedApproval, TrustedActor, verify_approval
from lesr.domain.semantic import document_hash, semantic_hash, uuid7_candidate


class RepositoryDomainService(InMemoryDomainService):
    """Capability port backed by the exact Canonical Git commit."""

    def __init__(self, project: Path) -> None:
        self.repository = GitCanonicalRepository(project)
        self.schemas = SchemaCatalog()
        self.repository.initialize()
        super().__init__()
        self.reload()

    def reload(self) -> None:
        self.base = self.repository.current_commit()
        resources: dict[str, dict[str, Any]] = {}
        revisions: dict[str, dict[str, Any]] = {}
        for _, document in self.repository.documents(self.base):
            resource_type = document.get("resource_type")
            if resource_type == "logical_object":
                uid = str(document["entity_uid"])
                resources[uid] = {
                    "uid": uid,
                    "human_key": document["human_key"],
                    "aliases": [item["value"] for item in document.get("aliases", [])],
                    "kind": document["kind"],
                    "revision_uid": None,
                    "canonical": document,
                }
            elif resource_type == "revision":
                revisions[str(document["object_uid"])] = document
        for uid, revision in revisions.items():
            if uid in resources:
                resources[uid]["revision_uid"] = revision["revision_uid"]
                resources[uid]["revision"] = revision
        self.resources = resources

    def open_workspace(self, request: WriteEnvelope) -> DomainResult:
        opened = super().open_workspace(request)
        if not opened.ok or request.dry_run:
            return opened
        workspace = dict(opened.value)
        checkpoint = self.repository.create_checkpoint(
            request.workspace_uid,
            workspace,
            CheckpointStrategy.WORKSPACE_REF,
        )
        workspace["checkpoint_uid"] = checkpoint.checkpoint_uid
        workspace["git_reference"] = checkpoint.git_reference
        self.workspaces[request.workspace_uid] = workspace
        return DomainResult(workspace)

    def propose_operation(self, request: WriteEnvelope) -> DomainResult:
        proposed = super().propose_operation(request)
        if not proposed.ok or request.dry_run:
            return proposed
        checkpoint = self.repository.create_checkpoint(
            request.workspace_uid,
            self.workspaces[request.workspace_uid],
            CheckpointStrategy.WORKSPACE_REF,
        )
        return DomainResult(
            dict(proposed.value)
            | {
                "checkpoint_uid": checkpoint.checkpoint_uid,
                "git_reference": checkpoint.git_reference,
            }
        )

    def apply_transaction(self, request: WriteEnvelope) -> DomainResult:
        error = self._validate_write(request, require_workspace=True)
        if error is not None:
            return error
        try:
            signed_value = request.operation["signed_approval"]
            trust_value = request.operation["trust_record"]
            review_package = request.operation["review_package"]
            self.schemas.validate("approval-attestation.schema.json", signed_value)
            self.schemas.validate("trusted-actor.schema.json", trust_value)
            self.schemas.validate("review-package.schema.json", review_package)
            signed = SignedApproval.model_validate(signed_value)
            trust = TrustedActor.model_validate(trust_value)
            package_hash = str(review_package["package_hash"])
            effective_model_hash = str(request.operation["effective_model_hash"])
            self._validate_review_package(
                request,
                review_package,
                package_hash,
                effective_model_hash,
            )
            if request.actor != signed.actor_uid:
                raise PermissionError("write actor does not match the human approver")
            verify_approval(
                signed,
                trust,
                package_hash=package_hash,
                effective_model_hash=effective_model_hash,
            )
            operations = tuple(
                self._operation(item) for item in request.operation["operations"]
            )
            expected = tuple(
                (str(item["revision_uid"]), str(item["content_hash"]))
                for item in request.operation.get("expected_revisions", [])
            )
        except (
            JsonSchemaValidationError,
            AttributeError,
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
            operations=operations,
            approvals=(
                ApprovalAttestation(
                    signed.approval_uid,
                    package_hash,
                    signed.actor_uid,
                    "human",
                    signed.approval_type,
                ),
            ),
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
            result = self.repository.apply(transaction)
        except RuntimeError as exc:
            return self._error(
                "LESR-APPLY-CONFLICT",
                ErrorCategory.CONFLICT,
                str(exc),
                (request.workspace_uid,),
                retryable=True,
                suggested="workspace.rebase",
            )
        self.reload()
        self.workspaces[request.workspace_uid]["state"] = "applied"
        return DomainResult(
            {
                "workspace_uid": request.workspace_uid,
                "result_commit": result.commit,
                "idempotent_replay": result.idempotent_replay,
                "projection_stale": result.projection_stale,
            }
        )

    def _operation(self, value: Any) -> SemanticOperation:
        if not isinstance(value, dict):
            raise TypeError("each operation must be an object")
        payload = value.get("resource")
        if not isinstance(payload, dict):
            raise TypeError("operation resource must be an object")
        operation_type = OperationType(str(value["operation_type"]))
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
            for item in request.operation["operations"]
        ]
        if semantic_diff.get("operation_hashes") != operation_hashes:
            raise PermissionError("review package does not bind the semantic operations")


_RESOURCE_SCHEMAS = {
    "logical_object": "logical-object.schema.json",
    "revision": "revision.schema.json",
    "relation_assertion_revision": "relation-assertion.schema.json",
    "immutable_record": "immutable-record.schema.json",
    "baseline_manifest": "baseline-manifest.schema.json",
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
    if resource_type == "baseline_manifest":
        return f"canonical/baselines/{resource['baseline_uid']}.json"
    raise ValueError(f"unsupported canonical resource type: {resource_type}")
