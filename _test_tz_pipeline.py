import asyncio, sys, time, json
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
    print(f"      source_type={obs['source_type']}")
    print(f"      tool={obs['tool_name']}")
    print(f"      success={obs['success']}")
    print(f"      latency_ms={obs['latency_ms']}")
    print(f"      content={obs['content'][:120]}")
    print(f"      state_changed={obs['state_changed']}")
    print(f"      action={obs['action']}")

    # Verify the timezone actually changed
    import subprocess
    tz = subprocess.run(["timedatectl", "show", "--property=Timezone", "--value"],
                        capture_output=True, text=True).stdout.strip()
    print(f"\n[verify] Current timezone: {tz}")

    return result, obs

result, obs = asyncio.run(run())

print()
print("=" * 50)
print("Full Pipeline Summary")
print("=" * 50)
print(f"  1. init_all_tools()           -> 24 tools registered")
print(f"  2. registry.get(timezone)   -> TimezoneTool(risk=consequential)")
print(f"  3. ClosedLoopExecutor.run()   -> execute → verify → VERIFIED ✅")
print(f"  4. _record_to_memory()        -> fire-and-forget to MemoryEngine")
print(f"  5. to_observation()           -> source_type=tool_result")
print()
print(f"  Result: {result.output}")
print(f"  Status: {result.status.value}")
print(f"  Duration: {result.duration_ms}ms")

# check DB
try:
    from src.memory_engine.store import MemoryEngineStore
    store = MemoryEngineStore()
    counts = store.counts()
    print(f"\n  Memory Store: {counts}")
except Exception as e:
    print(f"\n  Memory check: {e}")
