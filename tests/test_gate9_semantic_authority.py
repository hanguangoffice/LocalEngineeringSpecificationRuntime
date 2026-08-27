from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from lesr.adapters.schemas import SchemaCatalog
from lesr.application.runtime import LocalRuntimeService
from lesr.domain.approval import ApprovalKeyStore, ApprovalPayload
from lesr.domain.evaluation import GraphNode, GraphRelation, GraphSnapshot, SemanticEvaluator
from lesr.domain.governance import ValidationFinding
from lesr.domain.model import (
    CompositionMode,
    EffectiveModelCompiler,
    FacetDefinitionRevision,
    FieldDefinition,
    KindDefinitionRevision,
    NormativeProfileRevision,
    ProfileContribution,
    ProfileLayer,
    ProfileUnitDefinition,
    RelationTypeRevision,
)
from lesr.domain.review import (
    ApprovalRevocation,
    BaselineManifest,
    GovernanceEvaluator,
    ReviewPackage,
    ReviewPolicy,
    StageQuorum,
)
from lesr.domain.rules import (
    EnforcementEffect,
    NormativeModality,
    RuleCompiler,
    RuleDefinition,
    RuleOutcome,
)
from lesr.domain.semantic import (
    BindingMode,
    ConfigurationSnapshot,
    CoreRelationRole,
    CoreResourceClass,
    ImmutableRecord,
    ProvenanceKind,
    RelationAssertion,
    RelationEndpoint,
    Revision,
    SemanticField,
    governance_subject_hash,
    semantic_hash,
)
from lesr.domain.workspace import CandidateRevisionSet, Workspace
from tests.test_v1_rules import UNITS, source

UIDS = tuple(f"018f0000-0000-7000-8000-{index:012d}" for index in range(1, 80))


def _compiled_rule() -> tuple[object, object]:
    rule = source()
    result = RuleCompiler({"statement": str, "safety_level": str}, UNITS).compile(rule)
    assert result.passed and result.ast is not None
    return rule, result.ast


def _deviation_documents(
    tmp_path: Path,
    *,
    scope_subject_uid: str | None = None,
    role: str = "risk_deviation",
    revoked: bool = False,
) -> tuple[LocalRuntimeService, dict[str, object], Revision, list[tuple[object, object]]]:
    now = datetime.now(UTC)
    rule, ast = _compiled_rule()
    subject = Revision(
        revision_uid=UIDS[1],
        object_uid=UIDS[2],
        revision_number=1,
        human_key="REQ-GATE9",
        kind="software_requirement",
        fields=(SemanticField(path="/safety_level", value="ASIL_B"),),
        provenance_origin=ProvenanceKind.AUTHORED,
        created_at=now,
    )
    unsigned = Revision(
        revision_uid=UIDS[3],
        object_uid=UIDS[4],
        revision_number=1,
        human_key="DEV-GATE9",
        kind="deviation",
        fields=(
            SemanticField(path="/subject_uid", value=subject.object_uid),
            SemanticField(path="/rule_revision_uid", value=rule.rule_revision_uid),
            SemanticField(
                path="/valid_until", value=(now + timedelta(days=1)).isoformat()
            ),
            SemanticField(path="/compensating_control", value="Independent monitor"),
        ),
        provenance_origin=ProvenanceKind.AUTHORED,
        created_at=now,
    )
    governed_hash = governance_subject_hash(unsigned)
    store = ApprovalKeyStore(tmp_path / f"keys-{role}", password="gate9-password")
    trust = store.generate(UIDS[5], "Risk owner", (role,))
    scope: dict[str, object] = {
        "deviation_revision_uid": unsigned.revision_uid,
        "deviation_hash": governed_hash,
        "rule_revision_uid": rule.rule_revision_uid,
        "subject_uid": scope_subject_uid or subject.object_uid,
    }
    approval = store.sign(
        trust,
        role,
        ApprovalPayload(
            package_hash=governed_hash,
            effective_model_hash=semantic_hash({"model": "gate9"}),
            scope=scope,
            approval_type="deviation",
            expires_at=now + timedelta(hours=2),
        ),
    )
    deviation = Revision.model_validate(
        unsigned.model_dump(mode="json", exclude={"content_hash"})
        | {
            "fields": [
                *unsigned.model_dump(mode="json")["fields"],
                {"path": "/approval_uid", "value": approval.approval_uid},
            ]
        }
    )
    configuration: dict[str, object] = {
        "configuration_uid": UIDS[6],
        "effective_model_hash": semantic_hash({"model": "gate9"}),
        "active_deviation_revision_uids": [deviation.revision_uid],
    }
    documents = [
        deviation.model_dump(mode="json"),
        approval.model_dump(mode="json"),
        trust.model_dump(mode="json"),
    ]
    if revoked:
        documents.append(
            ApprovalRevocation(
                approval_uid=approval.approval_uid,
                actor_uid=trust.actor_uid,
                reason="withdrawn",
                revoked_at=now,
            ).model_dump(mode="json")
        )
    service = LocalRuntimeService.__new__(LocalRuntimeService)
    service.documents = documents
    return service, configuration, subject, [(rule, ast)]


