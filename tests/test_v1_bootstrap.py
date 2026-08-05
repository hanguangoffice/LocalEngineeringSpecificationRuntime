from __future__ import annotations

from lesr.application.service import RepositoryDomainService
from lesr.domain.approval import ApprovalKeyStore, ApprovalPayload
from lesr.domain.profiles import ProfileCompiler
from lesr.domain.semantic import document_hash
from tests.test_v1_profiles import profile
from tests.test_v1_rules import source


def test_public_bootstrap_installs_root_governance_and_initial_configuration(
    tmp_path,
) -> None:
    domain = RepositoryDomainService(tmp_path / "project")
    actor_uid = "018f0000-0000-7000-8000-000000000901"
    workspace_uid = "018f0000-0000-7000-8000-000000000902"
    delegation_uid = "018f0000-0000-7000-8000-000000000903"
    configuration_uid = "018f0000-0000-7000-8000-000000000904"
    store = ApprovalKeyStore(tmp_path / "keys")
    trust = store.generate(actor_uid, "Root owner", ("technical",))
    rule = source()
    selected_profile = profile(rule.rule_revision_uid)
    model = ProfileCompiler().compile((selected_profile,), (rule,))
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
        {
            "operation_type": "create_rule",
            "resource": rule.model_dump(mode="json", exclude_none=True),
        },
        {
            "operation_type": "update_profile_binding",
            "resource": selected_profile.model_dump(mode="json", exclude_none=True),
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
        "effective_model_hash": model.effective_model_hash,
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
    assert RepositoryDomainService(domain.repository.path).base == initialized.value[
        "result_commit"
    ]
    assert not domain.bootstrap_root_owner(
        trust_value,
        delegation,
        approval.model_dump(mode="json"),
        "second-bootstrap",
        governance,
    ).ok
