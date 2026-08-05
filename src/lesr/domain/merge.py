"""Three-way semantic rebase, merge conflict and reconciliation contracts."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal, cast

from pydantic import Field, model_validator

from lesr.application.contracts import RiskClass
from lesr.domain.semantic import FrozenModel, JsonValue, document_hash, uuid7_candidate


class ConflictType(StrEnum):
    SAME_FIELD = "same_field"
    DELETE_MODIFY = "delete_modify"
    KIND_FACET = "kind_facet"
    HUMAN_KEY = "human_key"
    RELATION_ENDPOINT = "relation_endpoint"
    RULE_PROFILE_DEVIATION = "rule_profile_deviation"


class ConflictState(StrEnum):
    OPEN = "open"
    RESOLVED = "resolved"


class ResolutionType(StrEnum):
    TAKE_OURS = "take_ours"
    TAKE_THEIRS = "take_theirs"
    SET_VALUE = "set_value"
    DELETE = "delete"


class SemanticState(FrozenModel):
    object_uid: str
    human_key: str
    kind: str
    facets: tuple[str, ...]
    fields: tuple[tuple[str, JsonValue], ...]
    fragments: tuple[tuple[str, JsonValue], ...] = ()
    relations: tuple[tuple[str, JsonValue], ...] = ()


class MergeConflict(FrozenModel):
    schema_version: Literal["1.0"] = "1.0"
    resource_type: Literal["merge_conflict"] = "merge_conflict"
    conflict_uid: str = Field(default_factory=uuid7_candidate)
    workspace_uid: str
    object_uid: str
    conflict_type: ConflictType
    path: str
    base: JsonValue = None
    ours: JsonValue = None
    theirs: JsonValue = None
    risk_class: RiskClass
    state: ConflictState = ConflictState.OPEN
    conflict_hash: str = ""

    @model_validator(mode="after")
    def calculate_hash(self) -> MergeConflict:
        expected = document_hash(self.model_dump(mode="json"), "conflict_hash")
        if self.conflict_hash and self.conflict_hash != expected:
            raise ValueError("conflict_hash is invalid")
        object.__setattr__(self, "conflict_hash", expected)
        return self


class ConflictResolution(FrozenModel):
    schema_version: Literal["1.0"] = "1.0"
    resource_type: Literal["conflict_resolution"] = "conflict_resolution"
    resolution_uid: str = Field(default_factory=uuid7_candidate)
    conflict_uid: str
    operation: ResolutionType
    value: JsonValue = None
    actor_uid: str
    actor_type: Literal["human", "ai", "tool", "system"]
    resolved_at: datetime
    resolution_hash: str = ""

    @model_validator(mode="after")
    def calculate_hash(self) -> ConflictResolution:
        expected = document_hash(self.model_dump(mode="json"), "resolution_hash")
        if self.resolution_hash and self.resolution_hash != expected:
            raise ValueError("resolution_hash is invalid")
        object.__setattr__(self, "resolution_hash", expected)
        return self


class RebaseResult(FrozenModel):
    merged: SemanticState
    conflicts: tuple[MergeConflict, ...]
    approvals_invalidated: Literal[True] = True
    rebuild_required: tuple[
        Literal["graph", "rule", "validation", "context", "impact", "review_package"],
        ...,
    ] = ("graph", "rule", "validation", "context", "impact", "review_package")


class SemanticMergeEngine:
    """Merge Base/Ours/New Base without treating a Git merge as authority."""

    @staticmethod
    def merge(
        workspace_uid: str,
        base: SemanticState,
        ours: SemanticState,
        theirs: SemanticState,
    ) -> RebaseResult:
        if len({base.object_uid, ours.object_uid, theirs.object_uid}) != 1:
            raise ValueError("LESR-MERGE-OBJECT-MISMATCH")
        conflicts: list[MergeConflict] = []
        human_key_value = SemanticMergeEngine._scalar(
            workspace_uid,
            base.object_uid,
            "/human_key",
            base.human_key,
            ours.human_key,
            theirs.human_key,
            ConflictType.HUMAN_KEY,
            conflicts,
        )
        kind_value = SemanticMergeEngine._scalar(
            workspace_uid,
            base.object_uid,
            "/kind",
            base.kind,
            ours.kind,
            theirs.kind,
            ConflictType.KIND_FACET,
            conflicts,
        )
        facets_value = SemanticMergeEngine._scalar(
            workspace_uid,
            base.object_uid,
            "/facets",
            list(base.facets),
            list(ours.facets),
            list(theirs.facets),
            ConflictType.KIND_FACET,
            conflicts,
        )
        fields = SemanticMergeEngine._mapping(
            workspace_uid,
            base.object_uid,
            dict(base.fields),
            dict(ours.fields),
            dict(theirs.fields),
            "/fields",
            ConflictType.SAME_FIELD,
            conflicts,
        )
        fragments = SemanticMergeEngine._mapping(
            workspace_uid,
            base.object_uid,
            dict(base.fragments),
            dict(ours.fragments),
            dict(theirs.fragments),
            "/fragments",
            ConflictType.SAME_FIELD,
            conflicts,
        )
        relations = SemanticMergeEngine._mapping(
            workspace_uid,
            base.object_uid,
            dict(base.relations),
            dict(ours.relations),
            dict(theirs.relations),
            "/relations",
            ConflictType.RELATION_ENDPOINT,
            conflicts,
        )
        return RebaseResult(
            merged=SemanticState(
                object_uid=base.object_uid,
                human_key=str(human_key_value),
                kind=str(kind_value),
                facets=tuple(str(item) for item in cast(list[JsonValue], facets_value)),
                fields=tuple(sorted(fields.items())),
                fragments=tuple(sorted(fragments.items())),
                relations=tuple(sorted(relations.items())),
            ),
            conflicts=tuple(conflicts),
        )

    @staticmethod
    def resolve(
        result: RebaseResult,
        resolutions: tuple[ConflictResolution, ...],
    ) -> RebaseResult:
        by_uid = {item.conflict_uid: item for item in resolutions}
        fields = dict(result.merged.fields)
        fragments = dict(result.merged.fragments)
        relations = dict(result.merged.relations)
        human_key = result.merged.human_key
        kind = result.merged.kind
        facets = result.merged.facets
        remaining: list[MergeConflict] = []
        for conflict in result.conflicts:
            resolution = by_uid.get(conflict.conflict_uid)
            if resolution is None:
                remaining.append(conflict)
                continue
            if conflict.risk_class is RiskClass.HIGH and resolution.actor_type != "human":
                raise ValueError("LESR-HIGH-RISK-CONFLICT-REQUIRES-HUMAN")
            selected = SemanticMergeEngine._resolution_value(conflict, resolution)
            if conflict.path == "/human_key":
                human_key = str(selected)
            elif conflict.path == "/kind":
                kind = str(selected)
            elif conflict.path == "/facets":
                if not isinstance(selected, list):
                    raise ValueError("facet resolution must be an array")
                facets = tuple(str(item) for item in selected)
            else:
                root, key = conflict.path.rsplit("/", 1)
                target = (
                    fields
                    if root == "/fields"
                    else fragments
                    if root == "/fragments"
                    else relations
                )
                if resolution.operation is ResolutionType.DELETE:
                    target.pop(key, None)
                else:
                    target[key] = selected
        return RebaseResult(
            merged=SemanticState(
                object_uid=result.merged.object_uid,
                human_key=human_key,
                kind=kind,
                facets=facets,
                fields=tuple(sorted(fields.items())),
                fragments=tuple(sorted(fragments.items())),
                relations=tuple(sorted(relations.items())),
            ),
            conflicts=tuple(remaining),
        )

    @staticmethod
    def _scalar(
        workspace_uid: str,
        object_uid: str,
        path: str,
        base: JsonValue,
        ours: JsonValue,
        theirs: JsonValue,
        conflict_type: ConflictType,
        conflicts: list[MergeConflict],
    ) -> JsonValue:
        if ours == theirs:
            return ours
        if ours == base:
            return theirs
        if theirs == base:
            return ours
        conflicts.append(
            SemanticMergeEngine._conflict(
                workspace_uid,
                object_uid,
                conflict_type,
                path,
                base,
                ours,
                theirs,
            )
        )
        return ours

    @staticmethod
    def _mapping(
        workspace_uid: str,
        object_uid: str,
        base: dict[str, JsonValue],
        ours: dict[str, JsonValue],
        theirs: dict[str, JsonValue],
        root: str,
        conflict_type: ConflictType,
        conflicts: list[MergeConflict],
    ) -> dict[str, JsonValue]:
        missing = object()
        merged: dict[str, JsonValue] = {}
        for key in sorted(set(base) | set(ours) | set(theirs)):
            base_value = base.get(key, missing)
            ours_value = ours.get(key, missing)
            theirs_value = theirs.get(key, missing)
            if ours_value == theirs_value:
                chosen = ours_value
            elif ours_value == base_value:
                chosen = theirs_value
            elif theirs_value == base_value:
                chosen = ours_value
            else:
                actual_type = (
                    ConflictType.DELETE_MODIFY
                    if base_value is missing or ours_value is missing or theirs_value is missing
                    else conflict_type
                )
                base_json = None if base_value is missing else cast(JsonValue, base_value)
                ours_json = None if ours_value is missing else cast(JsonValue, ours_value)
                theirs_json = None if theirs_value is missing else cast(JsonValue, theirs_value)
                conflicts.append(
                    SemanticMergeEngine._conflict(
                        workspace_uid,
                        object_uid,
                        actual_type,
                        f"{root}/{key}",
                        base_json,
                        ours_json,
                        theirs_json,
                    )
                )
                chosen = ours_value
            if chosen is not missing:
                merged[key] = cast(JsonValue, chosen)
        return merged

    @staticmethod
    def _conflict(
        workspace_uid: str,
        object_uid: str,
        conflict_type: ConflictType,
        path: str,
        base: JsonValue,
        ours: JsonValue,
        theirs: JsonValue,
    ) -> MergeConflict:
        high_risk = conflict_type in {
            ConflictType.KIND_FACET,
            ConflictType.HUMAN_KEY,
            ConflictType.RELATION_ENDPOINT,
            ConflictType.RULE_PROFILE_DEVIATION,
        }
        return MergeConflict(
            workspace_uid=workspace_uid,
            object_uid=object_uid,
            conflict_type=conflict_type,
            path=path,
            base=base,
            ours=ours,
            theirs=theirs,
            risk_class=RiskClass.HIGH if high_risk else RiskClass.MEDIUM,
        )

    @staticmethod
    def _resolution_value(conflict: MergeConflict, resolution: ConflictResolution) -> JsonValue:
        if resolution.operation is ResolutionType.TAKE_OURS:
            return conflict.ours
        if resolution.operation is ResolutionType.TAKE_THEIRS:
            return conflict.theirs
        if resolution.operation is ResolutionType.SET_VALUE:
            return resolution.value
        return None


class ForeignDiff(FrozenModel):
    old_commit: str
    foreign_commit: str
    changed_paths: tuple[str, ...]
    has_merge_commit: bool
    diff_hash: str = ""

    @model_validator(mode="after")
    def calculate_hash(self) -> ForeignDiff:
        expected = document_hash(self.model_dump(mode="json"), "diff_hash")
        if self.diff_hash and self.diff_hash != expected:
            raise ValueError("foreign diff_hash is invalid")
        object.__setattr__(self, "diff_hash", expected)
        return self


class ReconciliationWorkspace(FrozenModel):
    workspace_uid: str = Field(default_factory=uuid7_candidate)
    base_commit: str
    foreign_commit: str
    foreign_diff_hash: str
    authority_status: Literal["not_authoritative_pending_reconciliation"] = (
        "not_authoritative_pending_reconciliation"
    )


def begin_reconciliation(diff: ForeignDiff) -> ReconciliationWorkspace:
    if not diff.changed_paths:
        raise ValueError("LESR-RECONCILIATION-NOT-REQUIRED")
    return ReconciliationWorkspace(
        base_commit=diff.old_commit,
        foreign_commit=diff.foreign_commit,
        foreign_diff_hash=diff.diff_hash,
    )
