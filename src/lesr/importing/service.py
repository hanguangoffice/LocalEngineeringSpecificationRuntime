"""Preview and controlled acceptance services for local specifications."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from pathlib import Path

from lesr.domain.models import Artifact
from lesr.errors import LESRError
from lesr.importing.base import SpecificationImporter
from lesr.importing.markdown import MarkdownSpecificationImporter
from lesr.importing.models import ImportPreview, SourceDocument
from lesr.storage.yaml_repository import YamlRepository


class ImportService:
    """Preview sources and accept explicitly reviewed candidates as drafts."""

    def __init__(
        self,
        project_root: Path,
        importers: Mapping[str, SpecificationImporter] | None = None,
    ) -> None:
        self.project_root = project_root.resolve()
        self.importers = dict(importers or {".md": MarkdownSpecificationImporter()})

    def preview(
        self,
        source: Path,
        *,
        artifact_type: str = "specification_item",
        version: str | None = None,
    ) -> ImportPreview:
        path = source.resolve() if source.is_absolute() else (self.project_root / source).resolve()
        self._require_inside_project(path)
        if not path.is_file():
            raise LESRError(
                "LESR-IMPORT-SOURCE-NOT-FOUND",
                "Specification source does not exist",
                {"path": str(source)},
            )

        importer = self.importers.get(path.suffix.casefold())
        if importer is None:
            raise LESRError(
                "LESR-IMPORT-FORMAT-UNSUPPORTED",
                "Specification source format is not supported",
                {"path": str(source), "suffix": path.suffix},
            )

        try:
            text = path.read_text(encoding="utf-8-sig")
        except UnicodeDecodeError as error:
            raise LESRError(
                "LESR-IMPORT-ENCODING-INVALID",
                "Specification source must be UTF-8 encoded",
                {"path": str(source)},
            ) from error
        except OSError as error:
            raise LESRError(
                "LESR-IMPORT-READ-FAILED",
                "Specification source could not be read",
                {"path": str(source), "reason": str(error)},
            ) from error

        normalized_text = text.replace("\r\n", "\n").replace("\r", "\n")
        digest = hashlib.sha256(normalized_text.encode("utf-8")).hexdigest()
        document = SourceDocument(
            document_id=f"DOC-{digest[:12].upper()}",
            source_path=path.relative_to(self.project_root).as_posix(),
            media_type="text/markdown",
            content_hash=f"sha256:{digest}",
            version=version,
        )
        return importer.preview(
            document,
            normalized_text,
            artifact_type=artifact_type,
        )

    def accept(
        self,
        source: Path,
        candidate_id: str,
        *,
        expected_source_hash: str,
        actor: str,
        artifact_type: str = "specification_item",
        version: str | None = None,
    ) -> Artifact:
        """Accept one exact preview candidate as a formal draft Artifact."""
        confirmed_actor = actor.strip()
        if not confirmed_actor:
            raise LESRError(
                "LESR-HUMAN-CONFIRMATION-REQUIRED",
                "A human actor is required to accept an import candidate",
                {"candidate_id": candidate_id},
            )

        preview = self.preview(
            source,
            artifact_type=artifact_type,
            version=version,
        )
        if preview.source.content_hash != expected_source_hash:
            raise LESRError(
                "LESR-IMPORT-SOURCE-CHANGED",
                "Specification source changed after preview",
                {
                    "expected_source_hash": expected_source_hash,
                    "actual_source_hash": preview.source.content_hash,
                },
                "run_import_preview_again",
            )

        candidate = next(
            (item for item in preview.candidates if item.candidate_id == candidate_id),
            None,
        )
        if candidate is None:
            raise LESRError(
                "LESR-IMPORT-CANDIDATE-NOT-FOUND",
                "Import candidate is not present in the current preview",
                {"candidate_id": candidate_id},
                "run_import_preview_again",
            )
        if candidate.suggested_artifact_id is None:
            raise LESRError(
                "LESR-IMPORT-STABLE-ID-REQUIRED",
                "Import candidate requires a stable Artifact ID before acceptance",
                {"candidate_id": candidate_id},
                "add_a_stable_id_to_the_source",
            )
        if candidate.warnings:
            raise LESRError(
                "LESR-IMPORT-CANDIDATE-REVIEW-REQUIRED",
                "Import candidate has unresolved warnings",
                {
                    "candidate_id": candidate_id,
                    "warnings": [warning.model_dump(mode="json") for warning in candidate.warnings],
                },
            )

        location = candidate.source_location
        attributes = dict(candidate.attributes)
        attributes["provenance"] = {
            "document_id": preview.source.document_id,
            "source_path": preview.source.source_path,
            "source_content_hash": preview.source.content_hash,
            "source_version": preview.source.version,
            "section": location.section,
            "line_start": location.line_start,
            "line_end": location.line_end,
            "page": location.page,
            "import_candidate_id": candidate.candidate_id,
        }
        artifact = Artifact(
            id=candidate.suggested_artifact_id,
            artifact_type=candidate.artifact_type,
            title=candidate.title,
            status="draft",
            statement=candidate.statement,
            attributes=attributes,
        )
        return YamlRepository(self.project_root).create_artifact(
            artifact,
            actor=confirmed_actor,
        )

    def _require_inside_project(self, path: Path) -> None:
        if path != self.project_root and self.project_root not in path.parents:
            raise LESRError(
                "LESR-IMPORT-PATH-INVALID",
                "Specification source is outside the project root",
                {"path": str(path), "project_root": str(self.project_root)},
            )
