"""SQLite persistence for local-only Mission orchestration state.

All records in this module live in ``.lesr/runtime.sqlite3``.  They are operational
coordination state and MUST NOT be copied into the Canonical Git tree or Workspace
refs.  Integrity is provided by SQLite primary keys, foreign keys and transactions;
the store deliberately adds no content, request or audit-chain hashes.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from lesr.domain.decision import DecisionRequest, DecisionResolution, MissionMandate
from lesr.domain.mission import AgentRun, Mission
from lesr.domain.semantic import canonical_json


class MissionConcurrencyError(RuntimeError):
    """The stored Mission changed after a coordinator read it."""


class MissionStore:
    """Transactional local store for Missions, runs, mandates and decisions."""

    def __init__(self, project: Path) -> None:
        self.path = project / ".lesr" / "runtime.sqlite3"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def put_mission(self, mission: Mission) -> Mission:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._put_mission_rows(connection, mission)
        return mission

    def put_mission_with_mandate(
        self,
        mission: Mission,
        mandate: MissionMandate,
    ) -> None:
        """Create or update the Mission and its authority in one transaction."""

        if mandate.mission_uid != mission.mission_uid:
            raise ValueError("MissionMandate does not belong to the Mission")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._put_mission_rows(connection, mission)
            self._put_mandate_row(connection, mandate)

    def put_execution_state(
        self,
        mission: Mission,
        run: AgentRun,
        *,
        expected_mission: Mission,
    ) -> None:
        """Atomically persist a Mission transition and its matching AgentRun."""

        package = next(
            (
                item
                for item in mission.work_packages
                if item.work_package_uid == run.work_package_uid
            ),
            None,
        )
        if run.mission_uid != mission.mission_uid or package is None:
            raise ValueError("AgentRun does not belong to the Mission state")
        if run.agent_run_uid not in package.agent_run_uids:
            raise ValueError("Mission state does not reference the AgentRun")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._assert_current_mission(connection, expected_mission)
            self._put_mission_rows(connection, mission)
            self._put_agent_run_row(connection, run)

    def put_decision_state(
        self,
        mission: Mission,
        request: DecisionRequest,
        *,
        expected_mission: Mission,
    ) -> None:
        """Persist a waiting Mission and its immutable DecisionRequest atomically."""

        package_uids = {item.work_package_uid for item in mission.work_packages}
        if (
            mission.mission_uid != expected_mission.mission_uid
            or request.mission_uid != mission.mission_uid
            or request.work_package_uid not in package_uids
        ):
            raise ValueError("DecisionRequest does not belong to the Mission state")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._assert_current_mission(connection, expected_mission)
            self._put_mission_rows(connection, mission)
            self._put_decision_request_row(connection, request)

    def put_decision_resolution_state(
        self,
        mission: Mission,
        resolution: DecisionResolution,
        *,
        expected_mission: Mission,
    ) -> None:
        """Persist one resolution and the resumed Mission in one transaction."""

        if mission.mission_uid != expected_mission.mission_uid:
            raise ValueError("resolved Mission identity changed")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._assert_current_mission(connection, expected_mission)
            request_row = connection.execute(
                "SELECT value FROM agentic_decision_requests "
                "WHERE decision_request_uid = ?",
                (resolution.decision_request_uid,),
            ).fetchone()
            if request_row is None:
                raise KeyError(resolution.decision_request_uid)
            request = DecisionRequest.model_validate(self._load_value(request_row[0]))
            package_uids = {item.work_package_uid for item in mission.work_packages}
            if (
                request.mission_uid != mission.mission_uid
                or request.work_package_uid not in package_uids
            ):
                raise ValueError("DecisionResolution does not belong to the Mission state")
            self._put_mission_rows(connection, mission)
            self._record_decision_resolution_row(connection, resolution)

    def get_mission(self, mission_uid: str) -> Mission:
        return Mission.model_validate(
            self._get_value("agentic_missions", "mission_uid", mission_uid)
        )

    def list_missions(self) -> tuple[Mission, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT value FROM agentic_missions ORDER BY created_at, mission_uid"
            ).fetchall()
        return tuple(Mission.model_validate(self._load_value(row[0])) for row in rows)

    def put_mission_mandate(self, mandate: MissionMandate) -> MissionMandate:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._put_mandate_row(connection, mandate)
        return mandate

    def get_mission_mandate(self, mandate_uid: str) -> MissionMandate:
        return MissionMandate.model_validate(
            self._get_value("agentic_mandates", "mandate_uid", mandate_uid)
        )

    def put_mandate(self, mandate: MissionMandate) -> MissionMandate:
        """Short alias for callers that already operate inside one Mission."""

        return self.put_mission_mandate(mandate)

    def get_mandate(self, mandate_uid: str) -> MissionMandate:
        """Short alias for callers that already operate inside one Mission."""

        return self.get_mission_mandate(mandate_uid)

    def put_agent_run(self, run: AgentRun) -> AgentRun:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._put_agent_run_row(connection, run)
        return run

    def get_agent_run(self, agent_run_uid: str) -> AgentRun:
        return AgentRun.model_validate(
            self._get_value("agentic_agent_runs", "agent_run_uid", agent_run_uid)
        )

    def list_agent_runs(
        self,
        mission_uid: str | None = None,
        work_package_uid: str | None = None,
    ) -> tuple[AgentRun, ...]:
        clauses: list[str] = []
        parameters: list[str] = []
        if mission_uid is not None:
            clauses.append("mission_uid = ?")
            parameters.append(mission_uid)
        if work_package_uid is not None:
            clauses.append("work_package_uid = ?")
            parameters.append(work_package_uid)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT value FROM agentic_agent_runs"
                + where
                + " ORDER BY created_at, agent_run_uid",
                tuple(parameters),
            ).fetchall()
        return tuple(AgentRun.model_validate(self._load_value(row[0])) for row in rows)

    def put_decision_request(self, request: DecisionRequest) -> DecisionRequest:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._put_decision_request_row(connection, request)
        return request

    def get_decision_request(self, decision_request_uid: str) -> DecisionRequest:
        return DecisionRequest.model_validate(
            self._get_value(
                "agentic_decision_requests",
                "decision_request_uid",
                decision_request_uid,
            )
        )

    def list_decision_requests(
        self,
        mission_uid: str | None = None,
        *,
        unresolved_only: bool = False,
    ) -> tuple[DecisionRequest, ...]:
        clauses: list[str] = []
        parameters: list[str] = []
        if mission_uid is not None:
            clauses.append("request.mission_uid = ?")
            parameters.append(mission_uid)
        if unresolved_only:
            clauses.append("resolution.resolution_uid IS NULL")
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT request.value
                FROM agentic_decision_requests AS request
                LEFT JOIN agentic_decision_resolutions AS resolution
                    ON resolution.decision_request_uid = request.decision_request_uid
                """
                + where
                + " ORDER BY request.created_at, request.decision_request_uid",
                tuple(parameters),
            ).fetchall()
        return tuple(
            DecisionRequest.model_validate(self._load_value(row[0])) for row in rows
        )

    def record_decision_resolution(
        self, resolution: DecisionResolution
    ) -> DecisionResolution:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._record_decision_resolution_row(connection, resolution)
        return resolution

    def get_decision_resolution(self, resolution_uid: str) -> DecisionResolution:
        return DecisionResolution.model_validate(
            self._get_value(
                "agentic_decision_resolutions",
                "resolution_uid",
                resolution_uid,
            )
        )

    def decision_resolution_for(
        self, decision_request_uid: str
    ) -> DecisionResolution | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT value FROM agentic_decision_resolutions "
                "WHERE decision_request_uid = ?",
                (decision_request_uid,),
            ).fetchone()
        if row is None:
            return None
        return DecisionResolution.model_validate(self._load_value(row[0]))

    def list_decision_resolutions(self) -> tuple[DecisionResolution, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT value FROM agentic_decision_resolutions "
                "ORDER BY resolved_at, resolution_uid"
            ).fetchall()
        return tuple(
            DecisionResolution.model_validate(self._load_value(row[0])) for row in rows
        )

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS agentic_missions (
                    mission_uid TEXT PRIMARY KEY,
                    state TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS agentic_work_packages (
                    mission_uid TEXT NOT NULL,
                    work_package_uid TEXT NOT NULL,
                    PRIMARY KEY (mission_uid, work_package_uid),
                    FOREIGN KEY (mission_uid)
                        REFERENCES agentic_missions (mission_uid)
                );

                CREATE TABLE IF NOT EXISTS agentic_mandates (
                    mandate_uid TEXT PRIMARY KEY,
                    mission_uid TEXT NOT NULL,
                    issued_at TEXT NOT NULL,
                    value TEXT NOT NULL,
                    UNIQUE (mandate_uid, mission_uid),
                    FOREIGN KEY (mission_uid)
                        REFERENCES agentic_missions (mission_uid)
                );

                CREATE TABLE IF NOT EXISTS agentic_agent_runs (
                    agent_run_uid TEXT PRIMARY KEY,
                    mission_uid TEXT NOT NULL,
                    work_package_uid TEXT NOT NULL,
                    state TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    value TEXT NOT NULL,
                    FOREIGN KEY (mission_uid, work_package_uid)
                        REFERENCES agentic_work_packages (mission_uid, work_package_uid)
                );

                CREATE TABLE IF NOT EXISTS agentic_decision_requests (
                    decision_request_uid TEXT PRIMARY KEY,
                    mission_uid TEXT NOT NULL,
                    work_package_uid TEXT NOT NULL,
                    mandate_uid TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    value TEXT NOT NULL,
                    FOREIGN KEY (mission_uid, work_package_uid)
                        REFERENCES agentic_work_packages (mission_uid, work_package_uid),
                    FOREIGN KEY (mandate_uid, mission_uid)
                        REFERENCES agentic_mandates (mandate_uid, mission_uid)
                );

                CREATE TABLE IF NOT EXISTS agentic_decision_resolutions (
                    resolution_uid TEXT PRIMARY KEY,
                    decision_request_uid TEXT NOT NULL UNIQUE,
                    resolved_at TEXT NOT NULL,
                    value TEXT NOT NULL,
                    FOREIGN KEY (decision_request_uid)
                        REFERENCES agentic_decision_requests (decision_request_uid)
                );

                CREATE INDEX IF NOT EXISTS agentic_agent_runs_by_mission
                    ON agentic_agent_runs (mission_uid, created_at);
                CREATE INDEX IF NOT EXISTS agentic_decisions_by_mission
                    ON agentic_decision_requests (mission_uid, created_at);
                """
            )

    @staticmethod
    def _put_mission_rows(connection: sqlite3.Connection, mission: Mission) -> None:
        encoded = canonical_json(mission)
        package_uids = {item.work_package_uid for item in mission.work_packages}
        connection.execute(
            """
            INSERT INTO agentic_missions (
                mission_uid, state, created_at, updated_at, value
            ) VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(mission_uid) DO UPDATE SET
                state = excluded.state,
                created_at = excluded.created_at,
                updated_at = excluded.updated_at,
                value = excluded.value
            """,
            (
                mission.mission_uid,
                mission.state.value,
                mission.created_at.isoformat(),
                mission.updated_at.isoformat(),
                encoded,
            ),
        )
        existing = {
            str(row[0])
            for row in connection.execute(
                "SELECT work_package_uid FROM agentic_work_packages WHERE mission_uid = ?",
                (mission.mission_uid,),
            ).fetchall()
        }
        connection.executemany(
            "INSERT INTO agentic_work_packages (mission_uid, work_package_uid) VALUES (?, ?)",
            (
                (mission.mission_uid, work_package_uid)
                for work_package_uid in sorted(package_uids - existing)
            ),
        )
        connection.executemany(
            "DELETE FROM agentic_work_packages WHERE mission_uid = ? AND work_package_uid = ?",
            (
                (mission.mission_uid, work_package_uid)
                for work_package_uid in sorted(existing - package_uids)
            ),
        )

    @staticmethod
    def _put_mandate_row(
        connection: sqlite3.Connection,
        mandate: MissionMandate,
    ) -> None:
        connection.execute(
            """
            INSERT INTO agentic_mandates (
                mandate_uid, mission_uid, issued_at, value
            ) VALUES (?, ?, ?, ?)
            ON CONFLICT(mandate_uid) DO UPDATE SET
                mission_uid = excluded.mission_uid,
                issued_at = excluded.issued_at,
                value = excluded.value
            """,
            (
                mandate.mandate_uid,
                mandate.mission_uid,
                mandate.issued_at.isoformat(),
                canonical_json(mandate),
            ),
        )

    @staticmethod
    def _put_agent_run_row(connection: sqlite3.Connection, run: AgentRun) -> None:
        connection.execute(
            """
            INSERT INTO agentic_agent_runs (
                agent_run_uid, mission_uid, work_package_uid, state,
                created_at, updated_at, value
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(agent_run_uid) DO UPDATE SET
                mission_uid = excluded.mission_uid,
                work_package_uid = excluded.work_package_uid,
                state = excluded.state,
                created_at = excluded.created_at,
                updated_at = excluded.updated_at,
                value = excluded.value
            """,
            (
                run.agent_run_uid,
                run.mission_uid,
                run.work_package_uid,
                run.state.value,
                run.created_at.isoformat(),
                run.updated_at.isoformat(),
                canonical_json(run),
            ),
        )

    @staticmethod
    def _put_decision_request_row(
        connection: sqlite3.Connection,
        request: DecisionRequest,
    ) -> None:
        encoded = canonical_json(request)
        row = connection.execute(
            "SELECT value FROM agentic_decision_requests "
            "WHERE decision_request_uid = ?",
            (request.decision_request_uid,),
        ).fetchone()
        if row is not None:
            if str(row[0]) != encoded:
                raise ValueError("LESR-DECISION-REQUEST-IMMUTABLE")
            return
        connection.execute(
            """
            INSERT INTO agentic_decision_requests (
                decision_request_uid, mission_uid, work_package_uid,
                mandate_uid, created_at, value
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                request.decision_request_uid,
                request.mission_uid,
                request.work_package_uid,
                request.mandate_uid,
                request.created_at.isoformat(),
                encoded,
            ),
        )

    @staticmethod
    def _record_decision_resolution_row(
        connection: sqlite3.Connection,
        resolution: DecisionResolution,
    ) -> None:
        encoded = canonical_json(resolution)
        row = connection.execute(
            "SELECT value FROM agentic_decision_resolutions "
            "WHERE decision_request_uid = ?",
            (resolution.decision_request_uid,),
        ).fetchone()
        if row is not None:
            if str(row[0]) != encoded:
                raise ValueError("LESR-DECISION-ALREADY-RESOLVED")
            return
        connection.execute(
            """
            INSERT INTO agentic_decision_resolutions (
                resolution_uid, decision_request_uid, resolved_at, value
            ) VALUES (?, ?, ?, ?)
            """,
            (
                resolution.decision_resolution_uid,
                resolution.decision_request_uid,
                resolution.decided_at.isoformat(),
                encoded,
            ),
        )

    @staticmethod
    def _assert_current_mission(
        connection: sqlite3.Connection,
        expected_mission: Mission,
    ) -> None:
        row = connection.execute(
            "SELECT value FROM agentic_missions WHERE mission_uid = ?",
            (expected_mission.mission_uid,),
        ).fetchone()
        if row is None:
            raise KeyError(expected_mission.mission_uid)
        if str(row[0]) != canonical_json(expected_mission):
            raise MissionConcurrencyError("LESR-MISSION-STATE-CHANGED")

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _get_value(self, table: str, key_column: str, key: str) -> dict[str, object]:
        allowed = {
            ("agentic_missions", "mission_uid"),
            ("agentic_mandates", "mandate_uid"),
            ("agentic_agent_runs", "agent_run_uid"),
            ("agentic_decision_requests", "decision_request_uid"),
            ("agentic_decision_resolutions", "resolution_uid"),
        }
        if (table, key_column) not in allowed:
            raise ValueError("invalid MissionStore lookup")
        with self._connect() as connection:
            row = connection.execute(
                f"SELECT value FROM {table} WHERE {key_column} = ?",
                (key,),
            ).fetchone()
        if row is None:
            raise KeyError(key)
        return self._load_value(row[0])

    @staticmethod
    def _load_value(raw: object) -> dict[str, object]:
        value = json.loads(str(raw))
        if not isinstance(value, dict):
            raise TypeError("MissionStore record is not a JSON object")
        return value
