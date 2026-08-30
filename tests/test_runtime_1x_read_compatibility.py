from __future__ import annotations

from lesr.adapters.schemas import SchemaCatalog
from lesr.domain.approval import SignedApproval
from lesr.domain.review import (
    ApprovalRevocation,
    CommentResolution,
    ConditionSatisfaction,
    ReviewComment,
    ReviewPackage,
)
from lesr.domain.semantic import document_hash, semantic_hash
from lesr.domain.workspace import WorkspaceCheckpoint

NOW = "2026-08-30T00:00:00Z"
COMMIT = "1" * 40
HASH = "sha256:" + "a" * 64


def uid(index: int) -> str:
    return f"018f0000-0000-7000-8000-{index:012d}"


def test_runtime_2_reads_runtime_1x_governance_records_without_reemitting_helpers() -> None:
    catalog = SchemaCatalog()
    package_base: dict[str, object] = {
        "schema_version": "1.0",
        "resource_type": "review_package",
        "package_uid": uid(1),
        "workspace_uid": uid(2),
        "base_commit": COMMIT,
        "configuration_uid": uid(3),
        "result_configuration_uid": uid(4),
        "result_configuration_hash": HASH,
        "candidate_hash": HASH,
        "candidate_scope": [uid(5)],
        "semantic_diff_hash": HASH,
        "graph_snapshot_hash": HASH,
        "context_bundle_hash": HASH,
        "impact_report_hash": HASH,
        "validation_hash": HASH,
        "finding_hashes": [],
        "governance_finding_uids": [],
        "review_policy": {
            "stages": [{"stage": "technical", "role": "technical", "minimum_count": 1}],
            "require_preparer_independence": True,
            "require_comment_resolution": True,
        },
        "effective_model_hash": HASH,
        "prepared_by_actor_uid": uid(6),
        "created_at": NOW,
    }
    legacy_package = package_base | {"subject_hash": semantic_hash(package_base)}
    legacy_package["package_hash"] = document_hash(legacy_package, "package_hash")
    catalog.validate("review-package.schema.json", legacy_package)
    package = ReviewPackage.model_validate(legacy_package)
    assert package.package_hash == legacy_package["package_hash"]
    assert "subject_hash" not in package.model_dump(mode="json")

    comment_base: dict[str, object] = {
        "schema_version": "1.0",
        "resource_type": "review_comment",
        "comment_uid": uid(7),
        "package_hash": package.package_hash,
        "resource_uid": uid(5),
        "location": "/statement",
        "author_uid": uid(8),
        "body": "Clarify the acceptance condition.",
        "created_at": NOW,
    }
    legacy_comment = comment_base | {
        "comment_hash": document_hash(comment_base, "comment_hash")
    }
    catalog.validate("review-comment.schema.json", legacy_comment)
    comment = ReviewComment.model_validate(legacy_comment)
    assert str(legacy_comment["comment_hash"]) in comment.references
    assert "comment_hash" not in comment.model_dump(mode="json")

    resolution_base: dict[str, object] = {
        "schema_version": "1.0",
        "resource_type": "comment_resolution",
        "resolution_uid": uid(9),
        "comment_hash": legacy_comment["comment_hash"],
        "actor_uid": uid(10),
        "disposition": "accepted",
        "rationale": "Acceptance condition added.",
        "created_at": NOW,
    }
    legacy_resolution = resolution_base | {
        "resolution_hash": document_hash(resolution_base, "resolution_hash")
    }
    catalog.validate("comment-resolution.schema.json", legacy_resolution)
    resolution = CommentResolution.model_validate(legacy_resolution)
    assert resolution.comment_reference == legacy_comment["comment_hash"]
    assert "comment_hash" not in resolution.model_dump(mode="json", exclude_none=True)
    assert "resolution_hash" not in resolution.model_dump(mode="json", exclude_none=True)

    condition = {"statement": "Evidence attached"}
    satisfaction_base: dict[str, object] = {
        "schema_version": "1.0",
        "resource_type": "condition_satisfaction",
        "satisfaction_uid": uid(11),
        "approval_uid": uid(12),
        "condition_hash": semantic_hash({"condition": condition}),
        "evidence_uids": [uid(13)],
        "actor_uid": uid(14),
        "satisfied_at": NOW,
    }
    legacy_satisfaction = satisfaction_base | {
        "satisfaction_hash": document_hash(satisfaction_base, "satisfaction_hash")
    }
    catalog.validate("condition-satisfaction.schema.json", legacy_satisfaction)
    satisfaction = ConditionSatisfaction.model_validate(legacy_satisfaction)
    assert satisfaction.matches(condition)
    assert "condition_hash" not in satisfaction.model_dump(mode="json", exclude_none=True)
    assert "satisfaction_hash" not in satisfaction.model_dump(mode="json", exclude_none=True)

    revocation_base: dict[str, object] = {
        "schema_version": "1.0",
        "resource_type": "approval_revocation",
        "revocation_uid": uid(15),
        "approval_uid": uid(12),
        "actor_uid": uid(14),
        "reason": "Superseded by a later engineering decision.",
        "revoked_at": NOW,
    }
    legacy_revocation = revocation_base | {
        "revocation_hash": document_hash(revocation_base, "revocation_hash")
    }
    catalog.validate("approval-revocation.schema.json", legacy_revocation)
    revocation = ApprovalRevocation.model_validate(legacy_revocation)
    assert "revocation_hash" not in revocation.model_dump(mode="json")

    scope = {"resource_uids": [uid(5)]}
    legacy_approval = {
        "schema_version": "1.0",
        "resource_type": "approval_attestation",
        "approval_uid": uid(12),
        "package_hash": package.package_hash,
        "effective_model_hash": HASH,
        "scope": scope,
        "scope_hash": semantic_hash(scope),
        "approval_type": "technical",
        "actor_uid": uid(14),
        "actor_role": "technical",
        "actor_type": "human",
        "issued_at": NOW,
        "expires_at": None,
        "conditions": [condition],
        "signature_algorithm": "Ed25519",
        "key_uid": uid(16),
        "signature": "A" * 88,
        "provenance_uid": uid(17),
    }
    catalog.validate("approval-attestation.schema.json", legacy_approval)
    approval = SignedApproval.model_validate(legacy_approval)
    assert "scope_hash" not in approval.model_dump(mode="json")


