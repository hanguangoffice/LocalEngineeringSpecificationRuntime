"""Integrated LESR 1.0 local runtime application service."""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from functools import partial
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Literal

from jsonschema.exceptions import ValidationError as JsonSchemaValidationError
from pydantic import ValidationError

from lesr.adapters.git import (
    ApprovalAttestation,
    ApprovalError,
    CheckpointStrategy,
    ConcurrencyConflict,
    GitCanonicalRepository,
    IdempotencyConflict,
    IntegrityError,
    OperationType,
    SemanticOperation,
    SemanticTransaction,
)
from lesr.adapters.mission_store import MissionStore
from lesr.adapters.operations import RepositoryMaintenance, TaskStore, TaskWorker
from lesr.adapters.presentation_store import PresentationMappingStore
from lesr.adapters.schemas import SchemaCatalog
from lesr.application.agent_broker import AgentReport
from lesr.application.contracts import (
    CapabilityDescriptor,
    CapabilityGroup,
    DomainErrorContract,
    DomainResult,
    ErrorCategory,
    WorkspaceAssessmentRequest,
    WriteEnvelope,
)
from lesr.application.engineering_view import build_engineering_view
from lesr.application.mission_runtime import MissionCoordinator, MissionPlan
from lesr.domain.approval import (
    SignedApproval,
    TrustedActor,
    verify_approval,
    verify_bound_approval,
)
from lesr.domain.catalog import RUNTIME_CAPABILITIES
from lesr.domain.decision import (
    DecisionDisposition,
    DecisionPolicyFacts,
    DecisionRequestDraft,
    ImpactSummary,
    ValidationConclusion,
    ValidationSummary,
)
from lesr.domain.decision import (
    ImpactCompleteness as DecisionImpactCompleteness,
)
from lesr.domain.evaluation import (
    ConstraintEnvironment,
    ConstraintExpression,
    ContextBundle,
    Direction,
    GraphNode,
    GraphRelation,
    GraphSnapshot,
    Quantity,
    RuleOperator,
    RuntimeValue,
    RuntimeValueKind,
    SemanticEvaluator,
    UnitDefinition,
    UnitRegistry,
    ValidationTarget,
    analyze_impact,
    decode_runtime_value,
    evaluate_constraint,
    evaluate_path,
    plan_context,
)
from lesr.domain.governance import (
    OperationDecision,
    OperationDisposition,
    ValidationFinding,
    ValidationObservation,
    ValidationRun,
)
from lesr.domain.merge import (
    ConflictResolution,
    ForeignDiff,
    RebaseResult,
    SemanticMergeEngine,
    SemanticState,
    begin_reconciliation,
)
from lesr.domain.mission import WorkPackageState
from lesr.domain.model import (
    DefinitionRevision,
    EffectiveModel,
    EffectiveModelCompiler,
    FacetDefinitionRevision,
    FieldDefinition,
    KindDefinitionRevision,
    NormativeProfileRevision,
    RelationTypeRevision,
    TailoringOverlay,
    WorkflowProjector,
    WorkflowRevision,
)
from lesr.domain.presentation import (
    EngineeringArea,
    PresentationMappingRevision,
    PresentationSelector,
    ViewMode,
)
from lesr.domain.review import (
    ApprovalRevocation,
    BaselineManifest,
    BaselinePreparation,
    CommentResolution,
    ConditionSatisfaction,
    GovernanceEvaluator,
    ReviewComment,
    ReviewPackage,
    ReviewPolicy,
    StageQuorum,
    prepare_baseline,
)
from lesr.domain.rules import (
    EnforcementEffect,
    EvaluationEnvironment,
    FieldSymbol,
    RuleCompiler,
    RuleDefinition,
    RuleOutcome,
    ValueCell,
    detect_direct_conflict,
    evaluate_rule,
)
from lesr.domain.semantic import (
    BindingMode,
    ConfigurationSnapshot,
    Fragment,
    ImmutableRecord,
    ProvenanceKind,
    RelationAssertion,
    Revision,
    SemanticField,
    governance_subject_hash,
    semantic_hash,
    uuid7_candidate,
)
from lesr.domain.workspace import (
    CandidateRevisionSet,
    EditOperation,
    SemanticDiff,
    Submission,
    ValidationState,
    WorkingCopy,
    WorkingCopyState,
    Workspace,
    WorkspaceCheckpoint,
    WorkspaceEngine,
    WorkspacePreview,
)


