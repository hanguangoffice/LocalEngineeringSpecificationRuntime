"""LESR v1 explicit configuration resolution and auditable context contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum


class ClosureStatus(StrEnum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    INDETERMINATE = "indeterminate"
    INCONSISTENT = "inconsistent"


class ResolutionStatus(StrEnum):
    RESOLVED = "resolved"
    INDETERMINATE = "indeterminate"
    NOT_FOUND = "not_found"


class CompletenessStatus(StrEnum):
    COMPLETE_UNDER_MODEL = "complete_under_model"
    INCOMPLETE_MISSING_RELATION = "incomplete_missing_relation"
    INCOMPLETE_UNKNOWN_SCOPE = "incomplete_unknown_scope"
    INCOMPLETE_BUDGET = "incomplete_budget"
    INCOMPLETE_INDEX = "incomplete_index"
    INCOMPLETE_CONFIDENTIALITY = "incomplete_confidentiality"
    INDETERMINATE_CONFIGURATION = "indeterminate_configuration"
    INDETERMINATE_PROFILE_CONFLICT = "indeterminate_profile_conflict"


class ContextSection(StrEnum):
    INVARIANT = "invariant"
    MANDATORY = "mandatory"
    CONDITIONAL = "conditional"
    SUPPORTING = "supporting"
    BACKGROUND = "background"


HIGH_RISK_OPERATIONS = frozenset(
    {"approve_revision", "apply_transaction", "create_baseline", "approve_deviation"}
)


@dataclass(frozen=True, slots=True)
class RevisionDescriptor:
    object_uid: str
    revision_uid: str
    revision_number: int
    maturity: str
    disposition: str = "active"
    variants: frozenset[str] = frozenset()
    valid_from: datetime | None = None
    valid_until: datetime | None = None

    def valid_at(self, instant: datetime) -> bool:
        return (self.valid_from is None or self.valid_from <= instant) and (
            self.valid_until is None or instant < self.valid_until
        )


@dataclass(frozen=True, slots=True)
class ConfigurationMembership:
    object_uid: str
    revision_uid: str


@dataclass(frozen=True, slots=True)
class ConfigurationDefinition:
    configuration_uid: str
    base_commit: str
    memberships: tuple[ConfigurationMembership, ...]
    profile_revision_uids: tuple[str, ...]
    effective_model_hash: str
    active_deviation_revision_uids: tuple[str, ...] = ()
    closure_status: ClosureStatus = ClosureStatus.COMPLETE


@dataclass(frozen=True, slots=True)
class EvaluationContext:
    repository: str
    project: str
    operation: str
    actor: str
    target_object_uids: tuple[str, ...]
    evaluation_time: datetime = field(default_factory=lambda: datetime.now(UTC))
    configuration_uid: str | None = None
    variant: str | None = None
    workspace_uid: str | None = None
    workspace_overlay: tuple[ConfigurationMembership, ...] = ()
    explicit_revisions: tuple[ConfigurationMembership, ...] = ()
    delegation_uid: str | None = None
    allow_latest_approved_fallback: bool = False


@dataclass(frozen=True, slots=True)
class ObjectResolution:
    object_uid: str
    status: ResolutionStatus
    revision_uid: str | None
    reason: str
    candidates: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class EffectiveResolution:
    context: EvaluationContext
    objects: tuple[ObjectResolution, ...]
    closure_status: ClosureStatus
    excluded_revisions: tuple[str, ...]
    unknowns: tuple[str, ...]
    conflicts: tuple[str, ...]

    @property
    def selected(self) -> dict[str, str]:
        return {
            item.object_uid: item.revision_uid
            for item in self.objects
            if item.status is ResolutionStatus.RESOLVED and item.revision_uid is not None
        }


class EffectiveResolver:
    def resolve(
        self,
        context: EvaluationContext,
        revisions: tuple[RevisionDescriptor, ...],
        configuration: ConfigurationDefinition | None,
    ) -> EffectiveResolution:
        by_object: dict[str, list[RevisionDescriptor]] = {}
        for revision in revisions:
            by_object.setdefault(revision.object_uid, []).append(revision)
        explicit = {item.object_uid: item.revision_uid for item in context.explicit_revisions}
        workspace = {item.object_uid: item.revision_uid for item in context.workspace_overlay}
        configured = (
            {item.object_uid: item.revision_uid for item in configuration.memberships}
            if configuration is not None
            else {}
        )
        results: list[ObjectResolution] = []
        excluded: list[str] = []
        unknowns: list[str] = []
        conflicts: list[str] = []
        object_scope = tuple(
            dict.fromkeys(
                context.target_object_uids
                + tuple(configured)
                + tuple(workspace)
                + tuple(explicit)
            )
        )
        for object_uid in object_scope:
            candidates = by_object.get(object_uid, [])
            selected: tuple[RevisionDescriptor, str] | None = None
            binding_failed = False
            for bindings, reason in (
                (explicit, "explicit pinned"),
                (workspace, "workspace candidate"),
                (configured, "configuration membership"),
            ):
                if object_uid not in bindings:
                    continue
                requested_uid = bindings[object_uid]
                selected = self._select_bound(object_uid, candidates, bindings, reason)
                if selected is None:
                    message = f"{object_uid}: {reason} revision {requested_uid} is unavailable"
                    results.append(
                        ObjectResolution(
                            object_uid,
                            ResolutionStatus.INDETERMINATE,
                            None,
                            message,
                            tuple(item.revision_uid for item in candidates),
                        )
                    )
                    conflicts.append(message)
                    unknowns.append(message)
                    binding_failed = True
                break
            if binding_failed:
                continue
            if selected is None:
                variant_matches = [
                    item
                    for item in candidates
                    if context.variant is not None
                    if item.valid_at(context.evaluation_time)
                    and context.variant in item.variants
                    and item.disposition not in {"retired", "superseded"}
                ]
                if len(variant_matches) == 1:
                    selected = variant_matches[0], "variant/time selector"
                elif len(variant_matches) > 1:
                    revision_uids = tuple(item.revision_uid for item in variant_matches)
                    results.append(
                        ObjectResolution(
                            object_uid,
                            ResolutionStatus.INDETERMINATE,
                            None,
                            "ambiguous variant/time selector",
                            revision_uids,
                        )
                    )
                    conflicts.append(
                        f"{object_uid}: ambiguous variant/time selector: {revision_uids}"
                    )
                    continue
            if selected is None and context.allow_latest_approved_fallback:
                if context.operation in HIGH_RISK_OPERATIONS:
                    conflicts.append(
                        f"{object_uid}: latest-approved fallback forbidden for {context.operation}"
                    )
                else:
                    approved = [
                        item
                        for item in candidates
                        if item.maturity == "approved" and item.disposition == "active"
                    ]
                    if approved:
                        latest = max(approved, key=lambda item: item.revision_number)
                        selected = (latest, "latest approved fallback")
            if selected is None:
                if len(candidates) > 1:
                    revision_uids = tuple(item.revision_uid for item in candidates)
                    results.append(
                        ObjectResolution(
                            object_uid,
                            ResolutionStatus.INDETERMINATE,
                            None,
                            "ambiguous unqualified current revision",
                            revision_uids,
                        )
                    )
                    conflicts.append(f"{object_uid}: ambiguous current: {revision_uids}")
                    continue
                results.append(
                    ObjectResolution(
                        object_uid,
                        ResolutionStatus.NOT_FOUND,
                        None,
                        "no uniquely resolvable revision",
                        tuple(item.revision_uid for item in candidates),
                    )
                )
                unknowns.append(f"{object_uid}: effective revision unknown")
                continue
            descriptor, reason = selected
            results.append(
                ObjectResolution(
                    object_uid, ResolutionStatus.RESOLVED, descriptor.revision_uid, reason
                )
            )
            excluded.extend(
                item.revision_uid for item in candidates if item.revision_uid != descriptor.revision_uid
            )
        base_closure = configuration.closure_status if configuration else ClosureStatus.PARTIAL
        if conflicts or any(item.status is ResolutionStatus.INDETERMINATE for item in results):
            closure = ClosureStatus.INDETERMINATE
        elif unknowns:
            closure = ClosureStatus.PARTIAL
        else:
            closure = base_closure
        return EffectiveResolution(
            context,
            tuple(results),
            closure,
            tuple(sorted(set(excluded))),
            tuple(unknowns),
            tuple(conflicts),
        )

    @staticmethod
    def _select_bound(
        object_uid: str,
        candidates: list[RevisionDescriptor],
        bindings: dict[str, str],
        reason: str,
    ) -> tuple[RevisionDescriptor, str] | None:
        revision_uid = bindings.get(object_uid)
        if revision_uid is None:
            return None
        return next(
            ((item, reason) for item in candidates if item.revision_uid == revision_uid), None
        )

@dataclass(frozen=True, slots=True)
class ContextResource:
    object_uid: str
    revision_uid: str
    kind: str
    title: str
    token_estimate: int
    sensitivity: str = "internal"


@dataclass(frozen=True, slots=True)
class ContextRelation:
    source_object_uid: str
    predicate: str
    target_object_uid: str
    active: bool = True


@dataclass(frozen=True, slots=True)
class EffectiveRuleReference:
    rule_revision_uid: str
    operations: frozenset[str]
    mandatory_object_uids: frozenset[str]


@dataclass(frozen=True, slots=True)
class ContextPolicy:
    invariant_object_uids: frozenset[str]
    mandatory_predicates: frozenset[str]
    conditional_predicates: frozenset[str] = frozenset()
    forbidden_sensitivities: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class ContextSelection:
    resource: ContextResource
    section: ContextSection
    reason: str
    relation_path: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class OmittedCandidate:
    revision_uid: str
    reason: str


@dataclass(frozen=True, slots=True)
class ContextContract:
    task_type: str
    evaluation_context: EvaluationContext
    selections: tuple[ContextSelection, ...]
    negative_context: tuple[OmittedCandidate, ...]
    active_deviation_revision_uids: tuple[str, ...]
    conflicts: tuple[str, ...]
    unknowns: tuple[str, ...]
    validation_obligations: tuple[str, ...]
    omitted_candidates: tuple[OmittedCandidate, ...]
    completeness: CompletenessStatus
    token_estimate: int


class ContextPlanner:
    def build(
        self,
        *,
        task_type: str,
        resolution: EffectiveResolution,
        resources: tuple[ContextResource, ...],
        relations: tuple[ContextRelation, ...],
        rules: tuple[EffectiveRuleReference, ...],
        policy: ContextPolicy,
        token_budget: int,
        configuration: ConfigurationDefinition | None,
        index_complete: bool = True,
    ) -> ContextContract:
        selected_revisions = set(resolution.selected.values())
        effective_by_object = resolution.selected
        current_resources = {
            item.object_uid: item
            for item in resources
            if effective_by_object.get(item.object_uid) == item.revision_uid
        }
        stale = [
            OmittedCandidate(item.revision_uid, "stale revision excluded by effective resolution")
            for item in resources
            if item.object_uid in effective_by_object and item.revision_uid not in selected_revisions
        ]
        mandatory: dict[str, ContextSelection] = {}
        for uid in policy.invariant_object_uids:
            if uid in current_resources:
                mandatory[uid] = ContextSelection(
                    current_resources[uid], ContextSection.INVARIANT, "profile invariant"
                )
        for uid in resolution.context.target_object_uids:
            if uid in current_resources:
                mandatory[uid] = ContextSelection(
                    current_resources[uid], ContextSection.MANDATORY, "explicit task target"
                )
        targets = set(resolution.context.target_object_uids)
        conditional: dict[str, ContextSelection] = {}
        for relation in relations:
            if not relation.active:
                continue
            linked: str | None = None
            if relation.source_object_uid in targets:
                linked = relation.target_object_uid
            elif relation.target_object_uid in targets:
                linked = relation.source_object_uid
            if linked is None or linked not in current_resources:
                continue
            if relation.predicate in policy.mandatory_predicates:
                mandatory.setdefault(
                    linked,
                    ContextSelection(
                        current_resources[linked],
                        ContextSection.MANDATORY,
                        f"mandatory relation {relation.predicate}",
                        (relation.predicate,),
                    ),
                )
            elif relation.predicate in policy.conditional_predicates:
                conditional.setdefault(
                    linked,
                    ContextSelection(
                        current_resources[linked],
                        ContextSection.CONDITIONAL,
                        f"conditional relation {relation.predicate}",
                        (relation.predicate,),
                    ),
                )
        for rule in rules:
            if resolution.context.operation not in rule.operations:
                continue
            for uid in rule.mandatory_object_uids:
                if uid in current_resources:
                    mandatory.setdefault(
                        uid,
                        ContextSelection(
                            current_resources[uid],
                            ContextSection.MANDATORY,
                            f"effective rule {rule.rule_revision_uid}",
                        ),
                    )
        negative = list(stale)
        mandatory_confidentiality_omissions = False
        for uid, selection in tuple(mandatory.items()) + tuple(conditional.items()):
            if selection.resource.sensitivity in policy.forbidden_sensitivities:
                negative.append(
                    OmittedCandidate(selection.resource.revision_uid, "sensitivity boundary")
                )
                if uid in mandatory:
                    mandatory_confidentiality_omissions = True
                mandatory.pop(uid, None)
                conditional.pop(uid, None)
        ordered_mandatory = sorted(
            mandatory.values(), key=lambda item: (item.section != ContextSection.INVARIANT, item.resource.object_uid)
        )
        used = sum(item.resource.token_estimate for item in ordered_mandatory)
        selections = list(ordered_mandatory)
        omitted: list[OmittedCandidate] = []
        for item in sorted(conditional.values(), key=lambda candidate: candidate.resource.object_uid):
            if used + item.resource.token_estimate <= token_budget:
                selections.append(item)
                used += item.resource.token_estimate
            else:
                omitted.append(OmittedCandidate(item.resource.revision_uid, "token budget exceeded"))
        if resolution.closure_status in {ClosureStatus.INDETERMINATE, ClosureStatus.INCONSISTENT}:
            completeness = CompletenessStatus.INDETERMINATE_CONFIGURATION
        elif mandatory_confidentiality_omissions:
            completeness = CompletenessStatus.INCOMPLETE_CONFIDENTIALITY
        elif not index_complete:
            completeness = CompletenessStatus.INCOMPLETE_INDEX
        elif used > token_budget or omitted:
            completeness = CompletenessStatus.INCOMPLETE_BUDGET
        elif resolution.unknowns:
            completeness = CompletenessStatus.INCOMPLETE_UNKNOWN_SCOPE
        else:
            completeness = CompletenessStatus.COMPLETE_UNDER_MODEL
        deviations = configuration.active_deviation_revision_uids if configuration else ()
        obligations = tuple(
            sorted(rule.rule_revision_uid for rule in rules if resolution.context.operation in rule.operations)
        )
        return ContextContract(
            task_type,
            resolution.context,
            tuple(selections),
            tuple(negative),
            deviations,
            resolution.conflicts,
            resolution.unknowns,
            obligations,
            tuple(omitted),
            completeness,
            used,
        )
