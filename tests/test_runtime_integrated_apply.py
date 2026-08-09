from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from lesr.adapters.git import GitCanonicalRepository, InjectedFailure
from lesr.application.runtime import LocalRuntimeService
from lesr.domain.approval import (
    ApprovalKeyStore,
    ApprovalPayload,
    SignedApproval,
    TrustedActor,
)
from lesr.domain.evaluation import GraphNode, GraphRelation, GraphSnapshot, SemanticEvaluator
from lesr.domain.model import EffectiveModelCompiler, NormativeProfileRevision, ProfileLayer
from lesr.domain.review import ReviewPackage, ReviewPolicy, StageQuorum
from lesr.domain.semantic import (
    ImmutableRecord,
    ProvenanceKind,
    Revision,
    SemanticField,
    semantic_hash,
)
from lesr.domain.workspace import CandidateRevisionSet, Workspace
from tests.test_gate3_graph_evaluation import REQ, TEST, assertion, relation_type
from tests.test_v1_rules import source

NOW = datetime.now(UTC)
UIDS = [f"018f0000-0000-7000-8000-{index:012d}" for index in range(1, 30)]
MODEL_HASH = semantic_hash({"model": "integrated"})


def bound_evidence(package: ReviewPackage) -> dict[str, object]:
    return {
        "semantic_diff": {"diff_hash": package.semantic_diff_hash},
        "graph_snapshot": {"snapshot_hash": package.graph_snapshot_hash},
        "context_bundle": {"bundle_hash": package.context_bundle_hash},
        "impact_report": {"report_hash": package.impact_report_hash},
        "validation": {
            "validation_hash": package.validation_hash,
            "finding_hashes": list(package.finding_hashes),
            "outcome": "pass",
        },
    }


def governed_candidate(
    tmp_path: Path,
) -> tuple[
    GitCanonicalRepository,
    CandidateRevisionSet,
    ReviewPackage,
    tuple[SignedApproval, ...],
    tuple[TrustedActor, ...],
]:
    repository = GitCanonicalRepository(tmp_path)
    base = repository.initialize()
    revision = Revision(
        revision_uid=UIDS[1],
        object_uid=UIDS[0],
        revision_number=1,
        human_key="REQ-1",
        kind="software_requirement",
        provenance_origin=ProvenanceKind.AUTHORED,
        created_at=NOW,
    )
    candidate = CandidateRevisionSet(
        candidate_uid=UIDS[2],
        workspace_uid=UIDS[3],
        checkpoint_uid=UIDS[4],
        effective_model_hash=MODEL_HASH,
        revisions=(revision,),
        relation_revisions=(),
        lifecycle_records=(
            ImmutableRecord(
                record_uid=UIDS[19],
                record_type="lifecycle",
                subject_uid=revision.object_uid,
                actor_uid=UIDS[7],
                actor_type="human",
                occurred_at=NOW,
                fields=(SemanticField(path="/to_state", value="reviewed"),),
            ),
        ),
    )
    package = ReviewPackage(
        package_uid=UIDS[5],
        workspace_uid=candidate.workspace_uid,
        base_commit=base,
        configuration_uid=UIDS[6],
        candidate_hash=candidate.candidate_hash,
        candidate_scope=(revision.object_uid,),
        semantic_diff_hash=semantic_hash({"diff": 1}),
        graph_snapshot_hash=semantic_hash({"graph": 1}),
        context_bundle_hash=semantic_hash({"context": 1}),
        impact_report_hash=semantic_hash({"impact": 1}),
        validation_hash=semantic_hash({"validation": "pass"}),
        finding_hashes=(),
        comment_hashes=(),
        review_policy=ReviewPolicy(
            stages=(StageQuorum(stage="review", role="technical", minimum_count=1),)
        ),
        effective_model_hash=MODEL_HASH,
        prepared_by_actor_uid=UIDS[7],
        created_at=NOW,
    )
    store = ApprovalKeyStore(tmp_path / "keys", password="test-password")
    trust = store.generate(UIDS[8], "Reviewer", ("technical",))
    approval = store.sign(
        trust,
        "technical",
        ApprovalPayload(
            package_hash=package.package_hash,
            effective_model_hash=package.effective_model_hash,
            scope={"resource_uids": list(package.candidate_scope)},
            approval_type="review",
        ),
    )
    return repository, candidate, package, (approval,), (trust,)


