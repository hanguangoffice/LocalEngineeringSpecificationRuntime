from __future__ import annotations

import sqlite3
from dataclasses import replace
from pathlib import Path

from typer.testing import CliRunner

from lesr.adapters.git import (
    OperationType,
    SemanticOperation,
)
from lesr.adapters.schemas import SchemaCatalog
from lesr.application.contracts import RiskClass, WriteEnvelope
from lesr.application.service import RepositoryDomainService
from lesr.cli.main import app
from lesr.domain.approval import ApprovalKeyStore, ApprovalPayload
from lesr.domain.profiles import ProfileCompiler, ProfileRevision
from lesr.domain.rules import (
    EnforcementEffect,
    EnforcementMapping,
    FixtureKind,
    KindIs,
    RuleDefinition,
    RuleOutcome,
)
from lesr.domain.semantic import document_hash, semantic_hash
from tests.support.canonical_auth import bootstrap_repository
from tests.test_v1_rules import source

OBJECT_UID = "018f0000-0000-7000-8000-000000000001"
REVISION_UID = "018f0000-0000-7000-8000-000000000002"
TRANSACTION_UID = "018f0000-0000-7000-8000-000000000005"
PACKAGE_UID = "018f0000-0000-7000-8000-000000000007"
BASELINE_UID = "018f0000-0000-7000-8000-000000000008"
CONFIGURATION_UID = "018f0000-0000-7000-8000-000000000009"


def canonical_resources() -> tuple[dict[str, object], dict[str, object]]:
    logical: dict[str, object] = {
        "schema_version": "1.0",
        "resource_type": "logical_object",
        "entity_uid": OBJECT_UID,
        "namespace": "demo",
        "human_key": "REQ-SW-0001",
        "kind": "software_requirement",
        "core_class": "governed_object",
        "facets": ["authored", "traceability"],
        "aliases": [],
        "external_identities": [],
        "created_at": "2026-08-05T00:00:00Z",
    }
    revision_without_hash: dict[str, object] = {
        "schema_version": "1.0",
        "resource_type": "revision",
        "revision_uid": REVISION_UID,
        "object_uid": OBJECT_UID,
        "revision_number": 1,
        "parent_revision_uid": None,
        "human_key": "REQ-SW-0001",
        "kind": "software_requirement",
        "facets": ["authored", "traceability"],
        "fields": [{"path": "/statement", "value": "The client shall reconnect."}],
        "fragments": [],
        "provenance_origin": "authored",
        "created_at": "2026-08-05T00:00:00Z",
    }
    return logical, revision_without_hash | {"content_hash": semantic_hash(revision_without_hash)}


def baseline_manifest(base_commit: str, model_hash: str) -> dict[str, object]:
    manifest: dict[str, object] = {
        "schema_version": "1.0",
        "resource_type": "baseline_manifest",
        "baseline_uid": BASELINE_UID,
        "git_commit": base_commit,
        "revision_uids": [REVISION_UID],
        "relation_revision_uids": [],
        "profile_revision_uids": [],
        "configuration_uid": CONFIGURATION_UID,
        "effective_model_hash": model_hash,
        "deviation_revision_uids": [],
        "external_references": [],
        "evidence_revision_uids": [],
        "created_at": "2026-08-05T00:00:00Z",
    }
    return manifest | {"manifest_hash": document_hash(manifest, "manifest_hash")}


def test_reviewed_multi_resource_apply_resolve_and_projection_rebuild(tmp_path: Path) -> None:
    authorization = bootstrap_repository(tmp_path / "project")
    repository = authorization.repository
    logical, revision = canonical_resources()
    transaction = authorization.transaction(
        transaction_uid=TRANSACTION_UID,
        idempotency_key="e2e-reviewed-apply",
        operations=(
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
        ),
    )
    content_applied = repository.apply(transaction)
    baseline = baseline_manifest(content_applied.commit, authorization.model_hash)
    baseline |= {
        "configuration_uid": authorization.configuration_uid,
        "profile_revision_uids": [authorization.profile_revision_uid],
        "effective_model_hash": authorization.model_hash,
    }
    baseline["manifest_hash"] = document_hash(baseline, "manifest_hash")
    applied = repository.apply(
        authorization.transaction(
            transaction_uid="018f0000-0000-7000-8000-000000000017",
            base_commit=content_applied.commit,
            operations=(
                SemanticOperation(
                    OperationType.CREATE_BASELINE,
                    f"canonical/baselines/{BASELINE_UID}.json",
                    baseline,
                ),
            ),
            idempotency_key="e2e-reviewed-baseline",
        )
    )
    assert not content_applied.idempotent_replay
    catalog = SchemaCatalog()
    catalog.validate(
        "baseline-manifest.schema.json",
        repository.read_json(
            applied.commit, f"canonical/baselines/{BASELINE_UID}.json"
        ),
    )
    for schema_name, path in (
        (
            "applied-change.schema.json",
                f"canonical/applied_changes/{TRANSACTION_UID}.json",
        ),
        (
            "provenance.schema.json",
            f"canonical/provenance/{TRANSACTION_UID}.json",
        ),
        (
            "audit-anchor.schema.json",
            f"canonical/audit_anchors/{TRANSACTION_UID}.json",
        ),
    ):
        catalog.validate(schema_name, repository.read_json(applied.commit, path))
    domain = RepositoryDomainService(repository.path)
    assert domain.resolve("REQ-SW-0001").ok
    discovered = domain.query(None, None, 20, "reconnect")
    assert discovered.ok and discovered.value["total"] >= 1
    traversed = domain.traverse(OBJECT_UID, None, 4)
    assert traversed.ok and traversed.value["start_object_uid"] == OBJECT_UID
    assert repository.verify_audit_chain(applied.commit)

    database = tmp_path / "projection.sqlite3"
    assert repository.rebuild_projection(database) == applied.commit
    with sqlite3.connect(database) as connection:
        meta = connection.execute(
            "SELECT source_commit, schema_version, completeness FROM projection_meta"
        ).fetchone()
        assert meta == (applied.commit, "1.0", "complete")
        assert connection.execute("SELECT count(*) FROM documents_fts").fetchone()[0] >= 2


