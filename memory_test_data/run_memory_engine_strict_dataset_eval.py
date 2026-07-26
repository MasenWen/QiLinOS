from __future__ import annotations

import argparse
import csv
import json
import shutil
import statistics
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from time import perf_counter
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
DATASET_TIMEZONE = timezone(timedelta(hours=8))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.memory_engine.strict.config import StrictMemoryEngineConfig
from src.memory_engine.strict.engine import StrictMemoryEngine
from src.memory_engine.strict.kylin import KylinSDKSemanticScorer
from src.memory_engine.strict.store import StrictMemoryEngineStore


class ZeroSemanticScorer:
    backend_id = "lexical_zero_test_only"

    def score(self, query: str, memories: list[Any]) -> dict[str, float]:
        return {memory.memory_id: 0.0 for memory in memories}


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def event_payload(row: dict[str, str], sequence_no: int) -> dict[str, Any]:
    detail = row["detail"].strip()
    object_name = row["object"].strip()
    content = detail
    if object_name and object_name.casefold() not in detail.casefold():
        content = f"{detail} 对象：{object_name}"
    context = {
        "scene": row["scene"],
        "app": row["app"],
        "dataset_task_id": row["related_task_id"],
        "event_type": row["event_type"],
    }
    activity = activity_hint(
        f"{detail} {object_name}",
        action=row["action"],
    )
    if activity:
        context["activity"] = activity
    common = {
        "source_event_id": row["event_id"],
        "user_id": row["user_id"],
        "session_id": row["session_id"],
        "sequence_no": sequence_no,
        "event_time": datetime.strptime(
            row["timestamp"],
            "%Y-%m-%d %H:%M:%S",
        )
        .replace(tzinfo=DATASET_TIMEZONE)
        .isoformat(),
        "content": content,
        "task": row["scene"],
        "app": row["app"],
        "context": context,
        "artifact_refs": [object_name] if object_name else [],
        "raw_source_ref": f"user_event_log.csv:{row['event_id']}",
    }
    if row["event_type"] == "preference_statement":
        return {
            **common,
            "source_type": "dialogue",
            "actor": "user",
        }
    return {
        **common,
        "source_type": "gui_action",
        "action": row["action"],
        "target": object_name,
    }


def query_context(row: dict[str, str]) -> dict[str, Any]:
    activity = activity_hint(
        " ".join(
            (
                row["query_text"],
                row["current_task"],
                row["current_goal"],
                row["memory_need"],
            )
        )
    )
    condition = {
        "scene": row["scene"],
        "app": row["app"],
    }
    if activity:
        condition["activity"] = activity
    return {
        "user_id": row["user_id"],
        "query_time": datetime.strptime(
            row["query_time"],
            "%Y-%m-%d %H:%M:%S",
        )
        .replace(tzinfo=DATASET_TIMEZONE)
        .isoformat(),
        "task": row["scene"],
        "goal": row["current_goal"],
        "memory_need": row["memory_need"],
        "scene": row["scene"],
        "app": row["app"],
        "condition": condition,
    }


def activity_hint(text: str, *, action: str = "") -> str:
    lowered = f"{action} {text}".casefold()
    if any(
        marker in lowered
        for marker in (
            "财务汇总",
            "部门预算",
            "finance_summary",
            "finance summary",
            "department budget",
        )
    ):
        return "finance_summary"
    if any(
        marker in lowered
        for marker in (
            "销售趋势",
            "销售数据",
            "sales trend",
            "sales_report",
        )
    ):
        return "sales_trend"
    return ""


def source_event_ids_for_item(
    item: dict[str, Any],
    *,
    evidence_by_id: dict[str, Any],
    observation_by_id: dict[str, Any],
) -> tuple[set[str], set[str]]:
    source_event_ids: set[str] = set()
    evidence_types: set[str] = set()
    for evidence_id in item["lineage"]["evidence_ids"]:
        evidence = evidence_by_id.get(evidence_id)
        if evidence is None:
            continue
        evidence_types.add(evidence.evidence_type)
        for observation_id in evidence.source_observation_ids:
            observation = observation_by_id.get(observation_id)
            if observation is not None:
                source_event_ids.add(observation.source_event_id)
    return source_event_ids, evidence_types


def category_compatible(
    target_type: str,
    target_category: str,
    item: dict[str, Any],
    evidence_types: set[str],
) -> bool:
    scoped = item["memory_id"].startswith("scoped-")
    if target_type == "short_term" and not scoped:
        return False
    if target_type == "mid_term" and scoped:
        return False
    if target_category == "current_context":
        return "current_context" in evidence_types
    if target_category == "task_state":
        return "task_state" in evidence_types
    if target_category == "temporary_preference":
        return scoped and bool(
            evidence_types
            & {
                "explicit_preference",
                "output_style",
                "explicit_safety",
                "template_reuse",
            }
        )
    return "observed_behavior" in evidence_types


