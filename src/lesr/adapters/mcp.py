"""LESR v1 MCP adapter. Only this module imports the replaceable MCP SDK."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, cast

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from lesr.application.contracts import (
    LESRDomainPort,
    WorkspaceAssessmentRequest,
    WriteEnvelope,
)
from lesr.domain.catalog import RUNTIME_CAPABILITIES, RUNTIME_CONTRACT_VERSION
from lesr.domain.semantic import uuid7_candidate


def create_server(domain: LESRDomainPort) -> FastMCP:
    server = FastMCP("LESR v1")
    read_only = ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    )
    write = ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=False,
        openWorldHint=False,
    )
    atomic_apply = ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=True,
        idempotentHint=True,
        openWorldHint=False,
    )

    @server.tool(annotations=read_only, structured_output=True)
    def capabilities() -> dict[str, Any]:
        """Negotiate the versioned LESR domain capability groups."""
        return {
            "domain_contract": RUNTIME_CONTRACT_VERSION,
            "capabilities": [
                item.model_dump(mode="json")
                for item in RUNTIME_CAPABILITIES
                if item.mcp
            ],
        }

    @server.tool(annotations=read_only, structured_output=True)
    def resolve(identifier: str) -> dict[str, Any]:
        """Resolve a UID, Human Key or Alias without assuming a current revision."""
        return domain.resolve(identifier).payload()

    @server.tool(annotations=read_only, structured_output=True)
    def inspect(uid: str) -> dict[str, Any]:
        """Inspect a resolved logical object or exact resource."""
        return domain.inspect(uid).payload()

    @server.tool(annotations=read_only, structured_output=True)
    def query(
        kind: str | None = None,
        cursor: str | None = None,
        page_size: int = 50,
        text: str | None = None,
    ) -> dict[str, Any]:
        """Page through structured resources; no arbitrary SQL is exposed."""
        return domain.query(kind, cursor, page_size, text).payload()

    @server.tool(annotations=read_only, structured_output=True)
    def traverse(
        start_uid: str,
        configuration_uid: str,
        evaluation_time: str,
        predicate: str | None = None,
        max_depth: int = 4,
    ) -> dict[str, Any]:
        """Traverse the bounded canonical relation graph without exposing SQL."""
        return domain.traverse(
            start_uid, predicate, max_depth, configuration_uid, evaluation_time
        ).payload()

    @server.tool(annotations=read_only, structured_output=True)
    def impact(
        start_uid: str,
        configuration_uid: str,
        evaluation_time: str,
        max_depth: int = 4,
    ) -> dict[str, Any]:
        """Return bounded bidirectional impact over canonical relations."""
        return domain.impact(
            start_uid, max_depth, configuration_uid, evaluation_time
        ).payload()

    @server.tool(name="context_plan", annotations=read_only, structured_output=True)
    def build_context(
        task_type: str,
        target_uids: list[str],
        token_budget: int,
        configuration_uid: str,
        actor: str,
        evaluation_time: str,
    ) -> dict[str, Any]:
        """Build an explainable Context Contract with explicit completeness."""
        return domain.build_context(
            task_type,
            tuple(target_uids),
            token_budget,
            configuration_uid,
            actor,
            evaluation_time,
        ).payload()

    @server.tool(name="context_read", annotations=read_only, structured_output=True)
    def read_context(
        bundle_hash: str,
        resource_uids: list[str] | None = None,
        maximum_resources: int = 100,
        maximum_bytes: int = 2 * 1024 * 1024,
    ) -> dict[str, Any]:
        """Read exact fields, Fragments and text selected by a Context Manifest."""
        reader = getattr(domain, "read_context", None)
        if not callable(reader):
            return _capability_unavailable("context.read")
        return cast(
            dict[str, Any],
            reader(
                bundle_hash,
                tuple(resource_uids or ()),
                maximum_resources,
                maximum_bytes,
            ).payload(),
        )

    @server.tool(name="context_trace", annotations=write, structured_output=True)
    def start_context_trace(
        bundle_hash: str, start_uid: str, max_depth: int = 16
    ) -> dict[str, Any]:
        """Queue a persistent Deep Trace task from an immutable Context Manifest."""
        starter = getattr(domain, "start_deep_trace", None)
        if not callable(starter):
            return _capability_unavailable("context.trace")
        return cast(
            dict[str, Any], starter(bundle_hash, start_uid, max_depth).payload()
        )

    @server.tool(name="workspace_validate", annotations=read_only, structured_output=True)
    def assess_workspace(
        workspace_uid: str,
        evaluation_time: str,
        maximum_depth: int = 3,
    ) -> dict[str, Any]:
        """Evaluate an editable Workspace without freezing or submitting it."""
        return domain.assess_workspace(
            WorkspaceAssessmentRequest(
                workspace_uid=workspace_uid,
                evaluation_time=evaluation_time,
                maximum_depth=maximum_depth,
            )
        ).payload()

    @server.tool(name="workspace_submit", annotations=write, structured_output=True)
    def prepare_review(
        workspace_uid: str,
        expected_base: str,
        idempotency_key: str,
        actor: str,
        delegation_uid: str,
        dry_run: bool,
        operation: dict[str, Any],
    ) -> dict[str, Any]:
        """Run Profile-derived validation and create an immutable review package."""
        return domain.prepare_review(
            _write(
                workspace_uid,
                expected_base,
                idempotency_key,
                actor,
                delegation_uid,
                dry_run,
                operation,
            )
        ).payload()

    @server.tool(name="workspace_open", annotations=write, structured_output=True)
    def open_workspace(
        workspace_uid: str,
        expected_base: str,
        idempotency_key: str,
        actor: str,
        delegation_uid: str,
        dry_run: bool,
        operation: dict[str, Any],
    ) -> dict[str, Any]:
        """Open an isolated workspace through the standard write envelope."""
        return domain.open_workspace(
            _write(
                workspace_uid,
                expected_base,
                idempotency_key,
                actor,
                delegation_uid,
                dry_run,
                operation,
            )
        ).payload()

    @server.tool(name="workspace_edit", annotations=write, structured_output=True)
    def propose_operation(
        workspace_uid: str,
        expected_base: str,
        idempotency_key: str,
        actor: str,
        delegation_uid: str,
        dry_run: bool,
        operation: dict[str, Any],
    ) -> dict[str, Any]:
        """Propose a structured semantic operation; no raw file write is exposed."""
        return domain.propose_operation(
            _write(
                workspace_uid,
                expected_base,
                idempotency_key,
                actor,
                delegation_uid,
                dry_run,
                operation,
            )
        ).payload()

    def invoke_write_capability(
        method_name: str,
        capability_name: str,
        workspace_uid: str,
        expected_base: str,
        idempotency_key: str,
        actor: str,
        delegation_uid: str,
        dry_run: bool,
        operation: dict[str, Any],
    ) -> dict[str, Any]:
        method = getattr(domain, method_name, None)
        if not callable(method):
            return _capability_unavailable(capability_name)
        return cast(
            dict[str, Any],
            method(
                _write(
                    workspace_uid,
                    expected_base,
                    idempotency_key,
                    actor,
                    delegation_uid,
                    dry_run,
                    operation,
                )
            ).payload(),
        )

    @server.tool(name="workspace_rebase", annotations=write, structured_output=True)
    def rebase_workspace(
        workspace_uid: str,
        expected_base: str,
        idempotency_key: str,
        actor: str,
        delegation_uid: str,
        dry_run: bool,
        operation: dict[str, Any],
    ) -> dict[str, Any]:
        """Rebase Working Copies through the deterministic three-way semantic engine."""
        return invoke_write_capability(
            "rebase_workspace", "workspace.rebase", workspace_uid, expected_base,
            idempotency_key, actor, delegation_uid, dry_run, operation
        )

    @server.tool(name="workspace_merge", annotations=write, structured_output=True)
    def merge_workspace(
        workspace_uid: str,
        expected_base: str,
        idempotency_key: str,
        actor: str,
        delegation_uid: str,
        dry_run: bool,
        operation: dict[str, Any],
    ) -> dict[str, Any]:
        """Merge another Workspace without treating a Git merge as authority."""
        return invoke_write_capability(
            "merge_workspace", "workspace.merge", workspace_uid, expected_base,
            idempotency_key, actor, delegation_uid, dry_run, operation
        )

    @server.tool(name="workspace_resolve", annotations=write, structured_output=True)
    def resolve_workspace_conflict(
        workspace_uid: str,
        expected_base: str,
        idempotency_key: str,
        actor: str,
        delegation_uid: str,
        dry_run: bool,
        operation: dict[str, Any],
    ) -> dict[str, Any]:
        """Resolve one structured semantic merge conflict."""
        return invoke_write_capability(
            "resolve_merge_conflict", "workspace.resolve", workspace_uid, expected_base,
            idempotency_key, actor, delegation_uid, dry_run, operation
        )

    @server.tool(name="review_record", annotations=write, structured_output=True)
    def write_review_record(
        record_type: str,
        workspace_uid: str,
        expected_base: str,
        idempotency_key: str,
        actor: str,
        delegation_uid: str,
        dry_run: bool,
        operation: dict[str, Any],
    ) -> dict[str, Any]:
        """Create a comment, resolution, condition satisfaction, or revocation record."""
        methods = {
            "comment": ("add_review_comment", "review.comment"),
            "resolution": ("resolve_review_comment", "review.resolve"),
            "condition": ("satisfy_review_condition", "review.condition"),
            "revocation": ("revoke_approval", "review.revoke"),
        }
        selected = methods.get(record_type)
        if selected is None:
            return _capability_unavailable(f"review.{record_type}")
        return invoke_write_capability(
            selected[0], selected[1], workspace_uid, expected_base, idempotency_key,
            actor, delegation_uid, dry_run, operation
        )

    @server.tool(name="reconciliation_open", annotations=write, structured_output=True)
    def open_reconciliation(
        workspace_uid: str,
        expected_base: str,
        idempotency_key: str,
        actor: str,
        delegation_uid: str,
        dry_run: bool,
        operation: dict[str, Any],
    ) -> dict[str, Any]:
        """Open a non-authoritative Workspace for a detected foreign Canonical diff."""
        return invoke_write_capability(
            "begin_reconciliation", "reconciliation.open", workspace_uid, expected_base,
            idempotency_key, actor, delegation_uid, dry_run, operation
        )

    @server.tool(name="apply", annotations=atomic_apply, structured_output=True)
    def apply_transaction(
        workspace_uid: str,
        expected_base: str,
        idempotency_key: str,
        actor: str,
        delegation_uid: str,
        dry_run: bool,
        operation: dict[str, Any],
    ) -> dict[str, Any]:
        """Apply an approved transaction with base and idempotency checks."""
        return domain.apply_transaction(
            _write(
                workspace_uid,
                expected_base,
                idempotency_key,
                actor,
                delegation_uid,
                dry_run,
                operation,
            )
        ).payload()

    @server.tool(name="baseline_prepare", annotations=write, structured_output=True)
    def prepare_baseline(
        workspace_uid: str,
        expected_base: str,
        idempotency_key: str,
        actor: str,
        delegation_uid: str,
        dry_run: bool,
        operation: dict[str, Any],
    ) -> dict[str, Any]:
        preparer = getattr(domain, "prepare_baseline", None)
        if not callable(preparer):
            return _capability_unavailable("baseline.prepare")
        return cast(
            dict[str, Any],
            preparer(
                _write(
                    workspace_uid,
                    expected_base,
                    idempotency_key,
                    actor,
                    delegation_uid,
                    dry_run,
                    operation,
                )
            ).payload(),
        )

    @server.tool(name="baseline_apply", annotations=atomic_apply, structured_output=True)
    def apply_baseline(
        workspace_uid: str,
        expected_base: str,
        idempotency_key: str,
        actor: str,
        delegation_uid: str,
        dry_run: bool,
        operation: dict[str, Any],
    ) -> dict[str, Any]:
        applier = getattr(domain, "apply_baseline", None)
        if not callable(applier):
            return _capability_unavailable("baseline.apply")
        return cast(
            dict[str, Any],
            applier(
                _write(
                    workspace_uid,
                    expected_base,
                    idempotency_key,
                    actor,
                    delegation_uid,
                    dry_run,
                    operation,
                )
            ).payload(),
        )

    @server.tool(name="task_start", annotations=write, structured_output=True)
    def start_task(task_type: str, request: dict[str, Any]) -> dict[str, Any]:
        """Start a protocol-independent long-running domain task."""
        if task_type not in {"full_validation", "deep_trace", "large_impact"}:
            return _capability_unavailable(f"task.{task_type}")
        return domain.start_task(task_type, request).payload()

    @server.tool(name="mission_create", annotations=write, structured_output=True)
    def create_mission(plan: dict[str, Any]) -> dict[str, Any]:
        """Create a local engineering Mission and its dependency-ordered work packages."""
        return domain.create_mission(plan).payload()

    @server.tool(name="mission_list", annotations=read_only, structured_output=True)
    def list_missions() -> dict[str, Any]:
        """List local Missions with their current engineering progress."""
        return domain.list_missions().payload()

    @server.tool(name="mission_inspect", annotations=read_only, structured_output=True)
    def inspect_mission(mission_uid: str) -> dict[str, Any]:
        """Inspect one Mission and all of its work-package states."""
        return domain.inspect_mission(mission_uid).payload()

    @server.tool(name="mission_ready_work", annotations=read_only, structured_output=True)
    def ready_mission_work(mission_uid: str) -> dict[str, Any]:
        """List work packages that are ready for an Agent to claim."""
        return domain.ready_mission_work(mission_uid).payload()

    @server.tool(name="mission_claim_work", annotations=write, structured_output=True)
    def claim_mission_work(
        mission_uid: str,
        work_package_uid: str,
        agent_identity: str,
        provider: str,
        model_identifier: str,
        client: str,
    ) -> dict[str, Any]:
        """Atomically claim one ready work package for one Agent run."""
        return domain.claim_mission_work(
            mission_uid,
            work_package_uid,
            agent_identity,
            provider,
            model_identifier,
            client,
        ).payload()

    @server.tool(name="mission_report_work", annotations=write, structured_output=True)
    def report_mission_work(report: dict[str, Any]) -> dict[str, Any]:
        """Record the terminal outcome of a claimed Agent run."""
        return domain.report_mission_work(report).payload()

    @server.tool(name="decision_list", annotations=read_only, structured_output=True)
    def list_decisions(mission_uid: str | None = None) -> dict[str, Any]:
        """List unresolved material decisions that need the local user."""
        return domain.list_decisions(mission_uid).payload()

    @server.tool(name="decision_resolve", annotations=write, structured_output=True)
    def resolve_decision(
        decision_request_uid: str,
        actor_uid: str,
        reason: str,
        selected_action: str | None = None,
        selected_alternative: str | None = None,
    ) -> dict[str, Any]:
        """Resolve one material engineering choice and resume its work package."""
        return domain.resolve_decision(
            decision_request_uid,
            actor_uid,
            reason,
            selected_action,
            selected_alternative,
        ).payload()

    @server.resource("lesr://objects/{uid}")
    def object_resource(uid: str) -> str:
        """Stable read-only logical-object resource."""
        import json

        return json.dumps(domain.inspect(uid).payload(), ensure_ascii=False, sort_keys=True)

    @server.resource("lesr://tasks/{uid}")
    def task_resource(uid: str) -> str:
        """Stable local task state and result without exposing the runtime database."""
        import json

        return json.dumps(domain.task_status(uid).payload(), ensure_ascii=False, sort_keys=True)

    return server


def _capability_unavailable(name: str) -> dict[str, Any]:
    return {
        "ok": False,
        "error": {
            "code": "LESR-CAPABILITY-UNAVAILABLE",
            "category": "not_found",
            "message": f"capability is unavailable: {name}",
            "affected_resources": [],
            "rule_or_policy": None,
            "retryable": False,
            "suggested_capability": None,
            "correlation_id": uuid7_candidate(),
        },
    }


def _write(
    workspace_uid: str,
    expected_base: str,
    idempotency_key: str,
    actor: str,
    delegation_uid: str,
    dry_run: bool,
    operation: dict[str, Any],
) -> WriteEnvelope:
    return WriteEnvelope(
        workspace_uid,
        expected_base,
        idempotency_key,
        actor,
        delegation_uid,
        dry_run,
        operation,
    )


def main() -> None:
    project = os.environ.get("LESR_PROJECT")
    if not project:
        raise RuntimeError("LESR_PROJECT is required; no synthetic repository fallback is allowed")
    from lesr.application.runtime import LocalRuntimeService

    domain: LESRDomainPort = LocalRuntimeService(Path(project))
    create_server(domain).run()


if __name__ == "__main__":
    main()
