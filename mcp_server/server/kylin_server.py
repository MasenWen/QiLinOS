#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import pwd
import re
import sys
import asyncio
import logging
from typing import Optional, Tuple

from mcp.server.fastmcp import FastMCP
import subprocess

# 日志走 stderr，避免污染 JSON-RPC stdout
logging.basicConfig(stream=sys.stderr, level=logging.INFO)

# ============================================================
#  环境准备：XDG_RUNTIME_DIR / DISPLAY / Qt 平台
#  目标：让 MCP 下的行为尽量和你在图形终端里运行一致
# ============================================================

def _ensure_runtime_and_gui_env():
    uid = os.getuid()
    user = pwd.getpwuid(uid).pw_name

    # 1. XDG_RUNTIME_DIR：优先使用 /run/user/<uid>
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

    # 2. DISPLAY：如果没有，就尝试兜底为 :0（和你平时桌面一致）
    if not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
        # 这里直接猜 DISPLAY=':0'，相当于模拟你在图形终端里的环境
        os.environ.setdefault("DISPLAY", ":0")
        logging.info("未检测到 DISPLAY/WAYLAND，尝试兜底设置 DISPLAY=':0'")

    # 3. 不强行设置 QT_QPA_PLATFORM，让 Qt 自己选 (xcb/wayland)
    if os.environ.get("QT_QPA_PLATFORM"):
        logging.info(
            "移除已有 QT_QPA_PLATFORM=%r，交由 Qt 自动选择平台",
            os.environ["QT_QPA_PLATFORM"],
        )
        os.environ.pop("QT_QPA_PLATFORM", None)

    # 4. 补上中文语言环境（locale）
    lang = os.environ.get("LANG", "")
    if not lang or lang.startswith(("C", "POSIX", "en")):
        os.environ["LANG"] = "zh_CN.UTF-8"
        os.environ.setdefault("LC_MESSAGES", "zh_CN.UTF-8")
        # 如果你系统里本来就用 LC_ALL，可以顺带设一下：
        # os.environ.setdefault("LC_ALL", "zh_CN.UTF-8")
        logging.info("已将 LANG/LC_MESSAGES 设置为 zh_CN.UTF-8 以启用中文界面")

    os.umask(0o077)

    logging.info(
        "最终环境: XDG_RUNTIME_DIR=%r, DISPLAY=%r, WAYLAND_DISPLAY=%r, LANG=%r, QT_QPA_PLATFORM=%r",
        os.environ.get("XDG_RUNTIME_DIR"),
        os.environ.get("DISPLAY"),
        os.environ.get("WAYLAND_DISPLAY"),
        os.environ.get("LANG"),
        os.environ.get("QT_QPA_PLATFORM"),
    )


_ensure_runtime_and_gui_env()

# ============================================================
#  执行器桥：调用 kylin-actuator + 纯命令行工具
# ============================================================

_ANSI_RE = re.compile(r'\x1b\[[0-9;]*m')

def _strip_ansi(s: str) -> str:
    return _ANSI_RE.sub('', s or '')

