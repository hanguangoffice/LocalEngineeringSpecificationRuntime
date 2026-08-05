from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

from lesr.adapters.schemas import SchemaCatalog
from lesr.domain.rules import (
    AllOf,
    AnyOf,
    ApplicabilityResult,
    AuthorityDeclaration,
    ConstantApplicability,
    DeviationPolicy,
    EnforcementEffect,
    EnforcementMapping,
    EvaluationEnvironment,
    EvaluationSpecification,
    FieldEquals,
    FieldKnown,
    FieldRequired,
    FixtureKind,
    KindIs,
    NormativeModality,
    Not,
    Quantity,
    QuantityMaximum,
    RelationMinimum,
    RuleCompiler,
    RuleDefinition,
    RuleFixtureDefinition,
    RuleOutcome,
    RuleSourceText,
    UnitDefinition,
    UnitRegistry,
    ValueCell,
    ValueState,
    detect_direct_conflict,
    evaluate_rule,
    project_to_rego,
    project_to_shacl,
)
from lesr.domain.semantic import semantic_hash

UNITS = UnitRegistry(
    (
        UnitDefinition("ms", "time", Decimal("0.001")),
        UnitDefinition("s", "time", Decimal(1)),
        UnitDefinition("mm", "length", Decimal("0.001")),
    )
)
DEFAULT_SAFETY = ValueCell.present("ASIL_B")
DEFAULT_STATEMENT = ValueCell.present("The software shall reconnect.")


def environment(
    *,
    kind: str = "software_requirement",
    safety: ValueCell = DEFAULT_SAFETY,
    statement: ValueCell = DEFAULT_STATEMENT,
    relation_count: int | None = 1,
    active_exception_rule_uids: frozenset[str] = frozenset(),
    active_deviation_rule_uids: frozenset[str] = frozenset(),
    conflicted_rule_uids: frozenset[str] = frozenset(),
    schema_version: int = 1,
) -> EvaluationEnvironment:
    counts = {} if relation_count is None else {"verified_by": relation_count}
    return EvaluationEnvironment(
        target_kind=kind,
        fields={"safety_level": safety, "statement": statement},
        relation_counts=counts,
        operation="approve_revision",
        active_exception_rule_uids=active_exception_rule_uids,
        active_deviation_rule_uids=active_deviation_rule_uids,
        conflicted_rule_uids=conflicted_rule_uids,
        schema_version=schema_version,
    )


def environment_data(**overrides: object) -> dict[str, object]:
    value = environment(**overrides)
    return {
        "target_kind": value.target_kind,
        "fields": {
            path: {"state": cell.state.value, "value": cell.value}
            for path, cell in value.fields.items()
        },
        "relation_counts": value.relation_counts,
        "operation": value.operation,
        "active_exception_rule_uids": sorted(value.active_exception_rule_uids),
        "active_deviation_rule_uids": sorted(value.active_deviation_rule_uids),
        "conflicted_rule_uids": sorted(value.conflicted_rule_uids),
        "schema_version": value.schema_version,
    }


