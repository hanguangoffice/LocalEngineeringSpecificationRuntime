"""Immutable graph snapshot and pure LESR 1.0 semantic evaluation."""

from __future__ import annotations

import re
from collections import deque
from datetime import datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Literal, cast

from pydantic import Field, model_validator

from lesr.domain.model import RelationTypeRevision, formal_provenance_allowed
from lesr.domain.semantic import (
    BindingMode,
    FrozenModel,
    JsonValue,
    RelationAssertion,
    Revision,
    document_hash,
    uuid7_candidate,
)


class TruthValue(StrEnum):
    TRUE = "TRUE"
    FALSE = "FALSE"
    INDETERMINATE = "INDETERMINATE"


class CyclePolicy(StrEnum):
    FORBID = "forbid"
    SIMPLE_PATH = "simple_path"
    ALLOW_BOUNDED = "allow_bounded"


class Direction(StrEnum):
    OUTGOING = "outgoing"
    INCOMING = "incoming"


class GraphNode(FrozenModel):
    revision: Revision
    lifecycle_state: str
    source: Literal["canonical", "candidate"] = "canonical"


class GraphRelation(FrozenModel):
    assertion: RelationAssertion
    relation_type_revision_uid: str
    lifecycle_state: str
    source: Literal["canonical", "candidate"] = "canonical"


class GraphSnapshot(FrozenModel):
    schema_version: Literal["1.0"] = "1.0"
    resource_type: Literal["graph_snapshot"] = "graph_snapshot"
    snapshot_uid: str = Field(default_factory=uuid7_candidate)
    configuration_uid: str
    canonical_commit: str
    effective_model_hash: str
    workspace_uid: str | None = None
    checkpoint_uid: str | None = None
    evaluation_time: datetime
    nodes: tuple[GraphNode, ...]
    relations: tuple[GraphRelation, ...]
    candidate_overlay_hash: str | None = None
    unresolved_external_endpoints: tuple[str, ...] = ()
    snapshot_hash: str = ""

    @model_validator(mode="after")
    def validate_and_hash(self) -> GraphSnapshot:
        object_uids = [item.revision.object_uid for item in self.nodes]
        revision_uids = [item.revision.revision_uid for item in self.nodes]
        relation_uids = [item.assertion.relation_revision_uid for item in self.relations]
        if len(object_uids) != len(set(object_uids)):
            raise ValueError("Graph Snapshot selects more than one Revision per object")
        if len(revision_uids) != len(set(revision_uids)):
            raise ValueError("Graph Snapshot revision UIDs must be unique")
        if len(relation_uids) != len(set(relation_uids)):
            raise ValueError("Graph Snapshot relation revisions must be unique")
        if (self.workspace_uid is None) != (self.checkpoint_uid is None):
            raise ValueError("workspace and checkpoint must be fixed together")
        if (
            any(item.source == "candidate" for item in self.nodes)
            or any(item.source == "candidate" for item in self.relations)
        ) and (self.workspace_uid is None or self.candidate_overlay_hash is None):
            raise ValueError("candidate overlay requires workspace, checkpoint and overlay hash")
        declared_unresolved = set(self.unresolved_external_endpoints)
        for relation in self.relations:
            for endpoint in (relation.assertion.source, relation.assertion.target):
                if endpoint.binding is not BindingMode.EXTERNAL:
                    continue
                external_key = (
                    f"{endpoint.system}:{endpoint.namespace}:{endpoint.external_id}"
                    f"@{endpoint.external_revision or 'unknown'}"
                )
                if endpoint.source_hash is None and external_key not in declared_unresolved:
                    raise ValueError(
                        "external endpoint must be a pinned imported snapshot or declared unresolved"
                    )
        expected = document_hash(self.model_dump(mode="json"), "snapshot_hash")
        if self.snapshot_hash and self.snapshot_hash != expected:
            raise ValueError("snapshot_hash is invalid")
        object.__setattr__(self, "snapshot_hash", expected)
        return self

    @property
    def selected_revision_uids(self) -> tuple[str, ...]:
        return tuple(sorted(item.revision.revision_uid for item in self.nodes))

    @property
    def relation_revision_uids(self) -> tuple[str, ...]:
        return tuple(sorted(item.assertion.relation_revision_uid for item in self.relations))


