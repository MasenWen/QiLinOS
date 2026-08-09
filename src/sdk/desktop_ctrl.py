"""
Kylin Desktop Control SDK — ctypes bindings for libkydesktopctrl.

Covers:
- Control panel module visibility / enable / status (kdk_controplpanel_*)
- Power settings: desktop idle hungup / close-display (kdk_powersetting_*)
- Screensaver: set file / enable / disable / autolock (kdk_screensaver_*)
- Wallpaper: set desktop wallpaper (kdk_wallpaper_set_file)
- Watermark: create / delete / visibility (kdk_watermark_*)

The library ships under ``libkysdk-desktopctrl`` and lives at
``/usr/lib/kysdk/kysdk-security/libkydesktopctrl.so``.

Every public API returns ``(ok: bool, message: str)`` and never raises —
callers use the bool to decide SDK-first vs shell fallback.
"""
from __future__ import annotations

import ctypes
import logging
from typing import Any, Tuple

from .base import load_library, declare

logger = logging.getLogger("sdk.desktop_ctrl")

# ---------------------------------------------------------------------------
# Library loading (mock-safe: returns None on non-Kylin / missing lib)
# ---------------------------------------------------------------------------

_lib = load_library(
    "kydesktopctrl",
    fallback_paths=["/usr/lib/kysdk/kysdk-security"],
    mock=True,
)

# --- Declare C signatures ---
if _lib is not None:
    # Control panel
    declare(_lib, "kdk_controlpanel_get_module_visible", restype=ctypes.c_bool,
            argtypes=[ctypes.c_int])
    declare(_lib, "kdk_controlpanel_get_module_enable", restype=ctypes.c_bool,
            argtypes=[ctypes.c_int])
    declare(_lib, "kdk_controplpanel_set_module_visible", restype=ctypes.c_int,
            argtypes=[ctypes.c_int, ctypes.c_bool])
    declare(_lib, "kdk_controplpanel_set_module_status", restype=ctypes.c_int,
            argtypes=[ctypes.c_int, ctypes.c_int])

    # Power settings
    declare(_lib, "kdk_powersetting_set_desktop_idle_hungup", restype=ctypes.c_int,
            argtypes=[ctypes.c_uint])
    declare(_lib, "kdk_powersetting_get_desktop_idle_hungup", restype=ctypes.c_uint)
    declare(_lib, "kdk_powersetting_set_desktop_idle_closedisplay", restype=ctypes.c_int,
            argtypes=[ctypes.c_uint])
    declare(_lib, "kdk_powersetting_get_desktop_idle_closedisplay", restype=ctypes.c_uint)

    # Screensaver
    declare(_lib, "kdk_screensaver_set_file", restype=ctypes.c_int,
            argtypes=[ctypes.c_char_p])
    declare(_lib, "kdk_screensaver_enable", restype=ctypes.c_int)
    declare(_lib, "kdk_screensaver_disable", restype=ctypes.c_int)
    declare(_lib, "kdk_screensaver_autolock_enable", restype=ctypes.c_int)
    declare(_lib, "kdk_screensaver_autolock_disable", restype=ctypes.c_int)
    declare(_lib, "kdk_screensaver_idlelock_time", restype=ctypes.c_int,
            argtypes=[ctypes.c_uint])
    declare(_lib, "kdk_screensaver_autolock_time", restype=ctypes.c_int,
            argtypes=[ctypes.c_uint])

    # Wallpaper
    declare(_lib, "kdk_wallpaper_set_file", restype=ctypes.c_int,
            argtypes=[ctypes.c_char_p])

    # Watermark
    declare(_lib, "kdk_watermark_create", restype=ctypes.c_int,
            argtypes=[ctypes.c_char_p])
    declare(_lib, "kdk_watermark_delete", restype=ctypes.c_int,
            argtypes=[ctypes.c_char_p])
    declare(_lib, "kdk_watermark_set_visibe", restype=ctypes.c_int,
            argtypes=[ctypes.c_char_p, ctypes.c_bool])
    declare(_lib, "kdk_watermark_get_visibe", restype=ctypes.c_bool,
            argtypes=[ctypes.c_char_p])


# ---------------------------------------------------------------------------
# Module ID enum (control panel modules)
# ---------------------------------------------------------------------------

