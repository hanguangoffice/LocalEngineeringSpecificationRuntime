"""LESR v1 immutable semantic kernel."""

from __future__ import annotations

import hashlib
import json
import secrets
import time
import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

JsonScalar = str | int | float | bool | None


class FrozenModel(BaseModel):
    """A deeply immutable model when compound values use tuples/models."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class CoreResourceClass(StrEnum):
    GOVERNED_OBJECT = "governed_object"
    IMMUTABLE_RECORD = "immutable_record"
    CHANGE_WORKSPACE = "change_workspace"
    CONFIGURATION_SNAPSHOT = "configuration_snapshot"
    PRESENTATION_RESOURCE = "presentation_resource"
    SUPPORTING_RESOURCE = "supporting_resource"


class CoreFacet(StrEnum):
    AUTHORED = "authored"
    LIFECYCLE = "lifecycle"
    NORMATIVE = "normative"
    APPLICABILITY = "applicability"
    COMPOSITION = "composition"
    TRACEABILITY = "traceability"
    VERIFICATION_PLAN = "verification_plan"
    EXECUTABLE = "executable"
    DECISION = "decision"
    AUTHORIZATION = "authorization"
    ISSUE = "issue"
    RECORD = "record"
    EVIDENCE = "evidence"
    OBSERVATION = "observation"
    CONFIDENTIALITY = "confidentiality"
    EXTERNAL_BINDING = "external_binding"


class BindingMode(StrEnum):
    LOGICAL = "logical"
    PINNED = "pinned"
    FRAGMENT = "fragment"
    EXTERNAL = "external"


class CoreRelationRole(StrEnum):
    ORGANIZES = "organizes"
    COMPOSES = "composes"
    REFINES = "refines"
    REALIZES = "realizes"
    VERIFIES = "verifies"
    CONSTRAINS = "constrains"
    APPLIES_TO = "applies_to"
    DEPENDS_ON = "depends_on"
    IMPACTS = "impacts"
    EVIDENCES = "evidences"
    GOVERNS = "governs"
    AUTHORIZES = "authorizes"
    DERIVES_FROM = "derives_from"
    SUPERSEDES = "supersedes"
    CONFLICTS_WITH = "conflicts_with"
    REFERENCES = "references"


class ProvenanceKind(StrEnum):
    AUTHORED = "authored"
    IMPORTED = "imported"
    OBSERVED = "observed"
    ASSERTED = "asserted"
    INFERRED = "inferred"
    PROPOSED = "proposed"
    GENERATED = "generated"


class LifecycleEventType(StrEnum):
    REVISION_SUBMITTED = "revision_submitted"
    REVIEW_STARTED = "review_started"
    REVISION_APPROVED = "revision_approved"
    REVISION_REJECTED = "revision_rejected"
    REVISION_WITHDRAWN = "revision_withdrawn"
    APPROVAL_REVOKED = "approval_revoked"
    OBJECT_DEPRECATED = "object_deprecated"
    OBJECT_SUPERSEDED = "object_superseded"
    OBJECT_RETIRED = "object_retired"
    OBJECT_REACTIVATED = "object_reactivated"


class ProjectionStatus(StrEnum):
    DRAFT = "draft"
    IN_REVIEW = "in_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"
    ACTIVE = "active"
    DEPRECATED = "deprecated"
    SUPERSEDED = "superseded"
    RETIRED = "retired"
    INDETERMINATE = "indeterminate"


def canonical_json(value: BaseModel | dict[str, Any] | list[Any] | tuple[Any, ...]) -> str:
    """Serialize semantic content deterministically for hashing and Git storage."""

    data: Any
    if isinstance(value, BaseModel):
        data = value.model_dump(mode="json", exclude_none=False)
    else:
        data = value
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def semantic_hash(value: BaseModel | dict[str, Any] | list[Any] | tuple[Any, ...]) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def document_hash(value: dict[str, Any], hash_field: str) -> str:
    """Hash a content-addressed document without its self-describing hash field."""
    return semantic_hash({key: item for key, item in value.items() if key != hash_field})


def uuid7_candidate(timestamp_ms: int | None = None) -> str:
    """Generate an RFC 9562 UUIDv7 candidate without a third-party dependency."""

    milliseconds = timestamp_ms if timestamp_ms is not None else time.time_ns() // 1_000_000
    if not 0 <= milliseconds < 1 << 48:
        raise ValueError("timestamp_ms must fit in 48 bits")
    rand_a = secrets.randbits(12)
    rand_b = secrets.randbits(62)
    integer = (
        (milliseconds << 80)
        | (0x7 << 76)
        | (rand_a << 64)
        | (0b10 << 62)
        | rand_b
    )
    return str(uuid.UUID(int=integer))


_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def ulid_candidate(timestamp_ms: int | None = None) -> str:
    milliseconds = timestamp_ms if timestamp_ms is not None else time.time_ns() // 1_000_000
    if not 0 <= milliseconds < 1 << 48:
        raise ValueError("timestamp_ms must fit in 48 bits")
    value = (milliseconds << 80) | secrets.randbits(80)
    chars: list[str] = []
    for _ in range(26):
        chars.append(_CROCKFORD[value & 31])
        value >>= 5
    return "".join(reversed(chars))


class SemanticField(FrozenModel):
    path: str = Field(min_length=1)
    value_json: str

    @classmethod
    def from_value(cls, path: str, value: JsonScalar | list[Any] | dict[str, Any]) -> Self:
        return cls(
            path=path,
            value_json=json.dumps(
                value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ),
        )

    def value(self) -> Any:
        return json.loads(self.value_json)


class Alias(FrozenModel):
    value: str = Field(min_length=1)
    alias_type: str = Field(min_length=1)
    valid_from: datetime
    valid_to: datetime | None = None
    introduced_by: str = Field(min_length=1)


class ExternalIdentity(FrozenModel):
    system: str
    namespace: str
    external_id: str
    external_revision: str | None = None
    uri: str | None = None
    source_hash: str | None = None


class Fragment(FrozenModel):
    local_key: str = Field(min_length=1)
    fields: tuple[SemanticField, ...] = ()


class FragmentAddress(FrozenModel):
    object_uid: str
    revision_uid: str
    fragment_path: str = Field(min_length=1)

    def as_uri(self, project: str) -> str:
        return f"lesr://{project}/{self.object_uid}@{self.revision_uid}#{self.fragment_path}"


class LogicalObject(FrozenModel):
    entity_uid: str = Field(default_factory=uuid7_candidate)
    namespace: str = Field(min_length=1)
    human_key: str = Field(min_length=1)
    kind: str = Field(min_length=1)
    core_class: CoreResourceClass = CoreResourceClass.GOVERNED_OBJECT
    facets: tuple[str, ...] = ()
    aliases: tuple[Alias, ...] = ()
    external_identities: tuple[ExternalIdentity, ...] = ()


class Revision(FrozenModel):
    revision_uid: str = Field(default_factory=uuid7_candidate)
    object_uid: str
    revision_number: int = Field(ge=1)
    parent_revision_uid: str | None = None
    human_key: str
    kind: str
    facets: tuple[str, ...] = ()
    fields: tuple[SemanticField, ...] = ()
    fragments: tuple[Fragment, ...] = ()
    provenance_origin: ProvenanceKind
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    content_hash: str = ""

    @model_validator(mode="after")
    def calculate_content_hash(self) -> Revision:
        payload = self.model_dump(mode="json", exclude={"content_hash"})
        calculated = semantic_hash(payload)
        if self.content_hash and self.content_hash != calculated:
            raise ValueError("content_hash does not match immutable revision content")
        object.__setattr__(self, "content_hash", calculated)
        return self


class ImmutableRecord(FrozenModel):
    record_uid: str = Field(default_factory=uuid7_candidate)
    record_type: str
    subject_uid: str
    actor: str
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    fields: tuple[SemanticField, ...] = ()
    supersedes_record_uid: str | None = None


class LifecycleRecord(ImmutableRecord):
    record_type: str = "lifecycle"
    event_type: LifecycleEventType
    from_state: str | None = None
    to_state: str
    workflow_revision_uid: str
    review_package_uid: str | None = None


class ProjectionResult(FrozenModel):
    status: ProjectionStatus
    record_uids: tuple[str, ...]
    conflicts: tuple[str, ...] = ()


class LifecycleProjector:
    """Project maturity/disposition without mutating the subject Revision."""

    @staticmethod
    def project(initial: str, records: tuple[LifecycleRecord, ...]) -> ProjectionResult:
        state = initial
        applied: list[str] = []
        conflicts: list[str] = []
        ordered = sorted(records, key=lambda item: (item.occurred_at, item.record_uid))
        for record in ordered:
            if record.from_state is not None and record.from_state != state:
                conflicts.append(
                    f"{record.record_uid}: expected {record.from_state}, projected {state}"
                )
                continue
            state = record.to_state
            applied.append(record.record_uid)
        if conflicts:
            return ProjectionResult(
                status=ProjectionStatus.INDETERMINATE,
                record_uids=tuple(applied),
                conflicts=tuple(conflicts),
            )
        try:
            status = ProjectionStatus(state)
        except ValueError:
            status = ProjectionStatus.INDETERMINATE
            conflicts.append(f"unknown projected state: {state}")
        return ProjectionResult(
            status=status,
            record_uids=tuple(applied),
            conflicts=tuple(conflicts),
        )


class RelationEndpoint(FrozenModel):
    binding: BindingMode
    object_uid: str | None = None
    revision_uid: str | None = None
    fragment: FragmentAddress | None = None
    external: ExternalIdentity | None = None

    @model_validator(mode="after")
    def exactly_one_binding_target(self) -> RelationEndpoint:
        valid = {
            BindingMode.LOGICAL: self.object_uid is not None
            and self.revision_uid is None
            and self.fragment is None
            and self.external is None,
            BindingMode.PINNED: self.object_uid is not None
            and self.revision_uid is not None
            and self.fragment is None
            and self.external is None,
            BindingMode.FRAGMENT: self.fragment is not None
            and self.external is None
            and self.object_uid is None
            and self.revision_uid is None,
            BindingMode.EXTERNAL: self.external is not None
            and self.fragment is None
            and self.object_uid is None
            and self.revision_uid is None,
        }
        if not valid[self.binding]:
            raise ValueError(f"endpoint fields do not match {self.binding} binding")
        return self


class RelationAssertion(FrozenModel):
    assertion_uid: str = Field(default_factory=uuid7_candidate)
    revision_uid: str = Field(default_factory=uuid7_candidate)
    revision_number: int = Field(default=1, ge=1)
    predicate: str
    core_role: CoreRelationRole
    source: RelationEndpoint
    target: RelationEndpoint
    scope: str
    provenance_kind: ProvenanceKind
    formal_trace_categories: tuple[str, ...] = ()
    rationale: str | None = None

    def identity_hash(self) -> str:
        return semantic_hash(
            {
                "source": self.source.model_dump(mode="json"),
                "predicate": self.predicate,
                "target": self.target.model_dump(mode="json"),
                "scope": self.scope,
            }
        )

    def grants_formal_trace(self) -> bool:
        return (
            self.provenance_kind in {ProvenanceKind.ASSERTED, ProvenanceKind.IMPORTED}
            and self.source.binding in {BindingMode.LOGICAL, BindingMode.PINNED}
            and self.target.binding in {BindingMode.LOGICAL, BindingMode.PINNED}
            and bool(self.formal_trace_categories)
        )


class WorkingCopy(FrozenModel):
    object_uid: str
    base_revision_uid: str
    fields: tuple[SemanticField, ...]
    proposed_relations: tuple[RelationAssertion, ...] = ()


class ChangeWorkspace(FrozenModel):
    workspace_uid: str = Field(default_factory=uuid7_candidate)
    base_configuration_uid: str
    effective_model_hash: str
    delegation_uid: str
    state: str = "open"
    working_copies: tuple[WorkingCopy, ...] = ()
    checkpoint_uids: tuple[str, ...] = ()

    @model_validator(mode="after")
    def one_working_copy_per_object(self) -> ChangeWorkspace:
        object_uids = [copy.object_uid for copy in self.working_copies]
        if len(object_uids) != len(set(object_uids)):
            raise ValueError("a workspace can have one active working copy per logical object")
        return self


class ConfigurationSnapshot(FrozenModel):
    configuration_uid: str = Field(default_factory=uuid7_candidate)
    git_commit: str
    revision_uids: tuple[str, ...]
    relation_revision_uids: tuple[str, ...]
    profile_revision_uids: tuple[str, ...]
    effective_model_hash: str
    active_deviation_revision_uids: tuple[str, ...] = ()
    closure_status: str = "complete"


class KindDefinition(FrozenModel):
    kind: str
    core_class: CoreResourceClass
    required_facets: tuple[str, ...]
    optional_facets: tuple[str, ...] = ()

    def capabilities(
        self, *, maturity: ProjectionStatus, delegated: bool = False
    ) -> frozenset[str]:
        capabilities = {"can_read"}
        if self.core_class is CoreResourceClass.GOVERNED_OBJECT:
            capabilities.update({"can_propose_revision", "can_be_baselined"})
            if CoreFacet.TRACEABILITY in self.required_facets:
                capabilities.add("can_have_formal_trace")
            if CoreFacet.AUTHORIZATION in self.required_facets:
                capabilities.add("can_be_deviated")
            if delegated and maturity in {ProjectionStatus.DRAFT, ProjectionStatus.IN_REVIEW}:
                capabilities.add("can_be_modified_under_delegation")
        if self.core_class is CoreResourceClass.IMMUTABLE_RECORD:
            capabilities.add("can_be_retracted_by_record")
        return frozenset(capabilities)
