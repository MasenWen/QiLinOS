"""Test kylin_actions DSL -> toolkit bridge."""
import sys, asyncio
sys.path.insert(0, ".")
from src.toolkit.init_tools import init_all_tools; init_all_tools()
from mcp_server.server.kylin_actions import execute_action

async def main():
    print(">>> Test 1: volume via DSL bridge")
    rc, out = await execute_action("open volume")
    print(f"  rc={rc}, output={out}")

    print(">>> Test 2: close volume via DSL bridge")
    rc, out = await execute_action("close volume")
    print(f"  rc={rc}, output={out}")

    print(">>> Test 3: screenshot via DSL bridge")
    rc, out = await execute_action("screenshot")
    print(f"  rc={rc}, output={out[:100]}")

    print(">>> Test 4: set background (path-based)")
    rc, out = await execute_action("set background /tmp/test.png")
    print(f"  rc={rc}, output={out[:100]}")

    print("\nAll bridge tests completed")

asyncio.run(main())