class ModuleID:
    """控制面板模块 ID (搬自 kylin_desktop_control_server.py, 避免重复定义)."""

    # 系统一级 (0-15)
    CP_SYS = 0
    CP_SYS_DISPLAY = 1
    CP_SYS_TOUCHSCREEN = 2
    CP_SYS_AUTOBOOT = 3
    CP_SYS_DEFAULTAPP = 4
    CP_SYS_POWER = 5
    CP_SYS_AUDIO = 6
    CP_SYS_NOTICE = 7
    CP_SYS_VINO = 8
    CP_SYS_ABOUT = 9

    # 时间语言 (16-31)
    CP_DT = 16
    CP_DT_AREA = 17
    CP_DT_DAT = 18

    # 账户 (32-47)
    CP_ACNT = 32
    CP_ACNT_CLOUD = 33
    CP_ACNT_USERINFO = 34
    CP_ACNT_BIOMETRICS = 35
    CP_ACNT_LOGINOPTION = 36

    # 设备 (48-63)
    CP_DEV = 48
    CP_DEV_AUDIO = 49
    CP_DEV_KEYBOARD = 50
    CP_DEV_MOUSE = 51
    CP_DEV_PRINTER = 52
    CP_DEV_SHORTCUT = 53
    CP_DEV_TOUCHPAD = 54
    CP_DEV_BLUETOOTH = 55
    CP_DEV_PROJECTION = 56

    # 网络 (64-79)
    CP_NET = 64
    CP_NET_CONNECT = 65
    CP_NET_PROXY = 66
    CP_NET_VINO = 67
    CP_NET_VPN = 68
    CP_NET_WLAN = 69
    CP_NET_HOTSPOT = 70

    # 个性化 (96-111)
    CP_PERSONAL = 96
    CP_PERSONAL_BACKGROUND = 97
    CP_PERSONAL_FONTS = 98
    CP_PERSONAL_SCREENLOCK = 99
    CP_PERSONAL_SCREENSAVER = 100
    CP_PERSONAL_THEME = 101

    # 更新 (112-127)
    CP_UPDATE = 112
    CP_UPDATE_BACKUP = 113
    CP_UPDATE_UPGRADE = 115

    # 安全 (128-143)
    CP_SECURITY = 128
    CP_SECURITY_DEFENDER = 129

    # 应用 (144-159)
    CP_APP = 144
    CP_APP_AUTOBOOT = 145
    CP_APP_DEFAULT = 146

    # 搜索 (160-175)
    CP_SEARCH = 160
    CP_SEARCH_SEARCH = 161

    # 通用 (176-191)
    CP_COMMON = 176
    CP_COMMON_BOOT = 177

    # 禁止操作模块（大于 1024，用于禁用功能）
    KYSDK_MODULE_DISABLED_MODIFY = 1 << 10  # 1024

    @classmethod
    def disabled(cls, module_id: int) -> int:
        """获取模块的禁用操作 ID"""
        return cls.KYSDK_MODULE_DISABLED_MODIFY | module_id


# 状态常量 (与 kylin_desktop_control_server.py 一致)
STATUS_HIDE = 0
STATUS_VISIBLE = 1
STATUS_DISABLED = 2
STATUS_ENABLED = 3


# ---------------------------------------------------------------------------
# Availability
# ---------------------------------------------------------------------------

def is_available() -> bool:
    """True if libkydesktopctrl.so loaded."""
    return _lib is not None


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _ok(msg: str) -> Tuple[bool, str]:
    return True, msg


def _err(msg: str) -> Tuple[bool, str]:
    return False, msg


def _call(fn, *args) -> Tuple[bool, str]:
    """Invoke a ctypes function, returning (ok, ret). Never raises."""
    try:
        ret = fn(*args)
        return True, ret
    except Exception as e:  # ctypes can raise OSError/ValueError
        logger.error("SDK 调用异常: %s", e)
        return False, f"SDK 调用异常: {e}"


def _path_arg(path: str) -> bytes:
    """Encode a filesystem path to bytes for c_char_p."""
    return path.encode("utf-8")


# ---------------------------------------------------------------------------
# Control panel
# ---------------------------------------------------------------------------

def set_module_visible(module_id: int, visible: bool) -> Tuple[bool, str]:
    """显示/隐藏控制面板模块."""
    if _lib is None:
        return _err("libkydesktopctrl 不可用")
    ok, ret = _call(_lib.kdk_controplpanel_set_module_visible, int(module_id), bool(visible))
    if ok and ret == 0:
        return _ok(f"控制面板模块 {module_id} 已{'显示' if visible else '隐藏'} (SDK)")
    return _err(f"设置模块可见性失败 (SDK 返回 {ret})")


def get_module_visible(module_id: int) -> Tuple[bool, Any]:
    """查询控制面板模块是否可见. 成功返回 (True, bool)."""
    if _lib is None:
        return _err("libkydesktopctrl 不可用")
    ok, ret = _call(_lib.kdk_controlpanel_get_module_visible, int(module_id))
    if ok:
        return True, bool(ret)
    return False, str(ret)


