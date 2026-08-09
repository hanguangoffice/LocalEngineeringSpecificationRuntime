from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from lesr.domain.approval import ApprovalKeyStore, ApprovalPayload
from lesr.domain.review import (
    ApprovalRevocation,
    CommentDisposition,
    CommentResolution,
    ConditionSatisfaction,
    GovernanceEvaluator,
    ReviewComment,
    ReviewPackage,
    ReviewPolicy,
    StageQuorum,
    prepare_baseline,
    revocation_consequence,
)
from lesr.domain.semantic import semantic_hash

NOW = datetime.now(UTC)
UIDS = [f"018f0000-0000-7000-8000-{index:012d}" for index in range(1, 30)]
HASHES = [semantic_hash({"value": index}) for index in range(20)]


def package(*, comment_hashes: tuple[str, ...] = ()) -> ReviewPackage:
    return ReviewPackage(
        package_uid=UIDS[0],
        workspace_uid=UIDS[1],
        base_commit="a" * 40,
        configuration_uid=UIDS[2],
        result_configuration_uid=UIDS[2],
        result_configuration_hash=HASHES[7],
        candidate_hash=HASHES[0],
        candidate_scope=(UIDS[3], UIDS[4]),
        semantic_diff_hash=HASHES[1],
        graph_snapshot_hash=HASHES[2],
        context_bundle_hash=HASHES[3],
        impact_report_hash=HASHES[4],
        validation_hash=HASHES[5],
        finding_hashes=(),
        comment_hashes=comment_hashes,
        review_policy=ReviewPolicy(
            stages=(StageQuorum(stage="review", role="technical", minimum_count=2),)
        ),
        effective_model_hash=HASHES[6],
        prepared_by_actor_uid=UIDS[5],
        created_at=NOW,
    )


def test_partial_conditional_approvals_jointly_cover_scope_and_quorum(tmp_path: Path) -> None:
    review_package = package()
    store = ApprovalKeyStore(tmp_path / "keys")
    reviewers = (
        store.generate(UIDS[6], "Reviewer A", ("technical",)),
        store.generate(UIDS[7], "Reviewer B", ("technical",)),
    )
    condition = {"type": "evidence_present", "uid": UIDS[8]}
    approvals = (
        store.sign(
            reviewers[0],
            "technical",
            ApprovalPayload(
                package_hash=review_package.package_hash,
                effective_model_hash=review_package.effective_model_hash,
                scope={"resource_uids": [UIDS[3]]},
                approval_type="review",
                conditions=(condition,),
                expires_at=NOW + timedelta(hours=1),
            ),
        ),
        store.sign(
            reviewers[1],
            "technical",
            ApprovalPayload(
                package_hash=review_package.package_hash,
                effective_model_hash=review_package.effective_model_hash,
                scope={"resource_uids": [UIDS[4]]},
                approval_type="review",
                expires_at=NOW + timedelta(hours=1),
            ),
        ),
    )
    satisfaction = ConditionSatisfaction(
        approval_uid=approvals[0].approval_uid,
        condition_hash=semantic_hash({"condition": condition}),
        evidence_uids=(UIDS[8],),
        actor_uid=UIDS[9],
        satisfied_at=NOW,
    )
    decision = GovernanceEvaluator.evaluate(
        review_package,
        approvals,
        reviewers,
        (),
        (),
        (satisfaction,),
        (),
        now=NOW + timedelta(minutes=1),
    )
    assert decision.allowed
    assert decision.covered_scope == tuple(sorted(review_package.candidate_scope))
    assert decision.quorum == (("review", "technical", 2, 2),)


def test_open_comment_and_pre_apply_revocation_both_block(tmp_path: Path) -> None:
    review_subject = package()
    comment = ReviewComment(
        package_hash=review_subject.subject_hash,
        resource_uid=UIDS[3],
        location="/statement",
        author_uid=UIDS[10],
        body="Clarify the timing bound",
        created_at=NOW,
    )
    review_package = package(comment_hashes=(comment.comment_hash,))
    store = ApprovalKeyStore(tmp_path / "keys")
    reviewer = store.generate(UIDS[6], "Reviewer", ("technical",))
    approval = store.sign(
        reviewer,
        "technical",
        ApprovalPayload(
            package_hash=review_package.package_hash,
            effective_model_hash=review_package.effective_model_hash,
            scope={"resource_uids": list(review_package.candidate_scope)},
            approval_type="review",
            expires_at=NOW + timedelta(hours=1),
        ),
    )
    revocation = ApprovalRevocation(
        approval_uid=approval.approval_uid,
        actor_uid=reviewer.actor_uid,
        reason="evidence withdrawn",
        revoked_at=NOW,
    )
    decision = GovernanceEvaluator.evaluate(
        review_package,
        (approval,),
        (reviewer,),
        (comment,),
        (),
        (),
        (revocation,),
        now=NOW + timedelta(minutes=1),
    )
    assert not decision.allowed
    assert "OPEN_REVIEW_COMMENT" in decision.reasons
    assert any(reason.startswith("APPROVAL_REVOKED") for reason in decision.reasons)


def test_comment_resolution_and_post_apply_revocation_are_immutable_evidence() -> None:
    resolution = CommentResolution(
        comment_hash=HASHES[7],
        actor_uid=UIDS[6],
        disposition=CommentDisposition.ACCEPTED,
        rationale="candidate was updated",
        created_at=NOW,
    )
    assert resolution.resolution_hash.startswith("sha256:")
    before = revocation_consequence(already_applied=False)
    after = revocation_consequence(already_applied=True)
    assert before.pre_apply_invalidates
    assert after.assurance_finding == "APPROVAL_REVOKED_AFTER_APPLY"
    assert after.revalidation_trigger == "REVALIDATE_APPLIED_SCOPE"


def test_baseline_preparation_requires_complete_configuration_validation_and_impact() -> None:
    preparation = prepare_baseline(
        configuration_uid=UIDS[2],
        state_commit="a" * 40,
        graph_snapshot_hash=HASHES[2],
        validation_run_hash=HASHES[5],
        impact_report_hash=HASHES[4],
        review_package_hash=HASHES[6],
        configuration_complete=True,
        validation_passed=True,
        impact_complete=True,
    )
    assert preparation.state_commit == "a" * 40
    assert preparation.preparation_hash.startswith("sha256:")
