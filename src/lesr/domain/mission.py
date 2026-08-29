"""Runtime-only Mission orchestration contracts for local multi-agent work.

Mission, WorkPackage and AgentRun are operational coordination state.  They are
stored in the local ``.lesr`` runtime database or recoverable Workspace refs and
MUST NOT be written into the Canonical Git tree.  Only engineering outputs that
cross an existing LESR authority boundary (for example an Applied Change or a
formal decision record) may later become Canonical resources.

The models intentionally contain no content hash.  Runtime identity, database
constraints and the existing Workspace/Git transaction boundaries are enough
for this coordination layer.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Literal, Self

from pydantic import Field, field_validator, model_validator

from lesr.domain.semantic import FrozenModel, uuid7_candidate


def _require_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError("timestamp must be UTC")
    return value.astimezone(UTC)


def _require_optional_utc(value: datetime | None) -> datetime | None:
    return _require_utc(value) if value is not None else None


class MissionState(StrEnum):
    PLANNED = "planned"
    RUNNING = "running"
    WAITING_FOR_DECISION = "waiting_for_decision"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class WorkPackageState(StrEnum):
    PLANNED = "planned"
    READY = "ready"
    RUNNING = "running"
    WAITING_FOR_DECISION = "waiting_for_decision"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class AgentRunState(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"


class WorkPackage(FrozenModel):
    """One node in a Mission DAG; local runtime state, never Canonical Git state."""

    schema_version: Literal["1.0"] = "1.0"
    resource_type: Literal["work_package"] = "work_package"
    persistence_scope: Literal["local_runtime"] = "local_runtime"
    canonical_git_eligible: Literal[False] = False
    work_package_uid: str = Field(default_factory=uuid7_candidate)
    mission_uid: str
    title: str = Field(min_length=1)
    objective: str = Field(min_length=1)
    role: str = Field(min_length=1)
    state: WorkPackageState = WorkPackageState.PLANNED
    dependency_uids: tuple[str, ...] = ()
    blocked_by_uids: tuple[str, ...] = ()
    workspace_uid: str | None = None
    agent_run_uids: tuple[str, ...] = ()
    failure_reason: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    _utc_created = field_validator("created_at")(_require_utc)
    _utc_updated = field_validator("updated_at")(_require_utc)

    @model_validator(mode="after")
    def validate_runtime_state(self) -> Self:
        if self.updated_at < self.created_at:
            raise ValueError("WorkPackage updated_at precedes created_at")
        if self.work_package_uid in self.dependency_uids:
            raise ValueError("WorkPackage cannot depend on itself")
        if len(self.dependency_uids) != len(set(self.dependency_uids)):
            raise ValueError("WorkPackage dependencies must be unique")
        if len(self.agent_run_uids) != len(set(self.agent_run_uids)):
            raise ValueError("WorkPackage Agent Runs must be unique")
        if self.state is WorkPackageState.BLOCKED and not self.blocked_by_uids:
            raise ValueError("blocked WorkPackage requires blocked_by_uids")
        if self.state is not WorkPackageState.BLOCKED and self.blocked_by_uids:
            raise ValueError("only a blocked WorkPackage may have blocked_by_uids")
        if self.state is WorkPackageState.FAILED and not self.failure_reason:
            raise ValueError("failed WorkPackage requires failure_reason")
        if self.state is not WorkPackageState.FAILED and self.failure_reason is not None:
            raise ValueError("only a failed WorkPackage may have failure_reason")
        return self


class Mission(FrozenModel):
    """A local orchestration aggregate; explicitly ineligible for Canonical Git."""

    schema_version: Literal["1.0"] = "1.0"
    resource_type: Literal["mission"] = "mission"
    persistence_scope: Literal["local_runtime"] = "local_runtime"
    canonical_git_eligible: Literal[False] = False
    mission_uid: str = Field(default_factory=uuid7_candidate)
    title: str = Field(min_length=1)
    objective: str = Field(min_length=1)
    initiated_by_actor_uid: str = Field(min_length=1)
    state: MissionState = MissionState.PLANNED
    configuration_uid: str | None = None
    delegation_uid: str | None = None
    work_packages: tuple[WorkPackage, ...] = Field(min_length=1)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    _utc_created = field_validator("created_at")(_require_utc)
    _utc_updated = field_validator("updated_at")(_require_utc)

    @model_validator(mode="after")
    def validate_dag(self) -> Self:
        if self.updated_at < self.created_at:
            raise ValueError("Mission updated_at precedes created_at")
        package_by_uid = {item.work_package_uid: item for item in self.work_packages}
        if len(package_by_uid) != len(self.work_packages):
            raise ValueError("Mission WorkPackage UIDs must be unique")
        for package in self.work_packages:
            if package.mission_uid != self.mission_uid:
                raise ValueError("WorkPackage belongs to another Mission")
            missing = set(package.dependency_uids) - set(package_by_uid)
            if missing:
                raise ValueError(
                    "WorkPackage references unknown dependencies: "
                    + ", ".join(sorted(missing))
                )
        _require_acyclic(package_by_uid)
        states = {item.state for item in self.work_packages}
        if self.state is MissionState.COMPLETED and states != {WorkPackageState.COMPLETED}:
            raise ValueError("completed Mission requires every WorkPackage to be completed")
        if self.state is MissionState.FAILED and not states & {
            WorkPackageState.FAILED,
            WorkPackageState.BLOCKED,
        }:
            raise ValueError("failed Mission requires a failed or blocked WorkPackage")
        if (
            self.state is MissionState.WAITING_FOR_DECISION
            and WorkPackageState.WAITING_FOR_DECISION not in states
        ):
            raise ValueError("waiting Mission requires a WorkPackage awaiting a decision")
        if self.state is MissionState.CANCELLED and WorkPackageState.CANCELLED not in states:
            raise ValueError("cancelled Mission requires a cancelled WorkPackage")
        return self

    @property
    def ready_work_package_uids(self) -> tuple[str, ...]:
        return tuple(
            item.work_package_uid
            for item in self.work_packages
            if item.state is WorkPackageState.READY
        )


class AgentRun(FrozenModel):
    """One provider execution attempt, retained only in local runtime storage."""

    schema_version: Literal["1.0"] = "1.0"
    resource_type: Literal["agent_run"] = "agent_run"
    persistence_scope: Literal["local_runtime"] = "local_runtime"
    canonical_git_eligible: Literal[False] = False
    agent_run_uid: str = Field(default_factory=uuid7_candidate)
    mission_uid: str
    work_package_uid: str
    role: str = Field(min_length=1)
    provider: str = Field(min_length=1)
    model_identifier: str = Field(min_length=1)
    client: str = Field(min_length=1)
    session_id: str | None = None
    attempt: int = Field(default=1, ge=1)
    state: AgentRunState = AgentRunState.QUEUED
    result_summary: str | None = None
    error_summary: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    started_at: datetime | None = None
    finished_at: datetime | None = None

    _utc_created = field_validator("created_at")(_require_utc)
    _utc_updated = field_validator("updated_at")(_require_utc)
    _utc_started = field_validator("started_at")(_require_optional_utc)
    _utc_finished = field_validator("finished_at")(_require_optional_utc)

    @model_validator(mode="after")
    def validate_lifecycle(self) -> Self:
        if self.updated_at < self.created_at:
            raise ValueError("AgentRun updated_at precedes created_at")
        if self.started_at is not None and self.started_at < self.created_at:
            raise ValueError("AgentRun started_at precedes created_at")
        if self.finished_at is not None:
            lower_bound = self.started_at or self.created_at
            if self.finished_at < lower_bound:
                raise ValueError("AgentRun finished_at precedes its start")
        if self.state is AgentRunState.QUEUED:
            if self.started_at is not None or self.finished_at is not None:
                raise ValueError("queued AgentRun cannot have execution timestamps")
        elif self.state is AgentRunState.RUNNING:
            if self.started_at is None or self.finished_at is not None:
                raise ValueError("running AgentRun requires only started_at")
        elif self.state is AgentRunState.COMPLETED:
            if self.started_at is None or self.finished_at is None or not self.result_summary:
                raise ValueError(
                    "completed AgentRun requires timestamps and result_summary"
                )
        elif self.state is AgentRunState.FAILED:
            if self.started_at is None or self.finished_at is None or not self.error_summary:
                raise ValueError("failed AgentRun requires timestamps and error_summary")
        elif self.finished_at is None:
            raise ValueError("cancelled or interrupted AgentRun requires finished_at")
        if self.state is not AgentRunState.COMPLETED and self.result_summary is not None:
            raise ValueError("only a completed AgentRun may have result_summary")
        if self.state is not AgentRunState.FAILED and self.error_summary is not None:
            raise ValueError("only a failed AgentRun may have error_summary")
        return self


class MissionEngine:
    """Pure Mission DAG transitions with branch-local failure propagation."""

    @staticmethod
    def reconcile(mission: Mission, *, updated_at: datetime) -> Mission:
        _require_utc(updated_at)
        packages = {item.work_package_uid: item for item in mission.work_packages}
        changed = True
        while changed:
            changed = False
            for uid, package in tuple(packages.items()):
                if package.state not in {
                    WorkPackageState.PLANNED,
                    WorkPackageState.READY,
                }:
                    continue
                dependencies = tuple(packages[item] for item in package.dependency_uids)
                blockers = tuple(
                    item.work_package_uid
                    for item in dependencies
                    if item.state
                    in {
                        WorkPackageState.FAILED,
                        WorkPackageState.BLOCKED,
                        WorkPackageState.CANCELLED,
                    }
                )
                if blockers:
                    packages[uid] = _replace_package(
                        package,
                        state=WorkPackageState.BLOCKED,
                        updated_at=updated_at,
                        blocked_by_uids=tuple(sorted(blockers)),
                    )
                    changed = True
                elif package.state is WorkPackageState.PLANNED and all(
                    item.state is WorkPackageState.COMPLETED for item in dependencies
                ):
                    packages[uid] = _replace_package(
                        package,
                        state=WorkPackageState.READY,
                        updated_at=updated_at,
                    )
                    changed = True
        ordered = tuple(packages[item.work_package_uid] for item in mission.work_packages)
        state = _mission_state(ordered)
        return Mission.model_validate(
            mission.model_dump(mode="python")
            | {"work_packages": ordered, "state": state, "updated_at": updated_at}
        )

    @staticmethod
    def start_package(
        mission: Mission, work_package_uid: str, *, updated_at: datetime
    ) -> Mission:
        return MissionEngine._transition(
            mission,
            work_package_uid,
            allowed=frozenset({WorkPackageState.READY}),
            target=WorkPackageState.RUNNING,
            updated_at=updated_at,
        )

    @staticmethod
    def complete_package(
        mission: Mission, work_package_uid: str, *, updated_at: datetime
    ) -> Mission:
        return MissionEngine._transition(
            mission,
            work_package_uid,
            allowed=frozenset({WorkPackageState.RUNNING}),
            target=WorkPackageState.COMPLETED,
            updated_at=updated_at,
        )

    @staticmethod
    def fail_package(
        mission: Mission,
        work_package_uid: str,
        reason: str,
        *,
        updated_at: datetime,
    ) -> Mission:
        if not reason.strip():
            raise ValueError("WorkPackage failure requires a reason")
        return MissionEngine._transition(
            mission,
            work_package_uid,
            allowed=frozenset(
                {WorkPackageState.READY, WorkPackageState.RUNNING, WorkPackageState.WAITING_FOR_DECISION}
            ),
            target=WorkPackageState.FAILED,
            updated_at=updated_at,
            failure_reason=reason,
        )

    @staticmethod
    def wait_for_decision(
        mission: Mission, work_package_uid: str, *, updated_at: datetime
    ) -> Mission:
        return MissionEngine._transition(
            mission,
            work_package_uid,
            allowed=frozenset({WorkPackageState.RUNNING}),
            target=WorkPackageState.WAITING_FOR_DECISION,
            updated_at=updated_at,
        )

    @staticmethod
    def resume_package(
        mission: Mission, work_package_uid: str, *, updated_at: datetime
    ) -> Mission:
        return MissionEngine._transition(
            mission,
            work_package_uid,
            allowed=frozenset({WorkPackageState.WAITING_FOR_DECISION}),
            target=WorkPackageState.RUNNING,
            updated_at=updated_at,
        )

    @staticmethod
    def cancel_package(
        mission: Mission, work_package_uid: str, *, updated_at: datetime
    ) -> Mission:
        return MissionEngine._transition(
            mission,
            work_package_uid,
            allowed=frozenset(
                {
                    WorkPackageState.PLANNED,
                    WorkPackageState.READY,
                    WorkPackageState.RUNNING,
                    WorkPackageState.WAITING_FOR_DECISION,
                }
            ),
            target=WorkPackageState.CANCELLED,
            updated_at=updated_at,
        )

    @staticmethod
    def _transition(
        mission: Mission,
        work_package_uid: str,
        *,
        allowed: frozenset[WorkPackageState],
        target: WorkPackageState,
        updated_at: datetime,
        failure_reason: str | None = None,
    ) -> Mission:
        _require_utc(updated_at)
        packages = {item.work_package_uid: item for item in mission.work_packages}
        package = packages.get(work_package_uid)
        if package is None:
            raise KeyError(work_package_uid)
        if package.state not in allowed:
            raise ValueError(
                f"WorkPackage transition {package.state.value} -> {target.value} is invalid"
            )
        packages[work_package_uid] = _replace_package(
            package,
            state=target,
            updated_at=updated_at,
            failure_reason=failure_reason,
        )
        transitioned = Mission.model_validate(
            mission.model_dump(mode="python")
            | {
                "work_packages": tuple(
                    packages[item.work_package_uid] for item in mission.work_packages
                ),
                "state": MissionState.RUNNING,
                "updated_at": updated_at,
            }
        )
        return MissionEngine.reconcile(transitioned, updated_at=updated_at)


class AgentRunEngine:
    """Pure lifecycle transitions for one local Agent execution attempt."""

    @staticmethod
    def start(run: AgentRun, *, started_at: datetime) -> AgentRun:
        if run.state is not AgentRunState.QUEUED:
            raise ValueError("only a queued AgentRun can start")
        return AgentRun.model_validate(
            run.model_dump(mode="python")
            | {
                "state": AgentRunState.RUNNING,
                "started_at": started_at,
                "updated_at": started_at,
            }
        )

    @staticmethod
    def complete(run: AgentRun, result_summary: str, *, finished_at: datetime) -> AgentRun:
        if run.state is not AgentRunState.RUNNING:
            raise ValueError("only a running AgentRun can complete")
        if not result_summary.strip():
            raise ValueError("AgentRun completion requires a result summary")
        return AgentRun.model_validate(
            run.model_dump(mode="python")
            | {
                "state": AgentRunState.COMPLETED,
                "result_summary": result_summary,
                "finished_at": finished_at,
                "updated_at": finished_at,
            }
        )

    @staticmethod
    def fail(run: AgentRun, error_summary: str, *, finished_at: datetime) -> AgentRun:
        if run.state is not AgentRunState.RUNNING:
            raise ValueError("only a running AgentRun can fail")
        if not error_summary.strip():
            raise ValueError("AgentRun failure requires an error summary")
        return AgentRun.model_validate(
            run.model_dump(mode="python")
            | {
                "state": AgentRunState.FAILED,
                "error_summary": error_summary,
                "finished_at": finished_at,
                "updated_at": finished_at,
            }
        )


def _require_acyclic(packages: dict[str, WorkPackage]) -> None:
    remaining = {uid: set(item.dependency_uids) for uid, item in packages.items()}
    while remaining:
        roots = {uid for uid, dependencies in remaining.items() if not dependencies}
        if not roots:
            raise ValueError("Mission WorkPackage dependencies contain a cycle")
        remaining = {
            uid: dependencies - roots
            for uid, dependencies in remaining.items()
            if uid not in roots
        }


def _replace_package(
    package: WorkPackage,
    *,
    state: WorkPackageState,
    updated_at: datetime,
    blocked_by_uids: tuple[str, ...] = (),
    failure_reason: str | None = None,
) -> WorkPackage:
    return WorkPackage.model_validate(
        package.model_dump(mode="python")
        | {
            "state": state,
            "updated_at": updated_at,
            "blocked_by_uids": blocked_by_uids,
            "failure_reason": failure_reason,
        }
    )


def _mission_state(packages: tuple[WorkPackage, ...]) -> MissionState:
    states = {item.state for item in packages}
    if states == {WorkPackageState.COMPLETED}:
        return MissionState.COMPLETED
    if states & {
        WorkPackageState.PLANNED,
        WorkPackageState.READY,
        WorkPackageState.RUNNING,
    }:
        return MissionState.RUNNING
    if WorkPackageState.WAITING_FOR_DECISION in states:
        return MissionState.WAITING_FOR_DECISION
    if states & {WorkPackageState.FAILED, WorkPackageState.BLOCKED}:
        return MissionState.FAILED
    if WorkPackageState.CANCELLED in states:
        return MissionState.CANCELLED
    return MissionState.BLOCKED