class FormalTraceDecision(FrozenModel):
    granted: bool
    reasons: tuple[str, ...]


class SemanticEvaluator:
    """Pure evaluator shared by service reads and the transaction boundary."""

    def __init__(
        self,
        snapshot: GraphSnapshot,
        relation_types: tuple[RelationTypeRevision, ...],
    ) -> None:
        self.snapshot = snapshot
        self.nodes = {item.revision.object_uid: item for item in snapshot.nodes}
        self.relation_types = {item.revision_uid: item for item in relation_types}

    def formal_trace_credit(
        self,
        relation: GraphRelation,
        category: str,
    ) -> FormalTraceDecision:
        assertion = relation.assertion
        relation_type = self.relation_types.get(relation.relation_type_revision_uid)
        reasons: list[str] = []
        if relation_type is None:
            reasons.append("RELATION_TYPE_UNRESOLVED")
            return FormalTraceDecision(granted=False, reasons=tuple(reasons))
        if (
            assertion.predicate != relation_type.predicate
            or assertion.core_role != relation_type.core_role
        ):
            reasons.append("RELATION_TYPE_MISMATCH")
        if (
            assertion.source.binding is BindingMode.FRAGMENT
            or assertion.target.binding is BindingMode.FRAGMENT
        ):
            reasons.append("FRAGMENT_BINDING")
        if (
            assertion.source.binding is BindingMode.EXTERNAL
            or assertion.target.binding is BindingMode.EXTERNAL
        ):
            reasons.append("EXTERNAL_NOT_PINNED_LOCAL_SNAPSHOT")
        if assertion.source.binding not in relation_type.allowed_bindings:
            reasons.append("SOURCE_BINDING_NOT_ALLOWED")
        if assertion.target.binding not in relation_type.allowed_bindings:
            reasons.append("TARGET_BINDING_NOT_ALLOWED")
        if not formal_provenance_allowed(assertion.provenance_kind):
            reasons.append("PROVENANCE_NOT_FORMAL")
        if relation.lifecycle_state.casefold() == "retired":
            reasons.append("RELATION_RETIRED")
        source = self.nodes.get(assertion.source.object_uid or "")
        target = self.nodes.get(assertion.target.object_uid or "")
        if source is None or target is None:
            reasons.append("ENDPOINT_UNRESOLVED")
        else:
            if source.lifecycle_state.casefold() == "retired":
                reasons.append("SOURCE_RETIRED")
            if target.lifecycle_state.casefold() == "retired":
                reasons.append("TARGET_RETIRED")
            if not self._matches_endpoint(source.revision, relation_type.source_kind_or_facet):
                reasons.append("SOURCE_KIND_OR_FACET_MISMATCH")
            if not self._matches_endpoint(target.revision, relation_type.target_kind_or_facet):
                reasons.append("TARGET_KIND_OR_FACET_MISMATCH")
        if category not in relation_type.formal_trace_categories:
            reasons.append("CATEGORY_NOT_GRANTED_BY_TYPE")
        if category not in assertion.formal_trace_categories:
            reasons.append("CATEGORY_NOT_ASSERTED")
        return FormalTraceDecision(granted=not reasons, reasons=tuple(reasons))

    @staticmethod
    def _matches_endpoint(revision: Revision, allowed: tuple[str, ...]) -> bool:
        return revision.kind in allowed or bool(set(revision.facets) & set(allowed))

    def relation_count(
        self,
        object_uid: str,
        *,
        predicate: str,
        direction: Direction,
        binding: BindingMode | None = None,
        lifecycle_state: str | None = None,
        formal_trace_category: str | None = None,
    ) -> int:
        return len(
            self._adjacent(
                object_uid,
                predicate=predicate,
                direction=direction,
                binding=binding,
                lifecycle_state=lifecycle_state,
                formal_trace_category=formal_trace_category,
            )
        )

    def _adjacent(
        self,
        object_uid: str,
        *,
        predicate: str | None,
        direction: Direction,
        binding: BindingMode | None = None,
        lifecycle_state: str | None = None,
        formal_trace_category: str | None = None,
    ) -> tuple[tuple[str, GraphRelation], ...]:
        adjacent: list[tuple[str, GraphRelation]] = []
        for relation in self.snapshot.relations:
            assertion = relation.assertion
            endpoint = assertion.source if direction is Direction.OUTGOING else assertion.target
            other = assertion.target if direction is Direction.OUTGOING else assertion.source
            if endpoint.object_uid != object_uid or other.object_uid is None:
                continue
            if predicate is not None and assertion.predicate != predicate:
                continue
            if binding is not None and other.binding is not binding:
                continue
            if lifecycle_state is not None and relation.lifecycle_state != lifecycle_state:
                continue
            if (
                formal_trace_category is not None
                and not self.formal_trace_credit(relation, formal_trace_category).granted
            ):
                continue
            adjacent.append((other.object_uid, relation))
        return tuple(adjacent)


