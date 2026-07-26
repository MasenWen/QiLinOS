from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from typing import Any, Iterator

from .contracts import (
    AtomicEvidence,
    BoundaryDecision,
    Completion,
    EvidenceAdmission,
    ExecutionFragment,
    ImpactAction,
    LifecycleStatus,
    MemoryCandidate,
    ReflectionArtifact,
    RepairedExecution,
    SourceType,
    StageOutput,
    StrictObservation,
    StrictConflictGroup,
    StrictImpact,
    StrictForgetRequest,
    StrictLifecycleEvent,
    StrictMemory,
    SuppressionRule,
)
from .errors import IdempotencyConflictError


STRICT_DB_SCHEMA_VERSION = 5


def _json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _load(value: str) -> dict[str, Any]:
    loaded = json.loads(value)
    if not isinstance(loaded, dict):
        raise ValueError("stored strict entity is not a JSON object")
    return loaded


class StrictMemoryEngineStore:
    """Versioned SQLite store owned only by the strict implementation."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.initialize()

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def initialize(self) -> None:
        with self._lock, self.connection() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS strict_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS strict_observations (
                    observation_id TEXT PRIMARY KEY,
                    source_event_id TEXT NOT NULL UNIQUE,
                    content_hash TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    sequence_no INTEGER,
                    event_time TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_strict_observation_session_order
                    ON strict_observations(
                        user_id, session_id, event_time, sequence_no, observation_id
                    );
                CREATE TABLE IF NOT EXISTS strict_fragments (
                    fragment_id TEXT NOT NULL,
                    execution_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    ordinal INTEGER NOT NULL,
                    payload_json TEXT NOT NULL,
                    PRIMARY KEY(execution_id, fragment_id)
                );
                CREATE INDEX IF NOT EXISTS idx_strict_fragment_execution
                    ON strict_fragments(execution_id, ordinal);
                CREATE TABLE IF NOT EXISTS strict_repaired_executions (
                    execution_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    input_fingerprint TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_strict_execution_session
                    ON strict_repaired_executions(user_id, session_id, created_at);
                CREATE TABLE IF NOT EXISTS strict_stage_outputs (
                    output_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    module_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_strict_stage_run
                    ON strict_stage_outputs(run_id, stage);
                CREATE TABLE IF NOT EXISTS strict_evidence (
                    evidence_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    independent_unit_id TEXT NOT NULL,
                    claim_slot TEXT NOT NULL,
                    admission TEXT NOT NULL,
                    status TEXT NOT NULL,
                    observed_time TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_strict_evidence_lineage
                    ON strict_evidence(user_id, independent_unit_id, status);
                CREATE INDEX IF NOT EXISTS idx_strict_evidence_slot
                    ON strict_evidence(user_id, claim_slot, admission, status);
                CREATE TABLE IF NOT EXISTS strict_candidates (
                    candidate_id TEXT PRIMARY KEY,
                    evidence_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    independent_unit_id TEXT NOT NULL,
                    slot_key TEXT NOT NULL,
                    source_module_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_strict_candidate_slot
                    ON strict_candidates(user_id, slot_key, status);
                CREATE TABLE IF NOT EXISTS strict_impacts (
                    impact_id TEXT PRIMARY KEY,
                    candidate_id TEXT NOT NULL,
                    evidence_id TEXT NOT NULL,
                    target_memory_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_strict_impact_memory
                    ON strict_impacts(target_memory_id, created_at);
                CREATE TABLE IF NOT EXISTS strict_memories (
                    memory_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    slot_key TEXT NOT NULL,
                    semantic_value TEXT NOT NULL,
                    status TEXT NOT NULL,
                    valid_from TEXT NOT NULL,
                    valid_to TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_strict_memory_slot
                    ON strict_memories(user_id, slot_key, status);
                CREATE TABLE IF NOT EXISTS strict_conflict_groups (
                    conflict_group_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    slot_key TEXT NOT NULL,
                    conflict_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_strict_conflict_slot
                    ON strict_conflict_groups(user_id, slot_key, status);
                CREATE TABLE IF NOT EXISTS strict_lifecycle_events (
                    event_id TEXT PRIMARY KEY,
                    memory_id TEXT NOT NULL,
                    from_status TEXT NOT NULL,
                    to_status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS strict_forget_requests (
                    request_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS strict_suppressions (
                    suppression_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    slot_key TEXT NOT NULL,
                    semantic_value TEXT NOT NULL,
                    active INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_strict_suppression_match
                    ON strict_suppressions(
                        user_id, slot_key, semantic_value, active
                    );
                CREATE TABLE IF NOT EXISTS strict_reflections (
                    reflection_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    reflection_type TEXT NOT NULL,
                    grounding_verified INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS strict_engine_runs (
                    run_id TEXT PRIMARY KEY,
                    operation TEXT NOT NULL,
                    stage_limit TEXT NOT NULL,
                    module_versions_json TEXT NOT NULL,
                    input_ids_json TEXT NOT NULL,
                    output_ids_json TEXT NOT NULL,
                    trace_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    latency_ms REAL NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )
            row = connection.execute(
                "SELECT value FROM strict_meta WHERE key = 'schema_version'"
            ).fetchone()
            if row and int(row["value"]) > STRICT_DB_SCHEMA_VERSION:
                raise RuntimeError(
                    "strict database schema is newer than this implementation"
                )
            if row and int(row["value"]) == 1:
                self._migrate_v1_to_v2(connection)
            connection.execute(
                """
                INSERT INTO strict_meta(key, value) VALUES('schema_version', ?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value
                """,
                (str(STRICT_DB_SCHEMA_VERSION),),
            )

    @staticmethod
    def _migrate_v1_to_v2(connection: sqlite3.Connection) -> None:
        connection.executescript(
            """
            ALTER TABLE strict_fragments RENAME TO strict_fragments_v1;
            CREATE TABLE strict_fragments (
                fragment_id TEXT NOT NULL,
                execution_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                session_id TEXT NOT NULL,
                ordinal INTEGER NOT NULL,
                payload_json TEXT NOT NULL,
                PRIMARY KEY(execution_id, fragment_id)
            );
            INSERT INTO strict_fragments(
                fragment_id, execution_id, user_id, session_id,
                ordinal, payload_json
            )
            SELECT fragment_id, execution_id, user_id, session_id,
                   ordinal, payload_json
            FROM strict_fragments_v1;
            DROP TABLE strict_fragments_v1;
            CREATE INDEX IF NOT EXISTS idx_strict_fragment_execution
                ON strict_fragments(execution_id, ordinal);
            """
        )

    def put_observation(self, observation: StrictObservation) -> bool:
        with self._lock, self.connection() as connection:
            existing = connection.execute(
                """
                SELECT observation_id, content_hash
                FROM strict_observations WHERE source_event_id = ?
                """,
                (observation.source_event_id,),
            ).fetchone()
            if existing:
                if existing["content_hash"] != observation.content_hash:
                    raise IdempotencyConflictError(
                        "source_event_id replayed with different semantic content: "
                        f"{observation.source_event_id}"
                    )
                return False
            connection.execute(
                """
                INSERT INTO strict_observations(
                    observation_id, source_event_id, content_hash, user_id,
                    session_id, sequence_no, event_time, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    observation.observation_id,
                    observation.source_event_id,
                    observation.content_hash,
                    observation.user_id,
                    observation.session_id,
                    observation.sequence_no,
                    observation.event_time,
                    _json(observation.to_dict()),
                ),
            )
            return True

    def get_observation_by_source_event(
        self,
        source_event_id: str,
    ) -> StrictObservation | None:
        with self.connection() as connection:
            row = connection.execute(
                """
                SELECT payload_json FROM strict_observations
                WHERE source_event_id = ?
                """,
                (source_event_id,),
            ).fetchone()
        return _observation(_load(row["payload_json"])) if row else None

    def list_observations(
        self,
        user_id: str,
        session_id: str,
    ) -> list[StrictObservation]:
        with self.connection() as connection:
            rows = connection.execute(
                """
                SELECT payload_json FROM strict_observations
                WHERE user_id = ? AND session_id = ?
                ORDER BY event_time,
                         CASE WHEN sequence_no IS NULL THEN 1 ELSE 0 END,
                         sequence_no,
                         observation_id
                """,
                (user_id, session_id),
            ).fetchall()
        return [_observation(_load(row["payload_json"])) for row in rows]

    def get_observations(
        self,
        observation_ids: tuple[str, ...],
    ) -> list[StrictObservation]:
        if not observation_ids:
            return []
        placeholders = ",".join("?" for _ in observation_ids)
        with self.connection() as connection:
            rows = connection.execute(
                f"""
                SELECT observation_id, payload_json FROM strict_observations
                WHERE observation_id IN ({placeholders})
                """,
                observation_ids,
            ).fetchall()
        by_id = {
            row["observation_id"]: _observation(_load(row["payload_json"]))
            for row in rows
        }
        return [
            by_id[observation_id]
            for observation_id in observation_ids
            if observation_id in by_id
        ]

    def replace_execution(
        self,
        execution: RepairedExecution,
        fragments: list[ExecutionFragment],
        *,
        input_fingerprint: str,
        created_at: str,
    ) -> None:
        with self._lock, self.connection() as connection:
            connection.execute(
                """
                INSERT INTO strict_repaired_executions(
                    execution_id, user_id, session_id, input_fingerprint,
                    payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(execution_id) DO UPDATE SET
                    input_fingerprint=excluded.input_fingerprint,
                    payload_json=excluded.payload_json,
                    created_at=excluded.created_at
                """,
                (
                    execution.execution_id,
                    execution.user_id,
                    execution.session_id,
                    input_fingerprint,
                    _json(execution.to_dict()),
                    created_at,
                ),
            )
            connection.execute(
                "DELETE FROM strict_fragments WHERE execution_id = ?",
                (execution.execution_id,),
            )
            connection.executemany(
                """
                INSERT INTO strict_fragments(
                    fragment_id, execution_id, user_id, session_id,
                    ordinal, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        fragment.fragment_id,
                        execution.execution_id,
                        fragment.user_id,
                        fragment.session_id,
                        ordinal,
                        _json(fragment.to_dict()),
                    )
                    for ordinal, fragment in enumerate(fragments)
                ],
            )

    def get_execution(
        self,
        user_id: str,
        session_id: str,
    ) -> tuple[RepairedExecution, list[ExecutionFragment]] | None:
        with self.connection() as connection:
            row = connection.execute(
                """
                SELECT execution_id, payload_json
                FROM strict_repaired_executions
                WHERE user_id = ? AND session_id = ?
                ORDER BY created_at DESC LIMIT 1
                """,
                (user_id, session_id),
            ).fetchone()
            if row is None:
                return None
            fragment_rows = connection.execute(
                """
                SELECT payload_json FROM strict_fragments
                WHERE execution_id = ? ORDER BY ordinal
                """,
                (row["execution_id"],),
            ).fetchall()
        return (
            _execution(_load(row["payload_json"])),
            [_fragment(_load(item["payload_json"])) for item in fragment_rows],
        )

    def put_stage_output(self, output: StageOutput) -> None:
        with self._lock, self.connection() as connection:
            connection.execute(
                """
                INSERT INTO strict_stage_outputs(
                    output_id, run_id, stage, module_id, payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    output.output_id,
                    output.run_id,
                    output.stage,
                    output.module_id,
                    _json(output.to_dict()),
                    output.created_at,
                ),
            )

    def list_stage_outputs(
        self,
        run_id: str,
    ) -> list[StageOutput]:
        with self.connection() as connection:
            rows = connection.execute(
                """
                SELECT payload_json FROM strict_stage_outputs
                WHERE run_id = ? ORDER BY rowid
                """,
                (run_id,),
            ).fetchall()
        return [
            _stage_output_record(_load(row["payload_json"]))
            for row in rows
        ]

    def put_evidence(self, evidence: AtomicEvidence) -> bool:
        with self._lock, self.connection() as connection:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO strict_evidence(
                    evidence_id, user_id, independent_unit_id, claim_slot,
                    admission, status, observed_time, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    evidence.evidence_id,
                    evidence.user_id,
                    evidence.independent_unit_id,
                    evidence.claim_slot,
                    evidence.admission.value,
                    evidence.status,
                    evidence.observed_time,
                    _json(evidence.to_dict()),
                ),
            )
            return cursor.rowcount > 0

    def set_evidence_status(
        self,
        evidence_id: str,
        status: str,
    ) -> AtomicEvidence | None:
        with self._lock, self.connection() as connection:
            row = connection.execute(
                "SELECT payload_json FROM strict_evidence WHERE evidence_id = ?",
                (evidence_id,),
            ).fetchone()
            if row is None:
                return None
            evidence = _evidence(_load(row["payload_json"]))
            from dataclasses import replace

            updated = replace(evidence, status=status)
            connection.execute(
                """
                UPDATE strict_evidence
                SET status = ?, payload_json = ?
                WHERE evidence_id = ?
                """,
                (status, _json(updated.to_dict()), evidence_id),
            )
            return updated

    def list_evidence(
        self,
        user_id: str,
        *,
        independent_unit_id: str | None = None,
    ) -> list[AtomicEvidence]:
        sql = "SELECT payload_json FROM strict_evidence WHERE user_id = ?"
        params: list[str] = [user_id]
        if independent_unit_id:
            sql += " AND independent_unit_id = ?"
            params.append(independent_unit_id)
        sql += " ORDER BY observed_time, evidence_id"
        with self.connection() as connection:
            rows = connection.execute(sql, params).fetchall()
        return [_evidence(_load(row["payload_json"])) for row in rows]

    def put_candidate(self, candidate: MemoryCandidate) -> bool:
        with self._lock, self.connection() as connection:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO strict_candidates(
                    candidate_id, evidence_id, user_id, independent_unit_id,
                    slot_key, source_module_id, status, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    candidate.candidate_id,
                    candidate.evidence_id,
                    candidate.user_id,
                    candidate.independent_unit_id,
                    candidate.slot_key,
                    candidate.source_module_id,
                    candidate.status,
                    _json(candidate.to_dict()),
                ),
            )
            return cursor.rowcount > 0

    def list_candidates(
        self,
        user_id: str,
        *,
        status: str | None = None,
    ) -> list[MemoryCandidate]:
        sql = "SELECT payload_json FROM strict_candidates WHERE user_id = ?"
        params: list[str] = [user_id]
        if status:
            sql += " AND status = ?"
            params.append(status)
        sql += " ORDER BY candidate_id"
        with self.connection() as connection:
            rows = connection.execute(sql, params).fetchall()
        return [_candidate(_load(row["payload_json"])) for row in rows]

    def list_unapplied_candidates(
        self,
        user_id: str,
    ) -> list[MemoryCandidate]:
        with self.connection() as connection:
            rows = connection.execute(
                """
                SELECT candidate.payload_json
                FROM strict_candidates AS candidate
                LEFT JOIN strict_impacts AS impact
                  ON impact.candidate_id = candidate.candidate_id
                WHERE candidate.user_id = ?
                  AND candidate.status = 'pending'
                  AND impact.candidate_id IS NULL
                ORDER BY candidate.candidate_id
                """,
                (user_id,),
            ).fetchall()
        return [_candidate(_load(row["payload_json"])) for row in rows]

    def set_candidate_status(
        self,
        candidate_id: str,
        status: str,
    ) -> MemoryCandidate | None:
        with self._lock, self.connection() as connection:
            row = connection.execute(
                """
                SELECT payload_json FROM strict_candidates
                WHERE candidate_id = ?
                """,
                (candidate_id,),
            ).fetchone()
            if row is None:
                return None
            candidate = _candidate(_load(row["payload_json"]))
            from dataclasses import replace

            updated = replace(candidate, status=status)
            connection.execute(
                """
                UPDATE strict_candidates
                SET status = ?, payload_json = ?
                WHERE candidate_id = ?
                """,
                (status, _json(updated.to_dict()), candidate_id),
            )
            return updated

    def put_impact(self, impact: StrictImpact) -> bool:
        with self._lock, self.connection() as connection:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO strict_impacts(
                    impact_id, candidate_id, evidence_id, target_memory_id,
                    action, created_at, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    impact.impact_id,
                    impact.candidate_id,
                    impact.evidence_id,
                    impact.target_memory_id,
                    impact.action.value,
                    impact.created_at,
                    _json(impact.to_dict()),
                ),
            )
            return cursor.rowcount > 0

    def list_impacts(self, target_memory_id: str | None = None) -> list[StrictImpact]:
        sql = "SELECT payload_json FROM strict_impacts"
        params: list[str] = []
        if target_memory_id:
            sql += " WHERE target_memory_id = ?"
            params.append(target_memory_id)
        sql += " ORDER BY created_at, impact_id"
        with self.connection() as connection:
            rows = connection.execute(sql, params).fetchall()
        return [_impact(_load(row["payload_json"])) for row in rows]

    def put_memory(self, memory: StrictMemory) -> None:
        with self._lock, self.connection() as connection:
            connection.execute(
                """
                INSERT INTO strict_memories(
                    memory_id, user_id, slot_key, semantic_value, status,
                    valid_from, valid_to, updated_at, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(memory_id) DO UPDATE SET
                    status=excluded.status,
                    valid_from=excluded.valid_from,
                    valid_to=excluded.valid_to,
                    updated_at=excluded.updated_at,
                    payload_json=excluded.payload_json
                """,
                (
                    memory.memory_id,
                    memory.user_id,
                    memory.slot_key,
                    memory.semantic_value,
                    memory.status.value,
                    memory.valid_from,
                    memory.valid_to,
                    memory.updated_at,
                    _json(memory.to_dict()),
                ),
            )

    def get_memory(self, memory_id: str) -> StrictMemory | None:
        with self.connection() as connection:
            row = connection.execute(
                "SELECT payload_json FROM strict_memories WHERE memory_id = ?",
                (memory_id,),
            ).fetchone()
        return _memory(_load(row["payload_json"])) if row else None

    def list_memories(
        self,
        user_id: str,
        *,
        slot_key: str | None = None,
        include_inactive: bool = True,
    ) -> list[StrictMemory]:
        sql = "SELECT payload_json FROM strict_memories WHERE user_id = ?"
        params: list[str] = [user_id]
        if slot_key:
            sql += " AND slot_key = ?"
            params.append(slot_key)
        if not include_inactive:
            sql += " AND status NOT IN ('archive','blocked','deleted')"
        sql += " ORDER BY updated_at, memory_id"
        with self.connection() as connection:
            rows = connection.execute(sql, params).fetchall()
        return [_memory(_load(row["payload_json"])) for row in rows]

    def put_conflict_group(self, group: StrictConflictGroup) -> None:
        with self._lock, self.connection() as connection:
            connection.execute(
                """
                INSERT INTO strict_conflict_groups(
                    conflict_group_id, user_id, slot_key, conflict_type,
                    status, updated_at, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(conflict_group_id) DO UPDATE SET
                    conflict_type=excluded.conflict_type,
                    status=excluded.status,
                    updated_at=excluded.updated_at,
                    payload_json=excluded.payload_json
                """,
                (
                    group.conflict_group_id,
                    group.user_id,
                    group.slot_key,
                    group.conflict_type.value,
                    group.status,
                    group.updated_at,
                    _json(group.to_dict()),
                ),
            )

    def list_conflict_groups(
        self,
        user_id: str,
        *,
        slot_key: str | None = None,
        include_obsolete: bool = False,
    ) -> list[StrictConflictGroup]:
        sql = "SELECT payload_json FROM strict_conflict_groups WHERE user_id = ?"
        params: list[str] = [user_id]
        if slot_key:
            sql += " AND slot_key = ?"
            params.append(slot_key)
        if not include_obsolete:
            sql += " AND status != 'obsolete'"
        sql += " ORDER BY updated_at, conflict_group_id"
        with self.connection() as connection:
            rows = connection.execute(sql, params).fetchall()
        return [_conflict_group(_load(row["payload_json"])) for row in rows]

    def retire_conflict_groups(
        self,
        user_id: str,
        active_group_ids: set[str],
        *,
        updated_at: str,
    ) -> list[str]:
        retired: list[str] = []
        with self._lock, self.connection() as connection:
            rows = connection.execute(
                """
                SELECT conflict_group_id, payload_json
                FROM strict_conflict_groups
                WHERE user_id = ? AND status != 'obsolete'
                """,
                (user_id,),
            ).fetchall()
            for row in rows:
                group_id = row["conflict_group_id"]
                if group_id in active_group_ids:
                    continue
                group = _conflict_group(_load(row["payload_json"]))
                obsolete = replace(
                    group,
                    status="obsolete",
                    updated_at=updated_at,
                )
                connection.execute(
                    """
                    UPDATE strict_conflict_groups
                    SET status = 'obsolete', updated_at = ?, payload_json = ?
                    WHERE conflict_group_id = ?
                    """,
                    (
                        updated_at,
                        _json(obsolete.to_dict()),
                        group_id,
                    ),
                )
                retired.append(group_id)
        return retired

    def put_lifecycle_event(self, event: StrictLifecycleEvent) -> None:
        with self._lock, self.connection() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO strict_lifecycle_events(
                    event_id, memory_id, from_status, to_status,
                    created_at, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    event.event_id,
                    event.memory_id,
                    event.from_status.value,
                    event.to_status.value,
                    event.created_at,
                    _json(event.to_dict()),
                ),
            )

    def list_lifecycle_events(
        self,
        memory_id: str | None = None,
    ) -> list[StrictLifecycleEvent]:
        sql = "SELECT payload_json FROM strict_lifecycle_events"
        params: list[str] = []
        if memory_id:
            sql += " WHERE memory_id = ?"
            params.append(memory_id)
        sql += " ORDER BY created_at, event_id"
        with self.connection() as connection:
            rows = connection.execute(sql, params).fetchall()
        return [
            _lifecycle_event(_load(row["payload_json"]))
            for row in rows
        ]

    def put_forget_request(self, request: StrictForgetRequest) -> None:
        with self._lock, self.connection() as connection:
            connection.execute(
                """
                INSERT INTO strict_forget_requests(
                    request_id, user_id, status, created_at, payload_json
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(request_id) DO UPDATE SET
                    status=excluded.status,
                    payload_json=excluded.payload_json
                """,
                (
                    request.request_id,
                    request.user_id,
                    request.status,
                    request.created_at,
                    _json(request.to_dict()),
                ),
            )

    def put_suppression(self, rule: SuppressionRule) -> None:
        with self._lock, self.connection() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO strict_suppressions(
                    suppression_id, user_id, slot_key, semantic_value,
                    active, created_at, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    rule.suppression_id,
                    rule.user_id,
                    rule.slot_key,
                    rule.semantic_value,
                    int(rule.active),
                    rule.created_at,
                    _json(rule.to_dict()),
                ),
            )

    def list_suppressions(
        self,
        user_id: str,
        *,
        active_only: bool = True,
    ) -> list[SuppressionRule]:
        sql = "SELECT payload_json FROM strict_suppressions WHERE user_id = ?"
        params: list[object] = [user_id]
        if active_only:
            sql += " AND active = 1"
        sql += " ORDER BY created_at, suppression_id"
        with self.connection() as connection:
            rows = connection.execute(sql, params).fetchall()
        return [_suppression(_load(row["payload_json"])) for row in rows]

    def evidence_is_suppressed(self, evidence: AtomicEvidence) -> bool:
        with self.connection() as connection:
            row = connection.execute(
                """
                SELECT 1 FROM strict_suppressions
                WHERE user_id = ? AND slot_key = ? AND semantic_value = ?
                  AND active = 1
                LIMIT 1
                """,
                (
                    evidence.user_id,
                    evidence.claim_slot,
                    evidence.claim_value,
                ),
            ).fetchone()
        return row is not None

    def put_reflection(self, reflection: ReflectionArtifact) -> None:
        with self._lock, self.connection() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO strict_reflections(
                    reflection_id, user_id, reflection_type,
                    grounding_verified, created_at, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    reflection.reflection_id,
                    reflection.user_id,
                    reflection.reflection_type,
                    int(reflection.grounding_verified),
                    reflection.created_at,
                    _json(reflection.to_dict()),
                ),
            )

    def list_reflections(self, user_id: str) -> list[ReflectionArtifact]:
        with self.connection() as connection:
            rows = connection.execute(
                """
                SELECT payload_json FROM strict_reflections
                WHERE user_id = ? ORDER BY created_at, reflection_id
                """,
                (user_id,),
            ).fetchall()
        return [_reflection(_load(row["payload_json"])) for row in rows]

    def put_engine_run(self, run: dict[str, Any]) -> None:
        with self._lock, self.connection() as connection:
            connection.execute(
                """
                INSERT INTO strict_engine_runs(
                    run_id, operation, stage_limit, module_versions_json,
                    input_ids_json, output_ids_json, trace_json, status,
                    latency_ms, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run["run_id"],
                    run["operation"],
                    run["stage_limit"],
                    _json(run["module_versions"]),
                    _json(run["input_ids"]),
                    _json(run["output_ids"]),
                    _json(run["trace"]),
                    run["status"],
                    float(run["latency_ms"]),
                    run["created_at"],
                ),
            )

    def counts(self) -> dict[str, int]:
        tables = (
            "strict_observations",
            "strict_fragments",
            "strict_repaired_executions",
            "strict_evidence",
            "strict_candidates",
            "strict_impacts",
            "strict_memories",
            "strict_conflict_groups",
            "strict_lifecycle_events",
            "strict_forget_requests",
            "strict_suppressions",
            "strict_reflections",
            "strict_stage_outputs",
            "strict_engine_runs",
        )
        with self.connection() as connection:
            return {
                table: int(
                    connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                )
                for table in tables
            }


def _observation(data: dict[str, Any]) -> StrictObservation:
    return StrictObservation(
        **{
            **data,
            "source_type": SourceType(data["source_type"]),
            "completion": Completion(data["completion"]),
            "artifact_refs": tuple(data.get("artifact_refs") or ()),
            "entity_refs": tuple(data.get("entity_refs") or ()),
            "input_refs": tuple(data.get("input_refs") or ()),
            "output_refs": tuple(data.get("output_refs") or ()),
        }
    )


def _boundary(data: dict[str, Any] | None) -> BoundaryDecision | None:
    if data is None:
        return None
    return BoundaryDecision(
        should_split=bool(data["should_split"]),
        score=float(data["score"]),
        reason_codes=tuple(data.get("reason_codes") or ()),
        features=dict(data.get("features") or {}),
        forced=bool(data.get("forced")),
        schema_version=str(data.get("schema_version") or "strict.boundary_decision.v1"),
    )


def _fragment(data: dict[str, Any]) -> ExecutionFragment:
    return ExecutionFragment(
        **{
            **data,
            "observation_ids": tuple(data["observation_ids"]),
            "actions": tuple(data.get("actions") or ()),
            "artifact_refs": tuple(data.get("artifact_refs") or ()),
            "entity_refs": tuple(data.get("entity_refs") or ()),
            "apps": tuple(data.get("apps") or ()),
            "completion": Completion(data["completion"]),
            "source_episode_ids": tuple(data.get("source_episode_ids") or ()),
            "boundary_before": _boundary(data.get("boundary_before")),
        }
    )


def _execution(data: dict[str, Any]) -> RepairedExecution:
    return RepairedExecution(
        **{
            **data,
            "fragment_ids": tuple(data["fragment_ids"]),
            "observation_ids": tuple(data["observation_ids"]),
            "repair_trace": tuple(data.get("repair_trace") or ()),
        }
    )


def _evidence(data: dict[str, Any]) -> AtomicEvidence:
    return AtomicEvidence(
        **{
            **data,
            "source_observation_ids": tuple(data["source_observation_ids"]),
            "source_fragment_ids": tuple(data["source_fragment_ids"]),
            "admission": EvidenceAdmission(data["admission"]),
            "admission_reasons": tuple(data.get("admission_reasons") or ()),
        }
    )


def _candidate(data: dict[str, Any]) -> MemoryCandidate:
    return MemoryCandidate(
        **{
            **data,
            "source_observation_ids": tuple(data["source_observation_ids"]),
            "source_fragment_ids": tuple(data["source_fragment_ids"]),
        }
    )


def _impact(data: dict[str, Any]) -> StrictImpact:
    return StrictImpact(
        **{
            **data,
            "action": ImpactAction(data["action"]),
        }
    )


def _memory(data: dict[str, Any]) -> StrictMemory:
    return StrictMemory(
        **{
            **data,
            "status": LifecycleStatus(data["status"]),
            "evidence_ids": tuple(data["evidence_ids"]),
            "support_unit_ids": tuple(data["support_unit_ids"]),
            "oppose_unit_ids": tuple(data["oppose_unit_ids"]),
            "applicable_unit_ids": tuple(data["applicable_unit_ids"]),
            "predecessor_memory_ids": tuple(data["predecessor_memory_ids"]),
            "successor_memory_ids": tuple(data["successor_memory_ids"]),
            "conflict_group_ids": tuple(data["conflict_group_ids"]),
        }
    )


def _conflict_group(data: dict[str, Any]) -> StrictConflictGroup:
    from .contracts import ConflictType

    return StrictConflictGroup(
        **{
            **data,
            "conflict_type": ConflictType(data["conflict_type"]),
            "memory_ids": tuple(data["memory_ids"]),
            "timeline": tuple(data.get("timeline") or ()),
        }
    )


def _lifecycle_event(data: dict[str, Any]) -> StrictLifecycleEvent:
    return StrictLifecycleEvent(
        **{
            **data,
            "from_status": LifecycleStatus(data["from_status"]),
            "to_status": LifecycleStatus(data["to_status"]),
        }
    )


def _suppression(data: dict[str, Any]) -> SuppressionRule:
    return SuppressionRule(
        **{
            **data,
            "source_observation_ids": tuple(data["source_observation_ids"]),
        }
    )


def _reflection(data: dict[str, Any]) -> ReflectionArtifact:
    return ReflectionArtifact(
        **{
            **data,
            "memory_ids": tuple(data["memory_ids"]),
            "evidence_ids": tuple(data["evidence_ids"]),
            "grounding_errors": tuple(data["grounding_errors"]),
        }
    )


def _stage_output_record(data: dict[str, Any]) -> StageOutput:
    return StageOutput(
        **{
            **data,
            "input_ids": tuple(data["input_ids"]),
            "output_ids": tuple(data["output_ids"]),
        }
    )