class LocalRuntimeService:
    """The production facade; all adapters delegate here and never to the 0.5 queue."""

    def __init__(self, project: Path) -> None:
        self.project = project.resolve()
        self.repository = GitCanonicalRepository(self.project)
        self.base = self.repository.initialize()
        self.task_store = TaskStore(self.project)
        self.mission_store = MissionStore(self.project)
        self.missions = MissionCoordinator(self.mission_store)
        self.presentation_store = PresentationMappingStore(self.project)
        self.workspaces: dict[str, Workspace] = {}
        self.submissions: dict[str, Any] = {}
        self.reviews: dict[str, ReviewPackage] = {}
        self.review_evidence: dict[str, dict[str, Any]] = {}
        self.review_records: dict[str, list[dict[str, Any]]] = {}
        self.rebase_results: dict[str, dict[str, RebaseResult]] = {}
        self.reconciliation: dict[str, dict[str, Any]] = {}
        self.baseline_preparations: dict[str, BaselinePreparation] = {}
        self._reload()
        self._recover_workspaces()

    def capabilities(self) -> tuple[CapabilityDescriptor, ...]:
        groups: dict[CapabilityGroup, list[str]] = {
            CapabilityGroup.RESOLVE: [],
            CapabilityGroup.INSPECT: [],
            CapabilityGroup.QUERY: [],
            CapabilityGroup.CONTEXT: [],
            CapabilityGroup.WORKSPACE: [],
            CapabilityGroup.GOVERNANCE: [],
            CapabilityGroup.COMPLIANCE: [],
            CapabilityGroup.MISSION: [],
            CapabilityGroup.DECISION: [],
            CapabilityGroup.ENGINEERING: [],
        }
        for capability in RUNTIME_CAPABILITIES:
            prefix = capability.name.split(".", 1)[0]
            group = (
                CapabilityGroup.RESOLVE
                if prefix == "resolve"
                else CapabilityGroup.INSPECT
                if prefix == "inspect"
                else CapabilityGroup.QUERY
                if prefix in {"query", "traverse", "impact"}
                else CapabilityGroup.CONTEXT
                if prefix == "context"
                else CapabilityGroup.WORKSPACE
                if prefix == "workspace"
                else CapabilityGroup.GOVERNANCE
                if prefix in {"review", "apply", "baseline", "reconciliation"}
                else CapabilityGroup.MISSION
                if prefix == "mission"
                else CapabilityGroup.DECISION
                if prefix == "decision"
                else CapabilityGroup.ENGINEERING
                if prefix == "engineering"
                else CapabilityGroup.COMPLIANCE
            )
            groups[group].append(capability.name)
        return tuple(
            CapabilityDescriptor(group, tuple(sorted(names)), "1.0.0")
            for group, names in groups.items()
            if names
        )

    def create_mission(self, plan: dict[str, Any]) -> DomainResult:
        """Create local orchestration state without changing Canonical Git."""

        try:
            mission = self.missions.create(MissionPlan.model_validate(plan))
            return DomainResult(mission.model_dump(mode="json"))
        except (KeyError, TypeError, ValueError, ValidationError) as error:
            return self._error(
                "LESR-MISSION-PLAN-INVALID",
                ErrorCategory.VALIDATION,
                str(error),
            )

    def list_missions(self) -> DomainResult:
        return DomainResult(
            tuple(item.model_dump(mode="json") for item in self.missions.list())
        )

    def inspect_mission(self, mission_uid: str) -> DomainResult:
        try:
            return DomainResult(
                self.missions.inspect(mission_uid).model_dump(mode="json")
            )
        except KeyError:
            return self._error(
                "LESR-MISSION-NOT-FOUND",
                ErrorCategory.NOT_FOUND,
                "mission does not exist",
                (mission_uid,),
                suggested="mission.list",
            )

    def ready_mission_work(self, mission_uid: str) -> DomainResult:
        try:
            return DomainResult(
                tuple(
                    item.model_dump(mode="json")
                    for item in self.missions.assignments(mission_uid)
                )
            )
        except KeyError:
            return self._error(
                "LESR-MISSION-NOT-FOUND",
                ErrorCategory.NOT_FOUND,
                "mission does not exist",
                (mission_uid,),
                suggested="mission.list",
            )

    def claim_mission_work(
        self,
        mission_uid: str,
        work_package_uid: str,
        agent_identity: str,
        provider: str,
        model_identifier: str,
        client: str,
    ) -> DomainResult:
        try:
            claimed = self.missions.claim(
                mission_uid,
                work_package_uid,
                agent_identity=agent_identity,
                provider=provider,
                model_identifier=model_identifier,
                client=client,
            )
            return DomainResult(self._local_runtime_payload(claimed))
        except KeyError as error:
            return self._error(
                "LESR-MISSION-WORK-NOT-FOUND",
                ErrorCategory.NOT_FOUND,
                str(error),
                (mission_uid, work_package_uid),
            )
        except (TypeError, ValueError, ValidationError) as error:
            return self._error(
                "LESR-MISSION-WORK-NOT-READY",
                ErrorCategory.CONFLICT,
                str(error),
                (mission_uid, work_package_uid),
                retryable=True,
                suggested="mission.ready-work",
            )

    def report_mission_work(self, report: dict[str, Any]) -> DomainResult:
        try:
            result = self.missions.report(AgentReport.model_validate(report))
            return DomainResult(self._local_runtime_payload(result))
        except KeyError as error:
            return self._error(
                "LESR-MISSION-RUN-NOT-FOUND",
                ErrorCategory.NOT_FOUND,
                str(error),
            )
        except (TypeError, ValueError, ValidationError) as error:
            return self._error(
                "LESR-MISSION-REPORT-INVALID",
                ErrorCategory.CONFLICT,
                str(error),
            )

    def evaluate_mission_work(
        self,
        mission_uid: str,
        work_package_uid: str,
        workspace_uid: str,
        evaluation_time: str,
        operation: str,
        narrative: dict[str, Any] | None = None,
    ) -> DomainResult:
        """Route real Workspace evidence without accepting a caller risk label."""

        try:
            instant = self._parse_evaluation_time(evaluation_time)
            mission = self.missions.inspect(mission_uid)
            package = next(
                item
                for item in mission.work_packages
                if item.work_package_uid == work_package_uid
            )
            workspace = self.workspaces[workspace_uid]
            if package.state is not WorkPackageState.RUNNING:
                raise ValueError("WorkPackage is not running under an Agent claim")
            if package.workspace_uid is not None and package.workspace_uid != workspace_uid:
                raise ValueError("WorkPackage belongs to another Workspace")
            if (
                mission.configuration_uid is not None
                and workspace.configuration_uid != mission.configuration_uid
            ):
                raise ValueError("Workspace belongs to another Mission configuration")
            if mission.delegation_uid is None:
                raise ValueError("Mission has no active mandate")
            mandate = self.mission_store.get_mandate(mission.delegation_uid)
            area = package.engineering_area
            if area is None:
                if len(mandate.scope.engineering_areas) != 1:
                    raise ValueError("WorkPackage has no unambiguous engineering area")
                area = mandate.scope.engineering_areas[0]
            assessment = self.assess_workspace(
                WorkspaceAssessmentRequest(
                    workspace_uid=workspace_uid,
                    evaluation_time=evaluation_time,
                    maximum_depth=3,
                )
            )
            if not assessment.ok:
                return assessment
            value = assessment.value
            if not isinstance(value, dict):
                raise TypeError("Workspace assessment returned an invalid payload")
            validation_value = value.get("validation", {})
            impact_value = value.get("impact_report", {})
            route_value = value.get("decision", {})
            if not isinstance(validation_value, dict) or not isinstance(impact_value, dict):
                raise TypeError("Workspace assessment evidence is incomplete")
            operation_decision = validation_value.get("operation_decision", {})
            operation_disposition = (
                str(operation_decision.get("disposition", "indeterminate"))
                if isinstance(operation_decision, dict)
                else "indeterminate"
            )
            validation_outcome = str(validation_value.get("outcome", "indeterminate"))
            if validation_outcome == "pass" and operation_disposition not in {
                "block",
                "indeterminate",
            }:
                validation_conclusion = ValidationConclusion.PASSED
            elif validation_outcome == "fail" or operation_disposition == "block":
                validation_conclusion = ValidationConclusion.FAILED
            else:
                validation_conclusion = ValidationConclusion.INDETERMINATE
            findings = validation_value.get("findings", ())
            finding_count = len(findings) if isinstance(findings, (list, tuple)) else 0
            validation_summary = {
                ValidationConclusion.PASSED: "候选内容校验通过",
                ValidationConclusion.FAILED: f"候选内容有 {finding_count} 项需要处理",
                ValidationConclusion.INDETERMINATE: "候选内容尚未形成确定校验结论",
            }[validation_conclusion]
            validation = ValidationSummary(
                conclusion=validation_conclusion,
                summary=validation_summary,
            )
            completeness_text = str(impact_value.get("completeness", ""))
            if completeness_text == "COMPLETE":
                impact_completeness = DecisionImpactCompleteness.COMPLETE
            elif completeness_text.startswith("INCOMPLETE_"):
                impact_completeness = DecisionImpactCompleteness.INCOMPLETE
            else:
                impact_completeness = DecisionImpactCompleteness.INDETERMINATE
            paths = impact_value.get("paths", ())
            path_count = len(paths) if isinstance(paths, (list, tuple)) else 0
            impact = ImpactSummary(
                completeness=impact_completeness,
                summary=(
                    f"已解析 {path_count} 条影响路径"
                    if impact_completeness is DecisionImpactCompleteness.COMPLETE
                    else "影响范围仍有未解析内容"
                ),
                affected_areas=(area,),
                affected_targets=tuple(str(item) for item in value.get("change_scope", ())),
            )
            copies = workspace.working_copies
            human_codes = (
                ("ENGINEERING_POLICY_REQUIRES_HUMAN_DECISION",)
                if isinstance(route_value, dict)
                and route_value.get("disposition")
                == DecisionDisposition.HUMAN_DECISION_NOW.value
                else ()
            )
            milestone_codes = (
                ("WORK_PACKAGE_REVIEW_MILESTONE",)
                if operation == "workspace.submit" and not human_codes
                else ()
            )
            facts = DecisionPolicyFacts(
                mission_uid=mission_uid,
                work_package_uid=work_package_uid,
                operation=operation,
                engineering_area=area,
                target_resource_uids=tuple(str(item) for item in value.get("change_scope", ())),
                new_resource_count=sum(item.base_revision_uid is None for item in copies),
                prospective_work_packages=len(mission.work_packages),
                prospective_changed_resources=len(value.get("change_scope", ())),
                prospective_changed_relations=sum(
                    len(item.relation_proposals) for item in copies
                ),
                validation=validation,
                impact=impact,
                human_decision_policy_codes=human_codes,
                milestone_policy_codes=milestone_codes,
            )
            draft = (
                DecisionRequestDraft.model_validate(narrative)
                if narrative is not None
                else None
            )
            routed = self.missions.route_decision(
                mission_uid,
                work_package_uid,
                facts,
                draft,
                evaluated_at=instant,
            )
            return DomainResult(
                self._local_runtime_payload(routed)
                | {"workspace_assessment": value}
            )
        except StopIteration:
            return self._error(
                "LESR-MISSION-WORK-NOT-FOUND",
                ErrorCategory.NOT_FOUND,
                "work package does not exist",
                (mission_uid, work_package_uid),
            )
        except KeyError as error:
            return self._error(
                "LESR-MISSION-EVALUATION-NOT-FOUND",
                ErrorCategory.NOT_FOUND,
                str(error),
                (mission_uid, work_package_uid, workspace_uid),
            )
        except (TypeError, ValueError, ValidationError) as error:
            return self._error(
                "LESR-MISSION-EVALUATION-INVALID",
                ErrorCategory.CONFLICT,
                str(error),
                (mission_uid, work_package_uid, workspace_uid),
            )

    def list_decisions(self, mission_uid: str | None = None) -> DomainResult:
        return DomainResult(
            tuple(
                item.model_dump(mode="json")
                for item in self.missions.decision_inbox(mission_uid)
            )
        )

    def resolve_decision(
        self,
        decision_request_uid: str,
        actor_uid: str,
        reason: str,
        selected_action: str | None = None,
        selected_alternative: str | None = None,
    ) -> DomainResult:
        try:
            result = self.missions.resolve_decision(
                decision_request_uid,
                actor_uid=actor_uid,
                reason=reason,
                selected_action=selected_action,
                selected_alternative=selected_alternative,
            )
            return DomainResult(self._local_runtime_payload(result))
        except KeyError as error:
            return self._error(
                "LESR-DECISION-NOT-FOUND",
                ErrorCategory.NOT_FOUND,
                str(error),
                (decision_request_uid,),
            )
        except (TypeError, ValueError, ValidationError) as error:
            return self._error(
                "LESR-DECISION-RESOLUTION-INVALID",
                ErrorCategory.CONFLICT,
                str(error),
                (decision_request_uid,),
            )

    def engineering_map(
        self,
        configuration_uid: str,
        evaluation_time: str,
        workspace_uid: str | None = None,
    ) -> DomainResult:
        """Render the resolved engineering structure without technical identifiers."""

        try:
            instant = self._parse_evaluation_time(evaluation_time)
            context: ContextBundle | None = None
            if workspace_uid is None:
                snapshot = self._evaluator(configuration_uid, instant).snapshot
            else:
                workspace = self.workspaces.get(workspace_uid)
                if workspace is None:
                    raise KeyError(workspace_uid)
                if workspace.configuration_uid != configuration_uid:
                    raise ValueError("workspace belongs to another engineering configuration")
                assessment = self.assess_workspace(
                    WorkspaceAssessmentRequest(
                        workspace_uid=workspace_uid,
                        evaluation_time=evaluation_time,
                        maximum_depth=3,
                    )
                )
                if not assessment.ok:
                    return assessment
                snapshot = GraphSnapshot.model_validate(
                    assessment.value["audit"]["graph_snapshot"]
                )
                context = ContextBundle.model_validate(
                    assessment.value["context_bundle"]
                )
            model = self._effective_model(configuration_uid)
            selected_uids = set(model.definition_revision_uids)
            definitions: tuple[DefinitionRevision, ...] = tuple(
                self._definition_revision(value)
                for value in self.documents
                if value.get("revision_uid") in selected_uids
                and value.get("resource_type")
                in {
                    "facet_definition_revision",
                    "kind_definition_revision",
                    "relation_type_revision",
                    "workflow_revision",
                }
            )
            for mapping in reversed(self.presentation_store.list()):
                try:
                    view = build_engineering_view(
                        mapping,
                        model,
                        snapshot,
                        definitions,
                        context_bundle=context,
                    )
                except ValueError:
                    continue
                return DomainResult(view.model_dump(mode="json"))
            fallback = self._fallback_presentation_mapping(model, definitions)
            view = build_engineering_view(
                fallback,
                model,
                snapshot,
                definitions,
                context_bundle=context,
            )
            return DomainResult(view.model_dump(mode="json"))
        except KeyError as error:
            return self._error(
                "LESR-ENGINEERING-MAP-NOT-AVAILABLE",
                ErrorCategory.NOT_FOUND,
                str(error),
                (configuration_uid,),
            )
        except (TypeError, ValueError, ValidationError) as error:
            return self._error(
                "LESR-ENGINEERING-MAP-INDETERMINATE",
                ErrorCategory.INDETERMINATE,
                str(error),
                (configuration_uid,),
            )

    @staticmethod
    def _fallback_presentation_mapping(
        model: EffectiveModel,
        definitions: tuple[DefinitionRevision, ...],
    ) -> PresentationMappingRevision:
        kinds = sorted(
            (item for item in definitions if isinstance(item, KindDefinitionRevision)),
            key=lambda item: item.name,
        )
        if not kinds:
            raise ValueError("effective engineering model defines no content types")
        known_labels = {
            "goal": "目标与边界",
            "functional_requirement": "功能需求",
            "quality_requirement": "质量需求",
            "constraint_requirement": "工程约束",
            "safety_requirement": "安全需求",
            "design": "设计",
            "architecture_decision": "架构决策",
            "test_case": "测试",
            "evidence": "验证证据",
            "api_contract": "接口契约",
            "message_contract": "消息契约",
            "data_asset": "数据资产",
            "model_asset": "模型资产",
            "threat": "威胁模型",
            "deliverable": "交付内容",
            "dependency": "外部依赖",
        }
        return PresentationMappingRevision(
            name="当前工程结构",
            source_profile_revision_uids=model.profile_revision_uids,
            engineering_areas=tuple(
                EngineeringArea(
                    area_key=item.name.replace("_", "-"),
                    label=known_labels.get(item.name, item.name.replace("_", " ")),
                    selector=PresentationSelector(
                        kind_definition_revision_uids=(item.revision_uid,)
                    ),
                    order=index * 10,
                )
                for index, item in enumerate(kinds, 1)
            ),
            view_modes=(ViewMode.OVERVIEW, ViewMode.OUTLINE, ViewMode.DOCUMENT),
            default_view_mode=ViewMode.OVERVIEW,
        )

    @classmethod
    def _local_runtime_payload(cls, value: Any) -> Any:
        if hasattr(value, "model_dump"):
            return value.model_dump(mode="json")
        if isinstance(value, dict):
            return {
                key: cls._local_runtime_payload(item) for key, item in value.items()
            }
        if isinstance(value, (list, tuple)):
            return tuple(cls._local_runtime_payload(item) for item in value)
        return value

    def resolve(self, identifier: str) -> DomainResult:
        matches = [item for item in self.documents if identifier in self._identifiers(item)]
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
            "identifier resolves to multiple exact resources",
            tuple(self._primary_uid(item) for item in matches),
        )

    def inspect(self, uid: str) -> DomainResult:
        matches = [item for item in self.documents if uid in self._identifiers(item)]
        if len(matches) != 1:
            return self._error(
                "LESR-EXACT-RESOURCE-REQUIRED",
                ErrorCategory.INDETERMINATE if matches else ErrorCategory.NOT_FOUND,
                "inspect requires one exact Logical Object, Revision or immutable resource",
                (uid,),
                suggested="resolve",
            )
        return DomainResult(matches[0])

    def review_package(self, package_uid: str) -> DomainResult:
        package = self.reviews.get(package_uid)
        if package is not None:
            return DomainResult(package.model_dump(mode="json"))
        match = next(
            (
                item
                for item in self.documents
                if item.get("resource_type") == "review_package"
                and item.get("package_uid") == package_uid
            ),
            None,
        )
        if match is None:
            return self._error(
                "LESR-REVIEW-PACKAGE-NOT-FOUND",
                ErrorCategory.NOT_FOUND,
                "review package is not available in Workspace or Canonical State",
                (package_uid,),
                suggested="workspace.submit",
            )
        return DomainResult(match)

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
            return self._error("LESR-CURSOR-INVALID", ErrorCategory.VALIDATION, "cursor is invalid")
        try:
            items, total = self.repository.query_projection(
                self.project / ".lesr" / "projection.sqlite3",
                kind=kind,
                text=text,
                offset=offset,
                page_size=page_size,
            )
        except (OSError, RuntimeError, ValueError) as error:
            return self._error(
                "LESR-PROJECTION-QUERY-FAILED",
                ErrorCategory.INDETERMINATE,
                str(error),
                retryable=True,
                suggested="projection.rebuild",
            )
        next_cursor = str(offset + page_size) if offset + page_size < total else None
        return DomainResult({"items": items, "next_cursor": next_cursor, "total": total})

    def traverse(
        self,
        start_uid: str,
        predicate: str | None,
        max_depth: int,
        configuration_uid: str,
        evaluation_time: str,
    ) -> DomainResult:
        try:
            if not 1 <= max_depth <= 16:
                raise ValueError("max_depth must be between 1 and 16")
            evaluator = self._evaluator(
                configuration_uid, self._parse_evaluation_time(evaluation_time)
            )
            frontier = [(start_uid, 0)]
            visited = {start_uid}
            edges: list[dict[str, Any]] = []
            while frontier:
                current, depth = frontier.pop(0)
                if depth >= max_depth:
                    continue
                for direction in (Direction.OUTGOING, Direction.INCOMING):
                    for other, relation in evaluator._adjacent(
                        current, predicate=predicate, direction=direction
                    ):
                        edges.append(
                            {
                                "from": current,
                                "to": other,
                                "direction": direction.value,
                                "relation_revision_uid": (
                                    relation.assertion.relation_revision_uid
                                ),
                                "predicate": relation.assertion.predicate,
                                "depth": depth + 1,
                            }
                        )
                        if other not in visited:
                            visited.add(other)
                            frontier.append((other, depth + 1))
            return DomainResult(
                {
                    "graph_snapshot_hash": evaluator.snapshot.snapshot_hash,
                    "start_uid": start_uid,
                    "visited_uids": sorted(visited),
                    "edges": edges,
                }
            )
        except (KeyError, TypeError, ValueError, PermissionError, ValidationError) as error:
            return self._error(
                "LESR-TRAVERSAL-INDETERMINATE",
                ErrorCategory.INDETERMINATE,
                str(error),
                (start_uid, configuration_uid),
                suggested="resolve",
            )

    def impact(
        self,
        start_uid: str,
        max_depth: int,
        configuration_uid: str,
        evaluation_time: str,
    ) -> DomainResult:
        try:
            configuration = self._configuration(configuration_uid)
            model = self._effective_model(configuration_uid)
            baselines = tuple(
                str(item["baseline_uid"])
                for item in self.documents
                if item.get("resource_type") == "baseline_manifest"
                and (
                    item.get("configuration_uid") == configuration_uid
                    or start_uid in set(item.get("revision_uids", ()))
                )
            )
            evaluator = self._evaluator(
                configuration_uid, self._parse_evaluation_time(evaluation_time)
            )
            report = analyze_impact(
                evaluator,
                (start_uid,),
                maximum_depth=max_depth,
                configuration_complete=configuration.get("closure_status") == "complete",
                profile_conflicts=tuple(item.code for item in model.conflicts),
                affected_rule_uids=model.rule_revision_uids,
                affected_configuration_uids=(configuration_uid,),
                affected_baseline_uids=baselines,
                affected_deviation_uids=tuple(
                    str(item)
                    for item in configuration.get("active_deviation_revision_uids", ())
                ),
            )
            return DomainResult(report.model_dump(mode="json"))
        except (KeyError, TypeError, ValueError, ValidationError) as error:
            return self._error(
                "LESR-IMPACT-INDETERMINATE",
                ErrorCategory.INDETERMINATE,
                str(error),
                (start_uid, configuration_uid),
                suggested="resolve",
            )

    def build_context(
        self,
        task_type: str,
        target_uids: tuple[str, ...],
        token_budget: int,
        configuration_uid: str,
        actor: str,
        evaluation_time: str,
    ) -> DomainResult:
        try:
            model = self._effective_model(configuration_uid)
            policies = [
                item
                for item in model.context_policies
                if item.task_type in {task_type, "*"}
            ]
            exact = [item for item in policies if item.task_type == task_type]
            selected = exact or [item for item in policies if item.task_type == "*"]
            if len(selected) != 1:
                raise ValueError(
                    "Effective Model must define exactly one Context Policy for the task"
                )
            policy = selected[0]
            evaluator = self._evaluator(
                configuration_uid, self._parse_evaluation_time(evaluation_time)
            )
            context = plan_context(
                evaluator,
                tuple(sorted(set(target_uids) | set(policy.invariant_object_uids))),
                policy.mandatory_predicates,
                token_limit=max(1, token_budget // 256),
                conditional_predicates=policy.conditional_predicates,
                mandatory_formal_trace=policy.mandatory_formal_trace,
                forbidden_sensitivities=policy.forbidden_sensitivities,
            )
            self.task_store.put_artifact(
                context.bundle_hash,
                {
                    "context_bundle": context.model_dump(mode="json"),
                    "graph_snapshot": evaluator.snapshot.model_dump(mode="json"),
                    "configuration_uid": configuration_uid,
                    "evaluation_time": evaluator.snapshot.evaluation_time.isoformat(),
                },
            )
            return DomainResult(
                context.model_dump(mode="json")
                | {"task_type": task_type, "requested_by_actor_uid": actor}
            )
        except (KeyError, TypeError, ValueError, ValidationError) as error:
            return self._error(
                "LESR-CONTEXT-INDETERMINATE",
                ErrorCategory.INDETERMINATE,
                str(error),
                target_uids,
                suggested="resolve",
            )

    def read_context(
        self,
        bundle_hash: str,
        resource_uids: tuple[str, ...] = (),
        maximum_resources: int = 100,
        maximum_bytes: int = 2 * 1024 * 1024,
    ) -> DomainResult:
        try:
            if not 1 <= maximum_resources <= 100 or not 1 <= maximum_bytes <= 2 * 1024 * 1024:
                raise ValueError("Focused Read limits exceed the product contract")
            artifact = self.task_store.artifact(bundle_hash)
            bundle = artifact.get("context_bundle")
            snapshot_value = artifact.get("graph_snapshot")
            if not isinstance(bundle, dict) or not isinstance(snapshot_value, dict):
                raise TypeError("Context Manifest artifact is incomplete")
            if bundle.get("bundle_hash") != bundle_hash:
                raise ValueError("Context Manifest hash is invalid")
            snapshot = GraphSnapshot.model_validate(snapshot_value)
            allowed = {str(item) for item in bundle.get("mandatory", ())} | {
                str(item) for item in bundle.get("supporting", ())
            }
            selected = tuple(resource_uids) if resource_uids else tuple(sorted(allowed))
            if not set(selected) <= allowed:
                raise PermissionError("Focused Read requested a resource outside the Manifest")
            by_uid = {item.revision.object_uid: item.revision for item in snapshot.nodes}
            values: list[dict[str, Any]] = []
            omitted: list[str] = []
            used = 0
            for uid in selected:
                revision = by_uid.get(uid)
                if revision is None:
                    omitted.append(uid)
                    continue
                value = revision.model_dump(mode="json")
                size = len(str(value).encode("utf-8"))
                if len(values) >= maximum_resources or used + size > maximum_bytes:
                    omitted.append(uid)
                    continue
                values.append(value)
                used += size
            return DomainResult(
                {
                    "bundle_hash": bundle_hash,
                    "stage": "focused_read",
                    "resources": values,
                    "omitted_candidates": omitted,
                    "completeness": "INCOMPLETE_BUDGET" if omitted else "COMPLETE",
                    "bytes": used,
                }
            )
        except (KeyError, TypeError, ValueError, PermissionError, ValidationError) as error:
            return self._error(
                "LESR-CONTEXT-READ-FAILED",
                ErrorCategory.INDETERMINATE,
                str(error),
                (bundle_hash,),
                suggested="context.plan",
            )

    def start_deep_trace(self, bundle_hash: str, start_uid: str, max_depth: int = 16) -> DomainResult:
        try:
            artifact = self.task_store.artifact(bundle_hash)
            request: dict[str, object] = {
                "start_uid": start_uid,
                "max_depth": max_depth,
                "configuration_uid": str(artifact["configuration_uid"]),
                "evaluation_time": str(artifact["evaluation_time"]),
            }
            return DomainResult(
                self.task_store.enqueue("deep_trace", request).model_dump(mode="json")
            )
        except (KeyError, TypeError, ValueError) as error:
            return self._error(
                "LESR-CONTEXT-TRACE-FAILED",
                ErrorCategory.INDETERMINATE,
                str(error),
                (bundle_hash,),
                suggested="context.plan",
            )

    def open_workspace(self, request: WriteEnvelope) -> DomainResult:
        error = self._validate_write(request, require_workspace=False)
        if error:
            return error
        try:
            configuration_uid = str(request.operation["configuration_uid"])
            configuration = self._configuration(configuration_uid)
            model_hash = str(configuration["effective_model_hash"])
            workspace = Workspace(
                workspace_uid=request.workspace_uid or uuid7_candidate(),
                base_commit=request.expected_base,
                configuration_uid=configuration_uid,
                effective_model_hash=model_hash,
                delegation_uid=request.delegation_uid,
                actor_uid=request.actor,
                created_at=datetime.now(UTC),
            )
            if not request.dry_run:
                self.workspaces[workspace.workspace_uid] = workspace
                self.repository.create_checkpoint(
                    workspace.workspace_uid,
                    self._workspace_state(workspace),
                    CheckpointStrategy.WORKSPACE_REF,
                )
            return DomainResult(workspace.model_dump(mode="json"))
        except (KeyError, TypeError, ValueError, ValidationError) as error:
            return self._error(
                "LESR-WORKSPACE-OPEN-INVALID",
                ErrorCategory.VALIDATION,
                str(error),
                suggested="resolve",
            )

    def propose_operation(self, request: WriteEnvelope) -> DomainResult:
        error = self._validate_write(request, require_workspace=True)
        if error:
            return error
        workspace = self.workspaces[request.workspace_uid]
        try:
            operation_type = str(request.operation.get("operation_type", ""))
            if operation_type == "create_object":
                raw = request.operation.get("working_copy")
                if not isinstance(raw, dict):
                    raise ValueError("create_object requires working_copy")
                working_copy = WorkingCopy.model_validate(
                    raw
                    | {
                        "workspace_uid": workspace.workspace_uid,
                        "effective_model_hash": workspace.effective_model_hash,
                        "delegation_uid": workspace.delegation_uid,
                    }
                )
                updated = WorkspaceEngine.add_working_copy(workspace, working_copy)
            else:
                operation = EditOperation.model_validate(
                    request.operation
                    | {
                        "resource_type": "edit_operation",
                        "object_uid": request.operation.get("object_uid"),
                        "actor_uid": request.actor,
                        "occurred_at": request.operation.get("occurred_at") or datetime.now(UTC),
                    }
                )
                if operation.relation is not None:
                    self._validate_relation_proposal(workspace, operation.relation)
                updated = WorkspaceEngine.edit(workspace, operation)
            if not request.dry_run:
                self.workspaces[request.workspace_uid] = updated
                self.repository.create_checkpoint(
                    request.workspace_uid,
                    self._workspace_state(updated),
                    CheckpointStrategy.WORKSPACE_REF,
                )
            return DomainResult(updated.model_dump(mode="json"))
        except (KeyError, TypeError, ValueError, ValidationError) as error:
            return self._error(
                "LESR-WORKSPACE-EDIT-INVALID",
                ErrorCategory.VALIDATION,
                str(error),
                (request.workspace_uid,),
            )

    def rebase_workspace(self, request: WriteEnvelope) -> DomainResult:
        """Three-way rebase every Working Copy onto an exact Canonical commit."""
        error = self._validate_write(request, require_workspace=True, check_base=False)
        if error:
            return error
        try:
            workspace = self.workspaces[request.workspace_uid]
            new_base = str(request.operation["new_base_commit"])
            self.repository.require_v1_manifest(new_base)
            if not self.repository.is_ancestor(workspace.base_commit, new_base):
                raise ValueError("new base must descend from the Workspace base")
            results: dict[str, RebaseResult] = {}
            updated_copies: list[WorkingCopy] = []
            for copy in workspace.working_copies:
                ours = self._state_from_working_copy(copy)
                base = self._state_at_revision(workspace.base_commit, copy.base_revision_uid) or ours
                theirs_revision = self._latest_revision_for_object(new_base, copy.object_uid)
                theirs = self._state_from_revision(theirs_revision) if theirs_revision else base
                result = SemanticMergeEngine.merge(workspace.workspace_uid, base, ours, theirs)
                results[copy.object_uid] = result
                updated_copies.append(self._copy_from_state(copy, result.merged, theirs_revision))
            updated = workspace.model_copy(
                update={
                    "base_commit": new_base,
                    "working_copies": tuple(updated_copies),
                    "state": WorkingCopyState.EDITABLE,
                }
            )
            payload = {
                "workspace": updated.model_dump(mode="json"),
                "results": {
                    uid: value.model_dump(mode="json") for uid, value in results.items()
                },
                "approvals_invalidated": True,
                "review_package_invalidated": True,
            }
            if not request.dry_run:
                self.workspaces[request.workspace_uid] = updated
                self.rebase_results[request.workspace_uid] = results
                self._invalidate_review(request.workspace_uid)
                self._checkpoint_workspace(updated)
            return DomainResult(payload)
        except (KeyError, TypeError, ValueError, ValidationError, IntegrityError) as error:
            return self._error(
                "LESR-WORKSPACE-REBASE-FAILED",
                ErrorCategory.CONFLICT,
                str(error),
                (request.workspace_uid,),
                retryable=True,
            )

    def resolve_merge_conflict(self, request: WriteEnvelope) -> DomainResult:
        error = self._validate_write(request, require_workspace=True, check_base=False)
        if error:
            return error
        try:
            resolution = ConflictResolution.model_validate(request.operation["resolution"])
            by_object = dict(self.rebase_results[request.workspace_uid])
            object_uid = next(
                uid
                for uid, result in by_object.items()
                if any(item.conflict_uid == resolution.conflict_uid for item in result.conflicts)
            )
            resolved = SemanticMergeEngine.resolve(by_object[object_uid], (resolution,))
            by_object[object_uid] = resolved
            workspace = self.workspaces[request.workspace_uid]
            copies = tuple(
                self._copy_from_state(item, resolved.merged, None)
                if item.object_uid == object_uid
                else item
                for item in workspace.working_copies
            )
            updated = workspace.model_copy(
                update={"working_copies": copies, "state": WorkingCopyState.EDITABLE}
            )
            if not request.dry_run:
                self.rebase_results[request.workspace_uid] = by_object
                self.workspaces[request.workspace_uid] = updated
                self._checkpoint_workspace(updated)
            return DomainResult(
                {
                    "resolution": resolution.model_dump(mode="json"),
                    "remaining_conflicts": sum(len(item.conflicts) for item in by_object.values()),
                    "workspace": updated.model_dump(mode="json"),
                }
            )
        except (KeyError, StopIteration, TypeError, ValueError, ValidationError) as error:
            return self._error(
                "LESR-MERGE-CONFLICT-RESOLUTION-FAILED",
                ErrorCategory.CONFLICT,
                str(error),
                (request.workspace_uid,),
            )

    def merge_workspace(self, request: WriteEnvelope) -> DomainResult:
        """Merge another Workspace through the same semantic three-way engine."""
        error = self._validate_write(request, require_workspace=True, check_base=False)
        if error:
            return error
        try:
            source_uid = str(request.operation["source_workspace_uid"])
            source = self.workspaces[source_uid]
            target = self.workspaces[request.workspace_uid]
            if (
                source.configuration_uid != target.configuration_uid
                or source.effective_model_hash != target.effective_model_hash
            ):
                raise ValueError("Workspace Merge requires the same Configuration and model")
            source_by_uid = {item.object_uid: item for item in source.working_copies}
            target_by_uid = {item.object_uid: item for item in target.working_copies}
            merged = list(target.working_copies)
            results: dict[str, RebaseResult] = {}
            for object_uid, theirs_copy in source_by_uid.items():
                ours_copy = target_by_uid.get(object_uid)
                if ours_copy is None:
                    merged.append(
                        WorkingCopy.model_validate(
                            theirs_copy.model_dump(mode="json")
                            | {
                                "workspace_uid": target.workspace_uid,
                                "delegation_uid": target.delegation_uid,
                                "working_state_hash": "",
                            }
                        )
                    )
                    continue
                base = self._state_at_revision(target.base_commit, ours_copy.base_revision_uid)
                base = base or self._state_from_working_copy(ours_copy)
                result = SemanticMergeEngine.merge(
                    target.workspace_uid,
                    base,
                    self._state_from_working_copy(ours_copy),
                    self._state_from_working_copy(theirs_copy),
                )
                results[object_uid] = result
                merged = [
                    self._copy_from_state(item, result.merged, None)
                    if item.object_uid == object_uid
                    else item
                    for item in merged
                ]
            updated = target.model_copy(
                update={
                    "working_copies": tuple(merged),
                    "state": WorkingCopyState.EDITABLE,
                }
            )
            if not request.dry_run:
                self.workspaces[target.workspace_uid] = updated
                self.rebase_results[target.workspace_uid] = results
                self._invalidate_review(target.workspace_uid)
                self._checkpoint_workspace(updated)
            return DomainResult(
                {
                    "workspace": updated.model_dump(mode="json"),
                    "source_workspace_uid": source_uid,
                    "results": {uid: item.model_dump(mode="json") for uid, item in results.items()},
                    "approvals_invalidated": True,
                }
            )
        except (KeyError, TypeError, ValueError, ValidationError) as error:
            return self._error(
                "LESR-WORKSPACE-MERGE-FAILED",
                ErrorCategory.CONFLICT,
                str(error),
                (request.workspace_uid,),
            )

    def begin_reconciliation(self, request: WriteEnvelope) -> DomainResult:
        """Represent a foreign Canonical diff as a non-authoritative Workspace."""
        error = self._validate_write(request, require_workspace=False, check_base=False)
        if error:
            return error
        try:
            diff = ForeignDiff.model_validate(request.operation["foreign_diff"])
            if not self.repository.requires_reconciliation(diff.changed_paths):
                raise ValueError("foreign diff does not touch Canonical State")
            reconciliation = begin_reconciliation(diff)
            value = reconciliation.model_dump(mode="json") | {
                "foreign_diff": diff.model_dump(mode="json")
            }
            if not request.dry_run:
                self.reconciliation[reconciliation.workspace_uid] = value
                self.repository.create_checkpoint(
                    reconciliation.workspace_uid,
                    {"runtime_state_version": "1.0", "reconciliation": value},
                    CheckpointStrategy.WORKSPACE_REF,
                )
            return DomainResult(value)
        except (KeyError, TypeError, ValueError, ValidationError) as error:
            return self._error(
                "LESR-RECONCILIATION-FAILED",
                ErrorCategory.CONFLICT,
                str(error),
            )

    def assess_workspace(self, request: WorkspaceAssessmentRequest) -> DomainResult:
        """Evaluate an editable Working Copy without freezing or checkpointing it."""

        workspace = self.workspaces.get(request.workspace_uid)
        if workspace is None:
            return self._error(
                "LESR-WORKSPACE-NOT-FOUND",
                ErrorCategory.NOT_FOUND,
                "workspace does not exist",
                (request.workspace_uid,),
                suggested="workspace.open",
            )
        if not 1 <= request.maximum_depth <= 16:
            return self._error(
                "LESR-WORKSPACE-ASSESSMENT-INVALID",
                ErrorCategory.VALIDATION,
                "maximum_depth must be between 1 and 16",
                (request.workspace_uid,),
            )
        try:
            evaluation_time = self._parse_evaluation_time(request.evaluation_time)
            canonical_evaluator = self._evaluator(
                workspace.configuration_uid, evaluation_time
            )
            self._validate_requested_transitions(
                workspace, canonical_evaluator, workspace.actor_uid
            )
            lifecycle_states = self._workspace_lifecycle_states(
                workspace, canonical_evaluator
            )
            preview = WorkspaceEngine.preview(
                workspace,
                actor_uid=workspace.actor_uid,
                previewed_at=evaluation_time,
                base_revisions=self._canonical_revisions(),
                lifecycle_states=lifecycle_states,
            )
            transient = self._submission_from_preview(preview)
            evaluator = self._evaluator(
                workspace.configuration_uid,
                evaluation_time,
                submission=transient,
            )
            context = self._candidate_context(transient, evaluator)
            impact = analyze_impact(
                evaluator,
                preview.scope,
                maximum_depth=request.maximum_depth,
            )
            validation = self._validate_submission(transient, evaluator)
            decision = self._assessment_decision(validation, impact.completeness.value)
            return DomainResult(
                {
                    "workspace_uid": workspace.workspace_uid,
                    "workspace_state": workspace.state.value,
                    "candidate_frozen": False,
                    "evaluation_time": evaluation_time.isoformat().replace("+00:00", "Z"),
                    "change_scope": preview.scope,
                    "changes": tuple(
                        item.model_dump(mode="json") for item in preview.changes
                    ),
                    "context_bundle": context.model_dump(mode="json"),
                    "impact_report": impact.model_dump(mode="json"),
                    "validation": validation,
                    "decision": decision,
                    "audit": {
                        "graph_snapshot": evaluator.snapshot.model_dump(mode="json"),
                        "working_state": tuple(
                            {
                                "human_key": item.human_key,
                                "working_state_hash": item.working_state_hash,
                            }
                            for item in workspace.working_copies
                        ),
                    },
                }
            )
        except (KeyError, TypeError, ValueError, PermissionError, ValidationError) as error:
            return self._error(
                "LESR-WORKSPACE-ASSESSMENT-FAILED",
                ErrorCategory.INDETERMINATE,
                str(error),
                (request.workspace_uid,),
            )

    def prepare_review(self, request: WriteEnvelope) -> DomainResult:
        error = self._validate_write(request, require_workspace=True)
        if error:
            return error
        try:
            evaluation_time = self._evaluation_time(request.operation)
            workspace = self.workspaces[request.workspace_uid]
            canonical_evaluator = self._evaluator(
                workspace.configuration_uid, evaluation_time
            )
            self._validate_requested_transitions(
                workspace, canonical_evaluator, request.actor
            )
            lifecycle_states = self._workspace_lifecycle_states(
                workspace, canonical_evaluator
            )
            submission = WorkspaceEngine.submit(
                workspace,
                checkpoint_uid=uuid7_candidate(),
                actor_uid=request.actor,
                submitted_at=evaluation_time,
                base_revisions=self._canonical_revisions(),
                lifecycle_states=lifecycle_states,
            )
            evaluator = self._evaluator(
                submission.workspace.configuration_uid,
                evaluation_time,
                submission=submission,
            )
            context = self._candidate_context(submission, evaluator)
            self.task_store.put_artifact(
                context.bundle_hash,
                {
                    "context_bundle": context.model_dump(mode="json"),
                    "graph_snapshot": evaluator.snapshot.model_dump(mode="json"),
                    "configuration_uid": submission.workspace.configuration_uid,
                    "evaluation_time": evaluator.snapshot.evaluation_time.isoformat(),
                },
            )
            impact = analyze_impact(
                evaluator,
                tuple(item.object_uid for item in submission.candidate.revisions),
                maximum_depth=int(request.operation.get("maximum_depth", 3)),
            )
            validation = self._validate_submission(submission, evaluator)
            result_configuration = self._next_configuration(
                submission, evaluation_time=evaluation_time
            )
            policy = self._review_policy(
                submission.workspace.configuration_uid, "apply_transaction"
            )
            package = ReviewPackage(
                workspace_uid=request.workspace_uid,
                base_commit=submission.workspace.base_commit,
                configuration_uid=submission.workspace.configuration_uid,
                result_configuration_uid=result_configuration.configuration_uid,
                result_configuration_hash=result_configuration.configuration_hash,
                candidate_hash=submission.candidate.candidate_hash,
                candidate_scope=tuple(item.object_uid for item in submission.candidate.revisions),
                semantic_diff_hash=submission.semantic_diff.diff_hash,
                graph_snapshot_hash=evaluator.snapshot.snapshot_hash,
                context_bundle_hash=context.bundle_hash,
                impact_report_hash=impact.report_hash,
                validation_hash=str(validation["validation_hash"]),
                finding_hashes=tuple(str(item) for item in validation["finding_hashes"]),
                governance_finding_uids=tuple(
                    str(item)
                    for item in validation["operation_decision"]["governance_finding_uids"]
                ),
                review_policy=policy,
                effective_model_hash=submission.workspace.effective_model_hash,
                prepared_by_actor_uid=request.actor,
                created_at=evaluation_time,
            )
            if not request.dry_run:
                self.workspaces[request.workspace_uid] = submission.workspace
                self.submissions[request.workspace_uid] = submission
                self.reviews[package.package_uid] = package
                self.review_evidence[package.package_uid] = {
                    "semantic_diff": submission.semantic_diff.model_dump(mode="json"),
                    "graph_snapshot": evaluator.snapshot.model_dump(mode="json"),
                    "context_bundle": context.model_dump(mode="json"),
                    "impact_report": impact.model_dump(mode="json"),
                    "validation": validation,
                    "result_configuration": result_configuration.model_dump(mode="json"),
                }
                self.repository.create_checkpoint(
                    request.workspace_uid,
                    self._workspace_state(
                        submission.workspace,
                        submission=submission,
                        review_package=package,
                        evidence=self.review_evidence[package.package_uid],
                    ),
                    CheckpointStrategy.WORKSPACE_REF,
                )
            return DomainResult(
                {
                    "workspace": submission.workspace.model_dump(mode="json"),
                    "candidate": submission.candidate.model_dump(mode="json"),
                    "semantic_diff": submission.semantic_diff.model_dump(mode="json"),
                    "graph_snapshot": evaluator.snapshot.model_dump(mode="json"),
                    "context_bundle": context.model_dump(mode="json"),
                    "impact_report": impact.model_dump(mode="json"),
                    "validation": validation,
                    "review_package": package.model_dump(mode="json"),
                    "result_configuration": result_configuration.model_dump(mode="json"),
                }
            )
        except (KeyError, TypeError, ValueError, PermissionError, ValidationError) as error:
            return self._error(
                "LESR-REVIEW-PREPARATION-FAILED",
                ErrorCategory.INDETERMINATE,
                str(error),
                (request.workspace_uid,),
            )

    def apply_transaction(self, request: WriteEnvelope) -> DomainResult:
        error = self._validate_write(request, require_workspace=True, check_base=False)
        if error:
            return error
        try:
            package_uid = str(request.operation["review_package_uid"])
            package = self.reviews[package_uid]
            submission = self.submissions[request.workspace_uid]
            approvals = tuple(
                SignedApproval.model_validate(item)
                for item in self._records(request.operation, "signed_approvals")
            )
            trust = tuple(
                TrustedActor.model_validate(item)
                for item in self.documents
                if item.get("resource_type") == "trusted_actor"
            )
            workspace_records = self.review_records.get(request.workspace_uid, [])
            comments = tuple(
                ReviewComment.model_validate(item)
                for item in [*self.documents, *workspace_records]
                if item.get("resource_type") == "review_comment"
            )
            resolutions = tuple(
                CommentResolution.model_validate(item)
                for item in [*self.documents, *workspace_records]
                if item.get("resource_type") == "comment_resolution"
            )
            satisfactions = tuple(
                ConditionSatisfaction.model_validate(item)
                for item in [
                    *workspace_records,
                    *self._records(request.operation, "condition_satisfactions"),
                ]
                if item.get("resource_type") == "condition_satisfaction"
            )
            revocations = tuple(
                ApprovalRevocation.model_validate(item)
                for item in [*self.documents, *workspace_records]
                if item.get("resource_type") == "approval_revocation"
            )
            decision = GovernanceEvaluator.evaluate(
                package,
                approvals,
                trust,
                comments,
                resolutions,
                satisfactions,
                revocations,
                now=self._evaluation_time(request.operation),
                findings=tuple(
                    ValidationFinding.model_validate(item)
                    for item in self.review_evidence[package_uid]["validation"]["findings"]
                ),
            )

            if not decision.allowed:
                return self._error(
                    "LESR-GOVERNANCE-NOT-SATISFIED",
                    ErrorCategory.AUTHORIZATION,
                    "; ".join(decision.reasons),
                    (package_uid,),
                )
            if request.dry_run:
                return DomainResult(
                    {"dry_run": True, "governance": decision.model_dump(mode="json")}
                )
            result = self.repository.apply_candidate(
                base_commit=request.expected_base,
                candidate=submission.candidate,
                review_package=package,
                result_configuration=self.review_evidence[package_uid][
                    "result_configuration"
                ],
                approvals=approvals,
                trust=trust,
                comments=comments,
                resolutions=resolutions,
                satisfactions=satisfactions,
                revocations=revocations,
                evidence=self.review_evidence.get(package_uid, {}),
                evaluation_time=self._evaluation_time(request.operation),
                actor_uid=request.actor,
                delegation_uid=request.delegation_uid,
                idempotency_key=request.idempotency_key,
                validation_recalculator=lambda: str(
                    self._validate_submission(
                        submission,
                        self._evaluator_from_review_evidence(package_uid),
                        validation_run_uid=str(
                            self.review_evidence[package_uid]["validation"][
                                "validation_run"
                            ]["validation_run_uid"]
                        ),
                        completed_at=self._parse_evaluation_time(
                            str(
                                self.review_evidence[package_uid]["validation"][
                                    "validation_run"
                                ]["completed_at"]
                            )
                        ),
                    )["validation_hash"]
                ),
                projection_updater=self._rebuild_projection,
            )
            self.base = self.repository.current_commit()
            self._reload()
            return DomainResult(
                {
                    "result_commit": result.commit,
                    "transaction_hash": result.transaction_hash,
                    "idempotent_replay": result.idempotent_replay,
                    "projection_stale": result.projection_stale,
                    "configuration_uid": result.configuration_uid,
                    "governance": decision.model_dump(mode="json"),
                }
            )
        except (
            ApprovalError,
            ConcurrencyConflict,
            IdempotencyConflict,
            IntegrityError,
            KeyError,
            TypeError,
            ValueError,
            ValidationError,
        ) as error:
            return self._error(
                "LESR-APPLY-FAILED",
                ErrorCategory.CONFLICT,
                str(error),
                (request.workspace_uid,),
                retryable=isinstance(error, ConcurrencyConflict),
            )

    def add_review_comment(self, request: WriteEnvelope) -> DomainResult:
        error = self._validate_write(request, require_workspace=True, check_base=False)
        if error:
            return error
        try:
            package_uid = str(request.operation["package_uid"])
            package = self.reviews[package_uid]
            comment = ReviewComment.model_validate(
                dict(request.operation["comment"]) | {"package_hash": package.package_hash}
            )
            if not request.dry_run:
                self.review_records.setdefault(request.workspace_uid, []).append(
                    comment.model_dump(mode="json")
                )
                self._checkpoint_workspace(
                    self.workspaces[request.workspace_uid],
                    review_package=package,
                )
            return DomainResult(
                {
                    "comment": comment.model_dump(mode="json"),
                    "review_package": package.model_dump(mode="json"),
                    "approvals_invalidated": False,
                }
            )
        except (KeyError, TypeError, ValueError, ValidationError) as error:
            return self._error(
                "LESR-REVIEW-COMMENT-FAILED",
                ErrorCategory.VALIDATION,
                str(error),
                (request.workspace_uid,),
            )

    def resolve_review_comment(self, request: WriteEnvelope) -> DomainResult:
        return self._append_review_record(request, CommentResolution, "comment_resolution")

    def satisfy_review_condition(self, request: WriteEnvelope) -> DomainResult:
        return self._append_review_record(
            request, ConditionSatisfaction, "condition_satisfaction"
        )

    def revoke_approval(self, request: WriteEnvelope) -> DomainResult:
        return self._append_review_record(request, ApprovalRevocation, "approval_revocation")

    def prepare_baseline(self, request: WriteEnvelope) -> DomainResult:
        error = self._validate_write(request, require_workspace=False)
        if error:
            return error
        try:
            evaluation_time = self._evaluation_time(request.operation)
            configuration_uid = str(request.operation["configuration_uid"])
            configuration = self._configuration(configuration_uid)
            if configuration.get("closure_status") != "complete":
                raise ValueError("Baseline requires a complete Configuration")
            evaluator = self._evaluator(configuration_uid, evaluation_time)
            revisions = tuple(item.revision for item in evaluator.snapshot.nodes)
            candidate = CandidateRevisionSet(
                workspace_uid=request.workspace_uid,
                checkpoint_uid=uuid7_candidate(),
                effective_model_hash=str(configuration["effective_model_hash"]),
                revisions=revisions,
                relation_revisions=tuple(
                    item.assertion for item in evaluator.snapshot.relations
                ),
                lifecycle_records=(),
            )
            workspace = Workspace(
                workspace_uid=request.workspace_uid,
                base_commit=request.expected_base,
                configuration_uid=configuration_uid,
                effective_model_hash=str(configuration["effective_model_hash"]),
                delegation_uid=request.delegation_uid,
                actor_uid=request.actor,
                created_at=evaluation_time,
            )
            submission = SimpleNamespace(workspace=workspace, candidate=candidate)
            validation = self._validate_submission(submission, evaluator)
            impact = analyze_impact(
                evaluator,
                tuple(item.object_uid for item in revisions),
                maximum_depth=16,
                configuration_complete=True,
                affected_configuration_uids=(configuration_uid,),
                affected_deviation_uids=tuple(
                    str(item)
                    for item in configuration.get("active_deviation_revision_uids", ())
                ),
            )
            model = self._effective_model(configuration_uid)
            baseline_context = [
                item for item in model.context_policies if item.task_type in {"baseline", "*"}
            ]
            exact_context = [item for item in baseline_context if item.task_type == "baseline"]
            selected_context = exact_context or [
                item for item in baseline_context if item.task_type == "*"
            ]
            if len(selected_context) != 1:
                raise ValueError(
                    "Effective Model must define exactly one baseline Context Policy"
                )
            context = plan_context(
                evaluator,
                tuple(item.object_uid for item in revisions),
                selected_context[0].mandatory_predicates,
                token_limit=max(1, len(revisions) + len(evaluator.snapshot.relations)),
                conditional_predicates=selected_context[0].conditional_predicates,
                mandatory_formal_trace=selected_context[0].mandatory_formal_trace,
                forbidden_sensitivities=selected_context[0].forbidden_sensitivities,
            )
            semantic_diff = {
                "schema_version": "1.0",
                "resource_type": "semantic_diff",
                "base_commit": request.expected_base,
                "candidate_uid": candidate.candidate_uid,
                "changes": [],
                "scope": [configuration_uid],
            }
            semantic_diff["diff_hash"] = semantic_hash(semantic_diff)
            policy = self._review_policy(configuration_uid, "baseline.apply")
            package = ReviewPackage(
                workspace_uid=request.workspace_uid,
                base_commit=request.expected_base,
                configuration_uid=configuration_uid,
                result_configuration_uid=configuration_uid,
                result_configuration_hash=ConfigurationSnapshot.model_validate(
                    configuration
                ).configuration_hash,
                candidate_hash=candidate.candidate_hash,
                candidate_scope=(configuration_uid,),
                semantic_diff_hash=str(semantic_diff["diff_hash"]),
                graph_snapshot_hash=evaluator.snapshot.snapshot_hash,
                context_bundle_hash=context.bundle_hash,
                impact_report_hash=impact.report_hash,
                validation_hash=str(validation["validation_hash"]),
                finding_hashes=tuple(str(item) for item in validation["finding_hashes"]),
                governance_finding_uids=tuple(
                    str(item)
                    for item in validation["operation_decision"]["governance_finding_uids"]
                ),
                review_policy=policy,
                effective_model_hash=str(configuration["effective_model_hash"]),
                prepared_by_actor_uid=request.actor,
                created_at=evaluation_time,
            )
            preparation = prepare_baseline(
                configuration_uid=configuration_uid,
                state_commit=request.expected_base,
                graph_snapshot_hash=evaluator.snapshot.snapshot_hash,
                validation_run_hash=str(validation["validation_hash"]),
                impact_report_hash=impact.report_hash,
                review_package_hash=package.package_hash,
                configuration_complete=True,
                validation_passed=validation["outcome"] == "pass",
                impact_complete=impact.completeness.value == "COMPLETE",
            )
            evidence = {
                "semantic_diff": semantic_diff,
                "graph_snapshot": evaluator.snapshot.model_dump(mode="json"),
                "context_bundle": context.model_dump(mode="json"),
                "impact_report": impact.model_dump(mode="json"),
                "validation": validation,
                "result_configuration": ConfigurationSnapshot.model_validate(
                    configuration
                ).model_dump(mode="json"),
            }
            if not request.dry_run:
                self.reviews[package.package_uid] = package
                self.review_evidence[package.package_uid] = evidence
                self.baseline_preparations[package.package_uid] = preparation
                self.repository.create_checkpoint(
                    request.workspace_uid,
                    {
                        "runtime_state_version": "1.0",
                        "review_package": package.model_dump(mode="json"),
                        "review_evidence": evidence,
                        "baseline_preparation": preparation.model_dump(mode="json"),
                    },
                    CheckpointStrategy.WORKSPACE_REF,
                )
            return DomainResult(
                {
                    "baseline_preparation": preparation.model_dump(mode="json"),
                    "review_package": package.model_dump(mode="json"),
                    "validation": validation,
                    "impact_report": impact.model_dump(mode="json"),
                }
            )
        except (KeyError, TypeError, ValueError, PermissionError, ValidationError) as error:
            return self._error(
                "LESR-BASELINE-PREPARATION-FAILED",
                ErrorCategory.INDETERMINATE,
                str(error),
                (request.workspace_uid,),
            )

    def apply_baseline(self, request: WriteEnvelope) -> DomainResult:
        error = self._validate_write(request, require_workspace=False)
        if error:
            return error
        try:
            package_uid = str(request.operation["review_package_uid"])
            package = self.reviews[package_uid]
            preparation = self.baseline_preparations[package_uid]
            evidence = self.review_evidence[package_uid]
            approvals = tuple(
                SignedApproval.model_validate(item)
                for item in self._records(request.operation, "signed_approvals")
            )
            trust = tuple(
                TrustedActor.model_validate(item)
                for item in self.documents
                if item.get("resource_type") == "trusted_actor"
            )
            decision = GovernanceEvaluator.evaluate(
                package,
                approvals,
                trust,
                (),
                (),
                (),
                (),
                now=self._evaluation_time(request.operation),
                findings=tuple(
                    ValidationFinding.model_validate(item)
                    for item in evidence["validation"]["findings"]
                ),
            )
            if not decision.allowed:
                raise ApprovalError("; ".join(decision.reasons))
            self.repository._verify_review_evidence(package, evidence)
            configuration = self._configuration(preparation.configuration_uid)
            manifest = BaselineManifest(
                state_commit=preparation.state_commit,
                configuration_uid=preparation.configuration_uid,
                exact_revision_uids=tuple(configuration.get("revision_uids", ())),
                exact_relation_revision_uids=tuple(
                    configuration.get("relation_revision_uids", ())
                ),
                effective_model_hash=package.effective_model_hash,
                deviation_revision_uids=tuple(
                    configuration.get("active_deviation_revision_uids", ())
                ),
                review_package_hash=package.package_hash,
                created_at=self._evaluation_time(request.operation),
            ).model_dump(mode="json")
            operations = [
                SemanticOperation(
                    OperationType.CREATE_BASELINE,
                    f"canonical/baselines/{manifest['baseline_uid']}.json",
                    manifest,
                ),
                SemanticOperation(
                    OperationType.RECORD_BASELINE_PREPARATION,
                    f"canonical/baseline_preparations/{preparation.preparation_uid}.json",
                    preparation.model_dump(mode="json"),
                ),
                SemanticOperation(
                    OperationType.RECORD_REVIEW_PACKAGE,
                    f"canonical/review_packages/{package.package_uid}.json",
                    package.model_dump(mode="json"),
                ),
            ]
            operations.extend(
                SemanticOperation(
                    OperationType.RECORD_APPROVAL,
                    f"canonical/approvals/{item.approval_uid}.json",
                    item.model_dump(mode="json"),
                )
                for item in approvals
            )
            operations.extend(
                SemanticOperation(
                    OperationType.RECORD_PROVENANCE,
                    f"canonical/provenance/{item.provenance_uid}.json",
                    self._approval_provenance(item),
                )
                for item in approvals
            )
            recorded_provenance = {
                str(item.payload.get("provenance_uid"))
                for item in operations
                if item.payload.get("resource_type") == "provenance_record"
            }
            if any(item.provenance_uid not in recorded_provenance for item in approvals):
                raise IntegrityError("baseline approval provenance was not assembled")
            transaction = SemanticTransaction(
                transaction_uid=uuid7_candidate(),
                base_commit=request.expected_base,
                expected_revisions=(),
                effective_model_hash=package.effective_model_hash,
                review_package_hash=package.package_hash,
                operations=tuple(operations),
                approvals=tuple(
                    ApprovalAttestation(
                        item.approval_uid,
                        item.package_hash,
                        item.actor_uid,
                        item.actor_type,
                        item.approval_type,
                    )
                    for item in approvals
                ),
                actor=request.actor,
                delegation_uid=request.delegation_uid,
                idempotency_key=request.idempotency_key,
            )
            if request.dry_run:
                return DomainResult({"dry_run": True, "baseline_manifest": manifest})
            result = self.repository.apply(
                transaction,
                projection_updater=self._rebuild_projection,
                governance_validator=lambda: self._validate_baseline_boundary(
                    package, preparation, evidence
                ),
            )
            tag_name = request.operation.get("tag_name")
            tag_status = "not_requested"
            if isinstance(tag_name, str) and tag_name:
                try:
                    self.repository._git(
                        "tag", "-a", tag_name, result.commit, "-m", f"LESR Baseline {tag_name}"
                    )
                    tag_status = "created"
                except RuntimeError:
                    tag_status = "pending_rebuild"
            self.base = result.commit
            self._reload()
            return DomainResult(
                {
                    "result_commit": result.commit,
                    "baseline_uid": manifest["baseline_uid"],
                    "manifest_hash": manifest["manifest_hash"],
                    "tag_status": tag_status,
                }
            )
        except (
            ApprovalError,
            ConcurrencyConflict,
            IntegrityError,
            KeyError,
            TypeError,
            ValueError,
            ValidationError,
        ) as error:
            return self._error(
                "LESR-BASELINE-APPLY-FAILED",
                ErrorCategory.CONFLICT,
                str(error),
                (request.workspace_uid,),
                retryable=isinstance(error, ConcurrencyConflict),
            )

    def _validate_baseline_boundary(
        self,
        package: ReviewPackage,
        preparation: BaselinePreparation,
        evidence: dict[str, Any],
    ) -> None:
        """Recompute immutable baseline inputs at the Git authority boundary."""

        self.repository._verify_review_evidence(package, evidence)
        if preparation.state_commit != self.repository.current_commit():
            raise ConcurrencyConflict("baseline preparation no longer pins canonical HEAD")
        configuration = self._configuration(preparation.configuration_uid)
        if configuration.get("closure_status") != "complete":
            raise ApprovalError("baseline Configuration is no longer complete")
        if str(configuration.get("effective_model_hash")) != package.effective_model_hash:
            raise ApprovalError("baseline Effective Model changed after review")
        evaluator = self._evaluator_from_review_evidence(package.package_uid)
        candidate = CandidateRevisionSet(
            workspace_uid=package.workspace_uid,
            checkpoint_uid=uuid7_candidate(),
            effective_model_hash=package.effective_model_hash,
            revisions=tuple(item.revision for item in evaluator.snapshot.nodes),
            relation_revisions=tuple(
                item.assertion for item in evaluator.snapshot.relations
            ),
            lifecycle_records=(),
        )

        workspace = Workspace(
            workspace_uid=package.workspace_uid,
            base_commit=package.base_commit,
            configuration_uid=package.configuration_uid,
            effective_model_hash=package.effective_model_hash,
            delegation_uid="boundary-revalidation",
            actor_uid=package.prepared_by_actor_uid,
            created_at=package.created_at,
        )
        recorded = evidence["validation"]
        recalculated = self._validate_submission(
            SimpleNamespace(workspace=workspace, candidate=candidate),
            evaluator,
            validation_run_uid=str(recorded["validation_run"]["validation_run_uid"]),
            completed_at=self._parse_evaluation_time(
                str(recorded["validation_run"]["completed_at"])
            ),
        )
        if (
            recalculated["snapshot_hash"] != recorded.get("snapshot_hash")
            or recalculated["outcome"] != recorded.get("outcome")
            or recalculated["finding_hashes"]
            != tuple(recorded.get("finding_hashes", ()))
        ):
            raise ApprovalError("baseline Validation changed at transaction boundary")

    def rebuild_baseline_tag(self, baseline_uid: str, tag_name: str) -> DomainResult:
        """Rebuild publication metadata at the Baseline Manifest creation commit."""
        try:
            safe_uid = baseline_uid.replace("/", "").replace("\\", "")
            if safe_uid != baseline_uid or not tag_name or tag_name.startswith("-"):
                raise ValueError("baseline UID or tag name is invalid")
            path = f"canonical/baselines/{baseline_uid}.json"
            manifest = self.repository.read_json(self.base, path)
            if manifest is None:
                raise KeyError(baseline_uid)
            commits = self.repository._git(
                "log",
                self.base,
                "--diff-filter=A",
                "--format=%H",
                "--reverse",
                "--",
                path,
            ).splitlines()
            if len(commits) != 1:
                raise IntegrityError("Baseline Manifest creation commit is ambiguous")
            existing = self.repository._try_git(
                "rev-parse", "--verify", f"refs/tags/{tag_name}"
            )
            if existing:
                tagged_commit = self.repository._git("rev-list", "-n", "1", tag_name)
                if tagged_commit != commits[0]:
                    raise IntegrityError("existing tag points to another commit")
                return DomainResult(
                    {"tag_name": tag_name, "tag_status": "created", "idempotent": True}
                )
            self.repository._git(
                "tag", "-a", tag_name, commits[0], "-m", f"LESR Baseline {tag_name}"
            )
            return DomainResult(
                {
                    "baseline_uid": baseline_uid,
                    "manifest_commit": commits[0],
                    "tag_name": tag_name,
                    "tag_status": "created",
                    "idempotent": False,
                }
            )
        except (KeyError, TypeError, ValueError, RuntimeError, IntegrityError) as error:
            return self._error(
                "LESR-BASELINE-TAG-REBUILD-FAILED",
                ErrorCategory.CONFLICT,
                str(error),
                (baseline_uid,),
            )

    def start_task(self, task_type: str, request: dict[str, Any]) -> DomainResult:
        try:
            return DomainResult(self.task_store.enqueue(task_type, request).model_dump(mode="json"))
        except ValidationError as error:
            return self._error("LESR-TASK-TYPE-INVALID", ErrorCategory.VALIDATION, str(error))

    def task_status(self, task_uid: str) -> DomainResult:
        try:
            return DomainResult(self.task_store.get(task_uid).model_dump(mode="json"))
        except KeyError:
            return self._error(
                "LESR-TASK-NOT-FOUND", ErrorCategory.NOT_FOUND, "task not found", (task_uid,)
            )

    def cancel_task(self, task_uid: str) -> DomainResult:
        try:
            return DomainResult(self.task_store.request_cancel(task_uid).model_dump(mode="json"))
        except KeyError:
            return self._error(
                "LESR-TASK-NOT-FOUND", ErrorCategory.NOT_FOUND, "task not found", (task_uid,)
            )

    def task_result(self, task_uid: str) -> DomainResult:
        try:
            result = self.task_store.result(task_uid)
            if result is None:
                return self._error(
                    "LESR-TASK-RESULT-NOT-READY",
                    ErrorCategory.CONFLICT,
                    "task result is not available",
                    (task_uid,),
                    retryable=True,
                )
            return DomainResult(result)
        except KeyError:
            return self._error(
                "LESR-TASK-NOT-FOUND", ErrorCategory.NOT_FOUND, "task not found", (task_uid,)
            )

    def run_next_task(self) -> DomainResult:
        worker = TaskWorker(
            self.task_store,
            {
                "full_validation": self._run_full_validation,
                "deep_trace": self._run_deep_trace,
                "large_impact": self._run_large_impact,
                "migration": self._run_migration,
                "backup": self._run_backup,
            },
        )
        task = worker.run_next()
        return DomainResult(task.model_dump(mode="json") if task is not None else {"idle": True})

    def _run_full_validation(
        self,
        request: dict[str, object],
        progress: Any,
        cancelled: Any,
    ) -> dict[str, object]:
        progress(10, {"phase": "graph_snapshot"})
        if cancelled():
            return {"cancelled": True}
        configuration_uid = str(request["configuration_uid"])
        evaluation_time = self._parse_evaluation_time(str(request["evaluation_time"]))
        evaluator = self._evaluator(configuration_uid, evaluation_time)
        configuration = self._configuration(configuration_uid)
        candidate = CandidateRevisionSet(
            workspace_uid=str(request.get("workspace_uid", uuid7_candidate())),
            checkpoint_uid=uuid7_candidate(),
            effective_model_hash=str(configuration["effective_model_hash"]),
            revisions=tuple(item.revision for item in evaluator.snapshot.nodes),
            relation_revisions=tuple(item.assertion for item in evaluator.snapshot.relations),
            lifecycle_records=(),
        )
        workspace = Workspace(
            workspace_uid=candidate.workspace_uid,
            base_commit=self.base,
            configuration_uid=configuration_uid,
            effective_model_hash=candidate.effective_model_hash,
            delegation_uid="persistent-full-validation",
            actor_uid=str(request.get("actor_uid", "system")),
            created_at=evaluation_time,
        )
        progress(60, {"phase": "rule_evaluation"})
        if cancelled():
            return {"cancelled": True}
        result = self._validate_submission(
            SimpleNamespace(workspace=workspace, candidate=candidate), evaluator
        )
        progress(100, {"phase": "complete"})
        return result

    def _run_migration(
        self,
        request: dict[str, object],
        progress: Any,
        cancelled: Any,
    ) -> dict[str, object]:
        progress(10, {"phase": "plan"})
        if cancelled():
            return {"cancelled": True}
        report = RepositoryMaintenance(self.project).migration_plan(
            str(request["target_version"]),
            dry_run=bool(request.get("dry_run", True)),
        )
        progress(100, {"phase": "complete"})
        return report

    def _run_backup(
        self,
        request: dict[str, object],
        progress: Any,
        cancelled: Any,
    ) -> dict[str, object]:
        progress(10, {"phase": "bundle"})
        if cancelled():
            return {"cancelled": True}
        result = RepositoryMaintenance(self.project).backup(Path(str(request["destination"])))
        progress(100, {"phase": "complete"})
        return {
            "bundle": str(result.bundle),
            "manifest": str(result.manifest),
            "bundle_sha256": result.bundle_sha256,
        }

    def _run_deep_trace(
        self,
        request: dict[str, object],
        progress: Any,
        cancelled: Any,
    ) -> dict[str, object]:
        progress(10, {"phase": "snapshot"})
        if cancelled():
            return {"cancelled": True}
        result = self.traverse(
            str(request["start_uid"]),
            str(request["predicate"]) if request.get("predicate") is not None else None,
            int(str(request.get("max_depth", 16))),
            str(request["configuration_uid"]),
            str(request["evaluation_time"]),
        ).payload()
        progress(100, {"phase": "complete"})
        return result

    def _run_large_impact(
        self,
        request: dict[str, object],
        progress: Any,
        cancelled: Any,
    ) -> dict[str, object]:
        progress(10, {"phase": "snapshot"})
        if cancelled():
            return {"cancelled": True}
        result = self.impact(
            str(request["start_uid"]),
            int(str(request.get("max_depth", 16))),
            str(request["configuration_uid"]),
            str(request["evaluation_time"]),
        ).payload()
        progress(100, {"phase": "complete"})
        return result

    @staticmethod
    def bootstrap_binding(
        base_commit: str,
        trust: dict[str, Any],
        delegation: dict[str, Any],
        governance_operations: tuple[dict[str, Any], ...] = (),
    ) -> tuple[str, str, dict[str, Any]]:
        resources = [item.get("resource", {}) for item in governance_operations]
        profiles = tuple(
            NormativeProfileRevision.model_validate(item)
            for item in resources
            if isinstance(item, dict)
            and item.get("resource_type") == "normative_profile_revision"
        )
        rules = tuple(
            RuleDefinition.model_validate(item)
            for item in resources
            if isinstance(item, dict)
            and item.get("resource_type") == "rule_definition_revision"
        )
        definitions = tuple(
            LocalRuntimeService._definition_revision(item)
            for item in resources
            if isinstance(item, dict)
            and item.get("resource_type")
            in {
                "facet_definition_revision",
                "kind_definition_revision",
                "relation_type_revision",
                "workflow_revision",
            }
        )
        if len(resources) != len(profiles) + len(rules) + len(definitions):
            raise ValueError(
                "bootstrap governance may contain only Normative Profile, Definition and Rule revisions"
            )
        if not profiles:
            raise ValueError("bootstrap requires at least one Normative Profile revision")
        model_hash = EffectiveModelCompiler().compile(profiles, definitions).model_hash
        scope = {
            "base_commit": base_commit,
            "actor_uid": trust.get("actor_uid"),
            "key_uid": trust.get("key_uid"),
            "delegation_uid": delegation.get("delegation_uid"),
            "governance_operation_hashes": [
                semantic_hash(
                    {
                        "operation_type": item.get("operation_type"),
                        "resource": item.get("resource"),
                    }
                )
                for item in governance_operations
            ],
        }
        return semantic_hash({"bootstrap": scope}), model_hash, scope

    def bootstrap_root_owner(
        self,
        trust: dict[str, Any],
        delegation: dict[str, Any],
        approval: dict[str, Any],
        idempotency_key: str,
        governance_operations: tuple[dict[str, Any], ...] = (),
    ) -> DomainResult:
        if any(item.get("resource_type") == "trusted_actor" for item in self.documents):
            return self._error(
                "LESR-BOOTSTRAP-ALREADY-COMPLETE",
                ErrorCategory.CONFLICT,
                "Canonical State already has a trusted root actor",
            )
        try:
            schemas = SchemaCatalog()
            schemas.validate("trusted-actor.schema.json", trust)
            schemas.validate("delegation-grant.schema.json", delegation)
            schemas.validate("approval-attestation.schema.json", approval)
            trusted = TrustedActor.model_validate(trust)
            signed = SignedApproval.model_validate(approval)
            package_hash, model_hash, scope = self.bootstrap_binding(
                self.base, trust, delegation, governance_operations
            )
            if signed.scope != scope:
                raise PermissionError("bootstrap approval scope is invalid")
            verify_approval(
                signed,
                trusted,
                package_hash=package_hash,
                effective_model_hash=model_hash,
            )
            if (
                delegation["base_commit"] != self.base
                or delegation["issued_by"] != trusted.actor_uid
                or delegation["principal_uid"] != trusted.actor_uid
                or signed.actor_uid != trusted.actor_uid
            ):
                raise PermissionError("bootstrap trust and delegation identities differ")
            governance: list[SemanticOperation] = []
            for item in governance_operations:
                resource = item.get("resource")
                if not isinstance(resource, dict):
                    raise TypeError("governance operation resource is invalid")
                resource_type = resource.get("resource_type")
                if resource_type == "normative_profile_revision":
                    operation_type = OperationType.UPDATE_PROFILE_BINDING
                    uid = resource["profile_revision_uid"]
                    path = f"canonical/profiles/{uid}.json"
                elif resource_type == "rule_definition_revision":
                    operation_type = OperationType.CREATE_RULE
                    uid = resource["rule_revision_uid"]
                    path = f"canonical/rules/{uid}.json"
                elif resource_type in {
                    "facet_definition_revision",
                    "kind_definition_revision",
                    "relation_type_revision",
                    "workflow_revision",
                }:
                    operation_type = OperationType.CREATE_RECORD
                    uid = resource["revision_uid"]
                    path = f"canonical/definitions/{uid}.json"
                else:
                    raise ValueError("unsupported bootstrap governance resource")
                governance.append(SemanticOperation(operation_type, path, resource))
            transaction = SemanticTransaction(
                transaction_uid=uuid7_candidate(),
                base_commit=self.base,
                expected_revisions=(),
                effective_model_hash=model_hash,
                review_package_hash=package_hash,
                operations=(
                    SemanticOperation(
                        OperationType.REGISTER_TRUSTED_ACTOR,
                        f"canonical/trust/{trusted.actor_uid}/{trusted.key_uid}.json",
                        trust,
                    ),
                    SemanticOperation(
                        OperationType.CREATE_DELEGATION,
                        f"canonical/delegations/{delegation['delegation_uid']}.json",
                        delegation,
                    ),
                    SemanticOperation(
                        OperationType.RECORD_APPROVAL,
                        f"canonical/approvals/{signed.approval_uid}.json",
                        approval,
                    ),
                    SemanticOperation(
                        OperationType.RECORD_PROVENANCE,
                        f"canonical/provenance/{signed.provenance_uid}.json",
                        self._approval_provenance(signed),
                    ),
                    *governance,
                ),
                approvals=(
                    ApprovalAttestation(
                        signed.approval_uid,
                        package_hash,
                        signed.actor_uid,
                        signed.actor_type,
                        signed.approval_type,
                    ),
                ),
                actor=trusted.actor_uid,
                delegation_uid=str(delegation["delegation_uid"]),
                idempotency_key=idempotency_key,
            )
            result = self.repository.apply(transaction, projection_updater=self._rebuild_projection)
            self.base = result.commit
            self._reload()
            return DomainResult(
                {
                    "result_commit": result.commit,
                    "actor_uid": trusted.actor_uid,
                    "delegation_uid": delegation["delegation_uid"],
                }
            )
        except (
            JsonSchemaValidationError,
            KeyError,
            TypeError,
            ValueError,
            PermissionError,
            RuntimeError,
        ) as error:
            return self._error(
                "LESR-BOOTSTRAP-INVALID",
                ErrorCategory.AUTHORIZATION,
                str(error),
            )

    @staticmethod
    def configuration_binding(
        base_commit: str,
        configuration: dict[str, Any],
        supporting_approvals: tuple[dict[str, Any], ...] = (),
    ) -> tuple[str, str, dict[str, Any]]:
        scope = {
            "base_commit": base_commit,
            "configuration_uid": configuration.get("configuration_uid"),
            "configuration_hash": semantic_hash(configuration),
            "supporting_approval_hashes": sorted(
                semantic_hash(item) for item in supporting_approvals
            ),
        }
        return (
            semantic_hash({"configuration": scope}),
            str(configuration.get("effective_model_hash")),
            scope,
        )

    @staticmethod
    def initial_configuration_binding(
        base_commit: str, configuration: dict[str, Any]
    ) -> tuple[str, str, dict[str, Any]]:
        return LocalRuntimeService.configuration_binding(base_commit, configuration)

    def initialize_configuration(
        self,
        configuration: dict[str, Any],
        approval: dict[str, Any],
        actor_uid: str,
        delegation_uid: str,
        idempotency_key: str,
    ) -> DomainResult:
        if any(item.get("resource_type") == "configuration_snapshot" for item in self.documents):
            return self._error(
                "LESR-CONFIGURATION-ALREADY-INITIALIZED",
                ErrorCategory.CONFLICT,
                "initial configuration already exists",
            )
        return self._create_configuration(
            configuration,
            approval,
            actor_uid,
            delegation_uid,
            idempotency_key,
            (),
        )

    def create_configuration(
        self,
        configuration: dict[str, Any],
        approval: dict[str, Any],
        actor_uid: str,
        delegation_uid: str,
        idempotency_key: str,
        supporting_approvals: tuple[dict[str, Any], ...] = (),
    ) -> DomainResult:
        return self._create_configuration(
            configuration,
            approval,
            actor_uid,
            delegation_uid,
            idempotency_key,
            supporting_approvals,
        )

    def plan_configuration(self, configuration: dict[str, Any]) -> DomainResult:
        """Resolve a successor Configuration without mutating Canonical State."""

        try:
            value = dict(configuration)
            value["base_commit"] = self.base
            value["state_anchor"] = ""
            value["configuration_hash"] = ""
            model = self._compile_effective_model_from_configuration_value(value)
            value["effective_model_hash"] = model.model_hash
            planned = ConfigurationSnapshot.model_validate(value)
            return DomainResult(planned.model_dump(mode="json"))
        except (KeyError, TypeError, ValueError, ValidationError) as error:
            return self._error(
                "LESR-CONFIGURATION-PLAN-INVALID",
                ErrorCategory.VALIDATION,
                str(error),
            )

    def record_governance_approval(
        self,
        approval: dict[str, Any],
        actor_uid: str,
        delegation_uid: str,
        idempotency_key: str,
    ) -> DomainResult:
        """Persist a human-signed governance approval before selecting it in a Configuration."""

        try:
            SchemaCatalog().validate("approval-attestation.schema.json", approval)
            signed = SignedApproval.model_validate(approval)
            if signed.approval_type not in {
                "deviation",
                "exception",
                "rule_conflict_resolution",
            }:
                raise PermissionError(
                    f"unsupported standalone approval type: {signed.approval_type}"
                )
            if actor_uid != signed.actor_uid:
                raise PermissionError("approval can only be recorded by its human signer")
            trust_value = next(
                (
                    item
                    for item in self.documents
                    if item.get("resource_type") == "trusted_actor"
                    and item.get("actor_uid") == signed.actor_uid
                    and item.get("key_uid") == signed.key_uid
                ),
                None,
            )
            if trust_value is None:
                raise PermissionError("approval trust is unavailable")
            verify_approval(
                signed,
                TrustedActor.model_validate(trust_value),
                package_hash=signed.package_hash,
                effective_model_hash=signed.effective_model_hash,
            )
            transaction = SemanticTransaction(
                transaction_uid=uuid7_candidate(),
                base_commit=self.base,
                expected_revisions=(),
                effective_model_hash=signed.effective_model_hash,
                review_package_hash=signed.package_hash,
                operations=(
                    SemanticOperation(
                        OperationType.RECORD_APPROVAL,
                        f"canonical/approvals/{signed.approval_uid}.json",
                        signed.model_dump(mode="json"),
                    ),
                    SemanticOperation(
                        OperationType.RECORD_PROVENANCE,
                        f"canonical/provenance/{signed.provenance_uid}.json",
                        self._approval_provenance(signed),
                    ),
                ),
                approvals=(
                    ApprovalAttestation(
                        signed.approval_uid,
                        signed.package_hash,
                        signed.actor_uid,
                        signed.actor_type,
                        signed.approval_type,
                    ),
                ),
                actor=actor_uid,
                delegation_uid=delegation_uid,
                idempotency_key=idempotency_key,
            )
            result = self.repository.apply(
                transaction, projection_updater=self._rebuild_projection
            )
            self.base = result.commit
            self._reload()
            return DomainResult(
                {
                    "result_commit": result.commit,
                    "approval_uid": signed.approval_uid,
                }
            )
        except (
            JsonSchemaValidationError,
            KeyError,
            TypeError,
            ValueError,
            PermissionError,
            RuntimeError,
        ) as error:
            return self._error(
                "LESR-GOVERNANCE-APPROVAL-RECORD-INVALID",
                ErrorCategory.AUTHORIZATION,
                str(error),
            )

    def _create_configuration(
        self,
        configuration: dict[str, Any],
        approval: dict[str, Any],
        actor_uid: str,
        delegation_uid: str,
        idempotency_key: str,
        supporting_approvals: tuple[dict[str, Any], ...],
    ) -> DomainResult:
        try:
            schemas = SchemaCatalog()
            schemas.validate("configuration.schema.json", configuration)
            schemas.validate("approval-attestation.schema.json", approval)
            for supporting_value in supporting_approvals:
                schemas.validate("approval-attestation.schema.json", supporting_value)
            if configuration["base_commit"] != self.base:
                raise ValueError("configuration must pin the exact Canonical base")
            existing = tuple(
                item
                for item in self.documents
                if item.get("resource_type") == "configuration_snapshot"
            )
            if any(
                item.get("configuration_uid") == configuration.get("configuration_uid")
                for item in existing
            ):
                raise ValueError("configuration UID already exists")
            parent_uid = configuration.get("parent_configuration_uid")
            if existing and not any(
                item.get("configuration_uid") == parent_uid for item in existing
            ):
                raise ValueError(
                    "subsequent configuration must reference an existing parent configuration"
                )
            model = self._effective_model_from_configuration_value(configuration)
            if model.model_hash != configuration["effective_model_hash"]:
                raise ValueError("configuration Effective Model is unavailable or stale")
            signed = SignedApproval.model_validate(approval)
            supporting_signed = tuple(
                SignedApproval.model_validate(item) for item in supporting_approvals
            )
            if len({item.approval_uid for item in supporting_signed}) != len(
                supporting_signed
            ):
                raise ValueError("supporting approval UIDs must be unique")
            package_hash, model_hash, scope = self.configuration_binding(
                self.base, configuration, supporting_approvals
            )
            trust_values = {
                (str(item.get("actor_uid")), str(item.get("key_uid"))): item
                for item in self.documents
                if item.get("resource_type") == "trusted_actor"
            }
            trust_value = trust_values.get((signed.actor_uid, signed.key_uid))
            if trust_value is None or signed.scope != scope:
                raise PermissionError("configuration approval scope is invalid")
            verify_approval(
                signed,
                TrustedActor.model_validate(trust_value),
                package_hash=package_hash,
                effective_model_hash=model_hash,
            )
            allowed_supporting_types = {
                "deviation",
                "exception",
                "rule_conflict_resolution",
            }
            for item in supporting_signed:
                if item.approval_type not in allowed_supporting_types:
                    raise PermissionError(
                        f"unsupported configuration approval type: {item.approval_type}"
                    )
                item_trust = trust_values.get((item.actor_uid, item.key_uid))
                if item_trust is None:
                    raise PermissionError(
                        f"supporting approval trust is unavailable: {item.approval_uid}"
                    )
                verify_approval(
                    item,
                    TrustedActor.model_validate(item_trust),
                    package_hash=item.package_hash,
                    effective_model_hash=model_hash,
                )
                if not any(
                    value.get("resource_type") == "approval_attestation"
                    and value.get("approval_uid") == item.approval_uid
                    and semantic_hash(value) == semantic_hash(item.model_dump(mode="json"))
                    for value in self.documents
                ):
                    raise PermissionError(
                        f"supporting approval is not canonical: {item.approval_uid}"
                    )
            self._validate_configuration_governance(
                configuration, model, supporting_signed, datetime.now(UTC)
            )
            transaction = SemanticTransaction(
                transaction_uid=uuid7_candidate(),
                base_commit=self.base,
                expected_revisions=(),
                effective_model_hash=model_hash,
                review_package_hash=package_hash,
                operations=(
                    SemanticOperation(
                        OperationType.CREATE_CONFIGURATION,
                        f"canonical/configurations/{configuration['configuration_uid']}.json",
                        configuration,
                    ),
                    SemanticOperation(
                        OperationType.RECORD_APPROVAL,
                        f"canonical/approvals/{signed.approval_uid}.json",
                        approval,
                    ),
                    SemanticOperation(
                        OperationType.RECORD_PROVENANCE,
                        f"canonical/provenance/{signed.provenance_uid}.json",
                        self._approval_provenance(signed),
                    ),
                ),
                approvals=(
                    ApprovalAttestation(
                        signed.approval_uid,
                        package_hash,
                        signed.actor_uid,
                        signed.actor_type,
                        signed.approval_type,
                    ),
                ),
                actor=actor_uid,
                delegation_uid=delegation_uid,
                idempotency_key=idempotency_key,
            )
            result = self.repository.apply(transaction, projection_updater=self._rebuild_projection)
            self.base = result.commit
            self._reload()
            return DomainResult(
                {
                    "result_commit": result.commit,
                    "configuration_uid": configuration["configuration_uid"],
                    "effective_model_hash": model_hash,
                }
            )
        except (
            JsonSchemaValidationError,
            KeyError,
            TypeError,
            ValueError,
            PermissionError,
            RuntimeError,
        ) as error:
            return self._error(
                "LESR-CONFIGURATION-CREATION-INVALID",
                ErrorCategory.AUTHORIZATION,
                str(error),
            )

    def _validate_configuration_governance(
        self,
        configuration: dict[str, Any],
        model: EffectiveModel,
        approvals: tuple[SignedApproval, ...],
        evaluation_time: datetime,
    ) -> None:
        """Require exact human evidence for every governed Configuration selection."""

        revisions = {
            str(value.get("revision_uid")): Revision.model_validate(value)
            for value in self.documents
            if value.get("resource_type") == "revision"
        }
        records = {
            str(value.get("record_uid")): ImmutableRecord.model_validate(value)
            for value in self.documents
            if value.get("resource_type") == "immutable_record"
        }
        rules = {
            str(value.get("rule_revision_uid")): RuleDefinition.model_validate(value)
            for value in self.documents
            if value.get("resource_type") == "rule_definition_revision"
            and value.get("rule_revision_uid") in set(model.rule_revision_uids)
        }
        trust_by_key = {
            str(value.get("key_uid")): TrustedActor.model_validate(value)
            for value in self.documents
            if value.get("resource_type") == "trusted_actor"
        }
        revoked = frozenset(
            str(value.get("approval_uid"))
            for value in self.documents
            if value.get("resource_type") == "approval_revocation"
            and datetime.fromisoformat(str(value["revoked_at"])) <= evaluation_time
        )
        requirements: dict[
            tuple[str, str], tuple[str, dict[str, object], frozenset[str]]
        ] = {}
        for revision_uid in configuration.get("active_deviation_revision_uids", ()):
            revision = revisions.get(str(revision_uid))
            if revision is None or revision.kind != "deviation":
                raise PermissionError(f"selected deviation is unavailable: {revision_uid}")
            fields = {item.path: item.value for item in revision.fields}
            rule_uid = str(fields.get("/rule_revision_uid", ""))
            rule = rules.get(rule_uid)
            if rule is None or not rule.deviation_policy.allowed:
                raise PermissionError(
                    f"selected deviation does not reference an effective relaxable Rule: {revision_uid}"
                )
            expiry = fields.get("/valid_until")
            if (
                not isinstance(expiry, str)
                or datetime.fromisoformat(expiry) <= evaluation_time
                or not fields.get("/compensating_control")
            ):
                raise PermissionError(f"selected deviation is expired or incomplete: {revision_uid}")
            subject_hash = governance_subject_hash(revision)
            scope: dict[str, object] = {
                "deviation_revision_uid": revision.revision_uid,
                "deviation_hash": subject_hash,
                "rule_revision_uid": rule_uid,
                "subject_uid": str(fields.get("/subject_uid", "")),
            }
            requirements[("deviation", revision.revision_uid)] = (
                subject_hash,
                scope,
                frozenset(rule.deviation_policy.required_approval_roles),
            )
        for revision_uid in configuration.get("active_exception_revision_uids", ()):
            revision = revisions.get(str(revision_uid))
            if revision is None or revision.kind != "exception":
                raise PermissionError(f"selected exception is unavailable: {revision_uid}")
            fields = {item.path: item.value for item in revision.fields}
            rule_uid = str(fields.get("/rule_revision_uid", ""))
            rule = rules.get(rule_uid)
            policy = rule.exception_policy if rule is not None else None
            if not isinstance(policy, dict) or not bool(policy.get("allowed", False)):
                raise PermissionError(
                    f"selected exception does not reference an effective exceptable Rule: {revision_uid}"
                )
            expiry = fields.get("/valid_until")
            if not isinstance(expiry, str) or datetime.fromisoformat(expiry) <= evaluation_time:
                raise PermissionError(f"selected exception is expired: {revision_uid}")
            raw_roles = policy.get("required_approval_roles", [])
            if not isinstance(raw_roles, list):
                raise TypeError("exception approval roles must be a list")
            subject_hash = governance_subject_hash(revision)
            scope = {
                "exception_revision_uid": revision.revision_uid,
                "exception_hash": subject_hash,
                "rule_revision_uid": rule_uid,
                "subject_uid": str(fields.get("/subject_uid", "")),
            }
            requirements[("exception", revision.revision_uid)] = (
                subject_hash,
                scope,
                frozenset(str(item) for item in raw_roles),
            )
        for record_uid in configuration.get("conflict_resolution_uids", ()):
            record = records.get(str(record_uid))
            if record is None or record.record_type != "rule_conflict_resolution":
                raise PermissionError(f"selected conflict resolution is unavailable: {record_uid}")
            left = record.field_value("/left_rule_revision_uid")
            right = record.field_value("/right_rule_revision_uid")
            if not isinstance(left, str) or not isinstance(right, str):
                raise PermissionError(f"selected conflict resolution is incomplete: {record_uid}")
            scope = {
                "resolution_record_uid": record.record_uid,
                "resolution_hash": record.content_hash,
                "left_rule_revision_uid": left,
                "right_rule_revision_uid": right,
            }
            requirements[("rule_conflict_resolution", record.record_uid)] = (
                record.content_hash,
                scope,
                frozenset(("technical",)),
            )
        uid_fields = {
            "deviation": "deviation_revision_uid",
            "exception": "exception_revision_uid",
            "rule_conflict_resolution": "resolution_record_uid",
        }
        provided = {
            (item.approval_type, str(item.scope.get(uid_fields[item.approval_type], ""))): item
            for item in approvals
        }
        if set(provided) != set(requirements):
            raise PermissionError(
                "supporting approvals must exactly cover all governed Configuration selections"
            )
        for key, (package_hash, scope, roles) in requirements.items():
            approval = provided[key]
            trust = trust_by_key.get(approval.key_uid)
            if trust is None:
                raise PermissionError(f"supporting approval trust is unavailable: {approval.approval_uid}")
            verify_bound_approval(
                approval,
                trust,
                package_hash=package_hash,
                effective_model_hash=model.model_hash,
                approval_type=key[0],
                scope=scope,
                allowed_roles=roles,
                revoked_approval_uids=revoked,
                now=evaluation_time,
            )

    @staticmethod
    def _approval_provenance(approval: SignedApproval) -> dict[str, Any]:
        value: dict[str, Any] = {
            "schema_version": "1.0",
            "resource_type": "provenance_record",
            "provenance_uid": approval.provenance_uid,
            "subject_uid": approval.approval_uid,
            "kind": "asserted",
            "responsible_actor_uid": approval.actor_uid,
            "performed_by_actor_uid": approval.actor_uid,
            "on_behalf_of_actor_uid": None,
            "tool_uids": [],
            "tool_identity": "human-ed25519-bootstrap",
            "delegation_uid": None,
            "used_uids": [],
            "generated_uids": [approval.approval_uid],
            "review_package_uid": None,
            "validation_run_uids": [],
            "context_bundle_hash": None,
            "generated_at": approval.issued_at.isoformat().replace("+00:00", "Z"),
        }
        value["content_hash"] = semantic_hash(value)
        return value

    def _canonical_revisions(self) -> tuple[Revision, ...]:
        return tuple(
            Revision.model_validate(value)
            for value in self.documents
            if value.get("resource_type") == "revision"
        )

    def _workspace_lifecycle_states(
        self,
        workspace: Workspace,
        canonical_evaluator: SemanticEvaluator,
    ) -> tuple[tuple[str, str], ...]:
        return tuple(
            (
                copy.object_uid,
                canonical_evaluator.nodes[copy.object_uid].lifecycle_state
                if copy.object_uid in canonical_evaluator.nodes
                else self._initial_state_for_kind(copy.kind),
            )
            for copy in workspace.working_copies
        )

    def _submission_from_preview(self, preview: WorkspacePreview) -> Any:
        """Adapt transient preview content to the existing pure evaluator.

        The evaluator currently consumes Revision-shaped nodes.  These stable,
        process-local identities are never returned as candidate resources and
        never enter a Workspace ref or Canonical Git.
        """

        state_by_object = {
            item.object_uid: item.working_state_hash
            for item in preview.workspace.working_copies
        }
        revisions = tuple(
            Revision.model_validate(
                item.model_dump(mode="python")
                | {
                    "revision_uid": self._stable_uuid7(
                        "preview:revision:"
                        f"{preview.workspace.workspace_uid}:{item.object_uid}:"
                        f"{state_by_object[item.object_uid]}",
                        preview.previewed_at,
                    )
                }
            )
            for item in preview.revision_previews
        )
        lifecycle_records = tuple(
            ImmutableRecord.model_validate(
                item.model_dump(mode="python")
                | {
                    "record_uid": self._stable_uuid7(
                        "preview:lifecycle:"
                        f"{preview.workspace.workspace_uid}:{item.subject_uid}:"
                        f"{state_by_object[item.subject_uid]}",
                        preview.previewed_at,
                    )
                }
            )
            for item in preview.lifecycle_record_previews
        )
        overlay_hash = semantic_hash(
            {
                "workspace_uid": preview.workspace.workspace_uid,
                "previewed_at": preview.previewed_at.isoformat(),
                "working_states": tuple(sorted(state_by_object.items())),
            }
        )
        candidate = SimpleNamespace(
            revisions=revisions,
            relation_revisions=preview.relation_proposals,
            lifecycle_records=lifecycle_records,
            candidate_hash=overlay_hash,
            checkpoint_uid=f"preview:{preview.workspace.workspace_uid}",
        )
        diff = SimpleNamespace(
            changes=preview.changes,
            scope=preview.scope,
        )
        return SimpleNamespace(
            workspace=preview.workspace,
            candidate=candidate,
            semantic_diff=diff,
        )

    def _candidate_context(
        self,
        submission: Any,
        evaluator: SemanticEvaluator,
    ) -> Any:
        model = self._effective_model(submission.workspace.configuration_uid)
        policies = [
            item for item in model.context_policies if item.task_type in {"review", "*"}
        ]
        exact = [item for item in policies if item.task_type == "review"]
        selected = exact or [item for item in policies if item.task_type == "*"]
        if len(selected) != 1:
            raise ValueError("Effective Model must define exactly one review Context Policy")
        if not submission.candidate.revisions:
            raise ValueError("Workspace assessment requires at least one Working Copy")
        policy = selected[0]
        return plan_context(
            evaluator,
            (submission.candidate.revisions[0].object_uid,),
            policy.mandatory_predicates,
            token_limit=500,
            conditional_predicates=policy.conditional_predicates,
            mandatory_formal_trace=policy.mandatory_formal_trace,
            forbidden_sensitivities=policy.forbidden_sensitivities,
        )

    @staticmethod
    def _assessment_decision(
        validation: dict[str, Any],
        impact_completeness: str,
    ) -> dict[str, Any]:
        operation = validation.get("operation_decision", {})
        operation_disposition = str(operation.get("disposition", "indeterminate"))
        reasons = [str(item) for item in operation.get("reasons", ())]
        if validation.get("outcome") != "pass" or operation_disposition in {
            "block",
            "indeterminate",
        }:
            disposition = DecisionDisposition.BLOCK
            reasons.append("WORKSPACE_REQUIRES_AGENT_REPAIR")
        elif impact_completeness != "COMPLETE":
            disposition = DecisionDisposition.BLOCK
            reasons.append(f"IMPACT_{impact_completeness}")
        elif operation_disposition == "requires_governance":
            disposition = DecisionDisposition.HUMAN_DECISION_NOW
            reasons.append("ENGINEERING_POLICY_REQUIRES_HUMAN_DECISION")
        else:
            disposition = DecisionDisposition.AUTO_EXECUTE
            reasons.append("WITHIN_ACTIVE_ENGINEERING_POLICY")
        return {
            "disposition": disposition.value,
            "reasons": tuple(sorted(set(reasons))),
        }

    def _evaluator(
        self,
        configuration_uid: str,
        evaluation_time: datetime,
        *,
        submission: Any | None = None,
    ) -> SemanticEvaluator:
        configuration = self._configuration(configuration_uid)
        effective_model = self._effective_model(configuration_uid)
        candidate_records = (
            tuple(submission.candidate.lifecycle_records) if submission is not None else ()
        )
        kind_definitions = {
            item.name: item
            for item in (
                KindDefinitionRevision.model_validate(value)
                for value in self.documents
                if value.get("resource_type") == "kind_definition_revision"
                and value.get("revision_uid") in set(effective_model.definition_revision_uids)
            )
        }
        relation_types = tuple(
            RelationTypeRevision.model_validate(value)
            for value in self.documents
            if value.get("resource_type") == "relation_type_revision"
            and value.get("revision_uid") in set(effective_model.definition_revision_uids)
        )
        relation_type_by_uid = {item.revision_uid: item for item in relation_types}
        nodes = {
            item.object_uid: GraphNode(
                revision=item,
                lifecycle_state=self._project_lifecycle(
                    item.object_uid,
                    kind_definitions[item.kind].workflow_revision_uid
                    if item.kind in kind_definitions
                    else None,
                    candidate_records,
                ),
            )
            for item in (
                Revision.model_validate(value)
                for value in self.documents
                if value.get("resource_type") == "revision"
                and value.get("revision_uid") in set(configuration.get("revision_uids", ()))
            )
        }
        relations = [
            GraphRelation(
                assertion=RelationAssertion.model_validate(value),
                relation_type_revision_uid=self._relation_type_uid(value),
                lifecycle_state=self._project_lifecycle(
                    str(value.get("assertion_uid")),
                    relation_type_by_uid[self._relation_type_uid(value)].workflow_revision_uid,
                    candidate_records,
                ),
            )
            for value in self.documents
            if value.get("resource_type") == "relation_assertion_revision"
            and value.get("relation_revision_uid")
            in set(configuration.get("relation_revision_uids", ()))
        ]
        workspace_uid = None
        checkpoint_uid = None
        overlay_hash = None
        if submission is not None:
            workspace_uid = submission.workspace.workspace_uid
            checkpoint_uid = submission.candidate.checkpoint_uid
            overlay_hash = submission.candidate.candidate_hash
            for revision in submission.candidate.revisions:
                nodes[revision.object_uid] = GraphNode(
                    revision=revision,
                    lifecycle_state=self._project_lifecycle(
                        revision.object_uid,
                        kind_definitions[revision.kind].workflow_revision_uid
                        if revision.kind in kind_definitions
                        else None,
                        candidate_records,
                    ),
                    source="candidate",
                )
            relations.extend(
                GraphRelation(
                    assertion=item,
                    relation_type_revision_uid=self._relation_type_uid(
                        item.model_dump(mode="json")
                    ),
                    lifecycle_state=self._project_lifecycle(
                        item.assertion_uid,
                        relation_type_by_uid[
                            self._relation_type_uid(item.model_dump(mode="json"))
                        ].workflow_revision_uid,
                        candidate_records,
                    ),
                    source="candidate",
                )
                for item in submission.candidate.relation_revisions
            )
        unresolved = tuple(
            sorted(
                f"{endpoint.system}:{endpoint.namespace}:{endpoint.external_id}"
                f"@{endpoint.external_revision or 'unknown'}"
                for relation in relations
                for endpoint in (relation.assertion.source, relation.assertion.target)
                if endpoint.binding.value == "external" and endpoint.source_hash is None
            )
        )
        snapshot = GraphSnapshot(
            configuration_uid=configuration_uid,
            canonical_commit=self.base,
            effective_model_hash=str(configuration["effective_model_hash"]),
            workspace_uid=workspace_uid,
            checkpoint_uid=checkpoint_uid,
            evaluation_time=evaluation_time,
            nodes=tuple(nodes[key] for key in sorted(nodes)),
            relations=tuple(relations),
            candidate_overlay_hash=overlay_hash,
            unresolved_external_endpoints=unresolved,
        )
        return SemanticEvaluator(snapshot, relation_types)

    def _evaluator_from_review_evidence(self, package_uid: str) -> SemanticEvaluator:
        evidence = self.review_evidence.get(package_uid)
        if not isinstance(evidence, dict) or not isinstance(
            evidence.get("graph_snapshot"), dict
        ):
            raise TypeError("review Graph Snapshot is unavailable")
        snapshot = GraphSnapshot.model_validate(evidence["graph_snapshot"])
        relation_type_uids = {
            item.relation_type_revision_uid for item in snapshot.relations
        }
        relation_types = tuple(
            RelationTypeRevision.model_validate(value)
            for value in self.documents
            if value.get("resource_type") == "relation_type_revision"
            and value.get("revision_uid") in relation_type_uids
        )
        if {item.revision_uid for item in relation_types} != relation_type_uids:
            raise ValueError("review Graph Snapshot Relation Type is unavailable")
        return SemanticEvaluator(snapshot, relation_types)

    def _project_lifecycle(
        self,
        subject_uid: str,
        workflow_revision_uid: str | None,
        candidate_records: tuple[ImmutableRecord, ...],
    ) -> str:
        if workflow_revision_uid is None:
            return "indeterminate"
        workflow_value = next(
            (
                value
                for value in self.documents
                if value.get("resource_type") == "workflow_revision"
                and value.get("revision_uid") == workflow_revision_uid
            ),
            None,
        )
        if workflow_value is None:
            return "indeterminate"
        records = tuple(
            ImmutableRecord.model_validate(value)
            for value in self.documents
            if value.get("resource_type") == "immutable_record"
            and value.get("subject_uid") == subject_uid
        ) + tuple(item for item in candidate_records if item.subject_uid == subject_uid)
        projection = WorkflowProjector.project(
            WorkflowRevision.model_validate(workflow_value), records
        )
        return "indeterminate" if projection.conflicts else projection.state

    def _initial_state_for_kind(self, kind: str) -> str:
        definition = next(
            (
                KindDefinitionRevision.model_validate(value)
                for value in self.documents
                if value.get("resource_type") == "kind_definition_revision"
                and value.get("name") == kind
            ),
            None,
        )
        if definition is None or definition.workflow_revision_uid is None:
            return "indeterminate"
        workflow = next(
            (
                WorkflowRevision.model_validate(value)
                for value in self.documents
                if value.get("resource_type") == "workflow_revision"
                and value.get("revision_uid") == definition.workflow_revision_uid
            ),
            None,
        )
        return workflow.initial_state if workflow is not None else "indeterminate"

    def _validate_relation_proposal(
        self, workspace: Workspace, relation: RelationAssertion
    ) -> None:
        if relation.relation_type_revision_uid is None:
            raise ValueError("Relation Proposal must bind an exact Relation Type Revision")
        model = self._effective_model(workspace.configuration_uid)
        if relation.relation_type_revision_uid not in model.relation_policy_revision_uids:
            raise ValueError("Relation Type Revision is not selected by the Effective Model")
        relation_type = next(
            RelationTypeRevision.model_validate(value)
            for value in self.documents
            if value.get("resource_type") == "relation_type_revision"
            and value.get("revision_uid") == relation.relation_type_revision_uid
        )
        if relation.predicate != relation_type.predicate or relation.core_role != relation_type.core_role:
            raise ValueError("Relation Proposal predicate/Core Role mismatches its type")
        for endpoint in (relation.source, relation.target):
            if endpoint.binding not in relation_type.allowed_bindings:
                raise ValueError("Relation Proposal uses a Binding forbidden by its type")
        working_revisions = {
            copy.object_uid: Revision(
                object_uid=copy.object_uid,
                revision_number=copy.base_revision_number + 1,
                parent_revision_uid=copy.base_revision_uid,
                human_key=copy.human_key,
                kind=copy.kind,
                facets=copy.facets,
                fields=copy.draft_fields,
                fragments=copy.draft_fragments,
                provenance_origin=ProvenanceKind.AUTHORED,
            )
            for copy in workspace.working_copies
        }
        canonical_revisions = {
            item.object_uid: item
            for item in (
                Revision.model_validate(value)
                for value in self.documents
                if value.get("resource_type") == "revision"
            )
        }
        revisions = canonical_revisions | working_revisions
        for endpoint, allowed, name in (
            (relation.source, relation_type.source_kind_or_facet, "source"),
            (relation.target, relation_type.target_kind_or_facet, "target"),
        ):
            if endpoint.binding is BindingMode.EXTERNAL:
                continue
            revision = revisions.get(endpoint.object_uid or "")
            if revision is None:
                raise ValueError(f"Relation Proposal {name} is unresolved")
            if not SemanticEvaluator._matches_endpoint(revision, allowed):
                raise ValueError(f"Relation Proposal {name} Kind/Facet is forbidden")

    def _validate_requested_transitions(
        self,
        workspace: Workspace,
        evaluator: SemanticEvaluator,
        actor_uid: str,
    ) -> None:
        actor_roles = {
            str(role)
            for value in self.documents
            if value.get("resource_type") == "trusted_actor"
            and value.get("actor_uid") == actor_uid
            for role in value.get("roles", ())
        }
        kind_definitions = {
            str(value.get("name")): KindDefinitionRevision.model_validate(value)
            for value in self.documents
            if value.get("resource_type") == "kind_definition_revision"
        }
        workflows = {
            str(value.get("revision_uid")): WorkflowRevision.model_validate(value)
            for value in self.documents
            if value.get("resource_type") == "workflow_revision"
        }
        for copy in workspace.working_copies:
            if copy.requested_lifecycle_state is None:
                continue
            definition = kind_definitions.get(copy.kind)
            workflow = (
                workflows.get(definition.workflow_revision_uid)
                if definition is not None and definition.workflow_revision_uid is not None
                else None
            )
            if workflow is None:
                raise ValueError("Lifecycle request has no exact Workflow Revision")
            current = (
                evaluator.nodes[copy.object_uid].lifecycle_state
                if copy.object_uid in evaluator.nodes
                else workflow.initial_state
            )
            transitions = [
                item
                for item in workflow.transitions
                if item.from_state == current
                and item.to_state == copy.requested_lifecycle_state
            ]
            if len(transitions) != 1:
                raise ValueError("Lifecycle transition is not defined by the selected Workflow")
            transition = transitions[0]
            if transition.roles and not actor_roles.intersection(transition.roles):
                raise PermissionError("actor lacks the role required by Lifecycle Workflow")
            requests = tuple(
                item
                for item in copy.edit_log
                if item.operation_type.value == "request_lifecycle_transition"
                and item.value == copy.requested_lifecycle_state
            )
            if len(requests) != 1:
                raise ValueError("Lifecycle transition has no unique Edit Operation evidence")
            request = requests[0]
            evidence_documents = tuple(
                value
                for value in self.documents
                if any(
                    value.get(field) in set(request.evidence_uids)
                    for field in (
                        "revision_uid",
                        "record_uid",
                        "finding_uid",
                        "provenance_uid",
                    )
                )
            )
            evidence_kinds = {
                str(value.get("kind") or value.get("record_type") or value.get("resource_type"))
                for value in evidence_documents
            }
            missing_evidence = set(transition.evidence_kinds) - evidence_kinds
            if missing_evidence:
                raise ValueError(
                    "Lifecycle transition is missing evidence: "
                    + ", ".join(sorted(missing_evidence))
                )
            fields = {self._rule_path(item.path): item.value for item in copy.draft_fields}
            for guard in transition.guards:
                if guard.startswith("field:"):
                    expression = guard.removeprefix("field:")
                    path, separator, expected = expression.partition("=")
                    actual = fields.get(self._rule_path(path))
                    satisfied = actual is not None and (
                        not separator or str(actual) == expected
                    )
                elif guard.startswith("attestation:"):
                    satisfied = guard.removeprefix("attestation:") in set(
                        request.human_attestations
                    )
                elif guard.startswith("evidence:"):
                    satisfied = guard.removeprefix("evidence:") in evidence_kinds
                else:
                    raise ValueError(f"unsupported deterministic Workflow guard: {guard}")
                if not satisfied:
                    raise ValueError(f"Lifecycle Workflow guard is not satisfied: {guard}")

    def _configuration(self, configuration_uid: str) -> dict[str, Any]:
        try:
            return next(
                item
                for item in self.documents
                if item.get("resource_type") == "configuration_snapshot"
                and item.get("configuration_uid") == configuration_uid
            )
        except StopIteration as error:
            raise KeyError(f"configuration is not available: {configuration_uid}") from error

    def _next_configuration(
        self, submission: Submission, *, evaluation_time: datetime
    ) -> ConfigurationSnapshot:
        """Resolve the exact post-Apply configuration before review is signed."""

        current = ConfigurationSnapshot.model_validate(
            self._configuration(submission.workspace.configuration_uid)
        )
        revision_object = {
            str(item["revision_uid"]): str(item["object_uid"])
            for item in self.documents
            if item.get("resource_type") == "revision"
        }
        selected_revisions = {
            revision_object[uid]: uid
            for uid in current.revision_uids
            if uid in revision_object
        }
        for revision in submission.candidate.revisions:
            selected_revisions[revision.object_uid] = revision.revision_uid

        relation_assertion = {
            str(item["relation_revision_uid"]): str(item["assertion_uid"])
            for item in self.documents
            if item.get("resource_type") == "relation_assertion_revision"
        }
        selected_relations = {
            relation_assertion[uid]: uid
            for uid in current.relation_revision_uids
            if uid in relation_assertion
        }
        for relation in submission.candidate.relation_revisions:
            selected_relations[relation.assertion_uid] = relation.relation_revision_uid

        return ConfigurationSnapshot(
            parent_configuration_uid=current.configuration_uid,
            base_commit=submission.workspace.base_commit,
            revision_uids=tuple(sorted(selected_revisions.values())),
            relation_revision_uids=tuple(sorted(selected_relations.values())),
            profile_revision_uids=current.profile_revision_uids,
            active_deviation_revision_uids=current.active_deviation_revision_uids,
            active_exception_revision_uids=current.active_exception_revision_uids,
            conflict_resolution_uids=current.conflict_resolution_uids,
            variant=current.variant,
            valid_at=current.valid_at,
            effective_model_hash=current.effective_model_hash,
            closure_status=current.closure_status,
            closure_reasons=current.closure_reasons,
            created_at=evaluation_time,
        )

    def _validate_submission(
        self,
        submission: Any,
        evaluator: SemanticEvaluator,
        *,
        validation_run_uid: str | None = None,
        completed_at: datetime | None = None,
    ) -> dict[str, Any]:
        """Compile once from the Effective Model and decide the requested operation."""

        configuration = self._configuration(submission.workspace.configuration_uid)
        model = self._effective_model(submission.workspace.configuration_uid)
        evaluation_time = completed_at or evaluator.snapshot.evaluation_time
        run_uid = validation_run_uid or uuid7_candidate()
        units = UnitRegistry(
            tuple(
                UnitDefinition(item.unit, item.dimension, Decimal(item.scale_to_base))
                for item in model.unit_registry
            )
        )
        schemas = self._effective_kind_schemas(model)
        for revision in submission.candidate.revisions:
            self._validate_revision_against_kind(revision, schemas, units)

        selected_rule_uids = set(model.rule_revision_uids)
        rule_values = sorted(
            (
                value
                for value in self.documents
                if value.get("resource_type") == "rule_definition_revision"
                and value.get("rule_revision_uid") in selected_rule_uids
            ),
            key=lambda item: str(item["rule_revision_uid"]),
        )
        compiled_rules = []
        compilation_failures: list[tuple[RuleDefinition, tuple[str, ...]]] = []
        for raw_rule in rule_values:
            rule = RuleDefinition.model_validate(raw_rule)
            symbols = self._symbols_for_kind(rule.target_type, rule.target_selector, schemas)
            compiled = RuleCompiler(symbols, units).compile(rule)
            if not compiled.passed or compiled.ast is None:
                compilation_failures.append(
                    (rule, tuple(item.code for item in compiled.diagnostics))
                )
            else:
                compiled_rules.append((rule, compiled.ast))

        conflicted_rule_uids = self._conflicted_rule_uids(
            configuration, compiled_rules, evaluation_time
        )

        observations: list[ValidationObservation] = []
        findings: list[ValidationFinding] = []
        for rule, diagnostics in compilation_failures:
            finding_uid = self._stable_uuid7(
                f"{run_uid}:{rule.rule_revision_uid}:compiler", evaluation_time
            )
            observations.append(
                ValidationObservation(
                    observation_uid=self._stable_uuid7(
                        f"{finding_uid}:observation", evaluation_time
                    ),
                    rule_uid=rule.rule_uid,
                    rule_revision_uid=rule.rule_revision_uid,
                    target_uid=submission.workspace.workspace_uid,
                    outcome=RuleOutcome.EVALUATOR_ERROR,
                    enforcement=EnforcementEffect.BLOCK_OPERATION,
                    explanation=list(diagnostics),
                )
            )
            findings.append(
                ValidationFinding(
                    finding_uid=finding_uid,
                    validation_run_uid=run_uid,
                    rule_uid=rule.rule_uid,
                    rule_revision_uid=rule.rule_revision_uid,
                    subject_uid=submission.workspace.workspace_uid,
                    outcome=RuleOutcome.EVALUATOR_ERROR,
                    enforcement=EnforcementEffect.BLOCK_OPERATION,
                    blocking=True,
                    explanation=list(diagnostics),
                    created_at=evaluation_time,
                )
            )

        for revision in submission.candidate.revisions:
            working_copy = next(
                (
                    item
                    for item in submission.workspace.working_copies
                    if item.object_uid == revision.object_uid
                ),
                None,
            )
            transition_operations = tuple(
                item
                for item in (working_copy.edit_log if working_copy is not None else ())
                if item.operation_type.value == "request_lifecycle_transition"
            )
            evidence_uids = {
                uid for item in transition_operations for uid in item.evidence_uids
            }
            evidence_kinds = {
                evaluator.nodes[uid].revision.kind
                for uid in evidence_uids
                if uid in evaluator.nodes
            }
            attestations = {
                value
                for item in transition_operations
                for value in item.human_attestations
            }
            transition = (
                (
                    evaluator.nodes[revision.object_uid].lifecycle_state,
                    str(transition_operations[-1].value),
                )
                if transition_operations and revision.object_uid in evaluator.nodes
                else None
            )
            applicability_fields = {
                self._rule_path(field.path): ValueCell.present(
                    self._quantity(field.value) or field.value
                )
                for field in revision.fields
            }
            constraint_fields = tuple(
                (
                    self._rule_path(field.path),
                    decode_runtime_value(field.value),
                )
                for field in revision.fields
            )
            active_deviations = self._active_deviation_rules(
                configuration, revision, compiled_rules, evaluation_time
            )
            active_exceptions = self._active_exception_rules(
                configuration, revision, compiled_rules, evaluation_time
            )
            for rule, ast in compiled_rules:
                if ast.target_type.value != "revision" or ast.target_kind != revision.kind:
                    continue
                predicates = {
                    item.predicate for item in ast.constraints if item.predicate is not None
                }
                relation_counts = {
                    predicate: evaluator.relation_count(
                        revision.object_uid,
                        predicate=predicate,
                        direction=Direction.OUTGOING,
                    )
                    for predicate in predicates
                }
                relation_values = {
                    predicate: self._relation_values(
                        evaluator, revision.object_uid, predicate, ast.constraints
                    )
                    for predicate in predicates
                }
                base_constraint_environment = ConstraintEnvironment(
                    target_uid=revision.object_uid,
                    fields=constraint_fields,
                    relation_counts=tuple(sorted(relation_counts.items())),
                    evidence_kinds=tuple(sorted(evidence_kinds)),
                    lifecycle_transition=transition,
                    human_attestations=tuple(sorted(attestations)),
                )

                evaluated = evaluate_rule(
                    ast,
                    EvaluationEnvironment(
                        target_kind=revision.kind,
                        fields=applicability_fields,
                        relation_counts=relation_counts,
                        relation_values=relation_values,
                        operation="apply_transaction",
                        active_deviation_rule_uids=frozenset(active_deviations),
                        active_exception_rule_uids=active_exceptions,
                        conflicted_rule_uids=conflicted_rule_uids,
                        evidence_kinds=frozenset(evidence_kinds),
                        lifecycle_transition=transition,
                        human_attestations=frozenset(attestations),
                    ),
                    partial(
                        self._evaluate_target_constraint,
                        evaluator,
                        revision.object_uid,
                        base_constraint_environment,
                        units,
                    ),
                )
                observation_uid = self._stable_uuid7(
                    f"{run_uid}:{rule.rule_revision_uid}:{revision.revision_uid}:observation",
                    evaluation_time,
                )
                explanation: Any = (
                    [item.reason for item in evaluated.constraint.children]
                    if evaluated.constraint is not None
                    else [evaluated.applicability.reason]
                )
                observations.append(
                    ValidationObservation(
                        observation_uid=observation_uid,
                        rule_uid=rule.rule_uid,
                        rule_revision_uid=rule.rule_revision_uid,
                        target_uid=revision.object_uid,
                        target_revision_uid=revision.revision_uid,
                        outcome=evaluated.outcome,
                        enforcement=evaluated.enforcement,
                        explanation=explanation,
                    )
                )
                if evaluated.outcome in {RuleOutcome.PASS, RuleOutcome.NOT_APPLICABLE}:
                    continue
                suppressed = evaluated.outcome is RuleOutcome.SUPPRESSED_BY_DEVIATION
                finding_blocking = not suppressed and evaluated.enforcement in {
                    EnforcementEffect.BLOCK_OPERATION,
                    EnforcementEffect.REQUIRE_DEVIATION,
                }
                finding_uid = self._stable_uuid7(
                    f"{run_uid}:{rule.rule_revision_uid}:{revision.revision_uid}:finding",
                    evaluation_time,
                )
                findings.append(
                    ValidationFinding(
                        finding_uid=finding_uid,
                        validation_run_uid=run_uid,
                        rule_uid=rule.rule_uid,
                        rule_revision_uid=rule.rule_revision_uid,
                        subject_uid=revision.object_uid,
                        subject_revision_uid=revision.revision_uid,
                        outcome=evaluated.outcome,
                        enforcement=evaluated.enforcement,
                        blocking=finding_blocking,
                        status="suppressed_by_deviation" if suppressed else "open",
                        deviation_revision_uid=active_deviations.get(rule.rule_uid),
                        explanation=explanation,
                        created_at=evaluation_time,
                    )
                )

        generic_targets: list[
            tuple[
                ValidationTarget,
                str,
                str,
                str | None,
                dict[str, ValueCell],
                frozenset[str],
                tuple[str, str] | None,
                frozenset[str],
            ]
        ] = []
        for relation in submission.candidate.relation_revisions:
            generic_targets.append(
                (
                    ValidationTarget.RELATION,
                    relation.predicate,
                    relation.assertion_uid,
                    relation.relation_revision_uid,
                    {
                        "predicate": ValueCell.present(relation.predicate),
                        "source_binding": ValueCell.present(relation.source.binding.value),
                        "target_binding": ValueCell.present(relation.target.binding.value),
                        "provenance": ValueCell.present(relation.provenance_kind.value),
                        "formal_trace_category_count": ValueCell.present(
                            len(relation.formal_trace_categories)
                        ),
                    },
                    frozenset(),
                    None,
                    frozenset(),
                )
            )
        generic_targets.extend(
            (
                target_type,
                kind,
                target_uid,
                None,
                fields,
                frozenset(),
                None,
                frozenset(),
            )
            for target_type, kind, target_uid, fields in (
                (
                    ValidationTarget.WORKSPACE,
                    "workspace",
                    submission.workspace.workspace_uid,
                    {
                        "state": ValueCell.present(submission.workspace.state.value),
                        "working_copy_count": ValueCell.present(
                            len(submission.workspace.working_copies)
                        ),
                        "candidate_revision_count": ValueCell.present(
                            len(submission.candidate.revisions)
                        ),
                    },
                ),
                (
                    ValidationTarget.CONFIGURATION,
                    "configuration_snapshot",
                    str(configuration["configuration_uid"]),
                    {
                        "closure_status": ValueCell.present(
                            str(configuration.get("closure_status", "indeterminate"))
                        ),
                        "revision_count": ValueCell.present(
                            len(configuration.get("revision_uids", ()))
                        ),
                        "relation_revision_count": ValueCell.present(
                            len(configuration.get("relation_revision_uids", ()))
                        ),
                        "deviation_count": ValueCell.present(
                            len(configuration.get("active_deviation_revision_uids", ()))
                        ),
                    },
                ),
                (
                    ValidationTarget.ACTIVITY,
                    "submit_review",
                    submission.workspace.workspace_uid,
                    {
                        "evidence_count": ValueCell.present(
                            sum(
                                len(item.evidence_uids)
                                for working_copy in submission.workspace.working_copies
                                for item in working_copy.edit_log
                            )
                        ),
                        "actor_uid": ValueCell.present(submission.workspace.actor_uid),
                    },
                ),
                (
                    ValidationTarget.OPERATION,
                    "apply_transaction",
                    submission.workspace.workspace_uid,
                    {
                        "operation": ValueCell.present("apply_transaction"),
                        "risk_class": ValueCell.present(
                            self._derived_impact_class(submission)
                        ),
                        "changed_resource_count": ValueCell.present(
                            len(submission.candidate.revisions)
                        ),
                        "changed_relation_count": ValueCell.present(
                            len(submission.candidate.relation_revisions)
                        ),
                    },
                ),
            )
        )
        for copy in submission.workspace.working_copies:
            if copy.requested_lifecycle_state is None:
                continue
            transition_operations = tuple(
                item
                for item in copy.edit_log
                if item.operation_type.value == "request_lifecycle_transition"
            )
            transition_evidence_uids = frozenset(
                uid for item in transition_operations for uid in item.evidence_uids
            )
            transition_evidence_kinds = frozenset(
                str(
                    value.get("kind")
                    or value.get("record_type")
                    or value.get("resource_type")
                )
                for value in self.documents
                if any(
                    value.get(field) in transition_evidence_uids
                    for field in ("revision_uid", "record_uid", "finding_uid")
                )
            )
            transition_attestations = frozenset(
                value
                for item in transition_operations
                for value in item.human_attestations
            )
            current_state = (
                evaluator.nodes[copy.object_uid].lifecycle_state
                if copy.object_uid in evaluator.nodes
                else self._initial_state_for_kind(copy.kind)
            )
            generic_targets.append(
                (
                    ValidationTarget.STATE_TRANSITION,
                    copy.kind,
                    copy.object_uid,
                    copy.base_revision_uid,
                    {
                        "from_state": ValueCell.present(current_state),
                        "to_state": ValueCell.present(copy.requested_lifecycle_state),
                        "evidence_count": ValueCell.present(
                            len(transition_evidence_uids)
                        ),
                        "attestation_count": ValueCell.present(
                            len(transition_attestations)
                        ),
                    },
                    transition_evidence_kinds,
                    (current_state, copy.requested_lifecycle_state),
                    transition_attestations,
                )
            )

        for rule, ast in compiled_rules:
            if ast.target_type is ValidationTarget.REVISION:
                continue
            for (
                target_type,
                target_kind,
                target_uid,
                target_revision_uid,
                fields,
                generic_evidence_kinds,
                transition,
                generic_attestations,
            ) in generic_targets:
                if target_type is not ast.target_type or target_kind != ast.target_kind:
                    continue
                generic_constraint_environment = ConstraintEnvironment(
                    target_uid=target_uid,
                    fields=tuple(
                        (
                            path,
                            decode_runtime_value(
                                cast_value.value,
                                kind_hint=(
                                    None
                                    if cast_value.state.value == "value"
                                    else RuntimeValueKind(cast_value.state.value)
                                ),
                            ),
                        )
                        for path, cast_value in fields.items()
                    ),
                    evidence_kinds=tuple(sorted(generic_evidence_kinds)),
                    lifecycle_transition=transition,
                    human_attestations=tuple(sorted(generic_attestations)),
                )
                evaluated = evaluate_rule(
                    ast,
                    EvaluationEnvironment(
                        target_type=target_type,
                        target_kind=target_kind,
                        fields=fields,
                        operation="apply_transaction",
                        evidence_kinds=generic_evidence_kinds,
                        lifecycle_transition=transition,
                        human_attestations=generic_attestations,
                        conflicted_rule_uids=conflicted_rule_uids,
                    ),
                    partial(
                        self._evaluate_target_constraint,
                        evaluator,
                        target_uid,
                        generic_constraint_environment,
                        units,
                    ),
                )
                observation_uid = self._stable_uuid7(
                    f"{run_uid}:{rule.rule_revision_uid}:{target_uid}:observation",
                    evaluation_time,
                )
                generic_explanation: Any = (
                    evaluated.constraint.reason
                    if evaluated.constraint is not None
                    else evaluated.applicability.reason
                )
                observations.append(
                    ValidationObservation(
                        observation_uid=observation_uid,
                        rule_uid=rule.rule_uid,
                        rule_revision_uid=rule.rule_revision_uid,
                        target_uid=target_uid,
                        target_revision_uid=target_revision_uid,
                        outcome=evaluated.outcome,
                        enforcement=evaluated.enforcement,
                        explanation=generic_explanation,
                    )
                )
                if evaluated.outcome in {RuleOutcome.PASS, RuleOutcome.NOT_APPLICABLE}:
                    continue
                finding_uid = self._stable_uuid7(
                    f"{run_uid}:{rule.rule_revision_uid}:{target_uid}:finding",
                    evaluation_time,
                )
                findings.append(
                    ValidationFinding(
                        finding_uid=finding_uid,
                        validation_run_uid=run_uid,
                        rule_uid=rule.rule_uid,
                        rule_revision_uid=rule.rule_revision_uid,
                        subject_uid=target_uid,
                        subject_revision_uid=target_revision_uid,
                        outcome=evaluated.outcome,
                        enforcement=evaluated.enforcement,
                        blocking=evaluated.enforcement
                        in {
                            EnforcementEffect.BLOCK_OPERATION,
                            EnforcementEffect.REQUIRE_DEVIATION,
                        },
                        explanation=generic_explanation,
                        created_at=evaluation_time,
                    )
                )

        blocking_finding_uids = tuple(
            item.finding_uid for item in findings if item.blocking
        )
        governance = tuple(
            item.finding_uid
            for item in findings
            if not item.blocking
            and item.status == "open"
            and item.enforcement
            in {
                EnforcementEffect.REQUIRE_ACKNOWLEDGEMENT,
                EnforcementEffect.REQUIRE_REVIEW,
            }
        )
        informational = tuple(
            item.finding_uid
            for item in findings
            if not item.blocking and item.finding_uid not in governance
        )
        disposition = (
            OperationDisposition.BLOCK
            if blocking_finding_uids
            else OperationDisposition.REQUIRES_GOVERNANCE
            if governance
            else OperationDisposition.ALLOW_WITH_OBSERVATIONS
            if informational
            else OperationDisposition.ALLOW
        )
        decision = OperationDecision(
            operation="apply_transaction",
            disposition=disposition,
            allowed_after_governance=not blocking_finding_uids,
            blocking_finding_uids=blocking_finding_uids,
            governance_finding_uids=governance,
            observation_finding_uids=informational,
            reasons=tuple(
                f"{item.enforcement.value}:{item.rule_revision_uid}"
                for item in findings
                if item.blocking
            ),
        )
        outcome: Literal["pass", "fail", "indeterminate"] = (
            "fail" if blocking_finding_uids else "pass"
        )
        run = ValidationRun(
            validation_run_uid=run_uid,
            workspace_uid=submission.workspace.workspace_uid,
            base_commit=submission.workspace.base_commit,
            configuration_uid=submission.workspace.configuration_uid,
            effective_model_hash=submission.workspace.effective_model_hash,
            candidate_hash=submission.candidate.candidate_hash,
            observations=tuple(observations),
            finding_uids=tuple(item.finding_uid for item in findings),
            operation_decision=decision,
            outcome=outcome,
            completed_at=evaluation_time,
        )
        serialized_findings = tuple(
            item.model_dump(mode="json", exclude_none=True) for item in findings
        )
        return {
            "snapshot_hash": evaluator.snapshot.snapshot_hash,
            "candidate_hash": submission.candidate.candidate_hash,
            "outcome": outcome,
            "operation_decision": decision.model_dump(mode="json"),
            "findings": serialized_findings,
            "finding_hashes": tuple(item.content_hash for item in findings),
            "validation_hash": run.content_hash,
            "validation_run": run.model_dump(mode="json"),
        }

    @staticmethod
    def _derived_impact_class(submission: Any) -> str:
        """Classify semantic impact without accepting an adapter-provided label."""

        semantic_diff = getattr(submission, "semantic_diff", None)
        changes = tuple(getattr(semantic_diff, "changes", ()))
        governed_definition_kinds = {
            "kind_definition",
            "facet_definition",
            "relation_type_definition",
            "workflow_definition",
            "normative_profile",
            "rule_definition",
            "deviation",
        }
        if (
            any(item.change_type in {"delete", "transition"} for item in changes)
            or any(
                item.kind in governed_definition_kinds
                for item in submission.candidate.revisions
            )
            or len(submission.candidate.revisions) > 25
        ):
            return "high"
        if submission.candidate.relation_revisions or len(submission.candidate.revisions) > 5:
            return "medium"
        return "low"

    @staticmethod
    def _stable_uuid7(seed: str, occurred_at: datetime) -> str:
        timestamp = int(occurred_at.timestamp() * 1000) & ((1 << 48) - 1)
        payload = bytearray(timestamp.to_bytes(6, "big") + hashlib.sha256(seed.encode()).digest()[:10])
        payload[6] = (payload[6] & 0x0F) | 0x70
        payload[8] = (payload[8] & 0x3F) | 0x80
        return str(uuid.UUID(bytes=bytes(payload)))

    def _effective_kind_schemas(
        self, model: EffectiveModel
    ) -> dict[str, tuple[KindDefinitionRevision, dict[str, FieldDefinition]]]:
        selected = set(model.definition_revision_uids)
        facets = {
            item.revision_uid: item
            for item in (
                FacetDefinitionRevision.model_validate(value)
                for value in self.documents
                if value.get("resource_type") == "facet_definition_revision"
                and value.get("revision_uid") in selected
            )
        }
        result: dict[str, tuple[KindDefinitionRevision, dict[str, FieldDefinition]]] = {}
        for kind in (
            KindDefinitionRevision.model_validate(value)
            for value in self.documents
            if value.get("resource_type") == "kind_definition_revision"
            and value.get("revision_uid") in selected
        ):
            fields: dict[str, FieldDefinition] = {}
            for facet_uid in (
                *kind.required_facet_revision_uids,
                *kind.optional_facet_revision_uids,
            ):
                facet = facets.get(facet_uid)
                if facet is None:
                    raise ValueError(f"Kind references unavailable Facet revision: {facet_uid}")
                for definition in facet.fields:
                    path = self._rule_path(definition.path)
                    previous = fields.setdefault(path, definition)
                    if previous != definition:
                        raise ValueError(f"Facet field contract conflicts at {definition.path}")
            if kind.name in result:
                raise ValueError(f"Effective Model defines Kind twice: {kind.name}")
            result[kind.name] = (kind, fields)
        return result

    def _symbols_for_kind(
        self,
        target_type: ValidationTarget,
        target_selector: dict[str, Any],
        schemas: dict[str, tuple[KindDefinitionRevision, dict[str, FieldDefinition]]],
    ) -> dict[str, type[Any] | FieldSymbol]:
        kind_name = str(target_selector.get("kind", ""))
        contract_symbols: dict[
            ValidationTarget, dict[str, type[Any] | FieldSymbol]
        ] = {
            ValidationTarget.RELATION: {
                "predicate": str,
                "source_binding": str,
                "target_binding": str,
                "provenance": str,
                "formal_trace_category_count": int,
            },
            ValidationTarget.WORKSPACE: {
                "state": str,
                "working_copy_count": int,
                "candidate_revision_count": int,
            },
            ValidationTarget.CONFIGURATION: {
                "closure_status": str,
                "revision_count": int,
                "relation_revision_count": int,
                "deviation_count": int,
            },
            ValidationTarget.ACTIVITY: {"evidence_count": int, "actor_uid": str},
            ValidationTarget.OPERATION: {"operation": str, "risk_class": str},
            ValidationTarget.STATE_TRANSITION: {
                "from_state": str,
                "to_state": str,
                "evidence_count": int,
                "attestation_count": int,
            },
        }
        if target_type is not ValidationTarget.REVISION:
            return dict(contract_symbols[target_type])
        if kind_name not in schemas:
            raise ValueError(f"Rule target Kind is absent from Effective Model: {kind_name}")
        symbols: dict[str, type[Any] | FieldSymbol] = {}
        for path, definition in schemas[kind_name][1].items():
            symbols[path] = (
                FieldSymbol(path, "quantity", definition.unit)
                if definition.value_type == "quantity"
                else {
                    "string": str,
                    "timestamp": str,
                    "integer": int,
                    "boolean": bool,
                    "object": dict,
                    "array": list,
                }[definition.value_type]
            )
        return symbols

    def _validate_revision_against_kind(
        self,
        revision: Revision,
        schemas: dict[str, tuple[KindDefinitionRevision, dict[str, FieldDefinition]]],
        units: UnitRegistry,
    ) -> None:
        if revision.kind not in schemas:
            raise ValueError(
                f"Candidate Kind is not defined by the Effective Model: {revision.kind}"
            )
        definitions = schemas[revision.kind][1]
        actual = {self._rule_path(item.path): item.value for item in revision.fields}
        missing = sorted(
            path for path, definition in definitions.items() if definition.required and path not in actual
        )
        unknown = sorted(set(actual) - set(definitions))
        if missing or unknown:
            raise ValueError(
                f"Candidate violates Kind schema; missing={missing}, unknown={unknown}"
            )
        for path, value in actual.items():
            definition = definitions[path]
            if not self._field_value_matches(value, definition, units):
                raise ValueError(
                    f"Candidate field {path} violates {revision.kind} schema"
                )

    def _field_value_matches(
        self, value: Any, definition: FieldDefinition, units: UnitRegistry
    ) -> bool:
        if definition.enum_values and value not in definition.enum_values:
            return False
        if definition.value_type == "quantity":
            quantity = self._quantity(value)
            if quantity is None or definition.unit is None:
                return False
            try:
                units.compare(quantity, Quantity(quantity.value, definition.unit))
            except ValueError:
                return False
            return True
        expected = {
            "string": str,
            "timestamp": str,
            "integer": int,
            "boolean": bool,
            "object": dict,
            "array": list,
        }[definition.value_type]
        if expected is int and isinstance(value, bool):
            return False
        if not isinstance(value, expected):
            return False
        if isinstance(value, list):
            if definition.minimum_items is not None and len(value) < definition.minimum_items:
                return False
            if definition.maximum_items is not None and len(value) > definition.maximum_items:
                return False
        return True

    def _active_deviation_rules(
        self,
        configuration: dict[str, Any],
        revision: Revision,
        compiled_rules: list[tuple[RuleDefinition, Any]],
        evaluation_time: datetime,
    ) -> dict[str, str]:
        rules_by_revision = {
            rule.rule_revision_uid: (rule, ast) for rule, ast in compiled_rules
        }
        revisions = {
            str(value["revision_uid"]): value
            for value in self.documents
            if value.get("resource_type") == "revision"
        }
        approvals = {
            str(value["approval_uid"]): SignedApproval.model_validate(value)
            for value in self.documents
            if value.get("resource_type") == "approval_attestation"
        }
        trust_by_key = {
            str(value["key_uid"]): TrustedActor.model_validate(value)
            for value in self.documents
            if value.get("resource_type") == "trusted_actor"
        }
        revoked = frozenset(
            str(value["approval_uid"])
            for value in self.documents
            if value.get("resource_type") == "approval_revocation"
            and datetime.fromisoformat(str(value["revoked_at"])) <= evaluation_time
        )
        effective_model_hash = str(configuration["effective_model_hash"])
        active: dict[str, str] = {}
        for deviation_uid in configuration.get("active_deviation_revision_uids", ()):
            value = revisions.get(str(deviation_uid))
            if value is None or value.get("kind") != "deviation":
                raise ValueError(f"active deviation is unavailable: {deviation_uid}")
            fields = {
                str(item["path"]): item.get("value")
                for item in value.get("fields", ())
                if isinstance(item, dict) and isinstance(item.get("path"), str)
            }
            valid_until = fields.get("/valid_until")
            if not isinstance(valid_until, str):
                raise TypeError(f"active deviation lacks expiration: {deviation_uid}")
            parsed_expiry = datetime.fromisoformat(valid_until)
            if parsed_expiry <= evaluation_time:
                raise ValueError(f"active deviation is expired: {deviation_uid}")
            if not fields.get("/compensating_control"):
                raise ValueError(
                    f"active deviation lacks a compensating control: {deviation_uid}"
                )
            if str(fields.get("/subject_uid", "")) not in {
                revision.object_uid,
                revision.revision_uid,
            }:
                continue
            rule_revision_uid = str(fields.get("/rule_revision_uid", ""))
            selected = rules_by_revision.get(rule_revision_uid)
            if selected is None or not selected[1].deviation_allowed:
                raise ValueError(
                    f"deviation does not reference an effective relaxable Rule: {deviation_uid}"
                )
            rule, _ = selected
            subject_hash = governance_subject_hash(Revision.model_validate(value))
            expected_scope: dict[str, object] = {
                "deviation_revision_uid": str(deviation_uid),
                "deviation_hash": subject_hash,
                "rule_revision_uid": rule_revision_uid,
                "subject_uid": str(fields["/subject_uid"]),
            }
            matching_approvals = tuple(
                item
                for item in approvals.values()
                if item.approval_type == "deviation"
                and item.package_hash == subject_hash
                and item.scope == expected_scope
            )
            valid_approvals: list[SignedApproval] = []
            for approval in matching_approvals:
                trust = trust_by_key.get(approval.key_uid)
                if trust is None:
                    continue
                try:
                    verify_bound_approval(
                        approval,
                        trust,
                        package_hash=subject_hash,
                        effective_model_hash=effective_model_hash,
                        approval_type="deviation",
                        scope=expected_scope,
                        allowed_roles=frozenset(
                            rule.deviation_policy.required_approval_roles
                        ),
                        revoked_approval_uids=revoked,
                        now=evaluation_time,
                    )
                except (PermissionError, ValueError):
                    continue
                valid_approvals.append(approval)
            if len(valid_approvals) != 1:
                raise PermissionError(
                    f"active deviation requires exactly one bound approval: {deviation_uid}"
                )
            active[selected[0].rule_uid] = str(deviation_uid)
        return active

    def _active_exception_rules(
        self,
        configuration: dict[str, Any],
        revision: Revision,
        compiled_rules: list[tuple[RuleDefinition, Any]],
        evaluation_time: datetime,
    ) -> frozenset[str]:
        """Resolve only cryptographically approved, exact-subject Rule exceptions."""

        rules_by_revision = {
            rule.rule_revision_uid: rule for rule, _ in compiled_rules
        }
        revisions = {
            str(value["revision_uid"]): value
            for value in self.documents
            if value.get("resource_type") == "revision"
        }
        approvals = {
            str(value["approval_uid"]): SignedApproval.model_validate(value)
            for value in self.documents
            if value.get("resource_type") == "approval_attestation"
        }
        trust_by_key = {
            str(value["key_uid"]): TrustedActor.model_validate(value)
            for value in self.documents
            if value.get("resource_type") == "trusted_actor"
        }
        revoked = frozenset(
            str(value["approval_uid"])
            for value in self.documents
            if value.get("resource_type") == "approval_revocation"
            and datetime.fromisoformat(str(value["revoked_at"])) <= evaluation_time
        )
        active: set[str] = set()
        for exception_uid in configuration.get("active_exception_revision_uids", ()):
            value = revisions.get(str(exception_uid))
            if value is None or value.get("kind") != "exception":
                raise ValueError(f"active exception is unavailable: {exception_uid}")
            fields = {
                str(item["path"]): item.get("value")
                for item in value.get("fields", ())
                if isinstance(item, dict) and isinstance(item.get("path"), str)
            }
            if str(fields.get("/subject_uid", "")) not in {
                revision.object_uid,
                revision.revision_uid,
            }:
                continue
            rule_revision_uid = str(fields.get("/rule_revision_uid", ""))
            rule = rules_by_revision.get(rule_revision_uid)
            if rule is None:
                raise ValueError(
                    f"exception does not reference an effective Rule: {exception_uid}"
                )
            policy = rule.exception_policy
            if not isinstance(policy, dict) or not bool(policy.get("allowed", False)):
                raise ValueError(f"Rule does not allow exceptions: {rule_revision_uid}")
            valid_until = fields.get("/valid_until")
            if not isinstance(valid_until, str) or datetime.fromisoformat(valid_until) <= evaluation_time:
                raise ValueError(f"active exception is expired: {exception_uid}")
            subject_hash = governance_subject_hash(Revision.model_validate(value))
            expected_scope: dict[str, object] = {
                "exception_revision_uid": str(exception_uid),
                "exception_hash": subject_hash,
                "rule_revision_uid": rule_revision_uid,
                "subject_uid": str(fields["/subject_uid"]),
            }
            raw_roles = policy.get("required_approval_roles", [])
            if not isinstance(raw_roles, list):
                raise TypeError("exception approval roles must be a list")
            roles = frozenset(str(item) for item in raw_roles)
            matching_approvals = tuple(
                item
                for item in approvals.values()
                if item.approval_type == "exception"
                and item.package_hash == subject_hash
                and item.scope == expected_scope
            )
            valid_approvals = []
            for approval in matching_approvals:
                trust = trust_by_key.get(approval.key_uid)
                if trust is None:
                    continue
                try:
                    verify_bound_approval(
                        approval,
                        trust,
                        package_hash=subject_hash,
                        effective_model_hash=str(configuration["effective_model_hash"]),
                        approval_type="exception",
                        scope=expected_scope,
                        allowed_roles=roles,
                        revoked_approval_uids=revoked,
                        now=evaluation_time,
                    )
                except (PermissionError, ValueError):
                    continue
                valid_approvals.append(approval)
            if len(valid_approvals) != 1:
                raise PermissionError(
                    f"active exception requires exactly one bound approval: {exception_uid}"
                )
            active.add(rule.rule_uid)
        return frozenset(active)

    def _conflicted_rule_uids(
        self,
        configuration: dict[str, Any],
        compiled_rules: list[tuple[RuleDefinition, Any]],
        evaluation_time: datetime,
    ) -> frozenset[str]:
        """Fail closed on normative Rule conflicts unless an exact resolution is selected."""

        selected_resolution_uids = {
            str(item) for item in configuration.get("conflict_resolution_uids", ())
        }
        approvals = tuple(
            SignedApproval.model_validate(value)
            for value in self.documents
            if value.get("resource_type") == "approval_attestation"
        )
        trust_by_key = {
            actor.key_uid: actor
            for actor in (
                TrustedActor.model_validate(value)
                for value in self.documents
                if value.get("resource_type") == "trusted_actor"
            )
        }
        revoked = frozenset(
            str(value.get("approval_uid"))
            for value in self.documents
            if value.get("resource_type") == "approval_revocation"
        )
        resolutions: set[frozenset[str]] = set()
        for value in self.documents:
            if (
                value.get("resource_type") != "immutable_record"
                or value.get("record_type") != "rule_conflict_resolution"
                or str(value.get("record_uid")) not in selected_resolution_uids
            ):
                continue
            record = ImmutableRecord.model_validate(value)
            left = record.field_value("/left_rule_revision_uid")
            right = record.field_value("/right_rule_revision_uid")
            if not isinstance(left, str) or not isinstance(right, str):
                continue
            expected_scope: dict[str, object] = {
                "resolution_record_uid": record.record_uid,
                "resolution_hash": record.content_hash,
                "left_rule_revision_uid": left,
                "right_rule_revision_uid": right,
            }
            matching = tuple(
                item
                for item in approvals
                if item.approval_type == "rule_conflict_resolution"
                and item.package_hash == record.content_hash
                and item.scope == expected_scope
            )
            if len(matching) != 1:
                continue
            approval = matching[0]
            trust = trust_by_key.get(approval.key_uid)
            if trust is None:
                continue
            try:
                verify_bound_approval(
                    approval,
                    trust,
                    package_hash=record.content_hash,
                    effective_model_hash=str(configuration.get("effective_model_hash", "")),
                    approval_type="rule_conflict_resolution",
                    scope=expected_scope,
                    allowed_roles=frozenset(("technical",)),
                    revoked_approval_uids=revoked,
                    now=evaluation_time,
                )
            except (PermissionError, ValueError):
                continue
            resolutions.add(frozenset((left, right)))
        conflicted: set[str] = set()
        for index, (left_rule, left_ast) in enumerate(compiled_rules):
            for right_rule, right_ast in compiled_rules[index + 1 :]:
                if not detect_direct_conflict(left_ast, right_ast):
                    continue
                pair = frozenset(
                    (left_rule.rule_revision_uid, right_rule.rule_revision_uid)
                )
                if pair in resolutions:
                    continue
                conflicted.update((left_rule.rule_uid, right_rule.rule_uid))
        return frozenset(conflicted)

    def _relation_values(
        self,
        evaluator: SemanticEvaluator,
        object_uid: str,
        predicate: str,
        constraints: tuple[ConstraintExpression, ...],
    ) -> tuple[int | Quantity, ...]:
        field_path = next(
            (
                item.field_path
                for item in constraints
                if item.predicate == predicate and item.field_path is not None
            ),
            None,
        )
        adjacent = evaluator._adjacent(
            object_uid, predicate=predicate, direction=Direction.OUTGOING
        )
        if field_path is None:
            return tuple(1 for _ in adjacent)
        values: list[int | Quantity] = []
        for target_uid, _ in adjacent:
            node = evaluator.nodes.get(target_uid)
            if node is None:
                continue
            field = next(
                (
                    item.value
                    for item in node.revision.fields
                    if self._rule_path(item.path) == field_path
                ),
                None,
            )
            quantity = self._quantity(field)
            if quantity is not None:
                values.append(quantity)
            elif isinstance(field, int) and not isinstance(field, bool):
                values.append(field)
        return tuple(values)

    def _aggregate_values(
        self,
        evaluator: SemanticEvaluator,
        object_uid: str,
        expression: ConstraintExpression,
    ) -> tuple[RuntimeValue, ...]:
        aggregate_operators = {
            RuleOperator.AGGREGATE_COUNT,
            RuleOperator.AGGREGATE_SUM,
            RuleOperator.AGGREGATE_MIN,
            RuleOperator.AGGREGATE_MAX,
            RuleOperator.AGGREGATE_RATIO,
            RuleOperator.AGGREGATE_ALL,
            RuleOperator.AGGREGATE_ANY,
            RuleOperator.AGGREGATE_NONE,
        }
        if expression.operator not in aggregate_operators:
            return ()
        if expression.relation_path is not None:
            targets = tuple(
                match.object_uids[-1]
                for match in evaluate_path(evaluator, object_uid, expression.relation_path).matches
            )
        elif expression.predicate is not None:
            targets = tuple(
                uid
                for uid, _ in evaluator._adjacent(
                    object_uid,
                    predicate=expression.predicate,
                    direction=expression.direction,
                )
            )
        else:
            targets = ()
        if expression.operator is RuleOperator.AGGREGATE_COUNT:
            return tuple(decode_runtime_value("1") for _ in targets)
        values: list[RuntimeValue] = []
        for target_uid in targets:
            node = evaluator.nodes.get(target_uid)
            if node is None or expression.field_path is None:
                values.append(
                    decode_runtime_value(None, kind_hint=RuntimeValueKind.UNKNOWN)
                )
                continue
            value = next(
                (
                    item.value
                    for item in node.revision.fields
                    if self._rule_path(item.path) == expression.field_path
                ),
                None,
            )
            if isinstance(value, bool):
                values.append(decode_runtime_value(value))
            elif isinstance(value, (int, str)):
                values.append(decode_runtime_value(str(value)))
            elif self._quantity(value) is not None:
                values.append(decode_runtime_value(value))
            else:
                values.append(
                    decode_runtime_value(None, kind_hint=RuntimeValueKind.UNKNOWN)
                )
        return tuple(values)

    def _evaluate_target_constraint(
        self,
        evaluator: SemanticEvaluator,
        target_uid: str,
        environment: ConstraintEnvironment,
        units: UnitRegistry,
        expression: ConstraintExpression,
    ) -> Any:
        return evaluate_constraint(
            evaluator,
            expression,
            environment.model_copy(
                update={
                    "aggregate_values": self._aggregate_values(
                        evaluator, target_uid, expression
                    )
                }
            ),
            units,
        )

    @staticmethod
    def _rule_path(path: str) -> str:
        return path.removeprefix("/").replace("/", ".")

    @staticmethod
    def _quantity(value: Any) -> Quantity | None:
        if not isinstance(value, dict) or "unit" not in value:
            return None
        try:
            raw = value.get("value", value.get("decimal"))
            if raw is None:
                return None
            return Quantity(Decimal(str(raw)), str(value["unit"]))
        except (ArithmeticError, ValueError, TypeError):
            return None

    def _reload(self) -> None:
        self.documents = [value for _, value in self.repository.documents(self.base)]

    def _rebuild_projection(self, _commit: str) -> None:
        self.repository.rebuild_projection(self.project / ".lesr" / "projection.sqlite3")

    def _recover_workspaces(self) -> None:
        for recovered in self.repository.recover_workspaces():
            state = recovered.get("working_state", {})
            if not isinstance(state, dict):
                continue
            package_value = state.get("review_package")
            records_value = state.get("review_records", ())
            if isinstance(records_value, list):
                workspace_uid = str(
                    state.get("working_state", {}).get("workspace_uid", "")
                )
                if workspace_uid:
                    self.review_records[workspace_uid] = [
                        item for item in records_value if isinstance(item, dict)
                    ]
            rebase_value = state.get("rebase_results", {})
            if isinstance(rebase_value, dict):
                workspace_uid = str(
                    state.get("working_state", {}).get("workspace_uid", "")
                )
                if workspace_uid:
                    self.rebase_results[workspace_uid] = {
                        str(uid): RebaseResult.model_validate(item)
                        for uid, item in rebase_value.items()
                        if isinstance(item, dict)
                    }
            reconciliation_value = state.get("reconciliation")
            if isinstance(reconciliation_value, dict):
                uid = str(reconciliation_value.get("workspace_uid", ""))
                if uid:
                    self.reconciliation[uid] = reconciliation_value
            if isinstance(package_value, dict):
                try:
                    package = ReviewPackage.model_validate(package_value)
                    self.reviews[package.package_uid] = package
                    evidence = state.get("review_evidence", {})
                    if isinstance(evidence, dict):
                        self.review_evidence[package.package_uid] = evidence
                    preparation_value = state.get("baseline_preparation")
                    if isinstance(preparation_value, dict):
                        self.baseline_preparations[package.package_uid] = (
                            BaselinePreparation.model_validate(preparation_value)
                        )
                except ValidationError as error:
                    raise IntegrityError(
                        f"LESR-WORKSPACE-REVIEW-STATE-INVALID: {error}"
                    ) from error
            if "working_state" not in state:
                continue
            raw = state.get("working_state", state)
            if not isinstance(raw, dict):
                continue
            try:
                workspace = Workspace.model_validate(raw)
            except ValidationError as error:
                raise IntegrityError(
                    f"LESR-WORKSPACE-REVIEW-STATE-INVALID: {raw.get('workspace_uid')}: {error}"
                ) from error
            self.workspaces[workspace.workspace_uid] = workspace
            candidate_value = state.get("candidate")
            diff_value = state.get("semantic_diff")
            checkpoint_value = state.get("workspace_checkpoint")
            package_value = state.get("review_package")
            if not all(
                isinstance(item, dict)
                for item in (candidate_value, diff_value, checkpoint_value, package_value)
            ):
                continue
            try:
                submission = Submission(
                    workspace=workspace,
                    checkpoint=WorkspaceCheckpoint.model_validate(checkpoint_value),
                    candidate=CandidateRevisionSet.model_validate(candidate_value),
                    semantic_diff=SemanticDiff.model_validate(diff_value),
                )
                package = ReviewPackage.model_validate(package_value)
            except ValidationError:
                continue
            self.submissions[workspace.workspace_uid] = submission
            self.reviews[package.package_uid] = package
            evidence = state.get("review_evidence", {})
            if isinstance(evidence, dict):
                self.review_evidence[package.package_uid] = evidence

    @staticmethod
    def _workspace_state(
        workspace: Workspace,
        *,
        submission: Submission | None = None,
        review_package: ReviewPackage | None = None,
        evidence: dict[str, Any] | None = None,
        review_records: list[dict[str, Any]] | None = None,
        rebase_results: dict[str, RebaseResult] | None = None,
    ) -> dict[str, Any]:
        value: dict[str, Any] = {
            "runtime_state_version": "1.0",
            "working_state": workspace.model_dump(mode="json"),
        }
        if submission is not None:
            value |= {
                "workspace_checkpoint": submission.checkpoint.model_dump(mode="json"),
                "candidate": submission.candidate.model_dump(mode="json"),
                "semantic_diff": submission.semantic_diff.model_dump(mode="json"),
            }
        if review_package is not None:
            value["review_package"] = review_package.model_dump(mode="json")
        if evidence is not None:
            value["review_evidence"] = evidence
        if review_records:
            value["review_records"] = review_records
        if rebase_results:
            value["rebase_results"] = {
                uid: item.model_dump(mode="json") for uid, item in rebase_results.items()
            }
        return value

    def _checkpoint_workspace(
        self,
        workspace: Workspace,
        *,
        review_package: ReviewPackage | None = None,
    ) -> None:
        submission = self.submissions.get(workspace.workspace_uid)
        package = review_package or next(
            (
                item
                for item in self.reviews.values()
                if item.workspace_uid == workspace.workspace_uid
            ),
            None,
        )
        evidence = self.review_evidence.get(package.package_uid) if package else None
        self.repository.create_checkpoint(
            workspace.workspace_uid,
            self._workspace_state(
                workspace,
                submission=submission,
                review_package=package,
                evidence=evidence,
                review_records=self.review_records.get(workspace.workspace_uid),
                rebase_results=self.rebase_results.get(workspace.workspace_uid),
            ),
            CheckpointStrategy.WORKSPACE_REF,
        )

    def _invalidate_review(self, workspace_uid: str) -> None:
        self.submissions.pop(workspace_uid, None)
        invalid_packages = [
            uid for uid, item in self.reviews.items() if item.workspace_uid == workspace_uid
        ]
        for uid in invalid_packages:
            self.reviews.pop(uid, None)
            self.review_evidence.pop(uid, None)
            self.baseline_preparations.pop(uid, None)
        self.review_records.pop(workspace_uid, None)

    def _append_review_record(
        self,
        request: WriteEnvelope,
        model: Any,
        record_type: str,
    ) -> DomainResult:
        error = self._validate_write(request, require_workspace=True, check_base=False)
        if error:
            return error
        try:
            raw = request.operation.get("record")
            if not isinstance(raw, dict):
                raise TypeError(f"{record_type} requires record")
            record = model.model_validate(raw)
            if not request.dry_run:
                self.review_records.setdefault(request.workspace_uid, []).append(
                    record.model_dump(mode="json")
                )
                self._checkpoint_workspace(self.workspaces[request.workspace_uid])
            return DomainResult({record_type: record.model_dump(mode="json")})
        except (KeyError, TypeError, ValueError, ValidationError) as error:
            return self._error(
                f"LESR-{record_type.replace('_', '-').upper()}-FAILED",
                ErrorCategory.VALIDATION,
                str(error),
                (request.workspace_uid,),
            )

    @staticmethod
    def _state_from_revision(revision: Revision) -> SemanticState:
        return SemanticState(
            object_uid=revision.object_uid,
            human_key=revision.human_key,
            kind=revision.kind,
            facets=revision.facets,
            fields=tuple((item.path, item.value) for item in revision.fields),
            fragments=tuple(
                (item.local_key, item.model_dump(mode="json")) for item in revision.fragments
            ),
        )

    @staticmethod
    def _state_from_working_copy(copy: WorkingCopy) -> SemanticState:
        return SemanticState(
            object_uid=copy.object_uid,
            human_key=copy.human_key,
            kind=copy.kind,
            facets=copy.facets,
            fields=tuple((item.path, item.value) for item in copy.draft_fields),
            fragments=tuple(
                (item.local_key, item.model_dump(mode="json"))
                for item in copy.draft_fragments
            ),
            relations=tuple(
                (item.relation_revision_uid, item.model_dump(mode="json"))
                for item in copy.relation_proposals
            ),
        )

    def _state_at_revision(self, commit: str, revision_uid: str | None) -> SemanticState | None:
        if revision_uid is None:
            return None
        value = self.repository.read_json(commit, f"canonical/revisions/{revision_uid}.json")
        return self._state_from_revision(Revision.model_validate(value)) if value else None

    def _latest_revision_for_object(self, commit: str, object_uid: str) -> Revision | None:
        revisions = [
            Revision.model_validate(value)
            for _, value in self.repository.documents(commit)
            if value.get("resource_type") == "revision" and value.get("object_uid") == object_uid
        ]
        return max(revisions, key=lambda item: item.revision_number, default=None)

    @staticmethod
    def _copy_from_state(
        copy: WorkingCopy,
        state: SemanticState,
        base_revision: Revision | None,
    ) -> WorkingCopy:
        return WorkingCopy.model_validate(
            copy.model_dump(mode="json")
            | {
                "base_revision_uid": (
                    base_revision.revision_uid if base_revision is not None else copy.base_revision_uid
                ),
                "base_revision_number": (
                    base_revision.revision_number
                    if base_revision is not None
                    else copy.base_revision_number
                ),
                "human_key": state.human_key,
                "kind": state.kind,
                "facets": state.facets,
                "draft_fields": tuple(SemanticField(path=path, value=value) for path, value in state.fields),
                "draft_fragments": tuple(
                    Fragment.model_validate(value)
                    for _, value in state.fragments
                    if isinstance(value, dict)
                ),
                "relation_proposals": tuple(
                    RelationAssertion.model_validate(value)
                    for _, value in state.relations
                    if isinstance(value, dict)
                ),
                "validation_state": ValidationState.NOT_RUN,
                "state": WorkingCopyState.EDITABLE,
                "working_state_hash": "",
            }
        )

    def _review_policy(self, configuration_uid: str, operation: str) -> ReviewPolicy:
        model = self._effective_model(configuration_uid)
        matches = [
            policy for policy in model.review_policies if policy.operation == operation
        ]
        if len(matches) != 1:
            raise ValueError(
                f"Effective Model must define exactly one {operation} review policy"
            )
        selected = matches[0]
        return ReviewPolicy(
            stages=tuple(
                StageQuorum(
                    stage=item.stage,
                    role=item.role,
                    minimum_count=item.minimum_count,
                )
                for item in selected.stages
            ),
            require_preparer_independence=selected.require_preparer_independence,
            require_comment_resolution=selected.require_comment_resolution,
        )

    def _effective_model(self, configuration_uid: str) -> EffectiveModel:
        configuration = self._configuration(configuration_uid)
        return self._effective_model_from_configuration_value(configuration)

    def _effective_model_from_configuration_value(
        self, configuration: dict[str, Any]
    ) -> EffectiveModel:
        model = self._compile_effective_model_from_configuration_value(configuration)
        if model.model_hash != configuration.get("effective_model_hash"):
            raise ValueError("Configuration Effective Model hash is stale")
        return model

    def _compile_effective_model_from_configuration_value(
        self, configuration: dict[str, Any]
    ) -> EffectiveModel:
        configuration_uid = str(configuration["configuration_uid"])
        selected_profiles = set(configuration.get("profile_revision_uids", ()))
        profiles = tuple(
            NormativeProfileRevision.model_validate(value)
            for value in self.documents
            if value.get("resource_type") == "normative_profile_revision"
            and value.get("profile_revision_uid") in selected_profiles
        )
        if {item.profile_revision_uid for item in profiles} != selected_profiles:
            raise ValueError("Configuration references unavailable Normative Profile revisions")
        definitions = tuple(
            self._definition_revision(value)
            for value in self.documents
            if value.get("resource_type")
            in {
                "facet_definition_revision",
                "kind_definition_revision",
                "relation_type_revision",
                "workflow_revision",
            }
        )
        overlays = tuple(
            TailoringOverlay.model_validate(value)
            for value in self.documents
            if value.get("resource_type") == "tailoring_overlay"
            and value.get("configuration_uid") == configuration_uid
        )
        model = EffectiveModelCompiler().compile(
            profiles,
            definitions,
            overlays=overlays,
            deviation_revision_uids=tuple(
                str(item)
                for item in configuration.get("active_deviation_revision_uids", ())
            ),
            exception_revision_uids=tuple(
                str(item)
                for item in configuration.get("active_exception_revision_uids", ())
            ),
            conflict_resolution_uids=tuple(
                str(item)
                for item in configuration.get("conflict_resolution_uids", ())
            ),
        )
        if model.conflicts:
            raise ValueError(
                "Effective Model has unresolved conflicts: "
                + ", ".join(item.code for item in model.conflicts)
            )
        return model

    def _validate_write(
        self,
        request: WriteEnvelope,
        *,
        require_workspace: bool,
        check_base: bool = True,
    ) -> DomainResult | None:
        if check_base and request.expected_base != self.base:
            return self._error(
                "LESR-BASE-CONFLICT",
                ErrorCategory.CONFLICT,
                "expected base is stale",
                (request.expected_base, self.base),
                retryable=True,
            )
        if require_workspace and request.workspace_uid not in self.workspaces:
            return self._error(
                "LESR-WORKSPACE-NOT-FOUND",
                ErrorCategory.NOT_FOUND,
                "workspace does not exist",
                (request.workspace_uid,),
                suggested="workspace.open",
            )
        if not all(
            (
                request.expected_base,
                request.idempotency_key,
                request.actor,
                request.delegation_uid,
            )
        ):
            return self._error(
                "LESR-WRITE-ENVELOPE-INVALID",
                ErrorCategory.VALIDATION,
                "Expected Base, Idempotency Key, Actor and Delegation are required",
            )
        return None

    @staticmethod
    def _evaluation_time(operation: dict[str, Any]) -> datetime:
        raw = operation.get("evaluation_time")
        if not isinstance(raw, str):
            raise TypeError("high-risk operation requires explicit evaluation_time")
        return LocalRuntimeService._parse_evaluation_time(raw)

    @staticmethod
    def _parse_evaluation_time(raw: str) -> datetime:
        value = datetime.fromisoformat(raw)
        if value.tzinfo is None:
            raise ValueError("evaluation_time must include UTC offset")
        return value.astimezone(UTC)

    @staticmethod
    def _records(operation: dict[str, Any], name: str) -> tuple[dict[str, Any], ...]:
        raw = operation.get(name, ())
        if not isinstance(raw, (list, tuple)) or not all(isinstance(item, dict) for item in raw):
            raise ValueError(f"{name} must be an array of records")
        return tuple(raw)

    @staticmethod
    def _relation_type_uid(value: dict[str, Any]) -> str:
        uid = value.get("relation_type_revision_uid")
        if not isinstance(uid, str):
            raise TypeError("Relation Assertion must bind exact Relation Type Revision")
        return uid

    @staticmethod
    def _definition_revision(
        value: dict[str, Any],
    ) -> (
        FacetDefinitionRevision
        | KindDefinitionRevision
        | RelationTypeRevision
        | WorkflowRevision
    ):
        resource_type = value.get("resource_type")
        if resource_type == "facet_definition_revision":
            return FacetDefinitionRevision.model_validate(value)
        if resource_type == "kind_definition_revision":
            return KindDefinitionRevision.model_validate(value)
        if resource_type == "relation_type_revision":
            return RelationTypeRevision.model_validate(value)
        if resource_type == "workflow_revision":
            return WorkflowRevision.model_validate(value)
        raise TypeError(f"unsupported definition revision: {resource_type}")

    @staticmethod
    def _identifiers(value: dict[str, Any]) -> set[str]:
        # Resolve only a resource's own identity.  Reference UIDs (actor,
        # profile, configuration, endpoint, etc.) must never make the
        # containing document appear to be that referenced resource.
        primary_keys = {
            "logical_object": ("object_uid",),
            "revision": ("revision_uid",),
            "relation_assertion": ("relation_revision_uid",),
            "configuration_snapshot": ("configuration_uid",),
            "normative_profile_revision": ("profile_revision_uid",),
            "rule_definition_revision": ("rule_revision_uid",),
            "kind_definition_revision": ("kind_revision_uid",),
            "facet_definition_revision": ("facet_revision_uid",),
            "relation_type_revision": ("relation_type_revision_uid",),
            "workflow_revision": ("workflow_revision_uid",),
            "mapping_pack_revision": ("mapping_pack_revision_uid",),
            "tailoring_overlay_revision": ("overlay_revision_uid",),
            "trusted_actor": ("key_uid",),
            "delegation_grant": ("delegation_uid",),
            "review_package": ("package_uid",),
            "baseline_manifest": ("baseline_uid",),
        }.get(str(value.get("resource_type")), ())
        identifiers = {
            str(value[key]) for key in primary_keys if isinstance(value.get(key), str)
        }
        if isinstance(value.get("human_key"), str):
            identifiers.add(str(value["human_key"]))
        for alias in value.get("aliases", ()):
            if isinstance(alias, dict) and isinstance(alias.get("value"), str):
                identifiers.add(str(alias["value"]))
        return identifiers

    @staticmethod
    def _primary_uid(value: dict[str, Any]) -> str:
        for key in (
            "revision_uid",
            "entity_uid",
            "relation_revision_uid",
            "record_uid",
            "configuration_uid",
            "profile_revision_uid",
        ):
            if isinstance(value.get(key), str):
                return str(value[key])
        return semantic_hash(value)

    def _removed(self, capability: str) -> DomainResult:
        return self._error(
            "LESR-0.5-CAPABILITY-REMOVED",
            ErrorCategory.NOT_FOUND,
            f"{capability} is not part of the 1.0 capability contract",
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
                code=code,
                category=category,
                message=message,
                affected_resources=resources,
                retryable=retryable,
                suggested_capability=suggested,
            )
        )
