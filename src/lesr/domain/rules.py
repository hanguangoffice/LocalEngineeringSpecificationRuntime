"""LESR v1 closed, typed and explainable rule compiler."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, Literal, Protocol

from pydantic import Field, model_validator

from lesr.domain.semantic import FrozenModel, JsonValue, canonical_json, semantic_hash


class ApplicabilityResult(StrEnum):
    APPLICABLE = "applicable"
    NOT_APPLICABLE = "not_applicable"
    INDETERMINATE = "indeterminate"


class ValueState(StrEnum):
    ABSENT = "absent"
    NULL = "null"
    UNKNOWN = "unknown"
    VALUE = "value"


class ConstraintResult(StrEnum):
    SATISFIED = "satisfied"
    VIOLATED = "violated"
    INDETERMINATE = "indeterminate"
    EVALUATOR_ERROR = "evaluator_error"


class RuleOutcome(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    NOT_APPLICABLE = "not_applicable"
    INDETERMINATE = "indeterminate"
    SUPPRESSED_BY_DEVIATION = "suppressed_by_deviation"
    EVALUATOR_ERROR = "evaluator_error"
    NOT_EVALUATED = "not_evaluated"


class NormativeModality(StrEnum):
    OBLIGATION = "obligation"
    PROHIBITION = "prohibition"
    PERMISSION = "permission"
    RECOMMENDATION = "recommendation"
    DISCOURAGEMENT = "discouragement"
    INFORMATIONAL = "informational"


class EnforcementEffect(StrEnum):
    ALLOW = "allow"
    ALLOW_WITH_OBSERVATION = "allow_with_observation"
    REQUIRE_ACKNOWLEDGEMENT = "require_acknowledgement"
    REQUIRE_REVIEW = "require_review"
    REQUIRE_DEVIATION = "require_deviation"
    BLOCK_OPERATION = "block_operation"


class FixtureKind(StrEnum):
    POSITIVE = "positive"
    NEGATIVE = "negative"
    NOT_APPLICABLE = "not_applicable"
    INDETERMINATE = "indeterminate"
    EXCEPTION = "exception"
    DEVIATION = "deviation"
    CONFLICT = "conflict"
    MIGRATION = "migration"


@dataclass(frozen=True, slots=True)
class ValueCell:
    state: ValueState
    value: Any = None

    @classmethod
    def present(cls, value: Any) -> ValueCell:
        return cls(ValueState.NULL if value is None else ValueState.VALUE, value)


@dataclass(frozen=True, slots=True)
class EvaluationEnvironment:
    target_kind: str
    fields: dict[str, ValueCell]
    relation_counts: dict[str, int] = field(default_factory=dict)
    operation: str = "validate"
    active_exception_rule_uids: frozenset[str] = frozenset()
    active_deviation_rule_uids: frozenset[str] = frozenset()
    conflicted_rule_uids: frozenset[str] = frozenset()
    schema_version: int = 1

    def read(self, path: str) -> ValueCell:
        return self.fields.get(path, ValueCell(ValueState.ABSENT))


@dataclass(frozen=True, slots=True)
class ExplanationNode:
    node: str
    result: str
    reason: str
    children: tuple[ExplanationNode, ...] = ()


class ApplicabilityExpression(Protocol):
    def evaluate(self, environment: EvaluationEnvironment) -> ExplanationNode: ...

    def to_data(self) -> dict[str, Any]: ...


@dataclass(frozen=True, slots=True)
class ConstantApplicability:
    result: ApplicabilityResult

    def evaluate(self, environment: EvaluationEnvironment) -> ExplanationNode:
        del environment
        return ExplanationNode("constant", self.result, "explicit constant")

    def to_data(self) -> dict[str, Any]:
        value = {
            ApplicabilityResult.APPLICABLE: "true",
            ApplicabilityResult.NOT_APPLICABLE: "false",
            ApplicabilityResult.INDETERMINATE: "unknown",
        }[self.result]
        return {"op": "constant", "value": value}


@dataclass(frozen=True, slots=True)
class KindIs:
    kind: str

    def evaluate(self, environment: EvaluationEnvironment) -> ExplanationNode:
        result = (
            ApplicabilityResult.APPLICABLE
            if environment.target_kind == self.kind
            else ApplicabilityResult.NOT_APPLICABLE
        )
        return ExplanationNode("kind_is", result, f"target kind is {environment.target_kind}")

    def to_data(self) -> dict[str, Any]:
        return {"op": "kind_is", "kind": self.kind}


@dataclass(frozen=True, slots=True)
class FieldKnown:
    path: str

    def evaluate(self, environment: EvaluationEnvironment) -> ExplanationNode:
        cell = environment.read(self.path)
        if cell.state is ValueState.VALUE:
            result = ApplicabilityResult.APPLICABLE
        elif cell.state in {ValueState.ABSENT, ValueState.UNKNOWN}:
            result = ApplicabilityResult.INDETERMINATE
        else:
            result = ApplicabilityResult.NOT_APPLICABLE
        return ExplanationNode("field_known", result, f"{self.path} is {cell.state}")

    def to_data(self) -> dict[str, Any]:
        return {"op": "field_known", "path": self.path}


@dataclass(frozen=True, slots=True)
class FieldEquals:
    path: str
    expected: JsonValue

    def evaluate(self, environment: EvaluationEnvironment) -> ExplanationNode:
        cell = environment.read(self.path)
        if cell.state in {ValueState.ABSENT, ValueState.UNKNOWN}:
            result = ApplicabilityResult.INDETERMINATE
        elif cell.state is ValueState.NULL:
            result = ApplicabilityResult.NOT_APPLICABLE
        else:
            result = (
                ApplicabilityResult.APPLICABLE
                if cell.value == self.expected
                else ApplicabilityResult.NOT_APPLICABLE
            )
        return ExplanationNode(
            "field_equals", result, f"{self.path}={cell.state}:{cell.value!r}"
        )

    def to_data(self) -> dict[str, Any]:
        return {"op": "field_equals", "path": self.path, "value": self.expected}


@dataclass(frozen=True, slots=True)
class AllOf:
    children: tuple[ApplicabilityExpression, ...]

    def evaluate(self, environment: EvaluationEnvironment) -> ExplanationNode:
        evaluated = tuple(child.evaluate(environment) for child in self.children)
        results = {ApplicabilityResult(item.result) for item in evaluated}
        if ApplicabilityResult.NOT_APPLICABLE in results:
            result = ApplicabilityResult.NOT_APPLICABLE
        elif ApplicabilityResult.INDETERMINATE in results:
            result = ApplicabilityResult.INDETERMINATE
        else:
            result = ApplicabilityResult.APPLICABLE
        return ExplanationNode("all_of", result, "Kleene three-valued ALL", evaluated)

    def to_data(self) -> dict[str, Any]:
        return {"op": "all_of", "items": [child.to_data() for child in self.children]}


@dataclass(frozen=True, slots=True)
class AnyOf:
    children: tuple[ApplicabilityExpression, ...]

    def evaluate(self, environment: EvaluationEnvironment) -> ExplanationNode:
        evaluated = tuple(child.evaluate(environment) for child in self.children)
        results = {ApplicabilityResult(item.result) for item in evaluated}
        if ApplicabilityResult.APPLICABLE in results:
            result = ApplicabilityResult.APPLICABLE
        elif ApplicabilityResult.INDETERMINATE in results:
            result = ApplicabilityResult.INDETERMINATE
        else:
            result = ApplicabilityResult.NOT_APPLICABLE
        return ExplanationNode("any_of", result, "Kleene three-valued ANY", evaluated)

    def to_data(self) -> dict[str, Any]:
        return {"op": "any_of", "items": [child.to_data() for child in self.children]}


@dataclass(frozen=True, slots=True)
class Not:
    child: ApplicabilityExpression

    def evaluate(self, environment: EvaluationEnvironment) -> ExplanationNode:
        evaluated = self.child.evaluate(environment)
        result = {
            ApplicabilityResult.APPLICABLE: ApplicabilityResult.NOT_APPLICABLE,
            ApplicabilityResult.NOT_APPLICABLE: ApplicabilityResult.APPLICABLE,
            ApplicabilityResult.INDETERMINATE: ApplicabilityResult.INDETERMINATE,
        }[ApplicabilityResult(evaluated.result)]
        return ExplanationNode("not", result, "Kleene three-valued NOT", (evaluated,))

    def to_data(self) -> dict[str, Any]:
        return {"op": "not", "item": self.child.to_data()}


@dataclass(frozen=True, slots=True)
class Quantity:
    value: Decimal
    unit: str


@dataclass(frozen=True, slots=True)
class UnitDefinition:
    unit: str
    dimension: str
    scale_to_base: Decimal


class UnitRegistry:
    def __init__(self, definitions: tuple[UnitDefinition, ...]) -> None:
        self._definitions = {item.unit: item for item in definitions}

    def compare(self, left: Quantity, right: Quantity) -> int:
        left_definition = self._require(left.unit)
        right_definition = self._require(right.unit)
        if left_definition.dimension != right_definition.dimension:
            raise ValueError(
                f"incompatible dimensions: {left_definition.dimension} and "
                f"{right_definition.dimension}"
            )
        left_base = left.value * left_definition.scale_to_base
        right_base = right.value * right_definition.scale_to_base
        return (left_base > right_base) - (left_base < right_base)

    def _require(self, unit: str) -> UnitDefinition:
        try:
            return self._definitions[unit]
        except KeyError as error:
            raise ValueError(f"unknown unit: {unit}") from error


class Constraint(Protocol):
    def evaluate(
        self, environment: EvaluationEnvironment, units: UnitRegistry
    ) -> ExplanationNode: ...

    def referenced_paths(self) -> frozenset[str]: ...

    def to_data(self) -> dict[str, Any]: ...


@dataclass(frozen=True, slots=True)
class FieldRequired:
    path: str

    def evaluate(
        self, environment: EvaluationEnvironment, units: UnitRegistry
    ) -> ExplanationNode:
        del units
        cell = environment.read(self.path)
        if cell.state is ValueState.VALUE:
            result = ConstraintResult.SATISFIED
        elif cell.state in {ValueState.ABSENT, ValueState.NULL}:
            result = ConstraintResult.VIOLATED
        else:
            result = ConstraintResult.INDETERMINATE
        return ExplanationNode("field_required", result, f"{self.path} is {cell.state}")

    def referenced_paths(self) -> frozenset[str]:
        return frozenset({self.path})

    def to_data(self) -> dict[str, Any]:
        return {"op": "field_required", "path": self.path}


@dataclass(frozen=True, slots=True)
class QuantityMaximum:
    path: str
    maximum: Quantity

    def evaluate(
        self, environment: EvaluationEnvironment, units: UnitRegistry
    ) -> ExplanationNode:
        cell = environment.read(self.path)
        if cell.state in {ValueState.ABSENT, ValueState.UNKNOWN}:
            return ExplanationNode(
                "quantity_maximum", ConstraintResult.INDETERMINATE, f"{self.path} unknown"
            )
        if not isinstance(cell.value, Quantity):
            return ExplanationNode(
                "quantity_maximum",
                ConstraintResult.EVALUATOR_ERROR,
                f"{self.path} is not a Quantity",
            )
        try:
            comparison = units.compare(cell.value, self.maximum)
        except ValueError as error:
            return ExplanationNode(
                "quantity_maximum", ConstraintResult.EVALUATOR_ERROR, str(error)
            )
        result = (
            ConstraintResult.SATISFIED if comparison <= 0 else ConstraintResult.VIOLATED
        )
        return ExplanationNode(
            "quantity_maximum",
            result,
            f"{cell.value.value}{cell.value.unit} <= "
            f"{self.maximum.value}{self.maximum.unit}",
        )

    def referenced_paths(self) -> frozenset[str]:
        return frozenset({self.path})

    def to_data(self) -> dict[str, Any]:
        return {
            "op": "quantity_maximum",
            "path": self.path,
            "maximum": {"decimal": str(self.maximum.value), "unit": self.maximum.unit},
        }


@dataclass(frozen=True, slots=True)
class RelationMinimum:
    predicate: str
    minimum: int
    maximum_depth: int = 1

    def __post_init__(self) -> None:
        if self.maximum_depth < 1:
            raise ValueError("relation paths must have a finite positive maximum depth")

    def evaluate(
        self, environment: EvaluationEnvironment, units: UnitRegistry
    ) -> ExplanationNode:
        del units
        count = environment.relation_counts.get(self.predicate)
        if count is None:
            result = ConstraintResult.INDETERMINATE
            reason = "relation projection is unknown"
        else:
            result = (
                ConstraintResult.SATISFIED
                if count >= self.minimum
                else ConstraintResult.VIOLATED
            )
            reason = f"count={count}, minimum={self.minimum}, max_depth={self.maximum_depth}"
        return ExplanationNode("relation_minimum", result, reason)

    def referenced_paths(self) -> frozenset[str]:
        return frozenset()

    def to_data(self) -> dict[str, Any]:
        return {
            "op": "relation_minimum",
            "path": {"roles": [self.predicate], "max_depth": self.maximum_depth},
            "minimum": self.minimum,
        }


@dataclass(frozen=True, slots=True)
class RuleFixture:
    fixture_id: str
    kind: FixtureKind
    environment: EvaluationEnvironment
    expected_outcome: RuleOutcome


class RuleSourceText(FrozenModel):
    text: str = Field(min_length=1)
    language: str = Field(min_length=2)
    source_hash: str
    interpretation_note: str = ""
    source_reference: JsonValue | None = None


class EvaluationSpecification(FrozenModel):
    kind: Literal[
        "declarative",
        "registered_validator",
        "external_tool",
        "human_attestation",
        "ai_semantic",
        "composite",
    ] = "declarative"
    validator_uid: str | None = None
    advisory_only: bool = False


class EnforcementMapping(FrozenModel):
    operation: str = Field(min_length=1)
    effect: EnforcementEffect


class AuthorityDeclaration(FrozenModel):
    source_uid: str
    profile_revision_uid: str
    issuer_uid: str
    scope: JsonValue
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    may_refine: bool
    may_relax: bool
    deviation_allowed: bool
    non_overridable: bool
    overrides: tuple[str, ...] = ()
    approval_record_uid: str | None = None


class DeviationPolicy(FrozenModel):
    allowed: bool
    required_approval_roles: tuple[str, ...] = ()


class RuleFixtureDefinition(FrozenModel):
    fixture_uid: str
    kind: FixtureKind
    environment: dict[str, JsonValue]
    expected_outcome: RuleOutcome


class RuleDefinition(FrozenModel):
    schema_version: Literal["1.0"] = "1.0"
    resource_type: Literal["rule_definition_revision"] = "rule_definition_revision"
    rule_uid: str
    rule_revision_uid: str
    source: RuleSourceText
    target_selector: dict[str, JsonValue]
    applicability: dict[str, JsonValue]
    modality: NormativeModality
    constraints: tuple[dict[str, JsonValue], ...]
    evaluation: EvaluationSpecification
    enforcement: tuple[EnforcementMapping, ...]
    authority: AuthorityDeclaration
    exception_policy: JsonValue
    deviation_policy: DeviationPolicy
    explanation_map: dict[str, str]
    fixtures: tuple[RuleFixtureDefinition, ...]
    content_hash: str = ""

    @model_validator(mode="after")
    def calculate_content_hash(self) -> RuleDefinition:
        calculated = semantic_hash(
            self.model_dump(mode="json", exclude={"content_hash"}, exclude_none=True)
        )
        if self.content_hash and self.content_hash != calculated:
            raise ValueError("content_hash does not match rule definition content")
        object.__setattr__(self, "content_hash", calculated)
        return self


@dataclass(frozen=True, slots=True)
class RuleAST:
    rule_uid: str
    rule_revision_uid: str
    schema_version: str
    ast_hash: str
    target_kind: str
    applicability: ApplicabilityExpression
    modality: NormativeModality
    constraints: tuple[Constraint, ...]
    enforcement: dict[str, EnforcementEffect]
    authority: AuthorityDeclaration
    deviation_allowed: bool


@dataclass(frozen=True, slots=True)
class CompilationDiagnostic:
    level: str
    code: str
    message: str


@dataclass(frozen=True, slots=True)
class CompilationResult:
    ast: RuleAST | None
    diagnostics: tuple[CompilationDiagnostic, ...]
    fixture_outcomes: tuple[tuple[str, RuleOutcome], ...]

    @property
    def passed(self) -> bool:
        return self.ast is not None and not any(item.level == "error" for item in self.diagnostics)


@dataclass(frozen=True, slots=True)
class RuleEvaluation:
    outcome: RuleOutcome
    applicability: ExplanationNode
    constraint: ExplanationNode | None
    enforcement: EnforcementEffect


class RuleCompiler:
    def __init__(self, symbols: dict[str, type[Any]], units: UnitRegistry) -> None:
        self.symbols = symbols
        self.units = units

    def compile(self, source: RuleDefinition) -> CompilationResult:
        diagnostics: list[CompilationDiagnostic] = []
        if not source.source.text.strip():
            diagnostics.append(
                CompilationDiagnostic("error", "RULE_STATEMENT_MISSING", "statement is required")
            )
        if not source.authority.source_uid:
            diagnostics.append(
                CompilationDiagnostic("error", "RULE_AUTHORITY_MISSING", "authority is required")
            )
        try:
            target = _parse_expression(source.target_selector)
            if not isinstance(target, KindIs):
                raise TypeError("v1 target selector must resolve to kind_is")
            applicability = _parse_expression(source.applicability)
            constraints = tuple(_parse_constraint(item) for item in source.constraints)
        except (KeyError, TypeError, ValueError) as error:
            diagnostics.append(
                CompilationDiagnostic("error", "RULE_AST_INVALID", str(error))
            )
            return CompilationResult(None, tuple(diagnostics), ())
        for path in frozenset().union(
            *(constraint.referenced_paths() for constraint in constraints)
        ):
            if path not in self.symbols:
                diagnostics.append(
                    CompilationDiagnostic("error", "RULE_PATH_UNKNOWN", f"unknown path: {path}")
                )
        if not source.explanation_map:
            diagnostics.append(
                CompilationDiagnostic(
                    "error", "RULE_EXPLANATION_MISSING", "explanation map is required"
                )
            )
        if source.evaluation.kind == "ai_semantic" and not source.evaluation.advisory_only:
            diagnostics.append(
                CompilationDiagnostic(
                    "error",
                    "RULE_AI_SEMANTIC_NOT_ADVISORY",
                    "AI semantic evaluation must be advisory unless a reviewed policy says otherwise",
                )
            )
        enforcement = {item.operation: item.effect for item in source.enforcement}
        if len(enforcement) != len(source.enforcement):
            diagnostics.append(
                CompilationDiagnostic(
                    "error", "RULE_ENFORCEMENT_DUPLICATE", "duplicate enforcement operation"
                )
            )
        ast_data = {
            "schema_version": source.schema_version,
            "rule_uid": source.rule_uid,
            "rule_revision_uid": source.rule_revision_uid,
            "target_selector": target.to_data(),
            "applicability": applicability.to_data(),
            "modality": source.modality,
            "constraints": [item.to_data() for item in constraints],
            "enforcement": enforcement,
            "authority": source.authority.model_dump(mode="json", exclude_none=True),
            "deviation_allowed": source.deviation_policy.allowed,
            "explanation_map": source.explanation_map,
        }
        ast = RuleAST(
            rule_uid=source.rule_uid,
            rule_revision_uid=source.rule_revision_uid,
            schema_version=source.schema_version,
            ast_hash=semantic_hash(ast_data),
            target_kind=target.kind,
            applicability=applicability,
            modality=source.modality,
            constraints=constraints,
            enforcement=enforcement,
            authority=source.authority,
            deviation_allowed=(
                source.deviation_policy.allowed and source.authority.deviation_allowed
            ),
        )
        outcomes: list[tuple[str, RuleOutcome]] = []
        fixture_kinds = {fixture.kind for fixture in source.fixtures}
        missing = set(FixtureKind) - fixture_kinds
        if missing:
            diagnostics.append(
                CompilationDiagnostic(
                    "error",
                    "RULE_FIXTURE_COVERAGE",
                    "missing fixtures: " + ", ".join(sorted(item.value for item in missing)),
                )
            )
        for fixture in source.fixtures:
            try:
                environment = _parse_environment(fixture.environment)
            except (KeyError, TypeError, ValueError) as error:
                diagnostics.append(
                    CompilationDiagnostic(
                        "error",
                        "RULE_FIXTURE_INVALID",
                        f"{fixture.fixture_uid}: {error}",
                    )
                )
                continue
            result = evaluate_rule(ast, environment, self.units)
            outcomes.append((fixture.fixture_uid, result.outcome))
            if result.outcome is not fixture.expected_outcome:
                diagnostics.append(
                    CompilationDiagnostic(
                        "error",
                        "RULE_FIXTURE_FAILED",
                        f"{fixture.fixture_uid}: expected {fixture.expected_outcome}, got {result.outcome}",
                    )
                )
        if any(item.level == "error" for item in diagnostics):
            return CompilationResult(None, tuple(diagnostics), tuple(outcomes))
        return CompilationResult(ast, tuple(diagnostics), tuple(outcomes))


def _parse_expression(value: dict[str, JsonValue]) -> ApplicabilityExpression:
    operation = value.get("op")
    if operation == "constant":
        result = {
            "true": ApplicabilityResult.APPLICABLE,
            "false": ApplicabilityResult.NOT_APPLICABLE,
            "unknown": ApplicabilityResult.INDETERMINATE,
        }[str(value["value"])]
        return ConstantApplicability(result)
    if operation == "kind_is":
        return KindIs(str(value["kind"]))
    if operation == "field_known":
        return FieldKnown(str(value["path"]))
    if operation == "field_equals":
        return FieldEquals(str(value["path"]), value.get("value"))
    if operation in {"all_of", "any_of"}:
        raw_items = value.get("items")
        if not isinstance(raw_items, list) or not raw_items:
            raise ValueError(f"{operation} requires non-empty items")
        items = tuple(_parse_expression(_require_dict(item)) for item in raw_items)
        return AllOf(items) if operation == "all_of" else AnyOf(items)
    if operation == "not":
        return Not(_parse_expression(_require_dict(value.get("item"))))
    raise ValueError(f"unsupported applicability operation: {operation}")


def _parse_constraint(value: dict[str, JsonValue]) -> Constraint:
    operation = value.get("op")
    if operation == "field_required":
        return FieldRequired(str(value["path"]))
    if operation == "quantity_maximum":
        maximum = _require_dict(value.get("maximum"))
        return QuantityMaximum(
            str(value["path"]),
            Quantity(Decimal(str(maximum["decimal"])), str(maximum["unit"])),
        )
    if operation == "relation_minimum":
        path = _require_dict(value.get("path"))
        roles = path.get("roles")
        if not isinstance(roles, list) or len(roles) != 1:
            raise ValueError("v1 relation_minimum requires exactly one bounded role")
        return RelationMinimum(
            str(roles[0]),
            int(str(value["minimum"])),
            int(str(path["max_depth"])),
        )
    raise ValueError(f"unsupported constraint operation: {operation}")


def _parse_environment(value: dict[str, JsonValue]) -> EvaluationEnvironment:
    raw_fields = value.get("fields", {})
    if not isinstance(raw_fields, dict):
        raise TypeError("fixture fields must be an object")
    fields: dict[str, ValueCell] = {}
    for path, raw_cell in raw_fields.items():
        cell = _require_dict(raw_cell)
        state = ValueState(str(cell.get("state", "value")))
        item: Any = cell.get("value")
        if isinstance(item, dict) and {"decimal", "unit"} <= item.keys():
            item = Quantity(Decimal(str(item["decimal"])), str(item["unit"]))
        fields[path] = ValueCell(state, item)
    raw_counts = value.get("relation_counts", {})
    if not isinstance(raw_counts, dict):
        raise TypeError("fixture relation_counts must be an object")
    return EvaluationEnvironment(
        target_kind=str(value["target_kind"]),
        fields=fields,
        relation_counts={key: int(str(item)) for key, item in raw_counts.items()},
        operation=str(value.get("operation", "validate")),
        active_exception_rule_uids=frozenset(
            str(item) for item in _require_list(value.get("active_exception_rule_uids", []))
        ),
        active_deviation_rule_uids=frozenset(
            str(item) for item in _require_list(value.get("active_deviation_rule_uids", []))
        ),
        conflicted_rule_uids=frozenset(
            str(item) for item in _require_list(value.get("conflicted_rule_uids", []))
        ),
        schema_version=int(str(value.get("schema_version", 1))),
    )


def _require_dict(value: JsonValue | None) -> dict[str, JsonValue]:
    if not isinstance(value, dict):
        raise TypeError("expected an object")
    return value


def _require_list(value: JsonValue | None) -> list[JsonValue]:
    if not isinstance(value, list):
        raise TypeError("expected an array")
    return value


def evaluate_rule(
    ast: RuleAST, environment: EvaluationEnvironment, units: UnitRegistry
) -> RuleEvaluation:
    enforcement = ast.enforcement.get(environment.operation, EnforcementEffect.REQUIRE_REVIEW)
    applicability = ast.applicability.evaluate(environment)
    if ast.rule_uid in environment.conflicted_rule_uids:
        return RuleEvaluation(RuleOutcome.INDETERMINATE, applicability, None, enforcement)
    if ast.rule_uid in environment.active_exception_rule_uids:
        return RuleEvaluation(RuleOutcome.NOT_APPLICABLE, applicability, None, enforcement)
    applicability_result = ApplicabilityResult(applicability.result)
    if applicability_result is ApplicabilityResult.NOT_APPLICABLE:
        return RuleEvaluation(RuleOutcome.NOT_APPLICABLE, applicability, None, enforcement)
    if applicability_result is ApplicabilityResult.INDETERMINATE:
        return RuleEvaluation(RuleOutcome.INDETERMINATE, applicability, None, enforcement)
    evaluated = tuple(item.evaluate(environment, units) for item in ast.constraints)
    results = {ConstraintResult(item.result) for item in evaluated}
    if ConstraintResult.EVALUATOR_ERROR in results:
        constraint_result = ConstraintResult.EVALUATOR_ERROR
    elif ConstraintResult.VIOLATED in results:
        constraint_result = ConstraintResult.VIOLATED
    elif ConstraintResult.INDETERMINATE in results:
        constraint_result = ConstraintResult.INDETERMINATE
    else:
        constraint_result = ConstraintResult.SATISFIED
    constraint = ExplanationNode(
        "all_constraints", constraint_result, "all compiled constraints", evaluated
    )
    if (
        constraint_result is ConstraintResult.VIOLATED
        and ast.deviation_allowed
        and ast.rule_uid in environment.active_deviation_rule_uids
    ):
        outcome = RuleOutcome.SUPPRESSED_BY_DEVIATION
    else:
        outcome = {
            ConstraintResult.SATISFIED: RuleOutcome.PASS,
            ConstraintResult.VIOLATED: RuleOutcome.FAIL,
            ConstraintResult.INDETERMINATE: RuleOutcome.INDETERMINATE,
            ConstraintResult.EVALUATOR_ERROR: RuleOutcome.EVALUATOR_ERROR,
        }[constraint_result]
    return RuleEvaluation(outcome, applicability, constraint, enforcement)


def detect_direct_conflict(left: RuleAST, right: RuleAST) -> bool:
    return (
        left.target_kind == right.target_kind
        and {left.modality, right.modality}
        == {NormativeModality.OBLIGATION, NormativeModality.PROHIBITION}
        and canonical_json([item.to_data() for item in left.constraints])
        == canonical_json([item.to_data() for item in right.constraints])
    )


def project_to_shacl(ast: RuleAST) -> dict[str, Any]:
    """Restricted comparison projection; it is not the authoritative rule form."""

    return {
        "@type": "sh:NodeShape",
        "lesr:rule": ast.rule_uid,
        "lesr:targetKind": ast.target_kind,
        "lesr:constraints": [item.to_data() for item in ast.constraints],
    }


def project_to_rego(ast: RuleAST) -> str:
    """Restricted inspection projection that never executes inside a Profile."""

    return (
        "package lesr.generated\n\n"
        f"# rule={ast.rule_uid} ast_hash={ast.ast_hash}\n"
        f"# target_kind={ast.target_kind}\n"
        "# semantic execution remains in the LESR domain evaluator\n"
    )
