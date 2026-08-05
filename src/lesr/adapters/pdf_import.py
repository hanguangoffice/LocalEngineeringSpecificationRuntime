"""Permission-aware PDF preview into reviewable Workspace operations."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from pypdf import PdfReader

from lesr.domain.semantic import semantic_hash, uuid7_candidate


class EncryptedPdfRejected(PermissionError):
    """LESR never decrypts or bypasses restrictions on import source PDFs."""


@dataclass(frozen=True, slots=True)
class PdfImportCandidate:
    candidate_uid: str
    heading: str
    page_number: int
    source_hash: str
    operations: tuple[dict[str, object], ...]


_PROCESS_HEADING = re.compile(r"\b(?:ACQ|MAN|PIM|REU|SUP|SYS|SWE)\.\d+\b", re.IGNORECASE)


def preview_pdf(
    source: Path,
    *,
    namespace: str,
    kind: str,
    rights_basis: str,
    license_id: str,
    page_numbers: tuple[int, ...] | None = None,
) -> tuple[PdfImportCandidate, ...]:
    """Extract selected unencrypted pages; returned candidates cannot mutate Canonical State."""
    raw = source.read_bytes()
    source_hash = "sha256:" + hashlib.sha256(raw).hexdigest()
    reader = PdfReader(source, strict=True)
    if reader.is_encrypted:
        raise EncryptedPdfRejected(
            "encrypted/restricted PDF import is refused; provide a rights-cleared source"
        )
    selected_pages = page_numbers or tuple(range(1, len(reader.pages) + 1))
    candidates: list[PdfImportCandidate] = []
    for page_number in selected_pages:
        if page_number < 1 or page_number > len(reader.pages):
            raise ValueError(f"PDF page is outside the document: {page_number}")
        text = reader.pages[page_number - 1].extract_text() or ""
        normalized = "\n".join(line.strip() for line in text.splitlines() if line.strip())
        if len(normalized) < 40:
            continue
        process = _PROCESS_HEADING.search(normalized)
        heading = process.group(0).upper() if process else f"PDF page {page_number}"
        candidates.append(
            _candidate(
                source,
                namespace,
                kind,
                page_number,
                heading,
                normalized,
                source_hash,
                rights_basis,
                license_id,
            )
        )
    return tuple(candidates)


def _candidate(
    source: Path,
    namespace: str,
    kind: str,
    page_number: int,
    heading: str,
    body: str,
    source_hash: str,
    rights_basis: str,
    license_id: str,
) -> PdfImportCandidate:
    object_uid = uuid7_candidate()
    revision_uid = uuid7_candidate()
    created_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    key = f"PDF-{source_hash.removeprefix('sha256:')[:12].upper()}-{page_number:04d}"
    logical: dict[str, object] = {
        "schema_version": "1.0",
        "resource_type": "logical_object",
        "entity_uid": object_uid,
        "namespace": namespace,
        "human_key": key,
        "kind": kind,
        "core_class": "governed_object",
        "facets": ["imported", "traceability"],
        "aliases": [],
        "external_identities": [],
        "created_at": created_at,
    }
    without_hash: dict[str, object] = {
        "schema_version": "1.0",
        "resource_type": "revision",
        "revision_uid": revision_uid,
        "object_uid": object_uid,
        "revision_number": 1,
        "parent_revision_uid": None,
        "human_key": key,
        "kind": kind,
        "facets": ["imported", "traceability"],
        "fields": [
            {"path": "/title", "value": heading},
            {"path": "/statement", "value": body},
            {"path": "/source/path", "value": source.name},
            {"path": "/source/page", "value": page_number},
            {"path": "/source/hash", "value": source_hash},
            {"path": "/source/extractor", "value": "pypdf-6"},
            {"path": "/source/rights_basis", "value": rights_basis},
            {"path": "/source/license", "value": license_id},
        ],
        "fragments": [],
        "provenance_origin": "imported",
        "created_at": created_at,
    }
    revision = without_hash | {"content_hash": semantic_hash(without_hash)}
    return PdfImportCandidate(
        uuid7_candidate(),
        heading,
        page_number,
        source_hash,
        (
            {"operation_type": "create_logical_object", "resource": logical},
            {"operation_type": "create_revision", "resource": revision},
        ),
    )
