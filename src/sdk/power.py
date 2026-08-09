"""
Kylin Power Management SDK — ctypes bindings.

Covers three shared libraries:
- ``libkypowermanagement`` : suspend / hibernate support + set
- ``libkyshutdown``        : scheduled power-off / cancel / query
- ``libkyrestart``         : scheduled reboot / cancel / query

Replaces shell commands::

    systemctl suspend          → power.suspend()
    systemctl poweroff         → power.power_off(min)
    shutdown -h +N             → power.power_off(min)
    shutdown -r +N             → power.reboot(min)
    shutdown -c                → power.cancel_power_off() / cancel_reboot()

Every public API returns ``(ok: bool, message: str)`` and never raises —
callers use the bool to decide SDK-first vs shell fallback.
"""
from __future__ import annotations

import ctypes
import logging
from typing import Tuple

from .base import load_library, declare

logger = logging.getLogger("sdk.power")

# ---------------------------------------------------------------------------
# Library loading (mock-safe: returns None on non-Kylin / missing lib)
# ---------------------------------------------------------------------------

_lib_power = load_library("kypowermanagement", mock=True)
_lib_shutdown = load_library("kyshutdown", mock=True)
_lib_restart = load_library("kyrestart", mock=True)

# --- Declare C signatures ---
if _lib_power is not None:
    declare(_lib_power, "kdk_power_set_suspend", restype=ctypes.c_int)          # 0 ok / -1 fail
    declare(_lib_power, "kdk_power_is_support_suspend", restype=ctypes.c_bool)
    declare(_lib_power, "kdk_power_set_hibernate", restype=ctypes.c_int)
    declare(_lib_power, "kdk_power_is_support_hibernate", restype=ctypes.c_bool)

if _lib_shutdown is not None:
    declare(_lib_shutdown, "kdk_shutdown_power_off", restype=ctypes.c_int,
            argtypes=[ctypes.c_int])   # minutes; negative => immediate
    declare(_lib_shutdown, "kdk_shutdown_cancel_power_off", restype=ctypes.c_bool)
    declare(_lib_shutdown, "kdk_shutdown_is_schedule_power_off", restype=ctypes.c_bool)

if _lib_restart is not None:
    declare(_lib_restart, "kdk_restart_reboot", restype=ctypes.c_int,
            argtypes=[ctypes.c_int])   # minutes; negative => immediate
    declare(_lib_restart, "kdk_restart_cancel_reboot", restype=ctypes.c_bool)
    declare(_lib_restart, "kdk_restart_is_schedule_reboot", restype=ctypes.c_bool)


# ---------------------------------------------------------------------------
# Availability
# ---------------------------------------------------------------------------

def is_available() -> bool:
    """True if at least one power/shutdown/restart library loaded."""
    return any(lib is not None for lib in (_lib_power, _lib_shutdown, _lib_restart))


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _ok(msg: str) -> Tuple[bool, str]:
    return True, msg


def _err(msg: str) -> Tuple[bool, str]:
    return False, msg


def _call(fn, *args, **kw) -> Tuple[bool, str]:
    """Invoke a ctypes function, returning (ok, msg). Never raises."""
    if fn is None:
        return _err("SDK 函数不可用（库未加载）")
    try:
        ret = fn(*args, **kw)
        return _ok("ok"), ret
    except Exception as e:  # ctypes can raise OSError/ValueError
        logger.error("SDK 调用异常: %s", e)
        return _err(f"SDK 调用异常: {e}")


# ---------------------------------------------------------------------------
# Suspend / Hibernate
# ---------------------------------------------------------------------------

def is_support_suspend() -> bool:
    if _lib_power is None or not hasattr(_lib_power, "kdk_power_is_support_suspend"):
        return False
    try:
        return bool(_lib_power.kdk_power_is_support_suspend())
    except Exception:
        return False


def is_support_hibernate() -> bool:
    if _lib_power is None or not hasattr(_lib_power, "kdk_power_is_support_hibernate"):
        return False
    try:
        return bool(_lib_power.kdk_power_is_support_hibernate())
    except Exception:
        return False


