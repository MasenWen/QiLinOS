from __future__ import annotations

import asyncio
import os
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

from .constants import HIDDEN_SERVERS
from .models import ConnectRequest, ToolCallRequest, RegisterServerRequest, UpdateServerRequest
from .runtime import get_audit, get_client, get_registry, get_request_id
from .mcp_config import generate_mcp_config, write_mcp_config_file

router = APIRouter(tags=["mcp"])


def _require_connected(client, name: str):
    if not client.is_connected(name):
        state = client.get_state(name)
        raise HTTPException(status_code=409, detail=f"server '{name}' 未连接（状态={state.get('status')}）")


@router.get("/health")
async def health() -> Dict[str, str]:
    return {"status": "ok"}


@router.get("/servers")
async def list_servers(request: Request) -> Dict[str, Any]:
    app = request.app
    client = get_client(app)
    registry = get_registry(app)

    servers: List[Dict[str, Any]] = []
    for item in registry.list_all_servers():
        name = item.get("name")
        if name in HIDDEN_SERVERS:
            continue
        state = client.get_state(name) if name else {"status": "stopped", "last_error": None}
        servers.append({
            **item,
            "connected": bool(name and client.is_connected(name)),
            "status": state.get("status"),
            "last_error": state.get("last_error"),
            "last_change_ts": state.get("last_change_ts"),
        })

    return {"servers": servers}


@router.get("/servers/{name}")
async def get_server(request: Request, name: str) -> Dict[str, Any]:
    if name in HIDDEN_SERVERS:
        raise HTTPException(status_code=404, detail="server 不存在")

    app = request.app
    client = get_client(app)
    registry = get_registry(app)

    info = registry.get_server_info(name)
    if not info:
        raise HTTPException(status_code=404, detail=f"registry 中没有找到 server '{name}'")

    state = client.get_state(name)
    return {
        "name": name,
        "description": info.get("description", ""),
        "filename": info.get("filename", ""),
        "abs_path": info.get("abs_path", ""),
        "auto_start": bool(info.get("auto_start", False)),
        "connected": client.is_connected(name),
        "status": state.get("status"),
        "last_error": state.get("last_error"),
        "last_change_ts": state.get("last_change_ts"),
    }


@router.post("/servers/{name}/connect")
async def connect_server(request: Request, name: str, body: ConnectRequest) -> Dict[str, Any]:
    if name in HIDDEN_SERVERS:
        raise HTTPException(status_code=404, detail="server 不存在")

    app = request.app
    rid = get_request_id(request)
    client = get_client(app)
    registry = get_registry(app)
    audit = get_audit(app)

    info = registry.get_server_info(name)
    path = body.path or (info.get("abs_path") if info else None)
    if not path:
        audit.log("connect_fail", {"server": name, "reason": "no_path"}, request_id=rid)
        raise HTTPException(status_code=400, detail=f"未提供 path 且 registry 中没有 '{name}' 的 abs_path")

    if client.is_connected(name):
        return {"server": name, "connected": True, "path": path, "request_id": rid, "already": True}

    audit.log("connect_begin", {"server": name, "path": path, "timeout_ms": body.timeout_ms}, request_id=rid)
    try:
        await client.connect_to_server(name, path, timeout_ms=body.timeout_ms or 0)
        audit.log("connect_ok", {"server": name, "path": path, "success": True}, request_id=rid)
        return {"server": name, "connected": True, "path": path, "request_id": rid}
    except Exception as e:
        audit.log("connect_error", {"server": name, "path": path, "success": False, "error": str(e)}, request_id=rid)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/servers/{name}/disconnect")
async def disconnect_server(request: Request, name: str) -> Dict[str, Any]:
    if name in HIDDEN_SERVERS:
        raise HTTPException(status_code=404, detail="server 不存在")

    app = request.app
    rid = get_request_id(request)
    client = get_client(app)
    audit = get_audit(app)

    audit.log("disconnect_begin", {"server": name}, request_id=rid)
    await client.disconnect_server(name, timeout_ms=int(os.getenv("MCP_DISCONNECT_TIMEOUT_MS", "2000")))
    audit.log("disconnect_end", {"server": name, "success": True}, request_id=rid)

    return {"server": name, "connected": False, "request_id": rid}


