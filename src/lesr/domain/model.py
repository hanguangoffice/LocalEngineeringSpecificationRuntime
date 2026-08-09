"""LESR 1.0 normative semantic model and deterministic profile compiler."""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
from enum import IntEnum, StrEnum
from typing import Annotated, Literal

from pydantic import Field, model_validator

from lesr.domain.semantic import (
    BindingMode,
    CoreRelationRole,
    CoreResourceClass,
    FrozenModel,
    ImmutableRecord,
    JsonValue,
    ProvenanceKind,
    document_hash,
    semantic_hash,
    uuid7_candidate,
)


class ProfileLayer(IntEnum):
    FOUNDATION = 0
    DOMAIN = 1
    INDUSTRY = 2
    ORGANIZATION = 3
    PROJECT = 4


class CompositionMode(StrEnum):
    EXTEND = "extend"
    REFINE = "refine"
    TAILOR = "tailor"
    REPLACE = "replace"


class DefinitionRevision(FrozenModel):
    revision_uid: str = Field(default_factory=uuid7_candidate)
    replaceable: bool = False
    authority: int = Field(default=0, ge=0)
    content_hash: str = ""

    @model_validator(mode="after")
    def calculate_hash(self) -> DefinitionRevision:
        expected = document_hash(self.model_dump(mode="json"), "content_hash")
        if self.content_hash and self.content_hash != expected:
            raise ValueError("definition content_hash is invalid")
        object.__setattr__(self, "content_hash", expected)
        return self


class FieldDefinition(FrozenModel):
    """Profile-owned structural contract for one semantic field."""

    path: str = Field(min_length=1, pattern=r"^/")
    value_type: Literal[
        "string", "integer", "boolean", "object", "array", "quantity", "timestamp"
    ]
    required: bool = False
    unit: str | None = None
    minimum: str | None = None
    maximum: str | None = None
    enum_values: tuple[JsonValue, ...] = ()
    minimum_items: int | None = Field(default=None, ge=0)
    maximum_items: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_contract(self) -> FieldDefinition:
        if self.value_type == "quantity" and not self.unit:
            raise ValueError("quantity fields require a Profile-owned unit")
        if self.value_type != "quantity" and self.unit is not None:
            raise ValueError("only quantity fields may declare a unit")
        if (
            self.minimum_items is not None
            and self.maximum_items is not None
            and self.minimum_items > self.maximum_items
        ):
            raise ValueError("field cardinality minimum exceeds maximum")
        if (
            self.minimum is not None
            and self.maximum is not None
            and Decimal(self.minimum) > Decimal(self.maximum)
        ):
            raise ValueError("field numeric minimum exceeds maximum")
        return self


class FragmentDefinition(FrozenModel):
    name: str = Field(min_length=1)
    minimum_count: int = Field(default=0, ge=0)
    maximum_count: int | None = Field(default=None, ge=0)
    fields: tuple[FieldDefinition, ...] = ()

    @model_validator(mode="after")
    def validate_fragment(self) -> FragmentDefinition:
        if self.maximum_count is not None and self.minimum_count > self.maximum_count:
            raise ValueError("fragment minimum exceeds maximum")
        paths = [item.path for item in self.fields]
        if len(paths) != len(set(paths)):
            raise ValueError("fragment field paths must be unique")
        return self


class ProfileUnitDefinition(FrozenModel):
    unit: str = Field(min_length=1)
    dimension: str = Field(min_length=1)
    scale_to_base: str = Field(pattern=r"^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$")