def test_cli_exposes_v1_capabilities_without_legacy_commands() -> None:
    result = CliRunner().invoke(app, ["--help"])
    assert result.exit_code == 0
    for capability in ("resolve", "inspect", "query", "context", "workspace", "approval", "apply", "baseline", "projection", "reconcile", "mcp"):
        assert capability in result.stdout
    assert "artifact-create" not in result.stdout
    assert "import-accept" not in result.stdout


def test_profile_governed_review_validation_and_apply_are_not_caller_defined(
    tmp_path: Path,
) -> None:
    authorization = bootstrap_repository(
        tmp_path / "governed-project", (OBJECT_UID, REVISION_UID)
    )
    repository = authorization.repository
    raw_rule = source().model_dump(mode="json", exclude={"content_hash"})
    outcome_by_kind = {
        FixtureKind.POSITIVE.value: RuleOutcome.PASS.value,
        FixtureKind.NEGATIVE.value: RuleOutcome.FAIL.value,
        FixtureKind.NOT_APPLICABLE.value: RuleOutcome.NOT_APPLICABLE.value,
        FixtureKind.INDETERMINATE.value: RuleOutcome.INDETERMINATE.value,
        FixtureKind.EXCEPTION.value: RuleOutcome.NOT_APPLICABLE.value,
        FixtureKind.DEVIATION.value: RuleOutcome.SUPPRESSED_BY_DEVIATION.value,
        FixtureKind.CONFLICT.value: RuleOutcome.INDETERMINATE.value,
        FixtureKind.MIGRATION.value: RuleOutcome.PASS.value,
    }
    for fixture in raw_rule["fixtures"]:
        environment = fixture["environment"]
        environment["operation"] = "apply_transaction"
        environment["fields"] = {
            "/statement": {"state": "value", "value": "A governed statement"}
        }
        if fixture["kind"] in {"negative", "deviation"}:
            environment["fields"] = {}
        if fixture["kind"] == "indeterminate":
            environment["fields"] = {"/statement": {"state": "unknown", "value": None}}
        fixture["expected_outcome"] = outcome_by_kind[fixture["kind"]]
    raw_rule |= {
        "applicability": KindIs("software_requirement").to_data(),
        "constraints": [{"op": "field_required", "path": "/statement"}],
        "enforcement": [
            EnforcementMapping(
                operation="apply_transaction",
                effect=EnforcementEffect.BLOCK_OPERATION,
            ).model_dump(mode="json")
        ],
    }
    rule = RuleDefinition.model_validate(raw_rule)
    profile = ProfileRevision(
        profile_uid="018f0000-0000-7000-8000-000000000104",
        profile_revision_uid=rule.authority.profile_revision_uid,
        profile_kind="project",
        resource_kinds=(
            {
                "kind": "software_requirement",
                "fields": [{"path": "/statement", "type": "string"}],
            },
        ),
        rule_revision_uids=(rule.rule_revision_uid,),
        configuration_policies=(
            {
                "latest_fallback": False,
                "context": {
                    "requirement_change": {
                        "mandatory_predicates": [],
                        "conditional_predicates": [],
                        "invariant_object_uids": [],
                        "forbidden_sensitivities": ["secret"],
                    }
                },
            },
        ),
        review_policies=(
            {
                "operation": "apply_transaction",
                "required_roles": ["technical"],
                "minimum_approval_count": 1,
                "require_preparer_independence": True,
                "blocking_effects": ["block_operation", "require_deviation"],
            },
        ),
    )
    model = ProfileCompiler().compile((profile,), (rule,))
    governance = authorization.transaction(
        transaction_uid="018f0000-0000-7000-8000-000000000801",
        idempotency_key="install-governance",
        operations=(
            SemanticOperation(
                OperationType.CREATE_RULE,
                f"canonical/rules/{rule.rule_revision_uid}.json",
                rule.model_dump(mode="json", exclude_none=True),
            ),
            SemanticOperation(
                OperationType.UPDATE_PROFILE_BINDING,
                f"canonical/profiles/{profile.profile_revision_uid}.json",
                profile.model_dump(mode="json", exclude_none=True),
            ),
        ),
    )
    governance_commit = repository.apply(governance).commit
    configuration = {
        "schema_version": "1.0",
        "resource_type": "configuration_snapshot",
        "configuration_uid": CONFIGURATION_UID,
        "git_commit": governance_commit,
        "revision_uids": [],
        "relation_revision_uids": [],
        "profile_revision_uids": [profile.profile_revision_uid],
        "active_deviation_revision_uids": [],
        "variant": "review-gate-test",
        "valid_at": None,
        "effective_model_hash": model.effective_model_hash,
        "closure_status": "complete",
        "closure_reasons": [],
        "created_at": "2026-08-05T00:00:00Z",
    }
    repository.apply(
        authorization.transaction(
            transaction_uid="018f0000-0000-7000-8000-000000000802",
            idempotency_key="install-configuration",
            operations=(
                SemanticOperation(
                    OperationType.CREATE_CONFIGURATION,
                    f"canonical/configurations/{CONFIGURATION_UID}.json",
                    configuration,
                ),
            ),
        )
    )
    reviewer_store = ApprovalKeyStore(tmp_path / "reviewer-keys")
    reviewer_uid = "018f0000-0000-7000-8000-000000000803"
    reviewer = reviewer_store.generate(reviewer_uid, "Independent reviewer", ("technical",))
    repository.apply(
        authorization.transaction(
            transaction_uid="018f0000-0000-7000-8000-000000000804",
            idempotency_key="register-reviewer",
            operations=(
                SemanticOperation(
                    OperationType.REGISTER_TRUSTED_ACTOR,
                    f"canonical/trust/{reviewer_uid}/{reviewer.key_uid}.json",
                    reviewer.model_dump(mode="json"),
                ),
            ),
        )
    )
    domain = RepositoryDomainService(repository.path)
    envelope = WriteEnvelope(
        authorization.workspace_uid,
        domain.base,
        "open-governed-workspace",
        authorization.actor_uid,
        authorization.delegation_uid,
        False,
        RiskClass.HIGH,
        {"type": "open_workspace"},
    )
    assert domain.open_workspace(envelope).ok
    logical, revision = canonical_resources()
    for index, operation in enumerate(
        (
            {"operation_type": "create_logical_object", "resource": logical},
            {"operation_type": "create_revision", "resource": revision},
        )
    ):
        assert domain.propose_operation(
            replace(
                envelope,
                idempotency_key=f"propose-{index}",
                operation=operation,
            )
        ).ok
    bypass = domain.apply_transaction(
        replace(
            envelope,
            idempotency_key="caller-defined-empty-validation",
            operation={
                "transaction_uid": "018f0000-0000-7000-8000-000000000806",
                "review_package_uid": PACKAGE_UID,
                "review_package": {"required_review_roles": []},
                "effective_model_hash": semantic_hash({"profiles": []}),
                "operations": [],
                "signed_approvals": [],
            },
        )
    )
    assert not bypass.ok
    prepared = domain.prepare_review(
        replace(
            envelope,
            idempotency_key="prepare-system-review",
            operation={"configuration_uid": CONFIGURATION_UID},
        )
    )
    assert prepared.ok
    package = prepared.value["review_package"]
    assert prepared.value["validation_run"]["outcome"] == "pass"
    assert package["required_review_roles"] == ["technical"]
    assert package["validation_run_uids"]
    assert package["effective_model_hash"] == model.effective_model_hash
    signed = reviewer_store.sign(
        reviewer,
        "technical",
        ApprovalPayload(
            package_hash=package["package_hash"],
            effective_model_hash=model.effective_model_hash,
            scope={
                "resource_uids": [OBJECT_UID, REVISION_UID],
                "revision_uids": [REVISION_UID],
            },
            approval_type="technical",
        ),
    )
    transaction_uid = "018f0000-0000-7000-8000-000000000805"
    applied = domain.apply_transaction(
        replace(
            envelope,
            idempotency_key="governed-apply",
            operation={
                "transaction_uid": transaction_uid,
                "review_package_uid": package["package_uid"],
                "signed_approvals": [signed.model_dump(mode="json")],
            },
        )
    )
    assert applied.ok, applied.payload()
    assert domain.repository.read_json(
        applied.value["result_commit"],
        f"canonical/review_packages/{package['package_uid']}.json",
    ) == package
    replayed = domain.apply_transaction(
        replace(
            envelope,
            idempotency_key="governed-apply",
            operation={
                "transaction_uid": transaction_uid,
                "review_package_uid": package["package_uid"],
                "signed_approvals": [signed.model_dump(mode="json")],
            },
        )
    )
    assert replayed.ok and replayed.value["idempotent_replay"] is True
