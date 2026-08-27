from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from lesr.application.contracts import RiskClass, WriteEnvelope
from lesr.domain.approval import ApprovalPayload
from lesr.domain.model import (
    FacetDefinitionRevision,
    FieldDefinition,
    KindDefinitionRevision,
)
from lesr.domain.rules import (
    AllOf,
    EnforcementEffect,
    EnforcementMapping,
    FieldKnown,
    FixtureKind,
    KindIs,
    RelationMinimum,
    RuleDefinition,
    RuleFixtureDefinition,
    RuleOutcome,
    ValueCell,
    ValueState,
)
from lesr.domain.semantic import (
    ConfigurationSnapshot,
    CoreResourceClass,
    Revision,
    SemanticField,
    governance_subject_hash,
)
from lesr.domain.workspace import WorkingCopy
from tests.support.public_product import PublicProduct, bootstrap_public_product
from tests.test_v1_rules import environment_data, source


def _finding_rule(effect: EnforcementEffect) -> RuleDefinition:
    base = source()
    rule_uid = "018f0000-0000-7000-8000-000000000991"
    cases = (
        (FixtureKind.POSITIVE, environment_data(kind="software_design"), RuleOutcome.PASS),
        (
            FixtureKind.NEGATIVE,
            environment_data(kind="software_design", relation_count=0),
            RuleOutcome.FAIL,
        ),
        (
            FixtureKind.NOT_APPLICABLE,
            environment_data(kind="software_requirement"),
            RuleOutcome.NOT_APPLICABLE,
        ),
        (
            FixtureKind.INDETERMINATE,
            environment_data(
                kind="software_design",
                statement=ValueCell(ValueState.UNKNOWN),
            ),
            RuleOutcome.INDETERMINATE,
        ),
        (
            FixtureKind.EXCEPTION,
            environment_data(
                kind="software_design",
                active_exception_rule_uids=frozenset((rule_uid,)),
            ),
            RuleOutcome.NOT_APPLICABLE,
        ),
        (
            FixtureKind.DEVIATION,
            environment_data(
                kind="software_design",
                relation_count=0,
                active_deviation_rule_uids=frozenset((rule_uid,)),
            ),
            RuleOutcome.SUPPRESSED_BY_DEVIATION,
        ),
        (
            FixtureKind.CONFLICT,
            environment_data(
                kind="software_design",
                conflicted_rule_uids=frozenset((rule_uid,)),
            ),
            RuleOutcome.INDETERMINATE,
        ),
        (
            FixtureKind.MIGRATION,
            environment_data(kind="software_design", schema_version=2),
            RuleOutcome.PASS,
        ),
    )
    fixtures = tuple(
        RuleFixtureDefinition(
            fixture_uid=f"018f0000-0000-7000-8000-{index:012d}",
            kind=kind,
            environment=environment,
            expected_outcome=outcome,
        )
        for index, (kind, environment, outcome) in enumerate(cases, 991)
    )
    return RuleDefinition.model_validate(
        base.model_dump(mode="json", exclude={"content_hash"})
        | {
            "rule_uid": rule_uid,
            "rule_revision_uid": "018f0000-0000-7000-8000-000000000992",
            "target_selector": KindIs("software_design").to_data(),
            "applicability": AllOf(
                (KindIs("software_design"), FieldKnown("statement"))
            ).to_data(),
            "constraints": [RelationMinimum("verified_by", 1).to_data()],
            "enforcement": [
                EnforcementMapping(
                    operation="apply_transaction", effect=effect
                ).model_dump(mode="json")
            ],
            "fixtures": [item.model_dump(mode="json") for item in fixtures],
        }
    )


def _write(
    product: PublicProduct,
    key: str,
    operation: dict[str, object],
) -> WriteEnvelope:
    return WriteEnvelope(
        product.workspace_uid,
        product.domain.base,
        key,
        product.actor_uid,
        product.delegation_uid,
        False,
        RiskClass.HIGH,
        operation,
    )