class RelationPathStep(FrozenModel):
    predicates: tuple[str, ...]
    direction: Direction
    minimum_repeat: int = Field(default=1, ge=0, le=16)
    maximum_repeat: int = Field(default=1, ge=1, le=16)
    endpoint_kind_or_facet: tuple[str, ...] = ()
    bindings: tuple[BindingMode, ...] = ()
    formal_trace_category: str | None = None

    @model_validator(mode="after")
    def repeat_bounds(self) -> RelationPathStep:
        if self.minimum_repeat > self.maximum_repeat:
            raise ValueError("path repeat minimum exceeds maximum")
        if not self.predicates:
            raise ValueError("path step needs at least one predicate alternative")
        return self


class RelationPath(FrozenModel):
    steps: tuple[RelationPathStep, ...]
    maximum_depth: int = Field(ge=1, le=16)
    cycle_policy: CyclePolicy = CyclePolicy.SIMPLE_PATH


class PathMatch(FrozenModel):
    object_uids: tuple[str, ...]
    relation_revision_uids: tuple[str, ...]


class PathResult(FrozenModel):
    matches: tuple[PathMatch, ...]
    truncated: bool


def evaluate_path(
    evaluator: SemanticEvaluator,
    start_uid: str,
    path: RelationPath,
) -> PathResult:
    frontier: tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...] = (
        (start_uid, (start_uid,), ()),
    )
    truncated = False
    for step in path.steps:
        produced: list[tuple[str, tuple[str, ...], tuple[str, ...]]] = []
        current = list(frontier)
        if step.minimum_repeat == 0:
            produced.extend(current)
        for repeat in range(1, step.maximum_repeat + 1):
            next_frontier: list[tuple[str, tuple[str, ...], tuple[str, ...]]] = []
            for current_uid, object_path, relation_path in current:
                if len(relation_path) >= path.maximum_depth:
                    truncated = True
                    continue
                for predicate in step.predicates:
                    for other_uid, relation in evaluator._adjacent(
                        current_uid,
                        predicate=predicate,
                        direction=step.direction,
                        formal_trace_category=step.formal_trace_category,
                    ):
                        other = evaluator.nodes.get(other_uid)
                        if other is None:
                            continue
                        if step.bindings:
                            endpoint = (
                                relation.assertion.target
                                if step.direction is Direction.OUTGOING
                                else relation.assertion.source
                            )
                            if endpoint.binding not in step.bindings:
                                continue
                        if step.endpoint_kind_or_facet and not evaluator._matches_endpoint(
                            other.revision, step.endpoint_kind_or_facet
                        ):
                            continue
                        if other_uid in object_path and path.cycle_policy in {
                            CyclePolicy.FORBID,
                            CyclePolicy.SIMPLE_PATH,
                        }:
                            if path.cycle_policy is CyclePolicy.FORBID:
                                truncated = True
                            continue
                        next_frontier.append(
                            (
                                other_uid,
                                object_path + (other_uid,),
                                relation_path + (relation.assertion.relation_revision_uid,),
                            )
                        )
            current = next_frontier
            if repeat >= step.minimum_repeat:
                produced.extend(current)
        frontier = tuple(produced)
    matches = tuple(
        PathMatch(object_uids=objects, relation_revision_uids=relations)
        for _, objects, relations in sorted(frontier, key=lambda item: (item[1], item[2]))
    )
    return PathResult(matches=matches, truncated=truncated)


