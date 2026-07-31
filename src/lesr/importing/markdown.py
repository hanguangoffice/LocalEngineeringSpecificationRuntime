"""Deterministic Markdown importer for explicitly structured specifications."""

from __future__ import annotations

import hashlib
import re

from lesr.domain.models import ID_PATTERN
from lesr.importing.models import (
    CandidateArtifact,
    ImportPreview,
    ImportWarning,
    SourceDocument,
    SourceLocation,
)

SECTION_BOUNDARY = re.compile(r"^#{1,2}\s+\S")
ITEM_HEADING = re.compile(r"^##\s+(?P<heading>.+?)\s*$")
REQUIRED_TERM = re.compile(r"\b(?:shall|must)\b", re.IGNORECASE)
ADVISORY_TERM = re.compile(r"\bshould\b", re.IGNORECASE)


class MarkdownSpecificationImporter:
    """Treat each level-two heading and its body as one candidate Artifact."""

    def preview(
        self,
        document: SourceDocument,
        text: str,
        *,
        artifact_type: str,
    ) -> ImportPreview:
        lines = text.splitlines()
        boundaries = [index for index, line in enumerate(lines) if SECTION_BOUNDARY.match(line)]
        candidates: list[CandidateArtifact] = []
        warnings: list[ImportWarning] = []

        for position, start in enumerate(boundaries):
            heading_match = ITEM_HEADING.match(lines[start])
            if heading_match is None:
                continue
            end = boundaries[position + 1] if position + 1 < len(boundaries) else len(lines)
            heading = heading_match.group("heading").strip()
            content_start = start + 1
            content_end = end
            while content_start < content_end and not lines[content_start].strip():
                content_start += 1
            while content_end > content_start and not lines[content_end - 1].strip():
                content_end -= 1
            section_lines = lines[content_start:content_end]
            statement = "\n".join(line.rstrip() for line in section_lines).strip()
            line_number = start + 1

            if not statement:
                warnings.append(
                    ImportWarning(
                        code="LESR-IMPORT-EMPTY-SECTION",
                        message=f"Section '{heading}' has no normative content",
                        line=line_number,
                    )
                )
                continue

            suggested_id, title = self._heading_parts(heading)
            candidate_warnings: list[ImportWarning] = []
            if suggested_id is None:
                warning = ImportWarning(
                    code="LESR-IMPORT-ID-MISSING",
                    message=f"Section '{heading}' does not start with a stable LESR ID",
                    line=line_number,
                )
                candidate_warnings.append(warning)
                warnings.append(warning)

            candidate_id = self._candidate_id(
                document,
                line_number,
                suggested_id,
                title,
                statement,
            )
            candidates.append(
                CandidateArtifact(
                    candidate_id=candidate_id,
                    suggested_artifact_id=suggested_id,
                    artifact_type=artifact_type,
                    title=title,
                    statement=statement,
                    attributes={"normative_level": self._normative_level(statement)},
                    source_location=SourceLocation(
                        document_id=document.document_id,
                        section=heading,
                        line_start=line_number,
                        line_end=content_end,
                    ),
                    confidence=1.0 if suggested_id else 0.7,
                    warnings=candidate_warnings,
                )
            )

        if not candidates:
            warnings.append(
                ImportWarning(
                    code="LESR-IMPORT-NO-CANDIDATES",
                    message="No non-empty level-two specification sections were found",
                )
            )
        return ImportPreview(source=document, candidates=candidates, warnings=warnings)

    @staticmethod
    def _heading_parts(heading: str) -> tuple[str | None, str]:
        first, separator, remainder = heading.partition(" ")
        if ID_PATTERN.fullmatch(first):
            return first, remainder.strip() if separator and remainder.strip() else first
        return None, heading

    @staticmethod
    def _candidate_id(
        document: SourceDocument,
        line_number: int,
        suggested_id: str | None,
        title: str,
        statement: str,
    ) -> str:
        seed = "|".join(
            [
                document.content_hash,
                str(line_number),
                suggested_id or "",
                title,
                statement,
            ]
        )
        digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:12].upper()
        return f"CAND-{digest}"

    @staticmethod
    def _normative_level(statement: str) -> str:
        if REQUIRED_TERM.search(statement) or any(
            token in statement for token in ("必须", "不得", "应当")
        ):
            return "required"
        if ADVISORY_TERM.search(statement) or "建议" in statement:
            return "advisory"
        return "unspecified"
