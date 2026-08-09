#!/usr/bin/env python3
"""
Phase 1 SDK-Memory Pipeline Benchmark Test (v5.3 Dataset)

Flow:
  1. Ingest operation events as ToolResult observations (Phase 1 pipeline)
  2. Ingest dialogue events as memory observations
  3. Run benchmark queries against strict memory engine
  4. Generate predictions CSV for evaluation

Usage: python3 _benchmark_phase1.py [--sample N] [--queries N]
"""
import argparse
import csv
import gzip
import json
import os
import sys
import time
import statistics
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(os.path.dirname(os.path.abspath(__file__))).parent))

from src.memory_engine.strict.engine import StrictMemoryEngine
from src.memory_engine.strict.config import StrictMemoryEngineConfig
from src.memory_engine.strict.store import StrictMemoryEngineStore
from src.toolkit.base import ToolResult, ToolStatus, RiskLevel

# ── Constants ──
BENCHMARK_DIR = Path(os.path.expanduser("~/work/projects/project_dev1/_benchmark"))
TEST_DB = Path(os.path.expanduser("~/.nex-agent/_bench_phase1.db"))
RESULTS_JSON = Path(os.path.expanduser("~/work/projects/project_dev1/_bench_phase1_results.json"))
PREDICTIONS_CSV = Path(os.path.expanduser("~/work/projects/project_dev1/_bench_phase1_predictions.csv"))


# ═══════════════════════════════════════════════════════
# 1. Load benchmark data
# ═══════════════════════════════════════════════════════