def test_git_boundary_recomputes_same_governance_and_atomically_promotes_candidate(
    tmp_path: Path,
) -> None:
    repository, candidate, package, raw_approvals, raw_trust = governed_candidate(tmp_path)
    approvals = tuple(raw_approvals)
    trust = tuple(raw_trust)
    result = repository.apply_candidate(
        base_commit=repository.current_commit(),
        candidate=candidate,
        review_package=package,
        approvals=approvals,
        trust=trust,
        evaluation_time=datetime.now(UTC),
        actor_uid=UIDS[9],
        delegation_uid=UIDS[10],
        idempotency_key="integrated-apply",
        evidence=bound_evidence(package),
        validation_recalculator=lambda: package.validation_hash,
    )
    assert repository.current_commit() == result.commit
    assert (
        repository.read_json(
            result.commit, f"canonical/revisions/{candidate.revisions[0].revision_uid}.json"
        )
        is not None
    )
    assert repository.read_json(
        result.commit,
        f"canonical/immutable_records/{candidate.lifecycle_records[0].record_uid}.json",
    ) is not None
    assert repository.read_json(
        result.commit,
        f"canonical/provenance/{approvals[0].provenance_uid}.json",
    ) is not None
    replay = repository.apply_candidate(
        base_commit=result.commit,
        candidate=candidate,
        review_package=package,
        approvals=approvals,
        trust=trust,
        evaluation_time=datetime.now(UTC),
        actor_uid=UIDS[9],
        delegation_uid=UIDS[10],
        idempotency_key="integrated-apply",
        evidence=bound_evidence(package),
        validation_recalculator=lambda: package.validation_hash,
    )
    assert replay.idempotent_replay
    assert replay.commit == result.commit


def test_ref_failure_leaves_no_half_state(tmp_path: Path) -> None:
    repository, candidate, package, raw_approvals, raw_trust = governed_candidate(tmp_path)
    base = repository.current_commit()

    def fail(stage: str) -> None:
        if stage == "update_ref":
            raise InjectedFailure(stage)

    with pytest.raises(InjectedFailure):
        repository.apply_candidate(
            base_commit=base,
            candidate=candidate,
            review_package=package,
            approvals=tuple(raw_approvals),
            trust=tuple(raw_trust),
            evaluation_time=datetime.now(UTC),
            actor_uid=UIDS[9],
            delegation_uid=UIDS[10],
            idempotency_key="failed-apply",
            evidence=bound_evidence(package),
            validation_recalculator=lambda: package.validation_hash,
            fault_injector=fail,
        )
    assert repository.current_commit() == base
    assert (
        repository.read_json(
            base, f"canonical/revisions/{candidate.revisions[0].revision_uid}.json"
        )
        is None
    )


def test_runtime_validation_uses_selected_compiled_rule_instead_of_fixed_pass() -> None:
    rule = source()
    configuration_uid = UIDS[11]
    profile_uid = UIDS[12]
    profile = NormativeProfileRevision(
        profile_revision_uid=profile_uid,
        layer=ProfileLayer.PROJECT,
        authority=100,
        rule_revision_uids=(rule.rule_revision_uid,),
    )
    effective_model = EffectiveModelCompiler().compile((profile,), ())
    revision = Revision(
        revision_uid=UIDS[13],
        object_uid=UIDS[14],
        revision_number=1,
        human_key="REQ-RULE-1",
        kind="software_requirement",
        fields=(
            SemanticField(path="/safety_level", value="ASIL_B"),
            SemanticField(path="/statement", value="The software shall reconnect."),
        ),
        provenance_origin=ProvenanceKind.AUTHORED,
        created_at=NOW,
    )
    candidate = CandidateRevisionSet(
        workspace_uid=UIDS[15],
        checkpoint_uid=UIDS[16],
        effective_model_hash=effective_model.model_hash,
        revisions=(revision,),
        relation_revisions=(),
        lifecycle_records=(),
    )
    workspace = Workspace(
        workspace_uid=candidate.workspace_uid,
        base_commit="a" * 40,
        configuration_uid=configuration_uid,
        effective_model_hash=effective_model.model_hash,
        delegation_uid=UIDS[17],
        actor_uid=UIDS[18],
        created_at=NOW,
    )
    submission = SimpleNamespace(workspace=workspace, candidate=candidate)
    snapshot = GraphSnapshot(
        configuration_uid=configuration_uid,
        canonical_commit="a" * 40,
        effective_model_hash=effective_model.model_hash,
        workspace_uid=candidate.workspace_uid,
        checkpoint_uid=candidate.checkpoint_uid,
        evaluation_time=NOW,
        nodes=(GraphNode(revision=revision, lifecycle_state="draft", source="candidate"),),
        relations=(),
        candidate_overlay_hash=candidate.candidate_hash,
    )
    service = LocalRuntimeService.__new__(LocalRuntimeService)
    service.documents = [
        {
            "resource_type": "configuration_snapshot",
            "configuration_uid": configuration_uid,
            "profile_revision_uids": [profile_uid],
            "active_deviation_revision_uids": [],
            "effective_model_hash": effective_model.model_hash,
        },
        profile.model_dump(mode="json"),
        rule.model_dump(mode="json"),
    ]

    validation = service._validate_submission(
        submission, SemanticEvaluator(snapshot, ())
    )

    assert validation["outcome"] != "pass"
    assert validation["findings"][0]["rule_revision_uid"] == rule.rule_revision_uid


