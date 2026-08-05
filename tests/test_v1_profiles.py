from __future__ import annotations

import pytest

from lesr.adapters.schemas import SchemaCatalog
from lesr.domain.profiles import ProfileCompiler, ProfileRevision
from lesr.domain.semantic import uuid7_candidate
from tests.test_v1_rules import source


def profile(rule_uid: str) -> ProfileRevision:
    return ProfileRevision(
        profile_uid=uuid7_candidate(),
        profile_revision_uid=uuid7_candidate(),
        profile_kind="project",
        resource_kinds=("software_requirement", "software_design"),
        relation_types=("verified_by",),
        rule_revision_uids=(rule_uid,),
        configuration_policies=({"latest_fallback": False},),
        review_policies=({"required_roles": ["reviewer"]},),
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
        profile_revision_uid=uuid7_candidate(),
        profile_kind="project",
        rule_revision_uids=(left.rule_revision_uid, right_uid),
    )
    with pytest.raises(ValueError, match="cycle"):
        ProfileCompiler().compile((selected,), (left, right))