def expected_event_ids(
    acceptable_memory_ids: Iterable[str],
    ground_truth: dict[str, dict[str, str]],
) -> set[str]:
    result: set[str] = set()
    for memory_id in acceptable_memory_ids:
        memory = ground_truth.get(memory_id)
        if memory is not None:
            result.update(
                item
                for item in memory["evidence_event_ids"].split("|")
                if item
            )
    return result


def rank_query(
    row: dict[str, str],
    expected: dict[str, str],
    result: dict[str, Any],
    *,
    ground_truth: dict[str, dict[str, str]],
    evidence_by_id: dict[str, Any],
    observation_by_id: dict[str, Any],
) -> tuple[int | None, list[dict[str, Any]]]:
    acceptable = [
        item
        for item in expected["acceptable_memory_ids"].split("|")
        if item
    ]
    if not acceptable:
        acceptable = [expected["expected_memory_id"]]
    expected_events = expected_event_ids(acceptable, ground_truth)
    item_audit: list[dict[str, Any]] = []
    hit_rank: int | None = None
    for rank, item in enumerate(result["items"], start=1):
        source_events, evidence_types = source_event_ids_for_item(
            item,
            evidence_by_id=evidence_by_id,
            observation_by_id=observation_by_id,
        )
        compatible = category_compatible(
            row["target_memory_type"],
            row["target_memory_category"],
            item,
            evidence_types,
        )
        lineage_match = bool(source_events & expected_events)
        if hit_rank is None and compatible and lineage_match:
            hit_rank = rank
        item_audit.append(
            {
                "rank": rank,
                "memory_id": item["memory_id"],
                "decision": item["decision"],
                "semantic_value": item["semantic_value"],
                "evidence_types": sorted(evidence_types),
                "source_event_ids": sorted(source_events),
                "category_compatible": compatible,
                "lineage_match": lineage_match,
                "activation": item["scores"]["activation"]["total"],
                "kylin_semantic": item["scores"]["kylin_semantic"],
            }
        )
    return hit_rank, item_audit


def percentile_95(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int(0.95 * len(ordered)) - 1))
    return ordered[index]


def metric_block(rows: list[dict[str, Any]]) -> dict[str, Any]:
    scored = [row for row in rows if row["scored"]]
    total = len(scored)
    return {
        "queries": total,
        "hit_at_1": (
            sum(row["hit_rank"] == 1 for row in scored) / total
            if total
            else 0.0
        ),
        "hit_at_3": (
            sum(
                row["hit_rank"] is not None and row["hit_rank"] <= 3
                for row in scored
            )
            / total
            if total
            else 0.0
        ),
        "hit_at_5": (
            sum(
                row["hit_rank"] is not None and row["hit_rank"] <= 5
                for row in scored
            )
            / total
            if total
            else 0.0
        ),
        "mrr": (
            sum(
                1.0 / row["hit_rank"]
                for row in scored
                if row["hit_rank"] is not None
            )
            / total
            if total
            else 0.0
        ),
    }