def test_deviation_approval_is_bound_to_exact_subject_and_role(tmp_path: Path) -> None:
    service, configuration, subject, compiled = _deviation_documents(tmp_path)
    active = service._active_deviation_rules(
        configuration, subject, compiled, datetime.now(UTC) + timedelta(minutes=1)
    )
    assert active == {source().rule_uid: UIDS[3]}


@pytest.mark.parametrize(
    ("scope_subject_uid", "role", "revoked"),
    ((UIDS[20], "risk_deviation", False), (None, "technical", False), (None, "risk_deviation", True)),
)
def test_unrelated_wrong_role_and_revoked_deviation_approvals_fail_closed(
    tmp_path: Path,
    scope_subject_uid: str | None,
    role: str,
    revoked: bool,
) -> None:
    service, configuration, subject, compiled = _deviation_documents(
        tmp_path, scope_subject_uid=scope_subject_uid, role=role, revoked=revoked
    )
    with pytest.raises(PermissionError):
        service._active_deviation_rules(
            configuration, subject, compiled, datetime.now(UTC) + timedelta(minutes=1)
        )


def test_governance_finding_requires_finding_specific_human_attestation(
    tmp_path: Path,
) -> None:
    now = datetime.now(UTC)
    finding = ValidationFinding(
        validation_run_uid=UIDS[8],
        rule_uid=UIDS[9],
        rule_revision_uid=UIDS[10],
        subject_uid=UIDS[11],
        outcome=RuleOutcome.FAIL,
        enforcement=EnforcementEffect.REQUIRE_ACKNOWLEDGEMENT,
        blocking=False,
        explanation="acknowledge residual risk",
        created_at=now,
    )
    package = ReviewPackage(
        workspace_uid=UIDS[12],
        base_commit="a" * 40,
        configuration_uid=UIDS[13],
        result_configuration_uid=UIDS[14],
        result_configuration_hash=semantic_hash({"configuration": "next"}),
        candidate_hash=semantic_hash({"candidate": 1}),
        candidate_scope=(finding.subject_uid,),
        semantic_diff_hash=semantic_hash({"diff": 1}),
        graph_snapshot_hash=semantic_hash({"graph": 1}),
        context_bundle_hash=semantic_hash({"context": 1}),
        impact_report_hash=semantic_hash({"impact": 1}),
        validation_hash=semantic_hash({"validation": 1}),
        finding_hashes=(finding.content_hash,),
        governance_finding_uids=(finding.finding_uid,),
        review_policy=ReviewPolicy(
            stages=(StageQuorum(stage="review", role="technical", minimum_count=1),),
            require_preparer_independence=False,
        ),
        effective_model_hash=semantic_hash({"model": 1}),
        prepared_by_actor_uid=UIDS[15],
        created_at=now,
    )
    store = ApprovalKeyStore(tmp_path / "finding-keys", password="gate9-password")
    trust = store.generate(UIDS[16], "Reviewer", ("technical",))
    review = store.sign(
        trust,
        "technical",
        ApprovalPayload(
            package_hash=package.package_hash,
            effective_model_hash=package.effective_model_hash,
            scope={"resource_uids": list(package.candidate_scope)},
            approval_type="review",
        ),
    )
    rejected = GovernanceEvaluator.evaluate(
        package, (review,), (trust,), (), (), (), (), now=now + timedelta(minutes=1), findings=(finding,)
    )
    assert not rejected.allowed
    assert any("GOVERNANCE_FINDING_UNFULFILLED" in item for item in rejected.reasons)

    acknowledgement = store.sign(
        trust,
        "technical",
        ApprovalPayload(
            package_hash=package.package_hash,
            effective_model_hash=package.effective_model_hash,
            scope={"finding_uid": finding.finding_uid},
            approval_type="finding_acknowledgement",
        ),
    )
    accepted = GovernanceEvaluator.evaluate(
        package,
        (review, acknowledgement),
        (trust,),
        (),
        (),
        (),
        (),
        now=now + timedelta(minutes=1),
        findings=(finding,),
    )
    assert accepted.allowed


