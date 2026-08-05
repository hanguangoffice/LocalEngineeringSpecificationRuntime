"""Pure LESR 1.0 Working Copy, checkpoint and candidate-state engine."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal

from pydantic import Field, model_validator

from lesr.domain.semantic import (
    Fragment,
    FrozenModel,
    JsonValue,
    ProvenanceKind,
    RelationAssertion,
    Revision,
    SemanticField,
    document_hash,
    semantic_hash,
    uuid7_candidate,
)


class EditOperationType(StrEnum):
    CREATE_OBJECT = "create_object"
    SET_FIELD = "set_field"
    DELETE_FIELD = "delete_field"
    ADD_FRAGMENT = "add_fragment"
    MODIFY_FRAGMENT = "modify_fragment"
    DELETE_FRAGMENT = "delete_fragment"
    PROPOSE_RELATION = "propose_relation"
    WITHDRAW_RELATION = "withdraw_relation"
    REQUEST_LIFECYCLE_TRANSITION = "request_lifecycle_transition"


class WorkingCopyState(StrEnum):
    EDITABLE = "editable"
    SUBMITTED = "submitted"


class ValidationState(StrEnum):
    NOT_RUN = "not_run"
    PASS = "pass"
    FAIL = "fail"
    INDETERMINATE = "indeterminate"


class EditOperation(FrozenModel):
    schema_version: Literal["1.0"] = "1.0"
    resource_type: Literal["edit_operation"] = "edit_operation"
    operation_uid: str = Field(default_factory=uuid7_candidate)
    operation_type: EditOperationType
    object_uid: str
    actor_uid: str
    occurred_at: datetime
    path: str | None = None
    value: JsonValue = None
    relation: RelationAssertion | None = None
    operation_hash: str = ""

    @model_validator(mode="after")
    def validate_operation(self) -> EditOperation:
        path_required = {
            EditOperationType.SET_FIELD,
            EditOperationType.DELETE_FIELD,
            EditOperationType.ADD_FRAGMENT,
            EditOperationType.MODIFY_FRAGMENT,
            EditOperationType.DELETE_FRAGMENT,
        }
        if self.operation_type in path_required and not self.path:
            raise ValueError("edit operation requires path")
        if self.operation_type is EditOperationType.PROPOSE_RELATION and self.relation is None:
            raise ValueError("propose_relation requires relation")
        if self.operation_type is EditOperationType.WITHDRAW_RELATION and not isinstance(
            self.value, str
        ):
            raise ValueError("withdraw_relation requires relation revision UID")
        if self.operation_type is EditOperationType.REQUEST_LIFECYCLE_TRANSITION and not isinstance(
            self.value, str
        ):
            raise ValueError("lifecycle transition requires target state")
        expected = document_hash(self.model_dump(mode="json"), "operation_hash")
        if self.operation_hash and self.operation_hash != expected:
            raise ValueError("operation_hash is invalid")
        object.__setattr__(self, "operation_hash", expected)
        return self


class WorkingCopy(FrozenModel):
    schema_version: Literal["1.0"] = "1.0"
    resource_type: Literal["working_copy"] = "working_copy"
    workspace_uid: str
    object_uid: str
    base_revision_uid: str | None
    base_revision_number: int = Field(default=0, ge=0)
    human_key: str
    kind: str
    facets: tuple[str, ...] = ()
    effective_model_hash: str
    delegation_uid: str
    draft_fields: tuple[SemanticField, ...] = ()
    draft_fragments: tuple[Fragment, ...] = ()
    relation_proposals: tuple[RelationAssertion, ...] = ()
    requested_lifecycle_state: str | None = None
    validation_state: ValidationState = ValidationState.NOT_RUN
    edit_log: tuple[EditOperation, ...] = ()
    state: WorkingCopyState = WorkingCopyState.EDITABLE
    working_state_hash: str = ""

    @model_validator(mode="after")
    def calculate_state_hash(self) -> WorkingCopy:
        field_paths = [item.path for item in self.draft_fields]
        fragment_keys = [item.local_key for item in self.draft_fragments]
        relation_uids = [item.relation_revision_uid for item in self.relation_proposals]
        if len(field_paths) != len(set(field_paths)):
            raise ValueError("working copy field paths must be unique")
        if len(fragment_keys) != len(set(fragment_keys)):
            raise ValueError("working copy fragment keys must be unique")
        if len(relation_uids) != len(set(relation_uids)):
            raise ValueError("working copy relation proposals must be unique")
        payload = self.model_dump(mode="json", exclude={"working_state_hash", "validation_state"})
        expected = semantic_hash(payload)
        if self.working_state_hash and self.working_state_hash != expected:
            raise ValueError("working_state_hash is invalid")
        object.__setattr__(self, "working_state_hash", expected)
        return self


class Workspace(FrozenModel):
    schema_version: Literal["1.0"] = "1.0"
    resource_type: Literal["change_workspace"] = "change_workspace"
    workspace_uid: str = Field(default_factory=uuid7_candidate)
    base_commit: str
    configuration_uid: str
    effective_model_hash: str
    delegation_uid: str
    actor_uid: str
    working_copies: tuple[WorkingCopy, ...] = ()
    checkpoint_uids: tuple[str, ...] = ()
    state: WorkingCopyState = WorkingCopyState.EDITABLE
    created_at: datetime

    @model_validator(mode="after")
    def one_copy_per_object(self) -> Workspace:
        object_uids = [item.object_uid for item in self.working_copies]
        if len(object_uids) != len(set(object_uids)):
            raise ValueError("workspace permits one active Working Copy per object")
        for item in self.working_copies:
            if item.workspace_uid != self.workspace_uid:
                raise ValueError("Working Copy belongs to another workspace")
        return self


class WorkspaceCheckpoint(FrozenModel):
    schema_version: Literal["1.0"] = "1.0"
    resource_type: Literal["workspace_checkpoint"] = "workspace_checkpoint"
    checkpoint_uid: str = Field(default_factory=uuid7_candidate)
    workspace_uid: str
    base_commit: str
    working_state_hash: str
    edit_scope: tuple[str, ...]
    actor_uid: str
    validation_summary: tuple[tuple[str, str], ...]
    created_at: datetime
    git_ref: str
    workspace_state: Workspace
    checkpoint_hash: str = ""

    @model_validator(mode="after")
    def calculate_hash(self) -> WorkspaceCheckpoint:
        expected = document_hash(self.model_dump(mode="json"), "checkpoint_hash")
        if self.checkpoint_hash and self.checkpoint_hash != expected:
            raise ValueError("checkpoint_hash is invalid")
        object.__setattr__(self, "checkpoint_hash", expected)
        return self


class CandidateRevisionSet(FrozenModel):
    schema_version: Literal["1.0"] = "1.0"
    resource_type: Literal["candidate_revision_set"] = "candidate_revision_set"
    candidate_uid: str = Field(default_factory=uuid7_candidate)
    workspace_uid: str
    checkpoint_uid: str
    effective_model_hash: str
    revisions: tuple[Revision, ...]
    relation_revisions: tuple[RelationAssertion, ...]
    lifecycle_records: tuple[dict[str, JsonValue], ...]
    candidate_hash: str = ""

    @model_validator(mode="after")
    def calculate_hash(self) -> CandidateRevisionSet:
        expected = document_hash(self.model_dump(mode="json"), "candidate_hash")
        if self.candidate_hash and self.candidate_hash != expected:
            raise ValueError("candidate_hash is invalid")
        object.__setattr__(self, "candidate_hash", expected)
        return self


class SemanticChange(FrozenModel):
    object_uid: str
    path: str
    change_type: Literal["create", "set", "delete", "relation", "transition"]
    before: JsonValue = None
    after: JsonValue = None


class SemanticDiff(FrozenModel):
    schema_version: Literal["1.0"] = "1.0"
    resource_type: Literal["semantic_diff"] = "semantic_diff"
    diff_uid: str = Field(default_factory=uuid7_candidate)
    base_commit: str
    candidate_uid: str
    changes: tuple[SemanticChange, ...]
    scope: tuple[str, ...]
    diff_hash: str = ""

    @model_validator(mode="after")
    def calculate_hash(self) -> SemanticDiff:
        expected = document_hash(self.model_dump(mode="json"), "diff_hash")
        if self.diff_hash and self.diff_hash != expected:
            raise ValueError("diff_hash is invalid")
        object.__setattr__(self, "diff_hash", expected)
        return self


class Submission(FrozenModel):
    workspace: Workspace
    checkpoint: WorkspaceCheckpoint
    candidate: CandidateRevisionSet
    semantic_diff: SemanticDiff


class WorkspaceEngine:
    """Stateless editor; each method returns a new immutable aggregate."""

    @staticmethod
    def add_working_copy(workspace: Workspace, working_copy: WorkingCopy) -> Workspace:
        WorkspaceEngine._require_editable(workspace)
        if any(item.object_uid == working_copy.object_uid for item in workspace.working_copies):
            raise ValueError("LESR-WORKING-COPY-ALREADY-ACTIVE")
        return workspace.model_copy(
            update={"working_copies": workspace.working_copies + (working_copy,)}
        )

    @staticmethod
    def edit(workspace: Workspace, operation: EditOperation) -> Workspace:
        WorkspaceEngine._require_editable(workspace)
        copies = {item.object_uid: item for item in workspace.working_copies}
        copy = copies.get(operation.object_uid)
        if copy is None:
            raise ValueError("LESR-WORKING-COPY-NOT-FOUND")
        if copy.state is not WorkingCopyState.EDITABLE:
            raise ValueError("LESR-WORKING-COPY-READ-ONLY")
        fields = {item.path: item for item in copy.draft_fields}
        fragments = {item.local_key: item for item in copy.draft_fragments}
        relations = {item.relation_revision_uid: item for item in copy.relation_proposals}
        lifecycle = copy.requested_lifecycle_state
        path = operation.path or ""
        if operation.operation_type is EditOperationType.SET_FIELD:
            fields[path] = SemanticField(path=path, value=operation.value)
        elif operation.operation_type is EditOperationType.DELETE_FIELD:
            fields.pop(path, None)
        elif operation.operation_type in {
            EditOperationType.ADD_FRAGMENT,
            EditOperationType.MODIFY_FRAGMENT,
        }:
            local_key = path.removeprefix("/fragments/")
            raw = operation.value
            if not isinstance(raw, dict):
                raise ValueError("fragment value must be an object")
            fragment_fields = tuple(
                SemanticField(path=str(key), value=value) for key, value in sorted(raw.items())
            )
            if (
                operation.operation_type is EditOperationType.ADD_FRAGMENT
                and local_key in fragments
            ):
                raise ValueError("LESR-FRAGMENT-ALREADY-EXISTS")
            if (
                operation.operation_type is EditOperationType.MODIFY_FRAGMENT
                and local_key not in fragments
            ):
                raise ValueError("LESR-FRAGMENT-NOT-FOUND")
            fragments[local_key] = Fragment(local_key=local_key, fields=fragment_fields)
        elif operation.operation_type is EditOperationType.DELETE_FRAGMENT:
            fragments.pop(path.removeprefix("/fragments/"), None)
        elif operation.operation_type is EditOperationType.PROPOSE_RELATION:
            assert operation.relation is not None
            relations[operation.relation.relation_revision_uid] = operation.relation
        elif operation.operation_type is EditOperationType.WITHDRAW_RELATION:
            assert isinstance(operation.value, str)
            relations.pop(operation.value, None)
        elif operation.operation_type is EditOperationType.REQUEST_LIFECYCLE_TRANSITION:
            assert isinstance(operation.value, str)
            lifecycle = operation.value
        elif operation.operation_type is EditOperationType.CREATE_OBJECT:
            raise ValueError("create_object initializes a Working Copy; it cannot be replayed")
        updated = WorkingCopy.model_validate(
            copy.model_dump(mode="json")
            | {
                "draft_fields": tuple(fields[key] for key in sorted(fields)),
                "draft_fragments": tuple(fragments[key] for key in sorted(fragments)),
                "relation_proposals": tuple(relations[key] for key in sorted(relations)),
                "requested_lifecycle_state": lifecycle,
                "validation_state": ValidationState.NOT_RUN,
                "edit_log": copy.edit_log + (operation,),
                "working_state_hash": "",
            }
        )
        copies[operation.object_uid] = updated
        return workspace.model_copy(
            update={"working_copies": tuple(copies[key] for key in sorted(copies))}
        )

    @staticmethod
    def checkpoint(
        workspace: Workspace,
        *,
        checkpoint_uid: str,
        actor_uid: str,
        created_at: datetime,
    ) -> tuple[Workspace, WorkspaceCheckpoint]:
        WorkspaceEngine._require_editable(workspace)
        state_hash = semantic_hash(
            tuple(item.working_state_hash for item in workspace.working_copies)
        )
        checkpoint = WorkspaceCheckpoint(
            checkpoint_uid=checkpoint_uid,
            workspace_uid=workspace.workspace_uid,
            base_commit=workspace.base_commit,
            working_state_hash=state_hash,
            edit_scope=tuple(item.object_uid for item in workspace.working_copies),
            actor_uid=actor_uid,
            validation_summary=tuple(
                (item.object_uid, item.validation_state.value) for item in workspace.working_copies
            ),
            created_at=created_at,
            git_ref=f"refs/lesr/workspaces/{workspace.workspace_uid}",
            workspace_state=workspace,
        )
        updated = workspace.model_copy(
            update={"checkpoint_uids": workspace.checkpoint_uids + (checkpoint_uid,)}
        )
        return updated, checkpoint

    @staticmethod
    def submit(
        workspace: Workspace,
        *,
        checkpoint_uid: str,
        actor_uid: str,
        submitted_at: datetime,
    ) -> Submission:
        checkpointed, checkpoint = WorkspaceEngine.checkpoint(
            workspace,
            checkpoint_uid=checkpoint_uid,
            actor_uid=actor_uid,
            created_at=submitted_at,
        )
        revisions: list[Revision] = []
        relations: list[RelationAssertion] = []
        lifecycle_records: list[dict[str, JsonValue]] = []
        changes: list[SemanticChange] = []
        for copy in checkpointed.working_copies:
            revisions.append(
                Revision(
                    object_uid=copy.object_uid,
                    revision_number=copy.base_revision_number + 1,
                    parent_revision_uid=copy.base_revision_uid,
                    human_key=copy.human_key,
                    kind=copy.kind,
                    facets=copy.facets,
                    fields=copy.draft_fields,
                    fragments=copy.draft_fragments,
                    provenance_origin=ProvenanceKind.AUTHORED,
                    created_at=submitted_at,
                )
            )
            relations.extend(copy.relation_proposals)
            changes.extend(
                SemanticChange(
                    object_uid=copy.object_uid,
                    path=operation.path or "/",
                    change_type=WorkspaceEngine._change_type(operation.operation_type),
                    after=operation.value,
                )
                for operation in copy.edit_log
            )
            if copy.requested_lifecycle_state is not None:
                lifecycle_records.append(
                    {
                        "object_uid": copy.object_uid,
                        "to_state": copy.requested_lifecycle_state,
                        "actor_uid": actor_uid,
                        "occurred_at": submitted_at.isoformat().replace("+00:00", "Z"),
                    }
                )
        candidate = CandidateRevisionSet(
            workspace_uid=workspace.workspace_uid,
            checkpoint_uid=checkpoint_uid,
            effective_model_hash=workspace.effective_model_hash,
            revisions=tuple(revisions),
            relation_revisions=tuple(relations),
            lifecycle_records=tuple(lifecycle_records),
        )
        diff = SemanticDiff(
            base_commit=workspace.base_commit,
            candidate_uid=candidate.candidate_uid,
            changes=tuple(changes),
            scope=tuple(item.object_uid for item in checkpointed.working_copies),
        )
        read_only_copies = tuple(
            item.model_copy(update={"state": WorkingCopyState.SUBMITTED})
            for item in checkpointed.working_copies
        )
        submitted = checkpointed.model_copy(
            update={"working_copies": read_only_copies, "state": WorkingCopyState.SUBMITTED}
        )
        return Submission(
            workspace=submitted,
            checkpoint=checkpoint,
            candidate=candidate,
            semantic_diff=diff,
        )

    @staticmethod
    def restore(checkpoint: WorkspaceCheckpoint) -> Workspace:
        if checkpoint.workspace_state.workspace_uid != checkpoint.workspace_uid:
            raise ValueError("LESR-CHECKPOINT-WORKSPACE-MISMATCH")
        return checkpoint.workspace_state

    @staticmethod
    def _require_editable(workspace: Workspace) -> None:
        if workspace.state is not WorkingCopyState.EDITABLE:
            raise ValueError("LESR-WORKSPACE-READ-ONLY")

    @staticmethod
    def _change_type(
        operation_type: EditOperationType,
    ) -> Literal["create", "set", "delete", "relation", "transition"]:
        if operation_type is EditOperationType.CREATE_OBJECT:
            return "create"
        if operation_type in {
            EditOperationType.DELETE_FIELD,
            EditOperationType.DELETE_FRAGMENT,
        }:
            return "delete"
        if operation_type in {
            EditOperationType.PROPOSE_RELATION,
            EditOperationType.WITHDRAW_RELATION,
        }:
            return "relation"
        if operation_type is EditOperationType.REQUEST_LIFECYCLE_TRANSITION:
            return "transition"
        return "set"


def new_workspace(
    *,
    base_commit: str,
    configuration_uid: str,
    effective_model_hash: str,
    delegation_uid: str,
    actor_uid: str,
    created_at: datetime | None = None,
) -> Workspace:
    return Workspace(
        base_commit=base_commit,
        configuration_uid=configuration_uid,
        effective_model_hash=effective_model_hash,
        delegation_uid=delegation_uid,
        actor_uid=actor_uid,
        created_at=created_at or datetime.now(UTC),
    )