def test_runtime_formal_trace_rejects_inferred_relation_even_when_raw_count_is_one() -> None:
    rule_value = source().model_dump(mode="json", exclude={"content_hash"})
    rule_value["constraints"] = [
        {
            "op": "relation_minimum",
            "path": {
                "roles": ["verified_by"],
                "max_depth": 1,
                "direction": "outgoing",
                "binding": "pinned",
                "lifecycle_state": "active",
                "formal_trace_category": "verification",
            },
            "minimum": 1,
        }
    ]
    rule = source().__class__.model_validate(rule_value)
    configuration_uid = UIDS[20]
    profile = NormativeProfileRevision(
        profile_revision_uid=UIDS[21],
        layer=ProfileLayer.PROJECT,
        authority=100,
        rule_revision_uids=(rule.rule_revision_uid,),
    )
    effective_model = EffectiveModelCompiler().compile((profile,), ())
    candidate = CandidateRevisionSet(
        workspace_uid=UIDS[22],
        checkpoint_uid=UIDS[23],
        effective_model_hash=effective_model.model_hash,
        revisions=(REQ, TEST),
        relation_revisions=(),
        lifecycle_records=(),
    )
    workspace = Workspace(
        workspace_uid=candidate.workspace_uid,
        base_commit="a" * 40,
        configuration_uid=configuration_uid,
        effective_model_hash=effective_model.model_hash,
        delegation_uid=UIDS[24],
        actor_uid=UIDS[25],
        created_at=NOW,
    )
    submission = SimpleNamespace(workspace=workspace, candidate=candidate)
    inferred = assertion(provenance=ProvenanceKind.INFERRED)
    selected_type = relation_type()
    snapshot = GraphSnapshot(
        configuration_uid=configuration_uid,
        canonical_commit="a" * 40,
        effective_model_hash=effective_model.model_hash,
        workspace_uid=candidate.workspace_uid,
        checkpoint_uid=candidate.checkpoint_uid,
        evaluation_time=NOW,
        nodes=(
            GraphNode(revision=REQ, lifecycle_state="approved", source="candidate"),
            GraphNode(revision=TEST, lifecycle_state="approved", source="candidate"),
        ),
        relations=(
            GraphRelation(
                assertion=inferred,
                relation_type_revision_uid=selected_type.revision_uid,
                lifecycle_state="active",
                source="candidate",
            ),
        ),
        candidate_overlay_hash=candidate.candidate_hash,
    )
    service = LocalRuntimeService.__new__(LocalRuntimeService)
    service.documents = [
        {
            "resource_type": "configuration_snapshot",
            "configuration_uid": configuration_uid,
            "profile_revision_uids": [profile.profile_revision_uid],
            "active_deviation_revision_uids": [],
            "effective_model_hash": effective_model.model_hash,
        },
        profile.model_dump(mode="json"),
        rule.model_dump(mode="json"),
    ]
    validation = service._validate_submission(
        submission, SemanticEvaluator(snapshot, (selected_type,))
    )
    assert validation["outcome"] != "pass"
    assert validation["findings"][0]["outcome"] in {"fail", "indeterminate"}