class FacetDefinitionRevision(DefinitionRevision):
    schema_version: Literal["1.0"] = "1.0"
    resource_type: Literal["facet_definition_revision"] = "facet_definition_revision"
    facet_uid: str = Field(default_factory=uuid7_candidate)
    name: str = Field(min_length=1)
    capabilities: tuple[str, ...] = ()
    fields: tuple[FieldDefinition, ...] = ()
    fragments: tuple[FragmentDefinition, ...] = ()

    @model_validator(mode="after")
    def unique_schema_members(self) -> FacetDefinitionRevision:
        paths = [item.path for item in self.fields]
        names = [item.name for item in self.fragments]
        if len(paths) != len(set(paths)) or len(names) != len(set(names)):
            raise ValueError("Facet field paths and Fragment names must be unique")
        return self


class KindDefinitionRevision(DefinitionRevision):
    schema_version: Literal["1.0"] = "1.0"
    resource_type: Literal["kind_definition_revision"] = "kind_definition_revision"
    kind_uid: str = Field(default_factory=uuid7_candidate)
    name: str = Field(min_length=1)
    core_class: CoreResourceClass
    required_facet_revision_uids: tuple[str, ...] = ()
    optional_facet_revision_uids: tuple[str, ...] = ()
    workflow_revision_uid: str | None = None

    @model_validator(mode="after")
    def facets_are_disjoint(self) -> KindDefinitionRevision:
        if set(self.required_facet_revision_uids) & set(self.optional_facet_revision_uids):
            raise ValueError("a facet cannot be both required and optional")
        return self


class WorkflowTransition(FrozenModel):
    from_state: str = Field(min_length=1)
    to_state: str = Field(min_length=1)
    roles: tuple[str, ...] = ()
    guards: tuple[str, ...] = ()
    evidence_kinds: tuple[str, ...] = ()


class WorkflowRevision(DefinitionRevision):
    schema_version: Literal["1.0"] = "1.0"
    resource_type: Literal["workflow_revision"] = "workflow_revision"
    workflow_uid: str = Field(default_factory=uuid7_candidate)
    states: tuple[str, ...]
    initial_state: str
    transitions: tuple[WorkflowTransition, ...] = ()

    @model_validator(mode="after")
    def validate_graph(self) -> WorkflowRevision:
        states = set(self.states)
        if len(states) != len(self.states) or self.initial_state not in states:
            raise ValueError("workflow states must be unique and include initial_state")
        for transition in self.transitions:
            if transition.from_state not in states or transition.to_state not in states:
                raise ValueError("workflow transition references an unknown state")
        return self


class RelationTypeRevision(DefinitionRevision):
    schema_version: Literal["1.0"] = "1.0"
    resource_type: Literal["relation_type_revision"] = "relation_type_revision"
    relation_type_uid: str = Field(default_factory=uuid7_candidate)
    predicate: str = Field(min_length=1)
    core_role: CoreRelationRole
    source_kind_or_facet: tuple[str, ...]
    target_kind_or_facet: tuple[str, ...]
    allowed_bindings: tuple[BindingMode, ...]
    default_binding: BindingMode
    workflow_revision_uid: str
    formal_trace_categories: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_intrinsic_semantics(self) -> RelationTypeRevision:
        if self.default_binding not in self.allowed_bindings:
            raise ValueError("default binding must be allowed")
        if not self.source_kind_or_facet or not self.target_kind_or_facet:
            raise ValueError("relation direction requires source and target constraints")
        return self


SemanticDefinition = Annotated[
    FacetDefinitionRevision | KindDefinitionRevision | WorkflowRevision | RelationTypeRevision,
    Field(discriminator="resource_type"),
]


class ProfileContribution(FrozenModel):
    mode: CompositionMode
    definition_revision_uid: str
    target_revision_uid: str | None = None
    compatibility_report_hash: str | None = None
    impact_report_hash: str | None = None


class ProfileReviewStage(FrozenModel):
    stage: str = Field(min_length=1)
    role: str = Field(min_length=1)
    minimum_count: int = Field(default=1, ge=1)


class ProfileReviewPolicy(FrozenModel):
    operation: str = Field(min_length=1)
    stages: tuple[ProfileReviewStage, ...]
    require_preparer_independence: bool = True
    require_comment_resolution: bool = True


