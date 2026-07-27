#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
麒麟操作系统 MCP 工具服务器 — 桌面控制。

SDK 迁移版本：
- 之前: ``asyncio.create_subprocess_exec(["kylin-actuator", dsl])`` + ``subprocess.run(["amixer", ...])``
- 现在: ``kylin_actions.execute_action(dsl)`` (优先 SDK/DBus，fallback 到 actuator)
"""

import os
import pwd
import re
import sys
import logging
from typing import Optional, Tuple

from mcp.server.fastmcp import FastMCP

from .kylin_actions import execute_action
from src.sdk.desktop_dbus import volume_set, volume_mute, volume_unmute, volume_up, volume_down

# 日志走 stderr，避免污染 JSON-RPC stdout
logging.basicConfig(stream=sys.stderr, level=logging.INFO)
logger = logging.getLogger(__name__)

# ============================================================
#  环境准备：XDG_RUNTIME_DIR / DISPLAY / Qt 平台
#  目标：让 MCP 下的行为尽量和你在图形终端里运行一致
# ============================================================

_ANSI_RE = re.compile(r'\x1b\[[0-9;]*m')


def _strip_ansi(s: str) -> str:
    return _ANSI_RE.sub('', s or '')


def _ensure_runtime_and_gui_env():
    uid = os.getuid()
    user = pwd.getpwuid(uid).pw_name

    # 1. XDG_RUNTIME_DIR
    rd = os.environ.get("XDG_RUNTIME_DIR")
    if not rd:
        systemd_rd = f"/run/user/{uid}"
        if os.path.isdir(systemd_rd):
            rd = systemd_rd
        else:
            rd = f"/tmp/runtime-{user}"
            os.makedirs(rd, exist_ok=True)
            try:
                os.chmod(rd, 0o700)
            except PermissionError:
                pass
        os.environ["XDG_RUNTIME_DIR"] = rd

    # 2. DISPLAY
    if not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
        os.environ.setdefault("DISPLAY", ":0")
        logger.info("未检测到 DISPLAY/WAYLAND，尝试兜底设置 DISPLAY=':0'")

    # 3. Qt platform
    if os.environ.get("QT_QPA_PLATFORM"):
        logger.info(
            "移除已有 QT_QPA_PLATFORM=%r，交由 Qt 自动选择平台",
            os.environ["QT_QPA_PLATFORM"],
        )
        os.environ.pop("QT_QPA_PLATFORM", None)

    # 4. Locale
    lang = os.environ.get("LANG", "")
    if not lang or lang.startswith(("C", "POSIX", "en")):
        os.environ["LANG"] = "zh_CN.UTF-8"
        os.environ.setdefault("LC_MESSAGES", "zh_CN.UTF-8")
        logger.info("已将 LANG/LC_MESSAGES 设置为 zh_CN.UTF-8 以启用中文界面")

    os.umask(0o077)

    logger.info(
        "最终环境: XDG_RUNTIME_DIR=%r, DISPLAY=%r, WAYLAND_DISPLAY=%r, LANG=%r, QT_QPA_PLATFORM=%r",
        os.environ.get("XDG_RUNTIME_DIR"),
        os.environ.get("DISPLAY"),
        os.environ.get("WAYLAND_DISPLAY"),
        os.environ.get("LANG"),
        os.environ.get("QT_QPA_PLATFORM"),
    )


_ensure_runtime_and_gui_env()

# ============================================================
#  DSL 路径辅助
# ============================================================

def _run_dsl(directive: str, timeout: float = 20.0) -> Tuple[int, str]:
    """
    将简单 DSL 包装为花括号形式并通过 kylin_actions 执行。
    优先走 SDK/DBus，无匹配时 fallback 到 kylin-actuator 二进制。
    """
    directive = (directive or "").strip()
    if not directive:
        return 1, "empty directive"
    if not directive.startswith("{") and not directive.endswith("}"):
        directive = "{" + directive + "}"
    return execute_action(directive, timeout=timeout)


def _dsl_quote_path(path: str) -> str:
    if re.search(r"\s", path):
        return '"' + path.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return path


# ============================================================
#  MCP 服务器工具定义
# ============================================================

mcp = FastMCP("KylinTools")
server_name = '麒麟操作系统指令'

# -------------------------------------------------------------------
# Bluetooth
# -------------------------------------------------------------------

@mcp.tool()
async def control_bluetooth(action: str) -> str:
    """
    控制蓝牙的开关状态。可用参数：open（打开），close（关闭）。
    """
    if action == 'open':
        rc, out = await _run_dsl('open bluetooth')
        return "蓝牙已打开" if rc == 0 else f"打开失败(rc={rc})：{out}"
    elif action == 'close':
        rc, out = await _run_dsl('close bluetooth')
        return "蓝牙已关闭" if rc == 0 else f"关闭失败(rc={rc})：{out}"
    else:
        return "未知的蓝牙操作"


# -------------------------------------------------------------------
# Volume (使用 desktop_dbus SDK)
# -------------------------------------------------------------------

@mcp.tool()
async def control_volume(action: str, value: Optional[int] = None) -> str:
    """
    控制系统音量。

    参数：
    - action: "set", "mute", "unmute", "open_volume", "close_volume",
              "open_maxvolume", "open_minvolume"
    - value: 当 action="set" 时的音量百分比 0~100
    """
    logger.info("control_volume: XDG_RUNTIME_DIR=%r", os.environ.get("XDG_RUNTIME_DIR"))
    try:
        if action == "set" and value is not None:
            if 0 <= value <= 100:
                success = volume_set(value)
                return f"已将音量设置为 {value}%" if success else f"设置音量失败"
            else:
                return "音量值必须在 0 到 100 之间"
        elif action == "mute":
            success = volume_mute()
            return "已静音" if success else "静音失败"
        elif action == "unmute":
            success = volume_unmute()
            return "已取消静音" if success else "取消静音失败"
        elif action == "open_volume":
            msg = volume_up()
            return msg
        elif action == "close_volume":
            msg = volume_down()
            return msg
        elif action == "open_maxvolume":
            success = volume_set(100)
            return "已将音量设置为最高" if success else "设置最高音量失败"
        elif action == "open_minvolume":
            success = volume_set(0)
            return "已将音量设置为最低" if success else "设置最低音量失败"
        else:
            return "参数错误，请提供正确的操作类型和参数"
    except Exception as e:
        return f"执行音量控制出错: {e}"


# -------------------------------------------------------------------
# Brightness
# -------------------------------------------------------------------

@mcp.tool()
async def control_brightness(action: str, brightness_value: Optional[int] = None) -> str:
    """
    控制屏幕亮度。

    支持的操作：
    - 设置亮度百分比：action="set", brightness_value=75
    - 增加亮度：action="open_brightness"
    - 降低亮度：action="close_brightness"
    - 设置最高亮度：action="open_maxbrightness"
    - 设置最低亮度：action="open_minbrightness"
    """
    try:
        if action == "set" and brightness_value is not None:
            if not isinstance(brightness_value, int):
                return "亮度值必须是一个整数。"
            if not (0 <= brightness_value <= 100):
                return "亮度值必须在 0 到 100 之间。"
            rc, out = await _run_dsl(f'set brightness {brightness_value}')
            return f"屏幕亮度已设置为 {brightness_value}%" if rc == 0 else f"设置亮度失败：{out}"
        elif action == "open_brightness":
            rc, out = await _run_dsl('open brightness')
            return "屏幕亮度已增加。" if rc == 0 else f"增加亮度失败：{out}"
        elif action == "close_brightness":
            rc, out = await _run_dsl('close brightness')
            return "屏幕亮度已降低。" if rc == 0 else f"降低亮度失败：{out}"
        elif action == "open_maxbrightness":
            rc, out = await _run_dsl('open maxbrightness')
            return "屏幕亮度已设置为最高。" if rc == 0 else f"设置最高亮度失败：{out}"
        elif action == "open_minbrightness":
            rc, out = await _run_dsl('open minbrightness')
            return "屏幕亮度已设置为最低。" if rc == 0 else f"设置最低亮度失败：{out}"
        else:
            return "参数错误，请提供正确的操作类型和参数"
    except Exception as e:
        return f"设置屏幕亮度出错: {e}"


# -------------------------------------------------------------------
# Display mode
# -------------------------------------------------------------------

@mcp.tool()
async def set_display_mode(mode: str) -> str:
    """
    设置显示模式（亮色/暗色）。可用参数：light (亮色模式)，dark (暗色模式)。
    """
    try:
        if mode == 'light':
            rc, out = await _run_dsl('set light')
            return "已设置为亮色模式。" if rc == 0 else f"设置亮色模式失败：{out}"
        elif mode == 'dark':
            rc, out = await _run_dsl('set dark')
            return "已设置为暗色模式。" if rc == 0 else f"设置暗色模式失败：{out}"
        else:
            return f"未知的显示模式: '{mode}'。请使用 'light' 或 'dark'。"
    except Exception as e:
        return f"设置显示模式出错: {e}"


# -------------------------------------------------------------------
# Mouse settings
# -------------------------------------------------------------------

@mcp.tool()
async def set_mouse_pointer_size(size: str) -> str:
    """设置鼠标指针大小。可用参数：small, medium, large。"""
    size_map = {
        'small': 'set mousesize small',
        'medium': 'set mousesize medium',
        'large': 'set mousesize large'
    }
    cmd = size_map.get(size)
    if not cmd:
        return f"未知的鼠标指针大小: '{size}'。请使用 'small', 'medium' 或 'large'。"
    rc, out = await _run_dsl(cmd)
    return f"已尝试将鼠标指针大小设置为: {size}。" if rc == 0 else f"设置鼠标指针大小失败：{out}"


@mcp.tool()
async def set_mouse_speed(speed: str) -> str:
    """设置鼠标移动速度。可用参数：slow, normal, fast。"""
    speed_map = {
        'slow': 'set mousespeed slow',
        'normal': 'set mousespeed normal',
        'fast': 'set mousespeed fast'
    }
    cmd = speed_map.get(speed)
    if not cmd:
        return f"未知的鼠标移动速度: '{speed}'。请使用 'slow', 'normal' 或 'fast'。"
    rc, out = await _run_dsl(cmd)
    return f"已尝试将鼠标移动速度设置为: {speed}。" if rc == 0 else f"设置鼠标移动速度失败：{out}"


@mcp.tool()
async def set_mouse_main_button(button: str) -> str:
    """设置鼠标主按键。可用参数：left, right。"""
    if button == 'right':
        rc, out = await _run_dsl('open mouseltohand')
        return "已尝试将鼠标主按键设置为右边。" if rc == 0 else f"设置失败：{out}"
    elif button == 'left':
        rc, out = await _run_dsl('close mouseltohand')
        return "已尝试将鼠标主按键设置为左边。" if rc == 0 else f"设置失败：{out}"
    else:
        return f"未知的鼠标主按键设置: '{button}'。请使用 'left' 或 'right'。"


@mcp.tool()
async def set_mouse_acceleration(enable: bool) -> str:
    """控制鼠标指针加速的开启或关闭。"""
    if enable:
        rc, out = await _run_dsl('open mouseacceleration')
        return "已尝试开启鼠标指针加速。" if rc == 0 else f"开启失败：{out}"
    else:
        rc, out = await _run_dsl('close mouseacceleration')
        return "已尝试关闭鼠标指针加速。" if rc == 0 else f"关闭失败：{out}"


# -------------------------------------------------------------------
# System settings & apps
# -------------------------------------------------------------------

@mcp.tool()
async def open_system_setting(setting_name: str) -> str:
    """
    打开特定的系统设置界面。
    setting_name 支持："touchpadsetting", "displaysetting", "bluetoothsetting" 等。
    """
    name = setting_name.strip()

    if name.startswith("{") and name.endswith("}"):
        dsl = name
    else:
        if name.startswith("open "):
            dsl_content = name
        else:
            dsl_content = f"open {name}"
        dsl = "{" + dsl_content + "}"

    logger.info("open_system_setting: dsl=%r", dsl)
    rc, out = await _run_dsl(dsl)
    logger.info("open_system_setting: rc=%s, out=%r", rc, out)
    return f"{out}" if rc == 0 else f"打开 {name} 失败：{out}"


@mcp.tool()
async def open_common_app(app: str) -> str:
    """
    打开常用应用或系统工具。
    可选值：'system_monitor', 'file_manager', 'browser', 'terminal',
           'calculator', 'global_search', 'bing', 'baidu', 'google'
    """
    norm = app.strip().lower().replace(" ", "_")
    mapping = {
        "system_monitor": ("open systemmonitor", "系统监视器"),
        "file_manager": ("open filemanager", "文件管理器"),
        "browser": ("open browser", "浏览器"),
        "terminal": ("open terminal", "终端"),
        "calculator": ("open calculator", "计算器"),
        "global_search": ("open globalsearch", "全局搜索"),
        "bing": ("open bingsearch", "必应搜索"),
        "baidu": ("open baidusearch", "百度搜索"),
        "google": ("open googlesearch", "Google 搜索"),
    }

    alias = {
        "sysmon": "system_monitor", "monitor": "system_monitor",
        "systemmonitor": "system_monitor", "fm": "file_manager",
        "filemanager": "file_manager", "web": "browser",
        "term": "terminal", "shell": "terminal", "calc": "calculator",
        "search": "global_search", "globalsearch": "global_search",
    }
    norm = alias.get(norm, norm)

    item = mapping.get(norm)
    if not item:
        return f"未知的应用类型: '{app}'。请使用文档中列出的 app 值。"

    directive, label = item
    rc, out = await _run_dsl(directive)
    if rc == 0:
        return f"已尝试打开 {label}。"
    return f"打开 {label} 失败(rc={rc})：{out}"


@mcp.tool()
async def open_special_directory(dir_type: str) -> str:
    """
    打开常见的系统目录（会在文件管理器中打开）。
    可选值：'root', 'temp', 'home', 'desktop', 'documents',
           'pictures', 'downloads', 'music', 'videos', 'public', 'templates'
    """
    norm = dir_type.strip().lower().replace(" ", "_")
    mapping = {
        "root": ("open rootdir", "根目录"),
        "temp": ("open tempdir", "临时目录"), "tmp": ("open tempdir", "临时目录"),
        "home": ("open homedir", "主目录"),
        "desktop": ("open desktopdir", "桌面目录"),
        "documents": ("open documentdir", "文档目录"), "docs": ("open documentdir", "文档目录"),
        "pictures": ("open imagedir", "图片目录"), "images": ("open imagedir", "图片目录"),
        "downloads": ("open downloaddir", "下载目录"), "download": ("open downloaddir", "下载目录"),
        "music": ("open musicdir", "音乐目录"),
        "videos": ("open videodir", "视频目录"), "video": ("open videodir", "视频目录"),
        "public": ("open publicdir", "公共目录"),
        "templates": ("open templatedir", "模板目录"),
    }

    item = mapping.get(norm)
    if not item:
        return f"未知的目录类型: '{dir_type}'。请使用文档中列出的 dir_type 值。"

    directive, label = item
    rc, out = await _run_dsl(directive)
    if rc == 0:
        return f"已尝试打开{label}。"
    return f"打开{label}失败(rc={rc})：{out}"


# -------------------------------------------------------------------
# WiFi / Bluetooth icon / Touchpad
# -------------------------------------------------------------------

@mcp.tool()
async def control_wifi(enable: bool) -> str:
    """控制 Wi-Fi 网络的开启或关闭。"""
    directive = "open network" if enable else "close network"
    rc, out = await _run_dsl(directive)
    if rc == 0:
        return "Wi-Fi 已打开。" if enable else "Wi-Fi 已关闭。"
    action = "打开" if enable else "关闭"
    return f"{action} Wi-Fi 失败(rc={rc})：{out}"


@mcp.tool()
async def control_bluetooth_icon(show: bool) -> str:
    """控制任务栏中的蓝牙图标显示与否。"""
    directive = "open bluetoothicon" if show else "close bluetoothicon"
    rc, out = await _run_dsl(directive)
    if rc == 0:
        return "任务栏蓝牙图标已显示。" if show else "任务栏蓝牙图标已隐藏。"
    action = "显示" if show else "隐藏"
    return f"{action}任务栏蓝牙图标失败(rc={rc})：{out}"


@mcp.tool()
async def control_touchpad(enable: bool) -> str:
    """控制触摸板（触控板）的开启或关闭。"""
    directive = "open touchpad" if enable else "close touchpad"
    rc, out = await _run_dsl(directive)
    if rc == 0:
        return "触摸板已开启。" if enable else "触摸板已关闭。"
    action = "开启" if enable else "关闭"
    return f"{action}触摸板失败(rc={rc})：{out}"


# -------------------------------------------------------------------
# Screenshot
# -------------------------------------------------------------------

@mcp.tool()
async def take_screenshot(mode: str = "full") -> str:
    """
    截图工具。参数 mode 可选值：'full' (全屏), 'area' (区域), 'window' (窗口)。
    """
    norm = mode.strip().lower()
    mapping = {
        "full": "screenshot", "screen": "screenshot", "global": "screenshot",
        "area": "areascreenshot", "region": "areascreenshot",
        "window": "windowscreenshot",
    }
    directive = mapping.get(norm)
    if not directive:
        return f"未知的截图模式: '{mode}'。请使用 'full'、'area' 或 'window'。"

    rc, out = await _run_dsl(directive)
    if rc == 0:
        if directive == "screenshot":
            return "已执行全屏截图。"
        if directive == "areascreenshot":
            return "已执行区域截图，请根据系统提示选择区域。"
        if directive == "windowscreenshot":
            return "已执行窗口截图，请根据系统提示选择窗口。"
    return f"截图命令执行失败(rc={rc})：{out}"


# -------------------------------------------------------------------
# Music
# -------------------------------------------------------------------

@mcp.tool()
async def control_music(action: str) -> str:
    """控制系统音乐播放。参数 action：'play', 'pause'。"""
    norm = action.strip().lower()
    if norm == "play":
        directive = "play music"
        label = "播放音乐"
    elif norm == "pause":
        directive = "pause"
        label = "暂停音乐"
    else:
        return f"未知的音乐控制动作: '{action}'。请使用 'play' 或 'pause'。"

    rc, out = await _run_dsl(directive)
    if rc == 0:
        return f"{label}命令已发送。"
    return f"{label}失败(rc={rc})：{out}"


# -------------------------------------------------------------------
# System info
# -------------------------------------------------------------------

@mcp.tool()
async def query_system_info(info_type: str = "basic") -> str:
    """
    查询系统关键信息（优先使用 SDK）。

    参数 info_type 可选值：'basic', 'kernel', 'cpu', 'memory', 'disk',
    'load', 'network', 'battery', 'gpu', 'fans', 'hostname', 'arch',
    'uptime', 'boot_time', 'locale'
    """
    norm = info_type.strip().lower().replace(" ", "_")
    mapping = {
        "basic": "show versioninfo", "os": "show versioninfo",
        "kernel": "show kernelinfo",
        "cpu": "show cpuinfo",
        "memory": "do showmemoryusagepercentageoverall",
        "mem": "do showmemoryusagepercentageoverall",
        "disk": "do getfreediskspace",
        "load": "do getsystemloadaverage",
        "network": "show ifconfiginfo", "net": "show ifconfiginfo",
        "battery": "do getbatterychargelevel",
        "battery_level": "do getbatterychargelevel",
        "battery_cycles": "do getbatterycyclecount",
        "gpu": "do showgpuinformation",
        "fans": "do getfanspeedsummary",
        "hostname": "do gethostname",
        "arch": "do getsystemarchitecture",
        "architecture": "do getsystemarchitecture",
        "uptime": "do showsystemuptime",
        "boot_time": "do showsystemboottime",
        "boottime": "do showsystemboottime",
        "locale": "do getsystemlocale",
    }

    directive = mapping.get(norm)
    if not directive:
        return (
            f"未知的系统信息类型: '{info_type}'。"
            "请使用文档中列出的 info_type 值（如 'basic'、'cpu'、'memory' 等）。"
        )

    rc, out = await _run_dsl(directive)
    if rc == 0:
        return out
    return f"查询系统信息 '{info_type}' 失败(rc={rc})：{out}"


# -------------------------------------------------------------------
# Desktop background
# -------------------------------------------------------------------

@mcp.tool()
async def set_desktop_background(image_path: str) -> str:
    """
    设置桌面背景（壁纸）。

    参数：
    - image_path: 图片文件路径（建议绝对路径），例如 /home/kylin/图片/test.png
    """
    try:
        if not image_path or not image_path.strip():
            return "请提供图片路径 image_path。"

        raw = image_path.strip()
        if raw.startswith("file://"):
            raw = raw[7:]

        p = os.path.realpath(
            os.path.abspath(os.path.expanduser(os.path.expandvars(raw)))
        )

        if any(x in p for x in ("{", "}", "\n", "\r", "\0")):
            return "图片路径包含非法字符（{ } 或换行等）。"

        if not os.path.exists(p):
            return f"图片文件不存在：{p}"
        if not os.path.isfile(p):
            return f"不是一个普通文件：{p}"

        dsl_path = _dsl_quote_path(p)
        rc, out = await _run_dsl(f"set background {dsl_path}")
        return "桌面背景已设置。" if rc == 0 else f"设置桌面背景失败(rc={rc})：{out}"

    except Exception as e:
        logger.exception("set_desktop_background error")
        return f"设置桌面背景出错: {e}"


if __name__ == "__main__":
    mcp.run()