def source() -> RuleDefinition:
    rule_uid = "018f0000-0000-7000-8000-000000000101"
    statement = "Approved requirements shall have verification trace."
    cases = (
        (FixtureKind.POSITIVE, environment_data(), RuleOutcome.PASS),
        (FixtureKind.NEGATIVE, environment_data(relation_count=0), RuleOutcome.FAIL),
        (
            FixtureKind.NOT_APPLICABLE,
            environment_data(kind="software_design"),
            RuleOutcome.NOT_APPLICABLE,
        ),
        (
            FixtureKind.INDETERMINATE,
            environment_data(safety=ValueCell(ValueState.UNKNOWN)),
            RuleOutcome.INDETERMINATE,
        ),
        (
            FixtureKind.EXCEPTION,
            environment_data(active_exception_rule_uids=frozenset({rule_uid})),
            RuleOutcome.NOT_APPLICABLE,
        ),
        (
            FixtureKind.DEVIATION,
            environment_data(
                relation_count=0,
                active_deviation_rule_uids=frozenset({rule_uid}),
            ),
            RuleOutcome.SUPPRESSED_BY_DEVIATION,
        ),
        (
            FixtureKind.CONFLICT,
            environment_data(conflicted_rule_uids=frozenset({rule_uid})),
            RuleOutcome.INDETERMINATE,
        ),
        (FixtureKind.MIGRATION, environment_data(schema_version=2), RuleOutcome.PASS),
    )
    fixtures = tuple(
        RuleFixtureDefinition(
            fixture_uid=f"018f0000-0000-7000-8000-{index:012d}",
            kind=kind,
            environment=data,
            expected_outcome=outcome,
        )
        for index, (kind, data, outcome) in enumerate(cases, 201)
    )
    return RuleDefinition(
        rule_uid=rule_uid,
        rule_revision_uid="018f0000-0000-7000-8000-000000000102",
        source=RuleSourceText(
            text=statement,
            language="en",
            source_hash=semantic_hash({"text": statement}),
            interpretation_note="verified_by minimum one",
        ),
        target_selector=KindIs("software_requirement").to_data(),
        applicability=AllOf(
            (KindIs("software_requirement"), FieldKnown("safety_level"))
        ).to_data(),
        modality=NormativeModality.OBLIGATION,
        constraints=(RelationMinimum("verified_by", 1).to_data(),),
        evaluation=EvaluationSpecification(),
        enforcement=(
            EnforcementMapping(
                operation="approve_revision",
                effect=EnforcementEffect.BLOCK_OPERATION,
            ),
        ),
        authority=AuthorityDeclaration(
            source_uid="018f0000-0000-7000-8000-000000000103",
            profile_revision_uid="018f0000-0000-7000-8000-000000000104",
            issuer_uid="018f0000-0000-7000-8000-000000000105",
            scope={"project": "demo"},
            may_refine=True,
            may_relax=False,
            deviation_allowed=True,
            non_overridable=False,
        ),
        exception_policy={},
        deviation_policy=DeviationPolicy(
            allowed=True, required_approval_roles=("risk_deviation",)
        ),
        explanation_map={"constraint": "shall have verification trace"},
        fixtures=fixtures,
    )


def test_three_valued_logic_and_absent_null_unknown_are_distinct() -> None:
    unknown = FieldEquals("missing", "x")
    false = KindIs("other")
    true = KindIs("software_requirement")
    env = environment()
    assert AllOf((unknown, false)).evaluate(env).result == ApplicabilityResult.NOT_APPLICABLE
    assert AnyOf((unknown, true)).evaluate(env).result == ApplicabilityResult.APPLICABLE
    assert Not(unknown).evaluate(env).result == ApplicabilityResult.INDETERMINATE
    assert FieldKnown("missing").evaluate(env).result == ApplicabilityResult.INDETERMINATE
    null_env = environment(safety=ValueCell.present(None))
    assert FieldKnown("safety_level").evaluate(null_env).result == ApplicabilityResult.NOT_APPLICABLE


def test_units_are_checked_by_dimension() -> None:
    assert UNITS.compare(Quantity(Decimal(120), "s"), Quantity(Decimal(120000), "ms")) == 0
    constraint = QuantityMaximum("timeout", Quantity(Decimal(2), "s"))
    ok = environment()
    ok.fields["timeout"] = ValueCell.present(Quantity(Decimal(1500), "ms"))
    assert constraint.evaluate(ok, UNITS).result == "satisfied"
    ok.fields["timeout"] = ValueCell.present(Quantity(Decimal(2), "mm"))
    assert constraint.evaluate(ok, UNITS).result == "evaluator_error"


