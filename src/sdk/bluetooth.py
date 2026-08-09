"""
Kylin Bluetooth SDK - ctypes Python bindings.
Replaces: bluetoothctl, hcitool
"""
import ctypes, subprocess
from typing import Dict, Any, List, Tuple
from .base import load_library, _decode_cstring, declare, IS_LINUX, IS_KYLIN

_LIB = None
def _get_lib():
    global _LIB
    if _LIB is None:
        _LIB = load_library("libkybluetooth", mock=not IS_KYLIN)
    return _LIB

def get_bluetooth_status():
    lib = _get_lib()
    if lib:
        try:
            declare(lib, "kdk_bt_get_status", restype=ctypes.c_char_p)
            raw = lib.kdk_bt_get_status()
            if raw:
                import json
                return json.loads(_decode_cstring(raw))
        except: pass
    return _fallback_bt_status()

def _fallback_bt_status():
    status = {"enabled": False, "devices": []}
    try:
        r = subprocess.run(["rfkill", "list", "bluetooth"], capture_output=True, text=True, timeout=3)
        status["enabled"] = "blocked" not in r.stdout.lower()
    except: pass
    return status

def enable_bluetooth():
    lib = _get_lib()
    if lib:
        try:
            declare(lib, "kdk_bt_enable", restype=ctypes.c_int)
            if lib.kdk_bt_enable() == 0: return True, "Bluetooth enabled (SDK)"
        except: pass
    try:
        subprocess.run(["rfkill", "unblock", "bluetooth"], capture_output=True, timeout=5)
        return True, "Bluetooth enabled (rfkill)"
    except Exception as e: return False, str(e)

def disable_bluetooth():
    lib = _get_lib()
    if lib:
        try:
            declare(lib, "kdk_bt_disable", restype=ctypes.c_int)
            if lib.kdk_bt_disable() == 0: return True, "Bluetooth disabled (SDK)"
        except: pass
    try:
        subprocess.run(["rfkill", "block", "bluetooth"], capture_output=True, timeout=5)
        return True, "Bluetooth disabled (rfkill)"
    except Exception as e: return False, str(e)

def scan_devices(timeout_s=10):
    lib = _get_lib()
    if lib:
        try:
            declare(lib, "kdk_bt_scan", restype=ctypes.c_char_p, argtypes=[ctypes.c_int])
            raw = lib.kdk_bt_scan(timeout_s)
            if raw:
                import json
                return json.loads(_decode_cstring(raw))
        except: pass
    return _fallback_bt_scan(timeout_s)

def _fallback_bt_scan(timeout_s=10):
    devs = []
    try:
        r = subprocess.run(["bluetoothctl", "devices"], capture_output=True, text=True, timeout=timeout_s)
        for line in r.stdout.strip().split("\n"):
            if line.startswith("Device "):
                parts = line[7:].split(" ", 1)
                if len(parts) >= 2: devs.append({"address": parts[0], "name": parts[1]})
    except: pass
    return devs

def pair_device(address):
    try:
        r = subprocess.run(["bluetoothctl", "pair", address], capture_output=True, text=True, timeout=30)
        if "successful" in r.stdout.lower(): return True, f"Paired: {address}"
        return False, r.stdout.strip() or r.stderr.strip()
    except Exception as e: return False, str(e)

def connect_device(address):
    try:
        r = subprocess.run(["bluetoothctl", "connect", address], capture_output=True, text=True, timeout=30)
        if "successful" in r.stdout.lower(): return True, f"Connected: {address}"
        return False, r.stdout.strip() or r.stderr.strip()
    except Exception as e: return False, str(e)

def disconnect_device(address):
    try:
        r = subprocess.run(["bluetoothctl", "disconnect", address], capture_output=True, text=True, timeout=10)
        if r.returncode == 0: return True, f"Disconnected: {address}"
        return False, r.stderr.strip()
    except Exception as e: return False, str(e)