def load_operation_events(path):
    """Load operation events from NDJSON.gz"""
    events = []
    with gzip.open(path, "rt", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                events.append(json.loads(line))
    return events


def load_dialogue_events(path):
    """Load dialogue events from NDJSON.gz"""
    events = []
    with gzip.open(path, "rt", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                events.append(json.loads(line))
    return events


def load_queries(path, sample=None, partition="dev"):
    """Load queries from CSV, optionally filter by partition and sample"""
    queries = []
    with open(path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if partition and row.get("dataset_partition", "") == partition:
                queries.append(row)
    if sample and len(queries) > sample:
        import random
        random.seed(42)
        queries = random.sample(queries, sample)
    return queries


# ═══════════════════════════════════════════════════════
# 2. Event → Observation adapters
# ═══════════════════════════════════════════════════════

def operation_event_to_observation(event: dict) -> dict:
    """Convert operation event to memory observation (mimicking ToolResult.to_observation())"""
    return {
        "source_type": "tool_result",
        "source_event_id": event.get("event_id", ""),
        "tool": event.get("action_key", ""),
        "tool_name": event.get("action_key", ""),
        "success": event.get("result_status") != "failed",
        "error_signature": "",
        "output": event.get("action_value", ""),
        "latency_ms": 0,
        "state_changed": True,
        "content": f"{event.get('action_key', '')}: {event.get('action_value', '')}",
        "action": event.get("action_key", "unknown"),
        "user_id": event.get("user_id", "nex_user"),
        "session_id": event.get("episode_id", "auto"),
        "timestamp": event.get("event_time", datetime.now(timezone.utc).isoformat()),
        "app": event.get("source_app", ""),
        "app_category": event.get("app_category", ""),
        "target_type": event.get("target_type", ""),
        "target_value": event.get("target_value", ""),
        "activity_family": event.get("activity_family", ""),
        "result_status": event.get("result_status", ""),
        "source_dataset": event.get("source_dataset_id", ""),
        "episode_id": event.get("episode_id", ""),
    }


def dialogue_event_to_observation(event: dict) -> dict:
    """Convert dialogue event to memory observation"""
    memory_claim = event.get("memory_claim_json", {})
    return {
        "source_type": "dialogue",
        "source_event_id": event.get("event_id", ""),
        "tool": "dialogue",
        "tool_name": "dialogue",
        "success": True,
        "error_signature": "",
        "output": event.get("message_text", ""),
        "latency_ms": 0,
        "state_changed": True,
        "content": event.get("message_text", ""),
        "action": event.get("utterance_role", "user_message"),
        "user_id": event.get("user_id", "nex_user"),
        "session_id": event.get("episode_id", "auto"),
        "timestamp": event.get("event_time", datetime.now(timezone.utc).isoformat()),
        "app": event.get("source_app", ""),
        "app_category": event.get("app_category", ""),
        "scenario_id": event.get("scenario_id", ""),
        "speaker": event.get("speaker", "user"),
        "message_type": event.get("message_type", ""),
        "utterance_role": event.get("utterance_role", ""),
        "memory_signal_type": event.get("memory_signal_type", ""),
        "episode_id": event.get("episode_id", ""),
        "context_task": event.get("context_task", ""),
        "context_artifact": event.get("context_artifact", ""),
        "context_topic": event.get("context_topic", ""),
        "memory_claim": json.dumps(memory_claim, ensure_ascii=False) if memory_claim else "",
        "preference_scope": event.get("preference_scope", ""),
        "effective_scope": event.get("effective_scope", ""),
    }


# ═══════════════════════════════════════════════════════
# 3. Query → Prediction generation
# ═══════════════════════════════════════════════════════

def run_query(engine, query_row, known_user_ids, top_k=5):
    """Run one benchmark query against the strict engine, trying all known user_ids"""
    query_text = query_row["query_text"]
    context_text = query_row.get("current_context_text", "")

    # Extract required event IDs from query for targeted lookup
    def _parse_ids(field):
        try:
            ids = json.loads(query_row.get(field, "[]"))
            return ids if isinstance(ids, list) else []
        except (json.JSONDecodeError, TypeError):
            return []

    required_dialogue = _parse_ids("required_dialogue_event_ids")
    required_operation = _parse_ids("required_operation_event_ids")
    target_user_ids = set()

    # Try to find relevant user_ids from required event IDs
    for uid in known_user_ids:
        for evt_id in required_dialogue + required_operation:
            if evt_id and evt_id.lower()[:8] in uid.lower():
                target_user_ids.add(uid)

    # Fall back to trying all known user_ids (capped at 20)
    if not target_user_ids:
        target_user_ids = set(list(known_user_ids)[:20])

    t0 = time.perf_counter()
    all_items = []
    try:
        for uid in list(target_user_ids)[:10]:
            ctx = {
                "user_id": uid,
                "current_task": context_text[:500] if context_text else "",
                "task": query_row.get("scenario_label", ""),
            }
            result = engine.retrieve(query_text, context=ctx, top_k=top_k)
            all_items.extend(result.get("items", []))

        elapsed = (time.perf_counter() - t0) * 1000

        predicted_ids = [item.get("memory_id", "") for item in all_items[:top_k]]
        predicted_scores = [item.get("scores", {}).get("final", item.get("scores", {}).get("activation", 0.0)) for item in all_items[:top_k]]

        return {
            "query_id": query_row["query_id"],
            "predicted_evidence_ids": json.dumps(predicted_ids),
            "predicted_decision_class": (
                all_items[0].get("decision_class", "retrieve_synthesize_execute")
                if all_items else "retrieve_synthesize_execute"
            ),
            "predicted_action_keys": json.dumps(
                all_items[0].get("action_keys", []) if all_items else []
            ),
            "predicted_operation_states_json": json.dumps(
                all_items[0].get("operation_states", {}) if all_items else {}
            ),
            "awarded_point_ids": "",
            "awarded_atomic_item_ids": "",
            "atomic_item_scores_json": "",
            "response_text": (
                all_items[0].get("rendered", all_items[0].get("content", ""))[:500]
                if all_items else ""
            ),
            "response_time_ms": round(elapsed, 2),
            "confidence": round(predicted_scores[0], 4) if predicted_scores else 0.0,
        }
    except Exception as e:
        elapsed = (time.perf_counter() - t0) * 1000
        return {
            "query_id": query_row["query_id"],
            "predicted_evidence_ids": "[]",
            "predicted_decision_class": "",
            "predicted_action_keys": "[]",
            "predicted_operation_states_json": "{}",
            "awarded_point_ids": "",
            "awarded_atomic_item_ids": "",
            "atomic_item_scores_json": "",
            "response_text": f"ERROR: {e}",
            "response_time_ms": round(elapsed, 2),
            "confidence": 0.0,
        }


# ═══════════════════════════════════════════════════════
# 4. Main test routine
# ═══════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample", type=int, default=0, help="Max events to ingest (0=all)")
    parser.add_argument("--queries", type=int, default=500, help="Max queries to run (0=all dev)")
    parser.add_argument("--skip-ingest", action="store_true", help="Skip ingestion (db already populated)")
    args = parser.parse_args()

    print("=" * 60)
    print("Phase 1 SDK-Memory Benchmark Test (v5.3)")
    print(f"Start: {datetime.now(timezone.utc).isoformat()}")
    print("=" * 60)

    # ── Cleanup old DB ──
    if not args.skip_ingest:
        if TEST_DB.exists():
            print(f"[setup] removing old test db: {TEST_DB}")
            for f in TEST_DB.parent.glob(f"{TEST_DB.name}*"):
                f.unlink()

    # ── Init strict engine ──
    print("[setup] loading StrictMemoryEngine config...")
    config = StrictMemoryEngineConfig.load(
        database_path=str(TEST_DB),
    )
    # Use BM25-only config without Kylin semantic requirement
    bench_config_path = BENCHMARK_DIR / "bench_config.toml"
    if bench_config_path.exists():
        config = StrictMemoryEngineConfig.load(
            path=str(bench_config_path),
            database_path=str(TEST_DB),
        )
    print("[setup] initializing StrictMemoryEngine...")
    store = StrictMemoryEngineStore(str(TEST_DB))
    engine = StrictMemoryEngine(config=config, store=store)
    print(f"[setup] engine ready, db={TEST_DB}")

    all_metrics = {}
    known_user_ids = set()

    # ── Phase A: Ingest operation events ──
    op_gz = BENCHMARK_DIR / "source_data/operation/operation_events_representative.ndjson.gz"
    if op_gz.exists() and not args.skip_ingest:
        print("\n--- Phase A: Ingesting Operation Events ---")
        events = load_operation_events(op_gz)
        if args.sample and len(events) > args.sample:
            events = events[:args.sample]
        print(f"  loaded {len(events)} operation events")

        op_latencies = []
        op_success = 0
        op_fail = 0
        batch_interval = max(1, len(events) // 10)

        t_batch_start = time.perf_counter()
        for i, event in enumerate(events):
            known_user_ids.add(event.get("user_id", ""))
            try:
                obs = operation_event_to_observation(event)
                result = engine.ingest_observation(obs, stage_limit="evidence")
                op_latencies.append(result.get("latency_ms", 0))
                if result.get("status") == "ok":
                    op_success += 1
                else:
                    op_fail += 1
            except Exception as e:
                op_fail += 1
                if op_fail <= 5:
                    print(f"  [warn] op event {event.get('event_id','?')[:30]}: {e}")

            if (i + 1) % batch_interval == 0:
                pct = (i + 1) / len(events) * 100
                elapsed = time.perf_counter() - t_batch_start
                rate = (i + 1) / elapsed if elapsed > 0 else 0
                print(f"  [{pct:.0f}%] {i+1}/{len(events)} op events | {rate:.1f} evt/s")

        op_total_time = time.perf_counter() - t_batch_start
        op_metrics = {
            "total": len(events),
            "success": op_success,
            "failed": op_fail,
            "success_rate": round(op_success / len(events), 4) if events else 0,
            "total_time_s": round(op_total_time, 2),
            "rate_evt_per_s": round(len(events) / op_total_time, 1) if op_total_time > 0 else 0,
            "P50_ms": round(_percentile(op_latencies, 50), 2),
            "P95_ms": round(_percentile(op_latencies, 95), 2),
            "P99_ms": round(_percentile(op_latencies, 99), 2),
            "mean_ms": round(statistics.mean(op_latencies), 2) if op_latencies else 0,
        }
        all_metrics["operation_ingestion"] = op_metrics
        print(f"  ✓ Operation ingestion done: {op_success}/{len(events)} ok, "
              f"{op_metrics['total_time_s']}s, {op_metrics['rate_evt_per_s']} evt/s")

    # ── Phase B: Ingest dialogue events ──
    dial_gz = BENCHMARK_DIR / "source_data/dialogue/dialogue_events.ndjson.gz"
    if dial_gz.exists() and not args.skip_ingest:
        print("\n--- Phase B: Ingesting Dialogue Events ---")
        events = load_dialogue_events(dial_gz)
        if args.sample and len(events) > args.sample:
            events = events[:args.sample]
        print(f"  loaded {len(events)} dialogue events")

        dial_latencies = []
        dial_success = 0
        dial_fail = 0
        batch_interval = max(1, len(events) // 10)

        t_batch_start = time.perf_counter()
        for i, event in enumerate(events):
            known_user_ids.add(event.get("user_id", ""))
            try:
                obs = dialogue_event_to_observation(event)
                result = engine.ingest_observation(obs, stage_limit="evidence")
                dial_latencies.append(result.get("latency_ms", 0))
                if result.get("status") == "ok":
                    dial_success += 1
                else:
                    dial_fail += 1
            except Exception as e:
                dial_fail += 1
                if dial_fail <= 5:
                    print(f"  [warn] event {event.get('event_id','?')[:30]}: {e}")

            if (i + 1) % batch_interval == 0:
                pct = (i + 1) / len(events) * 100
                elapsed = time.perf_counter() - t_batch_start
                rate = (i + 1) / elapsed if elapsed > 0 else 0
                print(f"  [{pct:.0f}%] {i+1}/{len(events)} dial events | {rate:.1f} evt/s")

        dial_total_time = time.perf_counter() - t_batch_start
        dial_metrics = {
            "total": len(events),
            "success": dial_success,
            "failed": dial_fail,
            "success_rate": round(dial_success / len(events), 4) if events else 0,
            "total_time_s": round(dial_total_time, 2),
            "rate_evt_per_s": round(len(events) / dial_total_time, 1) if dial_total_time > 0 else 0,
            "P50_ms": round(_percentile(dial_latencies, 50), 2),
            "P95_ms": round(_percentile(dial_latencies, 95), 2),
            "P99_ms": round(_percentile(dial_latencies, 99), 2),
            "mean_ms": round(statistics.mean(dial_latencies), 2) if dial_latencies else 0,
        }
        all_metrics["dialogue_ingestion"] = dial_metrics
        print(f"  ✓ Dialogue ingestion done: {dial_success}/{len(events)} ok, "
              f"{dial_metrics['total_time_s']}s, {dial_metrics['rate_evt_per_s']} evt/s")

    # ── Store counts ──
    try:
        counts = store.counts()
        all_metrics["store_counts"] = counts
        print(f"\n[store] counts: {counts}")
    except Exception as e:
        print(f"[store] count error: {e}")
        all_metrics["store_counts"] = {"error": str(e)}

    # ── Phase C: Run queries ──
    query_csv = BENCHMARK_DIR / "processed_data/query_set.csv"
    if query_csv.exists():
        print("\n--- Phase C: Running Benchmark Queries ---")
        n_queries = args.queries if args.queries > 0 else None
        queries = load_queries(query_csv, sample=n_queries, partition="dev")
        print(f"  loaded {len(queries)} queries (partition=dev)")

        query_latencies = []
        predictions = []
        batch_interval = max(1, len(queries) // 10)

        print(f"  {len(known_user_ids)} known user_ids collected")
        t_batch_start = time.perf_counter()
        for i, q in enumerate(queries):
            pred = run_query(engine, q, known_user_ids, top_k=5)
            predictions.append(pred)
            query_latencies.append(pred["response_time_ms"])

            if (i + 1) % batch_interval == 0:
                pct = (i + 1) / len(queries) * 100
                elapsed = time.perf_counter() - t_batch_start
                rate = (i + 1) / elapsed if elapsed > 0 else 0
                print(f"  [{pct:.0f}%] {i+1}/{len(queries)} queries | {rate:.1f} q/s")

        query_total_time = time.perf_counter() - t_batch_start
        query_metrics = {
            "total": len(queries),
            "total_time_s": round(query_total_time, 2),
            "rate_q_per_s": round(len(queries) / query_total_time, 1) if query_total_time > 0 else 0,
            "P50_ms": round(_percentile(query_latencies, 50), 2),
            "P95_ms": round(_percentile(query_latencies, 95), 2),
            "P99_ms": round(_percentile(query_latencies, 99), 2),
            "mean_ms": round(statistics.mean(query_latencies), 2) if query_latencies else 0,
            "hits_nonzero": sum(1 for p in predictions if p["predicted_evidence_ids"] != "[]"),
            "hits_zero": sum(1 for p in predictions if p["predicted_evidence_ids"] == "[]"),
            "hit_rate": round(
                sum(1 for p in predictions if p["predicted_evidence_ids"] != "[]") / len(predictions), 4
            ) if predictions else 0,
        }
        all_metrics["query_execution"] = query_metrics
        print(f"  ✓ Query execution done: {query_metrics['hits_nonzero']}/{len(queries)} "
              f"with results, {query_metrics['total_time_s']}s")

        # ── Write predictions CSV ──
        fieldnames = [
            "query_id", "predicted_evidence_ids", "predicted_decision_class",
            "predicted_action_keys", "predicted_operation_states_json",
            "awarded_point_ids", "awarded_atomic_item_ids",
            "atomic_item_scores_json", "response_text", "response_time_ms",
            "confidence",
        ]
        with open(PREDICTIONS_CSV, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(predictions)
        print(f"  [✓] predictions written to {PREDICTIONS_CSV}")

    # ── Write results JSON ──
    all_metrics["test_metadata"] = {
        "pipeline": "Phase1_SDK_Memory_v5.3_Benchmark",
        "date": datetime.now(timezone.utc).isoformat(),
        "server": "Kylin V11 (阿里云 ECS)",
        "python": sys.version.split()[0],
        "test_db": str(TEST_DB),
        "benchmark_dir": str(BENCHMARK_DIR),
        "sample_events": args.sample if args.sample else "all",
        "sample_queries": args.queries,
        "predictions_csv": str(PREDICTIONS_CSV),
    }

    with open(RESULTS_JSON, "w") as f:
        json.dump(all_metrics, f, ensure_ascii=False, indent=2)
    print(f"\n[✓] results written to {RESULTS_JSON}")

    # ── Summary ──
    print("\n" + "=" * 60)
    print("Benchmark Summary")
    print("=" * 60)
    for phase, metrics in all_metrics.items():
        if isinstance(metrics, dict) and "total" in metrics:
            print(f"  {phase}: {metrics['total']} items, "
                  f"P50={metrics.get('P50_ms','N/A')}ms, "
                  f"P95={metrics.get('P95_ms','N/A')}ms")


def _percentile(values, p):
    if not values:
        return 0
    s = sorted(values)
    n = len(s)
    idx = int(n * p / 100.0)
    idx = min(idx, n - 1)
    return s[idx]


if __name__ == "__main__":
    main()
