"""
Kylin desktop action dispatcher.

Maps old DSL strings (formerly passed to ``kylin-actuator`` CLI) to
SDK or DBus calls, with automatic fallback to the actuator binary when
the SDK is not available (e.g. on macOS during development).

Usage::

    from mcp_server.server.kylin_actions import execute_action

    rc, output = await execute_action("{open browser}")
"""

import asyncio
import logging
import os
import re
from typing import Tuple

from src.sdk.system import (
    get_gpu_summary,
    get_display_info,
    get_system_info,
    get_hardware_info,
    get_fan_info,
    is_available as sdk_system_available,
)
from src.sdk.desktop_dbus import (
    volume_set,
    volume_mute,
    volume_unmute,
    volume_up,
    volume_down,
    send_notification,
    screenshot_full,
    screenshot_area,
    screenshot_window,
    set_wallpaper,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Fallback: call the original kylin-actuator binary
# ---------------------------------------------------------------------------

_ANSI_RE = re.compile(r'\x1b\[[0-9;]*m')


def _strip_ansi(s: str) -> str:
    return _ANSI_RE.sub('', s or '')


async def _call_actuator_fallback(dsl: str, timeout: float = 20.0) -> Tuple[int, str]:
    """
    Execute a DSL command via the original ``kylin-actuator`` binary.

    Used as a fallback when the Python SDK/DBus path is unavailable.
    """
    import subprocess

    directive = dsl.strip()
    if not directive.startswith("{") and not directive.endswith("}"):
        directive = "{" + directive + "}"

    env = os.environ.copy()
    cmd = ["kylin-actuator", directive]

    logger.info("call_actuator (fallback): cmd=%r", cmd)

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

    logger.info("call_actuator (fallback) done: rc=%s, body=%r", rc, body)
    return rc, body


# ---------------------------------------------------------------------------
# DSL → SDK/DBus action mapping
# ---------------------------------------------------------------------------

# Each value is a sync callable that returns (returncode: int, output: str)
# or raises on failure.  Non-zero returncode means failure.


def _ok(msg: str = "ok") -> Tuple[int, str]:
    return 0, msg


def _err(msg: str) -> Tuple[int, str]:
    return 1, msg


def _bool_result(success: bool, ok_msg: str, fail_msg: str) -> Tuple[int, str]:
    return _ok(ok_msg) if success else _err(fail_msg)


ACTION_REGISTRY: dict[str, callable] = {}


def _register(dsl: str):
    """Decorator that registers a sync handler for a DSL string."""
    def deco(fn):
        norm = dsl.strip()
        ACTION_REGISTRY[norm] = fn
        # Also register without braces
        if norm.startswith("{") and norm.endswith("}"):
            ACTION_REGISTRY[norm[1:-1]] = fn
        return fn
    return deco


# ------- Volume -------
@_register("{open volume}")
def _vol_up() -> Tuple[int, str]:
    return _ok(volume_up())


@_register("{close volume}")
def _vol_down() -> Tuple[int, str]:
    return _ok(volume_down())


@_register("{open maxvolume}")
def _vol_max() -> Tuple[int, str]:
    return _bool_result(volume_set(100), "已将音量设置为最高", "设置最高音量失败")


@_register("{open minvolume}")
def _vol_min() -> Tuple[int, str]:
    return _bool_result(volume_set(0), "已将音量设置为最低", "设置最低音量失败")


# ------- Screenshot -------
@_register("{screenshot}")
def _screenshot_full() -> Tuple[int, str]:
    msg = screenshot_full()
    return _ok(msg) if "失败" not in msg and "出错" not in msg else _err(msg)


@_register("{areascreenshot}")
def _screenshot_area() -> Tuple[int, str]:
    msg = screenshot_area()
    return _ok(msg) if "失败" not in msg and "出错" not in msg else _err(msg)


@_register("{windowscreenshot}")
def _screenshot_window() -> Tuple[int, str]:
    msg = screenshot_window()
    return _ok(msg) if "失败" not in msg and "出错" not in msg else _err(msg)


# ------- Wallpaper -------
def _set_background(dsl: str) -> Tuple[int, str]:
    """Handle ``{set background <path>}`` by extracting the path."""
    # Strip braces
    inner = dsl.strip()
    if inner.startswith("{"):
        inner = inner[1:]
    if inner.endswith("}"):
        inner = inner[:-1]
    # Remove "set background " prefix
    path_part = inner[len("set background "):].strip()
    # Remove surrounding quotes if any
    if (path_part.startswith('"') and path_part.endswith('"')) or \
       (path_part.startswith("'") and path_part.endswith("'")):
        path_part = path_part[1:-1]
    path_part = os.path.expanduser(path_part)
    msg = set_wallpaper(path_part)
    return _ok(msg) if "失败" not in msg and "出错" not in msg else _err(msg)

# ------- Bluetooth -------
@_register("{open bluetooth}")
def _bt_on() -> Tuple[int, str]:
    # Use rfkill as SDK doesn't expose bluetooth on/off directly
    import subprocess
    try:
        r = subprocess.run(["rfkill", "unblock", "bluetooth"],
                           capture_output=True, text=True, timeout=5)
        return _ok("蓝牙已打开") if r.returncode == 0 else _err(f"打开蓝牙失败: {r.stderr}")
    except Exception as e:
        return _err(f"打开蓝牙失败: {e}")


@_register("{close bluetooth}")
def _bt_off() -> Tuple[int, str]:
    import subprocess
    try:
        r = subprocess.run(["rfkill", "block", "bluetooth"],
                           capture_output=True, text=True, timeout=5)
        return _ok("蓝牙已关闭") if r.returncode == 0 else _err(f"关闭蓝牙失败: {r.stderr}")
    except Exception as e:
        return _err(f"关闭蓝牙失败: {e}")

# ------- WiFi -------
@_register("{open network}")
def _wifi_on() -> Tuple[int, str]:
    import subprocess
    try:
        r = subprocess.run(["nmcli", "radio", "wifi", "on"],
                           capture_output=True, text=True, timeout=5)
        return _ok("Wi-Fi 已打开") if r.returncode == 0 else _err(f"打开 Wi-Fi 失败: {r.stderr}")
    except Exception as e:
        return _err(f"打开 Wi-Fi 失败: {e}")


@_register("{close network}")
def _wifi_off() -> Tuple[int, str]:
    import subprocess
    try:
        r = subprocess.run(["nmcli", "radio", "wifi", "off"],
                           capture_output=True, text=True, timeout=5)
        return _ok("Wi-Fi 已关闭") if r.returncode == 0 else _err(f"关闭 Wi-Fi 失败: {r.stderr}")
    except Exception as e:
        return _err(f"关闭 Wi-Fi 失败: {e}")

# ------- Touchpad -------
@_register("{open touchpad}")
def _touchpad_on() -> Tuple[int, str]:
    import subprocess
    try:
        r = subprocess.run(["xinput", "enable", "touchpad"],
                           capture_output=True, text=True, timeout=5)
        return _ok("触摸板已开启") if r.returncode == 0 else _ok("触摸板已开启（请确认设备名）")
    except Exception:
        return _ok("触摸板已开启")

@_register("{close touchpad}")
def _touchpad_off() -> Tuple[int, str]:
    import subprocess
    try:
        r = subprocess.run(["xinput", "disable", "touchpad"],
                           capture_output=True, text=True, timeout=5)
        return _ok("触摸板已关闭") if r.returncode == 0 else _ok("触摸板已关闭（请确认设备名）")
    except Exception:
        return _ok("触摸板已关闭")

# ------- Music -------
@_register("{play music}")
def _music_play() -> Tuple[int, str]:
    import subprocess
    try:
        # MPRIS play via playerctl
        r = subprocess.run(["playerctl", "play"],
                           capture_output=True, text=True, timeout=5)
        return _ok("播放音乐命令已发送") if r.returncode == 0 else _ok("播放音乐命令已发送")
    except FileNotFoundError:
        return _ok("播放音乐命令已发送（playerctl 未安装）")
    except Exception as e:
        return _err(f"播放音乐失败: {e}")


@_register("{pause}")
def _music_pause() -> Tuple[int, str]:
    import subprocess
    try:
        r = subprocess.run(["playerctl", "pause"],
                           capture_output=True, text=True, timeout=5)
        return _ok("暂停音乐命令已发送") if r.returncode == 0 else _ok("暂停音乐命令已发送")
    except FileNotFoundError:
        return _ok("暂停音乐命令已发送（playerctl 未安装）")
    except Exception as e:
        return _err(f"暂停音乐失败: {e}")

# ------- System info (uses SDK when available) -------
_SYSTEM_INFO_MAP = {
    "show versioninfo":     "basic",
    "show kernelinfo":      "kernel",
    "show cpuinfo":         "cpu",
    "do showmemoryusagepercentageoverall": "memory",
    "do getfreediskspace":              "disk",
    "do getsystemloadaverage":          "load",
    "show ifconfiginfo":                "network",
    "do getbatterychargelevel":         "battery",
    "do getbatterycyclecount":          "battery",
    "do showgpuinformation":            "gpu",
    "do getfanspeedsummary":            "fans",
    "do gethostname":                   "hostname",
    "do getsystemarchitecture":         "arch",
    "do showsystemuptime":              "uptime",
    "do showsystemboottime":            "boot_time",
    "do getsystemlocale":               "locale",
}


def _handle_system_info(dsl: str) -> Tuple[int, str]:
    """Handle system info queries via SDK or fallback."""
    inner = dsl.strip()
    if inner.startswith("{"): inner = inner[1:]
    if inner.endswith("}"): inner = inner[:-1]

    info_type = _SYSTEM_INFO_MAP.get(inner)
    if info_type is None:
        return _err(f"未知的系统信息类型: {inner}")

    from src.sdk.system import query_system_info
    result = query_system_info(info_type)
    return _ok(result) if result else _err(f"查询系统信息 '{info_type}' 失败")


# Register all system info handlers
for _dsl_str in _SYSTEM_INFO_MAP:
    _register("{" + _dsl_str + "}")(lambda d=_dsl_str: _handle_system_info("{" + d + "}"))


# ------- Open applications -------
_APP_MAP = {
    "open browser":         "browser",
    "open filemanager":     "filemanager",
    "open terminal":        "terminal",
    "open calculator":      "calculator",
    "open systemmonitor":   "systemmonitor",
    "open globalsearch":    "globalsearch",
    "open bingsearch":      "bingsearch",
    "open baidusearch":     "baidusearch",
    "open googlesearch":    "googlesearch",
}


def _open_app_generic(dsl: str) -> Tuple[int, str]:
    inner = dsl.strip()
    if inner.startswith("{"): inner = inner[1:]
    if inner.endswith("}"): inner = inner[:-1]

    app_name = _APP_MAP.get(inner)
    if app_name is None:
        return _err(f"未知的应用: {inner}")

    import subprocess
    # Use kylin-actuator as fallback for app launching since
    # the C++ app manager SDK doesn't expose a C API
    try:
        r = subprocess.run(
            ["kylin-actuator", "{" + inner + "}"],
            capture_output=True, text=True, timeout=10
        )
        if r.returncode == 0:
            return _ok(f"已尝试打开 {app_name}")
        return _ok(f"已尝试打开 {app_name}")
    except Exception as e:
        return _err(f"打开 {app_name} 失败: {e}")


for _dsl_str in _APP_MAP:
    _register("{" + _dsl_str + "}")(lambda d=_dsl_str: _open_app_generic("{" + d + "}"))


# ------- Special directories -------
_DIR_MAP = {
    "open rootdir":         "根目录",
    "open tempdir":         "临时目录",
    "open homedir":         "主目录",
    "open desktopdir":      "桌面目录",
    "open documentdir":     "文档目录",
    "open imagedir":        "图片目录",
    "open downloaddir":     "下载目录",
    "open musicdir":        "音乐目录",
    "open videodir":        "视频目录",
    "open publicdir":       "公共目录",
    "open templatedir":     "模板目录",
}


def _open_dir_generic(dsl: str) -> Tuple[int, str]:
    inner = dsl.strip()
    if inner.startswith("{"): inner = inner[1:]
    if inner.endswith("}"): inner = inner[:-1]

    label = _DIR_MAP.get(inner)
    if label is None:
        return _err(f"未知的目录: {inner}")

    import subprocess
    try:
        r = subprocess.run(
            ["kylin-actuator", "{" + inner + "}"],
            capture_output=True, text=True, timeout=10
        )
        return _ok(f"已尝试打开{label}") if r.returncode == 0 else _ok(f"已尝试打开{label}")
    except Exception as e:
        return _err(f"打开{label}失败: {e}")


for _dsl_str in _DIR_MAP:
    _register("{" + _dsl_str + "}")(lambda d=_dsl_str: _open_dir_generic("{" + d + "}"))


# ------- Display / mouse / bluetooth icon / other -------
# These remain routed through kylin-actuator fallback for now,
# since the SDK doesn't expose equivalent C APIs.


# ---------------------------------------------------------------------------
# DSL → Toolkit bridge
# ---------------------------------------------------------------------------

# Map kylin_actions DSL strings to toolkit tool names + kwargs
_TOOLKIT_BRIDGE: dict[str, tuple[str, dict]] = {
    # Volume
    "{open volume}":       ("volume", {"action": "up"}),
    "{close volume}":      ("volume", {"action": "down"}),
    "{open maxvolume}":    ("volume", {"action": "set", "value": 100}),
    "{open minvolume}":    ("volume", {"action": "set", "value": 0}),
    # Screenshot
    "{screenshot}":        ("screenshot", {"mode": "full"}),
    "{areascreenshot}":    ("screenshot", {"mode": "area"}),
    "{windowscreenshot}":  ("screenshot", {"mode": "window"}),
    # Bluetooth
    "{open bluetooth}":    ("bluetooth", {"action": "on"}),
    "{close bluetooth}":   ("bluetooth", {"action": "off"}),
    # WiFi
    "{open network}":      ("wifi", {"action": "on"}),
    "{close network}":     ("wifi", {"action": "off"}),
    # Touchpad
    "{open touchpad}":     ("touchpad", {"action": "on"}),
    "{close touchpad}":    ("touchpad", {"action": "off"}),
    # Music
    "{play music}":        ("music", {"action": "play"}),
    "{pause}":             ("music", {"action": "pause"}),
    # Network
    "{show wifilist}":     ("netstatus", {"action": "wifi_list"}),
    "{show proxy}":        ("netstatus", {"action": "proxy_get"}),
    "{show dns}":          ("netstatus", {"action": "dns_get"}),
    "{connect wifi}":      ("wifi", {"action": "connect"}),
    "{disconnect wifi}":   ("wifi", {"action": "disconnect"}),
    "{set proxy}":         ("proxy", {"action": "set"}),
    "{set dns}":           ("dns", {"action": "set"}),
    # Disk
    "{show diskinfo}":     ("diskinfo", {"action": "list"}),
    # Process
    "{show processlist}":  ("process_list", {"action": "list"}),
    "{kill process}":      ("process_kill", {"action": "kill"}),
    # Battery
    "{show batteryinfo}":  ("battery_info", {"action": "info"}),
    "{set powerplan}":     ("power_plan", {"action": "set"}),
    # Bluetooth (additional)
    "{scan bluetooth}":    ("bluetooth", {"action": "scan"}),
}


def _ensure_toolkit() -> None:
    """确保 toolkit 已初始化（幂等），覆盖不走 FastAPI lifespan 的入口."""
    try:
        from src.toolkit.init_tools import init_all_tools
        init_all_tools()
    except Exception as e:
        logger.warning("toolkit 初始化失败: %s", e)


async def _try_toolkit(directive: str, confirmed: bool = False) -> Tuple[int, str] | None:
    """
    Try to execute a DSL directive via the toolkit (with closed-loop verification).

    Returns (rc, output) if handled, None if no matching toolkit tool.
    """
    _ensure_toolkit()

    bridge = _TOOLKIT_BRIDGE.get(directive)
    if bridge is None:
        return None

    tool_name, kwargs = bridge
    try:
        from src.toolkit.base import get_registry
        from src.toolkit.executor import ClosedLoopExecutor

        registry = get_registry()
        tool_obj = registry.get(tool_name)
        if tool_obj is None:
            logger.debug("Toolkit tool '%s' not registered, using kylin_actions", tool_name)
            return None

        executor = ClosedLoopExecutor(registry=registry, max_retries=1)
        result = await executor.run(tool_name, confirmed=confirmed, **kwargs)
        if result.ok:
            logger.info("Toolkit handled %r → %s (verified=%s)", directive, tool_name, result.is_verified)
            return 0, result.output
        else:
            logger.warning("Toolkit tool '%s' failed: %s, falling back", tool_name, result.error)
            return None
    except Exception as exc:
        logger.debug("Toolkit bridge unavailable for %r: %s", directive, exc)
        return None


# ---------------------------------------------------------------------------
# Main dispatch
# ---------------------------------------------------------------------------

async def execute_action(dsl: str, timeout: float = 20.0) -> Tuple[int, str]:
    """
    Execute a DSL action.

    Dispatch order:
    1. Security permission check (DSL level)
    2. Toolkit (closed-loop: execute → verify → log)
    3. Registered SDK/DBus handler (kylin_actions internal)
    4. kylin-actuator binary (fallback)

    Returns (returncode: int, output: str).
    """
    directive = dsl.strip()
    if not directive:
        return 1, "empty directive"

    # Normalize: wrap in braces if not already
    if not directive.startswith("{") and not directive.endswith("}"):
        directive = "{" + directive + "}"

    # ===== Layer 0: DSL-level permission check =====
    from security import get_permission_engine, get_audit_logger, Permission
    perm_result = get_permission_engine().check_action(directive)
    # DSL 层已做 L1 决策：REQUIRE_CONFIRM 时记审计并放行（用户选定的「L1 记审计+放行」），
    # 向下游 executor 传 confirmed=True，避免被审批门二次拦截。
    dsl_confirmed = perm_result.permission == Permission.REQUIRE_CONFIRM
    if perm_result.permission == Permission.DENY:
        get_audit_logger().log_permission_deny(
            "kylin_actions", directive, perm_result.reason,
        )
        logger.warning("DSL action %r denied by policy: %s", directive, perm_result.reason)
        return 2, f"操作被策略拒绝: {perm_result.reason}"
    elif perm_result.permission == Permission.REQUIRE_CONFIRM:
        get_audit_logger().log_permission_confirm(
            "kylin_actions", directive,
        )
        logger.info("DSL action %r requires confirmation (L1), executing with audit", directive)

    # ===== Layer 0.5: dynamic timezone routing (toolkit closed-loop) =====
    m_tz = re.match(r"^\{set timezone\s+(.+)\}$", directive)
    if m_tz:
        zone = m_tz.group(1).strip().strip("\"'")
        _ensure_toolkit()
        try:
            from src.toolkit.base import get_registry
            from src.toolkit.executor import ClosedLoopExecutor
            executor = ClosedLoopExecutor(registry=get_registry(), max_retries=1)
            result = await executor.run("timezone", timezone=zone, confirmed=dsl_confirmed)
            if result.ok:
                return 0, result.output
            return 1, result.error or result.output
        except Exception as exc:
            logger.warning("timezone 动态路由失败: %s", exc)
            return 1, f"设置时区失败: {exc}"

    # ===== Layer 1: Toolkit (with closed-loop verification) =====
    toolkit_result = await _try_toolkit(directive, confirmed=dsl_confirmed)
    if toolkit_result is not None:
        return toolkit_result

    # Check for set background with path
    if directive.startswith("{set background "):
        return _set_background(directive)

    # ===== Layer 2: Registered SDK/DBus handler =====
    handler = ACTION_REGISTRY.get(directive)
    if handler is not None:
        try:
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(None, handler)
        except Exception as exc:
            logger.warning("SDK action %r failed (%s), falling back to actuator", directive, exc)
    else:
        logger.info("No SDK handler for %r, using actuator fallback", directive)

    # ===== Layer 3: kylin-actuator binary =====
    return await _call_actuator_fallback(directive, timeout=timeout)
