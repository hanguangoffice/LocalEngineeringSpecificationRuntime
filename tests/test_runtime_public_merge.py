from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from lesr.application.contracts import WriteEnvelope
from lesr.application.runtime import LocalRuntimeService
from lesr.domain.merge import ForeignDiff
from lesr.domain.review import CommentResolution, ReviewPackage, ReviewPolicy, StageQuorum
from lesr.domain.semantic import SemanticField
from lesr.domain.workspace import WorkingCopy, Workspace


def envelope(
    domain: LocalRuntimeService,
    workspace_uid: str,
    operation: dict[str, object],
) -> WriteEnvelope:
    return WriteEnvelope(
        workspace_uid,
        domain.base,
        f"request-{workspace_uid}-{operation.get('new_base_commit', 'operation')}",
        "human-reviewer",
        "delegation-1",
        False,
        operation,
    )


def workspace(domain: LocalRuntimeService, uid: str, statement: str) -> Workspace:
    copy = WorkingCopy(
        workspace_uid=uid,
        object_uid="object-1",
        base_revision_uid=None,
        human_key="REQ-1",
        kind="requirement",
        effective_model_hash="model-1",
        delegation_uid="delegation-1",
        draft_fields=(SemanticField(path="/statement", value=statement),),
    )
    return Workspace(
        workspace_uid=uid,
        base_commit=domain.base,
        configuration_uid="configuration-1",
        effective_model_hash="model-1",
        delegation_uid="delegation-1",
        actor_uid="human-reviewer",
        working_copies=(copy,),
        created_at=datetime.now(UTC),
    )


def test_public_rebase_merge_and_reconciliation_persist_to_workspace_refs(
    tmp_path: Path,
) -> None:
    domain = LocalRuntimeService(tmp_path / "project")
    first = workspace(domain, "workspace-1", "ours")
    second = workspace(domain, "workspace-2", "theirs")
    domain.workspaces = {first.workspace_uid: first, second.workspace_uid: second}
    domain._checkpoint_workspace(first)
    domain._checkpoint_workspace(second)

    rebased = domain.rebase_workspace(
        envelope(
            domain,
            first.workspace_uid,
            {"new_base_commit": domain.base},
        )
    )
    assert rebased.ok, rebased.payload()
    assert rebased.value["approvals_invalidated"] is True

    merged = domain.merge_workspace(
        envelope(
            domain,
            first.workspace_uid,
            {"source_workspace_uid": second.workspace_uid},
        )
    )
    assert merged.ok, merged.payload()
    assert not merged.value["results"]["object-1"]["conflicts"]
    assert merged.value["workspace"]["working_copies"][0]["draft_fields"][0][
        "value"
    ] == "theirs"

    recovered = LocalRuntimeService(domain.project)
    assert first.workspace_uid in recovered.workspaces
    assert first.workspace_uid in recovered.rebase_results

    diff = ForeignDiff(
        old_commit=domain.base,
        foreign_commit=domain.base,
        changed_paths=("canonical/revisions/foreign.json",),
        has_merge_commit=False,
    )
    reconciliation = recovered.begin_reconciliation(
        envelope(
            recovered,
            "reconciliation-request",
            {"foreign_diff": diff.model_dump(mode="json")},
        )
    )
    assert reconciliation.ok, reconciliation.payload()
    assert reconciliation.value["authority_status"] == (
        "not_authoritative_pending_reconciliation"
    )
    restarted = LocalRuntimeService(domain.project)
    assert reconciliation.value["workspace_uid"] in restarted.reconciliation


def test_public_review_records_keep_package_immutable_and_survive_restart(tmp_path: Path) -> None:
    domain = LocalRuntimeService(tmp_path / "project")
    work = workspace(domain, "workspace-review", "review me")
    domain.workspaces[work.workspace_uid] = work
    package = ReviewPackage(
        workspace_uid=work.workspace_uid,
        base_commit=domain.base,
        configuration_uid="configuration-1",
        result_configuration_uid="configuration-1",
        result_configuration_hash="sha256:configuration-next",
        candidate_hash="sha256:candidate",
        candidate_scope=("object-1",),
        semantic_diff_hash="sha256:diff",
        graph_snapshot_hash="sha256:graph",
        context_bundle_hash="sha256:context",
        impact_report_hash="sha256:impact",
        validation_hash="sha256:validation",
        finding_hashes=(),
        review_policy=ReviewPolicy(
            stages=(StageQuorum(stage="apply", role="technical", minimum_count=1),)
        ),
        effective_model_hash="sha256:model",
        prepared_by_actor_uid="preparer",
        created_at=datetime.now(UTC),
    )
    domain.reviews[package.package_uid] = package
    commented = domain.add_review_comment(
        envelope(
            domain,
            work.workspace_uid,
            {
                "package_uid": package.package_uid,
                "comment": {
                    "resource_uid": "object-1",
                    "location": "/statement",
                    "author_uid": "reviewer",
                    "body": "Clarify the timing bound.",
                    "created_at": datetime.now(UTC).isoformat(),
                },
            },
        )
    )
    assert commented.ok, commented.payload()
    replacement = commented.value["review_package"]
    assert replacement["package_hash"] == package.package_hash
    assert commented.value["approvals_invalidated"] is False
    comment = commented.value["comment"]
    resolution = CommentResolution(
        comment_hash=comment["comment_hash"],
        actor_uid="reviewer",
        disposition="accepted",
        rationale="Timing bound added to the candidate.",
        created_at=datetime.now(UTC),
    )
    resolved = domain.resolve_review_comment(
        envelope(
            domain,
            work.workspace_uid,
            {"record": resolution.model_dump(mode="json")},
        )
    )
    assert resolved.ok, resolved.payload()
    restarted = LocalRuntimeService(domain.project)
    assert len(restarted.review_records[work.workspace_uid]) == 2
