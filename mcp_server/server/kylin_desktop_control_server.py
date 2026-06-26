#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
麒麟桌面管控 MCP Server
提供控制面板模块可见性控制功能
基于 libkydesktopctrl.so C 接口

功能：
- 查询控制面板模块是否可见
- 设置控制面板模块可见性（显示/隐藏）
- 设置控制面板模块状态（隐藏/可见/禁用/启用）
- 禁用/启用特定系统功能（如蓝牙、打印机等）
"""

import ctypes
import json
import logging
import sys
import os
from typing import Dict, Any, Optional

from mcp.server.fastmcp import FastMCP

logging.basicConfig(stream=sys.stderr, level=logging.INFO)
logger = logging.getLogger(__name__)

mcp = FastMCP("KylinDesktopControl")

# ============================================================================
# 加载动态库（在模块加载时直接加载）
# ============================================================================

LIB_PATH = "/usr/lib/kysdk/kysdk-security/libkydesktopctrl.so"

# 检查库文件是否存在
if not os.path.exists(LIB_PATH):
    logger.error(f"库文件不存在: {LIB_PATH}")
    lib = None
else:
    try:
        lib = ctypes.CDLL(LIB_PATH)

        # 声明函数
        lib.kdk_controlpanel_get_module_visible.argtypes = [ctypes.c_int]
        lib.kdk_controlpanel_get_module_visible.restype = ctypes.c_bool

        lib.kdk_controplpanel_set_module_visible.argtypes = [ctypes.c_int, ctypes.c_bool]
        lib.kdk_controplpanel_set_module_visible.restype = ctypes.c_int

        lib.kdk_controplpanel_set_module_status.argtypes = [ctypes.c_int, ctypes.c_int]
        lib.kdk_controplpanel_set_module_status.restype = ctypes.c_int

        logger.info(f"✅ 桌面管控库加载成功: {LIB_PATH}")
    except Exception as e:
        lib = None
        logger.error(f"❌ 库加载失败: {e}")


# ============================================================================
# 模块 ID 枚举（根据文档）
# ============================================================================

class ModuleID:
    """控制面板模块 ID"""

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


# 模块名称映射
_MODULE_NAMES = {
    ModuleID.CP_SYS_DISPLAY: "显示器",
    ModuleID.CP_SYS_POWER: "电源",
    ModuleID.CP_SYS_AUDIO: "声音",
    ModuleID.CP_DEV_KEYBOARD: "键盘",
    ModuleID.CP_DEV_MOUSE: "鼠标",
    ModuleID.CP_DEV_PRINTER: "打印机",
    ModuleID.CP_DEV_TOUCHPAD: "触摸板",
    ModuleID.CP_DEV_BLUETOOTH: "蓝牙",
    ModuleID.CP_DEV_PROJECTION: "多屏协同",
    ModuleID.CP_NET_WLAN: "无线网络",
    ModuleID.CP_NET_VPN: "VPN",
    ModuleID.CP_PERSONAL_BACKGROUND: "背景",
    ModuleID.CP_PERSONAL_THEME: "主题",
    ModuleID.CP_PERSONAL_SCREENLOCK: "锁屏",
    ModuleID.CP_UPDATE_UPGRADE: "系统更新",
    ModuleID.CP_SECURITY_DEFENDER: "安全中心",
}

# 状态常量
STATUS_HIDE = 0  # 隐藏
STATUS_VISIBLE = 1  # 可见
STATUS_DISABLED = 2  # 禁用
STATUS_ENABLED = 3  # 启用

_STATUS_NAMES = {
    STATUS_HIDE: "隐藏",
    STATUS_VISIBLE: "可见",
    STATUS_DISABLED: "禁用",
    STATUS_ENABLED: "启用",
}


# ============================================================================
# 辅助函数
# ============================================================================

def _get_module_name(module_id: int) -> str:
    """获取模块名称"""
    return _MODULE_NAMES.get(module_id, f"未知模块({module_id})")


# ============================================================================
# MCP 工具 - 直接使用 lib（和 test.py 一样）
# ============================================================================

@mcp.tool()
async def get_module_visible(module_id: int) -> str:
    """
    获取控制面板模块是否可见

    Args:
        module_id: 模块 ID（使用预定义的常量值）

    Returns:
        JSON 格式的结果，包含模块名称和可见性
    """
    if lib is None:
        return json.dumps({"error": "桌面管控库未加载，请检查是否已安装 libkysdk-desktopctrl"}, ensure_ascii=False)

    try:
        visible = lib.kdk_controlpanel_get_module_visible(module_id)

        result = {
            "module_id": module_id,
            "module_name": _get_module_name(module_id),
            "visible": visible,
            "status": "可见" if visible else "隐藏"
        }
        return json.dumps(result, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"get_module_visible 失败: {e}")
        return json.dumps({"error": str(e)}, ensure_ascii=False)


@mcp.tool()
async def set_module_visible(module_id: int, visible: bool) -> str:
    """
    设置控制面板模块是否可见（显示/隐藏）

    Args:
        module_id: 模块 ID
        visible: True=可见，False=隐藏

    Returns:
        操作结果
    """
    if lib is None:
        return json.dumps({"error": "桌面管控库未加载，请检查是否已安装 libkysdk-desktopctrl"}, ensure_ascii=False)

    try:
        ret = lib.kdk_controplpanel_set_module_visible(module_id, visible)
        logger.info(f"set_module_visible(module_id={module_id}, visible={visible}) 返回码: {ret}")

        if ret == 0 or ret == 498:
            return json.dumps({
                "success": True,
                "module_id": module_id,
                "module_name": _get_module_name(module_id),
                "action": "显示" if visible else "隐藏",
                "message": f"已{('显示' if visible else '隐藏')} {_get_module_name(module_id)}"
            }, ensure_ascii=False, indent=2)
        else:
            return json.dumps({
                "success": False,
                "error_code": ret,
                "message": f"操作失败，错误码: {ret}"
            }, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"set_module_visible 失败: {e}")
        return json.dumps({"error": str(e)}, ensure_ascii=False)


@mcp.tool()
async def set_module_status(module_id: int, status: int) -> str:
    """
    设置控制面板模块状态

    Args:
        module_id: 模块 ID
        status: 0-隐藏, 1-可见, 2-禁用, 3-启用

    Returns:
        操作结果
    """
    if lib is None:
        return json.dumps({"error": "桌面管控库未加载，请检查是否已安装 libkysdk-desktopctrl"}, ensure_ascii=False)

    try:
        if status not in _STATUS_NAMES:
            return json.dumps({
                "success": False,
                "error": f"无效的状态值: {status}，有效值: 0=隐藏,1=可见,2=禁用,3=启用"
            }, ensure_ascii=False)

        ret = lib.kdk_controplpanel_set_module_status(module_id, status)
        logger.info(f"set_module_status(module_id={module_id}, status={status}) 返回码: {ret}")

        if ret == 0:
            return json.dumps({
                "success": True,
                "module_id": module_id,
                "module_name": _get_module_name(module_id),
                "status": status,
                "status_name": _STATUS_NAMES[status],
                "message": f"已将 {_get_module_name(module_id)} 设置为 {_STATUS_NAMES[status]}"
            }, ensure_ascii=False, indent=2)
        else:
            return json.dumps({
                "success": False,
                "error_code": ret,
                "message": f"操作失败，错误码: {ret}"
            }, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"set_module_status 失败: {e}")
        return json.dumps({"error": str(e)}, ensure_ascii=False)


@mcp.tool()
async def list_common_modules() -> str:
    """列出常用的控制面板模块及其 ID"""
    modules = [
        {"id": ModuleID.CP_SYS_DISPLAY, "name": "显示器"},
        {"id": ModuleID.CP_SYS_POWER, "name": "电源"},
        {"id": ModuleID.CP_SYS_AUDIO, "name": "声音"},
        {"id": ModuleID.CP_DEV_KEYBOARD, "name": "键盘"},
        {"id": ModuleID.CP_DEV_MOUSE, "name": "鼠标"},
        {"id": ModuleID.CP_DEV_PRINTER, "name": "打印机"},
        {"id": ModuleID.CP_DEV_TOUCHPAD, "name": "触摸板"},
        {"id": ModuleID.CP_DEV_BLUETOOTH, "name": "蓝牙"},
        {"id": ModuleID.CP_DEV_PROJECTION, "name": "多屏协同"},
        {"id": ModuleID.CP_NET_WLAN, "name": "无线网络"},
        {"id": ModuleID.CP_NET_VPN, "name": "VPN"},
        {"id": ModuleID.CP_PERSONAL_BACKGROUND, "name": "背景"},
        {"id": ModuleID.CP_PERSONAL_THEME, "name": "主题"},
        {"id": ModuleID.CP_PERSONAL_SCREENLOCK, "name": "锁屏"},
        {"id": ModuleID.CP_UPDATE_UPGRADE, "name": "系统更新"},
        {"id": ModuleID.CP_SECURITY_DEFENDER, "name": "安全中心"},
    ]
    return json.dumps(modules, ensure_ascii=False, indent=2)


@mcp.tool()
async def hide_module(module_name: str) -> str:
    """
    根据模块名称隐藏控制面板模块

    Args:
        module_name: 模块名称（支持：蓝牙、打印机、触摸板、无线网络、显示器、声音等）

    Returns:
        操作结果
    """
    name_mapping = {
        "蓝牙": ModuleID.CP_DEV_BLUETOOTH,
        "打印机": ModuleID.CP_DEV_PRINTER,
        "触摸板": ModuleID.CP_DEV_TOUCHPAD,
        "键盘": ModuleID.CP_DEV_KEYBOARD,
        "鼠标": ModuleID.CP_DEV_MOUSE,
        "多屏协同": ModuleID.CP_DEV_PROJECTION,
        "无线网络": ModuleID.CP_NET_WLAN,
        "无线": ModuleID.CP_NET_WLAN,
        "WLAN": ModuleID.CP_NET_WLAN,
        "WiFi": ModuleID.CP_NET_WLAN,
        "VPN": ModuleID.CP_NET_VPN,
        "显示器": ModuleID.CP_SYS_DISPLAY,
        "显示": ModuleID.CP_SYS_DISPLAY,
        "声音": ModuleID.CP_SYS_AUDIO,
        "音量": ModuleID.CP_SYS_AUDIO,
        "电源": ModuleID.CP_SYS_POWER,
        "主题": ModuleID.CP_PERSONAL_THEME,
        "背景": ModuleID.CP_PERSONAL_BACKGROUND,
        "锁屏": ModuleID.CP_PERSONAL_SCREENLOCK,
    }
    
    module_id = name_mapping.get(module_name)
    if module_id is None:
        return json.dumps({
            "success": False,
            "error": f"未知模块名称: {module_name}",
            "supported_modules": list(name_mapping.keys())
        }, ensure_ascii=False, indent=2)
    
    # 直接调用，不经过 set_module_visible（和 test.py 一样）
    if lib is None:
        return json.dumps({"error": "桌面管控库未加载"}, ensure_ascii=False)
    
    try:
        ret = lib.kdk_controplpanel_set_module_visible(module_id, False)
        logger.info(f"hide_module: {module_name} -> module_id={module_id}, 返回码={ret}")
    
        if ret == 0:
            return json.dumps({
                "success": True,
                "module_name": module_name,
                "message": f"已隐藏 {module_name} 设置"
            }, ensure_ascii=False, indent=2)
        else:
            return json.dumps({
                "success": False,
                "error_code": ret,
                "message": f"隐藏 {module_name} 失败，错误码: {ret}"
            }, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"hide_module 异常: {e}")
        return json.dumps({"error": str(e)}, ensure_ascii=False)


@mcp.tool()
async def show_module(module_name: str) -> str:
    """
    根据模块名称显示控制面板模块

    Args:
        module_name: 模块名称（支持：蓝牙、打印机、触摸板、无线网络、显示器、声音等）

    Returns:
        操作结果
    """
    name_mapping = {
        "蓝牙": ModuleID.CP_DEV_BLUETOOTH,
        "打印机": ModuleID.CP_DEV_PRINTER,
        "触摸板": ModuleID.CP_DEV_TOUCHPAD,
        "键盘": ModuleID.CP_DEV_KEYBOARD,
        "鼠标": ModuleID.CP_DEV_MOUSE,
        "无线网络": ModuleID.CP_NET_WLAN,
        "显示器": ModuleID.CP_SYS_DISPLAY,
        "声音": ModuleID.CP_SYS_AUDIO,
        "电源": ModuleID.CP_SYS_POWER,
        "主题": ModuleID.CP_PERSONAL_THEME,
    }

    module_id = name_mapping.get(module_name)
    if module_id is None:
        return json.dumps({
            "success": False,
            "error": f"未知模块名称: {module_name}"
        }, ensure_ascii=False, indent=2)

    # 直接调用，不经过 set_module_visible（和 test.py 一样）
    if lib is None:
        return json.dumps({"error": "桌面管控库未加载"}, ensure_ascii=False)

    try:
        ret = lib.kdk_controplpanel_set_module_visible(module_id, True)
        logger.info(f"show_module: {module_name} -> module_id={module_id}, 返回码={ret}")

        if ret == 0:
            return json.dumps({
                "success": True,
                "module_name": module_name,
                "message": f"已显示 {module_name} 设置"
            }, ensure_ascii=False, indent=2)
        else:
            return json.dumps({
                "success": False,
                "error_code": ret,
                "message": f"显示 {module_name} 失败，错误码: {ret}"
            }, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"show_module 异常: {e}")
        return json.dumps({"error": str(e)}, ensure_ascii=False)


if __name__ == "__main__":
    logger.info("麒麟桌面管控 MCP 服务器启动中...")
    if lib:
        logger.info("✅ 桌面管控库加载成功，服务器就绪")
    else:
        logger.warning(f"⚠️ 桌面管控库加载失败，请检查是否已安装 libkysdk-desktopctrl")
    mcp.run()