class ValidationTarget(StrEnum):
    REVISION = "revision"
    RELATION = "relation"
    WORKSPACE = "workspace"
    CONFIGURATION = "configuration"
    ACTIVITY = "activity"
    OPERATION = "operation"
    STATE_TRANSITION = "state_transition"


class RuleOperator(StrEnum):
    FIELD_TYPE = "field_type"
    FIELD_FORBIDDEN = "field_forbidden"
    FIELD_ENUM = "field_enum"
    FIELD_PATTERN = "field_pattern"
    FIELD_RANGE = "field_range"
    FIELD_TOLERANCE = "field_tolerance"
    SET = "set"
    UNIQUE = "unique"
    RELATION_CARDINALITY = "relation_cardinality"
    RELATION_DIRECTION = "relation_direction"
    RELATION_ENDPOINT = "relation_endpoint"
    RELATION_BINDING = "relation_binding"
    RELATION_STATE = "relation_state"
    FORMAL_TRACE = "formal_trace"
    GRAPH_PATH = "graph_path"
    LIFECYCLE_TRANSITION = "lifecycle_transition"
    PROCESS_EVIDENCE = "process_evidence"
    TEMPORAL_FRESHNESS = "temporal_freshness"
    AGGREGATE_COUNT = "aggregate_count"
    AGGREGATE_SUM = "aggregate_sum"
    AGGREGATE_MIN = "aggregate_min"
    AGGREGATE_MAX = "aggregate_max"
    AGGREGATE_RATIO = "aggregate_ratio"
    AGGREGATE_ALL = "aggregate_all"
    AGGREGATE_ANY = "aggregate_any"
    AGGREGATE_NONE = "aggregate_none"
    EXTERNAL_OBSERVATION = "external_observation"
    HUMAN_ATTESTATION = "human_attestation"
    ADVISORY_AI_OBSERVATION = "advisory_ai_observation"


class ConstraintResult(FrozenModel):
    truth: TruthValue
    observed: JsonValue = None
    explanation: str


class ConstraintExpression(FrozenModel):
    operator: RuleOperator
    field_path: str | None = None
    expected: JsonValue = None
    minimum: str | None = None
    maximum: str | None = None
    tolerance: str | None = None
    predicate: str | None = None
    direction: Direction = Direction.OUTGOING
    binding: BindingMode | None = None
    lifecycle_state: str | None = None
    formal_trace_category: str | None = None
    relation_path: RelationPath | None = None
    evidence_kind: str | None = None
    observation_key: str | None = None
    maximum_age_seconds: int | None = Field(default=None, ge=0)


class ConstraintEnvironment(FrozenModel):
    target_uid: str
    fields: tuple[tuple[str, JsonValue], ...] = ()
    aggregate_values: tuple[str | bool | None, ...] = ()
    evidence_kinds: tuple[str, ...] = ()
    lifecycle_transition: tuple[str, str] | None = None
    fixed_external_observations: tuple[tuple[str, JsonValue], ...] = ()
    human_attestations: tuple[str, ...] = ()
    advisory_ai_observations: tuple[tuple[str, JsonValue], ...] = ()


