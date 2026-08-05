"""LESR v1 MCP adapter. Only this module imports the replaceable MCP SDK."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from lesr.application.contracts import (
    LESRDomainPort,
    RiskClass,
    WriteEnvelope,
)
from lesr.domain.catalog import CAPABILITIES, RUNTIME_CONTRACT_VERSION


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
            "capabilities": [item.model_dump(mode="json") for item in CAPABILITIES if item.mcp],
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
        start_uid: str, predicate: str | None = None, max_depth: int = 4
    ) -> dict[str, Any]:
        """Traverse the bounded canonical relation graph without exposing SQL."""
        return domain.traverse(start_uid, predicate, max_depth).payload()

    @server.tool(annotations=read_only, structured_output=True)
    def impact(start_uid: str, max_depth: int = 4) -> dict[str, Any]:
        """Return bounded bidirectional impact over canonical relations."""
        return domain.impact(start_uid, max_depth).payload()

    @server.tool(name="context_plan", annotations=read_only, structured_output=True)
    def build_context(
        task_type: str,
        target_uids: list[str],
        token_budget: int,
        configuration_uid: str,
        actor: str,
    ) -> dict[str, Any]:
        """Build an explainable Context Contract with explicit completeness."""
        return domain.build_context(
            task_type, tuple(target_uids), token_budget, configuration_uid, actor
        ).payload()

    @server.tool(name="workspace_submit", annotations=write, structured_output=True)
    def prepare_review(
        workspace_uid: str,
        expected_base: str,
        idempotency_key: str,
        actor: str,
        delegation_uid: str,
        dry_run: bool,
        risk_class: RiskClass,
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
                risk_class,
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
        risk_class: RiskClass,
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
                risk_class,
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
        risk_class: RiskClass,
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
                risk_class,
                operation,
            )
        ).payload()

    @server.tool(name="apply", annotations=atomic_apply, structured_output=True)
    def apply_transaction(
        workspace_uid: str,
        expected_base: str,
        idempotency_key: str,
        actor: str,
        delegation_uid: str,
        dry_run: bool,
        risk_class: RiskClass,
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
                risk_class,
                operation,
            )
        ).payload()

    @server.tool(name="context_trace", annotations=write, structured_output=True)
    def start_task(task_type: str, request: dict[str, Any]) -> dict[str, Any]:
        """Start a protocol-independent long-running domain task."""
        return domain.start_task(task_type, request).payload()

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


def _write(
    workspace_uid: str,
    expected_base: str,
    idempotency_key: str,
    actor: str,
    delegation_uid: str,
    dry_run: bool,
    risk_class: RiskClass,
    operation: dict[str, Any],
) -> WriteEnvelope:
    return WriteEnvelope(
        workspace_uid,
        expected_base,
        idempotency_key,
        actor,
        delegation_uid,
        dry_run,
        risk_class,
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
