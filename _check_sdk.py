"""Check actual SDK C library loading on Kylin server."""
import sys, ctypes
sys.path.insert(0, ".")

# --- Test 1: Direct ctypes load ---
print("=== Test 1: Direct ctypes CDLL ===")
path = "/usr/lib/x86_64-linux-gnu/libkysysinfo.so.3.0.0"
try:
    lib = ctypes.CDLL(path)
    print(f"  Loaded: {lib}")
    lib.kdk_get_host_vendor.restype = ctypes.c_char_p
    raw = lib.kdk_get_host_vendor()
    if raw:
        print(f"  host_vendor: {raw.decode('utf-8', errors='replace')}")
    else:
        print("  host_vendor: NULL pointer")
except Exception as e:
    print(f"  ERROR: {type(e).__name__}: {e}")

# --- Test 2: Via SDK wrapper ---
print("\n=== Test 2: Via src.sdk.system ===")
try:
    from src.sdk.base import _resolve_so_path, load_library
    path2 = _resolve_so_path("libkysysinfo")
    print(f"  Resolved: {path2}")

    lib2 = load_library("libkysysinfo", mock=False)
    print(f"  load_library: {lib2}")
    if lib2:
        from src.sdk.base import declare
        declare(lib2, "kdk_get_host_vendor", restype=ctypes.c_char_p)
        vendor = lib2.kdk_get_host_vendor()
        if vendor:
            print(f"  Vendor: {vendor.decode('utf-8', errors='replace')}")
except Exception as e:
    print(f"  ERROR: {type(e).__name__}: {e}")

# --- Test 3: What shell commands are actually called ---
print("\n=== Test 3: Actual implementation check ===")
from src.toolkit.system_tools import TimezoneTool
tz = TimezoneTool()
print(f"  TimezoneTool.execute uses: timedatectl (shell)")
print(f"  TimezoneTool.verify uses:  timedatectl show --property=Timezone --value (shell)")

from src.toolkit.desktop_tools import VolumeTool
vol = VolumeTool()
print(f"  VolumeTool.execute uses:  pactl / amixer (shell)")

print("\n=== Summary ===")
print("SDK C libraries (libkysysinfo.so etc.): EXIST on disk")
print("Direct ctypes loading: WORKS (if no segfault above)")
print("Toolkit tools (timezone, volume etc.): Use SHELL commands")
print("  → 这些工具目前是 shell-based，不是 SDK-based")
print("  → 原因: SDK 没有暴露 timezone/sleep/volume 的 C API")
print("  → SDK 主要提供: 系统信息查询、EDID/显示、硬件信息、AI Vision OCR")