def evaluate_constraint(
    evaluator: SemanticEvaluator,
    expression: ConstraintExpression,
    environment: ConstraintEnvironment,
) -> ConstraintResult:
    """Evaluate the frozen operator vocabulary without arbitrary Profile code."""

    fields = dict(environment.fields)
    value = fields.get(expression.field_path or "")
    field_known = expression.field_path in fields
    operator = expression.operator
    if operator is RuleOperator.FIELD_FORBIDDEN:
        return _truth(not field_known, value, "forbidden field check")
    if (
        operator
        in {
            RuleOperator.FIELD_TYPE,
            RuleOperator.FIELD_ENUM,
            RuleOperator.FIELD_PATTERN,
            RuleOperator.FIELD_RANGE,
            RuleOperator.FIELD_TOLERANCE,
            RuleOperator.SET,
            RuleOperator.UNIQUE,
        }
        and not field_known
    ):
        return _unknown("field is absent or unknown")
    if operator is RuleOperator.FIELD_TYPE:
        expected_type = str(expression.expected)
        actual = (
            "boolean"
            if isinstance(value, bool)
            else "integer"
            if isinstance(value, int)
            else "string"
            if isinstance(value, str)
            else "array"
            if isinstance(value, list)
            else "object"
            if isinstance(value, dict)
            else "null"
        )
        return _truth(actual == expected_type, actual, "field type check")
    if operator is RuleOperator.FIELD_ENUM:
        allowed = expression.expected if isinstance(expression.expected, list) else []
        return _truth(value in allowed, value, "field enum check")
    if operator is RuleOperator.FIELD_PATTERN:
        if not isinstance(value, str) or not isinstance(expression.expected, str):
            return _unknown("pattern requires known strings")
        return _truth(re.fullmatch(expression.expected, value) is not None, value, "pattern check")
    if operator in {RuleOperator.FIELD_RANGE, RuleOperator.FIELD_TOLERANCE}:
        try:
            numeric_observed = Decimal(str(value))
            numeric_minimum = (
                Decimal(expression.minimum) if expression.minimum is not None else None
            )
            numeric_maximum = (
                Decimal(expression.maximum) if expression.maximum is not None else None
            )
            if operator is RuleOperator.FIELD_TOLERANCE:
                numeric_expected = Decimal(str(expression.expected))
                tolerance = Decimal(expression.tolerance or "0")
                passed = abs(numeric_observed - numeric_expected) <= tolerance
            else:
                passed = (numeric_minimum is None or numeric_observed >= numeric_minimum) and (
                    numeric_maximum is None or numeric_observed <= numeric_maximum
                )
        except (InvalidOperation, ValueError):
            return _unknown("numeric value or decimal bound is invalid")
        return _truth(passed, str(numeric_observed), "numeric constraint")
    if operator is RuleOperator.SET:
        if not isinstance(value, list) or not isinstance(expression.expected, list):
            return _unknown("set constraint requires arrays")
        return _truth(
            {str(item) for item in value} == {str(item) for item in expression.expected},
            value,
            "set equality",
        )
    if operator is RuleOperator.UNIQUE:
        if not isinstance(value, list):
            return _unknown("unique constraint requires an array")
        return _truth(len(value) == len({str(item) for item in value}), value, "uniqueness")
    if operator in {
        RuleOperator.RELATION_CARDINALITY,
        RuleOperator.RELATION_DIRECTION,
        RuleOperator.RELATION_ENDPOINT,
        RuleOperator.RELATION_BINDING,
        RuleOperator.RELATION_STATE,
        RuleOperator.FORMAL_TRACE,
    }:
        if expression.predicate is None:
            return _unknown("relation constraint has no predicate")
        count = evaluator.relation_count(
            environment.target_uid,
            predicate=expression.predicate,
            direction=expression.direction,
            binding=expression.binding,
            lifecycle_state=expression.lifecycle_state,
            formal_trace_category=expression.formal_trace_category
            if operator is RuleOperator.FORMAL_TRACE
            else None,
        )
        relation_minimum = int(
            expression.minimum
            or ("1" if operator is not RuleOperator.RELATION_CARDINALITY else "0")
        )
        relation_maximum = int(expression.maximum) if expression.maximum is not None else None
        return _truth(
            count >= relation_minimum and (relation_maximum is None or count <= relation_maximum),
            count,
            "relation constraint",
        )
    if operator is RuleOperator.GRAPH_PATH:
        if expression.relation_path is None:
            return _unknown("graph path expression is absent")
        result = evaluate_path(evaluator, environment.target_uid, expression.relation_path)
        if result.truncated and not result.matches:
            return _unknown("graph path reached its depth or cycle bound")
        return _truth(bool(result.matches), len(result.matches), "graph path constraint")
    if operator is RuleOperator.LIFECYCLE_TRANSITION:
        if environment.lifecycle_transition is None:
            return _unknown("lifecycle transition is absent")
        expected_transition = expression.expected
        actual_transition = list(environment.lifecycle_transition)
        return _truth(
            actual_transition == expected_transition,
            cast(JsonValue, actual_transition),
            "lifecycle transition",
        )
    if operator is RuleOperator.PROCESS_EVIDENCE:
        if expression.evidence_kind is None:
            return _unknown("required evidence kind is absent")
        return _truth(
            expression.evidence_kind in environment.evidence_kinds,
            list(environment.evidence_kinds),
            "process evidence",
        )
    if operator is RuleOperator.TEMPORAL_FRESHNESS:
        if not isinstance(value, str) or expression.maximum_age_seconds is None:
            return _unknown("freshness requires a timestamp and maximum age")
        try:
            observed_at = datetime.fromisoformat(value)
            age = (evaluator.snapshot.evaluation_time - observed_at).total_seconds()
        except ValueError:
            return _unknown("freshness timestamp is invalid")
        return _truth(
            0 <= age <= expression.maximum_age_seconds,
            str(int(age)),
            "temporal freshness",
        )
    if operator in {
        RuleOperator.AGGREGATE_COUNT,
        RuleOperator.AGGREGATE_SUM,
        RuleOperator.AGGREGATE_MIN,
        RuleOperator.AGGREGATE_MAX,
        RuleOperator.AGGREGATE_RATIO,
        RuleOperator.AGGREGATE_ALL,
        RuleOperator.AGGREGATE_ANY,
        RuleOperator.AGGREGATE_NONE,
    }:
        values: tuple[Decimal | bool | None, ...] = tuple(
            Decimal(item) if isinstance(item, str) else item
            for item in environment.aggregate_values
        )
        return evaluate_aggregate(operator, values)
    if operator is RuleOperator.EXTERNAL_OBSERVATION:
        observations = dict(environment.fixed_external_observations)
        if expression.observation_key not in observations:
            return _unknown("fixed external observation is absent")
        fixed_observed = observations[expression.observation_key or ""]
        return _truth(
            fixed_observed == expression.expected,
            fixed_observed,
            "fixed external observation",
        )
    if operator is RuleOperator.HUMAN_ATTESTATION:
        if expression.observation_key is None:
            return _unknown("attestation key is absent")
        return _truth(
            expression.observation_key in environment.human_attestations,
            list(environment.human_attestations),
            "human attestation",
        )
    if operator is RuleOperator.ADVISORY_AI_OBSERVATION:
        return _unknown("AI observation is advisory and cannot determine enforcement")
    return _unknown("unsupported constraint")


