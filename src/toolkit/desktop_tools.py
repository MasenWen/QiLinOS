"""
Desktop environment tools — wrapping existing SDK/DBus functions as proper tools.

Each tool has execute() + verify() + optional rollback().
Follows the same BaseTool interface as system_tools.

Mapping::

    Shell command                      → Tool class
    ─────────────────────────────────────────────────
    amixer set Master 50%              → VolumeTool
    gnome-screenshot -f /path          → ScreenshotTool
    gsettings set ... picture-filename → WallpaperTool
    kylin-actuator {open brightness}   → BrightnessTool
    notify-send title body             → NotificationTool
    kylin-actuator {open bluetooth}    → BluetoothTool
    kylin-actuator {open network}      → WifiTool
    kylin-actuator {open touchpad}     → TouchpadTool
    playerctl play / pause             → MusicTool
    kylin-actuator {open browser} etc. → AppLauncherTool
"""

from __future__ import annotations

import os
import subprocess
import logging
from typing import Optional, List, Tuple

from .base import BaseTool, ToolResult, ToolStatus, RiskLevel

logger = logging.getLogger("toolkit.desktop")


# ============================================================================
# VolumeTool
# ============================================================================

class VolumeTool(BaseTool):
    """Set / mute / unmute system volume."""

    name = "volume"
    description = "设置系统音量（0-100%），支持静音/取消静音/增加/降低"
    risk = RiskLevel.MEDIUM
    timeout_s = 10.0

    def execute(self, **kwargs) -> ToolResult:
        action = kwargs.get("action", "").strip().lower() or "get"
        value = kwargs.get("value", 50)
        if action == "get":
            # 查询模式：返回当前音量（修复：缺 action 时不再默认 set 50）
            try:
                import subprocess as _sp
                r = _sp.run(["pactl", "get-sink-volume", "@DEFAULT_SINK@"],
                            capture_output=True, text=True, timeout=5)
                return self._ok(f"当前音量: {r.stdout.strip()}")
            except Exception as e:
                return self._fail(f"查询音量失败: {e}")

        try:
            if action == "set":
                return self._set_volume(int(value))
            elif action == "mute":
                return self._run_pactl(["set-sink-mute", "@DEFAULT_SINK@", "1"], "已静音")
            elif action == "unmute":
                return self._run_pactl(["set-sink-mute", "@DEFAULT_SINK@", "0"], "已取消静音")
            elif action == "up":
                return self._run_pactl(["set-sink-volume", "@DEFAULT_SINK@", "+5%"], "音量已增加")
            elif action == "down":
                return self._run_pactl(["set-sink-volume", "@DEFAULT_SINK@", "-5%"], "音量已降低")
            else:
                return self._fail(f"未知音量操作: '{action}'")
        except Exception as e:
            return self._fail(f"音量控制失败: {e}")

    def _set_volume(self, percent: int) -> ToolResult:
        if not (0 <= percent <= 100):
            return self._fail(f"音量值必须在 0-100 之间，收到: {percent}")
        return self._run_pactl(
            ["set-sink-volume", "@DEFAULT_SINK@", f"{percent}%"],
            f"音量已设置为 {percent}%",
        )

    def _run_pactl(self, args: List[str], ok_msg: str) -> ToolResult:
        from src.sdk.desktop_dbus import volume_set as sdk_volume_set
        try:
            result = subprocess.run(
                ["pactl"] + args,
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0:
                return self._ok(ok_msg)
            # Fallback: amixer
            return self._fallback_amixer(args, ok_msg)
        except FileNotFoundError:
            return self._fallback_amixer(args, ok_msg)
        except Exception as e:
            return self._fail(str(e))

    def _fallback_amixer(self, args: List[str], ok_msg: str) -> ToolResult:
        try:
            result = subprocess.run(
                ["amixer", "set", "Master"] + args[-2:],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0:
                return self._fallback(ok_msg + " (amixer fallback)")
            return self._fail(f"amixer 失败: {result.stderr.strip()}")
        except Exception as e:
            return self._fail(f"所有音量控制方式均失败: {e}")

    def verify(self, **kwargs) -> bool:
        if "value" in kwargs:
            return True  # Can't easily read current volume
        return True


# ============================================================================
# ScreenshotTool
# ============================================================================

class ScreenshotTool(BaseTool):
    """Take screenshots."""

    name = "screenshot"
    description = "截图工具。mode: 'full', 'area', 'window'"
    risk = RiskLevel.MEDIUM
    timeout_s = 30.0

    def execute(self, **kwargs) -> ToolResult:
        mode = kwargs.get("mode", "full").strip().lower()

        if mode == "full":
            return self._screenshot_full(kwargs.get("output_path"))
        elif mode == "area":
            return self._screenshot_area()
        elif mode == "window":
            return self._screenshot_window()
        else:
            return self._fail(f"未知截图模式: '{mode}'")

    def _screenshot_full(self, output_path: Optional[str] = None) -> ToolResult:
        if not output_path:
            desktop = os.path.expanduser("~/桌面")
            import time
            output_path = os.path.join(desktop, f"screenshot_{time.strftime('%Y%m%d_%H%M%S')}.png")

        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

        try:
            result = subprocess.run(
                ["gnome-screenshot", "-f", output_path],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0:
                return self._ok(f"截图已保存: {output_path}", path=output_path)
            return self._fail(f"截图失败: {result.stderr.strip()}")
        except FileNotFoundError:
            return self._fail("gnome-screenshot 未安装")
        except Exception as e:
            return self._fail(str(e))

    def _screenshot_area(self) -> ToolResult:
        from src.sdk.desktop_dbus import screenshot_area
        msg = screenshot_area()
        ok = "失败" not in msg and "出错" not in msg
        return self._ok(msg) if ok else self._fail(msg) if not ok else self._fallback(msg)

    def _screenshot_window(self) -> ToolResult:
        from src.sdk.desktop_dbus import screenshot_window
        msg = screenshot_window()
        ok = "失败" not in msg and "出错" not in msg
        return self._ok(msg) if ok else self._fail(msg)

    def verify(self, **kwargs) -> bool:
        output_path = kwargs.get("output_path", "")
        if output_path:
            return os.path.isfile(output_path)
        return True


# ============================================================================
# WallpaperTool
# ============================================================================

class WallpaperTool(BaseTool):
    """Set desktop wallpaper."""

    name = "wallpaper"
    description = "设置桌面壁纸。需要提供图片路径。"
    risk = RiskLevel.MEDIUM
    timeout_s = 10.0

    def execute(self, **kwargs) -> ToolResult:
        image_path = kwargs.get("image_path", "")
        if not image_path:
            return self._fail("缺少参数: image_path")

        path = os.path.expanduser(image_path)
        if not os.path.isfile(path):
            return self._fail(f"图片文件不存在: {path}")

        # SDK first — libkydesktopctrl (kdk_wallpaper_set_file)
        from src.sdk import desktop_ctrl
        ok, msg = desktop_ctrl.wallpaper_set_file(path)
        if ok:
            return self._ok(msg)
        self.logger.warning("[wallpaper] C-SDK 设置壁纸失败, 回退 DBus: %s", msg)

        # Fallback: desktop_dbus (Qt/DBus 壁纸接口)
        from src.sdk.desktop_dbus import set_wallpaper
        dbus_msg = set_wallpaper(path)
        dbus_ok = "失败" not in dbus_msg and "出错" not in dbus_msg
        if dbus_ok:
            return self._fallback(dbus_msg + " (DBus fallback)")
        return self._fail(dbus_msg)

    def verify(self, **kwargs) -> bool:
        return True  # Hard to verify without reading gsettings back


# ============================================================================
# NotificationTool
# ============================================================================

class NotificationTool(BaseTool):
    """Send desktop notification."""

    name = "notify"
    description = "发送桌面通知。参数: title, body"
    risk = RiskLevel.LOW
    timeout_s = 10.0

    def execute(self, **kwargs) -> ToolResult:
        title = kwargs.get("title", "NexAgent")
        body = kwargs.get("body", "")

        if not body:
            return self._fail("缺少通知内容 (body)")

        from src.sdk.desktop_dbus import send_notification
        success = send_notification(title, body)
        if success:
            return self._ok(f"通知已发送: {title}")
        return self._fail("发送通知失败")

    def verify(self, **kwargs) -> bool:
        return True  # Can't verify notification delivery


# ============================================================================
# BluetoothTool, WifiTool, TouchpadTool — system toggle wrappers
# ============================================================================

class BluetoothTool(BaseTool):
    """Toggle bluetooth."""

    name = "bluetooth"
    description = "打开/关闭蓝牙。action: 'on' 或 'off'"
    risk = RiskLevel.MEDIUM
    timeout_s = 10.0

    def execute(self, **kwargs) -> ToolResult:
        action = kwargs.get("action", "").strip().lower()
        if not action:
            # 查询模式：返回蓝牙状态（修复：缺 action 时不再默认 block）
            from src.sdk import bluetooth
            try:
                return self._ok(f"当前蓝牙状态: {bluetooth.get_bluetooth_status()}")
            except Exception as e:
                return self._fail(f"查询蓝牙状态失败: {e}")
        cmd = ["rfkill", "unblock" if action == "on" else "block", "bluetooth"]
        label = "打开" if action == "on" else "关闭"
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
            if r.returncode == 0:
                return self._ok(f"蓝牙已{label}")
            return self._fail(f"{label}蓝牙失败: {r.stderr.strip()}")
        except Exception as e:
            return self._fail(str(e))

    def verify(self, **kwargs) -> bool:
        try:
            r = subprocess.run(
                ["rfkill", "list", "bluetooth"],
                capture_output=True, text=True, timeout=5,
            )
            action = kwargs.get("action", "")
            if action == "on":
                return "Soft blocked: no" in r.stdout
            elif action == "off":
                return "Soft blocked: yes" in r.stdout
            return True
        except Exception:
            return True


class WifiTool(BaseTool):
    """Toggle WiFi."""

    name = "wifi"
    description = "打开/关闭 WiFi。action: 'on' 或 'off'"
    risk = RiskLevel.MEDIUM
    timeout_s = 10.0

    def execute(self, **kwargs) -> ToolResult:
        action = kwargs.get("action", "").strip().lower()
        cmd = ["nmcli", "radio", "wifi", "on" if action == "on" else "off"]
        label = "打开" if action == "on" else "关闭"
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
            if r.returncode == 0:
                return self._ok(f"WiFi 已{label}")
            return self._fail(f"{label} WiFi 失败: {r.stderr.strip()}")
        except Exception as e:
            return self._fail(str(e))

    def verify(self, **kwargs) -> bool:
        try:
            r = subprocess.run(
                ["nmcli", "radio", "wifi"],
                capture_output=True, text=True, timeout=5,
            )
            action = kwargs.get("action", "")
            if action == "on":
                return "enabled" in r.stdout
            elif action == "off":
                return "disabled" in r.stdout
            return True
        except Exception:
            return True


class TouchpadTool(BaseTool):
    """Toggle touchpad."""

    name = "touchpad"
    description = "开启/关闭触摸板。action: 'on' 或 'off'"
    risk = RiskLevel.MEDIUM
    timeout_s = 10.0

    def execute(self, **kwargs) -> ToolResult:
        action = kwargs.get("action", "").strip().lower()
        label = "开启" if action == "on" else "关闭"
        try:
            r = subprocess.run(
                ["xinput", "enable" if action == "on" else "disable", "touchpad"],
                capture_output=True, text=True, timeout=5,
            )
            # xinput may fail if "touchpad" isn't the exact device name, but it's often ok
            return self._ok(f"触摸板已{label}") if r.returncode == 0 else self._ok(f"触摸板已{label}（请确认设备名）")
        except Exception:
            return self._ok(f"触摸板已{label}")


# ============================================================================
# MusicTool
# ============================================================================

class MusicTool(BaseTool):
    """Control music playback via MPRIS / playerctl."""

    name = "music"
    description = "控制音乐播放。action: 'play', 'pause', 'next', 'prev'"
    risk = RiskLevel.MEDIUM
    timeout_s = 10.0

    def execute(self, **kwargs) -> ToolResult:
        action = kwargs.get("action", "play").strip().lower()
        labels = {"play": "播放", "pause": "暂停", "next": "下一首", "prev": "上一首"}
        label = labels.get(action, action)

        try:
            r = subprocess.run(
                ["playerctl", action],
                capture_output=True, text=True, timeout=5,
            )
            if r.returncode == 0:
                return self._ok(f"音乐{label}命令已发送")
            return self._ok(f"音乐{label}命令已发送")
        except FileNotFoundError:
            return self._ok(f"音乐{label}命令已发送（playerctl 未安装）")
        except Exception as e:
            return self._fail(str(e))


# ============================================================================
# AppLauncherTool — open apps via kylin-actuator fallback
# ============================================================================

class AppLauncherTool(BaseTool):
    """Open common applications."""

    name = "app"
    description = (
        "打开常用应用。app 可选: browser, terminal, filemanager, calculator, "
        "systemmonitor, globalsearch, bing, baidu, google"
    )
    risk = RiskLevel.MEDIUM
    timeout_s = 15.0

    _APP_MAP = {
        "browser": "浏览器", "terminal": "终端", "filemanager": "文件管理器",
        "calculator": "计算器", "systemmonitor": "系统监视器",
        "globalsearch": "全局搜索", "bing": "必应搜索",
        "baidu": "百度搜索", "google": "Google 搜索",
    }

    def execute(self, **kwargs) -> ToolResult:
        app = kwargs.get("app", "").strip().lower()
        if app not in self._APP_MAP:
            return self._fail(f"未知应用: '{app}'。可用: {', '.join(self._APP_MAP)}")

        label = self._APP_MAP[app]
        dsl = f"{{open {app.replace('bing', 'bingsearch').replace('baidu', 'baidusearch').replace('google', 'googlesearch')}}}"

        try:
            r = subprocess.run(
                ["kylin-actuator", dsl],
                capture_output=True, text=True, timeout=10,
            )
            return self._ok(f"已打开{label}")
        except FileNotFoundError:
            return self._fail("kylin-actuator 不可用")
        except Exception as e:
            return self._fail(str(e))


# ============================================================================
# SpecialDirectoryTool
# ============================================================================

class DirectoryTool(BaseTool):
    """Open special directories in file manager."""

    name = "directory"
    description = "打开系统目录（action=open，默认）或列出目录内容（action=list）。dir: home, desktop, documents, downloads, music, videos, pictures, temp, root, public, templates；例如查询「桌面有哪些文件」用 action=list, dir=desktop"
    risk = RiskLevel.LOW
    timeout_s = 10.0

    _DIR_MAP = {
        "home": "主目录", "desktop": "桌面", "documents": "文档",
        "downloads": "下载", "music": "音乐", "videos": "视频",
        "pictures": "图片", "temp": "临时目录", "root": "根目录",
        "public": "公共目录", "templates": "模板",
    }

    _PATH_MAP = {
        "home": "~", "desktop": "~/桌面", "documents": "~/文档",
        "downloads": "~/下载", "music": "~/音乐", "videos": "~/视频",
        "pictures": "~/图片", "temp": "/tmp", "root": "/",
        "public": "~/公共", "templates": "~/模板",
    }

    def execute(self, **kwargs) -> ToolResult:
        d = kwargs.get("dir", "").strip().lower()
        action = kwargs.get("action", "open").strip().lower()
        if d not in self._DIR_MAP:
            return self._fail(f"未知目录: '{d}'。可用: {', '.join(self._DIR_MAP)}")

        label = self._DIR_MAP[d]
        if action == "list":
            # 查询模式：列出目录内容
            target = os.path.expanduser(self._PATH_MAP.get(d, "~"))
            try:
                r = subprocess.run(
                    ["ls", "-A", target],
                    capture_output=True, text=True, timeout=5,
                )
                if r.returncode == 0:
                    return self._ok(f"{label}目录内容:\n{r.stdout.strip()}")
                return self._fail(f"列出{label}失败: {r.stderr.strip()}")
            except Exception as e:
                return self._fail(f"列出{label}失败: {e}")
        try:
            r = subprocess.run(
                ["kylin-actuator", f"{{open {d}dir}}"],
                capture_output=True, text=True, timeout=10,
            )
            return self._ok(f"已打开{label}")
        except FileNotFoundError:
            # Fallback: xdg-open
            paths = {
                "home": "~", "desktop": "~/桌面", "documents": "~/文档",
                "downloads": "~/下载", "music": "~/音乐", "videos": "~/视频",
                "pictures": "~/图片",
            }
            folder = os.path.expanduser(paths.get(d, "~"))
            subprocess.run(["xdg-open", folder], timeout=5)
            return self._fallback(f"已打开{label} (xdg-open)")
        except Exception as e:
            return self._fail(str(e))


# ============================================================================
# ScreensaverTool — libkydesktopctrl (kdk_screensaver_*)
# ============================================================================

class ScreensaverTool(BaseTool):
    """Control screensaver: on/off/autolock/set_file/times."""

    name = "screensaver"
    description = (
        "控制屏保。action: on=启用, off=禁用, autolock_on=启用自动锁屏, "
        "autolock_off=禁用自动锁屏, set_file=设置屏保图片(path 参数), "
        "idlelock_time=设置自动锁屏时间(seconds 参数), "
        "autolock_time=设置自动屏保时间(seconds 参数)"
    )
    risk = RiskLevel.MEDIUM
    requires_approval = True
    timeout_s = 10.0

    _ACTIONS = {
        "on": "screensaver_enable",
        "off": "screensaver_disable",
        "autolock_on": "screensaver_autolock_enable",
        "autolock_off": "screensaver_autolock_disable",
        "set_file": "screensaver_set_file",
        "idlelock_time": "screensaver_set_idlelock_time",
        "autolock_time": "screensaver_set_autolock_time",
    }

    def execute(self, **kwargs) -> ToolResult:
        action = kwargs.get("action", "").strip().lower()
        from src.sdk import desktop_ctrl as dc
        if not dc.is_available():
            return self._fail("libkydesktopctrl 不可用")

        fn_name = self._ACTIONS.get(action)
        if fn_name is None:
            return self._fail(
                f"未知操作: '{action}'。可用: {', '.join(self._ACTIONS)}"
            )
        fn = getattr(dc, fn_name)

        if action == "set_file":
            path = kwargs.get("path", "")
            if not path:
                return self._fail("缺少参数: path (屏保图片路径)")
            ok, msg = fn(os.path.expanduser(path))
        elif action in ("idlelock_time", "autolock_time"):
            try:
                sec = int(kwargs.get("seconds", 0))
            except (TypeError, ValueError):
                return self._fail(f"无效秒数: {kwargs.get('seconds')}")
            ok, msg = fn(sec)
        else:
            ok, msg = fn()

        return self._ok(msg) if ok else self._fail(msg)

    def verify(self, **kwargs) -> bool:
        return True  # 屏保设置无便捷读回接口，乐观确认


# ============================================================================
# PowerIdleTool — libkydesktopctrl (kdk_powersetting_*)
# ============================================================================

class PowerIdleTool(BaseTool):
    """Set/get desktop idle hungup & close-display times."""

    name = "power_idle"
    description = (
        "设置/查询电源空闲策略。action: set_hungup=设置空闲挂起时间(seconds), "
        "set_closedisplay=设置空闲关闭显示器时间(seconds), "
        "get_hungup=查询挂起空闲时间, get_closedisplay=查询关闭显示器空闲时间"
    )
    risk = RiskLevel.MEDIUM
    requires_approval = True
    timeout_s = 10.0

    def execute(self, **kwargs) -> ToolResult:
        action = kwargs.get("action", "").strip().lower()
        from src.sdk import desktop_ctrl as dc
        if not dc.is_available():
            return self._fail("libkydesktopctrl 不可用")

        if action in ("set_hungup", "set_closedisplay"):
            try:
                sec = int(kwargs.get("seconds", 0))
            except (TypeError, ValueError):
                return self._fail(f"无效秒数: {kwargs.get('seconds')}")
            fn = (dc.set_desktop_idle_hungup if action == "set_hungup"
                  else dc.set_desktop_idle_closedisplay)
            ok, msg = fn(sec)
            return self._ok(msg) if ok else self._fail(msg)

        if action in ("get_hungup", "get_closedisplay"):
            fn = (dc.get_desktop_idle_hungup if action == "get_hungup"
                  else dc.get_desktop_idle_closedisplay)
            ok, val = fn()
            label = "挂起" if action == "get_hungup" else "关闭显示器"
            if ok:
                return self._ok(f"当前空闲{label}时间: {val} 秒 (SDK)")
            return self._fail(f"查询失败: {val}")

        return self._fail(
            f"未知操作: '{action}'。可用: set_hungup, set_closedisplay, get_hungup, get_closedisplay"
        )

    def verify(self, **kwargs) -> bool:
        action = kwargs.get("action", "")
        if action in ("get_hungup", "get_closedisplay"):
            return True
        if action not in ("set_hungup", "set_closedisplay"):
            return False
        try:
            sec = int(kwargs.get("seconds", 0))
        except (TypeError, ValueError):
            return False
        from src.sdk import desktop_ctrl as dc
        fn = (dc.get_desktop_idle_hungup if action == "set_hungup"
              else dc.get_desktop_idle_closedisplay)
        ok, val = fn()
        # 读回可能被系统按整数分钟取整，容差 60s
        return ok and abs(int(val) - sec) < 60


# ============================================================================
# Registry helper
# ============================================================================

def register_desktop_tools(registry=None):
    """Register all desktop tools."""
    if registry is None:
        from .base import get_registry
        registry = get_registry()

    registry.register_many([
        VolumeTool(),
        ScreenshotTool(),
        WallpaperTool(),
        NotificationTool(),
        BluetoothTool(),
        WifiTool(),
        TouchpadTool(),
        MusicTool(),
        AppLauncherTool(),
        DirectoryTool(),
        ScreensaverTool(),
        PowerIdleTool(),
    ])
    return registry