class ProfileContextPolicy(FrozenModel):
    task_type: str = Field(min_length=1)
    mandatory_predicates: tuple[str, ...] = ()
    conditional_predicates: tuple[str, ...] = ()
    invariant_object_uids: tuple[str, ...] = ()
    forbidden_sensitivities: tuple[str, ...] = ()
    mandatory_formal_trace: tuple[tuple[str, str], ...] = ()


class NormativeProfileRevision(FrozenModel):
    schema_version: Literal["1.0"] = "1.0"
    resource_type: Literal["normative_profile_revision"] = "normative_profile_revision"
    profile_uid: str = Field(default_factory=uuid7_candidate)
    profile_revision_uid: str = Field(default_factory=uuid7_candidate)
    layer: ProfileLayer
    authority: int = Field(ge=0)
    contributions: tuple[ProfileContribution, ...] = ()
    rule_revision_uids: tuple[str, ...] = ()
    review_policies: tuple[ProfileReviewPolicy, ...] = ()
    context_policies: tuple[ProfileContextPolicy, ...] = ()
    unit_definitions: tuple[ProfileUnitDefinition, ...] = ()
    content_hash: str = ""

    @model_validator(mode="after")
    def calculate_hash(self) -> NormativeProfileRevision:
        expected = document_hash(self.model_dump(mode="json"), "content_hash")
        if self.content_hash and self.content_hash != expected:
            raise ValueError("profile content_hash is invalid")
        object.__setattr__(self, "content_hash", expected)
        return self


class Mapping(FrozenModel):
    external_namespace: str
    external_name: str
    internal_uid: str


class MappingPackRevision(FrozenModel):
    schema_version: Literal["1.0"] = "1.0"
    resource_type: Literal["mapping_pack_revision"] = "mapping_pack_revision"
    mapping_pack_uid: str = Field(default_factory=uuid7_candidate)
    revision_uid: str = Field(default_factory=uuid7_candidate)
    mappings: tuple[Mapping, ...] = ()
    content_hash: str = ""

    @model_validator(mode="after")
    def calculate_hash(self) -> MappingPackRevision:
        expected = document_hash(self.model_dump(mode="json"), "content_hash")
        if self.content_hash and self.content_hash != expected:
            raise ValueError("mapping pack content_hash is invalid")
        object.__setattr__(self, "content_hash", expected)
        return self


class TailoringOperation(FrozenModel):
    mode: Literal[CompositionMode.TAILOR, CompositionMode.REPLACE]
    target_revision_uid: str
    replacement_revision_uid: str
    allowed_boundary: str | None = None
    compatibility_report_hash: str | None = None
    impact_report_hash: str | None = None


class TailoringOverlay(FrozenModel):
    schema_version: Literal["1.0"] = "1.0"
    resource_type: Literal["tailoring_overlay"] = "tailoring_overlay"
    overlay_uid: str = Field(default_factory=uuid7_candidate)
    configuration_uid: str
    operations: tuple[TailoringOperation, ...]
    authority: int = Field(ge=0)
    content_hash: str = ""

    @model_validator(mode="after")
    def calculate_hash(self) -> TailoringOverlay:
        expected = document_hash(self.model_dump(mode="json"), "content_hash")
        if self.content_hash and self.content_hash != expected:
            raise ValueError("tailoring overlay content_hash is invalid")
        object.__setattr__(self, "content_hash", expected)
        return self


class ModelConflict(FrozenModel):
    code: str
    profile_revision_uid: str
    definition_revision_uid: str
    target_revision_uid: str | None = None
    explanation: str