def get_module_enable(module_id: int) -> Tuple[bool, Any]:
    """查询控制面板模块是否启用. 成功返回 (True, bool)."""
    if _lib is None:
        return _err("libkydesktopctrl 不可用")
    ok, ret = _call(_lib.kdk_controlpanel_get_module_enable, int(module_id))
    if ok:
        return True, bool(ret)
    return False, str(ret)


def set_module_status(module_id: int, status: int) -> Tuple[bool, str]:
    """设置控制面板模块状态 (0隐藏/1可见/2禁用/3启用)."""
    if _lib is None:
        return _err("libkydesktopctrl 不可用")
    if status not in (STATUS_HIDE, STATUS_VISIBLE, STATUS_DISABLED, STATUS_ENABLED):
        return _err(f"无效状态: {status} (有效值 0-3)")
    ok, ret = _call(_lib.kdk_controplpanel_set_module_status, int(module_id), int(status))
    if ok and ret == 0:
        return _ok(f"控制面板模块 {module_id} 状态已设为 {status} (SDK)")
    return _err(f"设置模块状态失败 (SDK 返回 {ret})")


# ---------------------------------------------------------------------------
# Power settings (desktop idle hungup / close-display)
# ---------------------------------------------------------------------------

def set_desktop_idle_hungup(seconds: int) -> Tuple[bool, str]:
    """设置台式机系统空闲多少秒后挂起."""
    if _lib is None:
        return _err("libkydesktopctrl 不可用")
    try:
        sec = int(seconds)
    except (TypeError, ValueError):
        return _err(f"无效秒数: {seconds}")
    ok, ret = _call(_lib.kdk_powersetting_set_desktop_idle_hungup, sec)
    if ok and ret == 0:
        return _ok(f"已设置: 空闲 {sec}s 后挂起 (SDK)")
    return _err(f"设置挂起空闲时间失败 (SDK 返回 {ret})")


def get_desktop_idle_hungup() -> Tuple[bool, Any]:
    """获取台式机挂起前的空闲时间(秒). 成功返回 (True, int)."""
    if _lib is None:
        return _err("libkydesktopctrl 不可用")
    ok, ret = _call(_lib.kdk_powersetting_get_desktop_idle_hungup)
    if ok:
        return True, int(ret)
    return False, str(ret)


def set_desktop_idle_closedisplay(seconds: int) -> Tuple[bool, str]:
    """设置台式机系统空闲多少秒后关闭显示器."""
    if _lib is None:
        return _err("libkydesktopctrl 不可用")
    try:
        sec = int(seconds)
    except (TypeError, ValueError):
        return _err(f"无效秒数: {seconds}")
    ok, ret = _call(_lib.kdk_powersetting_set_desktop_idle_closedisplay, sec)
    if ok and ret == 0:
        return _ok(f"已设置: 空闲 {sec}s 后关闭显示器 (SDK)")
    return _err(f"设置关闭显示器空闲时间失败 (SDK 返回 {ret})")


def get_desktop_idle_closedisplay() -> Tuple[bool, Any]:
    """获取台式机关闭显示器前的空闲时间(秒). 成功返回 (True, int)."""
    if _lib is None:
        return _err("libkydesktopctrl 不可用")
    ok, ret = _call(_lib.kdk_powersetting_get_desktop_idle_closedisplay)
    if ok:
        return True, int(ret)
    return False, str(ret)


# ---------------------------------------------------------------------------
# Screensaver
# ---------------------------------------------------------------------------

def screensaver_set_file(path: str) -> Tuple[bool, str]:
    """设置屏保图片."""
    if _lib is None:
        return _err("libkydesktopctrl 不可用")
    ok, ret = _call(_lib.kdk_screensaver_set_file, _path_arg(path))
    if ok and ret == 0:
        return _ok(f"屏保图片已设置: {path} (SDK)")
    return _err(f"设置屏保图片失败 (SDK 返回 {ret})")


def screensaver_enable() -> Tuple[bool, str]:
    if _lib is None:
        return _err("libkydesktopctrl 不可用")
    ok, ret = _call(_lib.kdk_screensaver_enable)
    if ok and ret == 0:
        return _ok("屏保已启用 (SDK)")
    return _err(f"启用屏保失败 (SDK 返回 {ret})")


def screensaver_disable() -> Tuple[bool, str]:
    if _lib is None:
        return _err("libkydesktopctrl 不可用")
    ok, ret = _call(_lib.kdk_screensaver_disable)
    if ok and ret == 0:
        return _ok("屏保已禁用 (SDK)")
    return _err(f"禁用屏保失败 (SDK 返回 {ret})")