def test_schema_definition_compiles_and_runs_all_fixture_kinds() -> None:
    definition = source()
    SchemaCatalog().validate(
        "rule-definition.schema.json",
        definition.model_dump(mode="json", exclude_none=True),
    )
    result = RuleCompiler({"statement": str, "safety_level": str}, UNITS).compile(
        definition
    )
    assert result.passed
    assert result.ast is not None
    assert {outcome for _, outcome in result.fixture_outcomes} >= {
        RuleOutcome.PASS,
        RuleOutcome.FAIL,
        RuleOutcome.NOT_APPLICABLE,
        RuleOutcome.INDETERMINATE,
        RuleOutcome.SUPPRESSED_BY_DEVIATION,
    }


def test_schema_aggregate_constraint_is_executable_not_schema_only() -> None:
    definition = source()
    aggregate = {
        "op": "aggregate",
        "function": "count",
        "path": {"roles": ["verified_by"], "max_depth": 1},
        "comparison": "gte",
        "expected": 1,
    }
    definition = RuleDefinition.model_validate(
        definition.model_dump(mode="json", exclude={"content_hash"})
        | {"constraints": [aggregate]}
    )
    SchemaCatalog().validate(
        "rule-definition.schema.json",
        definition.model_dump(mode="json", exclude_none=True),
    )
    result = RuleCompiler({"statement": str, "safety_level": str}, UNITS).compile(
        definition
    )
    assert result.passed
    assert result.ast is not None
    assert result.ast.constraints[0].to_data() == aggregate


def test_external_evaluation_kind_is_preserved_and_requires_evidence() -> None:
    definition = source()
    fixtures = []
    for fixture in definition.fixtures:
        environment_value = dict(fixture.environment)
        environment_value["external_rule_outcomes"] = {
            definition.rule_revision_uid: fixture.expected_outcome.value
        }
        fixtures.append(fixture.model_copy(update={"environment": environment_value}))
    definition = RuleDefinition.model_validate(
        definition.model_dump(mode="json", exclude={"content_hash"})
        | {
            "evaluation": {
                "kind": "external_tool",
                "validator_uid": "static-analyzer",
                "advisory_only": False,
            },
            "fixtures": [item.model_dump(mode="json") for item in fixtures],
        }
    )
    result = RuleCompiler({"statement": str, "safety_level": str}, UNITS).compile(
        definition
    )
    assert result.passed and result.ast is not None
    assert result.ast.evaluation.kind == "external_tool"
    without_evidence = evaluate_rule(result.ast, environment(), UNITS)
    assert without_evidence.outcome is RuleOutcome.NOT_EVALUATED
    incomplete = definition.model_copy(update={"fixtures": definition.fixtures[:1]})
    assert not RuleCompiler({"safety_level": str}, UNITS).compile(incomplete).passed


def test_unknown_path_and_unbounded_relation_path_fail_compilation() -> None:
    invalid = source().model_copy(
        update={"constraints": (FieldRequired("missing").to_data(),)}
    )
    assert not RuleCompiler({}, UNITS).compile(invalid).passed
    try:
        RelationMinimum("verified_by", 1, maximum_depth=0)
    except ValueError as error:
        assert "finite" in str(error)
    else:
        raise AssertionError("unbounded relation path was accepted")


def test_modality_conflict_and_restricted_projections_are_explainable() -> None:
    compiled = RuleCompiler({"statement": str, "safety_level": str}, UNITS).compile(
        source()
    )
    assert compiled.ast is not None
    prohibition = replace(compiled.ast, modality=NormativeModality.PROHIBITION)
    assert detect_direct_conflict(compiled.ast, prohibition)
    assert project_to_shacl(compiled.ast)["lesr:rule"] == source().rule_uid
    assert compiled.ast.ast_hash in project_to_rego(compiled.ast)


def test_constant_applicability_is_available_for_informational_rules() -> None:
    node = ConstantApplicability(ApplicabilityResult.APPLICABLE)
    assert node.evaluate(environment()).result == ApplicabilityResult.APPLICABLE
