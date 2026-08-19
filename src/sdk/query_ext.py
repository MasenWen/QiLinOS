#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""子进程隔离查询：C 库调用在主进程内 SIGSEGV（libkyedid/libkyrealtime），
本模块供主进程以 subprocess 方式调用，C 库崩溃不影响主进程。
用法: python query_ext.py <info_type>  → 输出单行 JSON {"ok": ...}
"""
import json
import os
import sys

# 项目根加入 sys.path（本脚本位于 src/sdk/ 下，需能 import src.*）
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


def _call(lib, fn, bound_libs, safe_cstring):
    l = bound_libs.get(lib)
    if l and hasattr(l, fn):
        try:
            import ctypes
            f = getattr(l, fn)
            if f.restype in (ctypes.c_char_p,):
                return safe_cstring(l, fn)  # Kylin segfault 规避
            return (lambda: f())()  # 数值接口 lambda 上下文
        except Exception:
            return None
    return None


def main():
    info_type = sys.argv[1] if len(sys.argv) > 1 else ""
    from src.sdk import official_bind as ob
    from src.sdk.base import _safe_cstring_call

    result = {}
    try:
        if info_type in ("edid", "monitor", "display"):
            parts = []
            for label, fn in (("厂商", "kdk_edid_get_manufacturer"),
                              ("型号", "kdk_edid_get_model"),
                              ("最大分辨率", "kdk_edid_get_max_resolution")):
                v = _call("libkyedid", fn, ob.BOUND_LIBS, _safe_cstring_call)
                if v:
                    parts.append(f"{label}: {v}")
            if parts:
                result["ok"] = "显示器信息（官方 SDK edid）\n" + "\n".join(parts)
        elif info_type in ("temp", "temperature"):
            v = _call("libkyrealtime", "kdk_real_get_cpu_temperature",
                      ob.BOUND_LIBS, _safe_cstring_call)
            if v is not None:
                result["ok"] = f"CPU 温度: {v}（官方 SDK realtime）"
        elif info_type in ("netspeed", "net_speed"):
            v = _call("libkyrealtime", "kdk_real_get_net_speed",
                      ob.BOUND_LIBS, _safe_cstring_call)
            if v is not None and v >= 0:
                result["ok"] = f"瞬时网速: {v}（官方 SDK realtime）"
    except Exception as e:
        result["err"] = str(e)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
