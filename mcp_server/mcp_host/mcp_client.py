from __future__ import annotations

import asyncio
import os
import sys
from contextlib import AsyncExitStack
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def _utc_ts() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


def _serialize_content_item(item: Any) -> Dict[str, Any]:
    text = getattr(item, "text", None)
    if isinstance(text, str):
        return {"type": "text", "text": text}

    uri = getattr(item, "uri", None)
    if isinstance(uri, str):
        mime = getattr(item, "mimeType", None) or getattr(item, "mime_type", None)
        return {"type": "resource", "uri": uri, "mimeType": mime}

    data = getattr(item, "data", None)
    if data is not None:
        mime = getattr(item, "mimeType", None) or getattr(item, "mime_type", None)
        try:
            if isinstance(data, (bytes, bytearray)):
                preview = f"<{len(data)} bytes>"
            else:
                s = str(data)
                preview = s if len(s) <= 200 else s[:200] + "..."
        except Exception:
            preview = "<unrepr>"
        return {"type": "blob", "mimeType": mime, "data": preview}

    try:
        return {"type": "unknown", "repr": str(item)}
    except Exception:
        return {"type": "unknown", "repr": "<unrepr>"}


def _serialize_mcp_output(raw: Any) -> Dict[str, Any]:
    parts: List[Dict[str, Any]] = []
    content = getattr(raw, "content", None)
    if isinstance(content, list):
        for it in content:
            try:
                parts.append(_serialize_content_item(it))
            except Exception:
                parts.append({"type": "unknown", "repr": "<serialize_error>"})
    else:
        try:
            s = str(raw)
        except Exception:
            s = "<unrepr>"
        parts.append({"type": "text", "text": s})

    try:
        raw_repr = str(raw)
    except Exception:
        raw_repr = "<unrepr>"

    return {"parts": parts, "raw_repr": raw_repr}


@dataclass
class ServerHandle:
    name: str
    path: str
    stop_event: asyncio.Event
    ready_event: asyncio.Event
    task: asyncio.Task
    session: Optional[ClientSession] = None
    status: str = "stopped"  # connecting|ready|failed|stopped
    last_error: Optional[str] = None
    last_change_ts: str = ""


