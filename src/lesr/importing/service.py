"""Side-effect-free service for previewing local specification imports."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from pathlib import Path

from lesr.errors import LESRError
from lesr.importing.base import SpecificationImporter
from lesr.importing.markdown import MarkdownSpecificationImporter
from lesr.importing.models import ImportPreview, SourceDocument


class ImportService:
    """Resolve, read and dispatch source documents without modifying a project."""

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

    def _require_inside_project(self, path: Path) -> None:
        if path != self.project_root and self.project_root not in path.parents:
            raise LESRError(
                "LESR-IMPORT-PATH-INVALID",
                "Specification source is outside the project root",
                {"path": str(path), "project_root": str(self.project_root)},
            )