@router.get("/servers/{name}/tools")
async def list_tools(request: Request, name: str) -> Dict[str, Any]:
    if name in HIDDEN_SERVERS:
        raise HTTPException(status_code=404, detail="server 不存在")

    client = get_client(request.app)
    _require_connected(client, name)

    tools = await client.list_tools(name)
    return {"server": name, "count": len(tools), "tools": tools}


@router.get("/servers/{name}/tools/{tool_name}")
async def get_tool_schema(request: Request, name: str, tool_name: str) -> Dict[str, Any]:
    if name in HIDDEN_SERVERS:
        raise HTTPException(status_code=404, detail="server 不存在")

    client = get_client(request.app)
    _require_connected(client, name)

    spec = client.get_cached_tool(name, tool_name)
    if spec is None:
        await client.list_tools(name)
        spec = client.get_cached_tool(name, tool_name)

    if spec is None:
        raise HTTPException(status_code=404, detail=f"server '{name}' 上找不到 tool '{tool_name}'")

    return {"server": name, "tool": tool_name, "spec": spec}


@router.post("/servers/{name}/tools/{tool_name}")
async def call_tool(request: Request, name: str, tool_name: str, body: ToolCallRequest) -> Dict[str, Any]:
    if name in HIDDEN_SERVERS:
        raise HTTPException(status_code=404, detail="server 不存在")

    rid = get_request_id(request)
    client = get_client(request.app)
    audit = get_audit(request.app)

    _require_connected(client, name)

    args = body.args or {}
    timeout_ms = body.timeout_ms or 0

    audit.log("tool_call_begin", {"server": name, "tool": tool_name, "args": args, "timeout_ms": timeout_ms}, request_id=rid)

    try:
        coro = client.call_tool(name, tool_name, args)
        if timeout_ms > 0:
            result = await asyncio.wait_for(coro, timeout=timeout_ms / 1000.0)
        else:
            result = await coro

        audit.log("tool_call_ok", {"server": name, "tool": tool_name, "success": True}, request_id=rid)
        return {"server": name, "tool": tool_name, "result": result, "request_id": rid}
    except asyncio.TimeoutError:
        audit.log("tool_call_timeout", {"server": name, "tool": tool_name, "success": False}, request_id=rid)
        raise HTTPException(status_code=504, detail="调用超时")
    except Exception as e:
        audit.log("tool_call_error", {"server": name, "tool": tool_name, "success": False, "error": str(e)}, request_id=rid)
        raise HTTPException(status_code=500, detail=str(e))


# ---------- registry ----------

@router.get("/servers/registry")
async def get_registry_view(request: Request) -> Dict[str, Any]:
    registry = get_registry(request.app)
    servers = [s for s in registry.list_all_servers() if s.get("name") not in HIDDEN_SERVERS]
    return {"servers": servers}


@router.post("/servers/registry")
async def register_server(request: Request, body: RegisterServerRequest) -> Dict[str, Any]:
    if body.name in HIDDEN_SERVERS:
        raise HTTPException(status_code=400, detail="该名称被系统隐藏/保留，请换一个名称")

    registry = get_registry(request.app)
    client = get_client(request.app)
    audit = get_audit(request.app)
    rid = get_request_id(request)

    try:
        registry.register_server(
            name=body.name,
            filename=body.filename,
            abs_path=body.abs_path,
            description=body.description,
            auto_start=body.auto_start,
            overwrite=body.overwrite,
        )
        audit.log("registry_add", {"server": body.name, "success": True}, request_id=rid)
    except Exception as e:
        audit.log("registry_add_error", {"server": body.name, "success": False, "error": str(e)}, request_id=rid)
        raise HTTPException(status_code=400, detail=str(e))

    # auto_start=true：best-effort 启动
    if body.auto_start and (not client.is_connected(body.name)):
        info = registry.get_server_info(body.name)
        if info and info.get("abs_path"):
            try:
                await client.connect_to_server(body.name, info["abs_path"], timeout_ms=5000)
            except Exception:
                pass

    return {"ok": True, "server": body.name}


