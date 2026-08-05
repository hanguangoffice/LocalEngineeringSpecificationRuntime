"""Integrated LESR 1.0 local runtime application service."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from lesr.adapters.git import (
    ApprovalError,
    CheckpointStrategy,
    ConcurrencyConflict,
    GitCanonicalRepository,
    IdempotencyConflict,
    IntegrityError,
)
from lesr.adapters.operations import TaskStore
from lesr.application.contracts import (
    CapabilityDescriptor,
    CapabilityGroup,
    DomainErrorContract,
    DomainResult,
    ErrorCategory,
    WriteEnvelope,
)
from lesr.domain.approval import SignedApproval, TrustedActor
from lesr.domain.catalog import CAPABILITIES
from lesr.domain.evaluation import (
    Direction,
    GraphNode,
    GraphRelation,
    GraphSnapshot,
    SemanticEvaluator,
    analyze_impact,
    plan_context,
)
from lesr.domain.model import RelationTypeRevision
from lesr.domain.review import (
    ApprovalRevocation,
    CommentResolution,
    ConditionSatisfaction,
    GovernanceEvaluator,
    ReviewComment,
    ReviewPackage,
    ReviewPolicy,
    StageQuorum,
)
from lesr.domain.rules import (
    EnforcementEffect,
    EvaluationEnvironment,
    FieldSymbol,
    Quantity,
    RuleCompiler,
    RuleDefinition,
    RuleOutcome,
    UnitDefinition,
    UnitRegistry,
    ValueCell,
    evaluate_rule,
)
from lesr.domain.semantic import (
    RelationAssertion,
    Revision,
    semantic_hash,
    uuid7_candidate,
)
from lesr.domain.workspace import (
    EditOperation,
    WorkingCopy,
    Workspace,
    WorkspaceEngine,
)


class LocalRuntimeService:
    """The production facade; all adapters delegate here and never to the 0.5 queue."""

    def __init__(self, project: Path) -> None:
        self.project = project.resolve()
        self.repository = GitCanonicalRepository(self.project)
        self.base = self.repository.initialize()
        self.task_store = TaskStore(self.project)
        self.workspaces: dict[str, Workspace] = {}
        self.submissions: dict[str, Any] = {}
        self.reviews: dict[str, ReviewPackage] = {}
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
        }
        for capability in CAPABILITIES:
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
                else CapabilityGroup.COMPLIANCE
            )
            groups[group].append(capability.name)
        return tuple(
            CapabilityDescriptor(group, tuple(sorted(names)), "1.0.0")
            for group, names in groups.items()
            if names
        )

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
        values = self.documents
        if kind:
            values = [item for item in values if item.get("kind") == kind]
        if text:
            needle = text.casefold()
            values = [item for item in values if needle in str(item).casefold()]
        values.sort(key=self._primary_uid)
        items = values[offset : offset + page_size]
        next_cursor = str(offset + page_size) if offset + page_size < len(values) else None
        return DomainResult({"items": items, "next_cursor": next_cursor, "total": len(values)})

    def traverse(self, start_uid: str, predicate: str | None, max_depth: int) -> DomainResult:
        del predicate, max_depth
        return self._error(
            "LESR-CONFIGURATION-REQUIRED",
            ErrorCategory.INDETERMINATE,
            "traversal requires an explicit Configuration and Evaluation Time",
            (start_uid,),
            suggested="context.plan",
        )

    def impact(self, start_uid: str, max_depth: int) -> DomainResult:
        del max_depth
        return self._error(
            "LESR-CONFIGURATION-REQUIRED",
            ErrorCategory.INDETERMINATE,
            "impact requires an explicit Configuration and Evaluation Time",
            (start_uid,),
            suggested="context.plan",
        )

    def build_context(
        self,
        task_type: str,
        target_uids: tuple[str, ...],
        token_budget: int,
        configuration_uid: str,
        actor: str,
    ) -> DomainResult:
        del task_type, actor
        try:
            evaluator = self._evaluator(configuration_uid, datetime.now(UTC))
            context = plan_context(
                evaluator,
                target_uids,
                (),
                token_limit=max(1, token_budget // 256),
            )
            return DomainResult(context.model_dump(mode="json"))
        except (KeyError, TypeError, ValueError, ValidationError) as error:
            return self._error(
                "LESR-CONTEXT-INDETERMINATE",
                ErrorCategory.INDETERMINATE,
                str(error),
                target_uids,
                suggested="resolve",
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
                updated = WorkspaceEngine.edit(workspace, operation)
            if not request.dry_run:
                self.workspaces[request.workspace_uid] = updated
                self.repository.create_checkpoint(
                    request.workspace_uid,
                    {"working_state": updated.model_dump(mode="json")},
                    CheckpointStrategy.WORKSPACE_REF,
                )
            return DomainResult(updated.model_dump(mode="json"))
        except (KeyError, TypeError, ValueError, ValidationError) as error:
            return self._error(
                "LESR-WORKSPACE-EDIT-INVALID",
                ErrorCategory.VALIDATION,
                str(error),
                (request.workspace_uid,),
                suggested="workspace.inspect",
            )

    def prepare_review(self, request: WriteEnvelope) -> DomainResult:
        error = self._validate_write(request, require_workspace=True)
        if error:
            return error
        try:
            evaluation_time = self._evaluation_time(request.operation)
            submission = WorkspaceEngine.submit(
                self.workspaces[request.workspace_uid],
                checkpoint_uid=uuid7_candidate(),
                actor_uid=request.actor,
                submitted_at=evaluation_time,
            )
            evaluator = self._evaluator(
                submission.workspace.configuration_uid,
                evaluation_time,
                submission=submission,
            )
            context = plan_context(
                evaluator,
                (submission.candidate.revisions[0].object_uid,),
                (),
                token_limit=500,
            )
            impact = analyze_impact(
                evaluator,
                tuple(item.object_uid for item in submission.candidate.revisions),
                maximum_depth=int(request.operation.get("maximum_depth", 3)),
            )
            validation = self._validate_submission(submission, evaluator)
            policy = ReviewPolicy(
                stages=(
                    StageQuorum(
                        stage=str(request.operation.get("review_stage", "review")),
                        role=str(request.operation.get("required_role", "technical")),
                        minimum_count=int(request.operation.get("minimum_count", 1)),
                    ),
                )
            )
            package = ReviewPackage(
                workspace_uid=request.workspace_uid,
                base_commit=submission.workspace.base_commit,
                configuration_uid=submission.workspace.configuration_uid,
                candidate_hash=submission.candidate.candidate_hash,
                candidate_scope=tuple(item.object_uid for item in submission.candidate.revisions),
                semantic_diff_hash=submission.semantic_diff.diff_hash,
                graph_snapshot_hash=evaluator.snapshot.snapshot_hash,
                context_bundle_hash=context.bundle_hash,
                impact_report_hash=impact.report_hash,
                validation_hash=str(validation["validation_hash"]),
                finding_hashes=tuple(str(item) for item in validation["finding_hashes"]),
                comment_hashes=(),
                review_policy=policy,
                effective_model_hash=submission.workspace.effective_model_hash,
                prepared_by_actor_uid=request.actor,
                created_at=evaluation_time,
            )
            if not request.dry_run:
                self.workspaces[request.workspace_uid] = submission.workspace
                self.submissions[request.workspace_uid] = submission
                self.reviews[package.package_uid] = package
                self.repository.create_checkpoint(
                    request.workspace_uid,
                    {
                        "working_state": submission.workspace.model_dump(mode="json"),
                        "candidate": submission.candidate.model_dump(mode="json"),
                        "semantic_diff": submission.semantic_diff.model_dump(mode="json"),
                        "review_package": package.model_dump(mode="json"),
                    },
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
                }
            )
        except (KeyError, TypeError, ValueError, ValidationError) as error:
            return self._error(
                "LESR-REVIEW-PREPARATION-FAILED",
                ErrorCategory.INDETERMINATE,
                str(error),
                (request.workspace_uid,),
                suggested="workspace.validate",
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
            comments = tuple(
                ReviewComment.model_validate(item)
                for item in self.documents
                if item.get("resource_type") == "review_comment"
            )
            resolutions = tuple(
                CommentResolution.model_validate(item)
                for item in self.documents
                if item.get("resource_type") == "comment_resolution"
            )
            satisfactions = tuple(
                ConditionSatisfaction.model_validate(item)
                for item in self._records(request.operation, "condition_satisfactions")
            )
            revocations = tuple(
                ApprovalRevocation.model_validate(item)
                for item in self.documents
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
                approvals=approvals,
                trust=trust,
                comments=comments,
                resolutions=resolutions,
                satisfactions=satisfactions,
                revocations=revocations,
                evaluation_time=self._evaluation_time(request.operation),
                actor_uid=request.actor,
                delegation_uid=request.delegation_uid,
                idempotency_key=request.idempotency_key,
                validation_recalculator=lambda: str(
                    self._validate_submission(
                        submission,
                        self._evaluator(
                            submission.workspace.configuration_uid,
                            self._evaluation_time(request.operation),
                            submission=submission,
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
                suggested="workspace.rebase" if isinstance(error, ConcurrencyConflict) else None,
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
        return self.task_status(task_uid)

    def bootstrap_root_owner(self, *_args: Any, **_kwargs: Any) -> DomainResult:
        return self._removed("bootstrap_root_owner")

    def initialize_configuration(self, *_args: Any, **_kwargs: Any) -> DomainResult:
        return self._removed("initialize_configuration")

    def _evaluator(
        self,
        configuration_uid: str,
        evaluation_time: datetime,
        *,
        submission: Any | None = None,
    ) -> SemanticEvaluator:
        configuration = self._configuration(configuration_uid)
        nodes = {
            item.object_uid: GraphNode(revision=item, lifecycle_state="approved")
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
                lifecycle_state="active",
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
                    revision=revision, lifecycle_state="draft", source="candidate"
                )
            relations.extend(
                GraphRelation(
                    assertion=item,
                    relation_type_revision_uid=self._relation_type_uid(
                        item.model_dump(mode="json")
                    ),
                    lifecycle_state="draft",
                    source="candidate",
                )
                for item in submission.candidate.relation_revisions
            )
        relation_types = tuple(
            RelationTypeRevision.model_validate(value)
            for value in self.documents
            if value.get("resource_type") == "relation_type_revision"
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

    def _configuration(self, configuration_uid: str) -> dict[str, Any]:
        return next(
            item
            for item in self.documents
            if item.get("resource_type") == "configuration_snapshot"
            and item.get("configuration_uid") == configuration_uid
        )

    def _validate_submission(self, submission: Any, evaluator: SemanticEvaluator) -> dict[str, Any]:
        """Compile and evaluate the exact Configuration rule set against one snapshot."""

        configuration = self._configuration(submission.workspace.configuration_uid)
        selected_profiles = set(configuration.get("profile_revision_uids", ()))
        selected_rule_uids: set[str] = set()
        for value in self.documents:
            profile_uid = value.get("profile_revision_uid")
            if profile_uid in selected_profiles:
                selected_rule_uids.update(str(uid) for uid in value.get("rule_revision_uids", ()))
        rule_values = [
            value
            for value in self.documents
            if value.get("resource_type") == "rule_definition_revision"
            and value.get("rule_revision_uid") in selected_rule_uids
        ]
        symbols: dict[str, type[Any] | FieldSymbol] = {}
        for revision in submission.candidate.revisions:
            for field in revision.fields:
                path = field.path.removeprefix("/").replace("/", ".")
                quantity = self._quantity(field.value)
                if quantity is not None:
                    symbols[path] = FieldSymbol(path, "quantity", quantity.unit)
                else:
                    symbols[path] = type(field.value)
        units = UnitRegistry(
            (
                UnitDefinition("s", "time", Decimal(1)),
                UnitDefinition("ms", "time", Decimal("0.001")),
                UnitDefinition("us", "time", Decimal("0.000001")),
                UnitDefinition("m", "length", Decimal(1)),
                UnitDefinition("mm", "length", Decimal("0.001")),
                UnitDefinition("V", "voltage", Decimal(1)),
            )
        )
        compiler = RuleCompiler(symbols, units)
        findings: list[dict[str, Any]] = []
        for raw_rule in sorted(rule_values, key=lambda item: str(item["rule_revision_uid"])):
            rule = RuleDefinition.model_validate(raw_rule)
            compiled = compiler.compile(rule)
            if not compiled.passed or compiled.ast is None:
                findings.append(
                    {
                        "rule_revision_uid": rule.rule_revision_uid,
                        "subject_uid": submission.workspace.workspace_uid,
                        "outcome": RuleOutcome.EVALUATOR_ERROR,
                        "enforcement": EnforcementEffect.BLOCK_OPERATION,
                        "explanation": [item.code for item in compiled.diagnostics],
                    }
                )
                continue
            predicates = {
                str(predicate)
                for constraint in compiled.ast.constraints
                if (predicate := getattr(constraint, "predicate", None)) is not None
            }
            for revision in submission.candidate.revisions:
                relation_counts = {
                    predicate: evaluator.relation_count(
                        revision.object_uid,
                        predicate=predicate,
                        direction=Direction.OUTGOING,
                    )
                    for predicate in predicates
                }
                fields = {
                    field.path.removeprefix("/").replace("/", "."): ValueCell.present(
                        self._quantity(field.value) or field.value
                    )
                    for field in revision.fields
                }
                evaluated = evaluate_rule(
                    compiled.ast,
                    EvaluationEnvironment(
                        target_kind=revision.kind,
                        fields=fields,
                        relation_counts=relation_counts,
                        operation="apply_candidate",
                        active_deviation_rule_uids=frozenset(
                            str(uid)
                            for uid in configuration.get("active_deviation_rule_uids", ())
                        ),
                    ),
                    units,
                )
                if evaluated.outcome not in {RuleOutcome.PASS, RuleOutcome.NOT_APPLICABLE}:
                    findings.append(
                        {
                            "rule_revision_uid": rule.rule_revision_uid,
                            "subject_uid": revision.revision_uid,
                            "outcome": evaluated.outcome,
                            "enforcement": evaluated.enforcement,
                            "explanation": evaluated.constraint.reason
                            if evaluated.constraint is not None
                            else evaluated.applicability.reason,
                        }
                    )
        serialized = [
            {
                key: value.value if hasattr(value, "value") else value
                for key, value in finding.items()
            }
            for finding in findings
        ]
        finding_hashes = tuple(semantic_hash(item) for item in serialized)
        outcome = "pass" if not serialized else "indeterminate" if all(
            item["outcome"] == RuleOutcome.INDETERMINATE.value for item in serialized
        ) else "fail"
        validation_hash = semantic_hash(
            {
                "snapshot_hash": evaluator.snapshot.snapshot_hash,
                "candidate_hash": submission.candidate.candidate_hash,
                "rule_revision_uids": tuple(sorted(selected_rule_uids)),
                "finding_hashes": finding_hashes,
                "outcome": outcome,
            }
        )
        return {
            "snapshot_hash": evaluator.snapshot.snapshot_hash,
            "candidate_hash": submission.candidate.candidate_hash,
            "outcome": outcome,
            "findings": serialized,
            "finding_hashes": finding_hashes,
            "validation_hash": validation_hash,
        }

    @staticmethod
    def _quantity(value: Any) -> Quantity | None:
        if not isinstance(value, dict) or set(value) != {"value", "unit"}:
            return None
        try:
            return Quantity(Decimal(str(value["value"])), str(value["unit"]))
        except (ArithmeticError, ValueError):
            return None

    def _reload(self) -> None:
        self.documents = [value for _, value in self.repository.documents(self.base)]

    def _rebuild_projection(self, _commit: str) -> None:
        self.repository.rebuild_projection(self.project / ".lesr" / "projection.sqlite3")

    def _recover_workspaces(self) -> None:
        for recovered in self.repository.recover_workspaces():
            raw = recovered.get("working_state", {})
            if isinstance(raw, dict) and isinstance(raw.get("working_state"), dict):
                raw = raw["working_state"]
            if not isinstance(raw, dict):
                continue
            try:
                workspace = Workspace.model_validate(raw)
            except ValidationError:
                continue
            self.workspaces[workspace.workspace_uid] = workspace

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
                suggested="workspace.rebase",
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
    def _identifiers(value: dict[str, Any]) -> set[str]:
        identifiers = {
            str(item)
            for key, item in value.items()
            if key.endswith("_uid") and isinstance(item, str)
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
