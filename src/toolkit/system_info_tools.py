"""系统信息查询工具（CPU/内存/负载等）— 解决"cpu占用情况"类查询

封装 SDK query_system_info，按 info_type 查询系统状态。
"""
from __future__ import annotations

import logging
import threading
from typing import Any

from .base import BaseTool, ToolResult

logger = logging.getLogger("toolkit.sysinfo")


class SystemInfoTool(BaseTool):
    """查询系统信息（CPU/内存/负载/磁盘/网络等）。"""

    name = "sysinfo"
    description = (
        "查询系统信息。info_type: cpu=CPU占用/型号, memory=内存占用, load=系统负载, "
        "disk=磁盘, network=网络, basic=基本信息, hostname, uptime, arch, "
        "display=显示器/屏幕(厂商/型号/分辨率) 等。"
        "例如查询\"cpu占用情况\"用 info_type=cpu。"
    )
    risk = None  # 由注册处指定
    requires_approval = False
    timeout_s = 10.0

    _VALID_TYPES = {
        "basic", "kernel", "cpu", "memory", "disk", "load", "network",
        "battery", "gpu", "fans", "hostname", "arch", "uptime",
        "boot_time", "locale", "edid", "monitor", "display", "temp", "temperature",
        "package", "netspeed", "net_speed",
    }

    def execute(self, **kwargs) -> ToolResult:
        info_type = (kwargs.get("info_type") or "").strip().lower() or "cpu"
        if info_type not in self._VALID_TYPES:
            return self._fail(
                f"未知 info_type: '{info_type}'。可用: {', '.join(sorted(self._VALID_TYPES))}"
            )
        # 系统命令兜底（SDK 无返回时用标准工具）
        _FALLBACK = {
            "cpu": ["top", "-bn1"],
            "load": ["cat", "/proc/loadavg"],
            "memory": ["free", "-h"],
            "uptime": ["uptime"],
            "arch": ["uname", "-m"],
        }
        # ---- 官方 SDK 扩展分支（edid/温度/包/网速）----
        ext = self._official_ext(info_type)
        if ext is not None:
            return ext
        try:
            from src.sdk.system import query_system_info
            text = query_system_info(info_type)
            if text and "当前环境中不可用" not in text and "不可用" not in text[:20]:
                return self._ok(text)
        except Exception:
            text = ""
        # fallback 到标准系统命令
        cmd = _FALLBACK.get(info_type)
        if cmd:
            try:
                import subprocess
                r = subprocess.run(cmd, capture_output=True, text=True, timeout=8)
                if r.returncode == 0 and r.stdout.strip():
                    return self._ok(r.stdout.strip()[:500])
            except Exception:
                pass
        return self._fail(f"查询 {info_type} 失败（SDK 与系统命令均无返回）")

    _SDK_EXT_LOCK = threading.Lock()  # libkyedid 等 C 库并发调用 SIGSEGV，全局串行化

    @staticmethod
    def _official_ext(info_type: str) -> "ToolResult | None":
        """官方 SDK 扩展查询：显示器(edid)/温度(realtime)/包(package)/网速。"""
        from src.sdk import official_bind as ob
        from src.sdk.base import _safe_cstring_call, _decode_cstring
        import ctypes

        def _call(lib, fn):
            with SystemInfoTool._SDK_EXT_LOCK:
                l = ob.BOUND_LIBS.get(lib)
                if l and hasattr(l, fn):
                    try:
                        f = getattr(l, fn)
                        if f.restype in (ctypes.c_char_p,):
                            return _safe_cstring_call(l, fn)  # Kylin segfault 规避
                        return (lambda: f())()  # 数值接口 lambda 上下文
                    except Exception:
                        return None
            return None

        if info_type in ("edid", "monitor", "display"):
            parts = []
            # 仅封装已验证安全的接口（kdk_edid_get_interface 在 Kylin 上 segfault，跳过）
            for label, fn in (("厂商", "kdk_edid_get_manufacturer"), ("型号", "kdk_edid_get_model"),
                              ("最大分辨率", "kdk_edid_get_max_resolution")):
                v = _call("libkyedid", fn)
                if v:
                    parts.append(f"{label}: {v}")
            if parts:
                return __import__("src.toolkit.base", fromlist=["ToolResult"]).ToolResult(
                    tool_name="sysinfo", status=__import__("src.toolkit.base", fromlist=["ToolStatus"]).ToolStatus.SUCCESS,
                    output="显示器信息（官方 SDK edid）\n" + "\n".join(parts))
        if info_type in ("temp", "temperature"):
            v = _call("libkyrealtime", "kdk_real_get_cpu_temperature")
            if v is not None:
                return __import__("src.toolkit.base", fromlist=["ToolResult"]).ToolResult(
                    tool_name="sysinfo", status=__import__("src.toolkit.base", fromlist=["ToolStatus"]).ToolStatus.SUCCESS,
                    output=f"CPU 温度: {v}（官方 SDK realtime）")
        # package 接口需先 init 且返回列表结构，未封装（避免误读内存地址）
        if info_type in ("netspeed", "net_speed"):
            v = _call("libkyrealtime", "kdk_real_get_net_speed")
            if v is not None and v >= 0:
                return __import__("src.toolkit.base", fromlist=["ToolResult"]).ToolResult(
                    tool_name="sysinfo", status=__import__("src.toolkit.base", fromlist=["ToolStatus"]).ToolStatus.SUCCESS,
                    output=f"瞬时网速: {v}（官方 SDK realtime）")
            # SDK 无有效数据 → /proc/net/dev 两次采样（1s）计算实时网速
            try:
                import time

                def _rx_tx():
                    with open("/proc/net/dev", "r", encoding="utf-8") as f:
                        for line in f:
                            if any(k in line for k in ("ens", "eth", "enp")):
                                p = line.split()
                                return int(p[1]), int(p[9])
                    return None
                a = _rx_tx()
                time.sleep(1)
                b = _rx_tx()
                if a and b:
                    rx = max(b[0] - a[0], 0) / 1024.0 / 1024.0
                    tx = max(b[1] - a[1], 0) / 1024.0 / 1024.0
                    return __import__("src.toolkit.base", fromlist=["ToolResult"]).ToolResult(
                        tool_name="sysinfo", status=__import__("src.toolkit.base", fromlist=["ToolStatus"]).ToolStatus.SUCCESS,
                        output=f"实时网速（/proc/net/dev 1s 采样）: 下载 {rx:.2f} MiB/s, 上传 {tx:.2f} MiB/s")
            except Exception:
                pass
        return None

    def verify(self, **kwargs) -> bool:
        # 只读查询：无需验证
        return True

    def rollback(self, **kwargs) -> bool:
        # 只读查询：无需回滚
        return True


def register_system_info_tools(registry=None):
    """注册系统信息查询工具。"""
    if registry is None:
        from .base import get_registry
        registry = get_registry()
    from .base import RiskLevel
    tool = SystemInfoTool()
    tool.risk = RiskLevel.LOW
    registry.register_many([tool])
    return registry
