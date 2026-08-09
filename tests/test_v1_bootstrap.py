from __future__ import annotations

from datetime import UTC, datetime

from lesr.application.contracts import RiskClass, WriteEnvelope
from lesr.application.runtime import LocalRuntimeService
from lesr.domain.approval import ApprovalKeyStore, ApprovalPayload
from lesr.domain.model import (
    CompositionMode,
    EffectiveModelCompiler,
    FacetDefinitionRevision,
    FieldDefinition,
    KindDefinitionRevision,
    NormativeProfileRevision,
    ProfileContextPolicy,
    ProfileContribution,
    ProfileLayer,
    ProfileReviewPolicy,
    ProfileReviewStage,
)
from lesr.domain.semantic import CoreResourceClass, SemanticField, document_hash
from lesr.domain.workspace import WorkingCopy
from tests.test_v1_rules import source


def test_public_bootstrap_installs_root_governance_and_initial_configuration(
    tmp_path,
) -> None:
    domain = LocalRuntimeService(tmp_path / "project")
    actor_uid = "018f0000-0000-7000-8000-000000000901"
    workspace_uid = "018f0000-0000-7000-8000-000000000902"
    delegation_uid = "018f0000-0000-7000-8000-000000000903"
    configuration_uid = "018f0000-0000-7000-8000-000000000904"
    store = ApprovalKeyStore(tmp_path / "keys")
    trust = store.generate(actor_uid, "Root owner", ("technical",))
    rule = source()
    design_facet = FacetDefinitionRevision(
        revision_uid="018f0000-0000-7000-8000-000000000105",
        facet_uid="018f0000-0000-7000-8000-000000000106",
        name="design_content",
        authority=100,
        fields=(FieldDefinition(path="/statement", value_type="string", required=True),),
    )
    design_kind = KindDefinitionRevision(
        revision_uid="018f0000-0000-7000-8000-000000000107",
        kind_uid="018f0000-0000-7000-8000-000000000108",
        name="software_design",
        core_class=CoreResourceClass.GOVERNED_OBJECT,
        required_facet_revision_uids=(design_facet.revision_uid,),
        authority=100,
    )
    requirement_facet = FacetDefinitionRevision(
        revision_uid="018f0000-0000-7000-8000-000000000109",
        facet_uid="018f0000-0000-7000-8000-000000000110",
        name="requirement_content",
        authority=100,
        fields=(
            FieldDefinition(path="/statement", value_type="string", required=True),
            FieldDefinition(path="/safety_level", value_type="string"),
        ),
    )
    requirement_kind = KindDefinitionRevision(
        revision_uid="018f0000-0000-7000-8000-000000000111",
        kind_uid="018f0000-0000-7000-8000-000000000112",
        name="software_requirement",
        core_class=CoreResourceClass.GOVERNED_OBJECT,
        required_facet_revision_uids=(requirement_facet.revision_uid,),
        authority=100,
    )
    semantic_definitions = (
        design_facet,
        design_kind,
        requirement_facet,
        requirement_kind,
    )
    selected_profile = NormativeProfileRevision(
        profile_revision_uid="018f0000-0000-7000-8000-000000000104",
        layer=ProfileLayer.PROJECT,
        authority=100,
        contributions=tuple(
            ProfileContribution(
                mode=CompositionMode.EXTEND,
                definition_revision_uid=item.revision_uid,
            )
            for item in semantic_definitions
        ),
        rule_revision_uids=(rule.rule_revision_uid,),
        review_policies=(
            ProfileReviewPolicy(
                operation="apply_transaction",
                require_preparer_independence=False,
                stages=(
                    ProfileReviewStage(
                        stage="apply_transaction", role="technical", minimum_count=1
                    ),
                ),
            ),
            ProfileReviewPolicy(
                operation="baseline.apply",
                require_preparer_independence=False,
                stages=(
                    ProfileReviewStage(
                            stage="baseline", role="technical", minimum_count=1
                    ),
                ),
            ),
        ),
        context_policies=(
            ProfileContextPolicy(task_type="review"),
            ProfileContextPolicy(task_type="baseline"),
        ),
    )
    model = EffectiveModelCompiler().compile(
        (selected_profile,), semantic_definitions
    )
    raw_delegation: dict[str, object] = {
        "schema_version": "1.0",
        "resource_type": "delegation_grant",
        "delegation_uid": delegation_uid,
        "principal_uid": actor_uid,
        "principal_type": "human",
        "workspace_uid": workspace_uid,
        "base_commit": domain.base,
        "operations": [
            "open_workspace",
            "propose_operation",
            "prepare_review",
            "apply_transaction",
        ],
        "scope": {"resource_uids": [], "revision_uids": []},
        "limits": {"max_operations": 100, "max_risk_class": "high"},
        "issued_by": actor_uid,
        "issued_at": "2026-08-05T00:00:00Z",
        "expires_at": "2099-08-05T00:00:00Z",
        "stop_conditions": [],
    }
    delegation = raw_delegation | {
        "content_hash": document_hash(raw_delegation, "content_hash")
    }
    governance = (
        *tuple(
            {
                "operation_type": "create_record",
                "resource": item.model_dump(mode="json"),
            }
            for item in semantic_definitions
        ),
        {
            "operation_type": "create_rule",
            "resource": rule.model_dump(mode="json", exclude_none=True),
        },
        {
            "operation_type": "update_profile_binding",
            "resource": selected_profile.model_dump(mode="json"),
        },
    )
    trust_value = trust.model_dump(mode="json")
    package_hash, model_hash, scope = domain.bootstrap_binding(
        domain.base, trust_value, delegation, governance
    )
    approval = store.sign(
        trust,
        "technical",
        ApprovalPayload(
            package_hash=package_hash,
            effective_model_hash=model_hash,
            scope=scope,
            approval_type="technical",
        ),
    )
    bootstrapped = domain.bootstrap_root_owner(
        trust_value,
        delegation,
        approval.model_dump(mode="json"),
        "public-root-bootstrap",
        governance,
    )
    assert bootstrapped.ok, bootstrapped.payload()
    configuration = {
        "schema_version": "1.0",
        "resource_type": "configuration_snapshot",
        "configuration_uid": configuration_uid,
        "git_commit": domain.base,
        "revision_uids": [],
        "relation_revision_uids": [],
        "profile_revision_uids": [selected_profile.profile_revision_uid],
        "active_deviation_revision_uids": [],
        "variant": "initial",
        "valid_at": None,
        "effective_model_hash": model.model_hash,
        "closure_status": "complete",
        "closure_reasons": [],
        "created_at": "2026-08-05T00:00:00Z",
    }
    package_hash, model_hash, scope = domain.initial_configuration_binding(
        domain.base, configuration
    )
    configuration_approval = store.sign(
        trust,
        "technical",
        ApprovalPayload(
            package_hash=package_hash,
            effective_model_hash=model_hash,
            scope=scope,
            approval_type="technical",
        ),
    )
    initialized = domain.initialize_configuration(
        configuration,
        configuration_approval.model_dump(mode="json"),
        actor_uid,
        delegation_uid,
        "initialize-first-configuration",
    )
    assert initialized.ok, initialized.payload()
    assert LocalRuntimeService(domain.repository.path).base == initialized.value[
        "result_commit"
    ]
    assert not domain.bootstrap_root_owner(
        trust_value,
        delegation,
        approval.model_dump(mode="json"),
        "second-bootstrap",
        governance,
    ).ok

    opened = domain.open_workspace(
        WriteEnvelope(
            workspace_uid,
            domain.base,
            "open-across-process",
            actor_uid,
            delegation_uid,
            False,
            RiskClass.MEDIUM,
            {"configuration_uid": configuration_uid},
        )
    )
    assert opened.ok, opened.payload()
    domain = LocalRuntimeService(domain.repository.path)
    assert workspace_uid in domain.workspaces

    object_uid = "018f0000-0000-7000-8000-000000000905"
    working_copy = WorkingCopy(
        workspace_uid=workspace_uid,
        object_uid=object_uid,
        base_revision_uid=None,
        human_key="DES-BOOT-1",
        kind="software_design",
        effective_model_hash=model.model_hash,
        delegation_uid=delegation_uid,
        draft_fields=(SemanticField(path="/statement", value="Bootstrap design"),),
    )
    proposed = domain.propose_operation(
        WriteEnvelope(
            workspace_uid,
            domain.base,
            "create-across-process",
            actor_uid,
            delegation_uid,
            False,
            RiskClass.MEDIUM,
            {
                "operation_type": "create_object",
                "working_copy": working_copy.model_dump(mode="json"),
            },
        )
    )
    assert proposed.ok, proposed.payload()
    domain = LocalRuntimeService(domain.repository.path)
    prepared = domain.prepare_review(
        WriteEnvelope(
            workspace_uid,
            domain.base,
            "review-across-process",
            actor_uid,
            delegation_uid,
            False,
            RiskClass.HIGH,
            {
                "configuration_uid": configuration_uid,
                "evaluation_time": datetime.now(UTC).isoformat(),
            },
        )
    )
    assert prepared.ok, prepared.payload()
    package_value = prepared.value["review_package"]
    domain = LocalRuntimeService(domain.repository.path)
    assert package_value["package_uid"] in domain.reviews
    package = domain.reviews[package_value["package_uid"]]
    final_approval = store.sign(
        trust,
        "technical",
        ApprovalPayload(
            package_hash=package.package_hash,
            effective_model_hash=package.effective_model_hash,
            scope={"resource_uids": list(package.candidate_scope)},
            approval_type="apply_transaction",
        ),
    )
    applied = domain.apply_transaction(
        WriteEnvelope(
            workspace_uid,
            domain.base,
            "apply-across-process",
            actor_uid,
            delegation_uid,
            False,
            RiskClass.HIGH,
            {
                "review_package_uid": package.package_uid,
                "signed_approvals": [final_approval.model_dump(mode="json")],
                "evaluation_time": datetime.now(UTC).isoformat(),
            },
        )
    )
    assert applied.ok, applied.payload()
    documents = [value for _, value in domain.repository.documents()]
    assert any(item.get("object_uid") == object_uid for item in documents)
    assert any(item.get("resource_type") == "graph_snapshot" for item in documents)

    baseline_workspace_uid = "018f0000-0000-7000-8000-000000000906"
    baseline_prepared = domain.prepare_baseline(
        WriteEnvelope(
            baseline_workspace_uid,
            domain.base,
            "baseline-prepare-across-process",
            actor_uid,
            delegation_uid,
            False,
            RiskClass.HIGH,
            {
                "configuration_uid": configuration_uid,
                "evaluation_time": datetime.now(UTC).isoformat(),
            },
        )
    )
    assert baseline_prepared.ok, baseline_prepared.payload()
    baseline_package_uid = baseline_prepared.value["review_package"]["package_uid"]
    domain = LocalRuntimeService(domain.repository.path)
    baseline_package = domain.reviews[baseline_package_uid]
    baseline_approval = store.sign(
        trust,
        "technical",
        ApprovalPayload(
            package_hash=baseline_package.package_hash,
            effective_model_hash=baseline_package.effective_model_hash,
            scope={"resource_uids": list(baseline_package.candidate_scope)},
            approval_type="baseline",
        ),
    )
    baseline_applied = domain.apply_baseline(
        WriteEnvelope(
            baseline_workspace_uid,
            domain.base,
            "baseline-apply-across-process",
            actor_uid,
            delegation_uid,
            False,
            RiskClass.HIGH,
            {
                "review_package_uid": baseline_package_uid,
                "signed_approvals": [baseline_approval.model_dump(mode="json")],
                "evaluation_time": datetime.now(UTC).isoformat(),
            },
        )
    )
    assert baseline_applied.ok, baseline_applied.payload()
    documents = [value for _, value in domain.repository.documents()]
    assert any(item.get("resource_type") == "baseline_manifest" for item in documents)
