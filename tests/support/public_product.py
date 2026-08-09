from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from lesr.application.runtime import LocalRuntimeService
from lesr.domain.approval import ApprovalKeyStore, ApprovalPayload, TrustedActor
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
from lesr.domain.semantic import CoreResourceClass, document_hash
from tests.test_v1_rules import source


@dataclass(frozen=True, slots=True)
class PublicProduct:
    domain: LocalRuntimeService
    store: ApprovalKeyStore
    trust: TrustedActor
    actor_uid: str
    workspace_uid: str
    delegation_uid: str
    configuration_uid: str
    signer_password: str


def bootstrap_public_product(root: Path) -> PublicProduct:
    project = root / "project"
    domain = LocalRuntimeService(project)
    actor_uid = "018f0000-0000-7000-8000-000000000901"
    workspace_uid = "018f0000-0000-7000-8000-000000000902"
    delegation_uid = "018f0000-0000-7000-8000-000000000903"
    configuration_uid = "018f0000-0000-7000-8000-000000000904"
    signer_password = "public-product-ci-password"
    store = ApprovalKeyStore(root / "keys", password=signer_password)
    trust = store.generate(actor_uid, "Root owner", ("technical",))
    rule = source()
    requirement_facet = FacetDefinitionRevision(
        revision_uid="018f0000-0000-7000-8000-000000000110",
        facet_uid="018f0000-0000-7000-8000-000000000111",
        name="requirement_content",
        authority=100,
        fields=(
            FieldDefinition(path="/statement", value_type="string", required=True),
            FieldDefinition(path="/safety_level", value_type="string"),
        ),
    )
    design_facet = FacetDefinitionRevision(
        revision_uid="018f0000-0000-7000-8000-000000000112",
        facet_uid="018f0000-0000-7000-8000-000000000113",
        name="design_content",
        authority=100,
        fields=(FieldDefinition(path="/statement", value_type="string", required=True),),
    )
    requirement_kind = KindDefinitionRevision(
        revision_uid="018f0000-0000-7000-8000-000000000114",
        kind_uid="018f0000-0000-7000-8000-000000000115",
        name="software_requirement",
        core_class=CoreResourceClass.GOVERNED_OBJECT,
        required_facet_revision_uids=(requirement_facet.revision_uid,),
        authority=100,
    )
    design_kind = KindDefinitionRevision(
        revision_uid="018f0000-0000-7000-8000-000000000116",
        kind_uid="018f0000-0000-7000-8000-000000000117",
        name="software_design",
        core_class=CoreResourceClass.GOVERNED_OBJECT,
        required_facet_revision_uids=(design_facet.revision_uid,),
        authority=100,
    )
    semantic_definitions = (
        requirement_facet,
        design_facet,
        requirement_kind,
        design_kind,
    )
    profile = NormativeProfileRevision(
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
    model = EffectiveModelCompiler().compile((profile,), semantic_definitions)
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
            "resource": profile.model_dump(mode="json"),
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
    result = domain.bootstrap_root_owner(
        trust_value,
        delegation,
        approval.model_dump(mode="json"),
        "public-product-bootstrap",
        governance,
    )
    if not result.ok:
        raise RuntimeError(str(result.payload()))
    configuration = {
        "schema_version": "1.0",
        "resource_type": "configuration_snapshot",
        "configuration_uid": configuration_uid,
        "git_commit": domain.base,
        "revision_uids": [],
        "relation_revision_uids": [],
        "profile_revision_uids": [profile.profile_revision_uid],
        "active_deviation_revision_uids": [],
        "variant": "public-product",
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
    configured = domain.initialize_configuration(
        configuration,
        configuration_approval.model_dump(mode="json"),
        actor_uid,
        delegation_uid,
        "public-product-configuration",
    )
    if not configured.ok:
        raise RuntimeError(str(configured.payload()))
    return PublicProduct(
        domain,
        store,
        trust,
        actor_uid,
        workspace_uid,
        delegation_uid,
        configuration_uid,
        signer_password,
    )
