"""
Kylin System Capability SDK — ctypes Python bindings.

Wraps the following C libraries:
- ``libkysysinfo.so``   : system / host information
- ``libkyhwinfo.so``    : hardware information
- ``libkyedid.so``       : display & GPU (EDID) information
- ``libkyfan.so``        : fan speed information
- ``libkydiskinfo.so``   : disk / partition information
- ``libkynetinfo.so``    : network interface information

Use these to replace shell commands like ``nvidia-smi``, ``cat /proc/cpuinfo``,
``df``, ``ifconfig`` etc.

API reference: ``03-系统能力SDK.md``
"""

import ctypes
from typing import Optional, Dict, Any

from .base import load_library, _decode_cstring, _safe_cstring_call, declare, IS_LINUX, IS_KYLIN

# ---------------------------------------------------------------------------
# Load libraries (all optional — mock on macOS)
# ---------------------------------------------------------------------------

_lib_sysinfo = load_library("libkysysinfo", mock=True)       # /usr/lib/x86_64-linux-gnu/libkysysinfo.so
_lib_hwinfo  = load_library("libkyhwinfo", mock=True)         # /usr/lib/x86_64-linux-gnu/libkyhwinfo.so
_lib_edid    = load_library("libkyedid", mock=True)           # /usr/lib/x86_64-linux-gnu/libkyedid.so
_lib_fan     = load_library("libkyfan", mock=True)            # /usr/lib/x86_64-linux-gnu/libkyfan.so
_lib_disk    = load_library("libkydiskinfo", mock=True)       # /usr/lib/x86_64-linux-gnu/libkydiskinfo.so
_lib_net     = load_library("libkynetinfo", mock=True)        # /usr/lib/x86_64-linux-gnu/libkynetinfo.so
_lib_location = load_library("libkylocation", mock=True)      # /usr/lib/x86_64-linux-gnu/libkylocation.so

# ---------------------------------------------------------------------------
# Declare function signatures
# ---------------------------------------------------------------------------

# --- libkysysinfo ---
if _lib_sysinfo is not None:
    # Host info
    declare(_lib_sysinfo, "kdk_get_host_vendor",     restype=ctypes.c_char_p)
    declare(_lib_sysinfo, "kdk_get_host_product",    restype=ctypes.c_char_p)
    declare(_lib_sysinfo, "kdk_get_host_serial",     restype=ctypes.c_char_p)
    # System info
    declare(_lib_sysinfo, "kdk_system_get_architecture",     restype=ctypes.c_char_p)
    declare(_lib_sysinfo, "kdk_system_get_buildTime",       restype=ctypes.c_char_p)
    declare(_lib_sysinfo, "kdk_system_get_custom_version",  restype=ctypes.c_char_p)
    declare(_lib_sysinfo, "kdk_system_get_appScene",        restype=ctypes.c_char_p)
    declare(_lib_sysinfo, "kdk_system_get_activationStatus", restype=ctypes.c_void_p)
    declare(_lib_sysinfo, "kdk_system_get_env",             restype=ctypes.c_char_p)
    # PCI
    declare(_lib_sysinfo, "kdk_hw_get_pci_info",     restype=ctypes.c_char_p)
    declare(_lib_sysinfo, "kdk_hw_free_pci_info",    restype=None, argtypes=[ctypes.c_void_p])

# --- libkyhwinfo ---
if _lib_hwinfo is not None:
    declare(_lib_hwinfo, "kdk_hw_get_hwinfo",    restype=ctypes.c_char_p)
    declare(_lib_hwinfo, "kdk_hw_free_hw",       restype=None, argtypes=[ctypes.c_void_p])
    declare(_lib_hwinfo, "kdk_hw_get_powerinfo", restype=ctypes.c_char_p)
    declare(_lib_hwinfo, "kdk_hw_free_power_info", restype=None, argtypes=[ctypes.c_void_p])

