from __future__ import annotations

import asyncio
import logging
import os
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request

from .audit_log import AuditLogger
from src.utils.db_manager import DBManager
from .constants import HIDDEN_SERVERS
from .mcp_client import MCPClient
from .registry_manager import ServerRegistry

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("mcp-host")


async def _autostart_servers(client: MCPClient, registry: ServerRegistry, audit: AuditLogger):
    timeout_ms = int(float(os.getenv("MCP_AUTOSTART_TIMEOUT_SEC", "5.0")) * 1000)

    async def _boot(entry: dict):
        if not entry.get("auto_start"):
            return
        name = entry.get("name")
        path = entry.get("abs_path")
        if not name or not path:
            audit.log("autostart_skip", {"server": name, "reason": "missing name/path"})
            return
        if name in HIDDEN_SERVERS:
            return

        audit.log("autostart_begin", {"server": name, "path": path})
        try:
            await client.connect_to_server(name, path, timeout_ms=timeout_ms)
            audit.log("autostart_ok", {"server": name, "path": path, "success": True})
        except Exception as e:
            audit.log("autostart_error", {"server": name, "path": path, "success": False, "error": str(e)})

    for entry in registry.list_all_servers():
        if entry.get("name") in HIDDEN_SERVERS:
            continue
        asyncio.create_task(_boot(entry))


@asynccontextmanager
async def lifespan(app: FastAPI):
    client = MCPClient()
    registry = ServerRegistry(
        registry_path=os.getenv("MCP_REGISTRY_PATH", "./mcp_server/servers_registry.json"),
        servers_base_dir=os.getenv("MCP_SERVERS_BASE_DIR", "./mcp_server/server"),
    )
    audit = AuditLogger(path=os.getenv("MCP_AUDIT_PATH", os.path.join("logs", "mcp_host.log.jsonl")))
    db = DBManager()
    app.state.mcp_client = client
    app.state.registry = registry
    app.state.audit = audit
    app.state.db = db

    asyncio.create_task(_autostart_servers(client, registry, audit))

    try:
        yield
    finally:
        try:
            await client.cleanup()
        finally:
            audit.log("host_shutdown", {})


def get_client(app: FastAPI) -> MCPClient:
    return app.state.mcp_client


def get_registry(app: FastAPI) -> ServerRegistry:
    return app.state.registry


def get_audit(app: FastAPI) -> AuditLogger:
    return app.state.audit


def get_request_id(req: Request) -> str:
    return req.headers.get("X-Request-Id") or str(uuid.uuid4())


def get_db(app: FastAPI) -> DBManager:
    return app.state.db