def test_configuration_state_anchor_is_semantic_not_git_self_reference() -> None:
    common = {
        "revision_uids": (UIDS[22],),
        "relation_revision_uids": (),
        "profile_revision_uids": (UIDS[23],),
        "effective_model_hash": semantic_hash({"model": "anchor"}),
    }
    first = ConfigurationSnapshot(base_commit="a" * 40, **common)
    second = ConfigurationSnapshot(base_commit="b" * 40, **common)
    changed = ConfigurationSnapshot(
        base_commit="b" * 40,
        **(common | {"revision_uids": (UIDS[24],)}),
    )
    assert first.state_anchor == second.state_anchor
    assert first.configuration_hash != second.configuration_hash
    assert changed.state_anchor != first.state_anchor


@pytest.mark.parametrize(("milliseconds", "expected"), (("1500", "pass"), ("2500", "fail")))
def test_product_validation_uses_units_in_the_single_evaluator(
    milliseconds: str, expected: str
) -> None:
    now = datetime.now(UTC)
    base_rule = source()
    fixture_values = []
    for fixture in base_rule.fixtures:
        environment = dict(fixture.environment)
        fields = dict(environment["fields"])
        timeout_value: dict[str, object] = {
            "state": "value",
            "value": {"decimal": "1500", "unit": "ms"},
        }
        if fixture.kind.value in {"negative", "deviation"}:
            timeout_value["value"] = {"decimal": "2500", "unit": "ms"}
        elif fixture.kind.value == "indeterminate":
            timeout_value = {"state": "unknown", "value": None}
        fields["timeout"] = timeout_value
        environment["fields"] = fields
        fixture_values.append(fixture.model_copy(update={"environment": environment}))
    rule = RuleDefinition.model_validate(
        base_rule.model_dump(mode="json", exclude={"content_hash"})
        | {
            "constraints": [
                {
                    "op": "quantity_maximum",
                    "path": "timeout",
                    "maximum": {"decimal": "2", "unit": "s"},
                }
            ],
            "fixtures": [item.model_dump(mode="json") for item in fixture_values],
        }
    )
    facet = FacetDefinitionRevision(
        revision_uid=UIDS[25],
        name="timed_requirement",
        fields=(
            FieldDefinition(path="/safety_level", value_type="string"),
            FieldDefinition(path="/timeout", value_type="quantity", unit="s"),
        ),
    )
    kind = KindDefinitionRevision(
        revision_uid=UIDS[26],
        name="software_requirement",
        core_class=CoreResourceClass.GOVERNED_OBJECT,
        required_facet_revision_uids=(facet.revision_uid,),
    )
    profile = NormativeProfileRevision(
        profile_revision_uid=UIDS[27],
        layer=ProfileLayer.PROJECT,
        authority=100,
        contributions=tuple(
            ProfileContribution(
                mode=CompositionMode.EXTEND,
                definition_revision_uid=item.revision_uid,
            )
            for item in (facet, kind)
        ),
        rule_revision_uids=(rule.rule_revision_uid,),
        unit_definitions=(
            ProfileUnitDefinition(unit="s", dimension="time", scale_to_base="1"),
            ProfileUnitDefinition(unit="ms", dimension="time", scale_to_base="0.001"),
        ),
    )
    model = EffectiveModelCompiler().compile((profile,), (facet, kind))
    revision = Revision(
        revision_uid=UIDS[28],
        object_uid=UIDS[29],
        revision_number=1,
        human_key="REQ-QUANTITY",
        kind="software_requirement",
        fields=(
            SemanticField(path="/safety_level", value="ASIL_B"),
            SemanticField(
                path="/timeout", value={"decimal": milliseconds, "unit": "ms"}
            ),
        ),
        provenance_origin=ProvenanceKind.AUTHORED,
        created_at=now,
    )
    candidate = CandidateRevisionSet(
        workspace_uid=UIDS[30],
        checkpoint_uid=UIDS[31],
        effective_model_hash=model.model_hash,
        revisions=(revision,),
        relation_revisions=(),
        lifecycle_records=(),
    )
    workspace = Workspace(
        workspace_uid=candidate.workspace_uid,
        base_commit="a" * 40,
        configuration_uid=UIDS[32],
        effective_model_hash=model.model_hash,
        delegation_uid=UIDS[33],
        actor_uid=UIDS[34],
        created_at=now,
    )
    snapshot = GraphSnapshot(
        configuration_uid=workspace.configuration_uid,
        canonical_commit=workspace.base_commit,
        effective_model_hash=model.model_hash,
        workspace_uid=workspace.workspace_uid,
        checkpoint_uid=candidate.checkpoint_uid,
        evaluation_time=now,
        nodes=(GraphNode(revision=revision, lifecycle_state="draft", source="candidate"),),
        relations=(),
        candidate_overlay_hash=candidate.candidate_hash,
    )
    service = LocalRuntimeService.__new__(LocalRuntimeService)
    service.documents = [
        {
            "resource_type": "configuration_snapshot",
            "configuration_uid": workspace.configuration_uid,
            "profile_revision_uids": [profile.profile_revision_uid],
            "active_deviation_revision_uids": [],
            "effective_model_hash": model.model_hash,
        },
        profile.model_dump(mode="json"),
        facet.model_dump(mode="json"),
        kind.model_dump(mode="json"),
        rule.model_dump(mode="json"),
    ]
    validation = service._validate_submission(
        SimpleNamespace(workspace=workspace, candidate=candidate),
        SemanticEvaluator(snapshot, ()),
    )
    assert validation["outcome"] == expected