def _truth(passed: bool, observed: JsonValue, explanation: str) -> ConstraintResult:
    return ConstraintResult(
        truth=TruthValue.TRUE if passed else TruthValue.FALSE,
        observed=observed,
        explanation=explanation,
    )


def _unknown(explanation: str) -> ConstraintResult:
    return ConstraintResult(truth=TruthValue.INDETERMINATE, explanation=explanation)


def evaluate_aggregate(
    operator: RuleOperator,
    values: tuple[Decimal | bool | None, ...],
) -> ConstraintResult:
    if not values or any(item is None for item in values):
        return ConstraintResult(
            truth=TruthValue.INDETERMINATE,
            explanation="aggregate input is absent or unknown",
        )
    if operator is RuleOperator.AGGREGATE_COUNT:
        observed: JsonValue = len(values)
    elif operator is RuleOperator.AGGREGATE_SUM:
        observed = str(sum(item for item in values if isinstance(item, Decimal)))
    elif operator is RuleOperator.AGGREGATE_MIN:
        observed = str(min(item for item in values if isinstance(item, Decimal)))
    elif operator is RuleOperator.AGGREGATE_MAX:
        observed = str(max(item for item in values if isinstance(item, Decimal)))
    elif operator is RuleOperator.AGGREGATE_RATIO:
        booleans = [item for item in values if isinstance(item, bool)]
        if not booleans:
            return ConstraintResult(
                truth=TruthValue.INDETERMINATE, explanation="ratio has no boolean inputs"
            )
        observed = str(Decimal(sum(booleans)) / Decimal(len(booleans)))
    elif operator is RuleOperator.AGGREGATE_ALL:
        observed = all(item is True for item in values)
    elif operator is RuleOperator.AGGREGATE_ANY:
        observed = any(item is True for item in values)
    elif operator is RuleOperator.AGGREGATE_NONE:
        observed = not any(item is True for item in values)
    else:
        return ConstraintResult(
            truth=TruthValue.INDETERMINATE, explanation="operator is not an aggregate"
        )
    return ConstraintResult(
        truth=TruthValue.TRUE, observed=observed, explanation="aggregate evaluated"
    )


