"""
Kylin SDK Python bindings (kysdk).

Provides Pythonic wrappers around the Kylin Linux SDK shared libraries.

Usage::

    from src.sdk import system, ai_vision, desktop_dbus

    # OCR — replaces subprocess.run(["ocr_tool", image_path])
    text = ai_vision.recognize_text("/path/to/image.png")

    # System / GPU info — replaces nvidia-smi, uname, etc.
    gpu = system.get_gpu_summary()
    info = system.get_system_info()

    # Desktop control — replaces amixer, kylin-actuator
    desktop_dbus.volume_set(75)
    desktop_dbus.send_notification("Title", "Body")
    desktop_dbus.screenshot_full()

Architecture:
    - C interfaces (libky*.so) → ``ctypes`` bindings in ``system.py``,
      ``ai_vision.py``.
    - C++/Qt interfaces → DBus bridge in ``desktop_dbus.py``.
"""

from src.sdk import system
from src.sdk import ai_vision
from src.sdk import desktop_dbus

__all__ = ["system", "ai_vision", "desktop_dbus"]
