"""LESR 1.0 normative semantic model and deterministic profile compiler."""

from __future__ import annotations

from collections import defaultdict
from enum import IntEnum, StrEnum
from typing import Annotated, Literal

from pydantic import Field, model_validator

from lesr.domain.semantic import (
    BindingMode,
    CoreRelationRole,
    CoreResourceClass,
    FrozenModel,
    ImmutableRecord,
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


class FacetDefinitionRevision(DefinitionRevision):
    schema_version: Literal["1.0"] = "1.0"
    resource_type: Literal["facet_definition_revision"] = "facet_definition_revision"
    facet_uid: str = Field(default_factory=uuid7_candidate)
    name: str = Field(min_length=1)
    capabilities: tuple[str, ...] = ()


class KindDefinitionRevision(DefinitionRevision):
    schema_version: Literal["1.0"] = "1.0"
    resource_type: Literal["kind_definition_revision"] = "kind_definition_revision"
    kind_uid: str = Field(default_factory=uuid7_candidate)
    name: str = Field(min_length=1)
    core_class: CoreResourceClass
    required_facet_revision_uids: tuple[str, ...] = ()
    optional_facet_revision_uids: tuple[str, ...] = ()

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


class NormativeProfileRevision(FrozenModel):
    schema_version: Literal["1.0"] = "1.0"
    resource_type: Literal["normative_profile_revision"] = "normative_profile_revision"
    profile_uid: str = Field(default_factory=uuid7_candidate)
    profile_revision_uid: str = Field(default_factory=uuid7_candidate)
    layer: ProfileLayer
    authority: int = Field(ge=0)
    contributions: tuple[ProfileContribution, ...] = ()
    rule_revision_uids: tuple[str, ...] = ()
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
    composition_sources: tuple[tuple[str, str], ...]
    authority: tuple[tuple[str, int], ...]
    tailoring_overlay_uids: tuple[str, ...]
    exception_revision_uids: tuple[str, ...]
    deviation_revision_uids: tuple[str, ...]
    relation_policy_revision_uids: tuple[str, ...]
    workflow_revision_uids: tuple[str, ...]
    conflict_resolutions: tuple[str, ...]
    function_registry: tuple[str, ...]
    unit_registry: tuple[str, ...]
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
        unit_registry: tuple[str, ...] = (),
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
                        and operation.allowed_boundary is not None
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
        source_items = tuple(sorted(sources.items()))
        authority_items = tuple(sorted(authority.items()))
        overlay_uids = tuple(sorted(item.overlay_uid for item in overlays))
        exception_uids = tuple(sorted(exception_revision_uids))
        deviation_uids = tuple(sorted(deviation_revision_uids))
        function_names = tuple(sorted(function_registry))
        unit_names = tuple(sorted(unit_registry))
        payload = {
            "profiles": profile_uids,
            "definitions": selected_uids,
            "sources": source_items,
            "authority": authority_items,
            "overlays": overlay_uids,
            "exceptions": exception_uids,
            "deviations": deviation_uids,
            "workflows": workflow_uids,
            "functions": function_names,
            "units": unit_names,
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
            conflicts=tuple(sorted(conflicts, key=lambda value: semantic_hash(value))),
            model_hash=model_hash,
        )

    @staticmethod
    def _is_refinement(base: SemanticDefinition, candidate: SemanticDefinition) -> bool:
        if type(base) is not type(candidate):
            return False
        return candidate.authority >= base.authority

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
