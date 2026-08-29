"""Contracts for source-backed requirement intake."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class FrozenIntakeModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class SourceFile(FrozenIntakeModel):
    path: str
    bytes: int = Field(ge=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class TemplateSource(FrozenIntakeModel):
    source_uid: str
    display_name: str
    repository: str
    commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    license: str
    usage: Literal["vendored_template", "method_reference"]
    files: tuple[SourceFile, ...]
    notes: str


class TemplateArtifact(FrozenIntakeModel):
    artifact_uid: str
    display_name: str
    source_uid: str
    path: str
    purpose: str
    role: Literal["primary", "companion", "reference"]


class TemplatePack(FrozenIntakeModel):
    pack_uid: str
    display_name: str
    summary: str
    source_uids: tuple[str, ...]
    signals: tuple[str, ...] = ()
    priority: int = Field(ge=0)
    architecture_depth: Literal["lean", "standard", "full"]
    artifacts: tuple[TemplateArtifact, ...]


class RequirementCategory(StrEnum):
    GOAL = "goal"
    FUNCTION = "function"
    QUALITY = "quality"
    CONSTRAINT = "constraint"
    TEST = "test"
    DELIVERABLE = "deliverable"
    DEPENDENCY = "dependency"
    SAFETY = "safety"


class RequirementItem(FrozenIntakeModel):
    human_key: str
    statement: str
    category: RequirementCategory
    source_line: int = Field(ge=1)


class GapDisposition(StrEnum):
    COVERED = "covered"
    DEFAULTED = "defaulted"
    DEFERRED = "deferred"
    NEEDS_DECISION = "needs_decision"
    BLOCKING = "blocking"


class GapItem(FrozenIntakeModel):
    topic: str
    disposition: GapDisposition
    reason: str
    recommended_answer: str | None = None
    source_rule: str


class IntakeQuestion(FrozenIntakeModel):
    topic: str
    question: str
    recommended_answer: str
    consequence: str
    source_rule: str


class TemplateAlternative(FrozenIntakeModel):
    pack_uid: str
    display_name: str
    score: int = Field(ge=0)


class IntakeRequest(FrozenIntakeModel):
    description: str = Field(min_length=20, max_length=100_000)
    project_name: str | None = Field(default=None, max_length=120)
    known_repository: str | None = Field(default=None, max_length=1024)


class IntakeAnalysis(FrozenIntakeModel):
    selected_pack: TemplatePack
    alternatives: tuple[TemplateAlternative, ...]
    selection_reasons: tuple[str, ...]
    requirements: tuple[RequirementItem, ...]
    gaps: tuple[GapItem, ...]
    next_question: IntakeQuestion | None
    source_template: str
    starter_document: str
    source_fidelity: Literal["verified_upstream_snapshot"] = "verified_upstream_snapshot"
    can_continue_with_defaults: bool