def test_product_validation_accepts_a_valid_two_hop_graph_path() -> None:
    now = datetime.now(UTC)
    base_rule = source()
    fixture_values = []
    for fixture in base_rule.fixtures:
        environment = dict(fixture.environment)
        counts = dict(environment["relation_counts"])
        counts["derived_through>verified_by"] = (
            0 if fixture.kind.value in {"negative", "deviation"} else 1
        )
        environment["relation_counts"] = counts
        fixture_values.append(fixture.model_copy(update={"environment": environment}))
    rule = RuleDefinition.model_validate(
        base_rule.model_dump(mode="json", exclude={"content_hash"})
        | {
            "constraints": [
                {
                    "op": "relation_minimum",
                    "path": {
                        "roles": ["derived_through", "verified_by"],
                        "max_depth": 2,
                        "direction": "outgoing",
                        "binding": "pinned",
                    },
                    "minimum": 1,
                }
            ],
            "fixtures": [item.model_dump(mode="json") for item in fixture_values],
        }
    )
    requirement_facet = FacetDefinitionRevision(
        revision_uid=UIDS[57],
        name="requirement_applicability",
        fields=(FieldDefinition(path="/safety_level", value_type="string"),),
    )
    requirement_kind = KindDefinitionRevision(
        revision_uid=UIDS[35],
        name="software_requirement",
        core_class=CoreResourceClass.GOVERNED_OBJECT,
        required_facet_revision_uids=(requirement_facet.revision_uid,),
    )
    design_kind = KindDefinitionRevision(
        revision_uid=UIDS[36],
        name="software_design",
        core_class=CoreResourceClass.GOVERNED_OBJECT,
    )
    test_kind = KindDefinitionRevision(
        revision_uid=UIDS[37],
        name="test_case",
        core_class=CoreResourceClass.GOVERNED_OBJECT,
    )
    first_type = RelationTypeRevision(
        revision_uid=UIDS[38],
        predicate="derived_through",
        core_role=CoreRelationRole.DERIVES_FROM,
        source_kind_or_facet=("software_requirement",),
        target_kind_or_facet=("software_design",),
        allowed_bindings=(BindingMode.PINNED,),
        default_binding=BindingMode.PINNED,
        workflow_revision_uid=UIDS[39],
    )
    second_type = RelationTypeRevision(
        revision_uid=UIDS[40],
        predicate="verified_by",
        core_role=CoreRelationRole.VERIFIES,
        source_kind_or_facet=("software_design",),
        target_kind_or_facet=("test_case",),
        allowed_bindings=(BindingMode.PINNED,),
        default_binding=BindingMode.PINNED,
        workflow_revision_uid=UIDS[39],
    )
    definitions = (
        requirement_facet,
        requirement_kind,
        design_kind,
        test_kind,
        first_type,
        second_type,
    )
    profile = NormativeProfileRevision(
        profile_revision_uid=UIDS[41],
        layer=ProfileLayer.PROJECT,
        authority=100,
        contributions=tuple(
            ProfileContribution(
                mode=CompositionMode.EXTEND,
                definition_revision_uid=item.revision_uid,
            )
            for item in definitions
        ),
        rule_revision_uids=(rule.rule_revision_uid,),
    )
    model = EffectiveModelCompiler().compile((profile,), definitions)

    def node(uid_index: int, revision_index: int, kind: str, key: str) -> Revision:
        return Revision(
            revision_uid=UIDS[revision_index],
            object_uid=UIDS[uid_index],
            revision_number=1,
            human_key=key,
            kind=kind,
            fields=(SemanticField(path="/safety_level", value="ASIL_B"),)
            if kind == "software_requirement"
            else (),
            provenance_origin=ProvenanceKind.AUTHORED,
            created_at=now,
        )

    requirement = node(42, 43, "software_requirement", "REQ-PATH")
    design = node(44, 45, "software_design", "DES-PATH")
    test = node(46, 47, "test_case", "TEST-PATH")

    def endpoint(revision: Revision) -> RelationEndpoint:
        return RelationEndpoint(
            binding=BindingMode.PINNED,
            object_uid=revision.object_uid,
            revision_uid=revision.revision_uid,
        )

    first = RelationAssertion(
        assertion_uid=UIDS[48],
        relation_revision_uid=UIDS[49],
        relation_type_revision_uid=first_type.revision_uid,
        predicate=first_type.predicate,
        core_role=first_type.core_role,
        source=endpoint(requirement),
        target=endpoint(design),
        scope="project",
        provenance_kind=ProvenanceKind.ASSERTED,
        created_at=now,
    )
    second = RelationAssertion(
        assertion_uid=UIDS[50],
        relation_revision_uid=UIDS[51],
        relation_type_revision_uid=second_type.revision_uid,
        predicate=second_type.predicate,
        core_role=second_type.core_role,
        source=endpoint(design),
        target=endpoint(test),
        scope="project",
        provenance_kind=ProvenanceKind.ASSERTED,
        created_at=now,
    )
    candidate = CandidateRevisionSet(
        workspace_uid=UIDS[52],
        checkpoint_uid=UIDS[53],
        effective_model_hash=model.model_hash,
        revisions=(requirement,),
        relation_revisions=(first, second),
        lifecycle_records=(),
    )
    workspace = Workspace(
        workspace_uid=candidate.workspace_uid,
        base_commit="a" * 40,
        configuration_uid=UIDS[54],
        effective_model_hash=model.model_hash,
        delegation_uid=UIDS[55],
        actor_uid=UIDS[56],
        created_at=now,
    )
    snapshot = GraphSnapshot(
        configuration_uid=workspace.configuration_uid,
        canonical_commit=workspace.base_commit,
        effective_model_hash=model.model_hash,
        workspace_uid=workspace.workspace_uid,
        checkpoint_uid=candidate.checkpoint_uid,
        evaluation_time=now,
        nodes=tuple(
            GraphNode(
                revision=item,
                lifecycle_state="approved",
                source="candidate" if item is requirement else "canonical",
            )
            for item in (requirement, design, test)
        ),
        relations=tuple(
            GraphRelation(
                assertion=item,
                relation_type_revision_uid=str(item.relation_type_revision_uid),
                lifecycle_state="active",
                source="candidate",
            )
            for item in (first, second)
        ),
        candidate_overlay_hash=candidate.candidate_hash,
    )
    service = LocalRuntimeService.__new__(LocalRuntimeService)
    service.documents = [
        {
            "resource_type": "configuration_snapshot",
            "configuration_uid": workspace.configuration_uid,
            "profile_revision_uids": [profile.profile_revision_uid],
            "active_deviation_revision_uids": [],
            "effective_model_hash": model.model_hash,
        },
        profile.model_dump(mode="json"),
        *(item.model_dump(mode="json") for item in definitions),
        rule.model_dump(mode="json"),
    ]
    validation = service._validate_submission(
        SimpleNamespace(workspace=workspace, candidate=candidate),
        SemanticEvaluator(snapshot, (first_type, second_type)),
    )
    assert validation["outcome"] == "pass"