# --- libkyedid ---
if _lib_edid is not None:
    declare(_lib_edid, "kdk_edid_get_manufacturer",       restype=ctypes.c_char_p)
    declare(_lib_edid, "kdk_edid_get_model",              restype=ctypes.c_char_p)
    declare(_lib_edid, "kdk_edid_get_serialNumber",       restype=ctypes.c_char_p)
    declare(_lib_edid, "kdk_edid_get_interface",          restype=ctypes.c_char_p)
    declare(_lib_edid, "kdk_edid_get_resolution",         restype=ctypes.c_char_p)
    declare(_lib_edid, "kdk_edid_get_max_resolution",     restype=ctypes.c_char_p)
    declare(_lib_edid, "kdk_edid_get_current_brightness", restype=ctypes.c_char_p)
    declare(_lib_edid, "kdk_edid_get_max_brightness",     restype=ctypes.c_char_p)
    declare(_lib_edid, "kdk_edid_get_gamma",              restype=ctypes.c_char_p)
    declare(_lib_edid, "kdk_edid_get_refreshRate",        restype=ctypes.c_char_p)
    declare(_lib_edid, "kdk_edid_get_rotation",           restype=ctypes.c_char_p)
    declare(_lib_edid, "kdk_edid_get_ratio",              restype=ctypes.c_char_p)
    declare(_lib_edid, "kdk_edid_get_rawDpiX",            restype=ctypes.c_char_p)
    declare(_lib_edid, "kdk_edid_get_rawDpiY",            restype=ctypes.c_char_p)
    declare(_lib_edid, "kdk_edid_get_red_primary",        restype=ctypes.c_char_p)
    declare(_lib_edid, "kdk_edid_get_green_primary",      restype=ctypes.c_char_p)
    declare(_lib_edid, "kdk_edid_get_blue_primary",       restype=ctypes.c_char_p)
    declare(_lib_edid, "kdk_edid_get_character",          restype=ctypes.c_char_p)

# --- libkyfan ---
if _lib_fan is not None:
    declare(_lib_fan, "kdk_fan_get_information", restype=ctypes.c_char_p)
    declare(_lib_fan, "kdk_fan_freeall",         restype=None)

# --- libkydiskinfo ---
if _lib_disk is not None:
    declare(_lib_disk, "kdk_disk_get_mount_point",       restype=ctypes.c_char_p)
    declare(_lib_disk, "kdk_disk_get_volume_label",      restype=ctypes.c_char_p)
    declare(_lib_disk, "kdk_disk_get_disk_geometry",     restype=ctypes.c_char_p)
    declare(_lib_disk, "kdk_disk_get_partition_table_type", restype=ctypes.c_char_p)
    declare(_lib_disk, "kdk_disk_get_total_tracks",      restype=ctypes.c_char_p)
    declare(_lib_disk, "kdk_disk_is_disk_writable",      restype=ctypes.c_char_p)

# --- libkynetinfo ---
if _lib_net is not None:
    declare(_lib_net, "kdk_net_get_hosts",            restype=ctypes.c_char_p)
    declare(_lib_net, "kdk_net_get_hosts_domain",     restype=ctypes.c_char_p)
    declare(_lib_net, "kdk_net_get_link_status",      restype=ctypes.c_char_p)
    declare(_lib_net, "kdk_net_get_link_type",         restype=ctypes.c_char_p)
    declare(_lib_net, "kdk_net_get_link_ncNmae",      restype=ctypes.c_char_p)
    declare(_lib_net, "kdk_net_get_addr_by_name",      restype=ctypes.c_char_p)
    declare(_lib_net, "kdk_net_get_name_by_addr",      restype=ctypes.c_char_p)
    declare(_lib_net, "kdk_net_get_iptable_rules",     restype=ctypes.c_char_p)
    declare(_lib_net, "kdk_net_get_ipv4_dhcp_config",  restype=ctypes.c_char_p)
    declare(_lib_net, "kdk_net_get_ipv6_dhcp_config",  restype=ctypes.c_char_p)
    declare(_lib_net, "kdk_net_get_multiple_port_stat", restype=ctypes.c_char_p)

