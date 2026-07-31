"""
End-to-end test: Timezone change with closed-loop verification.

Tests:
1. Change timezone (e.g., Asia/Singapore → Asia/Shanghai)
2. Verify change via timedatectl
3. Change back
4. Verify restoration
"""
import sys, asyncio, logging, subprocess
sys.path.insert(0, "src")
logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")

from toolkit.base import get_registry
from toolkit.system_tools import TimezoneTool
from toolkit.executor import ClosedLoopExecutor

registry = get_registry()
registry.register(TimezoneTool())
print(f"Tools registered: {registry.list_all()}")

executor = ClosedLoopExecutor(registry=registry, max_retries=1)


def get_tz():
    return subprocess.run(
        ["timedatectl", "show", "--property=Timezone", "--value"],
        capture_output=True, text=True
    ).stdout.strip()


async def main():
    before = get_tz()
    print(f"\nCurrent timezone: {before}")

    # Pick a different timezone
    target = "Asia/Shanghai" if before != "Asia/Shanghai" else "Asia/Urumqi"
    print(f"Target timezone:  {target}")

    # ======= Test 1: Change timezone =======
    print(f"\n{'='*60}")
    print("TEST 1: Change timezone with closed-loop verification")
    print(f"{'='*60}")

    result = await executor.run("timezone", timezone=target)

    print(f"  status:      {result.status.value}")
    print(f"  output:      {result.output}")
    print(f"  verification: {result.verification}")
    print(f"  duration:    {result.duration_ms:.0f}ms")
    print(f"  retries:     {result.retry_count}")
    print(f"  is_verified: {result.is_verified}")
    print(f"  to_log:      {result.to_log()}")

    after = get_tz()
    change_ok = (after == target)
    print(f"  Actual TZ:   {after}")
    print(f"  Match:       {change_ok}")

    # ======= Test 2: Restore timezone =======
    print(f"\n{'='*60}")
    print("TEST 2: Restore original timezone")
    print(f"{'='*60}")

    result2 = await executor.run("timezone", timezone=before)

    print(f"  status:      {result2.status.value}")
    print(f"  is_verified: {result2.is_verified}")
    print(f"  to_log:      {result2.to_log()}")

    final = get_tz()
    restore_ok = (final == before)
    print(f"  Final TZ:    {final}")
    print(f"  Restored:    {restore_ok}")

    # ======= Summary =======
    print(f"\n{'='*60}")
    print("EXECUTION TRACES")
    print(f"{'='*60}")
    for t in executor.traces:
        print(t.to_summary())

    all_ok = result.is_verified and result2.is_verified and change_ok and restore_ok
    print(f"\n{'✅ ALL PASSED' if all_ok else '❌ SOME TESTS FAILED'}")
    return all_ok


if __name__ == "__main__":
    ok = asyncio.run(main())
    sys.exit(0 if ok else 1)