class MCPClient:
    """MCP server 生命周期 + 工具调用（带状态与更稳的断开）。"""

    def __init__(self):
        self._lock = asyncio.Lock()
        self._servers: Dict[str, ServerHandle] = {}
        self._tool_cache: Dict[str, Dict[str, Dict[str, Any]]] = {}

    def is_connected(self, name: str) -> bool:
        h = self._servers.get(name)
        return bool(h and h.session and h.status == "ready")

    def get_state(self, name: str) -> Dict[str, Any]:
        h = self._servers.get(name)
        if not h:
            return {"status": "stopped", "last_error": None, "last_change_ts": None, "path": None}
        return {
            "status": h.status,
            "last_error": h.last_error,
            "last_change_ts": h.last_change_ts or None,
            "path": h.path,
        }

    def get_cached_tool(self, server: str, tool_name: str) -> Optional[Dict[str, Any]]:
        return (self._tool_cache.get(server) or {}).get(tool_name)

    async def connect_to_server(self, name: str, path: str, timeout_ms: int = 5000):
        path = os.path.abspath(path)

        async with self._lock:
            h = self._servers.get(name)
            if h and h.session and h.status == "ready":
                return

            if h and h.status == "connecting":
                handle = h
            else:
                stop_event = asyncio.Event()
                ready_event = asyncio.Event()
                task = asyncio.create_task(self._server_task(name, path, stop_event, ready_event), name=f"mcp-server-{name}")

                if not h:
                    handle = ServerHandle(
                        name=name,
                        path=path,
                        stop_event=stop_event,
                        ready_event=ready_event,
                        task=task,
                        status="connecting",
                        last_error=None,
                        last_change_ts=_utc_ts(),
                    )
                    self._servers[name] = handle
                else:
                    h.path = path
                    h.stop_event = stop_event
                    h.ready_event = ready_event
                    h.task = task
                    h.session = None
                    h.status = "connecting"
                    h.last_error = None
                    h.last_change_ts = _utc_ts()
                    handle = h

        try:
            if timeout_ms and timeout_ms > 0:
                await asyncio.wait_for(handle.ready_event.wait(), timeout=timeout_ms / 1000.0)
            else:
                await handle.ready_event.wait()
        except asyncio.TimeoutError:
            async with self._lock:
                h2 = self._servers.get(name)
                if h2 and h2.status == "connecting":
                    h2.status = "failed"
                    h2.last_error = f"连接超时（{timeout_ms}ms）"
                    h2.last_change_ts = _utc_ts()
            raise RuntimeError(f"连接超时（{timeout_ms}ms）")

        if not self.is_connected(name):
            err = self._servers.get(name).last_error if self._servers.get(name) else "failed"
            raise RuntimeError(err or "初始化失败")

    async def disconnect_server(self, name: str, timeout_ms: int = 2000):
        async with self._lock:
            h = self._servers.get(name)
            if not h:
                return
            h.stop_event.set()
            task = h.task

        # 先优雅退出，超时再 cancel（尽量避免卡死）
        try:
            await asyncio.wait_for(task, timeout=timeout_ms / 1000.0)
        except asyncio.TimeoutError:
            task.cancel()
            try:
                await asyncio.wait_for(task, timeout=1.0)
            except Exception:
                pass
        except Exception:
            pass

        async with self._lock:
            h2 = self._servers.get(name)
            if h2:
                h2.session = None
                if h2.status != "failed":
                    h2.status = "stopped"
                    h2.last_change_ts = _utc_ts()
            self._tool_cache.pop(name, None)

    async def cleanup(self):
        async with self._lock:
            names = list(self._servers.keys())
        for n in names:
            await self.disconnect_server(n, timeout_ms=1500)

    async def list_tools(self, name: str) -> List[Dict[str, Any]]:
        h = self._servers.get(name)
        if not h or not h.session or h.status != "ready":
            return []

        resp = await h.session.list_tools()
        out: List[Dict[str, Any]] = []
        cache: Dict[str, Dict[str, Any]] = {}

        for t in resp.tools:
            spec = {
                "name": t.name,
                "description": t.description,
                "inputSchema": getattr(t, "inputSchema", None),
            }
            out.append(spec)
            cache[t.name] = spec

        self._tool_cache[name] = cache
        return out

    async def call_tool(self, server_name: str, tool_name: str, args: Optional[dict] = None) -> Dict[str, Any]:
        args = args or {}
        h = self._servers.get(server_name)
        if not h or not h.session or h.status != "ready":
            raise RuntimeError(f"server '{server_name}' 未连接")

        raw = await h.session.call_tool(tool_name, args)
        return _serialize_mcp_output(raw)

    async def _server_task(self, name: str, path: str, stop_event: asyncio.Event, ready_event: asyncio.Event):
        # 默认使用当前 Python 解释器（避免 venv 不一致）
        py_cmd = os.getenv("MCP_PYTHON", sys.executable or "python")

        params = StdioServerParameters(
            command=py_cmd if path.endswith(".py") else "node",
            args=[path],
        )

        h = self._servers.get(name)

        async with AsyncExitStack() as stack:
            try:
                stdio, write = await stack.enter_async_context(stdio_client(params))
                session = await stack.enter_async_context(ClientSession(stdio, write))
                await session.initialize()

                if h:
                    h.session = session
                    h.status = "ready"
                    h.last_error = None
                    h.last_change_ts = _utc_ts()

                ready_event.set()
                await stop_event.wait()

            except Exception as e:
                if h:
                    h.session = None
                    h.status = "failed"
                    h.last_error = str(e)
                    h.last_change_ts = _utc_ts()
                ready_event.set()
            finally:
                if h and h.status == "ready":
                    h.session = None
                    h.status = "stopped"
                    h.last_change_ts = _utc_ts()
                await stack.aclose()
