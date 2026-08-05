"""Profile compilation into one deterministic effective model."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Literal

from pydantic import model_validator

from lesr.domain.rules import (
    RuleAST,
    RuleCompiler,
    RuleDefinition,
    UnitRegistry,
    detect_direct_conflict,
)
from lesr.domain.semantic import FrozenModel, JsonValue, document_hash, semantic_hash


class ProfileRevision(FrozenModel):
    """Persistent Profile DTO; its fields map one-to-one to profile.schema.json."""

    schema_version: Literal["1.0"] = "1.0"
    resource_type: Literal["profile_revision"] = "profile_revision"
    profile_uid: str
    profile_revision_uid: str
    profile_kind: Literal["core", "domain", "project", "tool_mapping", "tailoring"]
    resource_kinds: tuple[JsonValue, ...] = ()
    relation_types: tuple[JsonValue, ...] = ()
    rule_revision_uids: tuple[str, ...] = ()
    configuration_policies: tuple[JsonValue, ...] = ()
    review_policies: tuple[JsonValue, ...] = ()
    content_hash: str = ""

    @model_validator(mode="after")
    def valid_hash(self) -> ProfileRevision:
        expected = document_hash(
            self.model_dump(mode="json", exclude_none=True), "content_hash"
        )
        if self.content_hash and self.content_hash != expected:
            raise ValueError("profile content_hash is invalid")
        if not self.content_hash:
            object.__setattr__(self, "content_hash", expected)
        return self


@dataclass(frozen=True, slots=True)
class EffectiveModel:
    profile_revision_uids: tuple[str, ...]
    rule_revision_uids: tuple[str, ...]
    rules: tuple[RuleAST, ...]
    resource_kinds: tuple[str, ...]
    relation_types: tuple[str, ...]
    conflicts: tuple[str, ...]
    effective_model_hash: str


class ProfileCompiler:
    """Compile selected Profile and Rule revisions without executing profile code."""

    def compile(
        self,
        profiles: tuple[ProfileRevision, ...],
        rules: tuple[RuleDefinition, ...],
    ) -> EffectiveModel:
        if not profiles:
            raise ValueError("effective model requires at least one profile revision")
        profile_uids = [profile.profile_revision_uid for profile in profiles]
        if len(profile_uids) != len(set(profile_uids)):
            raise ValueError("duplicate profile revision in effective model")
        by_rule = {rule.rule_revision_uid: rule for rule in rules}
        selected_uids = tuple(
            dict.fromkeys(
                rule_uid
                for profile in profiles
                for rule_uid in profile.rule_revision_uids
            )
        )
        missing = sorted(set(selected_uids) - set(by_rule))
        if missing:
            raise ValueError("profile references unavailable rules: " + ", ".join(missing))
        selected = tuple(by_rule[uid] for uid in selected_uids)
        self._verify_authority_graph(selected)
        compiled_rules: list[RuleAST] = []
        compiler = RuleCompiler({}, UnitRegistry(()))
        for rule in selected:
            result = compiler.compile(rule)
            if not result.passed or result.ast is None:
                raise ValueError(
                    f"rule {rule.rule_revision_uid} failed compilation: "
                    + "; ".join(item.message for item in result.diagnostics)
                )
            compiled_rules.append(result.ast)
        compiled = tuple(compiled_rules)
        conflicts = tuple(
            f"{left.rule_revision_uid}:{right.rule_revision_uid}:direct contradiction"
            for index, left in enumerate(compiled)
            for right in compiled[index + 1 :]
            if detect_direct_conflict(left, right)
        )
        resource_kinds = tuple(
                sorted(
                    {
                        value
                        for profile in profiles
                        for value in profile.resource_kinds
                        if isinstance(value, str)
                    }
                )
            )
        relation_types = tuple(
                sorted(
                    {
                        value
                        for profile in profiles
                        for value in profile.relation_types
                        if isinstance(value, str)
                    }
                )
            )
        effective_model_hash = semantic_hash(
            {
                "profile_revision_uids": profile_uids,
                "rule_revision_uids": selected_uids,
                "rule_hashes": [rule.ast_hash for rule in compiled],
                "resource_kinds": resource_kinds,
                "relation_types": relation_types,
                "conflicts": conflicts,
            }
        )
        return EffectiveModel(
            profile_revision_uids=tuple(profile_uids),
            rule_revision_uids=selected_uids,
            rules=compiled,
            resource_kinds=resource_kinds,
            relation_types=relation_types,
            conflicts=conflicts,
            effective_model_hash=effective_model_hash,
        )

    @staticmethod
    def _verify_authority_graph(rules: tuple[RuleDefinition, ...]) -> None:
        known = {rule.rule_revision_uid for rule in rules}
        graph: dict[str, set[str]] = defaultdict(set)
        for rule in rules:
            for overridden in rule.authority.overrides:
                if overridden not in known:
                    raise ValueError(
                        f"authority override references unavailable rule: {overridden}"
                    )
                graph[rule.rule_revision_uid].add(overridden)
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(uid: str) -> None:
            if uid in visiting:
                raise ValueError("authority partial order contains a cycle")
            if uid in visited:
                return
            visiting.add(uid)
            for child in graph[uid]:
                visit(child)
            visiting.remove(uid)
            visited.add(uid)

        for uid in known:
            visit(uid)
