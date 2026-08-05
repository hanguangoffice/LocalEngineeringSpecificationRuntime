"""Profile compilation into one deterministic effective model."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from pydantic import model_validator

from lesr.domain.rules import (
    FieldSymbol,
    RuleAST,
    RuleCompiler,
    RuleDefinition,
    UnitDefinition,
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
    symbols: tuple[FieldSymbol, ...]
    units: tuple[UnitDefinition, ...]
    review_policies: tuple[ReviewPolicy, ...]
    context_policies: tuple[ContextPolicyDefinition, ...]
    conflicts: tuple[str, ...]
    effective_model_hash: str


@dataclass(frozen=True, slots=True)
class ReviewPolicy:
    operation: str
    required_roles: tuple[str, ...]
    minimum_approval_count: int = 1
    require_preparer_independence: bool = True
    blocking_effects: tuple[str, ...] = (
        "block_operation",
        "require_deviation",
    )


@dataclass(frozen=True, slots=True)
class ContextPolicyDefinition:
    task_type: str
    mandatory_predicates: tuple[str, ...] = ()
    conditional_predicates: tuple[str, ...] = ()
    invariant_object_uids: tuple[str, ...] = ()
    forbidden_sensitivities: tuple[str, ...] = ()


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
        self._verify_authority_graph(selected, set(profile_uids))
        symbols = self._compile_symbols(profiles)
        units = self._compile_units(profiles)
        compiled_rules: list[RuleAST] = []
        compiler = RuleCompiler({item.path: item for item in symbols}, UnitRegistry(units))
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
                        for value in [
                            value
                            if isinstance(value, str)
                            else value.get("kind")
                            if isinstance(value, dict)
                            else None
                        ]
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
                        for value in [
                            value
                            if isinstance(value, str)
                            else value.get("predicate")
                            if isinstance(value, dict)
                            else None
                        ]
                        if isinstance(value, str)
                    }
                )
            )
        review_policies = self._compile_review_policies(profiles)
        context_policies = self._compile_context_policies(profiles)
        effective_model_hash = semantic_hash(
            {
                "profile_revision_uids": profile_uids,
                "rule_revision_uids": selected_uids,
                "rule_hashes": [rule.ast_hash for rule in compiled],
                "resource_kinds": resource_kinds,
                "relation_types": relation_types,
                "symbols": [
                    {"path": item.path, "value_type": item.value_type, "unit": item.unit}
                    for item in symbols
                ],
                "units": [
                    {
                        "unit": item.unit,
                        "dimension": item.dimension,
                        "scale_to_base": str(item.scale_to_base),
                    }
                    for item in units
                ],
                "review_policies": [
                    {
                        "operation": item.operation,
                        "required_roles": item.required_roles,
                        "minimum_approval_count": item.minimum_approval_count,
                        "require_preparer_independence": item.require_preparer_independence,
                        "blocking_effects": item.blocking_effects,
                    }
                    for item in review_policies
                ],
                "context_policies": [
                    {
                        "task_type": item.task_type,
                        "mandatory_predicates": item.mandatory_predicates,
                        "conditional_predicates": item.conditional_predicates,
                        "invariant_object_uids": item.invariant_object_uids,
                        "forbidden_sensitivities": item.forbidden_sensitivities,
                    }
                    for item in context_policies
                ],
                "conflicts": conflicts,
            }
        )
        return EffectiveModel(
            profile_revision_uids=tuple(profile_uids),
            rule_revision_uids=selected_uids,
            rules=compiled,
            resource_kinds=resource_kinds,
            relation_types=relation_types,
            symbols=symbols,
            units=units,
            review_policies=review_policies,
            context_policies=context_policies,
            conflicts=conflicts,
            effective_model_hash=effective_model_hash,
        )

    @staticmethod
    def _verify_authority_graph(
        rules: tuple[RuleDefinition, ...], profile_uids: set[str]
    ) -> None:
        known = {rule.rule_revision_uid for rule in rules}
        graph: dict[str, set[str]] = defaultdict(set)
        for rule in rules:
            if rule.authority.profile_revision_uid not in profile_uids:
                raise ValueError("rule authority references an unselected profile revision")
            if (
                rule.authority.valid_from is not None
                and rule.authority.valid_until is not None
                and rule.authority.valid_from >= rule.authority.valid_until
            ):
                raise ValueError("rule authority validity interval is empty")
            for overridden in rule.authority.overrides:
                if overridden not in known:
                    raise ValueError(
                        f"authority override references unavailable rule: {overridden}"
                    )
                graph[rule.rule_revision_uid].add(overridden)
                target = next(item for item in rules if item.rule_revision_uid == overridden)
                if target.authority.non_overridable:
                    raise ValueError("authority attempts to override a non-overridable rule")
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

    @staticmethod
    def _compile_symbols(profiles: tuple[ProfileRevision, ...]) -> tuple[FieldSymbol, ...]:
        symbols: dict[str, FieldSymbol] = {}
        for profile in profiles:
            for resource_kind in profile.resource_kinds:
                if not isinstance(resource_kind, dict):
                    continue
                fields = resource_kind.get("fields", [])
                if not isinstance(fields, list):
                    raise TypeError("profile resource kind fields must be an array")
                for raw in fields:
                    if not isinstance(raw, dict):
                        raise TypeError("profile field symbol must be an object")
                    path = str(raw["path"])
                    candidate = FieldSymbol(
                        path,
                        str(raw["type"]),
                        str(raw["unit"]) if raw.get("unit") is not None else None,
                    )
                    existing = symbols.get(path)
                    if existing is not None and existing != candidate:
                        raise ValueError(f"conflicting profile field symbol: {path}")
                    symbols[path] = candidate
        return tuple(sorted(symbols.values(), key=lambda item: item.path))

    @staticmethod
    def _compile_units(profiles: tuple[ProfileRevision, ...]) -> tuple[UnitDefinition, ...]:
        units: dict[str, UnitDefinition] = {}
        for profile in profiles:
            for policy in profile.configuration_policies:
                if not isinstance(policy, dict):
                    continue
                raw_units = policy.get("units", [])
                if not isinstance(raw_units, list):
                    raise TypeError("profile units must be an array")
                for raw in raw_units:
                    if not isinstance(raw, dict):
                        raise TypeError("profile unit must be an object")
                    candidate = UnitDefinition(
                        str(raw["unit"]),
                        str(raw["dimension"]),
                        Decimal(str(raw["scale_to_base"])),
                    )
                    existing = units.get(candidate.unit)
                    if existing is not None and existing != candidate:
                        raise ValueError(f"conflicting profile unit: {candidate.unit}")
                    units[candidate.unit] = candidate
        return tuple(sorted(units.values(), key=lambda item: item.unit))

    @staticmethod
    def _compile_review_policies(
        profiles: tuple[ProfileRevision, ...]
    ) -> tuple[ReviewPolicy, ...]:
        compiled: dict[str, ReviewPolicy] = {}
        for profile in profiles:
            for raw in profile.review_policies:
                if not isinstance(raw, dict):
                    raise TypeError("profile review policy must be an object")
                operation = str(raw.get("operation", "*"))
                roles = raw.get("required_roles", [])
                effects = raw.get(
                    "blocking_effects", ["block_operation", "require_deviation"]
                )
                if not isinstance(roles, list) or not isinstance(effects, list):
                    raise TypeError("profile review roles/effects must be arrays")
                candidate = ReviewPolicy(
                    operation,
                    tuple(sorted(str(item) for item in roles)),
                    int(str(raw.get("minimum_approval_count", 1))),
                    bool(raw.get("require_preparer_independence", True)),
                    tuple(sorted(str(item) for item in effects)),
                )
                if candidate.minimum_approval_count < 1 or not candidate.required_roles:
                    raise ValueError("review policy requires roles and a positive quorum")
                existing = compiled.get(operation)
                if existing is not None and existing != candidate:
                    raise ValueError(f"conflicting review policy for operation: {operation}")
                compiled[operation] = candidate
        return tuple(sorted(compiled.values(), key=lambda item: item.operation))

    @staticmethod
    def _compile_context_policies(
        profiles: tuple[ProfileRevision, ...]
    ) -> tuple[ContextPolicyDefinition, ...]:
        compiled: list[ContextPolicyDefinition] = []
        for profile in profiles:
            for raw in profile.configuration_policies:
                if not isinstance(raw, dict) or "context" not in raw:
                    continue
                context = raw["context"]
                if not isinstance(context, dict):
                    raise TypeError("profile context policy must be an object")
                for task_type, value in context.items():
                    if not isinstance(value, dict):
                        raise TypeError("task context policy must be an object")
                    compiled.append(
                        ContextPolicyDefinition(
                            str(task_type),
                            _string_tuple(value.get("mandatory_predicates", [])),
                            _string_tuple(value.get("conditional_predicates", [])),
                            _string_tuple(value.get("invariant_object_uids", [])),
                            _string_tuple(value.get("forbidden_sensitivities", [])),
                        )
                    )
        return tuple(sorted(compiled, key=lambda item: item.task_type))


def _string_tuple(value: JsonValue | None) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise TypeError("profile policy value must be an array")
    return tuple(sorted(str(item) for item in value))
