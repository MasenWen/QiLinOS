from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import sqlite3
import statistics
import time
from array import array
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from src.memory_engine.knowledge_tags import WorkplaceTagKnowledgeBase
from src.memory_engine.observation import ObservationBudget, ObservationMatcher
from src.memory_engine.reflection import DeepSeekReflectionClient
from src.memory_engine.span_matching import JiebaSpanTokenizer
from tools.evaluate_bm25_embedding_cascade import _cosine
from tools.evaluate_bm25_only_retrieval import (
    JiebaIdentifierTokenizer,
    PrebuiltBM25Index,
    _memory_document,
)


DEFAULT_DATASET = Path(
    "../os_agent_memory_query_benchmark_official_1000_v1_20260806"
)
DEFAULT_DATABASE = Path("runtime/knowledge/workplace_tags_v1.sqlite")
DEFAULT_OUTPUT = Path(
    "runtime/results/official_1000_end_to_end/end_to_end_v1.json"
)
DEFAULT_MARKDOWN = Path(
    "runtime/results/official_1000_end_to_end/in-out.md"
)
DEFAULT_STATE_DATABASE = Path(
    "runtime/state/official_1000_full_chain.sqlite"
)

ANSWER_SYSTEM = """# Memory-aware desktop agent

请用简洁中文回答。优先依据当前上下文，再使用检索到的用户记忆。
`retrieved_memories` 是可溯源的用户证据；`knowledge_references` 只是帮助理解应用、
任务和对象的通用标签，不代表用户偏好，不能覆盖记忆。若证据互相冲突或不足以确定
唯一操作，请提出一个明确的澄清问题。不得提及内部 ID、排名或分数。

只返回一个 JSON 对象，字段为 `answer`。
"""

JUDGE_SYSTEM = """# Independent answer reviewer

回答已经生成完毕。请严格根据给定答案要点和评分规则审查，不因表述自然就奖励。
返回 JSON：`decision_correct`（布尔）、`content_score_10`（数字）、
`groundedness_score_10`（数字）、`knowledge_helpful`（布尔）和 `reason`（简短中文）。
"""


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _read_ndjson_gz(path: Path) -> list[dict[str, Any]]:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def _json_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if value in (None, ""):
        return []
    parsed = json.loads(str(value))
    return parsed if isinstance(parsed, list) else []


def _unique_text(values: Iterable[Any]) -> list[str]:
    return list(
        dict.fromkeys(
            str(value).strip()
            for value in values
            if value is not None and str(value).strip()
        )
    )