def screensaver_autolock_enable() -> Tuple[bool, str]:
    if _lib is None:
        return _err("libkydesktopctrl 不可用")
    ok, ret = _call(_lib.kdk_screensaver_autolock_enable)
    if ok and ret == 0:
        return _ok("自动锁屏已启用 (SDK)")
    return _err(f"启用自动锁屏失败 (SDK 返回 {ret})")


def screensaver_autolock_disable() -> Tuple[bool, str]:
    if _lib is None:
        return _err("libkydesktopctrl 不可用")
    ok, ret = _call(_lib.kdk_screensaver_autolock_disable)
    if ok and ret == 0:
        return _ok("自动锁屏已禁用 (SDK)")
    return _err(f"禁用自动锁屏失败 (SDK 返回 {ret})")


def screensaver_set_idlelock_time(seconds: int) -> Tuple[bool, str]:
    """设置自动锁屏时间(秒)."""
    if _lib is None:
        return _err("libkydesktopctrl 不可用")
    try:
        sec = int(seconds)
    except (TypeError, ValueError):
        return _err(f"无效秒数: {seconds}")
    ok, ret = _call(_lib.kdk_screensaver_idlelock_time, sec)
    if ok and ret == 0:
        return _ok(f"自动锁屏时间已设为 {sec}s (SDK)")
    return _err(f"设置自动锁屏时间失败 (SDK 返回 {ret})")


def screensaver_set_autolock_time(seconds: int) -> Tuple[bool, str]:
    """设置自动屏保时间(秒)."""
    if _lib is None:
        return _err("libkydesktopctrl 不可用")
    try:
        sec = int(seconds)
    except (TypeError, ValueError):
        return _err(f"无效秒数: {seconds}")
    ok, ret = _call(_lib.kdk_screensaver_autolock_time, sec)
    if ok and ret == 0:
        return _ok(f"自动屏保时间已设为 {sec}s (SDK)")
    return _err(f"设置自动屏保时间失败 (SDK 返回 {ret})")


# ---------------------------------------------------------------------------
# Wallpaper
# ---------------------------------------------------------------------------

def wallpaper_set_file(path: str) -> Tuple[bool, str]:
    """设置桌面壁纸."""
    if _lib is None:
        return _err("libkydesktopctrl 不可用")
    ok, ret = _call(_lib.kdk_wallpaper_set_file, _path_arg(path))
    if ok and ret == 0:
        return _ok(f"桌面壁纸已设置: {path} (SDK)")
    return _err(f"设置壁纸失败 (SDK 返回 {ret})")


# ---------------------------------------------------------------------------
# Watermark
# ---------------------------------------------------------------------------

def watermark_create(name: str) -> Tuple[bool, str]:
    """创建水印."""
    if _lib is None:
        return _err("libkydesktopctrl 不可用")
    ok, ret = _call(_lib.kdk_watermark_create, _path_arg(name))
    if ok and ret == 0:
        return _ok(f"水印已创建: {name} (SDK)")
    return _err(f"创建水印失败 (SDK 返回 {ret})")


def watermark_delete(name: str) -> Tuple[bool, str]:
    """删除水印."""
    if _lib is None:
        return _err("libkydesktopctrl 不可用")
    ok, ret = _call(_lib.kdk_watermark_delete, _path_arg(name))
    if ok and ret == 0:
        return _ok(f"水印已删除: {name} (SDK)")
    return _err(f"删除水印失败 (SDK 返回 {ret})")


def watermark_set_visible(name: str, visible: bool) -> Tuple[bool, str]:
    """设置水印是否可视."""
    if _lib is None:
        return _err("libkydesktopctrl 不可用")
    ok, ret = _call(_lib.kdk_watermark_set_visibe, _path_arg(name), bool(visible))
    if ok and ret == 0:
        return _ok(f"水印 {name} 已{'显示' if visible else '隐藏'} (SDK)")
    return _err(f"设置水印可见性失败 (SDK 返回 {ret})")


def watermark_get_visible(name: str) -> Tuple[bool, Any]:
    """获取水印是否可视. 成功返回 (True, bool)."""
    if _lib is None:
        return _err("libkydesktopctrl 不可用")
    ok, ret = _call(_lib.kdk_watermark_get_visibe, _path_arg(name))
    if ok:
        return True, bool(ret)
    return False, str(ret)


# ---------------------------------------------------------------------------
# Convenience summary for tool descriptions / debugging
# ---------------------------------------------------------------------------

def summary() -> str:
    parts = [f"desktop_ctrl={'✓' if _lib is not None else '✗'}"]
    if _lib is not None:
        parts.append("libkydesktopctrl loaded")
    return " | ".join(parts)
