from __future__ import annotations

import asyncio
import inspect
import sys
from pathlib import Path

import pytest
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from lesr.adapters.mcp import create_server
from lesr.application import contracts
from lesr.application.contracts import (
    InMemoryDomainService,
    WorkspaceAssessmentRequest,
    WriteEnvelope,
)

REQUIRED_WRITE_FIELDS = {
    "workspace_uid",
    "expected_base",
    "idempotency_key",
    "actor",
    "delegation_uid",
    "dry_run",
    "operation",
}


def write(
    *,
    workspace: str = "WS-1",
    key: str = "KEY-1",
    operation: dict[str, object] | None = None,
) -> WriteEnvelope:
    return WriteEnvelope(
        workspace_uid=workspace,
        expected_base="commit-1",
        idempotency_key=key,
        actor="USER-1",
        delegation_uid="DEL-1",
        dry_run=False,
        operation=operation or {"type": "create_revision"},
    )


def test_domain_contract_has_no_mcp_sdk_dependency() -> None:
    source = inspect.getsource(contracts)
    assert "from mcp" not in source
    assert "import mcp" not in source


def test_resolve_query_context_and_structured_errors() -> None:
    domain = InMemoryDomainService()
    assert domain.resolve("REQ-SW-0001").payload()["value"]["uid"] == "018f0000-0000-7000-8000-000000000001"
    assert domain.resolve("REQ-OLD-0001").ok
    missing = domain.inspect("missing").payload()["error"]
    assert set(missing) == {
        "code",
        "category",
        "message",
        "affected_resources",
        "rule_or_policy",
        "retryable",
        "suggested_capability",
        "correlation_id",
    }
    assert domain.query(None, None, 1).payload()["value"]["next_cursor"] == "1"
    context = domain.build_context(
        "coding",
        ("018f0000-0000-7000-8000-000000000001",),
        1,
        evaluation_time="2026-08-05T00:00:00Z",
    ).payload()["value"]
    assert context["completeness"] == "incomplete_budget"


def test_workspace_apply_requires_review_and_is_idempotent() -> None:
    domain = InMemoryDomainService()
    opened = domain.open_workspace(write()).payload()
    assert opened["ok"]
    proposal = domain.propose_operation(write(key="KEY-2"))
    assert proposal.ok
    assert "risk_class" not in proposal.value
    missing_approval = domain.apply_transaction(write(key="KEY-3")).payload()
    assert missing_approval["error"]["code"] == "LESR-APPROVAL-REQUIRED"
    approved = write(
        key="KEY-4",
        operation={
            "type": "create_revision",
            "review_package_hash": "sha256:package",
            "approval_uid": "APR-1",
        },
    )
    result = domain.apply_transaction(approved).payload()["value"]
    assert result["result_commit"] == "commit-2"
    replay = domain.apply_transaction(approved).payload()["value"]
    assert replay["idempotent_replay"]


def test_workspace_assessment_contract_is_read_only_and_has_no_caller_authority() -> None:
    domain = InMemoryDomainService()
    domain.open_workspace(write())
    before = dict(domain.workspaces["WS-1"])
    request = WorkspaceAssessmentRequest(
        workspace_uid="WS-1",
        evaluation_time="2026-08-05T00:00:00Z",
        maximum_depth=3,
    )

    result = domain.assess_workspace(request)

    assert result.payload()["error"]["code"] == "LESR-ADAPTER-ONLY"
    assert domain.workspaces["WS-1"] == before
    assert set(inspect.signature(WorkspaceAssessmentRequest).parameters) == {
        "workspace_uid",
        "evaluation_time",
        "maximum_depth",
    }
    assert "risk_class" not in inspect.signature(WriteEnvelope).parameters
    with pytest.raises(TypeError, match="risk_class"):
        WriteEnvelope(  # type: ignore[call-arg]
            workspace_uid="WS-2",
            expected_base="commit-1",
            idempotency_key="KEY-RISK",
            actor="USER-1",
            delegation_uid="DEL-1",
            dry_run=False,
            risk_class="high",
            operation={"type": "create_revision"},
        )


def test_long_task_contract_is_protocol_independent() -> None:
    domain = InMemoryDomainService()
    task = domain.start_task("validate_all", {"scope": "project"}).payload()["value"]
    assert domain.task_status(task["task_uid"]).ok
    assert domain.task_result(task["task_uid"]).payload()["error"]["retryable"]
    assert domain.cancel_task(task["task_uid"]).payload()["value"]["state"] == "cancelled"


def test_mcp_adapter_exposes_capabilities_resources_and_safe_write_schemas() -> None:
    server = create_server(InMemoryDomainService())
    tools = {tool.name: tool for tool in asyncio.run(server.list_tools())}
    assert {
        "capabilities",
        "resolve",
        "inspect",
        "query",
        "traverse",
        "impact",
        "context_plan",
        "workspace_validate",
        "workspace_open",
        "workspace_edit",
        "workspace_submit",
        "apply",
        "context_trace",
        "context_read",
        "task_start",
        "baseline_prepare",
            "baseline_apply",
            "workspace_rebase",
            "workspace_merge",
            "workspace_resolve",
            "review_record",
            "reconciliation_open",
            "mission_create",
            "mission_list",
            "mission_inspect",
            "mission_ready_work",
            "mission_claim_work",
            "mission_report_work",
            "decision_list",
            "decision_resolve",
        } == set(tools)
    for name in (
        "workspace_open",
        "workspace_edit",
        "workspace_submit",
        "apply",
    ):
        properties = set(tools[name].inputSchema["properties"])
        assert REQUIRED_WRITE_FIELDS <= properties
        assert "risk_class" not in properties
        assert not {"sql", "path", "shell", "command"} & properties
    assessment = tools["workspace_validate"]
    assert set(assessment.inputSchema["properties"]) == {
        "workspace_uid",
        "evaluation_time",
        "maximum_depth",
    }
    assert assessment.annotations is not None
    assert assessment.annotations.readOnlyHint is True
    templates = asyncio.run(server.list_resource_templates())
    assert any(str(item.uriTemplate).startswith("lesr://objects/") for item in templates)


def test_real_stdio_protocol_initializes_lists_and_calls_tools(tmp_path: Path) -> None:
    async def probe() -> None:
        parameters = StdioServerParameters(
            command=sys.executable,
            args=["-m", "lesr.adapters.mcp"],
            cwd=Path.cwd(),
            env={"LESR_PROJECT": str(tmp_path / "project")},
        )
        async with (
            stdio_client(parameters) as (read_stream, write_stream),
            ClientSession(read_stream, write_stream) as session,
        ):
            await session.initialize()
            tools = await session.list_tools()
            assert {item.name for item in tools.tools} >= {"capabilities", "resolve"}
            capabilities = await session.call_tool("capabilities", {})
            assert capabilities.isError is not True
            resolved = await session.call_tool("resolve", {"identifier": "REQ-SW-0001"})
            assert resolved.isError is not True
            assert resolved.structuredContent is not None
            assert resolved.structuredContent["ok"] is False
            assert resolved.structuredContent["error"]["code"] == "LESR-NOT-FOUND"

    asyncio.run(probe())
