"""Models for reviewable specification-import previews."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, model_validator

from lesr.domain.models import LESRModel

ReviewStatus = Literal["candidate", "reviewed", "approved", "rejected"]


class SourceDocument(LESRModel):
    """A local source document identified by its normalized content."""

    document_id: str
    source_path: str = Field(min_length=1)
    media_type: str = Field(min_length=1)
    content_hash: str = Field(min_length=1)
    version: str | None = None


class SourceLocation(LESRModel):
    """The exact location from which a candidate was extracted."""

    document_id: str
    section: str
    line_start: int | None = Field(default=None, ge=1)
    line_end: int | None = Field(default=None, ge=1)
    page: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def valid_line_range(self) -> SourceLocation:
        if (
            self.line_start is not None
            and self.line_end is not None
            and self.line_end < self.line_start
        ):
            raise ValueError("line_end must be greater than or equal to line_start")
        return self


class ImportWarning(LESRModel):
    """A stable, actionable warning that requires review."""

    code: str
    message: str
    line: int | None = Field(default=None, ge=1)


class CandidateArtifact(LESRModel):
    """A proposed Artifact that has not entered the formal repository."""

    candidate_id: str
    suggested_artifact_id: str | None = None
    artifact_type: str = Field(min_length=1)
    title: str = Field(min_length=1)
    statement: str = Field(min_length=1)
    attributes: dict[str, Any] = Field(default_factory=dict)
    source_location: SourceLocation
    confidence: float = Field(ge=0.0, le=1.0)
    warnings: list[ImportWarning] = Field(default_factory=list)
    review_status: ReviewStatus = "candidate"


class ImportPreview(LESRModel):
    """A side-effect-free preview returned to a human reviewer."""

    source: SourceDocument
    candidates: list[CandidateArtifact] = Field(default_factory=list)
    warnings: list[ImportWarning] = Field(default_factory=list)
