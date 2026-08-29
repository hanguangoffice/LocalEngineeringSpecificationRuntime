"""Provider-neutral contracts for assigning Mission work to an Agent.

The broker boundary describes work and receives lifecycle facts.  It does not
select a model provider, invoke an SDK, launch a process, or execute commands.
Assignments, claims, and reports are local runtime messages and are never
Canonical Git resources.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Literal, Protocol, Self

from pydantic import Field, field_validator, model_validator

from lesr.domain.mission import (
    AgentRun,
    AgentRunEngine,
    AgentRunState,
    Mission,
    WorkPackage,
    WorkPackageState,
)
from lesr.domain.semantic import FrozenModel


def _require_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError("timestamp must be UTC")
    return value.astimezone(UTC)


class AgentAssignment(FrozenModel):
    """The provider-independent work description offered to an Agent."""

    schema_version: Literal["1.0"] = "1.0"
    resource_type: Literal["agent_assignment"] = "agent_assignment"
    persistence_scope: Literal["local_runtime"] = "local_runtime"
    canonical_git_eligible: Literal[False] = False
    mission_uid: str = Field(min_length=1)
    mission_title: str = Field(min_length=1)
    work_package_uid: str = Field(min_length=1)
    work_package_title: str = Field(min_length=1)
    objective: str = Field(min_length=1)
    role: str = Field(min_length=1)
    configuration_uid: str | None = None
    workspace_uid: str | None = None
    context_capability: str = Field(min_length=1)
    allowed_operations: tuple[str, ...] = Field(min_length=1)

    @field_validator(
        "mission_uid",
        "mission_title",
        "work_package_uid",
        "work_package_title",
        "objective",
        "role",
        "context_capability",
    )
    @classmethod
    def require_nonblank_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("assignment text values must not be blank")
        return value

    @field_validator("allowed_operations")
    @classmethod
    def validate_operations(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(not operation.strip() for operation in value):
            raise ValueError("allowed operations must not be blank")
        if len(value) != len(set(value)):
            raise ValueError("allowed operations must be unique")
        return value


class AgentClaim(FrozenModel):
    """An Agent's claim on one READY WorkPackage assignment."""

    schema_version: Literal["1.0"] = "1.0"
    resource_type: Literal["agent_claim"] = "agent_claim"
    persistence_scope: Literal["local_runtime"] = "local_runtime"
    canonical_git_eligible: Literal[False] = False
    mission_uid: str = Field(min_length=1)
    work_package_uid: str = Field(min_length=1)
    agent_run_uid: str = Field(min_length=1)
    agent_identity: str = Field(min_length=1)
    claimed_at: datetime

    _utc_claimed = field_validator("claimed_at")(_require_utc)

    @field_validator("mission_uid", "work_package_uid", "agent_run_uid", "agent_identity")
    @classmethod
    def require_nonblank_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("claim values must not be blank")
        return value


class AgentReport(FrozenModel):
    """A terminal outcome reported for one claimed AgentRun."""

    schema_version: Literal["1.0"] = "1.0"
    resource_type: Literal["agent_report"] = "agent_report"
    persistence_scope: Literal["local_runtime"] = "local_runtime"
    canonical_git_eligible: Literal[False] = False
    mission_uid: str = Field(min_length=1)
    work_package_uid: str = Field(min_length=1)
    agent_run_uid: str = Field(min_length=1)
    state: Literal[AgentRunState.COMPLETED, AgentRunState.FAILED]
    result_summary: str | None = None
    error_summary: str | None = None
    reported_at: datetime

    _utc_reported = field_validator("reported_at")(_require_utc)

    @field_validator("mission_uid", "work_package_uid", "agent_run_uid")
    @classmethod
    def require_nonblank_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("report identifiers must not be blank")
        return value

    @model_validator(mode="after")
    def validate_terminal_outcome(self) -> Self:
        if self.state is AgentRunState.COMPLETED:
            if self.result_summary is None or not self.result_summary.strip():
                raise ValueError("completed Agent report requires a result summary")
            if self.error_summary is not None:
                raise ValueError("completed Agent report cannot contain an error summary")
        else:
            if self.error_summary is None or not self.error_summary.strip():
                raise ValueError("failed Agent report requires an error summary")
            if self.result_summary is not None:
                raise ValueError("failed Agent report cannot contain a result summary")
        return self


class AgentBrokerPort(Protocol):
    """Transport boundary implemented by a local or remote Agent broker."""

    def dispatch(self, assignment: AgentAssignment) -> AgentClaim: ...

    def collect_report(self, claim: AgentClaim) -> AgentReport | None: ...


def build_agent_assignment(
    mission: Mission,
    work_package_uid: str,
    *,
    context_capability: str,
    allowed_operations: tuple[str, ...],
) -> AgentAssignment:
    """Build an assignment from the exact READY WorkPackage in ``mission``."""

    package = _package(mission, work_package_uid)
    if package.state is not WorkPackageState.READY:
        raise ValueError("only a READY WorkPackage can be assigned")
    return AgentAssignment(
        mission_uid=mission.mission_uid,
        mission_title=mission.title,
        work_package_uid=package.work_package_uid,
        work_package_title=package.title,
        objective=package.objective,
        role=package.role,
        configuration_uid=mission.configuration_uid,
        workspace_uid=package.workspace_uid,
        context_capability=context_capability,
        allowed_operations=allowed_operations,
    )


def validate_agent_claim(
    mission: Mission,
    assignment: AgentAssignment,
    claim: AgentClaim,
) -> AgentClaim:
    """Accept a claim only while its exact WorkPackage remains READY."""

    package = _package(mission, assignment.work_package_uid)
    if package.state is not WorkPackageState.READY:
        raise ValueError("only a READY WorkPackage can be claimed")
    if assignment.mission_uid != mission.mission_uid:
        raise ValueError("assignment belongs to another Mission")
    if (
        claim.mission_uid != assignment.mission_uid
        or claim.work_package_uid != assignment.work_package_uid
    ):
        raise ValueError("claim does not match its assignment")
    return claim


def apply_agent_report(
    assignment: AgentAssignment,
    claim: AgentClaim,
    run: AgentRun,
    report: AgentReport,
) -> AgentRun:
    """Validate one terminal report and project it onto its running AgentRun."""

    assignment_key = (assignment.mission_uid, assignment.work_package_uid)
    claim_key = (claim.mission_uid, claim.work_package_uid)
    run_key = (run.mission_uid, run.work_package_uid)
    report_key = (report.mission_uid, report.work_package_uid)
    if len({assignment_key, claim_key, run_key, report_key}) != 1:
        raise ValueError("Agent report does not match its Mission and WorkPackage")
    if claim.agent_run_uid != run.agent_run_uid or report.agent_run_uid != run.agent_run_uid:
        raise ValueError("Agent report does not match its AgentRun")
    if run.role != assignment.role:
        raise ValueError("AgentRun role does not match its assignment")
    if report.state is AgentRunState.COMPLETED:
        assert report.result_summary is not None
        return AgentRunEngine.complete(
            run,
            report.result_summary,
            finished_at=report.reported_at,
        )
    assert report.error_summary is not None
    return AgentRunEngine.fail(
        run,
        report.error_summary,
        finished_at=report.reported_at,
    )


def _package(mission: Mission, work_package_uid: str) -> WorkPackage:
    for package in mission.work_packages:
        if package.work_package_uid == work_package_uid:
            return package
    raise KeyError(work_package_uid)
