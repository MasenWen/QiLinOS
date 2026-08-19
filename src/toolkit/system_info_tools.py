"""系统信息查询工具（CPU/内存/负载等）— 解决"cpu占用情况"类查询

封装 SDK query_system_info，按 info_type 查询系统状态。
"""
from __future__ import annotations

import logging
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

    @staticmethod
    def _official_ext(info_type: str) -> "ToolResult | None":
        """官方 SDK 扩展查询：显示器(edid)/温度(realtime)/网速。

        ⚠️ libkyedid / libkyrealtime 的 C 函数在 webchat 主进程内调用会 SIGSEGV
        （并发或特定环境下崩溃、直接杀死进程）。因此所有 C 调用隔离到子进程
        （src/sdk/query_ext.py），子进程崩溃不影响主进程。
        """
        import json as _json
        import os as _os
        import subprocess as _sp
        import sys as _sys

        base = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))  # .../src
        helper = _os.path.join(base, "sdk", "query_ext.py")
        if not _os.path.exists(helper):
            return None
        try:
            r = _sp.run(
                [_sys.executable, helper, info_type],
                capture_output=True, text=True, timeout=10,
                cwd=_os.path.dirname(base),  # 项目根，保证 import src.*
            )
            out = (r.stdout or "").strip()
            if out:
                data = _json.loads(out.splitlines()[-1])
                if data.get("ok"):
                    return __import__("src.toolkit.base", fromlist=["ToolResult"]).ToolResult(
                        tool_name="sysinfo",
                        status=__import__("src.toolkit.base", fromlist=["ToolStatus"]).ToolStatus.SUCCESS,
                        output=data["ok"])
        except Exception as e:
            print(f"[sysinfo] 子进程 SDK 查询失败({info_type}): {e}", flush=True)

        # netspeed：SDK 无有效数据 → /proc/net/dev 两次采样（1s）计算实时网速（纯 Python，安全）
        if info_type in ("netspeed", "net_speed"):
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