def run(
    dataset_dir: Path,
    output_dir: Path,
    *,
    top_k: int,
    semantic_backend: str,
    reuse_database: Path | None = None,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=False)
    database = output_dir / "memory_engine_strict_dataset.db"
    if reuse_database is not None:
        shutil.copy2(reuse_database, database)
    events = read_csv(dataset_dir / "user_event_log.csv")
    queries = read_csv(dataset_dir / "memory_query_set.csv")
    expected_rows = read_csv(dataset_dir / "memory_expected_results.csv")
    ground_truth_rows = read_csv(dataset_dir / "memory_ground_truth.csv")
    expected_by_query = {row["query_id"]: row for row in expected_rows}
    ground_truth = {row["memory_id"]: row for row in ground_truth_rows}

    config = StrictMemoryEngineConfig.load(database_path=database)
    store = StrictMemoryEngineStore(database)
    scorer = (
        KylinSDKSemanticScorer()
        if semantic_backend == "kylin"
        else ZeroSemanticScorer()
    )
    engine = StrictMemoryEngine(
        config=config,
        store=store,
        semantic_scorer=scorer,
    )

    sequence_by_session: Counter[tuple[str, str]] = Counter()
    ingest_failures: list[dict[str, str]] = []
    ingest_started = perf_counter()
    if reuse_database is None:
        ordered_events = sorted(
            events,
            key=lambda item: (item["timestamp"], item["event_id"]),
        )
        for event_index, row in enumerate(ordered_events, start=1):
            key = (row["user_id"], row["session_id"])
            sequence_by_session[key] += 1
            try:
                engine.ingest_observation(
                    event_payload(row, sequence_by_session[key]),
                    stage_limit="lifecycle",
                )
            except Exception as exc:
                ingest_failures.append(
                    {
                        "event_id": row["event_id"],
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )
            if event_index % 100 == 0 or event_index == len(ordered_events):
                print(
                    f"[strict-eval] imported {event_index}/{len(ordered_events)} events",
                    file=sys.stderr,
                    flush=True,
                )
    ingest_seconds = perf_counter() - ingest_started
    if ingest_failures:
        raise RuntimeError(
            f"{len(ingest_failures)} event imports failed: "
            + json.dumps(ingest_failures[:5], ensure_ascii=False)
        )

    evidence_by_id: dict[str, Any] = {}
    observation_by_id: dict[str, Any] = {}
    for user_id in sorted({row["user_id"] for row in events}):
        for evidence in store.list_evidence(user_id):
            evidence_by_id[evidence.evidence_id] = evidence
            for observation in store.get_observations(
                evidence.source_observation_ids
            ):
                observation_by_id[observation.observation_id] = observation

    result_rows: list[dict[str, Any]] = []
    misses: list[dict[str, Any]] = []
    latencies: list[float] = []
    decision_counts: Counter[str] = Counter()
    query_started = perf_counter()
    for query_index, row in enumerate(queries, start=1):
        expected = expected_by_query[row["query_id"]]
        result = engine.retrieve(
            row["query_text"],
            query_context(row),
            top_k=top_k,
        )
        latency_ms = float(result["latency_ms"])
        latencies.append(latency_ms)
        decision_counts.update(
            item["decision"] for item in result["items"]
        )
        hit_rank, item_audit = rank_query(
            row,
            expected,
            result,
            ground_truth=ground_truth,
            evidence_by_id=evidence_by_id,
            observation_by_id=observation_by_id,
        )
        scored = row["query_usage"] == "accuracy_and_latency"
        output_row = {
            "query_id": row["query_id"],
            "user_id": row["user_id"],
            "query_usage": row["query_usage"],
            "scored": scored,
            "target_memory_type": row["target_memory_type"],
            "target_memory_category": row["target_memory_category"],
            "expected_memory_id": expected["expected_memory_id"],
            "hit_rank": hit_rank,
            "hit_at_1": hit_rank == 1,
            "hit_at_3": hit_rank is not None and hit_rank <= 3,
            "hit_at_5": hit_rank is not None and hit_rank <= 5,
            "latency_ms": round(latency_ms, 4),
            "retrieved_memory_ids": "|".join(
                item["memory_id"] for item in result["items"]
            ),
            "retrieved_decisions": "|".join(
                item["decision"] for item in result["items"]
            ),
            "item_audit_json": json.dumps(item_audit, ensure_ascii=False),
        }
        result_rows.append(output_row)
        if scored and hit_rank is None:
            misses.append(output_row)
        if query_index % 25 == 0 or query_index == len(queries):
            print(
                f"[strict-eval] queried {query_index}/{len(queries)} cases",
                file=sys.stderr,
                flush=True,
            )
    query_seconds = perf_counter() - query_started

    category_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in result_rows:
        category_groups[
            f"{row['target_memory_type']}:{row['target_memory_category']}"
        ].append(row)
    summary = {
        "status": "completed",
        "dataset_dir": str(dataset_dir),
        "output_dir": str(output_dir),
        "database": str(database),
        "semantic_backend": scorer.backend_id,
        "fallback_used": False,
        "events_imported": len(events),
        "ingest_reused": reuse_database is not None,
        "reuse_database_source": (
            str(reuse_database) if reuse_database is not None else ""
        ),
        "ingest_failures": 0,
        "ingest_seconds": round(ingest_seconds, 4),
        "queries_executed": len(queries),
        "query_seconds": round(query_seconds, 4),
        "top_k": top_k,
        "official_accuracy": metric_block(result_rows),
        "by_category": {
            key: metric_block(value)
            for key, value in sorted(category_groups.items())
        },
        "latency_ms": {
            "mean": round(statistics.fmean(latencies), 4)
            if latencies
            else 0.0,
            "p95": round(percentile_95(latencies), 4),
            "max": round(max(latencies), 4) if latencies else 0.0,
        },
        "decision_counts": dict(decision_counts),
        "schema_counts": store.counts(),
        "miss_count": len(misses),
        "scoring_contract": {
            "tier_required": True,
            "category_required": True,
            "lineage_event_intersection_required": True,
            "answer_text_used_for_retrieval": False,
            "ground_truth_imported_as_memory": False,
        },
    }
    write_csv(output_dir / "strict_dataset_results.csv", result_rows)
    write_csv(output_dir / "strict_dataset_misses.csv", misses)
    (output_dir / "strict_dataset_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--dataset-dir",
        type=Path,
        default=ROOT.parent / "memory_test_data" / "memory_test_data",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT
        / ".strict_memory_engine_eval"
        / datetime.now().strftime("strict_dataset_%Y%m%d_%H%M%S"),
    )
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument(
        "--semantic-backend",
        choices=("kylin", "lexical-zero"),
        default="kylin",
    )
    parser.add_argument(
        "--reuse-database",
        type=Path,
        help="copy an existing strict lifecycle database and rerun queries only",
    )
    args = parser.parse_args()
    summary = run(
        args.dataset_dir.resolve(),
        args.output_dir.resolve(),
        top_k=args.top_k,
        semantic_backend=args.semantic_backend,
        reuse_database=(
            args.reuse_database.resolve()
            if args.reuse_database is not None
            else None
        ),
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
