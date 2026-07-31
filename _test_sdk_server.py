#!/usr/bin/env python3
"""Quick SDK test script for Kylin server (display-safe)."""
import sys, os, ctypes

# Suppress Qt/display warnings
os.environ.setdefault("DISPLAY", "")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, '.')

from src.sdk.base import load_library, _decode_cstring

def safe_call(fn, label=""):
    """Call a ctypes function safely, catch segfaults."""
    try:
        return _decode_cstring(fn())
    except Exception as e:
        return f"<error: {e}>"

# ---- libkysysinfo ----
print("=== libkysysinfo ===")
lib = load_library("libkysysinfo")
lib.kdk_system_get_architecture.restype = ctypes.c_char_p
lib.kdk_get_host_vendor.restype = ctypes.c_char_p
lib.kdk_get_host_product.restype = ctypes.c_char_p
lib.kdk_get_host_serial.restype = ctypes.c_char_p
lib.kdk_system_get_buildTime.restype = ctypes.c_char_p

print(f"  architecture: {safe_call(lib.kdk_system_get_architecture)}")
print(f"  host_vendor:  {safe_call(lib.kdk_get_host_vendor)}")
print(f"  host_product: {safe_call(lib.kdk_get_host_product)}")
print(f"  host_serial:  {safe_call(lib.kdk_get_host_serial)}")
print(f"  build_time:   {safe_call(lib.kdk_system_get_buildTime)}")

# ---- libkyhwinfo ----
print("\n=== libkyhwinfo ===")
hw = load_library("libkyhwinfo")
hw.kdk_hw_get_hwinfo.restype = ctypes.c_char_p
hw.kdk_hw_get_powerinfo.restype = ctypes.c_char_p
print(f"  hwinfo:   {safe_call(hw.kdk_hw_get_hwinfo)[:200]}")
print(f"  power:    {safe_call(hw.kdk_hw_get_powerinfo)[:200]}")

# ---- libkyedid (needs DISPLAY, might fail over SSH) ----
print("\n=== libkyedid ===")
edid = load_library("libkyedid")
edid.kdk_edid_get_manufacturer.restype = ctypes.c_char_p
edid.kdk_edid_get_model.restype = ctypes.c_char_p
edid.kdk_edid_get_resolution.restype = ctypes.c_char_p
print(f"  manufacturer: {safe_call(edid.kdk_edid_get_manufacturer)}")
print(f"  model:        {safe_call(edid.kdk_edid_get_model)}")
print(f"  resolution:   {safe_call(edid.kdk_edid_get_resolution)}")

# ---- libkyfan ----
print("\n=== libkyfan ===")
fan = load_library("libkyfan")
fan.kdk_fan_get_information.restype = ctypes.c_char_p
print(f"  fan: {safe_call(fan.kdk_fan_get_information)[:200]}")

# ---- AI Vision OCR ----
print("\n=== AI Vision OCR ===")
from src.sdk.ai_vision import is_available
print(f"  available: {is_available()}")

print("\nDone")
