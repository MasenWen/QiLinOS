"""
Kylin Battery/Power SDK - ctypes Python bindings.
Replaces: acpi -b, upower -d, /sys/class/power_supply
"""
import ctypes, os, subprocess
from typing import Optional, Dict, Any, Tuple
from .base import load_library, _decode_cstring, declare, IS_LINUX, IS_KYLIN

_LIB = None
def _get_lib():
    global _LIB
    if _LIB is None:
        _LIB = load_library("libkybattery", mock=not IS_KYLIN)
    return _LIB

def get_battery_info():
    lib = _get_lib()
    if lib:
        try:
            declare(lib, "kdk_battery_get_info", restype=ctypes.c_char_p)
            raw = lib.kdk_battery_get_info()
            if raw:
                import json
                return json.loads(_decode_cstring(raw))
        except: pass
    return _fallback_battery_info()

def _fallback_battery_info():
    info = {"present": False, "batteries": []}
    sup = "/sys/class/power_supply"
    if not os.path.exists(sup): return info
    for entry in os.listdir(sup):
        path = os.path.join(sup, entry)
        if not os.path.isdir(path): continue
        bat = {"name": entry}
        for prop in ["type","capacity","status","voltage_now","current_now","charge_full","charge_now","model_name","technology"]:
            try:
                with open(os.path.join(path, prop)) as f: bat[prop] = f.read().strip()
            except: pass
        if bat.get("type") == "Battery":
            info["present"] = True
            info["batteries"].append(bat)
    return info

def get_battery_percentage():
    info = get_battery_info()
    if not info.get("present") or not info.get("batteries"): return -1.0
    try: return float(info["batteries"][0].get("capacity", -1))
    except: return -1.0

def is_charging():
    info = get_battery_info()
    if not info.get("present") or not info.get("batteries"): return None
    s = info["batteries"][0].get("status","").lower()
    if "charging" in s or "full" in s: return True
    if "discharging" in s: return False
    return None

def get_power_plan():
    try:
        r = subprocess.run(["powerprofilesctl", "get"], capture_output=True, text=True, timeout=3)
        return r.stdout.strip()
    except: return "unknown"

def set_power_plan(plan):
    valid = {"power-saver","balanced","performance"}
    if plan not in valid: return False, f"Invalid: {plan}. Use: {valid}"
    try:
        r = subprocess.run(["powerprofilesctl", "set", plan], capture_output=True, text=True, timeout=5)
        if r.returncode == 0: return True, f"Power plan: {plan}"
        return False, r.stderr.strip()
    except FileNotFoundError: return False, "powerprofilesctl unavailable"
    except Exception as e: return False, str(e)
