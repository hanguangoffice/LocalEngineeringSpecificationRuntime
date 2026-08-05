from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

from prototypes.lesr_v1.p2_rules import (
    AllOf,
    AnyOf,
    ApplicabilityResult,
    ConstantApplicability,
    EnforcementEffect,
    EvaluationEnvironment,
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
    RuleFixture,
    RuleOutcome,
    RuleSource,
    UnitDefinition,
    UnitRegistry,
    ValueCell,
    ValueState,
    detect_direct_conflict,
    project_to_rego,
    project_to_shacl,
)

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


def source() -> RuleSource:
    rule_uid = "RULE-TRACE-1"
    fixtures = (
        RuleFixture("positive", FixtureKind.POSITIVE, environment(), RuleOutcome.PASS),
        RuleFixture(
            "negative", FixtureKind.NEGATIVE, environment(relation_count=0), RuleOutcome.FAIL
        ),
        RuleFixture(
            "not-applicable",
            FixtureKind.NOT_APPLICABLE,
            environment(kind="software_design"),
            RuleOutcome.NOT_APPLICABLE,
        ),
        RuleFixture(
            "indeterminate",
            FixtureKind.INDETERMINATE,
            environment(safety=ValueCell(ValueState.UNKNOWN)),
            RuleOutcome.INDETERMINATE,
        ),
        RuleFixture(
            "exception",
            FixtureKind.EXCEPTION,
            environment(active_exception_rule_uids=frozenset({rule_uid})),
            RuleOutcome.NOT_APPLICABLE,
        ),
        RuleFixture(
            "deviation",
            FixtureKind.DEVIATION,
            environment(
                relation_count=0, active_deviation_rule_uids=frozenset({rule_uid})
            ),
            RuleOutcome.SUPPRESSED_BY_DEVIATION,
        ),
        RuleFixture(
            "conflict",
            FixtureKind.CONFLICT,
            environment(conflicted_rule_uids=frozenset({rule_uid})),
            RuleOutcome.INDETERMINATE,
        ),
        RuleFixture(
            "migration",
            FixtureKind.MIGRATION,
            environment(schema_version=2),
            RuleOutcome.PASS,
        ),
    )
    return RuleSource(
        rule_uid=rule_uid,
        revision_uid="RULE-TRACE-1@1",
        schema_version=1,
        authoritative_statement="Approved requirements shall have verification trace.",
        interpretation_note="verified_by minimum one",
        target_kind="software_requirement",
        applicability=AllOf((KindIs("software_requirement"), FieldKnown("safety_level"))),
        modality=NormativeModality.OBLIGATION,
        constraint=RelationMinimum("verified_by", 1),
        enforcement={"approve_revision": EnforcementEffect.BLOCK_OPERATION},
        authority="profile/aspice-like@1",
        deviation_allowed=True,
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


def test_compiler_requires_all_fixture_kinds_and_passes_reference_rule() -> None:
    compiler = RuleCompiler({"statement": str, "safety_level": str}, UNITS)
    result = compiler.compile(source())
    assert result.passed
    assert result.ast is not None
    assert {outcome for _, outcome in result.fixture_outcomes} >= {
        RuleOutcome.PASS,
        RuleOutcome.FAIL,
        RuleOutcome.NOT_APPLICABLE,
        RuleOutcome.INDETERMINATE,
        RuleOutcome.SUPPRESSED_BY_DEVIATION,
    }
    incomplete = replace(source(), fixtures=source().fixtures[:1])
    assert not compiler.compile(incomplete).passed


def test_unknown_path_and_unbounded_relation_path_fail_compilation_or_construction() -> None:
    compiler = RuleCompiler({}, UNITS)
    invalid = replace(source(), constraint=FieldRequired("missing"))
    assert not compiler.compile(invalid).passed
    try:
        RelationMinimum("verified_by", 1, maximum_depth=0)
    except ValueError as error:
        assert "finite" in str(error)
    else:
        raise AssertionError("unbounded relation path was accepted")


def test_modality_conflict_and_restricted_projections_are_explainable() -> None:
    compiled = RuleCompiler({"statement": str, "safety_level": str}, UNITS).compile(source())
    assert compiled.ast is not None
    prohibition = replace(compiled.ast, modality=NormativeModality.PROHIBITION)
    assert detect_direct_conflict(compiled.ast, prohibition)
    assert project_to_shacl(compiled.ast)["lesr:rule"] == source().rule_uid
    assert compiled.ast.ast_hash in project_to_rego(compiled.ast)


def test_constant_applicability_is_available_for_informational_rules() -> None:
    node = ConstantApplicability(ApplicabilityResult.APPLICABLE)
    assert node.evaluate(environment()).result == ApplicabilityResult.APPLICABLE