@pytest.mark.parametrize(
    ("effect", "finding_approval_type"),
    (
        (EnforcementEffect.REQUIRE_ACKNOWLEDGEMENT, "finding_acknowledgement"),
        (EnforcementEffect.REQUIRE_REVIEW, "finding_review"),
    ),
)
def test_public_apply_requires_exact_finding_attestation(
    tmp_path: Path,
    effect: EnforcementEffect,
    finding_approval_type: str,
) -> None:
    product = bootstrap_public_product(tmp_path, rule=_finding_rule(effect))
    opened = product.domain.open_workspace(
        _write(
            product,
            f"open-{effect.value}",
            {"configuration_uid": product.configuration_uid},
        )
    )
    assert opened.ok, opened.payload()
    copy = WorkingCopy(
        workspace_uid=product.workspace_uid,
        object_uid="018f0000-0000-7000-8000-000000000993",
        base_revision_uid=None,
        human_key=f"DES-{effect.value.upper()}",
        kind="software_design",
        effective_model_hash=str(opened.value["effective_model_hash"]),
        delegation_uid=product.delegation_uid,
        draft_fields=(SemanticField(path="/statement", value="No trace yet"),),
    )
    edited = product.domain.propose_operation(
        _write(
            product,
            f"edit-{effect.value}",
            {
                "operation_type": "create_object",
                "working_copy": copy.model_dump(mode="json"),
            },
        )
    )
    assert edited.ok, edited.payload()
    evaluation_time = datetime.now(UTC).isoformat()
    prepared = product.domain.prepare_review(
        _write(
            product,
            f"review-{effect.value}",
            {"evaluation_time": evaluation_time},
        )
    )
    assert prepared.ok, prepared.payload()
    package = product.domain.reviews[prepared.value["review_package"]["package_uid"]]
    findings = prepared.value["validation"]["findings"]
    assert len(findings) == 1
    finding_uid = str(findings[0]["finding_uid"])
    assert package.governance_finding_uids == (finding_uid,)
    review = product.store.sign(
        product.trust,
        "technical",
        ApprovalPayload(
            package_hash=package.package_hash,
            effective_model_hash=package.effective_model_hash,
            scope={"resource_uids": list(package.candidate_scope)},
            approval_type="apply_transaction",
        ),
    )
    rejected = product.domain.apply_transaction(
        _write(
            product,
            f"reject-{effect.value}",
            {
                "review_package_uid": package.package_uid,
                "signed_approvals": [review.model_dump(mode="json")],
                "evaluation_time": evaluation_time,
            },
        )
    )
    assert not rejected.ok
    assert rejected.error is not None
    assert rejected.error.code == "LESR-GOVERNANCE-NOT-SATISFIED"
    finding_approval = product.store.sign(
        product.trust,
        "technical",
        ApprovalPayload(
            package_hash=package.package_hash,
            effective_model_hash=package.effective_model_hash,
            scope={"finding_uid": finding_uid},
            approval_type=finding_approval_type,
        ),
    )
    apply_time = datetime.now(UTC).isoformat()
    applied = product.domain.apply_transaction(
        _write(
            product,
            f"apply-{effect.value}",
            {
                "review_package_uid": package.package_uid,
                "signed_approvals": [
                    review.model_dump(mode="json"),
                    finding_approval.model_dump(mode="json"),
                ],
                "evaluation_time": apply_time,
            },
        )
    )
    assert applied.ok, applied.payload()
    assert applied.value["result_commit"] == product.domain.base


def _apply_working_copy(
    product: PublicProduct,
    copy: WorkingCopy,
    key: str,
) -> dict[str, object]:
    opened = product.domain.open_workspace(
        _write(product, f"open-{key}", {"configuration_uid": product.configuration_uid})
    )
    assert opened.ok, opened.payload()
    edited = product.domain.propose_operation(
        _write(
            product,
            f"edit-{key}",
            {
                "operation_type": "create_object",
                "working_copy": copy.model_dump(mode="json"),
            },
        )
    )
    assert edited.ok, edited.payload()
    prepared = product.domain.prepare_review(
        _write(
            product,
            f"review-{key}",
            {"evaluation_time": datetime.now(UTC).isoformat()},
        )
    )
    assert prepared.ok, prepared.payload()
    package = product.domain.reviews[prepared.value["review_package"]["package_uid"]]
    approval = product.store.sign(
        product.trust,
        "technical",
        ApprovalPayload(
            package_hash=package.package_hash,
            effective_model_hash=package.effective_model_hash,
            scope={"resource_uids": list(package.candidate_scope)},
            approval_type="apply_transaction",
        ),
    )
    applied = product.domain.apply_transaction(
        _write(
            product,
            f"apply-{key}",
            {
                "review_package_uid": package.package_uid,
                "signed_approvals": [approval.model_dump(mode="json")],
                "evaluation_time": datetime.now(UTC).isoformat(),
            },
        )
    )
    assert applied.ok, applied.payload()
    return {"prepared": prepared.value, "applied": applied.value}