def _percentile(values: Sequence[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    low = int(position)
    high = min(low + 1, len(ordered) - 1)
    ratio = position - low
    return ordered[low] * (1.0 - ratio) + ordered[high] * ratio


def _latency(values: Sequence[float]) -> dict[str, float | int]:
    return {
        "count": len(values),
        "mean_ms": statistics.fmean(values) if values else 0.0,
        "p50_ms": _percentile(values, 0.50),
        "p95_ms": _percentile(values, 0.95),
        "p99_ms": _percentile(values, 0.99),
        "max_ms": max(values, default=0.0),
    }


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if not value:
        return {}
    try:
        parsed = json.loads(str(value))
    except (TypeError, json.JSONDecodeError):
        return {}
    return dict(parsed) if isinstance(parsed, Mapping) else {}


def _compact_text(values: Iterable[Any], *, limit: int = 700) -> str:
    text = "；".join(_unique_text(values))
    if len(text) <= limit:
        return text
    return text[:limit].rsplit("；", 1)[0] or text[:limit]


def _semantic_fragment(memory: Mapping[str, Any]) -> str:
    semantic = _json_object(memory.get("semantic_value"))
    kind = str(memory.get("memory_kind") or "")
    if kind == "operation_episode":
        return _compact_text(
            (
                "应用 " + " ".join(semantic.get("apps") or []),
                "动作 " + " ".join(semantic.get("actions") or []),
                "对象 " + " ".join((semantic.get("targets") or [])[:16]),
                "状态 " + " ".join(semantic.get("statuses") or []),
                *(semantic.get("contexts") or [])[:3],
            )
        )
    return _compact_text(
        (
            memory.get("memory_summary"),
            memory.get("expected_action"),
            memory.get("constraints"),
        )
    )


def _legacy_memory(
    record: Mapping[str, Any],
    source_events: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    source_by_task = {
        str(event.get("source_task_id")): event for event in source_events
    }
    source = source_by_task.get(str(record.get("source_task_id")), {})
    evidence_ids = _unique_text(
        (
            record.get("memory_id"),
            source.get("event_id"),
        )
    )
    return {
        **dict(record),
        "memory_kind": "legacy_memory",
        "episode_id": str(record.get("source_task_id") or ""),
        "evidence_ids": evidence_ids,
        "source_event_count": 1 if source else 0,
        "source_text": str(source.get("instruction") or ""),
    }


def _dialogue_memory(
    episode_id: str,
    events: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    ordered = sorted(
        events,
        key=lambda value: (
            str(value.get("event_time") or ""),
            int(value.get("source_event_index") or 0),
            str(value.get("event_id") or ""),
        ),
    )
    messages = _unique_text(event.get("message_text") for event in ordered)
    tasks = _unique_text(event.get("context_task") for event in ordered)
    artifacts = _unique_text(event.get("context_artifact") for event in ordered)
    topics = _unique_text(event.get("context_topic") for event in ordered)
    apps = _unique_text(
        app
        for event in ordered
        for app in (
            event.get("windows_app_id"),
            *list(event.get("referenced_app_ids") or []),
        )
    )
    signals = _unique_text(event.get("memory_signal_type") for event in ordered)
    summary = "；".join(messages)
    semantic = {
        "kind": "dialogue_episode",
        "tasks": tasks,
        "artifacts": artifacts,
        "topics": topics,
        "apps": apps,
        "signals": signals,
    }
    return {
        "memory_id": f"DIALOGUE_MEMORY::{episode_id}",
        "memory_kind": "dialogue_episode",
        "episode_id": episode_id,
        "memory_summary": summary,
        "expected_action": " ".join(tasks),
        "constraints": " ".join((*artifacts, *topics, *signals)),
        "condition": json.dumps(
            {"apps": apps, "tasks": tasks}, ensure_ascii=False
        ),
        "semantic_value": json.dumps(semantic, ensure_ascii=False),
        "evidence_ids": _unique_text(
            event.get("event_id") for event in ordered
        ),
        "source_event_count": len(ordered),
        "source_text": summary,
    }


def _operation_memory(
    episode_id: str,
    events: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    ordered = sorted(
        events,
        key=lambda value: (
            str(value.get("event_time") or ""),
            int(value.get("source_event_index") or 0),
            str(value.get("event_id") or ""),
        ),
    )
    apps = _unique_text(
        event.get("windows_app_id") or event.get("source_app")
        for event in ordered
    )
    actions = _unique_text(event.get("action_key") for event in ordered)
    targets = _unique_text(event.get("target_value") for event in ordered)
    contexts = _unique_text(event.get("context_text") for event in ordered)
    statuses = _unique_text(event.get("result_status") for event in ordered)
    clauses = _unique_text(
        " ".join(
            value
            for value in (
                str(event.get("action_key") or ""),
                str(event.get("target_type") or ""),
                str(event.get("target_value") or ""),
                str(event.get("context_text") or ""),
                str(event.get("result_status") or ""),
            )
            if value
        )
        for event in ordered
    )
    summary = "；".join(clauses)
    semantic = {
        "kind": "operation_episode",
        "apps": apps,
        "actions": actions,
        "targets": targets,
        "statuses": statuses,
        "contexts": contexts,
    }
    return {
        "memory_id": f"OPERATION_MEMORY::{episode_id}",
        "memory_kind": "operation_episode",
        "episode_id": episode_id,
        "memory_summary": summary,
        "expected_action": " ".join(actions),
        "constraints": " ".join((*targets, *statuses, *contexts)),
        "condition": json.dumps({"apps": apps}, ensure_ascii=False),
        "semantic_value": json.dumps(semantic, ensure_ascii=False),
        "evidence_ids": _unique_text(
            event.get("event_id") for event in ordered
        ),
        "source_event_count": len(ordered),
        "source_text": summary,
    }


def form_memories(
    precedent_rows: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, str], dict[str, Any]]:
    started = time.perf_counter()
    legacy: dict[str, dict[str, Any]] = {}
    dialogue_events: dict[str, dict[str, Mapping[str, Any]]] = defaultdict(dict)
    operation_events: dict[str, dict[str, Mapping[str, Any]]] = defaultdict(dict)
    input_evidence_ids: set[str] = set()
    cases_by_evidence: dict[str, set[str]] = defaultdict(set)

    for row in precedent_rows:
        case_id = str(row.get("precedent_case_id") or "")
        row_evidence = [str(value) for value in row.get("evidence_ids", [])]
        input_evidence_ids.update(row_evidence)
        for evidence_id in row_evidence:
            cases_by_evidence[evidence_id].add(case_id)
        source_events = list(row.get("legacy_source_events") or [])
        for record in row.get("legacy_memory_records") or []:
            memory = _legacy_memory(record, source_events)
            legacy[memory["memory_id"]] = memory
        for event in row.get("dialogue_events") or []:
            episode_id = str(event.get("episode_id") or "")
            event_id = str(event.get("event_id") or "")
            if episode_id and event_id:
                dialogue_events[episode_id][event_id] = event
        for event in row.get("operation_events") or []:
            episode_id = str(event.get("episode_id") or "")
            event_id = str(event.get("event_id") or "")
            if episode_id and event_id:
                operation_events[episode_id][event_id] = event

    memories = list(legacy.values())
    memories.extend(
        _dialogue_memory(episode_id, tuple(events.values()))
        for episode_id, events in sorted(dialogue_events.items())
    )
    memories.extend(
        _operation_memory(episode_id, tuple(events.values()))
        for episode_id, events in sorted(operation_events.items())
    )
    for memory in memories:
        case_ids = sorted(
            {
                case_id
                for evidence_id in memory["evidence_ids"]
                for case_id in cases_by_evidence.get(evidence_id, ())
                if case_id
            }
        )
        memory["precedent_case_ids"] = case_ids
    evidence_to_memory: dict[str, str] = {}
    collisions: dict[str, list[str]] = defaultdict(list)
    for memory in memories:
        for evidence_id in memory["evidence_ids"]:
            previous = evidence_to_memory.get(evidence_id)
            if previous and previous != memory["memory_id"]:
                collisions[evidence_id].extend((previous, memory["memory_id"]))
            evidence_to_memory[evidence_id] = memory["memory_id"]

    represented = input_evidence_ids.intersection(evidence_to_memory)
    report = {
        "precedent_bundle_count": len(precedent_rows),
        "formed_memory_count": len(memories),
        "memory_counts_by_kind": {
            kind: sum(memory["memory_kind"] == kind for memory in memories)
            for kind in (
                "legacy_memory",
                "dialogue_episode",
                "operation_episode",
            )
        },
        "source_event_count": sum(
            int(memory["source_event_count"]) for memory in memories
        ),
        "input_evidence_count": len(input_evidence_ids),
        "represented_evidence_count": len(represented),
        "evidence_coverage": (
            len(represented) / len(input_evidence_ids)
            if input_evidence_ids
            else 1.0
        ),
        "unrepresented_evidence_ids": sorted(input_evidence_ids - represented),
        "evidence_collision_count": len(collisions),
        "elapsed_ms": (time.perf_counter() - started) * 1000.0,
        "policy": (
            "legacy formed memories are retained; structured dialogue and "
            "operation events are grouped by their source episode_id"
        ),
    }
    return memories, evidence_to_memory, report


class PersistentEvaluationStore:
    """Durable cursor and memory state for incremental benchmark runs."""

    schema_version = "official_1000_full_chain.v1"

    def __init__(self, path: Path, *, dataset_fingerprint: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.connection = sqlite3.connect(path)
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(
            """
            PRAGMA journal_mode=WAL;
            PRAGMA synchronous=FULL;
            CREATE TABLE IF NOT EXISTS metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS memories (
                memory_id TEXT PRIMARY KEY,
                payload_json TEXT NOT NULL,
                vector_blob BLOB NOT NULL,
                vector_dim INTEGER NOT NULL,
                created_sequence INTEGER NOT NULL,
                source_kind TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS observations (
                query_id TEXT PRIMARY KEY,
                sequence_no INTEGER NOT NULL UNIQUE,
                payload_json TEXT NOT NULL,
                promoted_memory_id TEXT
            );
            CREATE TABLE IF NOT EXISTS query_results (
                query_id TEXT PRIMARY KEY,
                sequence_no INTEGER NOT NULL UNIQUE,
                result_json TEXT NOT NULL
            );
            """
        )
        self._bind_metadata("schema_version", self.schema_version)
        self._bind_metadata("dataset_fingerprint", dataset_fingerprint)
        self.connection.commit()

    def _bind_metadata(self, key: str, value: str) -> None:
        row = self.connection.execute(
            "SELECT value FROM metadata WHERE key = ?", (key,)
        ).fetchone()
        if row is not None and row["value"] != value:
            raise RuntimeError(
                f"persistent_state_mismatch:{key}:{row['value']}:{value}"
            )
        self.connection.execute(
            "INSERT OR IGNORE INTO metadata(key, value) VALUES (?, ?)",
            (key, value),
        )

    @staticmethod
    def _vector_blob(vector: Sequence[float]) -> tuple[bytes, int]:
        values = array("f", (float(value) for value in vector))
        return values.tobytes(), len(values)

    @staticmethod
    def _vector(blob: bytes, dimension: int) -> tuple[float, ...]:
        values = array("f")
        values.frombytes(blob)
        if len(values) != dimension:
            raise RuntimeError("persisted_vector_dimension_mismatch")
        return tuple(values)

    def memory_ids(self) -> set[str]:
        return {
            str(row["memory_id"])
            for row in self.connection.execute("SELECT memory_id FROM memories")
        }

    def upsert_seed_memory(
        self,
        memory: Mapping[str, Any],
        vector: Sequence[float],
    ) -> None:
        blob, dimension = self._vector_blob(vector)
        self.connection.execute(
            """
            INSERT OR IGNORE INTO memories(
                memory_id, payload_json, vector_blob, vector_dim,
                created_sequence, source_kind
            ) VALUES (?, ?, ?, ?, 0, ?)
            """,
            (
                memory["memory_id"],
                json.dumps(memory, ensure_ascii=False),
                blob,
                dimension,
                memory["memory_kind"],
            ),
        )
        self.connection.commit()

    def load_memories(
        self,
    ) -> tuple[list[dict[str, Any]], dict[str, tuple[float, ...]]]:
        memories = []
        vectors = {}
        for row in self.connection.execute(
            "SELECT * FROM memories ORDER BY created_sequence, memory_id"
        ):
            memory = json.loads(row["payload_json"])
            memories.append(memory)
            vectors[row["memory_id"]] = self._vector(
                row["vector_blob"], int(row["vector_dim"])
            )
        return memories, vectors

    def processed_sequence_numbers(self) -> set[int]:
        return {
            int(row["sequence_no"])
            for row in self.connection.execute(
                "SELECT sequence_no FROM query_results"
            )
        }

    def commit_query(
        self,
        *,
        sequence_no: int,
        query_id: str,
        observation: Mapping[str, Any],
        result: Mapping[str, Any],
        promoted_memory: Mapping[str, Any] | None,
        promoted_vector: Sequence[float] | None,
    ) -> None:
        promoted_id = (
            str(promoted_memory["memory_id"]) if promoted_memory else None
        )
        with self.connection:
            if promoted_memory is not None and promoted_vector is not None:
                blob, dimension = self._vector_blob(promoted_vector)
                self.connection.execute(
                    """
                    INSERT OR IGNORE INTO memories(
                        memory_id, payload_json, vector_blob, vector_dim,
                        created_sequence, source_kind
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        promoted_id,
                        json.dumps(promoted_memory, ensure_ascii=False),
                        blob,
                        dimension,
                        sequence_no,
                        promoted_memory["memory_kind"],
                    ),
                )
            self.connection.execute(
                """
                INSERT INTO observations(
                    query_id, sequence_no, payload_json, promoted_memory_id
                ) VALUES (?, ?, ?, ?)
                """,
                (
                    query_id,
                    sequence_no,
                    json.dumps(observation, ensure_ascii=False),
                    promoted_id,
                ),
            )
            self.connection.execute(
                """
                INSERT INTO query_results(query_id, sequence_no, result_json)
                VALUES (?, ?, ?)
                """,
                (
                    query_id,
                    sequence_no,
                    json.dumps(result, ensure_ascii=False),
                ),
            )

    def query_results(self) -> list[dict[str, Any]]:
        return [
            json.loads(row["result_json"])
            for row in self.connection.execute(
                "SELECT result_json FROM query_results ORDER BY sequence_no"
            )
        ]

    def statistics(self) -> dict[str, Any]:
        counts = {
            row["source_kind"]: int(row["count"])
            for row in self.connection.execute(
                """
                SELECT source_kind, COUNT(*) AS count
                FROM memories GROUP BY source_kind
                """
            )
        }
        return {
            "path": str(self.path),
            "database_bytes": self.path.stat().st_size,
            "memory_count": sum(counts.values()),
            "memory_counts_by_kind": counts,
            "observation_count": self.connection.execute(
                "SELECT COUNT(*) FROM observations"
            ).fetchone()[0],
            "processed_query_count": self.connection.execute(
                "SELECT COUNT(*) FROM query_results"
            ).fetchone()[0],
            "last_sequence_no": self.connection.execute(
                "SELECT COALESCE(MAX(sequence_no), 0) FROM query_results"
            ).fetchone()[0],
        }

    def close(self) -> None:
        self.connection.close()


@dataclass(frozen=True)
class HybridCandidate:
    memory_id: str
    bm25_score: float
    bm25_ratio: float
    semantic_score: float
    identifier_coverage: float
    combined_score: float
    matched_terms: tuple[str, ...]


class EpisodeHybridRetriever:
    """BM25 fast path with one embedding verification and semantic fallback."""

    def __init__(
        self,
        memories: Sequence[Mapping[str, Any]],
        *,
        tokenizer: JiebaIdentifierTokenizer,
        embedder: Any,
        vectors_by_memory: Mapping[str, Sequence[float]],
    ) -> None:
        self.memories = {str(row["memory_id"]): dict(row) for row in memories}
        self.documents = {
            memory_id: _memory_document(row)
            for memory_id, row in self.memories.items()
        }
        self.tokenizer = tokenizer
        self.embedder = embedder
        self.index = PrebuiltBM25Index(self.documents, tokenizer)
        self.memory_ids_by_namespace: dict[str, set[str]] = defaultdict(set)
        for memory_id, memory in self.memories.items():
            for namespace in memory.get("precedent_case_ids") or ():
                self.memory_ids_by_namespace[str(namespace)].add(memory_id)
        self.index_by_namespace = {
            namespace: PrebuiltBM25Index(
                {
                    memory_id: self.documents[memory_id]
                    for memory_id in memory_ids
                },
                tokenizer,
            )
            for namespace, memory_ids in self.memory_ids_by_namespace.items()
        }
        self.fragment_vectors = {
            memory_id: (vectors_by_memory[memory_id],)
            for memory_id in self.memories
        }
        self.fragment_count = len(self.fragment_vectors)
        self.pending_memory_ids: set[str] = set()
        self.additions_since_rebuild = 0

    def add_memory(
        self,
        memory: Mapping[str, Any],
        vector: Sequence[float],
    ) -> None:
        memory_id = str(memory["memory_id"])
        self.memories[memory_id] = dict(memory)
        self.documents[memory_id] = _memory_document(memory)
        self.fragment_vectors[memory_id] = (vector,)
        self.pending_memory_ids.add(memory_id)
        self.additions_since_rebuild += 1
        self.fragment_count = len(self.fragment_vectors)
        if self.additions_since_rebuild >= 20:
            self.rebuild_index()

    def rebuild_index(self) -> None:
        self.index = PrebuiltBM25Index(self.documents, self.tokenizer)
        self.pending_memory_ids.clear()
        self.additions_since_rebuild = 0

    def rank(
        self,
        lexical_text: str,
        semantic_text: str,
        *,
        top_k: int = 8,
        namespace: str | None = None,
        query_vector: Sequence[float] | None = None,
    ) -> tuple[
        tuple[HybridCandidate, ...],
        dict[str, Any],
        Sequence[float],
    ]:
        started = time.perf_counter()
        scoped_memory_ids = (
            self.memory_ids_by_namespace.get(namespace, set())
            if namespace is not None
            else set(self.memories)
        )
        if not scoped_memory_ids:
            return (), {
                "candidate_limit": 0,
                "bm25_hit_count": 0,
                "fast_path": False,
                "namespace": namespace,
                "namespace_memory_count": 0,
                "pending_memory_count": len(self.pending_memory_ids),
                "fallback_scored_memory_count": 0,
                "bm25_ms": 0.0,
                "embedding_ms": 0.0,
                "total_ms": 0.0,
            }, ()
        identifiers = set(self.tokenizer.identifiers(lexical_text))
        candidate_limit = min(
            len(scoped_memory_ids),
            max(16, 16 + 4 * len(identifiers) + 4 * min(6, len(lexical_text) // 120)),
        )
        bm25_started = time.perf_counter()
        active_index = (
            self.index_by_namespace[namespace]
            if namespace is not None
            else self.index
        )
        bm25_hits = active_index.search(lexical_text, top_k=candidate_limit)
        bm25_ms = (time.perf_counter() - bm25_started) * 1000.0
        bm25_by_id = {hit.document_id: hit for hit in bm25_hits}
        top_bm25 = max((hit.score for hit in bm25_hits), default=1.0) or 1.0

        reused_query_vector = query_vector is not None
        embedding_started = time.perf_counter()
        if query_vector is None:
            query_vector = self.embedder.embed([semantic_text])[0]
        embedding_ms = (time.perf_counter() - embedding_started) * 1000.0

        def score(memory_id: str, *, semantic_fallback: bool = False) -> HybridCandidate:
            hit = bm25_by_id.get(memory_id)
            semantic = max(
                (_cosine(query_vector, vector) for vector in self.fragment_vectors[memory_id]),
                default=0.0,
            )
            covered = sum(
                identifier in self.documents[memory_id].casefold()
                for identifier in identifiers
            )
            identifier_coverage = covered / len(identifiers) if identifiers else 0.0
            bm25_score = hit.score if hit else 0.0
            bm25_ratio = bm25_score / top_bm25 if hit else 0.0
            if semantic_fallback:
                combined = (
                    0.90 * semantic
                    + 0.07 * bm25_ratio
                    + 0.03 * identifier_coverage
                )
            else:
                combined = (
                    0.72 * semantic
                    + 0.18 * bm25_ratio
                    + 0.10 * identifier_coverage
                )
            return HybridCandidate(
                memory_id=memory_id,
                bm25_score=bm25_score,
                bm25_ratio=bm25_ratio,
                semantic_score=semantic,
                identifier_coverage=identifier_coverage,
                combined_score=combined,
                matched_terms=hit.matched_terms if hit else (),
            )

        shortlist = sorted(
            (score(hit.document_id) for hit in bm25_hits),
            key=lambda value: (-value.combined_score, value.memory_id),
        )
        margin = (
            shortlist[0].combined_score - shortlist[1].combined_score
            if len(shortlist) > 1
            else shortlist[0].combined_score if shortlist else 0.0
        )
        fast_path = bool(
            shortlist
            and not self.pending_memory_ids
            and shortlist[0].semantic_score >= 0.75
            and shortlist[0].combined_score >= 0.82
            and margin >= 0.10
        )
        if fast_path:
            ranked = shortlist
        else:
            ranked = sorted(
                (
                    score(memory_id, semantic_fallback=True)
                    for memory_id in scoped_memory_ids
                ),
                key=lambda value: (-value.combined_score, value.memory_id),
            )
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        return tuple(ranked[:top_k]), {
            "candidate_limit": candidate_limit,
            "bm25_hit_count": len(bm25_hits),
            "fast_path": fast_path,
            "namespace": namespace,
            "namespace_memory_count": len(scoped_memory_ids),
            "pending_memory_count": len(self.pending_memory_ids),
            "fallback_scored_memory_count": (
                0 if fast_path else len(scoped_memory_ids)
            ),
            "reused_observation_vector": reused_query_vector,
            "bm25_ms": bm25_ms,
            "embedding_ms": embedding_ms,
            "total_ms": elapsed_ms,
        }, query_vector


def _memory_ids(
    query: Mapping[str, str],
    field: str,
    evidence_to_memory: Mapping[str, str],
) -> list[str]:
    return list(
        dict.fromkeys(
            evidence_to_memory[evidence_id]
            for evidence_id in _json_list(query.get(field))
            if evidence_id in evidence_to_memory
        )
    )


def _knowledge_refs(
    knowledge: WorkplaceTagKnowledgeBase,
    text: str,
    *,
    limit: int = 6,
) -> tuple[list[dict[str, Any]], float]:
    started = time.perf_counter()
    candidates = knowledge.query(text, top_k_per_group=4)
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    values = []
    for candidate in candidates[:limit]:
        values.append(
            {
                "tag_id": candidate.tag_id,
                "name": candidate.name,
                "groups": list(candidate.groups),
                "pack_id": candidate.pack_id,
                "score": round(candidate.score, 6),
                "exact_alias": candidate.exact_alias,
                "matched_alias": candidate.matched_alias,
            }
        )
    return values, elapsed_ms


def _observation_payload(result: Any) -> dict[str, Any]:
    frames = []
    for frame in result.frames[:3]:
        frames.append(
            {
                "condition_tag_id": (
                    frame.condition.tag_id if frame.condition else None
                ),
                "object_tag_id": frame.object.tag_id,
                "attitude_direction": (
                    "positive" if frame.attitude.value > 0 else "negative"
                ),
                "attitude_score": frame.attitude.value,
                "temporal_label": (
                    frame.temporal.label if frame.temporal else None
                ),
                "confidence": frame.confidence,
            }
        )
    budget = result.diagnostics.get("budget", {})
    return {
        "formed": bool(frames),
        "frames": frames,
        "hypothesis_count": len(result.hypotheses),
        "budget_exhausted": bool(budget.get("hard_stop_reached")),
    }


def _memory_payload(memory: Mapping[str, Any], rank: HybridCandidate) -> dict[str, Any]:
    return {
        "memory_id": memory["memory_id"],
        "memory_kind": memory["memory_kind"],
        "episode_id": memory["episode_id"],
        "summary": memory["memory_summary"],
        "expected_action": memory["expected_action"],
        "constraints": memory["constraints"],
        "score": round(rank.combined_score, 6),
        "semantic_score": round(rank.semantic_score, 6),
        "matched_terms": list(rank.matched_terms),
        "source_event_count": memory["source_event_count"],
        "evidence_ids": list(memory["evidence_ids"]),
    }


def _query_memory(
    query: Mapping[str, str],
    observation: Mapping[str, Any],
    knowledge_refs: Sequence[Mapping[str, Any]],
) -> dict[str, Any] | None:
    if not observation["formed"]:
        return None
    query_id = query["query_id"]
    frames = list(observation["frames"])
    condition_ids = _unique_text(
        frame.get("condition_tag_id") for frame in frames
    )
    object_ids = _unique_text(frame.get("object_tag_id") for frame in frames)
    temporal_labels = _unique_text(
        frame.get("temporal_label") for frame in frames
    )
    condition = {
        "condition_tag_ids": condition_ids,
        "current_context": query.get("current_context_text", ""),
    }
    semantic = {
        "kind": "query_observation",
        "object_tag_ids": object_ids,
        "temporal_labels": temporal_labels,
        "frames": frames,
        "knowledge_tag_ids": [value["tag_id"] for value in knowledge_refs],
    }
    return {
        "memory_id": f"QUERY_MEMORY::{query_id}",
        "memory_kind": "query_observation",
        "episode_id": f"QUERY_EPISODE::{query_id}",
        "memory_summary": query["query_text"],
        "expected_action": " ".join(object_ids),
        "constraints": _compact_text(
            (
                query.get("current_context_text"),
                " ".join(condition_ids),
                " ".join(temporal_labels),
            ),
            limit=700,
        ),
        "condition": json.dumps(condition, ensure_ascii=False),
        "semantic_value": json.dumps(semantic, ensure_ascii=False),
        "evidence_ids": [f"QUERY_EVENT::{query_id}"],
        "source_event_count": 1,
        "source_text": query["query_text"],
        "precedent_case_ids": [query["precedent_case_id"]],
    }


def run_queries(
    query_rows: Sequence[Mapping[str, str]],
    *,
    matcher: ObservationMatcher,
    retriever: EpisodeHybridRetriever,
    knowledge: WorkplaceTagKnowledgeBase,
    evidence_to_memory: Mapping[str, str],
    store: PersistentEvaluationStore | None,
    persist_queries: bool = True,
    isolate_precedent_case: bool = False,
) -> list[dict[str, Any]]:
    output = []
    for query in query_rows:
        query_text = query["query_text"].strip()
        context_text = query.get("current_context_text", "").strip()
        lexical_text = " ".join(value for value in (query_text, context_text) if value)

        observation_started = time.perf_counter()
        observation_result = matcher.match(
            query_text,
            budget=ObservationBudget(
                started_at=time.perf_counter(),
                soft_limit_ms=500.0,
                hard_limit_ms=800.0,
            ),
        )
        observation_ms = (time.perf_counter() - observation_started) * 1000.0
        observation = _observation_payload(observation_result)

        refs, knowledge_ms = _knowledge_refs(knowledge, lexical_text)
        exact_names = _unique_text(
            ref["name"] for ref in refs if ref["exact_alias"]
        )
        semantic_text = " ".join((query_text, *exact_names)).strip()
        observation_query_vector = matcher.embedder.cached_vector(query_text)
        ranked, retrieval_diagnostics, query_vector = retriever.rank(
            lexical_text,
            semantic_text,
            top_k=8,
            namespace=(
                query["precedent_case_id"] if isolate_precedent_case else None
            ),
            query_vector=observation_query_vector,
        )
        ranked_ids = [value.memory_id for value in ranked]
        required_ids = _memory_ids(query, "required_evidence_ids", evidence_to_memory)
        candidate_ids = _memory_ids(query, "candidate_evidence_ids", evidence_to_memory)
        forbidden_ids = _memory_ids(query, "forbidden_evidence_ids", evidence_to_memory)
        memories = [
            _memory_payload(retriever.memories[value.memory_id], value)
            for value in ranked
        ]
        total_ms = observation_ms + knowledge_ms + retrieval_diagnostics["total_ms"]
        sequence_no = int(query["sequence_no"])
        would_promote = _query_memory(query, observation, refs)
        promoted_memory = would_promote if persist_queries else None
        row = {
                "sequence_no": sequence_no,
                "query_id": query["query_id"],
                "precedent_case_id": query["precedent_case_id"],
                "answer_group_id": query["answer_group_id"],
                "dataset_origin": query["dataset_origin"],
                "evaluation_track": query["evaluation_track"],
                "query_type": query["query_type"],
                "difficulty_level": query["difficulty_level"],
                "query_text": query_text,
                "current_context_text": context_text,
                "query_observation": observation,
                "knowledge_references": refs,
                "ranked_memory_ids": ranked_ids,
                "required_memory_ids": required_ids,
                "candidate_memory_ids": candidate_ids,
                "forbidden_memory_ids": forbidden_ids,
                "retrieved_memories": memories,
                "stages_ms": {
                    "observation": observation_ms,
                    "knowledge": knowledge_ms,
                    "retrieval": retrieval_diagnostics["total_ms"],
                    "total": total_ms,
                },
                "retrieval_diagnostics": retrieval_diagnostics,
                "persisted_after_retrieval": persist_queries,
                "would_form_query_memory": would_promote is not None,
                "promoted_query_memory_id": (
                    promoted_memory["memory_id"] if promoted_memory else None
                ),
            }
        if persist_queries:
            if store is None:
                raise ValueError("persistent_store_required_for_dynamic_queries")
            store.commit_query(
                sequence_no=sequence_no,
                query_id=query["query_id"],
                observation=observation,
                result=row,
                promoted_memory=promoted_memory,
                promoted_vector=query_vector if promoted_memory else None,
            )
            if promoted_memory is not None:
                retriever.add_memory(promoted_memory, query_vector)
        output.append(row)
    return output


def retrieval_summary(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    required_total = sum(len(row["required_memory_ids"]) for row in rows)

    def at(k: int) -> dict[str, Any]:
        hits = sum(
            memory_id in row["ranked_memory_ids"][:k]
            for row in rows
            for memory_id in row["required_memory_ids"]
        )
        answerable = [row for row in rows if row["required_memory_ids"]]
        return {
            "required_memory_hit_count": hits,
            "required_memory_recall": hits / required_total if required_total else 1.0,
            "any_required_query_hit_rate": sum(
                bool(set(row["required_memory_ids"]) & set(row["ranked_memory_ids"][:k]))
                for row in answerable
            ) / len(answerable) if answerable else 1.0,
            "all_required_query_success_rate": sum(
                set(row["required_memory_ids"]) <= set(row["ranked_memory_ids"][:k])
                for row in answerable
            ) / len(answerable) if answerable else 1.0,
            "forbidden_memory_query_rate": sum(
                bool(set(row["forbidden_memory_ids"]) & set(row["ranked_memory_ids"][:k]))
                for row in rows
            ) / len(rows) if rows else 0.0,
        }

    return {
        "query_count": len(rows),
        "required_memory_count": required_total,
        **{f"recall_at_{k}": at(k) for k in (1, 2, 3, 5, 8)},
        "observation_formation_rate": sum(
            bool(row["query_observation"]["formed"]) for row in rows
        ) / len(rows) if rows else 1.0,
        "budget_exhaustion_rate": sum(
            bool(row["query_observation"]["budget_exhausted"]) for row in rows
        ) / len(rows) if rows else 0.0,
        "fast_path_rate": sum(
            bool(row["retrieval_diagnostics"]["fast_path"]) for row in rows
        ) / len(rows) if rows else 0.0,
        "query_observation_promotion_rate": sum(
            bool(row.get("promoted_query_memory_id")) for row in rows
        ) / len(rows) if rows else 0.0,
        "would_form_query_memory_rate": sum(
            bool(row.get("would_form_query_memory")) for row in rows
        ) / len(rows) if rows else 0.0,
        "prior_query_memory_top5_rate": sum(
            any(
                memory_id.startswith("QUERY_MEMORY::")
                for memory_id in row["ranked_memory_ids"][:5]
            )
            for row in rows
        ) / len(rows) if rows else 0.0,
        "latency": {
            stage: _latency([float(row["stages_ms"][stage]) for row in rows])
            for stage in ("observation", "knowledge", "retrieval", "total")
        },
        "by_origin": {
            origin: retrieval_summary([row for row in rows if row["dataset_origin"] == origin])
            for origin in sorted({str(row["dataset_origin"]) for row in rows})
        } if len({str(row["dataset_origin"]) for row in rows}) > 1 else {},
    }


def select_examples(
    rows: Sequence[Mapping[str, Any]],
    *,
    count: int,
) -> list[Mapping[str, Any]]:
    specifications = (
        ("single_memory", "v3.1", True),
        ("dialogue_log_complementary", "v5.3", True),
        ("multi_task_cross_app", "v5.3", True),
        ("conflict_resolution", "v5.3", True),
        ("clarification_required", "v5.3", None),
        ("operation_resume_only", "v5.3", True),
        ("dialogue_context_only", "v5.3", True),
        ("dialogue_log_complementary", "v5.3", False),
    )
    selected: list[Mapping[str, Any]] = []
    groups: set[str] = set()
    for track, origin, success in specifications:
        candidates = [
            row
            for row in rows
            if row["evaluation_track"] == track
            and row["dataset_origin"] == origin
            and row["answer_group_id"] not in groups
        ]
        preferred = []
        for row in candidates:
            complete = set(row["required_memory_ids"]) <= set(
                row["ranked_memory_ids"][:8]
            )
            if success is None or complete == success:
                preferred.append(row)
        for row in (*preferred, *candidates):
            if row["evaluation_track"] != track or row["dataset_origin"] != origin:
                continue
            if row["answer_group_id"] in groups:
                continue
            selected.append(row)
            groups.add(row["answer_group_id"])
            break
        if len(selected) >= count:
            break
    if len(selected) < count:
        for row in rows:
            if row["answer_group_id"] in groups:
                continue
            selected.append(row)
            groups.add(row["answer_group_id"])
            if len(selected) >= count:
                break
    return selected[:count]


def build_api_input(row: Mapping[str, Any]) -> str:
    payload = {
        "current_context": row["current_context_text"],
        "user_input": row["query_text"],
        "query_observation": row["query_observation"],
        "retrieved_memories": row["retrieved_memories"],
        "knowledge_references": row["knowledge_references"],
    }
    return (
        "请根据下面的检索包回答用户。\n\n"
        + json.dumps(payload, ensure_ascii=False, indent=2)
    )


def _scenario_description(row: Mapping[str, Any], query: Mapping[str, str]) -> str:
    required = set(row["required_memory_ids"])
    hits = required.intersection(row["ranked_memory_ids"][:8])
    apps = "、".join(str(value) for value in _json_list(query.get("apps_involved")))
    return (
        f"{query.get('scenario_label') or query.get('scenario_id')}；"
        f"证据模式为 {query.get('evidence_mode')}，涉及 {apps or '未指定应用'}。"
        f"运行后检查：Top-8 命中 {len(hits)}/{len(required)} 个必需记忆。"
    )


def _judge_input(
    row: Mapping[str, Any],
    answer: str,
    answer_key: Mapping[str, str],
) -> str:
    return json.dumps(
        {
            "query": row["query_text"],
            "decision_class": answer_key.get("decision_class"),
            "expected_conclusion": answer_key.get("expected_conclusion"),
            "reference_agent_response": answer_key.get("reference_agent_response"),
            "scoring_rubric": answer_key.get("scoring_rubric_text"),
            "answer": answer,
            "knowledge_references": row["knowledge_references"],
        },
        ensure_ascii=False,
        indent=2,
    )


def run_api_examples(
    rows: Sequence[Mapping[str, Any]],
    *,
    query_by_id: Mapping[str, Mapping[str, str]],
    answer_by_group: Mapping[str, Mapping[str, str]],
    client: DeepSeekReflectionClient,
) -> list[dict[str, Any]]:
    output = []
    for row in rows:
        api_input = build_api_input(row)
        response = client.complete_json(
            system_markdown=ANSWER_SYSTEM,
            user_markdown=api_input,
            task_name=f"official_1000_answer:{row['query_id']}",
        )
        answer = str(response.get("answer") or "").strip()
        answer_key = answer_by_group[row["answer_group_id"]]
        judge = client.complete_json(
            system_markdown=JUDGE_SYSTEM,
            user_markdown=_judge_input(row, answer, answer_key),
            task_name=f"official_1000_judge:{row['query_id']}",
        )
        output.append(
            {
                "query_id": row["query_id"],
                "evaluation_track": row["evaluation_track"],
                "query_type": row["query_type"],
                "scenario_description": _scenario_description(
                    row, query_by_id[row["query_id"]]
                ),
                "user_input": row["query_text"],
                "selected_memory_ids": row["ranked_memory_ids"][:8],
                "api_system": ANSWER_SYSTEM,
                "api_input": api_input,
                "api_answer": answer,
                "judge": judge,
            }
        )
    return output


def _api_summary(examples: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    content = [float(value["judge"]["content_score_10"]) for value in examples]
    grounded = [float(value["judge"]["groundedness_score_10"]) for value in examples]
    return {
        "example_count": len(examples),
        "decision_correct_count": sum(
            bool(value["judge"]["decision_correct"]) for value in examples
        ),
        "mean_content_score_10": statistics.fmean(content) if content else 0.0,
        "mean_groundedness_score_10": statistics.fmean(grounded) if grounded else 0.0,
        "knowledge_helpful_count": sum(
            bool(value["judge"]["knowledge_helpful"]) for value in examples
        ),
    }


def render_markdown(
    examples: Sequence[Mapping[str, Any]],
    summary: Mapping[str, Any],
) -> str:
    lines = [
        "# 记忆与知识库完整链路样例",
        "",
        "本文件来自服务器实际运行。场景描述在 API 回答完成后补充，不属于模型输入；",
        "知识库返回的是通用标签，不视为用户记忆。",
        "",
        "## 汇总",
        "",
        "```json",
        json.dumps(summary, ensure_ascii=False, indent=2),
        "```",
    ]
    for index, example in enumerate(examples, 1):
        lines.extend(
            [
                "",
                f"## 样例 {index}：{example['evaluation_track']} / {example['query_type']}",
                "",
                "### 场景描述（运行后补充）",
                "",
                example["scenario_description"],
                "",
                "### 用户输入",
                "",
                example["user_input"],
                "",
                "### 最终发送给 API 的文本",
                "",
                "```text",
                example["api_input"],
                "```",
                "",
                "### API 回答",
                "",
                example["api_answer"],
                "",
                "### 独立评审",
                "",
                "```json",
                json.dumps(example["judge"], ensure_ascii=False, indent=2),
                "```",
            ]
        )
    return "\n".join(lines) + "\n"


def _dataset_fingerprint(data_root: Path) -> str:
    digest = hashlib.sha256()
    for name in (
        "query_set.csv",
        "answer_key.csv",
        "precedent_inputs.ndjson.gz",
    ):
        path = data_root / name
        digest.update(name.encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--markdown", type=Path, default=DEFAULT_MARKDOWN)
    parser.add_argument(
        "--state-database", type=Path, default=DEFAULT_STATE_DATABASE
    )
    parser.add_argument("--sample-count", type=int, default=8)
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument("--limit", type=int)
    parser.add_argument(
        "--query-mode",
        choices=("dynamic", "static"),
        default="dynamic",
    )
    parser.add_argument("--skip-api", action="store_true")
    args = parser.parse_args()

    from src.rag.kylin_embedding_sdk import KylinTextEmbedding

    data_root = args.dataset / "processed_data"
    query_rows = _read_csv(data_root / "query_set.csv")
    precedent_rows = _read_ndjson_gz(data_root / "precedent_inputs.ndjson.gz")
    answer_rows = _read_csv(data_root / "answer_key.csv")
    query_by_id = {row["query_id"]: row for row in query_rows}
    answer_by_group = {row["answer_group_id"]: row for row in answer_rows}

    memories, evidence_to_memory, formation = form_memories(precedent_rows)
    store = PersistentEvaluationStore(
        args.state_database,
        dataset_fingerprint=_dataset_fingerprint(data_root),
    )
    knowledge = WorkplaceTagKnowledgeBase(args.database)
    initialized = time.perf_counter()
    matcher = ObservationMatcher(
        KylinTextEmbedding(),
        tokenizer=JiebaSpanTokenizer(),
        knowledge_base=knowledge,
        knowledge_top_k_per_group=12,
        min_frame_confidence=0.82,
    )
    existing_memory_ids = store.memory_ids()
    seed_embedding_latencies = []
    for memory in memories:
        if memory["memory_id"] in existing_memory_ids:
            continue
        embedded = time.perf_counter()
        vector = matcher.embedder.embed([_semantic_fragment(memory)])[0]
        seed_embedding_latencies.append(
            (time.perf_counter() - embedded) * 1000.0
        )
        store.upsert_seed_memory(memory, vector)
    runtime_memories, vectors_by_memory = store.load_memories()
    formed_by_id = {memory["memory_id"]: memory for memory in memories}
    runtime_memories = [
        {
            **memory,
            "precedent_case_ids": list(
                formed_by_id.get(memory["memory_id"], memory).get(
                    "precedent_case_ids", ()
                )
            ),
        }
        for memory in runtime_memories
    ]
    if args.query_mode == "static":
        runtime_memories = [
            memory
            for memory in runtime_memories
            if memory["memory_kind"] != "query_observation"
        ]
        retained_ids = {memory["memory_id"] for memory in runtime_memories}
        vectors_by_memory = {
            memory_id: vector
            for memory_id, vector in vectors_by_memory.items()
            if memory_id in retained_ids
        }
    retriever = EpisodeHybridRetriever(
        runtime_memories,
        tokenizer=JiebaIdentifierTokenizer(),
        embedder=matcher.embedder,
        vectors_by_memory=vectors_by_memory,
    )
    initialization_ms = (time.perf_counter() - initialized) * 1000.0
    processed = (
        store.processed_sequence_numbers()
        if args.query_mode == "dynamic"
        else set()
    )
    batch_size = args.limit if args.limit is not None else args.batch_size
    pending_rows = [
        row for row in query_rows if int(row["sequence_no"]) not in processed
    ][:batch_size]
    batch_rows = run_queries(
        pending_rows,
        matcher=matcher,
        retriever=retriever,
        knowledge=knowledge,
        evidence_to_memory=evidence_to_memory,
        store=store if args.query_mode == "dynamic" else None,
        persist_queries=args.query_mode == "dynamic",
        isolate_precedent_case=args.query_mode == "static",
    )
    rows = (
        store.query_results()
        if args.query_mode == "dynamic"
        else batch_rows
    )
    quality = retrieval_summary(rows)

    selected = select_examples(
        batch_rows, count=min(10, max(5, args.sample_count))
    )
    client = None
    examples: list[dict[str, Any]] = []
    if not args.skip_api:
        client = DeepSeekReflectionClient(max_tokens=2500)
        examples = run_api_examples(
            selected,
            query_by_id=query_by_id,
            answer_by_group=answer_by_group,
            client=client,
        )
    api_summary = _api_summary(examples)
    summary = {
        "dataset": {
            "precedent_bundle_count": len(precedent_rows),
            "query_count": len(query_rows),
            "batch_query_count": len(batch_rows),
            "batch_sequence_start": (
                batch_rows[0]["sequence_no"] if batch_rows else None
            ),
            "batch_sequence_end": (
                batch_rows[-1]["sequence_no"] if batch_rows else None
            ),
            "cumulative_processed_query_count": len(rows),
            "query_mode": args.query_mode,
        },
        "knowledge": knowledge.statistics(),
        "formation": formation,
        "persistent_state": {
            **store.statistics(),
            "modified_by_this_run": args.query_mode == "dynamic",
        },
        "retriever_initialization_ms": initialization_ms,
        "new_seed_embedding_latency": _latency(seed_embedding_latencies),
        "retriever_fragment_count": retriever.fragment_count,
        "retrieval": quality,
        "api_examples": api_summary,
        "api_call_latency": _latency(
            [
                float(value["elapsed_ms"])
                for value in (client.calls if client else [])
                if value.get("status") == "ok"
            ]
        ),
    }
    output = {
        "purpose": (
            "Formal 1000-record full-chain evaluation: structured memory "
            "formation, transient Observation, BM25 plus embedding retrieval, "
            "knowledge return, and real API answers."
        ),
        "contract": {
            "retrieval_algorithm_changed_for_this_evaluation": False,
            "answer_labels_used_for_retrieval_or_generation": False,
            "answer_labels_used_for_post_generation_judging": True,
            "queries_persisted_as_memories": (
                "after their own retrieval when a valid Observation frame forms"
                if args.query_mode == "dynamic"
                else False
            ),
            "all_queries_persisted_as_observation_events": (
                args.query_mode == "dynamic"
            ),
            "state_database_reused_without_cleanup": (
                args.query_mode == "dynamic"
            ),
            "knowledge_is_user_memory": False,
            "scene_description_added_after_api": True,
        },
        "summary": summary,
        "formed_seed_memories": memories,
        "batch_rows": batch_rows,
        "rows": rows,
        "examples": examples,
        "api_calls": client.calls if client else [],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(output, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    args.markdown.parent.mkdir(parents=True, exist_ok=True)
    args.markdown.write_text(
        render_markdown(examples, summary), encoding="utf-8"
    )
    store.close()
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
