"""Immutable validation evidence produced before human review."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import Field, model_validator

from lesr.domain.rules import EnforcementEffect, RuleOutcome
from lesr.domain.semantic import FrozenModel, JsonValue, semantic_hash, uuid7_candidate


class ValidationObservation(FrozenModel):
    observation_uid: str = Field(default_factory=uuid7_candidate)
    rule_uid: str
    rule_revision_uid: str
    target_uid: str
    target_revision_uid: str | None = None
    outcome: RuleOutcome
    enforcement: EnforcementEffect
    explanation: JsonValue


class ValidationRun(FrozenModel):
    schema_version: Literal["1.0"] = "1.0"
    resource_type: Literal["validation_run"] = "validation_run"
    validation_run_uid: str = Field(default_factory=uuid7_candidate)
    workspace_uid: str
    base_commit: str
    configuration_uid: str
    effective_model_hash: str
    candidate_hash: str
    observations: tuple[ValidationObservation, ...]
    finding_uids: tuple[str, ...]
    outcome: Literal["pass", "fail", "indeterminate"]
    completed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    content_hash: str = ""

    @model_validator(mode="after")
    def calculate_hash(self) -> ValidationRun:
        calculated = semantic_hash(
            self.model_dump(mode="json", exclude={"content_hash"}, exclude_none=True)
        )
        if self.content_hash and self.content_hash != calculated:
            raise ValueError("validation run content_hash is invalid")
        object.__setattr__(self, "content_hash", calculated)
        return self


class ValidationFinding(FrozenModel):
    schema_version: Literal["1.0"] = "1.0"
    resource_type: Literal["validation_finding"] = "validation_finding"
    finding_uid: str = Field(default_factory=uuid7_candidate)
    validation_run_uid: str
    rule_uid: str
    rule_revision_uid: str
    subject_uid: str
    subject_revision_uid: str | None = None
    outcome: RuleOutcome
    enforcement: EnforcementEffect
    blocking: bool
    status: Literal["open", "resolved", "suppressed_by_deviation"] = "open"
    deviation_revision_uid: str | None = None
    explanation: JsonValue
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    content_hash: str = ""

    @model_validator(mode="after")
    def calculate_hash(self) -> ValidationFinding:
        calculated = semantic_hash(
            self.model_dump(mode="json", exclude={"content_hash"}, exclude_none=True)
        )
        if self.content_hash and self.content_hash != calculated:
            raise ValueError("validation finding content_hash is invalid")
        object.__setattr__(self, "content_hash", calculated)
        return self
