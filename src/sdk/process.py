"""
Kylin Process SDK - ctypes Python bindings.
Replaces: ps aux, top, pidof, kill

注: 麒麟进程 SDK 由 libkysdk-proc 提供 (安装包: libkysdk-proc libkysdk-proc-dev)，
    库名为 libkyrtinfo.so (头文件 libkyrtinfo.h / libkyprocess.h)，
    函数 kdk_get_process_all_information 返回以 NULL 结尾的 char** 列表。
    原先引用的 libkyproc 库并不存在，已修正为 libkyrtinfo。
"""
import ctypes
import os
import re
import subprocess
import threading
from typing import Dict, Any, List, Tuple

from .base import load_library, _decode_cstring, declare, IS_KYLIN

_LIB = None
_lock = threading.Lock()


def _get_lib():
    global _LIB
    if _LIB is None:
        with _lock:
            if _LIB is None:
                try:
                    _LIB = load_library("libkyrtinfo", mock=not IS_KYLIN)
                except Exception:
                    _LIB = False
    return _LIB if _LIB else None


def _parse_proc_line(s: str) -> Dict[str, Any]:
    """Parse a 'key:value, key:value, ...' process line into a dict."""
    d: Dict[str, Any] = {}
    for part in re.split(r",\s*(?=\w+:)", s):
        if ":" in part:
            k, v = part.split(":", 1)
            d[k.strip()] = v.strip()
    return d


def _sdk_process_list(lib) -> List[Dict[str, Any]]:
    """Fetch the full process list via the SDK."""
    declare(lib, "kdk_get_process_all_information",
            restype=ctypes.POINTER(ctypes.c_char_p))
    declare(lib, "kdk_proc_freeall",
            argtypes=[ctypes.POINTER(ctypes.c_char_p)], restype=None)
    ptr = lib.kdk_get_process_all_information()
    if not ptr:
        return []
    procs = []
    try:
        i = 0
        while ptr[i]:
            raw = ptr[i].decode("utf-8", errors="replace")
            d = _parse_proc_line(raw)
            # 统一字段名，与 /proc 回退保持一致
            proc = {
                "pid": int(d.get("process_id", 0) or 0),
                "name": d.get("proc_name", ""),
                "cmdline": d.get("proc_command", "") or d.get("proc_name", ""),
            }
            for k, v in d.items():
                proc.setdefault(k, v)
            procs.append(proc)
            i += 1
    finally:
        lib.kdk_proc_freeall(ptr)
    return procs


def get_process_list():
    lib = _get_lib()
    if lib:
        try:
            procs = _sdk_process_list(lib)
            if procs:
                return procs
        except Exception:
            pass
    return _fallback_process_list()


def _fallback_process_list():
    procs = []
    try:
        for pid in os.listdir("/proc"):
            if not pid.isdigit():
                continue
            try:
                pp = f"/proc/{pid}"
                with open(f"{pp}/comm") as f:
                    name = f.read().strip()
                with open(f"{pp}/cmdline") as f:
                    cmdline = f.read().replace("\0", " ").strip()
                procs.append({"pid": int(pid), "name": name, "cmdline": cmdline or name})
            except Exception:
                pass
    except Exception:
        pass
    return procs


def get_process_info(pid):
    info = {"pid": pid}
    try:
        pp = f"/proc/{pid}"
        with open(f"{pp}/comm") as f:
            info["name"] = f.read().strip()
        with open(f"{pp}/cmdline") as f:
            info["cmdline"] = f.read().replace("\0", " ").strip()
        with open(f"{pp}/status") as f:
            for line in f:
                if ":" in line:
                    k, v = line.split(":", 1)
                    info[k.strip().lower()] = v.strip()
    except Exception:
        pass
    return info


def kill_process(pid, signal=15):
    try:
        os.kill(pid, signal)
        names = {15: "SIGTERM", 9: "SIGKILL", 2: "SIGINT", 1: "SIGHUP"}
        return True, f"Sent {names.get(signal, str(signal))} to PID {pid}"
    except ProcessLookupError:
        return False, f"PID {pid} not found"
    except PermissionError:
        return False, f"Permission denied for PID {pid}"
    except Exception as e:
        return False, str(e)


def get_process_by_name(name):
    return [p for p in get_process_list() if name.lower() in str(p.get("name", "")).lower()]


is_available = lambda: _get_lib() is not None
