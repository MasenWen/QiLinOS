"""
Kylin SDK Python bindings (kysdk).

Provides Pythonic wrappers around the Kylin Linux SDK shared libraries.

Usage::

    from src.sdk import system, ai_vision, desktop_dbus

    # OCR
    text = ai_vision.recognize_text("/path/to/image.png")

    # System / GPU info
    gpu = system.get_gpu_summary()
    info = system.get_system_info()

    # Desktop control
    desktop_dbus.volume_set(75)
    desktop_dbus.send_notification("Title", "Body")
    desktop_dbus.screenshot_full()

    # Network (new)
    from src.sdk import network
    status = network.get_network_status()

    # Disk (new)
    from src.sdk import disk
    usage = disk.get_disk_usage("/")

    # AI (new)
    from src.sdk import ai_text, ai_image, ai_speech

Architecture:
    - C interfaces (libky*.so) -> ``ctypes`` bindings
    - C++/Qt interfaces -> DBus bridge
"""

from src.sdk import system
from src.sdk import ai_vision
from src.sdk import desktop_dbus
from src.sdk import power
from src.sdk import desktop_ctrl
from src.sdk import network
from src.sdk import disk
from src.sdk import process
from src.sdk import battery
from src.sdk import bluetooth
from src.sdk import ai_text
from src.sdk import ai_image
from src.sdk import ai_speech

__all__ = [
    "system", "ai_vision", "desktop_dbus", "power", "desktop_ctrl",
    "network", "disk", "process", "battery", "bluetooth",
    "ai_text", "ai_image", "ai_speech",
]
