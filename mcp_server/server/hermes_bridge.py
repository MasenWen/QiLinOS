#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Hermes Bridge MCP Server —— 通过 Python import 直接调用 Hermes Agent

v3.1: 精简优化版
  - 直接 import AIAgent，无 MCP 子进程
  - 自动读取 Hermes config.yaml
  - 移除冗余代码

架构:
  nex-agent (MCPClient)
      └── hermes_bridge.py
              │  Python import → run_agent.AIAgent
              ▼
          Hermes Agent (记忆/技能/搜索/终端/浏览器)
"""

import asyncio
import atexit
import json
import logging
import os
import sys
import time
from pathlib import Path

import yaml
from mcp.server.fastmcp import FastMCP

logging.basicConfig(stream=sys.stderr, level=logging.INFO)
logger = logging.getLogger("hermes-bridge")

mcp = FastMCP("HermesBridge")

# ============================================================================
# 配置
# ============================================================================
HERMES_HOME = Path(os.path.expanduser(os.getenv("HERMES_HOME", "~/.hermes")))
HERMES_SRC = HERMES_HOME / "hermes-agent"

# 将 Hermes 源码插入 sys.path 最前面，确保 agent/ 包优先从 Hermes 加载
sys.path.insert(0, str(HERMES_SRC))


def _read_hermes_config() -> dict:
    """读取 Hermes config.yaml 获取模型配置。"""
    config_path = HERMES_HOME / "config.yaml"
    if not config_path.exists():
        logger.warning("⚠ config.yaml 不存在: %s", config_path)
        return {}
    with open(config_path) as f:
        return yaml.safe_load(f) or {}


def _get_api_key(provider: str) -> str:
    """根据 provider 获取 API key（先查环境变量，再查 Hermes .env）。"""
    env_map = {
        "deepseek": "DEEPSEEK_API_KEY",
        "openai": "OPENAI_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
        "openrouter": "OPENROUTER_API_KEY",
    }
    key_name = env_map.get(provider, f"{provider.upper()}_API_KEY")

    # 1. 当前进程环境变量
    key = os.getenv(key_name, "")
    if key:
        return key

    # 2. Hermes .env 文件
    env_file = HERMES_HOME / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if line.strip().startswith(key_name + "="):
                return line.strip().split("=", 1)[1].strip().strip('"').strip("'")
    return ""


# ============================================================================
# Hermes Agent 管理器
# ============================================================================

class HermesAgentManager:
    """管理 Hermes AIAgent 实例（延迟初始化 + 线程安全单例）。"""

    def __init__(self):
        self._agent = None
        self._ready = False
        self._error = ""
        self._lock = asyncio.Lock()
        self._model = ""
        self._provider = ""

    @property
    def is_ready(self) -> bool:
        return self._ready and self._agent is not None

    @property
    def model(self) -> str:
        return self._model

    @property
    def provider(self) -> str:
        return self._provider

    @property
    def error(self) -> str:
        return self._error

    async def initialize(self) -> bool:
        async with self._lock:
            if self._ready and self._agent:
                return True

            try:
                logger.info("🔧 初始化 Hermes Agent (Python import)...")

                config = _read_hermes_config()
                mc = config.get("model", {})
                self._model = mc.get("default", "deepseek-chat")
                self._provider = mc.get("provider", "deepseek")
                base_url = mc.get("base_url", "https://api.deepseek.com/v1")
                api_key = _get_api_key(self._provider)

                if not api_key:
                    self._error = f"未找到 {self._provider} 的 API Key"
                    return False

                logger.info("  %s @ %s", self._model, base_url)

                from run_agent import AIAgent

                self._agent = AIAgent(
                    provider=self._provider,
                    model=self._model,
                    base_url=base_url,
                    api_key=api_key,
                    quiet_mode=True,
                )
                self._ready = True
                logger.info("✅ Hermes Agent 就绪")
                return True

            except Exception as e:
                self._error = str(e)
                logger.error("❌ 初始化失败: %s", e)
                return False

    async def chat(self, prompt: str) -> str:
        if not self.is_ready and not await self.initialize():
            return json.dumps({
                "error": "Hermes Agent 未就绪", "detail": self._error,
            }, ensure_ascii=False)

        try:
            result = await asyncio.to_thread(self._agent.chat, prompt)
            return result or json.dumps({"message": "已处理"})
        except Exception as e:
            logger.error("❌ chat 失败: %s", e)
            return json.dumps({"error": str(e)}, ensure_ascii=False)

    async def shutdown(self):
        if self._agent:
            try:
                self._agent.close()
            except Exception:
                pass
        self._agent = None
        self._ready = False


_manager = HermesAgentManager()


# ============================================================================
# MCP 工具
# ============================================================================

@mcp.tool()
async def hermes_ask(prompt: str) -> str:
    """通过 Hermes Agent 处理自然语言请求（主要交互入口）。

    Hermes 内部自动调用记忆系统、技能库、搜索、浏览器、终端等。
    """
    return await _manager.chat(prompt)


@mcp.tool()
async def hermes_chat(prompt: str) -> str:
    """与 Hermes 对话（同 hermes_ask，兼容别名）。"""
    return await _manager.chat(prompt)


@mcp.tool()
async def hermes_status() -> str:
    """Hermes 桥接整体状态。"""
    return json.dumps({
        "bridge_version": "3.1",
        "bridge_mode": "Python import (AIAgent)",
        "hermes_home": str(HERMES_HOME),
        "agent_ready": _manager.is_ready,
        "model": _manager.model,
        "provider": _manager.provider,
        "error": _manager.error,
        "tools": [
            "hermes_ask", "hermes_chat",
            "hermes_memory_status", "hermes_read_memory", "hermes_write_memory",
            "hermes_status",
        ],
    }, ensure_ascii=False, indent=2)


@mcp.tool()
async def hermes_memory_status() -> str:
    """Hermes 记忆系统状态。"""
    memories_dir = HERMES_HOME / "memories"
    files = (
        [f.name for f in memories_dir.iterdir() if f.suffix == ".md"]
        if memories_dir.is_dir() else []
    )
    return json.dumps({
        "memories_dir": str(memories_dir),
        "files": files,
        "agent_ready": _manager.is_ready,
    }, ensure_ascii=False, indent=2)


@mcp.tool()
async def hermes_read_memory(filename: str = "MEMORY.md") -> str:
    """读取 Hermes 记忆文件。

    Args:
        filename: "MEMORY.md"（项目记忆）或 "USER.md"（用户偏好）
    """
    filepath = HERMES_HOME / "memories" / filename
    if not filepath.exists():
        return json.dumps({
            "error": f"文件不存在: {filepath}",
            "available": [f.name for f in (HERMES_HOME / "memories").iterdir()
                          if f.suffix == ".md"] if (HERMES_HOME / "memories").is_dir() else [],
        }, ensure_ascii=False, indent=2)
    return filepath.read_text(encoding="utf-8")


@mcp.tool()
async def hermes_write_memory(filename: str, content: str) -> str:
    """向 Hermes 记忆文件追加内容。

    Args:
        filename: "MEMORY.md" 或 "USER.md"
        content: Markdown 格式内容
    """
    memories_dir = HERMES_HOME / "memories"
    memories_dir.mkdir(parents=True, exist_ok=True)
    filepath = memories_dir / filename
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    entry = f"\n\n---\n## {timestamp}\n{content}\n"
    filepath.write_text(
        (filepath.read_text(encoding="utf-8") if filepath.exists() else "") + entry,
        encoding="utf-8",
    )
    return json.dumps({
        "success": True, "file": filename,
        "path": str(filepath), "timestamp": timestamp,
    }, ensure_ascii=False, indent=2)


# ============================================================================
# 清理
# ============================================================================

def _sync_shutdown():
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.create_task(_manager.shutdown())
        else:
            loop.run_until_complete(_manager.shutdown())
    except Exception:
        pass


atexit.register(_sync_shutdown)


# ============================================================================
# 入口
# ============================================================================

if __name__ == "__main__":
    logger.info("=" * 50)
    logger.info("  Hermes Bridge v3.1")
    logger.info("  Mode: Python import (AIAgent)")
    logger.info("  Hermes: %s", HERMES_SRC)
    logger.info("=" * 50)
    mcp.run()
