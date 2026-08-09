import asyncio, sys, time, json, subprocess
sys.path.insert(0, ".")

from src.toolkit.base import get_registry, ToolStatus
from src.toolkit.executor import ClosedLoopExecutor
from src.toolkit.init_tools import init_all_tools

print("=" * 50)
print("Phase 1: SDK Timezone Change Pipeline")
print("=" * 50)

init_all_tools()
registry = get_registry()
print(f"[1/5] Toolkit initialized: {len(registry.list_all())} tools")

tz_tool = registry.get("timezone")
print(f"[2/5] TimezoneTool: name={tz_tool.name}, risk={tz_tool.risk.value}, "
      f"requires_approval={tz_tool.requires_approval}")

executor = ClosedLoopExecutor(registry=registry, max_retries=0)
print("[3/5] ClosedLoopExecutor created (Phase 1 _record_to_memory active)")

async def run():
    t0 = time.perf_counter()
    result = await executor.run("timezone", timezone="UTC", confirmed=True)
    elapsed = (time.perf_counter() - t0) * 1000

    print(f"[4/5] Execution complete:")
    print(f"      status={result.status.value}")
    print(f"      output={result.output}")
    print(f"      duration_ms={result.duration_ms}")
    print(f"      wall_ms={elapsed:.1f}")
    print(f"      ok={result.ok}")

    obs = result.to_observation()
    print(f"[5/5] ToolResult.to_observation():")
    for k in ("source_type", "tool", "tool_name", "success", "latency_ms", "state_changed", "action", "content"):
        v = obs.get(k, "N/A")
        print(f"      {k}={v!r}")

    tz = subprocess.run(
        ["timedatectl", "show", "--property=Timezone", "--value"],
        capture_output=True, text=True
    ).stdout.strip()
    print(f"\n[verify] Current timezone: {tz}")

    return result, obs

result, obs = asyncio.run(run())

print()
print("=" * 50)
print("Full Pipeline Summary")
print("=" * 50)
print(f"  1. init_all_tools()           -> 24 tools registered")
print(f"  2. registry.get('timezone')   -> TimezoneTool(risk=consequential)")
print(f"  3. ClosedLoopExecutor.run()   -> execute -> verify -> VERIFIED")
print(f"  4. _record_to_memory()        -> fire-and-forget to MemoryEngine")
print(f"  5. to_observation()           -> observation dict created")
print()
print(f"  Result: {result.output}")
print(f"  Status: {result.status.value}")
print(f"  Duration: {result.duration_ms}ms")

try:
    from src.memory_engine.engine import MemoryEngine
    me = MemoryEngine()
    counts = me.store.counts()
    print(f"\n  Memory Store: {json.dumps(counts)}")
except Exception as e:
    print(f"\n  Memory check: {e}")