class EffectiveModel(FrozenModel):
    schema_version: Literal["1.0"] = "1.0"
    resource_type: Literal["effective_model"] = "effective_model"
    model_uid: str
    profile_revision_uids: tuple[str, ...]
    definition_revision_uids: tuple[str, ...]
    rule_revision_uids: tuple[str, ...]
    composition_sources: tuple[tuple[str, str], ...]
    authority: tuple[tuple[str, int], ...]
    tailoring_overlay_uids: tuple[str, ...]
    exception_revision_uids: tuple[str, ...]
    deviation_revision_uids: tuple[str, ...]
    relation_policy_revision_uids: tuple[str, ...]
    workflow_revision_uids: tuple[str, ...]
    conflict_resolutions: tuple[str, ...]
    function_registry: tuple[str, ...]
    unit_registry: tuple[ProfileUnitDefinition, ...]
    review_policies: tuple[ProfileReviewPolicy, ...] = ()
    context_policies: tuple[ProfileContextPolicy, ...] = ()
    compiler_version: Literal["1.0.0"] = "1.0.0"
    conflicts: tuple[ModelConflict, ...] = ()
    model_hash: str


class EffectiveModelCompiler:
    """Order-independent compiler for the normative stack and configuration overlays."""

    VERSION = "1.0.0"

    def compile(
        self,
        profiles: tuple[NormativeProfileRevision, ...],
        definitions: tuple[SemanticDefinition, ...],
        *,
        overlays: tuple[TailoringOverlay, ...] = (),
        exception_revision_uids: tuple[str, ...] = (),
        deviation_revision_uids: tuple[str, ...] = (),
        function_registry: tuple[str, ...] = (),
        unit_registry: tuple[ProfileUnitDefinition, ...] = (),
    ) -> EffectiveModel:
        ordered_profiles = tuple(
            sorted(profiles, key=lambda item: (item.layer, item.profile_revision_uid))
        )
        definitions_by_uid = {item.revision_uid: item for item in definitions}
        selected: dict[str, SemanticDefinition] = {}
        sources: dict[str, str] = {}
        authority: dict[str, int] = defaultdict(int)
        conflicts: list[ModelConflict] = []

        for profile in ordered_profiles:
            for contribution in sorted(
                profile.contributions,
                key=lambda item: (item.definition_revision_uid, item.mode),
            ):
                definition = definitions_by_uid.get(contribution.definition_revision_uid)
                if definition is None:
                    conflicts.append(
                        self._conflict(profile, contribution, "LESR-DEFINITION-MISSING")
                    )
                    continue
                target_uid = contribution.target_revision_uid
                if contribution.mode is CompositionMode.EXTEND:
                    if definition.revision_uid in selected:
                        conflicts.append(
                            self._conflict(profile, contribution, "LESR-EXTEND-DUPLICATE")
                        )
                        continue
                elif contribution.mode is CompositionMode.REFINE:
                    if target_uid not in selected or not self._is_refinement(
                        selected[target_uid], definition
                    ):
                        conflicts.append(
                            self._conflict(profile, contribution, "LESR-REFINE-NOT-NARROWER")
                        )
                        continue
                    selected.pop(str(target_uid))
                elif contribution.mode is CompositionMode.TAILOR:
                    conflicts.append(
                        self._conflict(profile, contribution, "LESR-TAILOR-REQUIRES-OVERLAY")
                    )
                    continue
                else:
                    if not self._replace_allowed(
                        profile.authority,
                        selected.get(str(target_uid)),
                        contribution.compatibility_report_hash,
                        contribution.impact_report_hash,
                    ):
                        conflicts.append(
                            self._conflict(profile, contribution, "LESR-REPLACE-FORBIDDEN")
                        )
                        continue
                    selected.pop(str(target_uid))
                selected[definition.revision_uid] = definition
                sources[definition.revision_uid] = profile.profile_revision_uid
                authority[definition.revision_uid] = profile.authority

        for overlay in sorted(overlays, key=lambda item: item.overlay_uid):
            for operation in overlay.operations:
                target = selected.get(operation.target_revision_uid)
                replacement = definitions_by_uid.get(operation.replacement_revision_uid)
                allowed = (
                    replacement is not None
                    and target is not None
                    and (
                        operation.mode is CompositionMode.TAILOR
                        and self._tailoring_within_boundary(
                            target, replacement, operation.allowed_boundary
                        )
                        or operation.mode is CompositionMode.REPLACE
                        and self._replace_allowed(
                            overlay.authority,
                            target,
                            operation.compatibility_report_hash,
                            operation.impact_report_hash,
                        )
                    )
                )
                if not allowed:
                    conflicts.append(
                        ModelConflict(
                            code="LESR-OVERLAY-OPERATION-FORBIDDEN",
                            profile_revision_uid=overlay.overlay_uid,
                            definition_revision_uid=operation.replacement_revision_uid,
                            target_revision_uid=operation.target_revision_uid,
                            explanation="tailoring boundary or replacement authority is insufficient",
                        )
                    )
                    continue
                selected.pop(operation.target_revision_uid)
                assert replacement is not None
                selected[replacement.revision_uid] = replacement
                sources[replacement.revision_uid] = overlay.overlay_uid
                authority[replacement.revision_uid] = overlay.authority

        selected_uids = tuple(sorted(selected))
        workflow_uids = tuple(
            sorted(
                item.revision_uid
                for item in selected.values()
                if isinstance(item, WorkflowRevision)
            )
        )
        profile_uids = tuple(item.profile_revision_uid for item in ordered_profiles)
        rule_uids = tuple(
            sorted({uid for profile in ordered_profiles for uid in profile.rule_revision_uids})
        )
        review_policies = tuple(
            sorted(
                (policy for profile in ordered_profiles for policy in profile.review_policies),
                key=lambda item: (item.operation, semantic_hash(item)),
            )
        )
        context_policies = tuple(
            sorted(
                (policy for profile in ordered_profiles for policy in profile.context_policies),
                key=lambda item: (item.task_type, semantic_hash(item)),
            )
        )
        source_items = tuple(sorted(sources.items()))
        authority_items = tuple(sorted(authority.items()))
        overlay_uids = tuple(sorted(item.overlay_uid for item in overlays))
        exception_uids = tuple(sorted(exception_revision_uids))
        deviation_uids = tuple(sorted(deviation_revision_uids))
        function_names = tuple(sorted(function_registry))
        profile_units = tuple(
            unit
            for profile in ordered_profiles
            for unit in profile.unit_definitions
        )
        selected_units = profile_units or unit_registry
        units_by_name: dict[str, ProfileUnitDefinition] = {}
        for unit in sorted(selected_units, key=lambda item: (item.unit, semantic_hash(item))):
            previous = units_by_name.setdefault(unit.unit, unit)
            if previous != unit:
                conflicts.append(
                    ModelConflict(
                        code="LESR-UNIT-CONFLICT",
                        profile_revision_uid="unit_registry",
                        definition_revision_uid=unit.unit,
                        explanation=f"unit {unit.unit} has conflicting definitions",
                    )
                )
        unit_names = tuple(units_by_name[key] for key in sorted(units_by_name))
        payload = {
            "profiles": profile_uids,
            "definitions": selected_uids,
            "rules": rule_uids,
            "sources": source_items,
            "authority": authority_items,
            "overlays": overlay_uids,
            "exceptions": exception_uids,
            "deviations": deviation_uids,
            "workflows": workflow_uids,
            "functions": function_names,
            "units": tuple(item.model_dump(mode="json") for item in unit_names),
            "review_policies": tuple(
                item.model_dump(mode="json") for item in review_policies
            ),
            "context_policies": tuple(
                item.model_dump(mode="json") for item in context_policies
            ),
            "compiler": self.VERSION,
            "conflicts": tuple(
                item.model_dump(mode="json")
                for item in sorted(conflicts, key=lambda value: semantic_hash(value))
            ),
        }
        model_hash = semantic_hash(payload)
        return EffectiveModel(
            model_uid=semantic_hash({"effective_model": model_hash}),
            profile_revision_uids=profile_uids,
            definition_revision_uids=selected_uids,
            rule_revision_uids=rule_uids,
            composition_sources=source_items,
            authority=authority_items,
            tailoring_overlay_uids=overlay_uids,
            exception_revision_uids=exception_uids,
            deviation_revision_uids=deviation_uids,
            relation_policy_revision_uids=tuple(
                sorted(
                    item.revision_uid
                    for item in selected.values()
                    if isinstance(item, RelationTypeRevision)
                )
            ),
            workflow_revision_uids=workflow_uids,
            conflict_resolutions=(),
            function_registry=function_names,
            unit_registry=unit_names,
            review_policies=review_policies,
            context_policies=context_policies,
            conflicts=tuple(sorted(conflicts, key=lambda value: semantic_hash(value))),
            model_hash=model_hash,
        )

    @staticmethod
    def _is_refinement(base: SemanticDefinition, candidate: SemanticDefinition) -> bool:
        if type(base) is not type(candidate):
            return False
        if candidate.authority < base.authority:
            return False
        if isinstance(base, FacetDefinitionRevision) and isinstance(
            candidate, FacetDefinitionRevision
        ):
            if base.facet_uid != candidate.facet_uid:
                return False
            base_fields = {item.path: item for item in base.fields}
            candidate_fields = {item.path: item for item in candidate.fields}
            return set(base.capabilities) <= set(candidate.capabilities) and all(
                path in candidate_fields
                and EffectiveModelCompiler._field_is_narrower(field, candidate_fields[path])
                for path, field in base_fields.items()
            )
        if isinstance(base, KindDefinitionRevision) and isinstance(
            candidate, KindDefinitionRevision
        ):
            return bool(
                base.kind_uid == candidate.kind_uid
                and base.core_class == candidate.core_class
                and set(base.required_facet_revision_uids)
                <= set(candidate.required_facet_revision_uids)
                and set(candidate.optional_facet_revision_uids)
                <= set(base.optional_facet_revision_uids)
                and (
                    base.workflow_revision_uid == candidate.workflow_revision_uid
                    or base.workflow_revision_uid is None
                )
            )
        if isinstance(base, RelationTypeRevision) and isinstance(
            candidate, RelationTypeRevision
        ):
            return bool(
                base.relation_type_uid == candidate.relation_type_uid
                and base.predicate == candidate.predicate
                and base.core_role == candidate.core_role
                and set(candidate.source_kind_or_facet) <= set(base.source_kind_or_facet)
                and set(candidate.target_kind_or_facet) <= set(base.target_kind_or_facet)
                and set(candidate.allowed_bindings) <= set(base.allowed_bindings)
                and set(candidate.formal_trace_categories)
                <= set(base.formal_trace_categories)
            )
        if isinstance(base, WorkflowRevision) and isinstance(candidate, WorkflowRevision):
            base_transitions = {
                (item.from_state, item.to_state): item for item in base.transitions
            }
            candidate_transitions = {
                (item.from_state, item.to_state): item for item in candidate.transitions
            }
            return bool(
                base.workflow_uid == candidate.workflow_uid
                and base.initial_state == candidate.initial_state
                and set(candidate.states) <= set(base.states)
                and all(
                    key in candidate_transitions
                    and set(candidate_transitions[key].roles) <= set(item.roles)
                    and set(candidate_transitions[key].guards) >= set(item.guards)
                    and set(candidate_transitions[key].evidence_kinds)
                    >= set(item.evidence_kinds)
                    for key, item in base_transitions.items()
                )
            )
        return False

    @staticmethod
    def _field_is_narrower(base: FieldDefinition, candidate: FieldDefinition) -> bool:
        if base.value_type != candidate.value_type or base.unit != candidate.unit:
            return False
        if base.required and not candidate.required:
            return False
        if base.enum_values and not set(map(str, candidate.enum_values)) <= set(
            map(str, base.enum_values)
        ):
            return False
        if base.minimum is not None and (
            candidate.minimum is None or Decimal(candidate.minimum) < Decimal(base.minimum)
        ):
            return False
        if base.maximum is not None and (
            candidate.maximum is None or Decimal(candidate.maximum) > Decimal(base.maximum)
        ):
            return False
        if base.minimum_items is not None and (
            candidate.minimum_items is None
            or candidate.minimum_items < base.minimum_items
        ):
            return False
        return not (
            base.maximum_items is not None
            and (
                candidate.maximum_items is None
                or candidate.maximum_items > base.maximum_items
            )
        )

    @staticmethod
    def _replace_allowed(
        authority: int,
        target: SemanticDefinition | None,
        compatibility_hash: str | None,
        impact_hash: str | None,
    ) -> bool:
        return bool(
            target
            and target.replaceable
            and authority >= target.authority
            and compatibility_hash
            and impact_hash
        )

    @staticmethod
    def _tailoring_within_boundary(
        target: SemanticDefinition,
        replacement: SemanticDefinition,
        boundary: str | None,
    ) -> bool:
        if type(target) is not type(replacement) or not boundary:
            return False
        allowed = {item.strip() for item in boundary.split(",") if item.strip()}
        if not allowed:
            return False
        before = target.model_dump(mode="json", exclude={"revision_uid", "content_hash"})
        after = replacement.model_dump(mode="json", exclude={"revision_uid", "content_hash"})
        changed = {key for key in set(before) | set(after) if before.get(key) != after.get(key)}
        immutable_identity = {
            "resource_type",
            "facet_uid",
            "kind_uid",
            "relation_type_uid",
            "workflow_uid",
        }
        if changed & immutable_identity:
            return False
        return "*" in allowed or changed <= allowed

    @staticmethod
    def _conflict(
        profile: NormativeProfileRevision,
        contribution: ProfileContribution,
        code: str,
    ) -> ModelConflict:
        return ModelConflict(
            code=code,
            profile_revision_uid=profile.profile_revision_uid,
            definition_revision_uid=contribution.definition_revision_uid,
            target_revision_uid=contribution.target_revision_uid,
            explanation=code.removeprefix("LESR-").lower().replace("-", " "),
        )