def suspend() -> Tuple[bool, str]:
    """Put the system into suspend (sleep)."""
    if _lib_power is None:
        return _err("libkypowermanagement 不可用")
    if not is_support_suspend():
        return _err("当前设备不支持挂起 (suspend)")
    ok, ret = _call(_lib_power.kdk_power_set_suspend)
    if ok and ret == 0:
        return _ok("系统已进入挂起状态 (SDK)")
    return _err(f"挂起失败 (SDK 返回 {ret})")


def hibernate() -> Tuple[bool, str]:
    """Put the system into hibernate."""
    if _lib_power is None:
        return _err("libkypowermanagement 不可用")
    if not is_support_hibernate():
        return _err("当前设备不支持休眠 (hibernate)")
    ok, ret = _call(_lib_power.kdk_power_set_hibernate)
    if ok and ret == 0:
        return _ok("系统已进入休眠状态 (SDK)")
    return _err(f"休眠失败 (SDK 返回 {ret})")


# ---------------------------------------------------------------------------
# Power-off (libkyshutdown)
# ---------------------------------------------------------------------------

def power_off(minutes: int) -> Tuple[bool, str]:
    """
    Schedule power-off after ``minutes``.  ``minutes < 0`` => immediate.

    Returns (True, msg) if the SDK accepted the schedule.
    """
    if _lib_shutdown is None:
        return _err("libkyshutdown 不可用")
    try:
        min_int = int(minutes)
    except (TypeError, ValueError):
        return _err(f"无效的分钟数: {minutes}")
    ok, ret = _call(_lib_shutdown.kdk_shutdown_power_off, min_int)
    if ok and ret == 0:
        label = "立即关机" if min_int < 0 else f"{min_int} 分钟后关机"
        return _ok(f"已调度: {label} (SDK)")
    return _err(f"关机调度失败 (SDK 返回 {ret})")


def cancel_power_off() -> Tuple[bool, str]:
    if _lib_shutdown is None:
        return _err("libkyshutdown 不可用")
    ok, ret = _call(_lib_shutdown.kdk_shutdown_cancel_power_off)
    if ok and ret:
        return _ok("已取消关机任务 (SDK)")
    return _err(f"取消关机失败 (SDK 返回 {ret})")


def is_schedule_power_off() -> bool:
    if _lib_shutdown is None or not hasattr(_lib_shutdown, "kdk_shutdown_is_schedule_power_off"):
        return False
    try:
        return bool(_lib_shutdown.kdk_shutdown_is_schedule_power_off())
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Reboot (libkyrestart)
# ---------------------------------------------------------------------------

def reboot(minutes: int) -> Tuple[bool, str]:
    """
    Schedule reboot after ``minutes``.  ``minutes < 0`` => immediate.
    """
    if _lib_restart is None:
        return _err("libkyrestart 不可用")
    try:
        min_int = int(minutes)
    except (TypeError, ValueError):
        return _err(f"无效的分钟数: {minutes}")
    ok, ret = _call(_lib_restart.kdk_restart_reboot, min_int)
    if ok and ret == 0:
        label = "立即重启" if min_int < 0 else f"{min_int} 分钟后重启"
        return _ok(f"已调度: {label} (SDK)")
    return _err(f"重启调度失败 (SDK 返回 {ret})")


def cancel_reboot() -> Tuple[bool, str]:
    if _lib_restart is None:
        return _err("libkyrestart 不可用")
    ok, ret = _call(_lib_restart.kdk_restart_cancel_reboot)
    if ok and ret:
        return _ok("已取消重启任务 (SDK)")
    return _err(f"取消重启失败 (SDK 返回 {ret})")


def is_schedule_reboot() -> bool:
    if _lib_restart is None or not hasattr(_lib_restart, "kdk_restart_is_schedule_reboot"):
        return False
    try:
        return bool(_lib_restart.kdk_restart_is_schedule_reboot())
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Convenience summary for tool descriptions / debugging
# ---------------------------------------------------------------------------

def summary() -> str:
    parts = []
    parts.append(f"power={'✓' if _lib_power is not None else '✗'}")
    parts.append(f"shutdown={'✓' if _lib_shutdown is not None else '✗'}")
    parts.append(f"restart={'✓' if _lib_restart is not None else '✗'}")
    if _lib_power is not None:
        parts.append(f"suspend_support={'✓' if is_support_suspend() else '✗'}")
        parts.append(f"hibernate_support={'✓' if is_support_hibernate() else '✗'}")
    return " | ".join(parts)
