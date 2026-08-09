"""
Kylin Disk SDK - ctypes Python bindings.
Wraps: libkydiskinfo.so
Replaces: df, lsblk, fdisk -l
"""
import ctypes, os, subprocess, json
from typing import Dict, Any, List, Tuple
from .base import load_library, _decode_cstring, declare, IS_LINUX, IS_KYLIN

_LIB = None
def _get_lib():
    global _LIB
    if _LIB is None:
        _LIB = load_library("libkydiskinfo", mock=not IS_KYLIN)
    return _LIB

def get_disk_list():
    lib = _get_lib()
    if lib:
        try:
            declare(lib, "kdk_disk_get_list", restype=ctypes.c_char_p)
            raw = lib.kdk_disk_get_list()
            if raw: return json.loads(_decode_cstring(raw))
        except: pass
    return _fallback_disk_list()

def _fallback_disk_list():
    disks = []
    try:
        r = subprocess.run(["lsblk", "-J", "-o", "NAME,SIZE,TYPE,MOUNTPOINT,MODEL,ROTA"],
                          capture_output=True, text=True, timeout=5)
        if r.returncode == 0:
            data = json.loads(r.stdout)
            for dev in data.get("blockdevices", []):
                if dev.get("type") == "disk":
                    disks.append({"name": dev.get("name",""), "size": dev.get("size",""),
                                  "model": dev.get("model",""), "rotational": dev.get("rota",False)})
    except: pass
    return disks

def get_disk_usage(path="/"):
    lib = _get_lib()
    if lib:
        try:
            declare(lib, "kdk_disk_get_usage", restype=ctypes.c_char_p, argtypes=[ctypes.c_char_p])
            raw = lib.kdk_disk_get_usage(path.encode())
            if raw: return json.loads(_decode_cstring(raw))
        except: pass
    return _fallback_disk_usage(path)

def _fallback_disk_usage(path="/"):
    try:
        stat = os.statvfs(path)
        total = stat.f_blocks * stat.f_frsize
        free = stat.f_bfree * stat.f_frsize
        used = total - free
        return {"path": path, "total_bytes": total, "used_bytes": used, "free_bytes": free,
                "percent": round(used/total*100,1) if total>0 else 0,
                "total": _format_bytes(total), "used": _format_bytes(used), "free": _format_bytes(free)}
    except Exception as e: return {"error": str(e)}

def get_partition_info(device):
    try:
        r = subprocess.run(["lsblk", "-J", "-o", "NAME,SIZE,FSTYPE,LABEL,UUID,MOUNTPOINT", f"/dev/{device}"],
                          capture_output=True, text=True, timeout=5)
        if r.returncode == 0: return json.loads(r.stdout)
    except: pass
    return {}

def get_mount_points():
    mounts = []
    try:
        with open("/proc/mounts") as f:
            for line in f:
                parts = line.split()
                if len(parts) >= 4:
                    mounts.append({"device": parts[0], "mount_point": parts[1],
                                   "filesystem": parts[2], "options": parts[3]})
    except: pass
    return mounts

def _format_bytes(size):
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if abs(size) < 1024.0: return f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} PB"
