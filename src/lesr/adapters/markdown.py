"""Markdown import preview that emits reviewable semantic operations only."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from lesr.domain.semantic import semantic_hash, uuid7_candidate


@dataclass(frozen=True, slots=True)
class ImportCandidate:
    candidate_uid: str
    heading: str
    body: str
    source_hash: str
    operations: tuple[dict[str, object], ...]


def preview_markdown(
    source: Path,
    *,
    namespace: str,
    kind: str,
    rights_basis: str,
    license_id: str,
) -> tuple[ImportCandidate, ...]:
    raw = source.read_bytes()
    text = raw.decode("utf-8")
    source_hash = semantic_hash({"bytes_utf8": text})
    matches = list(re.finditer(r"(?m)^#{1,6}\s+(.+?)\s*$", text))
    candidates: list[ImportCandidate] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        body = text[match.end() : end].strip()
        if not body:
            continue
        object_uid = uuid7_candidate()
        revision_uid = uuid7_candidate()
        key = (
            f"IMPORT-{source_hash.removeprefix('sha256:')[:12].upper()}-"
            f"{index + 1:04d}"
        )
        created_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
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
        revision_without_hash: dict[str, object] = {
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
                {"path": "/title", "value": match.group(1)},
                {"path": "/statement", "value": body},
                {"path": "/source/path", "value": source.name},
                {"path": "/source/section", "value": index + 1},
                {"path": "/source/hash", "value": source_hash},
                {"path": "/source/rights_basis", "value": rights_basis},
                {"path": "/source/license", "value": license_id},
            ],
            "fragments": [],
            "provenance_origin": "imported",
            "created_at": created_at,
        }
        revision = revision_without_hash | {
            "content_hash": semantic_hash(revision_without_hash)
        }
        candidates.append(
            ImportCandidate(
                candidate_uid=uuid7_candidate(),
                heading=match.group(1),
                body=body,
                source_hash=source_hash,
                operations=(
                    {
                        "operation_type": "create_logical_object",
                        "resource": logical,
                    },
                    {
                        "operation_type": "create_revision",
                        "resource": revision,
                    },
                ),
            )
        )
    return tuple(candidates)