# --- libkylocation ---
if _lib_location is not None:
    declare(_lib_location, "kdk_location_get", restype=ctypes.c_char_p)


# ---------------------------------------------------------------------------
# High-level Python API
# ---------------------------------------------------------------------------

def is_available() -> bool:
    """Return True if the system SDK libraries were loaded."""
    return _lib_sysinfo is not None


# ---- Display / GPU info (replaces ``nvidia-smi``) ----

def get_display_info() -> Dict[str, str]:
    """
    Get display and GPU information via EDID.

    Replaces ``nvidia-smi -q -d MEMORY`` for GPU identification.
    Returns hardware-level info (vendor, model, resolution, DPI, etc.).

    Returns empty dict on unsupported platforms.
    """
    if _lib_edid is None:
        return {}
    import os
    if not os.environ.get("DISPLAY"):
        return {"error": "无显示服务（headless 环境）"}

    return {
        "manufacturer":    _decode_cstring(_lib_edid.kdk_edid_get_manufacturer()),
        "model":           _decode_cstring(_lib_edid.kdk_edid_get_model()),
        "serial":          _decode_cstring(_lib_edid.kdk_edid_get_serialNumber()),
        "interface":       _decode_cstring(_lib_edid.kdk_edid_get_interface()),
        "resolution":      _decode_cstring(_lib_edid.kdk_edid_get_resolution()),
        "max_resolution":  _decode_cstring(_lib_edid.kdk_edid_get_max_resolution()),
        "refresh_rate":    _decode_cstring(_lib_edid.kdk_edid_get_refreshRate()),
        "brightness":      _decode_cstring(_lib_edid.kdk_edid_get_current_brightness()),
        "max_brightness":  _decode_cstring(_lib_edid.kdk_edid_get_max_brightness()),
        "gamma":           _decode_cstring(_lib_edid.kdk_edid_get_gamma()),
        "rotation":        _decode_cstring(_lib_edid.kdk_edid_get_rotation()),
        "ratio":           _decode_cstring(_lib_edid.kdk_edid_get_ratio()),
        "dpi_x":           _decode_cstring(_lib_edid.kdk_edid_get_rawDpiX()),
        "dpi_y":           _decode_cstring(_lib_edid.kdk_edid_get_rawDpiY()),
    }


def get_gpu_summary() -> str:
    """
    Human-readable GPU / display summary.

    Replaces the ``nvidia-smi`` text parsing in ``local_server.py``.
    """
    info = get_display_info()
    if not info:
        return "GPU/显示信息不可用（非 Kylin 系统）"

    parts = []
    if info.get("manufacturer"):
        parts.append(f"厂商: {info['manufacturer']}")
    if info.get("model"):
        parts.append(f"型号: {info['model']}")
    if info.get("resolution"):
        parts.append(f"当前分辨率: {info['resolution']}")
    if info.get("max_resolution"):
        parts.append(f"最大分辨率: {info['max_resolution']}")
    if info.get("refresh_rate"):
        parts.append(f"刷新率: {info['refresh_rate']} Hz")
    if info.get("dpi_x") and info.get("dpi_y"):
        parts.append(f"DPI: {info['dpi_x']}×{info['dpi_y']}")
    if info.get("brightness"):
        parts.append(f"亮度: {info['brightness']} (最大: {info.get('max_brightness', '?')})")

    return "GPU/显示信息 — " + "，".join(parts) if parts else "GPU/显示信息获取为空"


# ---- System / Host info (replaces ``uname``, ``hostnamectl`` etc.) ----

