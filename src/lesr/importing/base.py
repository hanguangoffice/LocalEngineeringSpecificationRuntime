"""Importer contract shared by deterministic and future assisted importers."""

from typing import Protocol

from lesr.importing.models import ImportPreview, SourceDocument


class SpecificationImporter(Protocol):
    """Convert source text into review candidates without writing formal data."""

    def preview(
        self,
        document: SourceDocument,
        text: str,
        *,
        artifact_type: str,
    ) -> ImportPreview:
        """Return candidates and warnings for a source document."""
        ...
