from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request

from .constants import HIDDEN_SERVERS
from .llm_deepseek import DeepSeekClient
from .models import AgentAskRequest
from .runtime import get_audit, get_client, get_registry, get_request_id, get_db

router = APIRouter(prefix="/agent", tags=["agent"])


def _normalize_session_id(v) -> Optional[int]:
    if v is None:
        return None
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v if v > 0 else None
    if isinstance(v, str):
        s = v.strip()
        if not s:
            return None
        if s.isdigit():
            n = int(s)
            return n if n > 0 else None
        return None
    try:
        n = int(v)
        return n if n > 0 else None
    except Exception:
        return None


def _maybe_log_call(
    db,
    sid: Optional[int],
    action: str,
    detail: str,
    *,
    server_name: str | None = None,
    correlation_id: str | None = None,
    level: str = "info",
) -> None:
    if sid is None or db is None:
        return

    action_cn = {
        "ask": "收到问题",
        "plan": "规划工具",
        "dry_run": "仅规划不执行",
        "tool_call": "调用工具",
        "tool_ok": "工具成功",
        "tool_fail": "工具失败",
        "clarify": "需要澄清",
        "answer": "输出回答",
    }.get(action, action)

    try:
        db.add_call_log(
            "MCP",
            action_cn+detail,
            session_id=sid,
            correlation_id=correlation_id,
            server_name=server_name,
            level=level,
        )
    except Exception:
        pass

def _tools_brief(tools: List[Dict[str, Any]], limit: int = 60) -> List[Dict[str, Any]]:
    out = []
    for t in tools[:limit]:
        out.append({
            "name": t.get("name"),
            "description": t.get("description", ""),
            "inputSchema": t.get("inputSchema"),
        })
    return out


def _schema_required(schema: Optional[dict]) -> List[str]:
    if not isinstance(schema, dict):
        return []
    req = schema.get("required")
    return req if isinstance(req, list) else []


def _validate_args(schema: Optional[dict], args: dict) -> Optional[str]:
    req = _schema_required(schema)
    if not req:
        return None
    missing = [k for k in req if k not in args]
    if missing:
        return f"缺少必填参数：{missing}"
    return None


async def _ensure_connected_and_tools(client, registry, server: str, timeout_ms: int) -> Optional[List[Dict[str, Any]]]:
    info = registry.get_server_info(server)
    if not info:
        return None
    if not client.is_connected(server):
        await client.connect_to_server(server, info.get("abs_path", ""), timeout_ms=timeout_ms)
    return await client.list_tools(server)


async def _plan_once(llm: DeepSeekClient, query: str, catalog: List[Dict[str, Any]], extra: Optional[str], timeout_ms: int) -> Dict[str, Any]:
    sys = (
        "你是一个MCP工具调用规划器。你只能输出JSON对象（不要输出多余文本）。\n"
        "你会得到一个server->tools目录。请在可用工具中选择最合适的一个server和tool，并构造args。\n"
        "如果信息不够，返回 clarification_needed=true 并给出 clarification.question。\n"
        "重要规则：\n"
        "- 当没有直接对应的工具时，不要反复要求澄清。优先考虑 hermes_ask / hermes_write_memory 作为兜底方案。\n"
        "- 对于提醒、闹钟、日历类任务（没有专用工具），使用 hermes_write_memory 记录提醒内容。\n"
        "- 对于个性化推荐（推荐饮料/食物/电影等）、偏好相关建议、\"有什么好喝的\"/\"推荐一些\"等请求：\n"
        "  使用 hermes_ask 处理。Hermes 会自动查询用户记忆中的偏好，再给出个性化推荐。\n"
        "  将用户的推荐请求连同偏好查询意图一起传给 hermes_ask，一步完成。\n"
        "- 对于查询个人偏好、记忆、习惯类任务，使用 hermes_read_memory。\n"
        "- 对于需要外部信息或复杂推理的任务，使用 hermes_ask 委托给 Hermes 处理。\n"
        "输出格式固定为：\n"
        "{\n"
        "  \"clarification_needed\": false,\n"
        "  \"clarification\": null,\n"
        "  \"plan\": { \"server\": \"...\", \"tool\": \"...\", \"args\": { ... } }\n"
        "}\n"
    )
    if extra:
        sys += "\n重要：上一次规划存在问题，请你修正：\n" + extra + "\n"

    messages = [
        {"role": "system", "content": sys},
        {"role": "user", "content": "用户问题：\n" + query},
        {"role": "user", "content": "可用目录（JSON）：\n" + str(catalog)},
    ]
    return await llm.chat_json(messages, timeout_ms=timeout_ms)