@router.patch("/servers/registry/{name}")
async def update_server(request: Request, name: str, body: UpdateServerRequest) -> Dict[str, Any]:
    if name in HIDDEN_SERVERS:
        raise HTTPException(status_code=404, detail="server 不存在")

    registry = get_registry(request.app)
    audit = get_audit(request.app)
    rid = get_request_id(request)

    try:
        registry.update_server(
            name=name,
            filename=body.filename,
            abs_path=body.abs_path,
            description=body.description,
            auto_start=body.auto_start,
        )
        audit.log("registry_update", {"server": name, "success": True}, request_id=rid)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"server '{name}' 不存在")
    except Exception as e:
        audit.log("registry_update_error", {"server": name, "success": False, "error": str(e)}, request_id=rid)
        raise HTTPException(status_code=400, detail=str(e))

    return {"ok": True, "server": name}


@router.delete("/servers/registry/{name}")
async def delete_server(request: Request, name: str) -> Dict[str, Any]:
    if name in HIDDEN_SERVERS:
        raise HTTPException(status_code=404, detail="server 不存在")

    registry = get_registry(request.app)
    client = get_client(request.app)
    audit = get_audit(request.app)
    rid = get_request_id(request)

    await client.disconnect_server(name, timeout_ms=1500)

    ok = registry.unregister_server(name)
    if not ok:
        raise HTTPException(status_code=404, detail=f"server '{name}' 不存在")

    audit.log("registry_delete", {"server": name, "success": True}, request_id=rid)
    return {"ok": True, "server": name}


# ---------- config ----------

@router.get("/config/mcp")
async def get_mcp_config(request: Request) -> Dict[str, Any]:
    registry = get_registry(request.app)
    data = {
        s["name"]: {"description": s["description"], "filename": s["filename"], "abs_path": s["abs_path"], "auto_start": s["auto_start"]}
        for s in registry.list_all_servers()
        if s["name"] not in HIDDEN_SERVERS
    }
    return generate_mcp_config(data)


@router.post("/config/mcp/generate")
async def generate_mcp_config_file(request: Request) -> Dict[str, Any]:
    registry = get_registry(request.app)
    out_path = os.getenv("MCP_CONFIG_OUT", "mcp_servers.config.json")
    data = {
        s["name"]: {"description": s["description"], "filename": s["filename"], "abs_path": s["abs_path"], "auto_start": s["auto_start"]}
        for s in registry.list_all_servers()
        if s["name"] not in HIDDEN_SERVERS
    }
    p = write_mcp_config_file(data, out_path)
    return {"ok": True, "path": os.path.abspath(p)}


@router.get("/config/mcp/download")
async def download_mcp_config(request: Request):
    registry = get_registry(request.app)
    tmp = os.getenv("MCP_CONFIG_OUT", "mcp_servers.config.json")
    data = {
        s["name"]: {"description": s["description"], "filename": s["filename"], "abs_path": s["abs_path"], "auto_start": s["auto_start"]}
        for s in registry.list_all_servers()
        if s["name"] not in HIDDEN_SERVERS
    }
    p = write_mcp_config_file(data, tmp)
    return FileResponse(path=p, filename=os.path.basename(p), media_type="application/json")


# ---------- logs ----------

@router.get("/logs")
async def get_logs(
    request: Request,
    limit: int = 100,
    event: Optional[str] = None,
    server: Optional[str] = None,
    tool: Optional[str] = None,
    success: Optional[bool] = None,
) -> Dict[str, Any]:
    audit = get_audit(request.app)
    rows = audit.read_recent(limit=limit, event=event, server=server, tool=tool, success=success)
    return {"logs": rows}