class WorkflowProjection(FrozenModel):
    state: str
    applied_record_uids: tuple[str, ...]
    conflicts: tuple[str, ...] = ()


class WorkflowProjector:
    """Project lifecycle records against one exact Workflow Revision."""

    @staticmethod
    def project(
        workflow: WorkflowRevision,
        records: tuple[ImmutableRecord, ...],
    ) -> WorkflowProjection:
        state = workflow.initial_state
        applied: list[str] = []
        conflicts: list[str] = []
        transitions = {(item.from_state, item.to_state): item for item in workflow.transitions}
        for record in sorted(records, key=lambda item: (item.occurred_at, item.record_uid)):
            if record.record_type != "lifecycle":
                continue
            from_state = record.field_value("/from_state")
            to_state = record.field_value("/to_state")
            if not isinstance(from_state, str) or not isinstance(to_state, str):
                conflicts.append(f"{record.record_uid}: invalid lifecycle state")
                continue
            transition = transitions.get((from_state, to_state))
            if state != from_state or transition is None:
                conflicts.append(f"{record.record_uid}: transition is not allowed")
                continue
            state = to_state
            applied.append(record.record_uid)
        return WorkflowProjection(
            state=state,
            applied_record_uids=tuple(applied),
            conflicts=tuple(conflicts),
        )


def formal_provenance_allowed(kind: ProvenanceKind) -> bool:
    return kind in {ProvenanceKind.ASSERTED, ProvenanceKind.IMPORTED}