@router.post("/ask")
async def ask(request: Request, body: AgentAskRequest) -> Dict[str, Any]:
    """
    - 如果 body.session_id 存在且可用（>0 / 可转int），则写 call_logs
    - 否则跳过所有 db 日志

    日志策略（简要）：
    - ask（用户问题）
    - plan（规划结果）
    - dry_run（仅规划不执行）
    - tool_call / tool_ok / tool_fail（工具调用）
    - clarify（需要补充信息）
    - answer（最终回复）
    """
    app = request.app
    rid = get_request_id(request)
    correlation_id = rid

    audit = get_audit(app)
    registry = get_registry(app)
    client = get_client(app)
    db = get_db(app)

    sid = _normalize_session_id(getattr(body, "session_id", None))

    # ① 简要日志：记录一次用户输入（如果 sid 可用）
    _maybe_log_call(db, sid, "ask", (body.query or "").strip(), server_name="mcp-host", correlation_id=correlation_id)

    query = (body.query or "").strip()
    if not query:
        _maybe_log_call(db, sid, "处理失败", "query 为空", server_name="mcp-host", correlation_id=correlation_id, level="error")
        raise HTTPException(status_code=400, detail="query 不能为空")

    allow = set(body.allow_servers) if body.allow_servers else None
    servers = [
        s["name"]
        for s in registry.list_all_servers()
        if (allow is None or s["name"] in allow) and (s["name"] not in HIDDEN_SERVERS)
    ]
    if not servers:
        _maybe_log_call(db, sid, "处理失败", "没有可用的 server", server_name="mcp-host", correlation_id=correlation_id, level="error")
        raise HTTPException(status_code=400, detail="没有可用的 server（检查 allow_servers / registry）")

    # ② 构建目录（不写详细 db log）
    catalog: List[Dict[str, Any]] = []
    tools_by_server: Dict[str, List[Dict[str, Any]]] = {}

    for name in servers:
        try:
            tools = await _ensure_connected_and_tools(client, registry, name, timeout_ms=min(5000, body.timeout_ms))
            if tools is None:
                continue
            brief = _tools_brief(tools)
            info = registry.get_server_info(name) or {}
            catalog.append({"server": name, "description": info.get("description", ""), "tools": brief})
            tools_by_server[name] = brief
        except Exception as e:
            audit.log("agent_catalog_skip", {"server": name, "error": str(e)}, request_id=rid)
            # 目录加载失败不影响主流程；按“简要日志”策略这里不写入 call_logs

    if not catalog:
        _maybe_log_call(db, sid, "处理失败", "所有 server 都无法加载 tools", server_name="mcp-host", correlation_id=correlation_id, level="error")
        raise HTTPException(status_code=500, detail="所有 server 都无法加载 tools（请先检查 server 是否能启动）")

    try:
        llm = DeepSeekClient()
    except Exception as e:
        _maybe_log_call(db, sid, "处理失败", str(e), server_name="deepseek", correlation_id=correlation_id, level="error")
        raise HTTPException(status_code=500, detail=str(e))

    extra = None
    plan_obj: Optional[Dict[str, Any]] = None

    # ③ 规划（校验 + 自动重试一次）
    for _ in range(2):
        plan_obj = await _plan_once(llm, query, catalog, extra, timeout_ms=body.timeout_ms)

        if bool(plan_obj.get("clarification_needed", False)):
            clarification = plan_obj.get("clarification") or {"question": "需要更多信息"}
            audit.log("agent_clarify", {"clarification": clarification}, request_id=rid)

            _maybe_log_call(
                db, sid,
                "clarify",
                clarification.get("question", "需要更多信息"),
                server_name="mcp-host",
                correlation_id=correlation_id,
                level="warning",
            )

            return {
                "executed": False,
                "plan": None,
                "answer": None,
                "clarification_needed": True,
                "clarification": clarification,
            }

        plan = plan_obj.get("plan") or {}
        server = plan.get("server")
        tool = plan.get("tool")
        args = plan.get("args") or {}

        if not server or server not in tools_by_server:
            extra = f"server 选择无效。请从这些 server 中选择：{list(tools_by_server.keys())}"
            continue

        tool_map = {t["name"]: t for t in tools_by_server[server] if t.get("name")}
        spec = tool_map.get(tool)
        if not tool or not spec:
            extra = f"tool 选择无效。server={server} 可用 tools={list(tool_map.keys())}"
            continue

        schema = spec.get("inputSchema")
        err = _validate_args(schema, args)
        if err:
            extra = f"args 不符合 schema（{err}）。tool={tool} required={_schema_required(schema)}"
            continue

        break
    else:
        _maybe_log_call(db, sid, "处理失败", "LLM 连续两次返回无效计划", server_name="deepseek", correlation_id=correlation_id, level="error")
        raise HTTPException(status_code=500, detail="LLM 连续两次返回无效计划")

    plan = plan_obj.get("plan") or {}
    server = plan.get("server")
    tool = plan.get("tool")
    args = plan.get("args") or {}

    if allow is not None and server not in allow:
        _maybe_log_call(db, sid, "处理失败", "计划 server 不在 allow_servers", server_name=str(server), correlation_id=correlation_id, level="error")
        raise HTTPException(status_code=400, detail=f"计划选择的 server '{server}' 不在 allow_servers 中")

    _maybe_log_call(
        db, sid,
        "plan",
        json.dumps({"server": server, "tool": tool, "args": args}, ensure_ascii=False),
        server_name=f"{server}-{tool}",
        correlation_id=correlation_id,
    )

    if body.dry_run:
        _maybe_log_call(db, sid, "dry_run", "仅规划不执行", server_name="mcp-host", correlation_id=correlation_id)
        return {
            "executed": False,
            "plan": {"server": server, "tool": tool, "args": args},
            "answer": None,
            "clarification_needed": False,
            "clarification": None,
        }

    # ④ 调用工具
    _maybe_log_call(
        db, sid,
        "tool_call",
        json.dumps({"server": server, "tool": tool, "args": args}, ensure_ascii=False),
        server_name=f"{server}-{tool}",
        correlation_id=correlation_id,
    )

    try:
        info = registry.get_server_info(server)
        if not info:
            raise RuntimeError(f"registry 中找不到 server '{server}'")
        if not client.is_connected(server):
            await client.connect_to_server(server, info.get("abs_path", ""), timeout_ms=min(5000, body.timeout_ms))

        coro = client.call_tool(server, tool, args)
        tool_result = await asyncio.wait_for(coro, timeout=body.timeout_ms / 1000.0)
        _maybe_log_call(db, sid, "tool_ok", "ok", server_name=f"{server}-{tool}", correlation_id=correlation_id)
    except asyncio.TimeoutError:
        msg = "工具调用超时"
        _maybe_log_call(db, sid, "tool_fail", msg, server_name=f"{server}-{tool}", correlation_id=correlation_id, level="error")
        raise HTTPException(status_code=504, detail=msg)
    except Exception as e:
        msg = str(e)
        _maybe_log_call(db, sid, "tool_fail", msg, server_name=f"{server}-{tool}", correlation_id=correlation_id, level="error")
        raise HTTPException(status_code=500, detail=msg)

    # ⑤ 生成最终回答
    answer_messages = [
        {"role": "system", "content": "你是一个助手。根据工具返回结果，给出清晰、简洁的中文回答。"},
        {"role": "user", "content": f"用户问题：{query}"},
        {"role": "user", "content": f"工具调用：server={server}, tool={tool}, args={args}"},
        {"role": "user", "content": f"工具结果（JSON）：{tool_result}"},
    ]
    answer_text = await llm.chat_text_stream(answer_messages, timeout_ms=body.timeout_ms)

    audit.log("agent_done", {"server": server, "tool": tool, "success": True}, request_id=rid)
    _maybe_log_call(db, sid, "answer", answer_text, server_name="mcp-host", correlation_id=correlation_id)

    return {
        "executed": True,
        "plan": {"server": server, "tool": tool, "args": args},
        "answer": answer_text,
        "clarification_needed": False,
        "clarification": None,
    }

@router.get("/logs/{session_id}")
async def read_session_logs(request: Request, session_id: str, limit: int = 200) -> Dict[str, Any]:
    db = get_db(request.app)
    sid = _normalize_session_id(session_id)
    if sid is None:
        raise HTTPException(status_code=400, detail="session_id 必须是正整数")
    return {"session_id": sid, "logs": db.list_call_logs(session_id=sid, limit=limit)}
