"""SQLite persistence for local, non-authoritative Presentation Mappings.

Mappings in this store are runtime navigation state.  They live only in the
project's ``.lesr/runtime.sqlite3`` and are never written to Canonical Git.
SQLite keys and transactions provide persistence; no additional content hash
or audit chain is introduced here.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from lesr.domain.presentation import PresentationMappingRevision
from lesr.domain.semantic import canonical_json


class PresentationMappingStore:
    """Persist template/profile presentation revisions across local restarts."""

    def __init__(self, project: Path) -> None:
        self.path = project / ".lesr" / "runtime.sqlite3"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def put(
        self,
        template_pack_uid: str,
        mapping: PresentationMappingRevision,
    ) -> PresentationMappingRevision:
        encoded = canonical_json(mapping)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT value FROM runtime_presentation_mappings WHERE revision_uid = ?",
                (mapping.revision_uid,),
            ).fetchone()
            if row is not None:
                if str(row[0]) != encoded:
                    raise ValueError("presentation mapping revision is immutable")
                return mapping
            connection.execute(
                """
                INSERT INTO runtime_presentation_mappings (
                    revision_uid, presentation_mapping_uid, template_pack_uid,
                    revision_number, value
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    mapping.revision_uid,
                    mapping.presentation_mapping_uid,
                    template_pack_uid,
                    mapping.revision_number,
                    encoded,
                ),
            )
        return mapping

    def get(self, revision_uid: str) -> PresentationMappingRevision:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT value FROM runtime_presentation_mappings WHERE revision_uid = ?",
                (revision_uid,),
            ).fetchone()
        if row is None:
            raise KeyError(revision_uid)
        return PresentationMappingRevision.model_validate(self._load_value(row[0]))

    def latest_for_pack(
        self,
        template_pack_uid: str,
    ) -> PresentationMappingRevision | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT value
                FROM runtime_presentation_mappings
                WHERE template_pack_uid = ?
                ORDER BY rowid DESC
                LIMIT 1
                """,
                (template_pack_uid,),
            ).fetchone()
        if row is None:
            return None
        return PresentationMappingRevision.model_validate(self._load_value(row[0]))

    def list(
        self,
        template_pack_uid: str | None = None,
    ) -> tuple[PresentationMappingRevision, ...]:
        where = " WHERE template_pack_uid = ?" if template_pack_uid is not None else ""
        parameters = (template_pack_uid,) if template_pack_uid is not None else ()
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT value FROM runtime_presentation_mappings"
                + where
                + " ORDER BY rowid",
                parameters,
            ).fetchall()
        return tuple(
            PresentationMappingRevision.model_validate(self._load_value(row[0]))
            for row in rows
        )

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS runtime_presentation_mappings (
                    revision_uid TEXT PRIMARY KEY,
                    presentation_mapping_uid TEXT NOT NULL,
                    template_pack_uid TEXT NOT NULL,
                    revision_number INTEGER NOT NULL,
                    value TEXT NOT NULL,
                    UNIQUE (presentation_mapping_uid, revision_number)
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS runtime_presentation_mappings_by_pack
                ON runtime_presentation_mappings (template_pack_uid)
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    @staticmethod
    def _load_value(raw: object) -> dict[str, object]:
        value = json.loads(str(raw))
        if not isinstance(value, dict):
            raise TypeError("Presentation Mapping record is not a JSON object")
        return value