def test_normative_conflict_is_indeterminate_until_exact_resolution_selected() -> None:
    left, left_ast = _compiled_rule()
    right = left.model_copy(
        update={"rule_uid": UIDS[58], "rule_revision_uid": UIDS[59]}
    )
    right_ast = replace(
        left_ast,
        rule_uid=right.rule_uid,
        rule_revision_uid=right.rule_revision_uid,
        modality=NormativeModality.PROHIBITION,
    )
    service = LocalRuntimeService.__new__(LocalRuntimeService)
    service.documents = []
    compiled = [(left, left_ast), (right, right_ast)]
    conflicted = service._conflicted_rule_uids({}, compiled)
    assert conflicted == frozenset((left.rule_uid, right.rule_uid))

    resolution = ImmutableRecord(
        record_uid=UIDS[60],
        record_type="rule_conflict_resolution",
        subject_uid=left.rule_uid,
        actor_uid=UIDS[61],
        actor_type="human",
        fields=(
            SemanticField(
                path="/left_rule_revision_uid", value=left.rule_revision_uid
            ),
            SemanticField(
                path="/right_rule_revision_uid", value=right.rule_revision_uid
            ),
        ),
    )
    service.documents = [resolution.model_dump(mode="json")]
    assert service._conflicted_rule_uids(
        {"conflict_resolution_uids": [resolution.record_uid]}, compiled
    ) == frozenset()


