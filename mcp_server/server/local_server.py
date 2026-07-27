"""
本地工具箱 MCP 服务器 — 使用麒麟 SDK 获取 GPU 及系统信息。

之前: subprocess.run(["nvidia-smi", "-q", "-d", "MEMORY"])
现在: src.sdk.system.get_gpu_summary()
"""
import datetime
import os
from pathlib import Path
from typing import Optional, List, Union

from mcp.server.fastmcp import FastMCP
from src.sdk.system import get_gpu_summary, get_display_info, get_system_info, is_available

mcp = FastMCP("server")

server_name = '本地工具箱'


@mcp.tool()
async def get_current_date_time() -> str:
    """获取当前时间和日期"""
    now = datetime.datetime.now()
    return f'当前时间为：{now.strftime("%Y-%m-%d %H:%M:%S")}'


@mcp.tool()
async def get_gpu_memory_summary() -> str:
    """
    获取当前 GPU / 显示信息摘要。

    使用麒麟 EDID SDK (libkyedid) 获取显示器厂商、型号、分辨率、DPI 等。
    如需 NVIDIA 专有显存使用量，请使用 nvidia-smi 作为补充。
    """
    if not is_available():
        return (
            "GPU/显示信息不可用。请确认在 Kylin 系统上运行，"
            "且已安装: sudo apt install libkysdk-system-dev"
        )

    summary = get_gpu_summary()
    return summary


@mcp.tool()
async def get_system_summary() -> str:
    """获取系统基础信息摘要（架构、厂商、版本等）。"""
    if not is_available():
        return "系统信息 SDK 不可用（非 Kylin 环境）"

    info = get_system_info()
    if not info:
        return "系统信息获取为空"

    parts = []
    for key, label in [
        ("architecture", "架构"),
        ("host_vendor", "主机厂商"),
        ("host_product", "主机型号"),
        ("custom_version", "系统版本"),
        ("build_time", "构建时间"),
        ("activation", "激活状态"),
    ]:
        if info.get(key):
            parts.append(f"{label}: {info[key]}")

    return "系统信息 — " + "，".join(parts) if parts else "系统信息获取为空"


if __name__ == "__main__":
    mcp.run(transport='stdio')
