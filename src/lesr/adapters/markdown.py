"""Markdown import preview that emits reviewable semantic operations only."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from lesr.domain.semantic import semantic_hash, uuid7_candidate


@dataclass(frozen=True, slots=True)
class ImportCandidate:
    candidate_uid: str
    heading: str
    body: str
    source_hash: str
    operations: tuple[dict[str, object], ...]


def preview_markdown(source: Path, *, namespace: str, kind: str) -> tuple[ImportCandidate, ...]:
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
        key = f"IMPORT-{index + 1:04d}"
        candidates.append(
            ImportCandidate(
                candidate_uid=uuid7_candidate(),
                heading=match.group(1),
                body=body,
                source_hash=source_hash,
                operations=(
                    {
                        "operation_type": "create_logical_object",
                        "target": f"canonical/objects/{object_uid}.json",
                        "payload": {"entity_uid": object_uid, "namespace": namespace, "human_key": key, "kind": kind},
                    },
                    {
                        "operation_type": "create_revision",
                        "target": f"canonical/revisions/{revision_uid}.json",
                        "payload": {"revision_uid": revision_uid, "object_uid": object_uid, "title": match.group(1), "body": body, "source_hash": source_hash},
                    },
                ),
            )
        )
    return tuple(candidates)
