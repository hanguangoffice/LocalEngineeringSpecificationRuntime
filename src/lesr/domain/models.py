"""Pydantic models for the Git-managed LESR source of truth."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

ID_PATTERN = re.compile(r"^[A-Z][A-Z0-9]*(?:-[A-Z0-9][A-Z0-9_.-]*)+$")


def utc_now() -> datetime:
    return datetime.now(UTC)


class LESRModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class Artifact(LESRModel):
    id: str
    artifact_type: str
    title: str = Field(min_length=1)
    status: str = "draft"
    version: int = Field(default=1, ge=1)
    profile_ids: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    module: str | None = None
    owner: str | None = None
    source_path: str | None = None
    content_hash: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    statement: str | None = None
    rationale: str | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)

    @field_validator("id")
    @classmethod
    def valid_id(cls, value: str) -> str:
        if not ID_PATTERN.fullmatch(value):
            raise ValueError("must use an uppercase, hyphenated stable identifier")
        return value


class Relation(LESRModel):
    id: str
    source_id: str
    relation_type: str
    target_id: str
    status: str = "active"
    rationale: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @field_validator("id", "source_id", "target_id")
    @classmethod
    def valid_id(cls, value: str) -> str:
        if not ID_PATTERN.fullmatch(value):
            raise ValueError("must use an uppercase, hyphenated stable identifier")
        return value


class Finding(LESRModel):
    id: str
    validator_id: str
    artifact_id: str
    severity: str
    status: str = "open"
    message: str
    details: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)
    resolved_at: datetime | None = None


class ChangeRequest(Artifact):
    artifact_type: str = "change_request"
    target_ids: list[str] = Field(default_factory=list)
    reason: str
    impact_analysis: dict[str, Any] | None = None


class BaselineMember(LESRModel):
    artifact_id: str
    version: int = Field(ge=1)


class Baseline(Artifact):
    artifact_type: str = "baseline"
    members: list[BaselineMember] = Field(default_factory=list)


class AuditEvent(LESRModel):
    id: str
    timestamp: datetime = Field(default_factory=utc_now)
    actor: str
    operation: str
    target_type: str
    target_id: str
    before_hash: str | None = None
    after_hash: str | None = None
    request: dict[str, Any] = Field(default_factory=dict)
    result: dict[str, Any] = Field(default_factory=dict)