def get_system_info() -> Dict[str, str]:
    """Get basic system information.

    Uses hostnamectl, /proc, /sys, and uname via list-form subprocess
    (no shell=True). Avoids ctypes calls to libkysysinfo which can cause
    segfaults on Kylin V11 after multiple sequential calls.
    """
    import subprocess, os

    def _run(cmd, default=""):
        """Run command safely (list form, no shell)."""
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
            return r.stdout.strip() if r.returncode == 0 else default
        except Exception:
            return default

    def _read_file(path, default=""):
        try:
            with open(path) as f:
                return f.read().strip()
        except Exception:
            return default

    info = {}

    # Architecture via os.uname (pure Python, no subprocess)
    info["architecture"] = os.uname().machine

    # Host vendor / product / serial -- run hostnamectl once, parse in Python
    hostnamectl_out = _run(["hostnamectl"])

    def _parse_hostnamectl(keyword):
        for line in hostnamectl_out.split("\n"):
            if keyword.lower() in line.lower() and ":" in line:
                val = line.split(":", 1)[1].strip()
                if val:
                    return val
        return ""

    vendor = _parse_hostnamectl("Hardware Vendor")
    if not vendor:
        vendor = _read_file("/sys/class/dmi/id/sys_vendor", "")
    info["host_vendor"] = vendor

    product = _parse_hostnamectl("Hardware Model")
    if not product:
        product = _read_file("/sys/class/dmi/id/product_name", "")
    info["host_product"] = product

    serial = _parse_hostnamectl("Serial")
    if not serial:
        serial = _read_file("/sys/class/dmi/id/product_serial", "")
    info["host_serial"] = serial

    # Build time from /proc/version
    proc_ver = _read_file("/proc/version", "")
    build = ""
    if "SMP" in proc_ver:
        parts = proc_ver.split("SMP")
        if len(parts) > 1:
            build = parts[1].split()[0] if parts[1] else ""
    info["build_time"] = build

    # Custom version from /etc/kylin-release or /etc/os-release
    cv = _read_file("/etc/kylin-release", "")
    if not cv:
        os_release = _read_file("/etc/os-release", "")
        for line in os_release.split("\n"):
            if line.startswith("VERSION="):
                cv = line.split("=", 1)[1].strip().replace('"', "")
                break
        if not cv:
            for line in os_release.split("\n"):
                if line.startswith("PRETTY_NAME="):
                    cv = line.split("=", 1)[1].strip().replace('"', "")
                    break
    info["custom_version"] = cv

    # Activation status
    act = _read_file("/etc/kylin-release", "")
    if not act:
        act = _run(["lsb_release", "-ds"])
    info["activation"] = act

    return info

def get_hardware_info() -> str:
    """Get comprehensive hardware information as a raw string."""
    if _lib_hwinfo is None:
        return ""
    return _decode_cstring(_lib_hwinfo.kdk_hw_get_hwinfo())


def get_power_info() -> str:
    """Get power supply information."""
    if _lib_hwinfo is None:
        return ""
    return _decode_cstring(_lib_hwinfo.kdk_hw_get_powerinfo())


def get_fan_info() -> str:
    """Get fan speed information."""
    if _lib_fan is None:
        return ""
    return _decode_cstring(_lib_fan.kdk_fan_get_information())


# ---- Query helpers (match the kylin_server.py DSL categories) ----

def query_system_info(info_type: str) -> str:
    """
    Get system info by type, matching the DSL categories from kylin_server.py.

    Parameters
    ----------
    info_type : str
        One of: ``basic``, ``kernel``, ``cpu``, ``memory``, ``disk``,
        ``load``, ``network``, ``battery``, ``gpu``, ``fans``,
        ``hostname``, ``arch``, ``uptime``, ``boot_time``, ``locale``.

    Returns
    -------
    str
        Human-readable info string.
    """
    info_type = info_type.strip().lower()

    if info_type in ("basic", "os", "version"):
        d = get_system_info()
        return "\n".join(f"{k}: {v}" for k, v in d.items() if v)

    if info_type in ("gpu",):
        return get_gpu_summary()

    if info_type in ("fans", "fan"):
        return get_fan_info()

    if info_type in ("disk",):
        return _decode_cstring(_lib_disk.kdk_disk_get_mount_point()) if _lib_disk else ""

    if info_type in ("network", "net"):
        return _decode_cstring(_lib_net.kdk_net_get_hosts()) if _lib_net else ""

    # Fallback: try hardware info
    if _lib_hwinfo is not None:
        return get_hardware_info()

    return f"系统信息类型 '{info_type}' 在当前环境中不可用"
