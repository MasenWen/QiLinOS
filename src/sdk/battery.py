"""
Kylin Battery/Power SDK - ctypes Python bindings.
Replaces: acpi -b, upower -d, /sys/class/power_supply

注: 麒麟电池 SDK 由 libkysdk-battery 提供 (安装包: libkysdk-battery libkysdk-battery-dev)，
    库名 libkybattery.so，函数前缀 kdk_battery_*。
"""
import ctypes
import os
import subprocess
import threading
from typing import Optional, Dict, Any, Tuple

from .base import load_library, _decode_cstring, declare, IS_KYLIN

_LIB = None
_lock = threading.Lock()

# BatteryChargeState (libkybattery.h)
_CHARGE_STATE = {0: "unknown", 1: "charging", 2: "discharging", 3: "full", 4: "not_charging"}
# BatteryHealthState
_HEALTH_STATE = {
    0: "unknown", 1: "good", 2: "overheat", 3: "overvoltage", 4: "cold", 5: "dead",
    6: "unspecified_failure", 7: "watchdog_timer_expire", 8: "safety_timer_expire",
    9: "overcurrent", 10: "calibration_required", 11: "warm", 12: "cool",
}
# BatteryPluggedType
_PLUGGED_TYPE = {
    0: "none", 1: "battery", 2: "ups", 3: "mains", 4: "usb", 5: "usb_dcp", 6: "usb_cdp",
    7: "usb_aca", 8: "usb_type_c", 9: "usb_pd", 10: "usb_pd_drp", 11: "apple_brick_id",
    12: "wireless",
}


def _get_lib():
    global _LIB
    if _LIB is None:
        with _lock:
            if _LIB is None:
                try:
                    _LIB = load_library("libkybattery", mock=not IS_KYLIN)
                except Exception:
                    _LIB = False
    return _LIB if _LIB else None


def _declare(lib):
    declare(lib, "kdk_battery_is_present", restype=ctypes.c_bool)
    declare(lib, "kdk_battery_get_soc", restype=ctypes.c_float)
    declare(lib, "kdk_battery_get_charge_state", restype=ctypes.c_int)
    declare(lib, "kdk_battery_get_health_state", restype=ctypes.c_int)
    declare(lib, "kdk_battery_get_plugged_type", restype=ctypes.c_int)
    declare(lib, "kdk_battery_get_voltage", restype=ctypes.c_float)
    declare(lib, "kdk_battery_get_temperature", restype=ctypes.c_float)
    declare(lib, "kdk_battery_get_technology", restype=ctypes.c_char_p)
    declare(lib, "kdk_battery_get_capacity_level", restype=ctypes.c_int)


def get_battery_info():
    """Return {'present': bool, 'batteries': [...]} from the SDK, or /sys fallback."""
    lib = _get_lib()
    if lib:
        try:
            _declare(lib)
            if not lib.kdk_battery_is_present():
                return {"present": False, "batteries": []}
            bat = {
                "name": "BAT0",
                "type": "Battery",
                "capacity": round(float(lib.kdk_battery_get_soc()), 1),
                "status": _CHARGE_STATE.get(lib.kdk_battery_get_charge_state(), "unknown"),
                "health": _HEALTH_STATE.get(lib.kdk_battery_get_health_state(), "unknown"),
                "plugged": _PLUGGED_TYPE.get(lib.kdk_battery_get_plugged_type(), "none"),
                "voltage_now": round(float(lib.kdk_battery_get_voltage()), 1),
                "temperature": round(float(lib.kdk_battery_get_temperature()), 1),
                "capacity_level": lib.kdk_battery_get_capacity_level(),
            }
            tech = lib.kdk_battery_get_technology()
            if tech:
                bat["technology"] = _decode_cstring(tech)
            return {"present": True, "batteries": [bat]}
        except Exception:
            pass
    return _fallback_battery_info()


def _fallback_battery_info():
    info = {"present": False, "batteries": []}
    sup = "/sys/class/power_supply"
    if not os.path.exists(sup):
        return info
    for entry in os.listdir(sup):
        path = os.path.join(sup, entry)
        if not os.path.isdir(path):
            continue
        bat = {"name": entry}
        for prop in ["type", "capacity", "status", "voltage_now", "current_now",
                     "charge_full", "charge_now", "model_name", "technology"]:
            try:
                with open(os.path.join(path, prop)) as f:
                    bat[prop] = f.read().strip()
            except Exception:
                pass
        if bat.get("type") == "Battery":
            info["present"] = True
            info["batteries"].append(bat)
    return info


def get_battery_percentage():
    info = get_battery_info()
    if not info.get("present") or not info.get("batteries"):
        return -1.0
    try:
        return float(info["batteries"][0].get("capacity", -1))
    except Exception:
        return -1.0


def is_charging():
    info = get_battery_info()
    if not info.get("present") or not info.get("batteries"):
        return None
    s = str(info["batteries"][0].get("status", "")).lower()
    if "charging" in s or "full" in s:
        return True
    if "discharging" in s:
        return False
    return None


def get_power_plan():
    try:
        r = subprocess.run(["powerprofilesctl", "get"], capture_output=True, text=True, timeout=3)
        return r.stdout.strip()
    except Exception:
        return "unknown"


def set_power_plan(plan):
    valid = {"power-saver", "balanced", "performance"}
    if plan not in valid:
        return False, f"Invalid: {plan}. Use: {valid}"
    try:
        r = subprocess.run(["powerprofilesctl", "set", plan], capture_output=True, text=True, timeout=5)
        if r.returncode == 0:
            return True, f"Power plan: {plan}"
        return False, r.stderr.strip()
    except FileNotFoundError:
        return False, "powerprofilesctl unavailable"
    except Exception as e:
        return False, str(e)


is_available = lambda: _get_lib() is not None
