"""LESR v1 domain capability contracts with no MCP SDK dependency."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import date, datetime
from enum import StrEnum
from typing import Any, Protocol

from lesr.domain.semantic import uuid7_candidate


class CapabilityGroup(StrEnum):
    RESOLVE = "resolve"
    INSPECT = "inspect"
    QUERY = "query"
    CONTEXT = "context"
    WORKSPACE = "workspace"
    GOVERNANCE = "governance"
    COMPLIANCE = "compliance"


class ErrorCategory(StrEnum):
    VALIDATION = "validation"
    NOT_FOUND = "not_found"
    CONFLICT = "conflict"
    AUTHORIZATION = "authorization"
    INDETERMINATE = "indeterminate"
    INTEGRITY = "integrity"
    INTERNAL = "internal"


class RiskClass(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class TaskState(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class CapabilityDescriptor:
    group: CapabilityGroup
    operations: tuple[str, ...]
    contract_version: str = "1.0"


@dataclass(frozen=True, slots=True)
class DomainErrorContract:
    code: str
    category: ErrorCategory
    message: str
    affected_resources: tuple[str, ...] = ()
    rule_or_policy: str | None = None
    retryable: bool = False
    suggested_capability: str | None = None
    correlation_id: str = field(default_factory=uuid7_candidate)

    def __post_init__(self) -> None:
        if self.suggested_capability is not None:
            from lesr.domain.catalog import CAPABILITIES

            names = {item.name for item in CAPABILITIES}
            if self.suggested_capability not in names:
                raise ValueError(
                    f"unknown suggested capability: {self.suggested_capability}"
                )


@dataclass(frozen=True, slots=True)
class DomainResult:
    value: Any = None
    error: DomainErrorContract | None = None

    @property
    def ok(self) -> bool:
        return self.error is None

    def payload(self) -> dict[str, Any]:
        if self.error is not None:
            return {"ok": False, "error": _jsonable(asdict(self.error))}
        return {"ok": True, "value": _jsonable(self.value)}


@dataclass(frozen=True, slots=True)
class WriteEnvelope:
    workspace_uid: str
    expected_base: str
    idempotency_key: str
    actor: str
    delegation_uid: str
    dry_run: bool
    risk_class: RiskClass
    operation: dict[str, Any]


@dataclass(frozen=True, slots=True)
class LongTask:
    task_uid: str
    task_type: str
    state: TaskState
    request: dict[str, Any]
    result: dict[str, Any] | None = None


class LESRDomainPort(Protocol):
    def capabilities(self) -> tuple[CapabilityDescriptor, ...]: ...

    def resolve(self, identifier: str) -> DomainResult: ...

    def inspect(self, uid: str) -> DomainResult: ...

    def query(
        self, kind: str | None, cursor: str | None, page_size: int, text: str | None = None
    ) -> DomainResult: ...

    def traverse(
        self,
        start_uid: str,
        predicate: str | None,
        max_depth: int,
        configuration_uid: str,
        evaluation_time: str,
    ) -> DomainResult: ...

    def impact(
        self,
        start_uid: str,
        max_depth: int,
        configuration_uid: str,
        evaluation_time: str,
    ) -> DomainResult: ...

    def build_context(
        self,
        task_type: str,
        target_uids: tuple[str, ...],
        token_budget: int,
        configuration_uid: str,
        actor: str,
        evaluation_time: str,
    ) -> DomainResult: ...

    def open_workspace(self, request: WriteEnvelope) -> DomainResult: ...

    def propose_operation(self, request: WriteEnvelope) -> DomainResult: ...

    def prepare_review(self, request: WriteEnvelope) -> DomainResult: ...

    def bootstrap_root_owner(
        self,
        trust: dict[str, Any],
        delegation: dict[str, Any],
        approval: dict[str, Any],
        idempotency_key: str,
        governance_operations: tuple[dict[str, Any], ...] = (),
    ) -> DomainResult: ...

    def initialize_configuration(
        self,
        configuration: dict[str, Any],
        approval: dict[str, Any],
        actor_uid: str,
        delegation_uid: str,
        idempotency_key: str,
    ) -> DomainResult: ...

    def create_configuration(
        self,
        configuration: dict[str, Any],
        approval: dict[str, Any],
        actor_uid: str,
        delegation_uid: str,
        idempotency_key: str,
        supporting_approvals: tuple[dict[str, Any], ...] = (),
    ) -> DomainResult: ...

    def plan_configuration(self, configuration: dict[str, Any]) -> DomainResult: ...

    def record_governance_approval(
        self,
        approval: dict[str, Any],
        actor_uid: str,
        delegation_uid: str,
        idempotency_key: str,
    ) -> DomainResult: ...

    def apply_transaction(self, request: WriteEnvelope) -> DomainResult: ...

    def start_task(self, task_type: str, request: dict[str, Any]) -> DomainResult: ...

    def task_status(self, task_uid: str) -> DomainResult: ...

    def cancel_task(self, task_uid: str) -> DomainResult: ...

    def task_result(self, task_uid: str) -> DomainResult: ...


class InMemoryDomainService:
    """Deterministic domain port for adapter conformance and embedded use."""

    def __init__(self) -> None:
        self.base = "commit-1"
        self.resources: dict[str, dict[str, Any]] = {
            "018f0000-0000-7000-8000-000000000001": {
                "uid": "018f0000-0000-7000-8000-000000000001",
                "human_key": "REQ-SW-0001",
                "aliases": ["REQ-OLD-0001"],
                "kind": "software_requirement",
                "revision_uid": "018f0000-0000-7000-8000-000000000002",
                "title": "MQTT reconnect",
            },
            "018f0000-0000-7000-8000-000000000003": {
                "uid": "018f0000-0000-7000-8000-000000000003",
                "human_key": "RULE-COM-0001",
                "aliases": [],
                "kind": "coding_rule",
                "revision_uid": "018f0000-0000-7000-8000-000000000004",
                "title": "Reconnect timeout",
            },
        }
        self.workspaces: dict[str, dict[str, Any]] = {}
        self.idempotency: dict[str, dict[str, Any]] = {}
        self.tasks: dict[str, LongTask] = {}

    def capabilities(self) -> tuple[CapabilityDescriptor, ...]:
        return (
            CapabilityDescriptor(CapabilityGroup.RESOLVE, ("resolve",)),
            CapabilityDescriptor(CapabilityGroup.INSPECT, ("inspect",)),
            CapabilityDescriptor(CapabilityGroup.QUERY, ("query", "compare")),
            CapabilityDescriptor(
                CapabilityGroup.CONTEXT, ("build_context", "check_completeness")
            ),
            CapabilityDescriptor(
                CapabilityGroup.WORKSPACE,
                ("open_workspace", "propose_operation", "checkpoint", "rebase"),
            ),
            CapabilityDescriptor(
                CapabilityGroup.GOVERNANCE,
                ("review", "approve", "apply_transaction", "create_baseline"),
            ),
            CapabilityDescriptor(
                CapabilityGroup.COMPLIANCE,
                ("compile_profile", "evaluate_rule", "run_validation"),
            ),
        )

    def resolve(self, identifier: str) -> DomainResult:
        matches = [
            item
            for item in self.resources.values()
            if identifier in {item["uid"], item["human_key"], *item["aliases"]}
        ]
        if len(matches) == 1:
            return DomainResult(matches[0])
        if not matches:
            return self._error(
                "LESR-NOT-FOUND",
                ErrorCategory.NOT_FOUND,
                f"identifier was not resolved: {identifier}",
                (identifier,),
                suggested="query",
            )
        return self._error(
            "LESR-IDENTIFIER-AMBIGUOUS",
            ErrorCategory.INDETERMINATE,
            f"identifier resolved to {len(matches)} resources",
            tuple(str(item["uid"]) for item in matches),
        )

    def inspect(self, uid: str) -> DomainResult:
        resource = self.resources.get(uid)
        if resource is None:
            return self._error(
                "LESR-NOT-FOUND", ErrorCategory.NOT_FOUND, "resource not found", (uid,)
            )
        return DomainResult(resource)

    def query(
        self,
        kind: str | None,
        cursor: str | None,
        page_size: int,
        text: str | None = None,
    ) -> DomainResult:
        if not 1 <= page_size <= 100:
            return self._error(
                "LESR-PAGE-SIZE-INVALID",
                ErrorCategory.VALIDATION,
                "page_size must be between 1 and 100",
            )
        try:
            offset = int(cursor or "0")
        except ValueError:
            return self._error(
                "LESR-CURSOR-INVALID", ErrorCategory.VALIDATION, "cursor is invalid"
            )
        items = sorted(self.resources.values(), key=lambda item: str(item["uid"]))
        if kind is not None:
            items = [item for item in items if item["kind"] == kind]
        if text is not None:
            needle = text.casefold()
            items = [item for item in items if needle in str(item).casefold()]
        page = items[offset : offset + page_size]
        next_cursor = str(offset + page_size) if offset + page_size < len(items) else None
        return DomainResult({"items": page, "next_cursor": next_cursor, "total": len(items)})

    def traverse(
        self,
        start_uid: str,
        predicate: str | None,
        max_depth: int,
        configuration_uid: str = "test-configuration",
        evaluation_time: str = "2026-08-05T00:00:00Z",
    ) -> DomainResult:
        del configuration_uid, evaluation_time
        del predicate, max_depth
        return self._error(
            "LESR-RELATION-NOT-FOUND",
            ErrorCategory.NOT_FOUND,
            "the in-memory adapter has no canonical relation graph",
            (start_uid,),
        )

    def impact(
        self,
        start_uid: str,
        max_depth: int,
        configuration_uid: str = "test-configuration",
        evaluation_time: str = "2026-08-05T00:00:00Z",
    ) -> DomainResult:
        return self.traverse(
            start_uid, None, max_depth, configuration_uid, evaluation_time
        )

    def build_context(
        self,
        task_type: str,
        target_uids: tuple[str, ...],
        token_budget: int,
        configuration_uid: str = "",
        actor: str = "context-reader",
        evaluation_time: str = "2026-08-05T00:00:00Z",
    ) -> DomainResult:
        del configuration_uid, actor, evaluation_time
        missing = tuple(uid for uid in target_uids if uid not in self.resources)
        if missing:
            return self._error(
                "LESR-CONTEXT-TARGET-MISSING",
                ErrorCategory.INDETERMINATE,
                "one or more context targets are missing",
                missing,
                suggested="resolve",
            )
        mandatory = [self.resources[uid] for uid in target_uids]
        estimated = 10 * len(mandatory)
        completeness = (
            "complete_under_model" if estimated <= token_budget else "incomplete_budget"
        )
        return DomainResult(
            {
                "task_type": task_type,
                "mandatory": mandatory,
                "selection_trace": ["explicit target" for _ in mandatory],
                "completeness": completeness,
                "token_estimate": estimated,
            }
        )

    def open_workspace(self, request: WriteEnvelope) -> DomainResult:
        error = self._validate_write(request, require_workspace=False)
        if error is not None:
            return error
        workspace_uid = request.workspace_uid or f"WS-{uuid7_candidate()}"
        workspace = {
            "workspace_uid": workspace_uid,
            "base": request.expected_base,
            "state": "open",
            "delegation_uid": request.delegation_uid,
            "operations": [],
        }
        if not request.dry_run:
            self.workspaces[workspace_uid] = workspace
        return DomainResult(workspace)

    def propose_operation(self, request: WriteEnvelope) -> DomainResult:
        error = self._validate_write(request, require_workspace=True)
        if error is not None:
            return error
        proposal = {
            "workspace_uid": request.workspace_uid,
            "operation": request.operation,
            "risk_class": request.risk_class,
            "dry_run": request.dry_run,
        }
        if not request.dry_run:
            self.workspaces[request.workspace_uid]["operations"].append(request.operation)
        return DomainResult(proposal)

    def prepare_review(self, request: WriteEnvelope) -> DomainResult:
        error = self._validate_write(request, require_workspace=True)
        if error is not None:
            return error
        return self._error(
            "LESR-ADAPTER-ONLY",
            ErrorCategory.INDETERMINATE,
            "the in-memory adapter cannot produce authoritative validation evidence",
            (request.workspace_uid,),
        )

    def bootstrap_root_owner(
        self,
        trust: dict[str, Any],
        delegation: dict[str, Any],
        approval: dict[str, Any],
        idempotency_key: str,
        governance_operations: tuple[dict[str, Any], ...] = (),
    ) -> DomainResult:
        del trust, delegation, approval, idempotency_key, governance_operations
        return self._error(
            "LESR-ADAPTER-ONLY",
            ErrorCategory.INDETERMINATE,
            "the in-memory adapter cannot bootstrap Canonical State",
        )

    def initialize_configuration(
        self,
        configuration: dict[str, Any],
        approval: dict[str, Any],
        actor_uid: str,
        delegation_uid: str,
        idempotency_key: str,
    ) -> DomainResult:
        del configuration, approval, actor_uid, delegation_uid, idempotency_key
        return self._error(
            "LESR-ADAPTER-ONLY",
            ErrorCategory.INDETERMINATE,
            "the in-memory adapter cannot initialize Canonical governance",
        )

    def apply_transaction(self, request: WriteEnvelope) -> DomainResult:
        error = self._validate_write(request, require_workspace=True)
        if error is not None:
            return error
        previous = self.idempotency.get(request.idempotency_key)
        if previous is not None:
            if previous["operation"] != request.operation:
                return self._error(
                    "LESR-IDEMPOTENCY-CONFLICT",
                    ErrorCategory.CONFLICT,
                    "idempotency key was used for another operation",
                    (request.workspace_uid,),
                )
            return DomainResult({**previous, "idempotent_replay": True})
        if request.expected_base != self.base:
            return self._error(
                "LESR-BASE-CONFLICT",
                ErrorCategory.CONFLICT,
                "expected base is stale",
                (request.expected_base, self.base),
                retryable=True,
                suggested="workspace.rebase",
            )
        required = {"review_package_hash", "approval_uid"}
        if not required <= request.operation.keys():
            return self._error(
                "LESR-APPROVAL-REQUIRED",
                ErrorCategory.AUTHORIZATION,
                "apply requires a review package hash and approval",
                (request.workspace_uid,),
                suggested="workspace.submit",
            )
        result = {
            "workspace_uid": request.workspace_uid,
            "operation": request.operation,
            "result_commit": "commit-2",
            "idempotent_replay": False,
        }
        if not request.dry_run:
            self.base = "commit-2"
            self.idempotency[request.idempotency_key] = result
            self.workspaces[request.workspace_uid]["state"] = "applied"
        return DomainResult(result)

    def start_task(self, task_type: str, request: dict[str, Any]) -> DomainResult:
        task = LongTask(f"TASK-{uuid7_candidate()}", task_type, TaskState.RUNNING, request)
        self.tasks[task.task_uid] = task
        return DomainResult(asdict(task))

    def task_status(self, task_uid: str) -> DomainResult:
        task = self.tasks.get(task_uid)
        return DomainResult(asdict(task)) if task else self._task_missing(task_uid)

    def cancel_task(self, task_uid: str) -> DomainResult:
        task = self.tasks.get(task_uid)
        if task is None:
            return self._task_missing(task_uid)
        cancelled = LongTask(task.task_uid, task.task_type, TaskState.CANCELLED, task.request)
        self.tasks[task_uid] = cancelled
        return DomainResult(asdict(cancelled))

    def task_result(self, task_uid: str) -> DomainResult:
        task = self.tasks.get(task_uid)
        if task is None:
            return self._task_missing(task_uid)
        if task.state is TaskState.RUNNING:
            return self._error(
                "LESR-TASK-NOT-COMPLETE",
                ErrorCategory.CONFLICT,
                "task is still running",
                (task_uid,),
                retryable=True,
                suggested=None,
            )
        return DomainResult(asdict(task))

    def _validate_write(
        self, request: WriteEnvelope, *, require_workspace: bool
    ) -> DomainResult | None:
        if require_workspace and request.workspace_uid not in self.workspaces:
            return self._error(
                "LESR-WORKSPACE-NOT-FOUND",
                ErrorCategory.NOT_FOUND,
                "workspace does not exist",
                (request.workspace_uid,),
                suggested="workspace.open",
            )
        missing = [
            name
            for name, value in (
                ("expected_base", request.expected_base),
                ("idempotency_key", request.idempotency_key),
                ("actor", request.actor),
                ("delegation_uid", request.delegation_uid),
            )
            if not value
        ]
        if missing:
            return self._error(
                "LESR-WRITE-ENVELOPE-INVALID",
                ErrorCategory.VALIDATION,
                "missing write fields: " + ", ".join(missing),
            )
        return None

    def _task_missing(self, task_uid: str) -> DomainResult:
        return self._error(
            "LESR-TASK-NOT-FOUND",
            ErrorCategory.NOT_FOUND,
            "task does not exist",
            (task_uid,),
        )

    @staticmethod
    def _error(
        code: str,
        category: ErrorCategory,
        message: str,
        resources: tuple[str, ...] = (),
        *,
        retryable: bool = False,
        suggested: str | None = None,
    ) -> DomainResult:
        return DomainResult(
            error=DomainErrorContract(
                code,
                category,
                message,
                resources,
                retryable=retryable,
                suggested_capability=suggested,
            )
        )


def _jsonable(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return _jsonable(asdict(value))
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, (datetime, date)):
        return value.isoformat().replace("+00:00", "Z")
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return [_jsonable(item) for item in sorted(value, key=str)]
    return value
