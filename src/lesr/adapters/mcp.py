"""LESR v1 MCP adapter. Only this module imports the replaceable MCP SDK."""

from __future__ import annotations

import os
from dataclasses import asdict
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from lesr.application.contracts import (
    LESRDomainPort,
    RiskClass,
    WriteEnvelope,
)


def create_server(domain: LESRDomainPort) -> FastMCP:
    server = FastMCP("LESR v1")

    @server.tool()
    def capabilities() -> dict[str, Any]:
        """Negotiate the versioned LESR domain capability groups."""
        return {
            "domain_contract": "1.0",
            "capabilities": [asdict(item) for item in domain.capabilities()],
        }

    @server.tool()
    def resolve(identifier: str) -> dict[str, Any]:
        """Resolve a UID, Human Key or Alias without assuming a current revision."""
        return domain.resolve(identifier).payload()

    @server.tool()
    def inspect(uid: str) -> dict[str, Any]:
        """Inspect a resolved logical object or exact resource."""
        return domain.inspect(uid).payload()

    @server.tool()
    def query(
        kind: str | None = None, cursor: str | None = None, page_size: int = 50
    ) -> dict[str, Any]:
        """Page through structured resources; no arbitrary SQL is exposed."""
        return domain.query(kind, cursor, page_size).payload()

    @server.tool()
    def build_context(
        task_type: str, target_uids: list[str], token_budget: int
    ) -> dict[str, Any]:
        """Build an explainable Context Contract with explicit completeness."""
        return domain.build_context(task_type, tuple(target_uids), token_budget).payload()

    @server.tool()
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

    @server.tool()
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

    @server.tool()
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

    @server.tool()
    def start_task(task_type: str, request: dict[str, Any]) -> dict[str, Any]:
        """Start a protocol-independent long-running domain task."""
        return domain.start_task(task_type, request).payload()

    @server.tool()
    def task_status(task_uid: str) -> dict[str, Any]:
        """Return long-task state."""
        return domain.task_status(task_uid).payload()

    @server.tool()
    def cancel_task(task_uid: str) -> dict[str, Any]:
        """Cancel a long task when supported."""
        return domain.cancel_task(task_uid).payload()

    @server.tool()
    def task_result(task_uid: str) -> dict[str, Any]:
        """Return the completed task result or a retryable structured error."""
        return domain.task_result(task_uid).payload()

    @server.resource("lesr://objects/{uid}")
    def object_resource(uid: str) -> str:
        """Stable read-only logical-object resource."""
        import json

        return json.dumps(domain.inspect(uid).payload(), ensure_ascii=False, sort_keys=True)

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
    from lesr.application.service import RepositoryDomainService

    domain: LESRDomainPort = RepositoryDomainService(Path(project))
    create_server(domain).run()


if __name__ == "__main__":
    main()