def test_deviation_can_be_created_approved_activated_and_applied_publicly(
    tmp_path: Path,
) -> None:
    deviation_facet = FacetDefinitionRevision(
        revision_uid="018f0000-0000-7000-8000-000000000980",
        facet_uid="018f0000-0000-7000-8000-000000000981",
        name="deviation_governance",
        authority=100,
        fields=(
            FieldDefinition(path="/subject_uid", value_type="string", required=True),
            FieldDefinition(path="/rule_revision_uid", value_type="string", required=True),
            FieldDefinition(path="/valid_until", value_type="timestamp", required=True),
            FieldDefinition(
                path="/compensating_control", value_type="string", required=True
            ),
        ),
    )
    deviation_kind = KindDefinitionRevision(
        revision_uid="018f0000-0000-7000-8000-000000000982",
        kind_uid="018f0000-0000-7000-8000-000000000983",
        name="deviation",
        core_class=CoreResourceClass.GOVERNED_OBJECT,
        required_facet_revision_uids=(deviation_facet.revision_uid,),
        authority=100,
    )
    product = bootstrap_public_product(
        tmp_path,
        extra_definitions=(deviation_facet, deviation_kind),
        actor_roles=("technical", "risk_deviation"),
    )
    requirement_uid = "018f0000-0000-7000-8000-000000000984"
    deviation_copy = WorkingCopy(
        workspace_uid=product.workspace_uid,
        object_uid="018f0000-0000-7000-8000-000000000985",
        base_revision_uid=None,
        human_key="DEV-PUBLIC-1",
        kind="deviation",
        effective_model_hash=product.domain._configuration(
            product.configuration_uid
        )["effective_model_hash"],
        delegation_uid=product.delegation_uid,
        draft_fields=(
            SemanticField(path="/subject_uid", value=requirement_uid),
            SemanticField(path="/rule_revision_uid", value=source().rule_revision_uid),
            SemanticField(
                path="/valid_until",
                value=(datetime.now(UTC) + timedelta(days=2)).isoformat(),
            ),
            SemanticField(
                path="/compensating_control", value="Independent runtime monitor"
            ),
        ),
    )
    deviation_result = _apply_working_copy(product, deviation_copy, "deviation")
    deviation_revision = Revision.model_validate(
        next(
            value
            for _, value in product.domain.repository.documents()
            if value.get("resource_type") == "revision"
            and value.get("object_uid") == deviation_copy.object_uid
        )
    )
    current_configuration = ConfigurationSnapshot.model_validate(
        product.domain._configuration(
            str(deviation_result["applied"]["configuration_uid"])
        )
    )
    draft_configuration = current_configuration.model_dump(
        mode="json", exclude={"configuration_hash", "state_anchor"}
    ) | {
        "configuration_uid": "018f0000-0000-7000-8000-000000000986",
        "parent_configuration_uid": current_configuration.configuration_uid,
        "base_commit": product.domain.base,
        "active_deviation_revision_uids": [deviation_revision.revision_uid],
        "created_at": datetime.now(UTC).isoformat(),
    }
    planned = product.domain.plan_configuration(draft_configuration)
    assert planned.ok, planned.payload()
    planned_configuration = ConfigurationSnapshot.model_validate(planned.value)
    deviation_hash = governance_subject_hash(deviation_revision)
    deviation_scope: dict[str, object] = {
        "deviation_revision_uid": deviation_revision.revision_uid,
        "deviation_hash": deviation_hash,
        "rule_revision_uid": source().rule_revision_uid,
        "subject_uid": requirement_uid,
    }
    wrong_role_approval = product.store.sign(
        product.trust,
        "technical",
        ApprovalPayload(
            package_hash=deviation_hash,
            effective_model_hash=planned_configuration.effective_model_hash,
            scope=deviation_scope,
            approval_type="deviation",
            expires_at=datetime.now(UTC) + timedelta(days=1),
        ),
    )
    recorded_wrong_role = product.domain.record_governance_approval(
        wrong_role_approval.model_dump(mode="json"),
        product.actor_uid,
        product.delegation_uid,
        "record-wrong-role-deviation-approval",
    )
    assert recorded_wrong_role.ok, recorded_wrong_role.payload()
    draft_configuration["base_commit"] = product.domain.base
    wrong_plan = product.domain.plan_configuration(draft_configuration)
    assert wrong_plan.ok, wrong_plan.payload()
    wrong_configuration = ConfigurationSnapshot.model_validate(wrong_plan.value)
    wrong_value = wrong_configuration.model_dump(mode="json")
    wrong_supporting = (wrong_role_approval.model_dump(mode="json"),)
    wrong_package_hash, wrong_model_hash, wrong_scope = (
        product.domain.configuration_binding(
            product.domain.base, wrong_value, wrong_supporting
        )
    )
    wrong_configuration_approval = product.store.sign(
        product.trust,
        "technical",
        ApprovalPayload(
            package_hash=wrong_package_hash,
            effective_model_hash=wrong_model_hash,
            scope=wrong_scope,
            approval_type="technical",
        ),
    )
    rejected_configuration = product.domain.create_configuration(
        wrong_value,
        wrong_configuration_approval.model_dump(mode="json"),
        product.actor_uid,
        product.delegation_uid,
        "reject-wrong-role-deviation-configuration",
        wrong_supporting,
    )
    assert not rejected_configuration.ok
    assert rejected_configuration.error is not None
    assert "role" in rejected_configuration.error.message

    deviation_approval = product.store.sign(
        product.trust,
        "risk_deviation",
        ApprovalPayload(
            package_hash=deviation_hash,
            effective_model_hash=planned_configuration.effective_model_hash,
            scope=deviation_scope,
            approval_type="deviation",
            expires_at=datetime.now(UTC) + timedelta(days=1),
        ),
    )
    recorded = product.domain.record_governance_approval(
        deviation_approval.model_dump(mode="json"),
        product.actor_uid,
        product.delegation_uid,
        "record-deviation-approval",
    )
    assert recorded.ok, recorded.payload()

    draft_configuration["base_commit"] = product.domain.base
    planned = product.domain.plan_configuration(draft_configuration)
    assert planned.ok, planned.payload()
    activated_configuration = ConfigurationSnapshot.model_validate(planned.value)
    configuration_value = activated_configuration.model_dump(mode="json")
    supporting = (deviation_approval.model_dump(mode="json"),)
    package_hash, model_hash, scope = product.domain.configuration_binding(
        product.domain.base, configuration_value, supporting
    )
    configuration_approval = product.store.sign(
        product.trust,
        "technical",
        ApprovalPayload(
            package_hash=package_hash,
            effective_model_hash=model_hash,
            scope=scope,
            approval_type="technical",
        ),
    )
    created = product.domain.create_configuration(
        configuration_value,
        configuration_approval.model_dump(mode="json"),
        product.actor_uid,
        product.delegation_uid,
        "activate-deviation-configuration",
        supporting,
    )
    assert created.ok, created.payload()
    product = PublicProduct(
        product.domain,
        product.store,
        product.trust,
        product.actor_uid,
        product.workspace_uid,
        product.delegation_uid,
        activated_configuration.configuration_uid,
        product.signer_password,
    )
    requirement_copy = WorkingCopy(
        workspace_uid=product.workspace_uid,
        object_uid=requirement_uid,
        base_revision_uid=None,
        human_key="REQ-DEVIATED-1",
        kind="software_requirement",
        effective_model_hash=activated_configuration.effective_model_hash,
        delegation_uid=product.delegation_uid,
        draft_fields=(
            SemanticField(path="/statement", value="Operate with compensating monitor"),
            SemanticField(path="/safety_level", value="ASIL_B"),
        ),
    )
    requirement_result = _apply_working_copy(product, requirement_copy, "requirement")
    findings = requirement_result["prepared"]["validation"]["findings"]
    assert len(findings) == 1
    assert findings[0]["outcome"] == "suppressed_by_deviation"
    assert findings[0]["deviation_revision_uid"] == deviation_revision.revision_uid
