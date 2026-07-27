"""
Kylin Desktop Environment SDK — DBus bridge layer.

The C++ Qt modules (libkysdk-soundeffects, libkysdk-notification,
libkysdk-appmanager, libkysdk-thememanager) cannot be called via ctypes
directly because they use C++ name mangling and Qt types.

However, these modules are thin wrappers around system DBus services.
This module provides Python-side DBus wrappers that achieve the same
functionality without the C++ dependency.

Requirements (Kylin server)::

    pip install pydbus           # or: sudo apt install python3-dbus

Reference: ``08-桌面环境SDK.md``
"""

import sys
import os
from typing import Optional, Tuple


# ---------------------------------------------------------------------------
# DBus availability guard
# ---------------------------------------------------------------------------

_dbus_available = False
_dbus_bus = None

try:
    import dbus
    from dbus.mainloop.glib import DBusGMainLoop
    DBusGMainLoop(set_as_default=True)
    _dbus_available = True
except ImportError:
    pass


def _get_session_bus():
    """Lazy session bus connection."""
    global _dbus_bus
    if _dbus_bus is None and _dbus_available:
        try:
            _dbus_bus = dbus.SessionBus()
        except Exception:
            pass
    return _dbus_bus


def _get_system_bus():
    """Lazy system bus connection."""
    if _dbus_available:
        try:
            return dbus.SystemBus()
        except Exception:
            pass
    return None


def is_available() -> bool:
    """Return True if DBus is usable."""
    return _dbus_available


# ---------------------------------------------------------------------------
# Volume control (replaces ``amixer set Master ...``)
# ---------------------------------------------------------------------------

def volume_set(percent: int) -> bool:
    """
    Set master volume to *percent* (0–100).

    Replaces:
    - ``amixer set Master {percent}%``
    - ``kylin-actuator {open maxvolume}`` (percent=100)
    - ``kylin-actuator {open minvolume}`` (percent=0)
    """
    # Try PulseAudio first, then PipeWire, then amixer fallback
    try:
        bus = _get_session_bus()
        if bus is None:
            return _volume_set_fallback_amixer(percent)

        # org.freedesktop.DBus / PulseAudio approach
        # The canonical Kylin path may vary; this is the standard interface
        import subprocess
        result = subprocess.run(
            ["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{percent}%"],
            capture_output=True, text=True, timeout=5
        )
        return result.returncode == 0
    except Exception:
        return _volume_set_fallback_amixer(percent)


def _volume_set_fallback_amixer(percent: int) -> bool:
    """Last-resort fallback using amixer."""
    import subprocess
    try:
        result = subprocess.run(
            ["amixer", "set", "Master", f"{percent}%"],
            capture_output=True, text=True, timeout=5
        )
        return result.returncode == 0
    except Exception:
        return False


def volume_mute() -> bool:
    """Mute audio.  Replaces ``amixer set Master mute``."""
    import subprocess
    try:
        result = subprocess.run(
            ["pactl", "set-sink-mute", "@DEFAULT_SINK@", "1"],
            capture_output=True, text=True, timeout=5
        )
        return result.returncode == 0
    except Exception:
        try:
            result = subprocess.run(
                ["amixer", "set", "Master", "mute"],
                capture_output=True, text=True, timeout=5
            )
            return result.returncode == 0
        except Exception:
            return False


def volume_unmute() -> bool:
    """Unmute audio.  Replaces ``amixer set Master unmute``."""
    import subprocess
    try:
        result = subprocess.run(
            ["pactl", "set-sink-mute", "@DEFAULT_SINK@", "0"],
            capture_output=True, text=True, timeout=5
        )
        return result.returncode == 0
    except Exception:
        try:
            result = subprocess.run(
                ["amixer", "set", "Master", "unmute"],
                capture_output=True, text=True, timeout=5
            )
            return result.returncode == 0
        except Exception:
            return False


def volume_up() -> str:
    """Increase volume by one step."""
    try:
        import subprocess
        result = subprocess.run(
            ["pactl", "set-sink-volume", "@DEFAULT_SINK@", "+5%"],
            capture_output=True, text=True, timeout=5
        )
        return "已增加音量" if result.returncode == 0 else f"增加音量失败: {result.stderr}"
    except Exception as e:
        return f"增加音量失败: {e}"


