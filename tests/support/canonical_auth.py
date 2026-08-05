"""Reusable real-signature authorization harness for Git adapter tests."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from lesr.adapters.git import (
    ApprovalAttestation,
    GitCanonicalRepository,
    OperationType,
    SemanticOperation,
    SemanticTransaction,
)
from lesr.domain.approval import ApprovalKeyStore, ApprovalPayload, TrustedActor
from lesr.domain.governance import ValidationRun
from lesr.domain.profiles import ProfileCompiler, ProfileRevision
from lesr.domain.semantic import document_hash, semantic_hash, uuid7_candidate


@dataclass(frozen=True, slots=True)
class CanonicalAuth:
    repository: GitCanonicalRepository
    store: ApprovalKeyStore
    trust: TrustedActor
    actor_uid: str
    delegation_uid: str
    workspace_uid: str
    configuration_uid: str
    profile_revision_uid: str
    model_hash: str

    def transaction(
        self,
        *,
        transaction_uid: str,
        idempotency_key: str,
        operations: tuple[SemanticOperation, ...],
        base_commit: str | None = None,
    ) -> SemanticTransaction:
        actual_base = base_commit or self.repository.current_commit()
        candidate_hash = semantic_hash(
            {
                "operations": [
                    {
                        "operation_type": item.operation_type.value,
                        "resource": item.payload,
                    }
                    for item in operations
                ]
            }
        )
        run = ValidationRun(
            workspace_uid=self.workspace_uid,
            base_commit=actual_base,
            configuration_uid=self.configuration_uid,
            effective_model_hash=self.model_hash,
            candidate_hash=candidate_hash,
            observations=(),
            finding_uids=(),
            outcome="pass",
        )
        validation_summary_hash = semantic_hash(
            {"run": run.content_hash, "findings": []}
        )
        package: dict[str, object] = {
            "schema_version": "1.0",
            "resource_type": "review_package",
            "package_uid": uuid7_candidate(),
            "workspace_uid": self.workspace_uid,
            "base_commit": actual_base,
            "configuration_uid": self.configuration_uid,
            "candidate_hash": candidate_hash,
            "base_revision_uids": [],
            "candidate_revision_uids": [
                str(item.payload["revision_uid"])
                for item in operations
                if item.payload.get("resource_type") == "revision"
                and "revision_uid" in item.payload
            ],
            "relation_changes": [],
            "disposition_changes": [],
            "semantic_diff": {
                "operation_hashes": [
                    semantic_hash(
                        {
                            "operation_type": item.operation_type.value,
                            "resource": item.payload,
                        }
                    )
                    for item in operations
                ]
            },
            "impact_analysis": {"test_harness": True},
            "validation_run_uids": [run.validation_run_uid],
            "validation_summary_hash": validation_summary_hash,
            "open_finding_uids": [],
            "effective_model_hash": self.model_hash,
            "evaluation_context_hash": semantic_hash(
                {"configuration_uid": self.configuration_uid, "candidate_hash": candidate_hash}
            ),
            "prepared_by_actor_uid": self.actor_uid,
            "required_review_roles": ["technical"],
            "minimum_approval_count": 1,
            "preparer_independence_required": False,
            "created_at": "2026-08-05T00:00:00Z",
        }
        package["package_hash"] = document_hash(package, "package_hash")
        actual_package_hash = str(package["package_hash"])
        scope_uids = sorted(
            {
                str(value)
                for operation in operations
                for name in (
                    "entity_uid",
                    "object_uid",
                    "revision_uid",
                    "relation_revision_uid",
                    "record_uid",
                    "configuration_uid",
                    "baseline_uid",
                )
                for value in [operation.payload.get(name)]
                if value is not None
            }
        )
        approval = self.store.sign(
            self.trust,
            "technical",
            ApprovalPayload(
                package_hash=actual_package_hash,
                effective_model_hash=self.model_hash,
                scope={"resource_uids": scope_uids, "revision_uids": scope_uids},
                approval_type="technical",
            ),
        )
        approval_operation = SemanticOperation(
            OperationType.RECORD_APPROVAL,
            f"canonical/approvals/{approval.approval_uid}.json",
            approval.model_dump(mode="json"),
        )
        approval_value = approval.model_dump(mode="json")
        provenance_operation = SemanticOperation(
            OperationType.RECORD_PROVENANCE,
            f"canonical/provenance/{approval.provenance_uid}.json",
            _bootstrap_provenance(approval_value),
        )
        governance_operations = (
            SemanticOperation(
                OperationType.RECORD_VALIDATION_RUN,
                f"canonical/validation/runs/{run.validation_run_uid}.json",
                run.model_dump(mode="json"),
            ),
            SemanticOperation(
                OperationType.RECORD_REVIEW_PACKAGE,
                f"canonical/review_packages/{package['package_uid']}.json",
                package,
            ),
        )
        return SemanticTransaction(
            transaction_uid,
            actual_base,
            (),
            self.model_hash,
            actual_package_hash,
            operations + governance_operations + (approval_operation, provenance_operation),
            (
                ApprovalAttestation(
                    approval.approval_uid,
                    actual_package_hash,
                    approval.actor_uid,
                    approval.actor_type,
                    approval.approval_type,
                ),
            ),
            self.actor_uid,
            self.delegation_uid,
            idempotency_key,
        )


def bootstrap_repository(
    path: Path, scope_uids: tuple[str, ...] = ()
) -> CanonicalAuth:
    repository = GitCanonicalRepository(path)
    base = repository.initialize()
    actor_uid = "018f0000-0000-7000-8000-000000000701"
    delegation_uid = "018f0000-0000-7000-8000-000000000702"
    workspace_uid = "018f0000-0000-7000-8000-000000000703"
    store = ApprovalKeyStore(path.parent / f"keys-{path.name}")
    trust = store.generate(actor_uid, "Canonical test owner", ("technical",))
    raw_delegation: dict[str, object] = {
        "schema_version": "1.0",
        "resource_type": "delegation_grant",
        "delegation_uid": delegation_uid,
        "principal_uid": actor_uid,
        "principal_type": "human",
        "workspace_uid": workspace_uid,
        "base_commit": base,
        "operations": [
            "open_workspace",
            "propose_operation",
            "prepare_review",
            "apply_transaction",
        ],
        "scope": {
            "resource_uids": list(scope_uids),
            "revision_uids": list(scope_uids),
        },
        "limits": {"max_operations": 1000, "max_risk_class": "high"},
        "issued_by": actor_uid,
        "issued_at": "2026-08-05T00:00:00Z",
        "expires_at": "2099-08-05T00:00:00Z",
        "stop_conditions": [],
    }
    delegation = raw_delegation | {
        "content_hash": document_hash(raw_delegation, "content_hash")
    }
    model_hash = semantic_hash({"bootstrap": "model"})
    package_hash = semantic_hash({"bootstrap": "root-owner"})
    approval = store.sign(
        trust,
        "technical",
        ApprovalPayload(
            package_hash=package_hash,
            effective_model_hash=model_hash,
            scope={"repository": str(path.resolve())},
            approval_type="technical",
        ),
    )
    transaction = SemanticTransaction(
        uuid7_candidate(),
        base,
        (),
        model_hash,
        package_hash,
        (
            SemanticOperation(
                OperationType.REGISTER_TRUSTED_ACTOR,
                f"canonical/trust/{actor_uid}/{trust.key_uid}.json",
                trust.model_dump(mode="json"),
            ),
            SemanticOperation(
                OperationType.CREATE_DELEGATION,
                f"canonical/delegations/{delegation_uid}.json",
                delegation,
            ),
            SemanticOperation(
                OperationType.RECORD_APPROVAL,
                f"canonical/approvals/{approval.approval_uid}.json",
                approval.model_dump(mode="json"),
            ),
            SemanticOperation(
                OperationType.RECORD_PROVENANCE,
                f"canonical/provenance/{approval.provenance_uid}.json",
                _bootstrap_provenance(approval.model_dump(mode="json")),
            ),
        ),
        (
            ApprovalAttestation(
                approval.approval_uid,
                package_hash,
                actor_uid,
                "human",
                "technical",
            ),
        ),
        actor_uid,
        delegation_uid,
        "bootstrap-root-owner",
    )
    repository.apply(transaction)
    profile_revision_uid = "018f0000-0000-7000-8000-000000000706"
    configuration_uid = "018f0000-0000-7000-8000-000000000704"
    profile = ProfileRevision(
        profile_uid="018f0000-0000-7000-8000-000000000705",
        profile_revision_uid=profile_revision_uid,
        profile_kind="project",
        configuration_policies=(
            {
                "latest_fallback": False,
                "context": {
                    "*": {
                        "mandatory_predicates": [],
                        "conditional_predicates": [],
                        "invariant_object_uids": [],
                        "forbidden_sensitivities": [],
                    }
                },
            },
        ),
        review_policies=(
            {
                "operation": "apply_transaction",
                "required_roles": ["technical"],
                "minimum_approval_count": 1,
                "require_preparer_independence": False,
                "blocking_effects": ["block_operation", "require_deviation"],
            },
        ),
    )
    effective = ProfileCompiler().compile((profile,), ())
    profile_operation = SemanticOperation(
        OperationType.UPDATE_PROFILE_BINDING,
        f"canonical/profiles/{profile_revision_uid}.json",
        profile.model_dump(mode="json", exclude_none=True),
    )
    repository.apply(
        _plain_transaction(
            repository,
            store,
            trust,
            actor_uid,
            delegation_uid,
            (profile_operation,),
            effective.effective_model_hash,
            "bootstrap-test-profile",
        )
    )
    configuration = {
        "schema_version": "1.0",
        "resource_type": "configuration_snapshot",
        "configuration_uid": configuration_uid,
        "git_commit": repository.current_commit(),
        "revision_uids": [],
        "relation_revision_uids": [],
        "profile_revision_uids": [profile_revision_uid],
        "active_deviation_revision_uids": [],
        "variant": "test-harness",
        "valid_at": None,
        "effective_model_hash": effective.effective_model_hash,
        "closure_status": "complete",
        "closure_reasons": [],
        "created_at": "2026-08-05T00:00:00Z",
    }
    repository.apply(
        _plain_transaction(
            repository,
            store,
            trust,
            actor_uid,
            delegation_uid,
            (
                SemanticOperation(
                    OperationType.CREATE_CONFIGURATION,
                    f"canonical/configurations/{configuration_uid}.json",
                    configuration,
                ),
            ),
            effective.effective_model_hash,
            "bootstrap-test-configuration",
        )
    )
    return CanonicalAuth(
        repository,
        store,
        trust,
        actor_uid,
        delegation_uid,
        workspace_uid,
        configuration_uid,
        profile_revision_uid,
        effective.effective_model_hash,
    )


def _plain_transaction(
    repository: GitCanonicalRepository,
    store: ApprovalKeyStore,
    trust: TrustedActor,
    actor_uid: str,
    delegation_uid: str,
    operations: tuple[SemanticOperation, ...],
    model_hash: str,
    idempotency_key: str,
) -> SemanticTransaction:
    package_hash = semantic_hash(
        {
            "bootstrap_governance": [
                {
                    "operation_type": item.operation_type.value,
                    "resource": item.payload,
                }
                for item in operations
            ]
        }
    )
    approval = store.sign(
        trust,
        "technical",
        ApprovalPayload(
            package_hash=package_hash,
            effective_model_hash=model_hash,
            scope={"bootstrap_governance": True},
            approval_type="technical",
        ),
    )
    return SemanticTransaction(
        uuid7_candidate(),
        repository.current_commit(),
        (),
        model_hash,
        package_hash,
        operations
        + (
            SemanticOperation(
                OperationType.RECORD_APPROVAL,
                f"canonical/approvals/{approval.approval_uid}.json",
                approval.model_dump(mode="json"),
            ),
            SemanticOperation(
                OperationType.RECORD_PROVENANCE,
                f"canonical/provenance/{approval.provenance_uid}.json",
                _bootstrap_provenance(approval.model_dump(mode="json")),
            ),
        ),
        (
            ApprovalAttestation(
                approval.approval_uid,
                package_hash,
                actor_uid,
                "human",
                "technical",
            ),
        ),
        actor_uid,
        delegation_uid,
        idempotency_key,
    )


def _bootstrap_provenance(approval: dict[str, object]) -> dict[str, object]:
    value: dict[str, object] = {
        "schema_version": "1.0",
        "resource_type": "provenance_record",
        "provenance_uid": approval["provenance_uid"],
        "subject_uid": approval["approval_uid"],
        "kind": "asserted",
        "responsible_actor_uid": approval["actor_uid"],
        "performed_by_actor_uid": approval["actor_uid"],
        "on_behalf_of_actor_uid": None,
        "tool_uids": [],
        "tool_identity": "human-ed25519-bootstrap",
        "delegation_uid": None,
        "used_uids": [],
        "generated_uids": [approval["approval_uid"]],
        "review_package_uid": None,
        "validation_run_uids": [],
        "context_bundle_hash": None,
        "generated_at": approval["issued_at"],
    }
    return value | {"content_hash": document_hash(value, "content_hash")}