async def call_actuator(input_dsl: str, timeout: float = 20.0) -> Tuple[int, str]:
    """
    统一调用 kylin-actuator（异步）。
    传入整串花括号 DSL：'{open bluetooth}' 或 '{open touchpadsetting}'。
    返回：(returncode, output)
      - 优先拼接 <AI> 之后的文本
      - 若未出现 <AI>，返回净化后的原始输出
    """
    env = os.environ.copy()

    # 这里尽量模拟你之前在终端里运行的方式：
    #   kylin-actuator "{open touchpadsetting}"
    cmd = ["kylin-actuator", input_dsl]

    logging.info(
        "call_actuator: cmd=%r, DISPLAY=%r, QT_QPA_PLATFORM=%r",
        cmd, env.get("DISPLAY"), env.get("QT_QPA_PLATFORM"),
    )

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )

    parsed: list[str] = []
    raw_lines: list[str] = []

    async def reader():
        while True:
            line = await proc.stdout.readline()
            if not line:
                break
            clean = _strip_ansi(line.decode("utf-8", "replace")).rstrip("\n")
            raw_lines.append(clean)
            if "<AI>" in clean:
                parsed.append(clean.split("<AI>", 1)[1].strip())
            if "<end>" in clean:
                break

    try:
        await asyncio.wait_for(reader(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.terminate()
        try:
            await asyncio.wait_for(proc.wait(), 2)
        except Exception:
            proc.kill()
        return 124, "timeout"

    try:
        _, err = await asyncio.wait_for(proc.communicate(), 0.1)
        if err:
            raw_lines.append(_strip_ansi(err.decode("utf-8", "replace")))
    except Exception:
        pass

    rc = proc.returncode or 0
    body = "\n".join(parsed).strip() or "\n".join(raw_lines).strip()
    if not body:
        body = "ok"

    logging.info("call_actuator done: rc=%s, body=%r", rc, body)
    return rc, body

def run_cmd_safely(cmd: list[str]) -> Tuple[int, str]:
    """同步命令安全执行（如 amixer），完全截获输出。"""
    env = os.environ.copy()
    p = subprocess.run(
        cmd,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )
    out = _strip_ansi(p.stdout or "").strip()
    err = _strip_ansi(p.stderr or "").strip()
    return p.returncode, (out if out else err)

def _run_dsl(directive: str, timeout: float = 20.0) -> Tuple[int, str]:
    """
    将简单 DSL（例如 "show versioninfo" 或 "do gethostname"）包装成
    花括号形式并调用 kylin-actuator。
    """
    directive = (directive or "").strip()
    if not directive:
        return 1, "empty directive"
    # 已经包含花括号就直接用
    if directive.startswith("{") and directive.endswith("}"):
        dsl = directive
    else:
        dsl = "{" + directive + "}"
    return  call_actuator(dsl, timeout=timeout)

def _dsl_quote_path(path: str) -> str:
    if re.search(r"\s", path):
        return '"' + path.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return path

# ============================================================
#  MCP 服务器工具定义
# ============================================================

mcp = FastMCP("KylinTools")
server_name = '麒麟操作系统指令'

@mcp.tool()
async def control_bluetooth(action: str) -> str:
    """
    控制蓝牙的开关状态。可用参数：open（打开），close（关闭）。例如：
    - 打开蓝牙 → action='open'
    - 关闭蓝牙 → action='close'
    """
    if action == 'open':
        rc, out = await call_actuator('{open bluetooth}')
        return "蓝牙已打开" if rc == 0 else f"打开失败(rc={rc})：{out}"
    elif action == 'close':
        rc, out = await call_actuator('{close bluetooth}')
        return "蓝牙已关闭" if rc == 0 else f"关闭失败(rc={rc})：{out}"
    else:
        return "未知的蓝牙操作"

@mcp.tool()
async def control_volume(action: str, value: Optional[int] = None) -> str:
    """
    控制系统音量。

    参数：
    - action: 只能是以下之一：
        "set", "mute", "unmute",
        "open_volume", "close_volume",
        "open_maxvolume", "open_minvolume"
      （会自动兼容 "最大音量"/"max"/"取消静音" 等常见写法）
    - value: 当 action="set" 时的音量百分比 0~100

    返回：操作执行结果
    """
    logging.info("control_volume: XDG_RUNTIME_DIR=%r", os.environ.get("XDG_RUNTIME_DIR"))
    try:
        if action == "set" and value is not None:
            if 0 <= value <= 100:
                rc, out = run_cmd_safely(["amixer", "set", "Master", f"{value}%"])
                return f"已将音量设置为 {value}%" if rc == 0 else f"设置失败：{out}"
            else:
                return "音量值必须在 0 到 100 之间"
        elif action == "mute":
            rc, out = run_cmd_safely(["amixer", "set", "Master", "mute"])
            return "已静音" if rc == 0 else f"静音失败：{out}"
        elif action == "unmute":
            rc, out = run_cmd_safely(["amixer", "set", "Master", "unmute"])
            return "已取消静音" if rc == 0 else f"取消静音失败：{out}"
        elif action == "open_volume":
            rc, out = await call_actuator('{open volume}')
            return "已增加音量" if rc == 0 else f"增加音量失败：{out}"
        elif action == "close_volume":
            rc, out = await call_actuator('{close volume}')
            return "已降低音量" if rc == 0 else f"降低音量失败：{out}"
        elif action == "open_maxvolume":
            rc, out = await call_actuator('{open maxvolume}')
            return "已将音量设置为最高" if rc == 0 else f"设置最高音量失败：{out}"
        elif action == "open_minvolume":
            rc, out = await call_actuator('{open minvolume}')
            return "已将音量设置为最低" if rc == 0 else f"设置最低音量失败：{out}"
        else:
            return "参数错误，请提供正确的操作类型和参数"
    except Exception as e:
        return f"执行音量控制出错: {e}"

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

    返回：操作执行结果
    """
    try:
        if action == "set" and brightness_value is not None:
            if not isinstance(brightness_value, int):
                return "亮度值必须是一个整数。"
            if not (0 <= brightness_value <= 100):
                return "亮度值必须在 0 到 100 之间。"
            rc, out = await call_actuator(f'{{set brightness {brightness_value}}}')
            return f"屏幕亮度已设置为 {brightness_value}%" if rc == 0 else f"设置亮度失败：{out}"
        elif action == "open_brightness":
            rc, out = await call_actuator('{open brightness}')
            return "屏幕亮度已增加。" if rc == 0 else f"增加亮度失败：{out}"
        elif action == "close_brightness":
            rc, out = await call_actuator('{close brightness}')
            return "屏幕亮度已降低。" if rc == 0 else f"降低亮度失败：{out}"
        elif action == "open_maxbrightness":
            rc, out = await call_actuator('{open maxbrightness}')
            return "屏幕亮度已设置为最高。" if rc == 0 else f"设置最高亮度失败：{out}"
        elif action == "open_minbrightness":
            rc, out = await call_actuator('{open minbrightness}')
            return "屏幕亮度已设置为最低。" if rc == 0 else f"设置最低亮度失败：{out}"
        else:
            return "参数错误，请提供正确的操作类型和参数"
    except Exception as e:
        return f"设置屏幕亮度出错: {e}"

@mcp.tool()
async def set_display_mode(mode: str) -> str:
    """
    设置显示模式（亮色/暗色）。可用参数：light (亮色模式)，dark (暗色模式)。例如：
    - 切换到暗色模式 → mode='dark'
    - 切换到亮色模式 → mode='light'
    """
    try:
        if mode == 'light':
            rc, out = await call_actuator('{set light}')
            return "已设置为亮色模式。" if rc == 0 else f"设置亮色模式失败：{out}"
        elif mode == 'dark':
            rc, out = await call_actuator('{set dark}')
            return "已设置为暗色模式。" if rc == 0 else f"设置暗色模式失败：{out}"
        else:
            return f"未知的显示模式: '{mode}'。请使用 'light' 或 'dark'。"
    except Exception as e:
        return f"设置显示模式出错: {e}"

@mcp.tool()
async def set_mouse_pointer_size(size: str) -> str:
    """
    设置鼠标指针大小。可用参数：small (小), medium (中), large (大)。
    """
    size_map = {
        'small': '{set mousesize small}',
        'medium': '{set mousesize medium}',
        'large': '{set mousesize large}'
    }
    cmd = size_map.get(size)
    if not cmd:
        return f"未知的鼠标指针大小: '{size}'。请使用 'small', 'medium' 或 'large'。"
    rc, out = await call_actuator(cmd)
    return f"已尝试将鼠标指针大小设置为: {size}。" if rc == 0 else f"设置鼠标指针大小失败：{out}"

@mcp.tool()
async def set_mouse_speed(speed: str) -> str:
    """
    设置鼠标移动速度。可用参数：slow (缓慢), normal (中等), fast (最快)。
    """
    speed_map = {
        'slow': '{set mousespeed slow}',
        'normal': '{set mousespeed normal}',
        'fast': '{set mousespeed fast}'
    }
    cmd = speed_map.get(speed)
    if not cmd:
        return f"未知的鼠标移动速度: '{speed}'。请使用 'slow', 'normal' 或 'fast'。"
    rc, out = await call_actuator(cmd)
    return f"已尝试将鼠标移动速度设置为: {speed}。" if rc == 0 else f"设置鼠标移动速度失败：{out}"

@mcp.tool()
async def set_mouse_main_button(button: str) -> str:
    """
    设置鼠标主按键。可用参数：left (左边), right (右边)。
    """
    if button == 'right':
        rc, out = await call_actuator('{open mouseltohand}')
        return "已尝试将鼠标主按键设置为右边。" if rc == 0 else f"设置失败：{out}"
    elif button == 'left':
        rc, out = await call_actuator('{close mouseltohand}')
        return "已尝试将鼠标主按键设置为左边。" if rc == 0 else f"设置失败：{out}"
    else:
        return f"未知的鼠标主按键设置: '{button}'。请使用 'left' 或 'right'。"

@mcp.tool()
async def set_mouse_acceleration(enable: bool) -> str:
    """
    控制鼠标指针加速的开启或关闭。可用参数：True (开启), False (关闭)。
    """
    if enable:
        rc, out = await call_actuator('{open mouseacceleration}')
        return "已尝试开启鼠标指针加速。" if rc == 0 else f"开启失败：{out}"
    else:
        rc, out = await call_actuator('{close mouseacceleration}')
        return "已尝试关闭鼠标指针加速。" if rc == 0 else f"关闭失败：{out}"

@mcp.tool()
async def open_system_setting(setting_name: str) -> str:
    """
    打开特定的系统设置界面。

    setting_name 支持两种写法：
    1）只写关键字：
        - "touchpadsetting"
        - "displaysetting"
        - "bluetoothsetting"
        ...
    2）写完整 DSL 片段（不带花括号）：
        - "open touchpadsetting"
        - "open displaysetting"
        - "open bluetoothsetting"
    """
    name = setting_name.strip()

    # 已经写成 "{open xxx}" 的情况，直接用
    if name.startswith("{") and name.endswith("}"):
        dsl = name
    else:
        # 如果已经带 "open " 前缀，就不要再加一次
        if name.startswith("open "):
            dsl_content = name
        else:
            dsl_content = f"open {name}"
        dsl = "{" + dsl_content + "}"

    logging.info("open_system_setting: dsl=%r", dsl)
    rc, out = await call_actuator(dsl)
    logging.info("open_system_setting: rc=%s, out=%r", rc, out)

    return f"{out}" if rc == 0 else f"打开 {name} 失败：{out}"

@mcp.tool()
async def open_common_app(app: str) -> str:
    """
    打开常用应用或系统工具。

    参数 app 可选值（不区分大小写，下划线和空格等价）：
    - 'system_monitor' : 系统监视器           (open systemmonitor)
    - 'file_manager'   : 文件管理器           (open filemanager)
    - 'browser'        : 默认浏览器           (open browser)
    - 'terminal'       : 终端                 (open terminal)
    - 'calculator'     : 计算器               (open calculator)
    - 'global_search'  : 全局搜索             (open globalsearch)
    - 'bing'           : 必应搜索             (open bingsearch)
    - 'baidu'          : 百度搜索             (open baidusearch)
    - 'google'         : Google 搜索          (open googlesearch)
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

    # 一些常见别名
    alias = {
        "sysmon": "system_monitor",
        "monitor": "system_monitor",
        "systemmonitor": "system_monitor",
        "fm": "file_manager",
        "filemanager": "file_manager",
        "web": "browser",
        "term": "terminal",
        "shell": "terminal",
        "calc": "calculator",
        "search": "global_search",
        "globalsearch": "global_search",
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

    参数 dir_type 可选值（不区分大小写，下划线和空格等价）：
    - 'root'       : 根目录        (open rootdir)
    - 'temp'       : 临时目录      (open tempdir)
    - 'home'       : 主目录        (open homedir)
    - 'desktop'    : 桌面目录      (open desktopdir)
    - 'documents'  : 文档目录      (open documentdir)
    - 'pictures'   : 图片目录      (open imagedir)
    - 'downloads'  : 下载目录      (open downloaddir)
    - 'music'      : 音乐目录      (open musicdir)
    - 'videos'     : 视频目录      (open videodir)
    - 'public'     : 公共目录      (open publicdir)
    - 'templates'  : 模板目录      (open templatedir)
    """
    norm = dir_type.strip().lower().replace(" ", "_")
    mapping = {
        "root": ("open rootdir", "根目录"),
        "temp": ("open tempdir", "临时目录"),
        "tmp": ("open tempdir", "临时目录"),
        "home": ("open homedir", "主目录"),
        "desktop": ("open desktopdir", "桌面目录"),
        "documents": ("open documentdir", "文档目录"),
        "docs": ("open documentdir", "文档目录"),
        "pictures": ("open imagedir", "图片目录"),
        "images": ("open imagedir", "图片目录"),
        "downloads": ("open downloaddir", "下载目录"),
        "download": ("open downloaddir", "下载目录"),
        "music": ("open musicdir", "音乐目录"),
        "videos": ("open videodir", "视频目录"),
        "video": ("open videodir", "视频目录"),
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

@mcp.tool()
async def control_wifi(enable: bool) -> str:
    """
    控制 Wi-Fi 网络的开启或关闭。

    - enable=True  → 'open network'（打开 Wi-Fi）
    - enable=False → 'close network'（关闭 Wi-Fi）
    """
    directive = "open network" if enable else "close network"
    rc, out = await _run_dsl(directive)
    if rc == 0:
        return "Wi-Fi 已打开。" if enable else "Wi-Fi 已关闭。"
    action = "打开" if enable else "关闭"
    return f"{action} Wi-Fi 失败(rc={rc})：{out}"


@mcp.tool()
async def control_bluetooth_icon(show: bool) -> str:
    """
    控制任务栏中的蓝牙图标显示与否。

    - show=True  → 'open bluetoothicon'（显示蓝牙图标）
    - show=False → 'close bluetoothicon'（隐藏蓝牙图标）
    """
    directive = "open bluetoothicon" if show else "close bluetoothicon"
    rc, out = await _run_dsl(directive)
    if rc == 0:
        return "任务栏蓝牙图标已显示。" if show else "任务栏蓝牙图标已隐藏。"
    action = "显示" if show else "隐藏"
    return f"{action}任务栏蓝牙图标失败(rc={rc})：{out}"


@mcp.tool()
async def control_touchpad(enable: bool) -> str:
    """
    控制触摸板（触控板）的开启或关闭。

    - enable=True  → 'open touchpad'  （开启触摸板）
    - enable=False → 'close touchpad' （关闭触摸板）
    """
    directive = "open touchpad" if enable else "close touchpad"
    rc, out = await _run_dsl(directive)
    if rc == 0:
        return "触摸板已开启。" if enable else "触摸板已关闭。"
    action = "开启" if enable else "关闭"
    return f"{action}触摸板失败(rc={rc})：{out}"

@mcp.tool()
async def take_screenshot(mode: str = "full") -> str:
    """
    截图工具。

    参数 mode 可选值（不区分大小写）：
    - 'full' / 'screen' / 'global' : 全屏截图   (screenshot)
    - 'area' / 'region'            : 区域截图   (areascreenshot)
    - 'window'                     : 窗口截图   (windowscreenshot)
    """
    norm = mode.strip().lower()
    mapping = {
        "full": "screenshot",
        "screen": "screenshot",
        "global": "screenshot",
        "area": "areascreenshot",
        "region": "areascreenshot",
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

@mcp.tool()
async def control_music(action: str) -> str:
    """
    控制系统音乐播放。

    参数 action 可选值（不区分大小写）：
    - 'play'  : 播放音乐  (play music)
    - 'pause' : 暂停音乐  (pause)
    """
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

@mcp.tool()
async def query_system_info(info_type: str = "basic") -> str:
    """
    查询系统关键信息（基于测试集 DSL 指令聚合了一些有意义的功能点）。

    参数 info_type 可选值（不区分大小写、下划线和空格等价）：
    - 'basic'     : 系统版本信息          (show versioninfo)
    - 'kernel'    : 内核详细信息          (show kernelinfo)
    - 'cpu'       : CPU 基本信息          (show cpuinfo)
    - 'memory'    : 内存整体使用百分比    (do showmemoryusagepercentageoverall)
    - 'disk'      : 剩余磁盘空间          (do getfreediskspace)
    - 'load'      : 系统平均负载          (do getsystemloadaverage)
    - 'network'   : 网络基础信息          (show ifconfiginfo)
    - 'battery'   : 电池当前电量          (do getbatterychargelevel)
    - 'battery_cycles' : 电池循环次数     (do getbatterycyclecount)
    - 'gpu'       : GPU 硬件信息          (do showgpuinformation)
    - 'fans'      : 风扇转速概览          (do getfanspeedsummary)
    - 'hostname'  : 主机名                (do gethostname)
    - 'arch'      : 系统硬件架构          (do getsystemarchitecture)
    - 'uptime'    : 系统已运行时间        (do showsystemuptime)
    - 'boot_time' : 系统启动时间点        (do showsystemboottime)
    - 'locale'    : 系统区域与本地化设置  (do getsystemlocale)
    """
    norm = info_type.strip().lower().replace(" ", "_")
    mapping = {
        "basic": "show versioninfo",
        "os": "show versioninfo",
        "kernel": "show kernelinfo",
        "cpu": "show cpuinfo",
        "memory": "do showmemoryusagepercentageoverall",
        "mem": "do showmemoryusagepercentageoverall",
        "disk": "do getfreediskspace",
        "load": "do getsystemloadaverage",
        "network": "show ifconfiginfo",
        "net": "show ifconfiginfo",
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

@mcp.tool()
async def set_desktop_background(image_path: str) -> str:
    """
    设置桌面背景（壁纸）。

    参数：
    - image_path: 图片文件路径（建议绝对路径），例如：
      /home/ok/下载/test.png
    """
    try:
        if not image_path or not image_path.strip():
            return "请提供图片路径 image_path。"

        raw = image_path.strip()
        # 允许传 file:// 开头
        if raw.startswith("file://"):
            raw = raw[7:]

        # 展开 ~ / 环境变量，并转成绝对真实路径
        p = os.path.realpath(
            os.path.abspath(os.path.expanduser(os.path.expandvars(raw)))
        )

        # 防止 DSL 注入/非法字符
        if any(x in p for x in ("{", "}", "\n", "\r", "\0")):
            return "图片路径包含非法字符（{ } 或换行等）。"

        if not os.path.exists(p):
            return f"图片文件不存在：{p}"
        if not os.path.isfile(p):
            return f"不是一个普通文件：{p}"

        dsl_path = _dsl_quote_path(p)
        rc, out = await call_actuator(f"{{set background {dsl_path}}}")
        return "桌面背景已设置。" if rc == 0 else f"设置桌面背景失败(rc={rc})：{out}"

    except Exception as e:
        logging.exception("set_desktop_background error")
        return f"设置桌面背景出错: {e}"


if __name__ == "__main__":
    mcp.run()