def volume_down() -> str:
    """Decrease volume by one step."""
    try:
        import subprocess
        result = subprocess.run(
            ["pactl", "set-sink-volume", "@DEFAULT_SINK@", "-5%"],
            capture_output=True, text=True, timeout=5
        )
        return "已降低音量" if result.returncode == 0 else f"降低音量失败: {result.stderr}"
    except Exception as e:
        return f"降低音量失败: {e}"


# ---------------------------------------------------------------------------
# Desktop notification (replaces libkysdk-notification)
# ---------------------------------------------------------------------------

def send_notification(
    title: str,
    body: str,
    app_name: str = "NexAgent",
    timeout_ms: int = 5000,
    icon: str = "",
) -> bool:
    """
    Send a desktop notification via org.freedesktop.Notifications.

    Replaces ``libkysdk-notification`` C++ API.
    """
    bus = _get_session_bus()
    if bus is None:
        # Fallback to notify-send CLI
        try:
            import subprocess
            result = subprocess.run(
                ["notify-send", title, body],
                capture_output=True, text=True, timeout=5
            )
            return result.returncode == 0
        except Exception:
            return False

    try:
        notify_obj = bus.get_object(
            "org.freedesktop.Notifications",
            "/org/freedesktop/Notifications"
        )
        notify_iface = dbus.Interface(notify_obj, "org.freedesktop.Notifications")
        notify_iface.Notify(
            app_name,
            0,          # replaces_id
            icon,       # app_icon
            title,
            body,
            [],         # actions
            {},         # hints
            timeout_ms,
        )
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Screenshot (replaces ``kylin-actuator {screenshot}``)
# ---------------------------------------------------------------------------

def screenshot_full() -> str:
    """Take a full-screen screenshot.  Returns file path or error string."""
    desktop_dir = os.path.expanduser("~/桌面")
    if not os.path.isdir(desktop_dir):
        desktop_dir = os.path.expanduser("~/Desktop")
    os.makedirs(desktop_dir, exist_ok=True)

    import time
    filename = f"screenshot_{time.strftime('%Y%m%d_%H%M%S')}.png"
    filepath = os.path.join(desktop_dir, filename)

    try:
        import subprocess
        result = subprocess.run(
            ["gnome-screenshot", "-f", filepath],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            return f"全屏截图已保存到: {filepath}"
        else:
            return f"截图失败: {result.stderr}"
    except FileNotFoundError:
        return "截图失败: gnome-screenshot 未安装。请安装: sudo apt install gnome-screenshot"
    except Exception as e:
        return f"截图出错: {e}"


def screenshot_area() -> str:
    """Take an area screenshot."""
    try:
        import subprocess
        result = subprocess.run(
            ["gnome-screenshot", "-a"],
            capture_output=True, text=True, timeout=30
        )
        return "已执行区域截图" if result.returncode == 0 else f"区域截图失败: {result.stderr}"
    except FileNotFoundError:
        return "截图失败: gnome-screenshot 未安装"
    except Exception as e:
        return f"截图出错: {e}"


def screenshot_window() -> str:
    """Take a window screenshot."""
    try:
        import subprocess
        result = subprocess.run(
            ["gnome-screenshot", "-w"],
            capture_output=True, text=True, timeout=10
        )
        return "已执行窗口截图" if result.returncode == 0 else f"窗口截图失败: {result.stderr}"
    except FileNotFoundError:
        return "截图失败: gnome-screenshot 未安装"
    except Exception as e:
        return f"截图出错: {e}"


# ---------------------------------------------------------------------------
# Wallpaper (replaces ``kylin-actuator {set background ...}``)
# ---------------------------------------------------------------------------

def set_wallpaper(image_path: str) -> str:
    """Set desktop wallpaper.  Replaces ``{set background <path>}``."""
    if not os.path.isfile(image_path):
        return f"图片文件不存在: {image_path}"

    try:
        import subprocess
        # gsettings works for GNOME/UKUI based desktops
        uri = f"file://{image_path}"
        result = subprocess.run(
            ["gsettings", "set", "org.mate.background", "picture-filename", image_path],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            return "桌面背景已设置"
        # Try alternative schema
        result = subprocess.run(
            ["gsettings", "set", "org.gnome.desktop.background", "picture-uri", uri],
            capture_output=True, text=True, timeout=5
        )
        return "桌面背景已设置" if result.returncode == 0 else f"设置壁纸失败: {result.stderr}"
    except FileNotFoundError:
        return "设置壁纸失败: gsettings 不可用"
    except Exception as e:
        return f"设置壁纸出错: {e}"
