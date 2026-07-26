from __future__ import annotations

import json
import os
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .models import Episode, Evidence, MemoryRecord, Observation


SCHEMA_VERSION = "memory_engine.sqlite.v1"


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _loads(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return default


class MemoryEngineStore:
    """SQLite lineage sidecar. Mem0 remains the vector index in phase 1/2."""

    def __init__(self, path: str | os.PathLike[str] | None = None):
        configured = path or os.getenv("NEX_MEMORY_ENGINE_DB")
        self.path = Path(configured or os.path.expanduser("~/.nex-agent/memory_engine.db"))
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
        schema = """
        CREATE TABLE IF NOT EXISTS engine_meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS observations (
            observation_id TEXT PRIMARY KEY,
            source_event_id TEXT NOT NULL UNIQUE,
            user_id TEXT NOT NULL,
            session_id TEXT NOT NULL,
            event_time TEXT NOT NULL,
            ingest_time TEXT NOT NULL,
            source_type TEXT NOT NULL,
            actor TEXT NOT NULL,
            content TEXT NOT NULL,
            payload_json TEXT NOT NULL DEFAULT '{}',
            task_hint TEXT NOT NULL,
            goal_hint TEXT NOT NULL,
            context_json TEXT NOT NULL,
            source_reliability REAL NOT NULL,
            privacy_json TEXT NOT NULL,
            schema_version TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_observations_user_time
            ON observations(user_id, event_time);
        CREATE TABLE IF NOT EXISTS episodes (
            episode_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            session_id TEXT NOT NULL,
            observation_ids_json TEXT NOT NULL,
            start_time TEXT NOT NULL,
            end_time TEXT,
            state_json TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS evidence (
            evidence_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            status TEXT NOT NULL,
            evidence_type TEXT NOT NULL,
            memory_family TEXT NOT NULL,
            memory_type TEXT NOT NULL,
            memory_category TEXT NOT NULL,
            claim_subject TEXT NOT NULL,
            claim_slot TEXT NOT NULL,
            claim_value TEXT NOT NULL,
            claim_polarity TEXT NOT NULL,
            condition_json TEXT NOT NULL,
            observed_time TEXT NOT NULL,
            source_observation_ids_json TEXT NOT NULL,
            source_episode_ids_json TEXT NOT NULL DEFAULT '[]',
            independent_unit_id TEXT NOT NULL,
            valid_from TEXT NOT NULL DEFAULT '',
            valid_to TEXT NOT NULL DEFAULT '',
            impact_ids_json TEXT NOT NULL DEFAULT '[]',
            directness TEXT NOT NULL,
            source_reliability REAL NOT NULL,
            extraction_confidence REAL NOT NULL,
            statistics_json TEXT NOT NULL,
            extractor_json TEXT NOT NULL,
            privacy_json TEXT NOT NULL,
            schema_version TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_evidence_user_slot
            ON evidence(user_id, claim_slot, status);
        CREATE TABLE IF NOT EXISTS memories (
            memory_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            memory_family TEXT NOT NULL,
            memory_type TEXT NOT NULL,
            memory_category TEXT NOT NULL,
            status TEXT NOT NULL,
            slot_key TEXT NOT NULL,
            semantic_value TEXT NOT NULL,
            condition_json TEXT NOT NULL,
            scope_json TEXT NOT NULL,
            evidence_ids_json TEXT NOT NULL,
            statistics_json TEXT NOT NULL,
            confidence_json TEXT NOT NULL,
            stability_json TEXT NOT NULL,
            provenance_json TEXT NOT NULL,
            version INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            schema_version TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_memories_retrieval
            ON memories(user_id, status, memory_type, memory_category);
        CREATE INDEX IF NOT EXISTS idx_memories_slot
            ON memories(user_id, slot_key);
        CREATE TABLE IF NOT EXISTS impacts (
            impact_id TEXT PRIMARY KEY,
            evidence_id TEXT NOT NULL,
            target_memory_id TEXT NOT NULL,
            action TEXT NOT NULL,
            reason_code TEXT NOT NULL,
            before_snapshot_json TEXT NOT NULL,
            after_snapshot_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS conflict_groups (
            conflict_group_id TEXT PRIMARY KEY,
            slot_key TEXT NOT NULL,
            state_json TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS lifecycle_events (
            event_id TEXT PRIMARY KEY,
            memory_id TEXT NOT NULL,
            from_status TEXT,
            to_status TEXT NOT NULL,
            reason_code TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS forget_requests (
            request_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            request_json TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            completed_at TEXT
        );
        CREATE TABLE IF NOT EXISTS index_refs (
            memory_id TEXT NOT NULL,
            backend TEXT NOT NULL,
            backend_id TEXT NOT NULL,
            tier TEXT NOT NULL,
            state TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY(memory_id, backend, backend_id)
        );
        CREATE TABLE IF NOT EXISTS engine_runs (
            run_id TEXT PRIMARY KEY,
            operation TEXT NOT NULL,
            module_versions_json TEXT NOT NULL,
            input_ids_json TEXT NOT NULL,
            output_ids_json TEXT NOT NULL,
            trace_json TEXT NOT NULL,
            status TEXT NOT NULL,
            latency_ms REAL NOT NULL,
            created_at TEXT NOT NULL
        );
        """
        with self._lock, self.connection() as connection:
            connection.executescript(schema)
            columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(observations)").fetchall()
            }
            if "payload_json" not in columns:
                connection.execute(
                    "ALTER TABLE observations "
                    "ADD COLUMN payload_json TEXT NOT NULL DEFAULT '{}'"
                )
            evidence_columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(evidence)").fetchall()
            }
            evidence_migrations = {
                "source_episode_ids_json": "TEXT NOT NULL DEFAULT '[]'",
                "valid_from": "TEXT NOT NULL DEFAULT ''",
                "valid_to": "TEXT NOT NULL DEFAULT ''",
                "impact_ids_json": "TEXT NOT NULL DEFAULT '[]'",
            }
            for name, definition in evidence_migrations.items():
                if name not in evidence_columns:
                    connection.execute(
                        f"ALTER TABLE evidence ADD COLUMN {name} {definition}"
                    )
            connection.execute(
                "INSERT OR REPLACE INTO engine_meta(key, value) VALUES('schema_version', ?)",
                (SCHEMA_VERSION,),
            )

    def put_observation(self, observation: Observation) -> bool:
        data = observation.to_dict()
        with self._lock, self.connection() as connection:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO observations (
                    observation_id, source_event_id, user_id, session_id,
                    event_time, ingest_time, source_type, actor, content,
                    payload_json, task_hint, goal_hint, context_json,
                    source_reliability, privacy_json, schema_version
                ) VALUES (
                    :observation_id, :source_event_id, :user_id, :session_id,
                    :event_time, :ingest_time, :source_type, :actor, :content,
                    :payload_json, :task_hint, :goal_hint, :context_json,
                    :source_reliability, :privacy_json, :schema_version
                )
                """,
                {
                    **data,
                    "payload_json": _json(
                        {
                            "sequence_no": data["sequence_no"],
                            "app": data["app"],
                            "tool": data["tool"],
                            "action": data["action"],
                            "artifact_refs": data["artifact_refs"],
                            "entity_refs": data["entity_refs"],
                            "available_tools": data["available_tools"],
                            "input_refs": data["input_refs"],
                            "output_refs": data["output_refs"],
                            "state": data["state"],
                            "result": data["result"],
                            "raw_source_ref": data["raw_source_ref"],
                            "completeness": data["completeness"],
                        }
                    ),
                    "context_json": _json(data["context"]),
                    "privacy_json": _json(data["privacy"]),
                },
            )
            return cursor.rowcount > 0

    def get_observation(self, observation_id: str) -> Observation | None:
        with self.connection() as connection:
            row = connection.execute(
                "SELECT * FROM observations WHERE observation_id = ?",
                (observation_id,),
            ).fetchone()
        return self._observation_from_row(row) if row else None

    def list_observations(
        self,
        user_id: str,
        *,
        session_id: str | None = None,
    ) -> list[Observation]:
        sql = "SELECT * FROM observations WHERE user_id = ?"
        params: list[str] = [user_id]
        if session_id:
            sql += " AND session_id = ?"
            params.append(session_id)
        sql += " ORDER BY event_time, ingest_time, observation_id"
        with self.connection() as connection:
            rows = connection.execute(sql, params).fetchall()
        return [self._observation_from_row(row) for row in rows]

    def put_episode(self, episode: Episode) -> None:
        data = episode.to_dict()
        state = {
            key: value
            for key, value in data.items()
            if key
            not in {
                "episode_id",
                "user_id",
                "session_id",
                "observation_ids",
                "start_time",
                "end_time",
            }
        }
        with self._lock, self.connection() as connection:
            connection.execute(
                """
                INSERT INTO episodes(
                    episode_id, user_id, session_id, observation_ids_json,
                    start_time, end_time, state_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(episode_id) DO UPDATE SET
                    observation_ids_json=excluded.observation_ids_json,
                    end_time=excluded.end_time,
                    state_json=excluded.state_json
                """,
                (
                    episode.episode_id,
                    episode.user_id,
                    episode.session_id,
                    _json(episode.observation_ids),
                    episode.start_time,
                    episode.end_time,
                    _json(state),
                ),
            )

    def get_episode(self, episode_id: str) -> Episode | None:
        with self.connection() as connection:
            row = connection.execute(
                "SELECT * FROM episodes WHERE episode_id = ?",
                (episode_id,),
            ).fetchone()
        return self._episode_from_row(row) if row else None

    def list_episodes(
        self,
        user_id: str,
        *,
        session_id: str | None = None,
    ) -> list[Episode]:
        sql = "SELECT * FROM episodes WHERE user_id = ?"
        params: list[str] = [user_id]
        if session_id:
            sql += " AND session_id = ?"
            params.append(session_id)
        sql += " ORDER BY start_time, episode_id"
        with self.connection() as connection:
            rows = connection.execute(sql, params).fetchall()
        return [self._episode_from_row(row) for row in rows]

    def latest_open_episode(self, user_id: str, session_id: str) -> Episode | None:
        episodes = self.list_episodes(user_id, session_id=session_id)
        for episode in reversed(episodes):
            if episode.status == "open":
                return episode
        return None

    def find_episode_for_observation(self, observation_id: str) -> Episode | None:
        with self.connection() as connection:
            rows = connection.execute(
                "SELECT * FROM episodes ORDER BY start_time DESC"
            ).fetchall()
        for row in rows:
            episode = self._episode_from_row(row)
            if observation_id in episode.observation_ids:
                return episode
        return None

    def put_evidence(self, evidence: Evidence) -> bool:
        data = evidence.to_dict()
        with self._lock, self.connection() as connection:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO evidence (
                    evidence_id, user_id, status, evidence_type,
                    memory_family, memory_type, memory_category,
                    claim_subject, claim_slot, claim_value, claim_polarity,
                    condition_json, observed_time, source_observation_ids_json,
                    source_episode_ids_json, independent_unit_id,
                    valid_from, valid_to, impact_ids_json, directness,
                    source_reliability, extraction_confidence, statistics_json,
                    extractor_json, privacy_json, schema_version
                ) VALUES (
                    :evidence_id, :user_id, :status, :evidence_type,
                    :memory_family, :memory_type, :memory_category,
                    :claim_subject, :claim_slot, :claim_value, :claim_polarity,
                    :condition_json, :observed_time, :source_observation_ids_json,
                    :source_episode_ids_json, :independent_unit_id,
                    :valid_from, :valid_to, :impact_ids_json, :directness,
                    :source_reliability, :extraction_confidence,
                    :statistics_json, :extractor_json, :privacy_json,
                    :schema_version
                )
                """,
                {
                    **data,
                    "condition_json": _json(data["condition"]),
                    "source_observation_ids_json": _json(data["source_observation_ids"]),
                    "source_episode_ids_json": _json(data["source_episode_ids"]),
                    "impact_ids_json": _json(data["impact_ids"]),
                    "statistics_json": _json(data["statistics"]),
                    "extractor_json": _json(data["extractor"]),
                    "privacy_json": _json(data["privacy"]),
                },
            )
            return cursor.rowcount > 0

    def get_evidence(self, evidence_id: str) -> Evidence | None:
        with self.connection() as connection:
            row = connection.execute(
                "SELECT * FROM evidence WHERE evidence_id = ?",
                (evidence_id,),
            ).fetchone()
        return self._evidence_from_row(row) if row else None

    def list_evidence_for_episode(self, episode_id: str) -> list[Evidence]:
        with self.connection() as connection:
            rows = connection.execute(
                """
                SELECT * FROM evidence
                WHERE source_episode_ids_json LIKE ?
                ORDER BY observed_time, evidence_id
                """,
                (f'%"{episode_id}"%',),
            ).fetchall()
        return [self._evidence_from_row(row) for row in rows]

    def put_engine_run(self, run: dict[str, Any]) -> None:
        with self._lock, self.connection() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO engine_runs(
                    run_id, operation, module_versions_json, input_ids_json,
                    output_ids_json, trace_json, status, latency_ms, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run["run_id"],
                    run["operation"],
                    _json(run.get("module_versions") or {}),
                    _json(run.get("input_ids") or []),
                    _json(run.get("output_ids") or []),
                    _json(run.get("trace") or {}),
                    run["status"],
                    float(run.get("latency_ms") or 0.0),
                    run["created_at"],
                ),
            )

    def find_memory(self, user_id: str, slot_key: str, semantic_value: str) -> MemoryRecord | None:
        with self.connection() as connection:
            row = connection.execute(
                """
                SELECT * FROM memories
                WHERE user_id = ? AND slot_key = ? AND semantic_value = ?
                  AND status NOT IN ('deleted', 'blocked')
                LIMIT 1
                """,
                (user_id, slot_key, semantic_value),
            ).fetchone()
        return self._memory_from_row(row) if row else None

    def list_slot_memories(self, user_id: str, slot_key: str) -> list[MemoryRecord]:
        with self.connection() as connection:
            rows = connection.execute(
                """
                SELECT * FROM memories
                WHERE user_id = ? AND slot_key = ?
                  AND status NOT IN ('deleted', 'blocked')
                ORDER BY updated_at DESC
                """,
                (user_id, slot_key),
            ).fetchall()
        return [self._memory_from_row(row) for row in rows]

    def get_memories(self, memory_ids: list[str]) -> dict[str, MemoryRecord]:
        unique = sorted(set(memory_id for memory_id in memory_ids if memory_id))
        if not unique:
            return {}
        placeholders = ",".join("?" for _ in unique)
        with self.connection() as connection:
            rows = connection.execute(
                f"SELECT * FROM memories WHERE memory_id IN ({placeholders})",
                unique,
            ).fetchall()
        return {row["memory_id"]: self._memory_from_row(row) for row in rows}

    def search_memories(self, user_id: str, keyword: str) -> list[MemoryRecord]:
        with self.connection() as connection:
            rows = connection.execute(
                """
                SELECT * FROM memories
                WHERE user_id = ? AND semantic_value LIKE ?
                  AND status NOT IN ('deleted', 'blocked')
                ORDER BY updated_at DESC
                """,
                (user_id, f"%{keyword}%"),
            ).fetchall()
        return [self._memory_from_row(row) for row in rows]

    def set_memory_status(self, memory_id: str, status: str, updated_at: str) -> MemoryRecord | None:
        records = self.get_memories([memory_id])
        memory = records.get(memory_id)
        if not memory:
            return None
        memory.status = status
        memory.version += 1
        memory.updated_at = updated_at
        self.put_memory(memory)
        return memory

    def retract_evidence(self, evidence_ids: list[str]) -> int:
        if not evidence_ids:
            return 0
        placeholders = ",".join("?" for _ in evidence_ids)
        with self._lock, self.connection() as connection:
            cursor = connection.execute(
                f"UPDATE evidence SET status = 'retracted' WHERE evidence_id IN ({placeholders})",
                evidence_ids,
            )
            return cursor.rowcount

    def put_memory(self, memory: MemoryRecord) -> None:
        data = memory.to_dict()
        with self._lock, self.connection() as connection:
            connection.execute(
                """
                INSERT INTO memories VALUES (
                    :memory_id, :user_id, :memory_family, :memory_type,
                    :memory_category, :status, :slot_key, :semantic_value,
                    :condition_json, :scope_json, :evidence_ids_json,
                    :statistics_json, :confidence_json, :stability_json,
                    :provenance_json, :version, :created_at, :updated_at,
                    :schema_version
                )
                ON CONFLICT(memory_id) DO UPDATE SET
                    status=excluded.status,
                    evidence_ids_json=excluded.evidence_ids_json,
                    statistics_json=excluded.statistics_json,
                    confidence_json=excluded.confidence_json,
                    stability_json=excluded.stability_json,
                    provenance_json=excluded.provenance_json,
                    version=excluded.version,
                    updated_at=excluded.updated_at
                """,
                {
                    **data,
                    "condition_json": _json(data["condition"]),
                    "scope_json": _json(data["scope"]),
                    "evidence_ids_json": _json(data["evidence_ids"]),
                    "statistics_json": _json(data["statistics"]),
                    "confidence_json": _json(data["confidence"]),
                    "stability_json": _json(data["stability"]),
                    "provenance_json": _json(data["provenance"]),
                },
            )

    def put_impact(self, impact: dict[str, Any]) -> None:
        with self._lock, self.connection() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO impacts(
                    impact_id, evidence_id, target_memory_id, action, reason_code,
                    before_snapshot_json, after_snapshot_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    impact["impact_id"],
                    impact["evidence_id"],
                    impact["target_memory_id"],
                    impact["action"],
                    impact["reason_code"],
                    _json(impact.get("before_snapshot") or {}),
                    _json(impact.get("after_snapshot") or {}),
                    impact["created_at"],
                ),
            )

    def put_conflict_group(self, group: dict[str, Any]) -> None:
        with self._lock, self.connection() as connection:
            connection.execute(
                """
                INSERT INTO conflict_groups(conflict_group_id, slot_key, state_json, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(conflict_group_id) DO UPDATE SET
                    state_json=excluded.state_json,
                    updated_at=excluded.updated_at
                """,
                (group["conflict_group_id"], group["slot_key"], _json(group), group["updated_at"]),
            )

    def put_lifecycle_event(self, event: dict[str, Any]) -> None:
        with self._lock, self.connection() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO lifecycle_events(
                    event_id, memory_id, from_status, to_status, reason_code, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    event["event_id"],
                    event["memory_id"],
                    event.get("from_status"),
                    event["to_status"],
                    event["reason_code"],
                    event["created_at"],
                ),
            )

    def list_memories(self, user_id: str, include_archived: bool = False) -> list[MemoryRecord]:
        statuses = "('candidate','stable','historical','recover')" if include_archived else "('candidate','stable','historical','recover')"
        with self.connection() as connection:
            rows = connection.execute(
                f"SELECT * FROM memories WHERE user_id = ? AND status IN {statuses}",
                (user_id,),
            ).fetchall()
        return [self._memory_from_row(row) for row in rows]

    def get_index_refs(self, memory_id: str, state: str = "active") -> list[dict[str, str]]:
        with self.connection() as connection:
            rows = connection.execute(
                "SELECT * FROM index_refs WHERE memory_id = ? AND state = ?",
                (memory_id, state),
            ).fetchall()
        return [dict(row) for row in rows]

    def put_index_ref(
        self,
        memory_id: str,
        backend_id: str,
        *,
        backend: str = "mem0",
        tier: str = "mid",
        state: str = "active",
        updated_at: str,
    ) -> None:
        with self._lock, self.connection() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO index_refs
                    (memory_id, backend, backend_id, tier, state, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (memory_id, backend, backend_id, tier, state, updated_at),
            )

    def set_index_ref_state(self, memory_id: str, state: str, updated_at: str) -> int:
        with self._lock, self.connection() as connection:
            cursor = connection.execute(
                "UPDATE index_refs SET state = ?, updated_at = ? WHERE memory_id = ?",
                (state, updated_at, memory_id),
            )
            return cursor.rowcount

    def put_forget_request(self, request: dict[str, Any]) -> None:
        with self._lock, self.connection() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO forget_requests(
                    request_id, user_id, request_json, status, created_at, completed_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    request["request_id"],
                    request["user_id"],
                    _json(request),
                    request["status"],
                    request["created_at"],
                    request.get("completed_at"),
                ),
            )

    def counts(self) -> dict[str, int]:
        names = (
            "observations", "evidence", "impacts", "memories", "conflict_groups",
            "lifecycle_events", "index_refs", "engine_runs",
        )
        with self.connection() as connection:
            return {name: int(connection.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]) for name in names}

    @staticmethod
    def _evidence_from_row(row: sqlite3.Row) -> Evidence:
        keys = set(row.keys())
        return Evidence(
            evidence_id=row["evidence_id"],
            user_id=row["user_id"],
            status=row["status"],
            evidence_type=row["evidence_type"],
            memory_family=row["memory_family"],
            memory_type=row["memory_type"],
            memory_category=row["memory_category"],
            claim_subject=row["claim_subject"],
            claim_slot=row["claim_slot"],
            claim_value=row["claim_value"],
            claim_polarity=row["claim_polarity"],
            condition=_loads(row["condition_json"], {}),
            observed_time=row["observed_time"],
            source_observation_ids=tuple(
                _loads(row["source_observation_ids_json"], [])
            ),
            source_episode_ids=tuple(
                _loads(row["source_episode_ids_json"], [])
            )
            if "source_episode_ids_json" in keys
            else (),
            independent_unit_id=row["independent_unit_id"],
            valid_from=row["valid_from"] if "valid_from" in keys else "",
            valid_to=row["valid_to"] if "valid_to" in keys else "",
            impact_ids=tuple(_loads(row["impact_ids_json"], []))
            if "impact_ids_json" in keys
            else (),
            directness=row["directness"],
            source_reliability=float(row["source_reliability"]),
            extraction_confidence=float(row["extraction_confidence"]),
            statistics=_loads(row["statistics_json"], {}),
            extractor=_loads(row["extractor_json"], {}),
            privacy=_loads(row["privacy_json"], {}),
            schema_version=row["schema_version"],
        )

    @staticmethod
    def _observation_from_row(row: sqlite3.Row) -> Observation:
        payload = _loads(row["payload_json"], {}) if "payload_json" in row.keys() else {}
        return Observation(
            observation_id=row["observation_id"],
            source_event_id=row["source_event_id"],
            user_id=row["user_id"],
            session_id=row["session_id"],
            event_time=row["event_time"],
            ingest_time=row["ingest_time"],
            source_type=row["source_type"],
            actor=row["actor"],
            content=row["content"],
            sequence_no=payload.get("sequence_no"),
            app=str(payload.get("app") or ""),
            tool=str(payload.get("tool") or ""),
            action=str(payload.get("action") or ""),
            artifact_refs=tuple(payload.get("artifact_refs") or ()),
            entity_refs=tuple(payload.get("entity_refs") or ()),
            available_tools=tuple(payload.get("available_tools") or ()),
            input_refs=tuple(payload.get("input_refs") or ()),
            output_refs=tuple(payload.get("output_refs") or ()),
            state=dict(payload.get("state") or {}),
            result=dict(payload.get("result") or {}),
            raw_source_ref=str(payload.get("raw_source_ref") or ""),
            completeness=dict(payload.get("completeness") or {}),
            task_hint=row["task_hint"],
            goal_hint=row["goal_hint"],
            context=_loads(row["context_json"], {}),
            source_reliability=float(row["source_reliability"]),
            privacy=_loads(row["privacy_json"], {}),
            schema_version=row["schema_version"],
        )

    @staticmethod
    def _episode_from_row(row: sqlite3.Row) -> Episode:
        state = _loads(row["state_json"], {})
        return Episode(
            episode_id=row["episode_id"],
            user_id=row["user_id"],
            session_id=row["session_id"],
            observation_ids=list(_loads(row["observation_ids_json"], [])),
            start_time=row["start_time"],
            end_time=row["end_time"],
            status=str(state.get("status") or "open"),
            task_hint=str(state.get("task_hint") or ""),
            goal_hint=str(state.get("goal_hint") or ""),
            apps=list(state.get("apps") or []),
            artifact_refs=list(state.get("artifact_refs") or []),
            entity_refs=list(state.get("entity_refs") or []),
            task_instance_ids=list(state.get("task_instance_ids") or []),
            boundary_confidence=float(state.get("boundary_confidence") or 0.0),
            boundary_reason=str(state.get("boundary_reason") or "initial"),
            state=dict(state.get("state") or {}),
            schema_version=str(state.get("schema_version") or "episode.v1"),
        )

    @staticmethod
    def _memory_from_row(row: sqlite3.Row) -> MemoryRecord:
        return MemoryRecord(
            memory_id=row["memory_id"],
            user_id=row["user_id"],
            memory_family=row["memory_family"],
            memory_type=row["memory_type"],
            memory_category=row["memory_category"],
            status=row["status"],
            slot_key=row["slot_key"],
            semantic_value=row["semantic_value"],
            evidence_ids=list(_loads(row["evidence_ids_json"], [])),
            condition=_loads(row["condition_json"], {}),
            scope=_loads(row["scope_json"], {}),
            statistics=_loads(row["statistics_json"], {}),
            confidence=_loads(row["confidence_json"], {}),
            stability=_loads(row["stability_json"], {}),
            provenance=_loads(row["provenance_json"], {}),
            version=int(row["version"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            schema_version=row["schema_version"],
        )
