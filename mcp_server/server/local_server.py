import re
import subprocess
from mcp.server.fastmcp import FastMCP
import datetime
import os
from pathlib import Path
from typing import Optional, List, Union

mcp = FastMCP("server")

server_name = '本地工具箱'

@mcp.tool()
async def get_current_date_time() -> str:
    """
    获取当前时间和日期
    """
    import datetime
    now = datetime.datetime.now()
    return f'当前时间为：{now.strftime("%Y-%m-%d %H:%M:%S")}'

@mcp.tool()
async def get_gpu_memory_summary() -> str:
    """
    获取当前 GPU 显存使用情况摘要，包括总量、已用、剩余及使用率。
    """
    # 获取显存详细信息
    result = subprocess.run(
        ["nvidia-smi", "-q", "-d", "MEMORY"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True
    )
    text = result.stdout

    total = used = free = None
    in_fb = False
    for line in text.splitlines():
        if "FB Memory Usage" in line:
            in_fb = True
            continue
        if in_fb:
            # 遇到下一个板块则退出
            if line.strip().endswith("Memory Usage"):
                break
            m = re.match(r"\s*Total\s*:\s*(\d+)\s*MiB", line)
            if m:
                total = int(m.group(1))
                continue
            m = re.match(r"\s*Used\s*:\s*(\d+)\s*MiB", line)
            if m:
                used = int(m.group(1))
                continue
            m = re.match(r"\s*Free\s*:\s*(\d+)\s*MiB", line)
            if m:
                free = int(m.group(1))
                continue
    # 如果解析失败，则返回原始文本
    if total is None or used is None or free is None:
        return text
    usage = used / total * 100
    return (
        f"GPU 显存总量: {total} MiB，已用: {used} MiB，剩余: {free} MiB，使用率: {usage:.2f}%"
    )

if __name__ == "__main__":
    mcp.run(transport='stdio')