"""Rebuildable SQLite FTS5 index derived solely from YAML source data."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from lesr.domain.models import Artifact, Relation
from lesr.errors import LESRError


class SQLiteIndex:
    def __init__(self, project_root: Path) -> None:
        self.path = project_root.resolve() / ".lesr" / "index.db"

    def rebuild(self, artifacts: list[Artifact], relations: list[Relation]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript("""
                DROP TABLE IF EXISTS artifacts;
                DROP TABLE IF EXISTS relations;
                DROP TABLE IF EXISTS artifact_fts;
                CREATE TABLE artifacts (id TEXT PRIMARY KEY, artifact_type TEXT NOT NULL, title TEXT NOT NULL, status TEXT NOT NULL, module TEXT, profile_ids_json TEXT NOT NULL, tags_json TEXT NOT NULL, source_path TEXT, content_text TEXT NOT NULL, attributes_json TEXT NOT NULL, content_hash TEXT, current_version INTEGER NOT NULL);
                CREATE TABLE relations (id TEXT PRIMARY KEY, source_id TEXT NOT NULL, relation_type TEXT NOT NULL, target_id TEXT NOT NULL, status TEXT NOT NULL, rationale TEXT);
                CREATE INDEX relations_source_idx ON relations(source_id);
                CREATE INDEX relations_target_idx ON relations(target_id);
                CREATE VIRTUAL TABLE artifact_fts USING fts5(id UNINDEXED, title, content_text);
            """)
            conn.executemany("INSERT INTO artifacts VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", [self._artifact_row(item) for item in artifacts])
            conn.executemany("INSERT INTO relations VALUES (?, ?, ?, ?, ?, ?)", [(item.id, item.source_id, item.relation_type, item.target_id, item.status, item.rationale) for item in relations])
            conn.executemany("INSERT INTO artifact_fts VALUES (?, ?, ?)", [(item.id, item.title, self._text(item)) for item in artifacts])

    def get(self, artifact_id: str) -> dict[str, object]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM artifacts WHERE id = ?", (artifact_id,)).fetchone()
        if row is None:
            raise LESRError("LESR-ARTIFACT-NOT-FOUND", "Artifact does not exist in index", {"artifact_id": artifact_id})
        return dict(row)

    def list_artifacts(self, *, artifact_type: str | None = None, status: str | None = None, module: str | None = None) -> list[dict[str, object]]:
        clauses, params = [], []
        for column, value in (("artifact_type", artifact_type), ("status", status), ("module", module)):
            if value is not None:
                clauses.append(f"{column} = ?")
                params.append(value)
        query = "SELECT * FROM artifacts" + (" WHERE " + " AND ".join(clauses) if clauses else "") + " ORDER BY id"
        with self._connect() as conn:
            return [dict(row) for row in conn.execute(query, params)]

    def search(self, query: str) -> list[dict[str, object]]:
        with self._connect() as conn:
            rows = conn.execute("SELECT a.* FROM artifact_fts f JOIN artifacts a ON a.id=f.id WHERE artifact_fts MATCH ? ORDER BY bm25(artifact_fts)", (query,)).fetchall()
        return [dict(row) for row in rows]

    def related(self, artifact_id: str, depth: int = 1) -> list[dict[str, object]]:
        with self._connect() as conn:
            rows = conn.execute("""WITH RECURSIVE graph(id, depth) AS (SELECT ?, 0 UNION SELECT CASE WHEN r.source_id = graph.id THEN r.target_id ELSE r.source_id END, graph.depth + 1 FROM relations r JOIN graph ON r.source_id = graph.id OR r.target_id = graph.id WHERE r.status='active' AND graph.depth < ?) SELECT DISTINCT a.* FROM graph g JOIN artifacts a ON a.id = g.id WHERE g.depth > 0""", (artifact_id, depth)).fetchall()
        return [dict(row) for row in rows]

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def _text(artifact: Artifact) -> str:
        return " ".join(filter(None, [artifact.title, artifact.statement, artifact.rationale, json.dumps(artifact.attributes, ensure_ascii=False)]))

    def _artifact_row(self, item: Artifact) -> tuple[object, ...]:
        return (item.id, item.artifact_type, item.title, item.status, item.module, json.dumps(item.profile_ids), json.dumps(item.tags), item.source_path, self._text(item), json.dumps(item.attributes), item.content_hash, item.version)