class ContextCompleteness(StrEnum):
    COMPLETE = "COMPLETE"
    INCOMPLETE_MISSING_RELATION = "INCOMPLETE_MISSING_RELATION"
    INCOMPLETE_BUDGET = "INCOMPLETE_BUDGET"
    INCOMPLETE_CONFIGURATION = "INCOMPLETE_CONFIGURATION"
    INCOMPLETE_CONFLICT = "INCOMPLETE_CONFLICT"
    INCOMPLETE_CONFIDENTIALITY = "INCOMPLETE_CONFIDENTIALITY"


class ContextBundle(FrozenModel):
    schema_version: Literal["1.0"] = "1.0"
    resource_type: Literal["context_bundle"] = "context_bundle"
    bundle_uid: str = Field(default_factory=uuid7_candidate)
    graph_snapshot_hash: str
    stage: Literal["manifest", "focused_read", "deep_trace"]
    mandatory: tuple[str, ...]
    supporting: tuple[str, ...]
    selection_trace: tuple[str, ...]
    omitted_candidates: tuple[str, ...]
    completeness: ContextCompleteness
    bundle_hash: str = ""

    @model_validator(mode="after")
    def calculate_hash(self) -> ContextBundle:
        expected = document_hash(self.model_dump(mode="json"), "bundle_hash")
        if self.bundle_hash and self.bundle_hash != expected:
            raise ValueError("bundle_hash is invalid")
        object.__setattr__(self, "bundle_hash", expected)
        return self


def plan_context(
    evaluator: SemanticEvaluator,
    targets: tuple[str, ...],
    mandatory_predicates: tuple[str, ...],
    *,
    token_limit: int,
    supporting_from_fts: tuple[str, ...] = (),
) -> ContextBundle:
    mandatory = set(targets)
    trace: list[str] = [f"explicit:{uid}" for uid in targets]
    missing = False
    for target in targets:
        for predicate in mandatory_predicates:
            adjacent = evaluator._adjacent(
                target, predicate=predicate, direction=Direction.OUTGOING
            )
            if not adjacent:
                missing = True
                trace.append(f"missing-relation:{target}:{predicate}")
            for uid, _ in adjacent:
                mandatory.add(uid)
                trace.append(f"mandatory-relation:{target}:{predicate}:{uid}")
    ordered = tuple(sorted(mandatory))
    omitted: tuple[str, ...] = ()
    completeness = (
        ContextCompleteness.INCOMPLETE_MISSING_RELATION if missing else ContextCompleteness.COMPLETE
    )
    if len(ordered) > token_limit:
        omitted = ordered[token_limit:]
        ordered = ordered[:token_limit]
        completeness = ContextCompleteness.INCOMPLETE_BUDGET
    return ContextBundle(
        graph_snapshot_hash=evaluator.snapshot.snapshot_hash,
        stage="manifest",
        mandatory=ordered,
        supporting=tuple(uid for uid in supporting_from_fts if uid not in set(ordered)),
        selection_trace=tuple(trace),
        omitted_candidates=omitted,
        completeness=completeness,
    )


