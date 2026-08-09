"""
Kylin Process SDK - ctypes Python bindings.
Replaces: ps aux, top, pidof, kill
"""
import ctypes, os, subprocess
from typing import Dict, Any, List, Tuple
from .base import load_library, _decode_cstring, declare, IS_LINUX, IS_KYLIN

_LIB = None
def _get_lib():
    global _LIB
    if _LIB is None:
        _LIB = load_library("libkyproc", mock=not IS_KYLIN)
    return _LIB

def get_process_list():
    lib = _get_lib()
    if lib:
        try:
            declare(lib, "kdk_proc_get_list", restype=ctypes.c_char_p)
            raw = lib.kdk_proc_get_list()
            if raw:
                import json
                return json.loads(_decode_cstring(raw))
        except: pass
    return _fallback_process_list()

def _fallback_process_list():
    procs = []
    try:
        for pid in os.listdir("/proc"):
            if not pid.isdigit(): continue
            try:
                pp = f"/proc/{pid}"
                with open(f"{pp}/comm") as f: name = f.read().strip()
                with open(f"{pp}/cmdline") as f: cmdline = f.read().replace("\0", " ").strip()
                procs.append({"pid": int(pid), "name": name, "cmdline": cmdline or name})
            except: pass
    except: pass
    return procs

def get_process_info(pid):
    info = {"pid": pid}
    try:
        pp = f"/proc/{pid}"
        with open(f"{pp}/comm") as f: info["name"] = f.read().strip()
        with open(f"{pp}/cmdline") as f: info["cmdline"] = f.read().replace("\0", " ").strip()
        with open(f"{pp}/status") as f:
            for line in f:
                if ":" in line:
                    k, v = line.split(":", 1)
                    info[k.strip().lower()] = v.strip()
    except: pass
    return info

def kill_process(pid, signal=15):
    try:
        os.kill(pid, signal)
        names = {15: "SIGTERM", 9: "SIGKILL", 2: "SIGINT", 1: "SIGHUP"}
        return True, f"Sent {names.get(signal, str(signal))} to PID {pid}"
    except ProcessLookupError: return False, f"PID {pid} not found"
    except PermissionError: return False, f"Permission denied for PID {pid}"
    except Exception as e: return False, str(e)

def get_process_by_name(name):
    return [p for p in get_process_list() if name.lower() in p.get("name","").lower()]