def test_runtime_2_accepts_legacy_checkpoint_and_audit_shapes() -> None:
    catalog = SchemaCatalog()
    workspace = {
        "schema_version": "1.0",
        "resource_type": "change_workspace",
        "workspace_uid": uid(20),
        "base_commit": COMMIT,
        "configuration_uid": uid(21),
        "effective_model_hash": HASH,
        "delegation_uid": uid(22),
        "actor_uid": uid(23),
        "working_copies": [],
        "checkpoint_uids": [],
        "state": "editable",
        "created_at": NOW,
    }
    checkpoint_base: dict[str, object] = {
        "schema_version": "1.0",
        "resource_type": "workspace_checkpoint",
        "checkpoint_uid": uid(24),
        "workspace_uid": uid(20),
        "base_commit": COMMIT,
        "working_state_hash": HASH,
        "edit_scope": [],
        "actor_uid": uid(23),
        "validation_summary": [],
        "created_at": NOW,
        "git_ref": f"refs/lesr/workspaces/{uid(20)}",
        "workspace_state": workspace,
    }
    legacy_checkpoint = checkpoint_base | {
        "checkpoint_hash": document_hash(checkpoint_base, "checkpoint_hash")
    }
    catalog.validate("checkpoint.schema.json", legacy_checkpoint)
    checkpoint = WorkspaceCheckpoint.model_validate(legacy_checkpoint)
    assert "checkpoint_hash" not in checkpoint.model_dump(mode="json")

    legacy_audit = {
        "schema_version": "1.0",
        "resource_type": "audit_anchor",
        "anchor_uid": uid(25),
        "transaction_uid": uid(25),
        "previous_anchor_hash": None,
        "event_hashes": [HASH],
        "created_at": NOW,
        "anchor_hash": HASH,
    }
    catalog.validate("audit-anchor.schema.json", legacy_audit)
