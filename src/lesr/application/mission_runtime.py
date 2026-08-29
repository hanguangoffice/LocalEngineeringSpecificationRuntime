"""Local Mission coordinator for provider-neutral multi-Agent engineering work."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Self

from pydantic import Field, model_validator

from lesr.adapters.mission_store import MissionStore
from lesr.application.agent_broker import (
    AgentAssignment,
    AgentClaim,
    AgentReport,
    apply_agent_report,
    build_agent_assignment,
    validate_agent_claim,
)
from lesr.domain.decision import (
    DecisionPolicy,
    DecisionPolicyFacts,
    DecisionRequest,
    DecisionRequestFactory,
    DecisionRequestNarrative,
    DecisionResolution,
    MandateLimits,
    MandateScope,
    MissionMandate,
)
from lesr.domain.mission import (
    AgentRun,
    AgentRunEngine,
    Mission,
    MissionEngine,
    WorkPackage,
    WorkPackageState,
)
from lesr.domain.semantic import FrozenModel, uuid7_candidate


class MissionPackagePlan(FrozenModel):
    key: str = Field(min_length=1, pattern=r"^[a-z][a-z0-9_.-]*$")
    title: str = Field(min_length=1)
    objective: str = Field(min_length=1)
    role: str = Field(min_length=1)
    depends_on: tuple[str, ...] = ()
    workspace_uid: str | None = None

    @model_validator(mode="after")
    def validate_dependencies(self) -> Self:
        if self.key in self.depends_on:
            raise ValueError("Mission package cannot depend on itself")
        if len(self.depends_on) != len(set(self.depends_on)):
            raise ValueError("Mission package dependencies must be unique")
        return self


class MissionPlan(FrozenModel):
    title: str = Field(min_length=1)
    objective: str = Field(min_length=1)
    initiated_by_actor_uid: str = Field(min_length=1)
    configuration_uid: str | None = None
    engineering_areas: tuple[str, ...] = Field(min_length=1)
    allowed_operations: tuple[str, ...] = Field(min_length=1)
    packages: tuple[MissionPackagePlan, ...] = Field(min_length=1)
    mandate_duration: timedelta = Field(default=timedelta(days=30))
    limits: MandateLimits = Field(default_factory=MandateLimits)

    @model_validator(mode="after")
    def validate_plan(self) -> Self:
        keys = {item.key for item in self.packages}
        if len(keys) != len(self.packages):
            raise ValueError("Mission package keys must be unique")
        missing = {
            dependency
            for package in self.packages
            for dependency in package.depends_on
            if dependency not in keys
        }
        if missing:
            raise ValueError(
                "Mission package dependencies are missing: " + ", ".join(sorted(missing))
            )
        if self.mandate_duration <= timedelta(0):
            raise ValueError("Mission mandate duration must be positive")
        return self


class MissionCoordinator:
    """Persisted Mission DAG, Agent claims, results and human decision routing."""

    def __init__(self, store: MissionStore) -> None:
        self.store = store

    def create(self, plan: MissionPlan, *, created_at: datetime | None = None) -> Mission:
        now = created_at or datetime.now(UTC)
        mission_uid = uuid7_candidate()
        mandate_uid = uuid7_candidate()
        package_uid_by_key = {item.key: uuid7_candidate() for item in plan.packages}
        packages = tuple(
            WorkPackage(
                work_package_uid=package_uid_by_key[item.key],
                mission_uid=mission_uid,
                title=item.title,
                objective=item.objective,
                role=item.role,
                dependency_uids=tuple(
                    package_uid_by_key[dependency] for dependency in item.depends_on
                ),
                workspace_uid=item.workspace_uid,
                created_at=now,
                updated_at=now,
            )
            for item in plan.packages
        )
        mission = Mission(
            mission_uid=mission_uid,
            title=plan.title,
            objective=plan.objective,
            initiated_by_actor_uid=plan.initiated_by_actor_uid,
            configuration_uid=plan.configuration_uid,
            delegation_uid=mandate_uid,
            work_packages=packages,
            created_at=now,
            updated_at=now,
        )
        mission = MissionEngine.reconcile(mission, updated_at=now)
        mandate = MissionMandate(
            mandate_uid=mandate_uid,
            mission_uid=mission_uid,
            title=f"{plan.title} · 执行范围",
            issued_by_actor_uid=plan.initiated_by_actor_uid,
            scope=MandateScope(
                configuration_uid=plan.configuration_uid,
                engineering_areas=plan.engineering_areas,
            ),
            allowed_operations=plan.allowed_operations,
            limits=plan.limits,
            issued_at=now,
            expires_at=now + plan.mandate_duration,
        )
        self.store.put_mission_with_mandate(mission, mandate)
        return mission

    def inspect(self, mission_uid: str) -> Mission:
        return self.store.get_mission(mission_uid)

    def list(self) -> tuple[Mission, ...]:
        return self.store.list_missions()

    def assignments(self, mission_uid: str) -> tuple[AgentAssignment, ...]:
        mission = self.inspect(mission_uid)
        mandate = self._mandate(mission)
        return tuple(
            build_agent_assignment(
                mission,
                uid,
                context_capability="workspace.validate",
                allowed_operations=mandate.allowed_operations,
            )
            for uid in mission.ready_work_package_uids
        )

    def claim(
        self,
        mission_uid: str,
        work_package_uid: str,
        *,
        agent_identity: str,
        provider: str,
        model_identifier: str,
        client: str,
        claimed_at: datetime | None = None,
    ) -> dict[str, object]:
        now = claimed_at or datetime.now(UTC)
        mission = self.inspect(mission_uid)
        if work_package_uid not in mission.ready_work_package_uids:
            raise ValueError("WorkPackage is not READY for assignment")
        mandate = self._mandate(mission)
        assignment = build_agent_assignment(
            mission,
            work_package_uid,
            context_capability="workspace.validate",
            allowed_operations=mandate.allowed_operations,
        )
        run = AgentRun(
            mission_uid=mission_uid,
            work_package_uid=work_package_uid,
            role=assignment.role,
            provider=provider,
            model_identifier=model_identifier,
            client=client,
            created_at=now,
            updated_at=now,
        )
        claim = AgentClaim(
            mission_uid=mission_uid,
            work_package_uid=work_package_uid,
            agent_run_uid=run.agent_run_uid,
            agent_identity=agent_identity,
            claimed_at=now,
        )
        validate_agent_claim(mission, assignment, claim)
        running = AgentRunEngine.start(run, started_at=now)
        updated = MissionEngine.start_package(mission, work_package_uid, updated_at=now)
        updated = self._attach_run(updated, work_package_uid, running.agent_run_uid, now)
        self.store.put_execution_state(
            updated,
            running,
            expected_mission=mission,
        )
        return {"assignment": assignment, "claim": claim, "agent_run": running}

    def report(self, report: AgentReport) -> dict[str, object]:
        mission = self.inspect(report.mission_uid)
        expected_mission = mission
        run = self.store.get_agent_run(report.agent_run_uid)
        mandate = self._mandate(mission)
        assignment = AgentAssignment(
            mission_uid=mission.mission_uid,
            mission_title=mission.title,
            work_package_uid=report.work_package_uid,
            work_package_title=self._package(mission, report.work_package_uid).title,
            objective=self._package(mission, report.work_package_uid).objective,
            role=run.role,
            configuration_uid=mission.configuration_uid,
            workspace_uid=self._package(mission, report.work_package_uid).workspace_uid,
            context_capability="workspace.validate",
            allowed_operations=mandate.allowed_operations,
        )
        claim = AgentClaim(
            mission_uid=mission.mission_uid,
            work_package_uid=report.work_package_uid,
            agent_run_uid=run.agent_run_uid,
            agent_identity=f"{run.provider}:{run.client}",
            claimed_at=run.started_at or run.created_at,
        )
        finished = apply_agent_report(assignment, claim, run, report)
        if finished.state.value == "completed":
            mission = MissionEngine.complete_package(
                mission, report.work_package_uid, updated_at=report.reported_at
            )
        else:
            mission = MissionEngine.fail_package(
                mission,
                report.work_package_uid,
                report.error_summary or "Agent execution failed",
                updated_at=report.reported_at,
            )
        self.store.put_execution_state(
            mission,
            finished,
            expected_mission=expected_mission,
        )
        return {"mission": mission, "agent_run": finished}

    def route_decision(
        self,
        mission_uid: str,
        work_package_uid: str,
        facts: DecisionPolicyFacts,
        narrative: DecisionRequestNarrative | None,
        *,
        evaluated_at: datetime,
    ) -> dict[str, object]:
        mission = self.inspect(mission_uid)
        if facts.work_package_uid != work_package_uid:
            raise ValueError("Decision facts name another WorkPackage")
        mandate = self._mandate(mission)
        policy = DecisionPolicy.decide(mandate, facts, evaluated_at=evaluated_at)
        routed = DecisionRequestFactory.create(
            facts,
            policy,
            narrative,
            created_at=evaluated_at,
        )
        if routed.decision_request is not None:
            waiting = MissionEngine.wait_for_decision(
                mission, work_package_uid, updated_at=evaluated_at
            )
            self.store.put_decision_state(
                waiting,
                routed.decision_request,
                expected_mission=mission,
            )
            mission = waiting
        return {"mission": mission, "policy": policy, "route": routed}

    def resolve_decision(
        self,
        decision_request_uid: str,
        *,
        actor_uid: str,
        reason: str,
        selected_action: str | None = None,
        selected_alternative: str | None = None,
        decided_at: datetime | None = None,
    ) -> dict[str, object]:
        now = decided_at or datetime.now(UTC)
        request = self.store.get_decision_request(decision_request_uid)
        resolution = DecisionResolution.from_request(
            request,
            decided_by_actor_uid=actor_uid,
            reason=reason,
            selected_action=selected_action,
            selected_alternative=selected_alternative,
            decided_at=now,
        )
        mission = self.inspect(request.mission_uid)
        package = self._package(mission, request.work_package_uid)
        if package.state is not WorkPackageState.WAITING_FOR_DECISION:
            raise ValueError("Decision WorkPackage is no longer waiting")
        resumed = MissionEngine.resume_package(
            mission, request.work_package_uid, updated_at=now
        )
        self.store.put_decision_resolution_state(
            resumed,
            resolution,
            expected_mission=mission,
        )
        return {"mission": resumed, "resolution": resolution}

    def decision_inbox(
        self, mission_uid: str | None = None
    ) -> tuple[DecisionRequest, ...]:
        return self.store.list_decision_requests(mission_uid, unresolved_only=True)

    def _mandate(self, mission: Mission) -> MissionMandate:
        if mission.delegation_uid is None:
            raise ValueError("Mission has no active mandate")
        return self.store.get_mandate(mission.delegation_uid)

    @staticmethod
    def _package(mission: Mission, work_package_uid: str) -> WorkPackage:
        match = next(
            (
                item
                for item in mission.work_packages
                if item.work_package_uid == work_package_uid
            ),
            None,
        )
        if match is None:
            raise KeyError(work_package_uid)
        return match

    @staticmethod
    def _attach_run(
        mission: Mission,
        work_package_uid: str,
        agent_run_uid: str,
        updated_at: datetime,
    ) -> Mission:
        packages = tuple(
            item.model_copy(
                update={
                    "agent_run_uids": item.agent_run_uids + (agent_run_uid,),
                    "updated_at": updated_at,
                }
            )
            if item.work_package_uid == work_package_uid
            else item
            for item in mission.work_packages
        )
        return Mission.model_validate(
            mission.model_dump(mode="python")
            | {"work_packages": packages, "updated_at": updated_at}
        )
