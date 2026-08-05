from __future__ import annotations

import pytest

from lesr.adapters.schemas import SchemaCatalog
from lesr.domain.profiles import ProfileCompiler, ProfileRevision
from lesr.domain.rules import FixtureKind, RuleDefinition, RuleOutcome
from lesr.domain.semantic import uuid7_candidate
from tests.test_v1_rules import source


def profile(rule_uid: str) -> ProfileRevision:
    return ProfileRevision(
        profile_uid=uuid7_candidate(),
        profile_revision_uid="018f0000-0000-7000-8000-000000000104",
        profile_kind="project",
        resource_kinds=("software_requirement", "software_design"),
        relation_types=("verified_by",),
        rule_revision_uids=(rule_uid,),
        configuration_policies=({"latest_fallback": False},),
        review_policies=(
            {
                "operation": "apply_transaction",
                "required_roles": ["reviewer"],
                "minimum_approval_count": 1,
            },
        ),
    )


def test_profile_compiles_schema_rules_into_deterministic_effective_model() -> None:
    definition = source()
    selected = profile(definition.rule_revision_uid)
    SchemaCatalog().validate(
        "profile.schema.json", selected.model_dump(mode="json", exclude_none=True)
    )
    first = ProfileCompiler().compile((selected,), (definition,))
    second = ProfileCompiler().compile((selected,), (definition,))
    assert first.effective_model_hash == second.effective_model_hash
    assert first.rule_revision_uids == (definition.rule_revision_uid,)
    assert first.rules[0].rule_revision_uid == definition.rule_revision_uid


def test_profile_rejects_unavailable_rule_instead_of_silently_omitting_it() -> None:
    selected = profile(uuid7_candidate())
    with pytest.raises(ValueError, match="unavailable rules"):
        ProfileCompiler().compile((selected,), ())


def test_authority_is_a_partial_order_and_cycles_are_rejected() -> None:
    left = source()
    right_uid = uuid7_candidate()
    right = left.model_copy(
        update={
            "rule_uid": uuid7_candidate(),
            "rule_revision_uid": right_uid,
            "authority": left.authority.model_copy(
                update={"overrides": (left.rule_revision_uid,)}
            ),
        }
    )
    left = left.model_copy(
        update={
            "authority": left.authority.model_copy(update={"overrides": (right_uid,)})
        }
    )
    selected = ProfileRevision(
        profile_uid=uuid7_candidate(),
        profile_revision_uid="018f0000-0000-7000-8000-000000000104",
        profile_kind="project",
        rule_revision_uids=(left.rule_revision_uid, right_uid),
    )
    with pytest.raises(ValueError, match="cycle"):
        ProfileCompiler().compile((selected,), (left, right))


def test_profile_supplies_field_symbols_for_common_field_rules() -> None:
    definition = source()
    expected = {
        FixtureKind.POSITIVE: RuleOutcome.PASS,
        FixtureKind.NEGATIVE: RuleOutcome.PASS,
        FixtureKind.NOT_APPLICABLE: RuleOutcome.NOT_APPLICABLE,
        FixtureKind.INDETERMINATE: RuleOutcome.INDETERMINATE,
        FixtureKind.EXCEPTION: RuleOutcome.NOT_APPLICABLE,
        FixtureKind.DEVIATION: RuleOutcome.PASS,
        FixtureKind.CONFLICT: RuleOutcome.INDETERMINATE,
        FixtureKind.MIGRATION: RuleOutcome.PASS,
    }
    definition = RuleDefinition.model_validate(
        definition.model_dump(mode="json", exclude={"content_hash"})
        | {
            "constraints": [{"op": "field_required", "path": "statement"}],
            "fixtures": [
                fixture.model_copy(
                    update={"expected_outcome": expected[fixture.kind]}
                ).model_dump(mode="json")
                for fixture in definition.fixtures
            ],
        }
    )
    selected = ProfileRevision(
        profile_uid=uuid7_candidate(),
        profile_revision_uid=definition.authority.profile_revision_uid,
        profile_kind="project",
        resource_kinds=(
            {
                "kind": "software_requirement",
                "fields": [{"path": "statement", "type": "string"}],
            },
        ),
        rule_revision_uids=(definition.rule_revision_uid,),
        review_policies=(
            {
                "operation": "apply_transaction",
                "required_roles": ["technical"],
                "minimum_approval_count": 1,
            },
        ),
    )
    model = ProfileCompiler().compile((selected,), (definition,))
    assert model.symbols[0].path == "statement"
    assert model.review_policies[0].required_roles == ("technical",)
