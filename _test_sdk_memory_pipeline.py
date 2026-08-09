#!/usr/bin/env python3
"""
SDK → Memory Pipeline Integration Test (Phase 1)

Tests:
  1. Tool execution → observation creation via _record_to_memory
  2. Pipeline latency (P50, P95, P99) at each stage
  3. Observation → Episode → Evidence pipeline
  4. Memory retrieval recall rate

Writes results to _test_sdk_memory_results.json
"""
import asyncio
import json
import os
import sys
import time
import statistics
from datetime import datetime, timezone
from pathlib import Path

# ── Ensure project root is on path ──
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.toolkit.base import ToolRegistry, ToolResult, ToolStatus, RiskLevel, BaseTool, get_registry
from src.toolkit.executor import ClosedLoopExecutor
from src.toolkit.init_tools import init_all_tools
from src.memory_engine.engine import MemoryEngine
from src.memory_engine.normalizers import observation_from_event
from src.memory_engine.store import MemoryEngineStore


# ═══════════════════════════════════════════════════════════
# 1. Setup — register tools
# ═══════════════════════════════════════════════════════════

registry = get_registry()
init_all_tools()
tool_names = registry.list_all()
print(f"[setup] {len(tool_names)} tools registered: {tool_names}")

# ── Add synthetic test tools for deterministic testing ──
class EchoTool(BaseTool):
    name = "echo"
    description = "Returns its input unchanged (test tool)"
    risk = RiskLevel.LOW

    def execute(self, **kwargs):
        msg = kwargs.get("message", "hello")
        return self._ok(f"echo: {msg}")

class FailingTool(BaseTool):
    name = "failer"
    description = "Always fails (test tool)"
    risk = RiskLevel.LOW

    def execute(self, **kwargs):
        return self._fail("intentional failure for test")

class SlowTool(BaseTool):
    name = "slower"
    description = "Slow tool with variable latency (test tool)"
    risk = RiskLevel.MEDIUM

    def execute(self, **kwargs):
        delay = float(kwargs.get("delay", 0.05))
        time.sleep(delay)
        return self._ok(f"done in {delay*1000:.0f}ms")

registry.register_many([EchoTool(), FailingTool(), SlowTool()])
all_tools = registry.list_all()
print(f"[setup] with test tools: {len(all_tools)} total")

# ── Memory engine with test DB ──
TEST_DB = Path(os.path.expanduser("~/.nex-agent/_test_pipeline.db"))
if TEST_DB.exists():
    TEST_DB.unlink()
TEST_DB.parent.mkdir(parents=True, exist_ok=True)

store = MemoryEngineStore(str(TEST_DB))
engine = MemoryEngine(store=store)
print(f"[setup] memory engine ready, db={TEST_DB}")

executor = ClosedLoopExecutor(registry=registry, max_retries=0)


# ═══════════════════════════════════════════════════════════
# 2. Run test batch
# ═══════════════════════════════════════════════════════════

TEST_BATCH = [
    # (tool_name, kwargs, expected_status)
    ("echo", {"message": "hello world"}, "VERIFIED"),
    ("echo", {"message": "test observation pipeline"}, "VERIFIED"),
    ("echo", {"message": "记忆管线集成测试"}, "VERIFIED"),
    ("slower", {"delay": 0.01}, "SUCCESS"),
    ("slower", {"delay": 0.05}, "SUCCESS"),
    ("slower", {"delay": 0.10}, "SUCCESS"),
    ("slower", {"delay": 0.02}, "SUCCESS"),
    ("slower", {"delay": 0.08}, "SUCCESS"),
    ("failer", {}, "FAILED"),
    ("echo", {"message": "batch complete"}, "VERIFIED"),
]

# Also add some system tools if available
try:
    if "timezone" in all_tools:
        import subprocess
        current_tz = subprocess.run(
            ["timedatectl", "show", "--property=Timezone", "--value"],
            capture_output=True, text=True, timeout=5
        ).stdout.strip()
        TEST_BATCH.append(("timezone", {"timezone": current_tz, "confirmed": True}, "VERIFIED"))
        print(f"[setup] timezone test added (current={current_tz})")
except Exception as e:
    print(f"[setup] timezone tool skipped: {e}")

results = []
exec_latencies = []
obs_latencies = []
ep_latencies = []
e2e_latencies = []