def test_approved_exception_enters_product_rule_environment(tmp_path: Path) -> None:
    now = datetime.now(UTC)
    raw_rule, ast = _compiled_rule()
    rule = raw_rule.model_copy(
        update={
            "exception_policy": {
                "allowed": True,
                "required_approval_roles": ["risk_exception"],
            }
        }
    )
    subject = Revision(
        revision_uid=UIDS[62],
        object_uid=UIDS[63],
        revision_number=1,
        human_key="REQ-EXCEPTION",
        kind="software_requirement",
        provenance_origin=ProvenanceKind.AUTHORED,
        created_at=now,
    )
    unsigned = Revision(
        revision_uid=UIDS[64],
        object_uid=UIDS[65],
        revision_number=1,
        human_key="EXC-1",
        kind="exception",
        fields=(
            SemanticField(path="/subject_uid", value=subject.object_uid),
            SemanticField(path="/rule_revision_uid", value=rule.rule_revision_uid),
            SemanticField(
                path="/valid_until", value=(now + timedelta(days=1)).isoformat()
            ),
        ),
        provenance_origin=ProvenanceKind.AUTHORED,
        created_at=now,
    )
    subject_hash = governance_subject_hash(unsigned)
    store = ApprovalKeyStore(tmp_path / "exception-keys", password="gate9-password")
    trust = store.generate(UIDS[66], "Exception owner", ("risk_exception",))
    approval = store.sign(
        trust,
        "risk_exception",
        ApprovalPayload(
            package_hash=subject_hash,
            effective_model_hash=semantic_hash({"model": "exception"}),
            scope={
                "exception_revision_uid": unsigned.revision_uid,
                "exception_hash": subject_hash,
                "rule_revision_uid": rule.rule_revision_uid,
                "subject_uid": subject.object_uid,
            },
            approval_type="exception",
        ),
    )
    exception = Revision.model_validate(
        unsigned.model_dump(mode="json", exclude={"content_hash"})
        | {
            "fields": [
                *unsigned.model_dump(mode="json")["fields"],
                {"path": "/approval_uid", "value": approval.approval_uid},
            ]
        }
    )
    service = LocalRuntimeService.__new__(LocalRuntimeService)
    service.documents = [
        exception.model_dump(mode="json"),
        approval.model_dump(mode="json"),
        trust.model_dump(mode="json"),
    ]
    active = service._active_exception_rules(
        {
            "effective_model_hash": semantic_hash({"model": "exception"}),
            "active_exception_revision_uids": [exception.revision_uid],
        },
        subject,
        [(rule, ast)],
        now + timedelta(minutes=1),
    )
    assert active == frozenset((rule.rule_uid,))


def test_baseline_domain_model_round_trips_the_canonical_schema() -> None:
    manifest = BaselineManifest(
        state_commit="a" * 40,
        configuration_uid=UIDS[67],
        exact_revision_uids=(UIDS[68],),
        exact_relation_revision_uids=(UIDS[69],),
        effective_model_hash=semantic_hash({"model": "baseline"}),
        deviation_revision_uids=(UIDS[70],),
        review_package_hash=semantic_hash({"review": "baseline"}),
        created_at=datetime.now(UTC),
    )
    value = manifest.model_dump(mode="json")
    SchemaCatalog().validate("baseline-manifest.schema.json", value)
    assert BaselineManifest.model_validate(value) == manifest