class ImpactCompleteness(StrEnum):
    COMPLETE = "COMPLETE"
    INCOMPLETE_UNKNOWN_EXTERNAL = "INCOMPLETE_UNKNOWN_EXTERNAL"
    INCOMPLETE_MAX_DEPTH = "INCOMPLETE_MAX_DEPTH"
    INCOMPLETE_UNRESOLVED_PROFILE = "INCOMPLETE_UNRESOLVED_PROFILE"
    INDETERMINATE_CONFIGURATION = "INDETERMINATE_CONFIGURATION"


class ImpactPath(FrozenModel):
    uids: tuple[str, ...]
    reason: str
    depth: int


class ImpactReport(FrozenModel):
    schema_version: Literal["1.0"] = "1.0"
    resource_type: Literal["impact_report"] = "impact_report"
    report_uid: str = Field(default_factory=uuid7_candidate)
    graph_snapshot_hash: str
    paths: tuple[ImpactPath, ...]
    affected_rule_uids: tuple[str, ...]
    affected_configuration_uids: tuple[str, ...]
    affected_baseline_uids: tuple[str, ...]
    affected_deviation_uids: tuple[str, ...]
    unknowns: tuple[str, ...]
    completeness: ImpactCompleteness
    report_hash: str = ""

    @model_validator(mode="after")
    def calculate_hash(self) -> ImpactReport:
        expected = document_hash(self.model_dump(mode="json"), "report_hash")
        if self.report_hash and self.report_hash != expected:
            raise ValueError("report_hash is invalid")
        object.__setattr__(self, "report_hash", expected)
        return self


def analyze_impact(
    evaluator: SemanticEvaluator,
    starts: tuple[str, ...],
    *,
    maximum_depth: int,
    profile_conflicts: tuple[str, ...] = (),
    configuration_complete: bool = True,
    affected_rule_uids: tuple[str, ...] = (),
    affected_configuration_uids: tuple[str, ...] = (),
    affected_baseline_uids: tuple[str, ...] = (),
    affected_deviation_uids: tuple[str, ...] = (),
) -> ImpactReport:
    queue: deque[tuple[str, tuple[str, ...], int]] = deque((uid, (uid,), 0) for uid in starts)
    visited = set(starts)
    paths: list[ImpactPath] = []
    depth_limited = False
    while queue:
        current, path, depth = queue.popleft()
        adjacent = evaluator._adjacent(
            current, predicate=None, direction=Direction.OUTGOING
        ) + evaluator._adjacent(current, predicate=None, direction=Direction.INCOMING)
        if depth >= maximum_depth:
            if any(uid not in visited for uid, _ in adjacent):
                depth_limited = True
            continue
        for uid, relation in adjacent:
            if uid in visited:
                continue
            visited.add(uid)
            new_path = path + (uid,)
            paths.append(
                ImpactPath(
                    uids=new_path,
                    reason=relation.assertion.predicate,
                    depth=depth + 1,
                )
            )
            queue.append((uid, new_path, depth + 1))
    unknowns = tuple(sorted(evaluator.snapshot.unresolved_external_endpoints))
    if not configuration_complete:
        completeness = ImpactCompleteness.INDETERMINATE_CONFIGURATION
    elif profile_conflicts:
        completeness = ImpactCompleteness.INCOMPLETE_UNRESOLVED_PROFILE
        unknowns += tuple(sorted(profile_conflicts))
    elif unknowns:
        completeness = ImpactCompleteness.INCOMPLETE_UNKNOWN_EXTERNAL
    elif depth_limited:
        completeness = ImpactCompleteness.INCOMPLETE_MAX_DEPTH
    else:
        completeness = ImpactCompleteness.COMPLETE
    return ImpactReport(
        graph_snapshot_hash=evaluator.snapshot.snapshot_hash,
        paths=tuple(paths),
        affected_rule_uids=tuple(sorted(affected_rule_uids)),
        affected_configuration_uids=tuple(sorted(affected_configuration_uids)),
        affected_baseline_uids=tuple(sorted(affected_baseline_uids)),
        affected_deviation_uids=tuple(sorted(affected_deviation_uids)),
        unknowns=unknowns,
        completeness=completeness,
    )