async def run_batch():

    for tool_name, kwargs, expected in TEST_BATCH:
        row = {
            "tool_name": tool_name,
            "kwargs": {k: v for k, v in kwargs.items() if k != "confirmed"},
            "expected_status": expected,
        }

        # ── Phase 1: Tool execution ──
        t0 = time.perf_counter()
        try:
            result = await executor.run(tool_name, **kwargs)
        except Exception as e:
            result = ToolResult(tool_name, ToolStatus.FAILED, error=str(e))
        t1 = time.perf_counter()
        exec_ms = (t1 - t0) * 1000
        exec_latencies.append(exec_ms)

        row["exec_status"] = result.status.value
        row["exec_match"] = result.status.value == expected
        row["exec_latency_ms"] = round(exec_ms, 2)

        # ── Phase 2: Observation creation ──
        t2 = time.perf_counter()
        try:
            obs_event = result.to_observation()
            observation = observation_from_event(obs_event)
            obs_created = engine.ingest_event(obs_event, segment=True)
        except Exception as e:
            obs_event = None
            observation = None
            obs_created = {"status": "error", "reason": str(e)}
        t3 = time.perf_counter()
        obs_ms = (t3 - t2) * 1000
        obs_latencies.append(obs_ms)

        row["observation_created"] = obs_created.get("status") == "ok"
        row["observation_id"] = obs_created.get("observation_id", "")
        row["episode_id"] = obs_created.get("episode_id", "")
        row["episode_status"] = obs_created.get("episode_status", "")
        row["observation_latency_ms"] = round(obs_ms, 2)
        row["source_type"] = obs_created.get("source_type", "")

        # ── End to end ──
        e2e_ms = exec_ms + obs_ms
        e2e_latencies.append(e2e_ms)
        row["e2e_latency_ms"] = round(e2e_ms, 2)

        results.append(row)

        icon = "✓" if row["observation_created"] else "✗"
        print(f"  {icon} {tool_name:12s} → {result.status.value:12s} | exec={exec_ms:6.1f}ms obs={obs_ms:5.1f}ms | obs={row['observation_id'][:20] if row['observation_id'] else 'NONE'}")

asyncio.run(run_batch())

# ═══════════════════════════════════════════════════════════
# 3. Recall test — retrieve memories and check
# ═══════════════════════════════════════════════════════════

print("\n[recall] running retrieval tests...")

recall_results = []
retrieval_latencies = []

test_queries = [
    ("echo message hello", 1),       # should find echo results
    ("管线集成", 1),                   # Chinese content
    ("slow tool result", 1),          # should find slower results
    ("batch complete", 1),            # should find last echo
    ("nonexistent_xyz_12345", 0),     # should find nothing relevant
]

for query, min_hits in test_queries:
    t0 = time.perf_counter()
    try:
        response = engine.retrieve(query, top_k=3)
        hits = len(response.results) if hasattr(response, 'results') else 0
    except Exception as e:
        response = None
        hits = -1
    t1 = time.perf_counter()
    retrieval_latencies.append((t1 - t0) * 1000)

    recall_results.append({
        "query": query,
        "hits": hits,
        "min_expected": min_hits,
        "satisfied": hits >= min_hits,
        "latency_ms": round((t1 - t0) * 1000, 2),
    })
    icon = "✓" if hits >= min_hits else "✗"
    print(f"  {icon} query='{query:30s}' hits={hits} (min={min_hits})")

# ═══════════════════════════════════════════════════════════
# 4. Store statistics
# ═══════════════════════════════════════════════════════════

store_counts = store.counts()
print(f"\n[store] counts: {store_counts}")

# ═══════════════════════════════════════════════════════════
# 5. Compute metrics
# ═══════════════════════════════════════════════════════════

def percentiles(values):
    if not values:
        return {"p50": 0, "p95": 0, "p99": 0, "min": 0, "max": 0, "mean": 0, "count": 0}
    s = sorted(values)
    n = len(s)
    return {
        "p50": round(s[int(n * 0.50)], 2) if n > 0 else 0,
        "p95": round(s[int(n * 0.95)], 2) if n >= 2 else round(s[-1], 2),
        "p99": round(s[int(n * 0.99)], 2) if n >= 3 else round(s[-1], 2),
        "min": round(min(s), 2),
        "max": round(max(s), 2),
        "mean": round(statistics.mean(s), 2),
        "stdev": round(statistics.stdev(s), 2) if n >= 2 else 0,
        "count": n,
    }

passed = sum(1 for r in results if r["exec_match"])
obs_created = sum(1 for r in results if r["observation_created"])
recall_passed = sum(1 for r in recall_results if r["satisfied"])

report = {
    "test_metadata": {
        "pipeline": "SDK_tool_result_to_memory_engine_observation_v1",
        "date": datetime.now(timezone.utc).isoformat(),
        "server": "Kylin V11 (阿里云 ECS)",
        "python": sys.version.split()[0],
        "test_db": str(TEST_DB),
    },
    "latency_metrics": {
        "tool_execution_ms": percentiles(exec_latencies),
        "observation_creation_ms": percentiles(obs_latencies),
        "end_to_end_ms": percentiles(e2e_latencies),
        "memory_retrieval_ms": percentiles(retrieval_latencies),
    },
    "recall_metrics": {
        "total_tests": len(results),
        "execution_pass_rate": round(passed / len(results), 4) if results else 0,
        "observations_created": obs_created,
        "observation_success_rate": round(obs_created / len(results), 4) if results else 0,
        "retrieval_tests": len(recall_results),
        "retrieval_pass_rate": round(recall_passed / len(recall_results), 4) if recall_results else 0,
        "store": store_counts,
    },
    "test_results": results,
    "recall_results": recall_results,
}

# Write JSON
output_path = Path(os.path.expanduser(
    "~/work/projects/project_dev1/_test_sdk_memory_results.json"
))
with open(output_path, "w") as f:
    json.dump(report, f, ensure_ascii=False, indent=2)
print(f"\n[✓] report written to {output_path}")
print(json.dumps(report["latency_metrics"], indent=2, ensure_ascii=False))
print(json.dumps(report["recall_metrics"], indent=2, ensure_ascii=False))

# Cleanup
if TEST_DB.exists():
    TEST_DB.unlink()
    print("[cleanup] test db removed")
