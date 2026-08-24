#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""webchat — 记忆增强 + 系统工具 网页 AI 聊天（麒麟 SDK）。

后端:
  - 对话:  src.sdk.ai_text（麒麟千问）
  - 记忆:  src.memory.mem0_store（麒麟嵌入 + 本地 Milvus + 麒麟千问 LLM，零 key）
  - 工具:  src.toolkit（24 个 SDK 工具，AI 编排调用）

依赖 .venv（mem0/numpy/pymilvus），请用 .venv/bin/python 运行:
    .venv/bin/python webchat.py [端口]    (默认 8080)
"""
import asyncio
import json
import os
# P1-1: 强制禁用 mem0 PostHog 遥测（必须早于任何 mem0 导入）
os.environ["MEM0_TELEMETRY"] = "False"
import re
import sys
import threading
import time
from collections import OrderedDict
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from src.sdk import ai_text  # noqa: E402
# mem0 惰性初始化：--no-memory 启动时完全不加载（P1-2）
_NO_MEMORY = "--no-memory" in sys.argv
_mem0 = None
_forget_flow = None

def _get_mem0():
    """惰性获取 mem0 单例；--no-memory 模式返回 None。"""
    global _mem0
    if _NO_MEMORY:
        return None
    if _mem0 is None:
        from src.memory.mem0_store import mem0_store
        _mem0 = mem0_store
    return _mem0

def _get_forget_flow():
    """惰性获取 ForgetFlow 单例。"""
    global _forget_flow
    if _forget_flow is None:
        _forget_flow = ForgetFlow()
    return _forget_flow
from src.toolkit.init_tools import init_all_tools  # noqa: E402
from src.toolkit.base import get_registry, ToolResult, ToolStatus  # noqa: E402
from src.toolkit.executor import ClosedLoopExecutor  # noqa: E402
from src.memory import log_reader  # noqa: E402 日志驱动记忆
from src import llm_client  # noqa: E402 统一 LLM 客户端（SDK/API 可切换）
from src.memory.forget_flow import ForgetFlow  # noqa: E402 精准遗忘交互流程

# ---------- 初始化工具 ----------
init_all_tools()
REGISTRY = get_registry()
EXECUTOR = ClosedLoopExecutor(registry=REGISTRY, max_retries=1)

# 工具参数 schema（dsh 风格：告诉模型每个工具的参数，避免瞎猜参数名）
# 格式：{tool_name: {param: {"type": "str|int|bool", "required": bool, "desc": "..."}}}
TOOL_PARAMS = {
    "sysinfo": {"info_type": {"type": "str", "required": True, "desc": "cpu/memory/disk/display/load/network/os"}},
    "process_list": {"keyword": {"type": "str", "required": False, "desc": "按名称过滤"}},
    "process_kill": {"pid": {"type": "int", "required": True, "desc": "进程 PID"}, "signal": {"type": "int", "required": False, "desc": "信号，默认 15"}},
    "netstatus": {"type": {"type": "str", "required": False, "desc": "ip=IP地址, net=网络详情"}},
    "battery": {},
    "diskinfo": {},
    "file": {"action": {"type": "str", "required": False, "desc": "mkdir/list/read/write/verify/delete"},
             "path": {"type": "str", "required": False, "desc": "文件或目录路径"},
             "paths": {"type": "list", "required": False, "desc": "批量路径"},
             "folder": {"type": "str", "required": False, "desc": "目标文件夹"},
             "files": {"type": "list", "required": False, "desc": "文件名列表"},
             "count": {"type": "int", "required": False, "desc": "批量数量"},
             "ext": {"type": "str", "required": False, "desc": "扩展名，默认 md"}},
    "shell": {"cmd": {"type": "str", "required": True, "desc": "要执行的命令（白名单受限）"}},
    "web_search": {"query": {"type": "str", "required": True, "desc": "搜索关键词"}, "num": {"type": "int", "required": False, "desc": "返回条数(1-10)"}},
    "python_exec": {"code": {"type": "str", "required": True, "desc": "Python 代码（沙箱执行，需 print 输出）"}},
    "kb": {"action": {"type": "str", "required": False, "desc": "add=入库, query=问答"},
           "content": {"type": "str", "required": False, "desc": "入库文本"},
           "path": {"type": "str", "required": False, "desc": "文件路径"},
           "question": {"type": "str", "required": False, "desc": "知识问答问题"}},
    "ocr": {"image_path": {"type": "str", "required": True, "desc": "图片绝对路径"}},
    "volume": {"action": {"type": "str", "required": False, "desc": "get/mute/unmute/up/down"}, "value": {"type": "int", "required": False, "desc": "音量百分比"}},
    "wifi": {"action": {"type": "str", "required": True, "desc": "scan/connect/disconnect"}, "ssid": {"type": "str", "required": False, "desc": "WiFi 名"}, "password": {"type": "str", "required": False, "desc": "密码"}},
    "timezone": {"timezone": {"type": "str", "required": True, "desc": "时区，如 Asia/Shanghai"}},
    "datetime": {"action": {"type": "str", "required": False, "desc": "get/set"}},
    "sleep": {"delay_seconds": {"type": "int", "required": False, "desc": "延时秒数，默认 60"}},
    "power": {"action": {"type": "str", "required": True, "desc": "reboot/shutdown"}, "delay_seconds": {"type": "int", "required": False, "desc": "延时秒数"}},
    "screenshot": {"mode": {"type": "str", "required": False, "desc": "full 全屏"}, "output_path": {"type": "str", "required": False, "desc": "保存路径"}},
    "notify": {"title": {"type": "str", "required": False, "desc": "通知标题"}, "body": {"type": "str", "required": False, "desc": "通知内容"}},
    "bluetooth": {"action": {"type": "str", "required": False, "desc": "scan/on/off"}},
    "app": {"name": {"type": "str", "required": True, "desc": "应用名"}},
}


def _tool_line(name):
    tool = REGISTRY.get(name)
    line = f"- {name}: {tool.description}"
    params = TOOL_PARAMS.get(name)
    if params:
        parts = []
        for pname, pinfo in params.items():
            req = "必填" if pinfo.get("required") else "可选"
            parts.append(f"{pname}({pinfo.get('type', 'str')},{req})={pinfo.get('desc', '')}")
        if parts:
            line += "  [参数: " + "; ".join(parts) + "]"
    return line


TOOL_CATALOG = "\n".join(_tool_line(name) for name in REGISTRY.list_all())

# ---------- 配置即长期记忆（类似 Codex AGENTS.md）----------
_skill_memory = None


def _get_skill_memory():
    """惰性获取配置记忆（SKILL 持久化到 ~/.nex-agent/skills.json）。"""
    global _skill_memory
    if _skill_memory is None:
        from src.memory_engine.skill_memory import SkillMemory
        _skill_memory = SkillMemory()
        try:
            # ③ 清理幽灵冲突（skills 空但 conflicts 有历史残留）
            if not _skill_memory.list_skills() and _skill_memory.conflicts():
                import os as _os
                _p = _os.path.expanduser("~/.nex-agent/skills.json")
                if _os.path.exists(_p):
                    import json as _json
                    with open(_p, "r", encoding="utf-8") as _f:
                        _d = _json.load(_f)
                    _d["conflicts"] = []
                    with open(_p, "w", encoding="utf-8") as _f:
                        _json.dump(_d, _f, ensure_ascii=False, indent=2)
                    print("[skill] 已清理幽灵冲突记录", flush=True)
        except Exception:
            pass
    return _skill_memory


# ---------- 记忆流转（短期→中期→长期 自动）----------
_flow = None


def _get_flow():
    """惰性获取记忆流转引擎（JSON 持久化到 ~/.nex-agent/memory_flow.json）。"""
    global _flow
    if _flow is None:
        from src.memory_engine.memory_flow import MemoryFlow
        _flow = MemoryFlow()
    return _flow


def _flow_after_chat(session_id: str, prompt: str, reply: str) -> dict:
    """每轮对话后：写入短期 → 溢出自动提升中期 → 容量/老化归档长期。"""
    flow = _get_flow()
    overflow = []
    try:
        # 写入短期（用户消息；AI 回复若为工具结果/快照则不流转，避免快照泛滥）
        overflow += flow.add_short(prompt, session_id)
        _SNAP = ("✅ 工具", "❌", "状态：", "**输出**")
        if not any(m in reply for m in _SNAP):
            overflow += flow.add_short(reply, session_id)
        # 溢出项（重要性达标）自动提升到中期
        if overflow:
            flow.promote(session_id, overflow)
        # 中期容量/老化检查 → 归档长期
        flow.consolidate(session_id, capacity=50, max_age_days=30)
        return {"short": len(flow._short), "midterm": flow.midterm_count(session_id),
                "longterm": flow.longterm_count(), "promoted": len(overflow)}
    except Exception as e:
        return {"error": str(e)}


# ---------- DB 用户画像（借鉴 AgentProject：持久化用户信息/行为注入）----------
def _db_user_profile() -> str:
    """从 MySQL 读取用户基本信息与历史行为模式（仅供参考，不作为指令）。"""
    try:
        from src.utils.db_manager import db_manager
        info = db_manager.get_user_info_simple()
        beh = db_manager.get_user_behavior_simple()
        parts = []
        if info:
            parts.append("用户基本信息：" + "；".join(f"{k}：{v}" for k, v in info))
        if beh:
            parts.append("历史行为模式：" + "；".join(f"{k}：{v}" for k, v in beh))
        return "\n".join(parts) if parts else ""
    except Exception:
        return ""


# ---------- 安全配置（P0 修复） ----------
WEBCHAT_TOKEN = os.getenv("WEBCHAT_TOKEN", "")          # 设置后 /api/* 需 X-Api-Token 头
WEBCHAT_HOST = os.getenv("WEBCHAT_HOST", "127.0.0.1")   # 默认仅本机，防远程操控
# 网页端禁用的高风险工具：不可逆 / 会中断服务，只能 SSH 人工执行
WEB_DISALLOWED_TOOLS = {"power", "sleep", "datetime"}

_mem_lock = threading.Lock()
_tool_lock = threading.Lock()

# ---------- 会话上下文（内存态，服务重启即清空；长期记忆走 mem0） ----------
MAX_SESSIONS = 64        # 最多保留的会话数（LRU 淘汰）
MAX_HISTORY_TURNS = 8    # 每会话最多拼接最近 8 轮（16 条消息）
MAX_TURN_CHARS = 500     # 单条历史消息截断长度，控制 prompt 体积
COMPACT_THRESHOLD = 12   # 历史超过 12 轮时触发早期压缩（dsh compaction）
COMPACT_KEEP = 6         # 压缩时移出的早期轮次数量（保留最近轮做总结上下文）
SESSIONS: "OrderedDict[str, list]" = OrderedDict()
SESSIONS_META: dict = {}  # sid -> {"summary": "早期对话摘要", "title": "LLM标题"}
_sessions_lock = threading.Lock()
_SESSIONS_PATH = os.path.join(os.path.expanduser("~"), ".nex-agent", "sessions.json")


def _load_sessions():
    """从 JSON 恢复会话历史 + meta（兼容旧格式 list）。"""
    global SESSIONS, SESSIONS_META
    try:
        with open(_SESSIONS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            if "sessions" in data:  # 新格式
                SESSIONS = OrderedDict((k, v[-MAX_HISTORY_TURNS * 2:])
                                       for k, v in data["sessions"].items())
                SESSIONS_META = data.get("meta", {}) or {}
            else:                   # 旧格式：直接是 sid -> hist
                SESSIONS = OrderedDict(
                    (k, v[-MAX_HISTORY_TURNS * 2:]) for k, v in data.items()
                )
            while len(SESSIONS) > MAX_SESSIONS:
                SESSIONS.popitem(last=False)
            print(f"[session] 已从 {_SESSIONS_PATH} 恢复 {len(SESSIONS)} 个会话")
    except FileNotFoundError:
        pass
    except Exception as e:
        print(f"[session] 会话恢复失败（忽略）: {e}")


def _persist_sessions():
    """将会话历史 + meta 落盘 JSON（原子写）。"""
    try:
        os.makedirs(os.path.dirname(_SESSIONS_PATH), exist_ok=True)
        tmp = _SESSIONS_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"sessions": SESSIONS, "meta": SESSIONS_META},
                      f, ensure_ascii=False)
        os.replace(tmp, _SESSIONS_PATH)
    except Exception as e:
        print(f"[session] 会话持久化失败: {e}")


def _session_history(session_id: str):
    with _sessions_lock:
        return list(SESSIONS.get(session_id, []))


def _delete_session(session_id: str) -> bool:
    """删除整个会话（历史 + meta + 持久化）。"""
    with _sessions_lock:
        existed = SESSIONS.pop(session_id, None) is not None
        SESSIONS_META.pop(session_id, None)
        if existed:
            _persist_sessions()
    print(f"[session] 已删除会话: {session_id[:12]}", flush=True)
    return existed


def _clear_session(session_id: str) -> bool:
    """清空会话对话内容（保留会话与标题，清历史 + 摘要）。"""
    with _sessions_lock:
        if session_id not in SESSIONS:
            return False
        SESSIONS[session_id] = []
        meta = SESSIONS_META.get(session_id)
        if meta:
            meta["summary"] = ""
        _persist_sessions()
    print(f"[session] 已清空会话: {session_id[:12]}", flush=True)
    return True


def _compact_async(session_id: str, old_msgs: list):
    """异步：用 LLM 把早期对话总结成摘要，追加到会话 meta.summary。"""
    try:
        from src import llm_client
        text = "\n".join(f"{'用户' if m.get('role') == 'user' else '助手'}：{m.get('content', '')}"
                          for m in old_msgs)
        if not text.strip():
            return
        prompt = ("把以下对话压缩成一段摘要（保留：关键事实、用户偏好、已执行的操作与结果、"
                  "明确承诺的事项）。150 字以内，只输出摘要正文：\n\n" + text)
        summary = (llm_client.generate(prompt) or "").strip()
        if not summary:
            return
        with _sessions_lock:
            meta = SESSIONS_META.setdefault(session_id, {"summary": "", "title": ""})
            old_s = (meta.get("summary") or "").strip()
            meta["summary"] = (old_s + "\n" + summary) if old_s else summary
            _persist_sessions()
        print(f"[session] 会话 {session_id[:8]} 历史压缩完成: +{len(summary)} 字", flush=True)
    except Exception as e:
        print(f"[session] 压缩失败: {e}", flush=True)


def _gen_title_async(session_id: str, first_msg: str):
    """异步：LLM 生成会话标题（10 字内）。"""
    try:
        from src import llm_client
        prompt = ("为下面这段对话的第一条用户消息生成一个简短标题（10 个汉字以内，"
                  "不要引号，不要标点结尾）：\n" + (first_msg or "")[:60])
        title = (llm_client.generate(prompt) or "").strip()[:20]
        if not title:
            return
        with _sessions_lock:
            meta = SESSIONS_META.setdefault(session_id, {"summary": "", "title": ""})
            if not meta.get("title"):
                meta["title"] = title
                _persist_sessions()
        print(f"[session] 会话标题生成: {title}", flush=True)
    except Exception as e:
        print(f"[session] 标题生成失败: {e}", flush=True)


def _session_append(session_id: str, role: str, content: str):
    with _sessions_lock:
        hist = SESSIONS.setdefault(session_id, [])
        hist.append({"role": role, "content": (content or "")[:MAX_TURN_CHARS]})
        meta = SESSIONS_META.setdefault(session_id, {"summary": "", "title": ""})
        # ④ 会话标题：第一条用户消息后异步生成
        if role == "user" and len(hist) == 1 and not meta.get("title"):
            threading.Thread(target=_gen_title_async,
                             args=(session_id, content or ""), daemon=True).start()
        # ① 历史压缩（dsh compaction）：按累计消息数触发
        #   hist 被拼接窗口截断在 MAX_HISTORY_TURNS*2 条，无法用 len(hist) 判断，
        #   因此用 meta.total_msgs 累计；每满 COMPACT_THRESHOLD*2 条压缩一次，
        #   把当前保留历史中最早的 COMPACT_KEEP*2 条总结成摘要。
        meta["total_msgs"] = int(meta.get("total_msgs") or 0) + 1
        if meta["total_msgs"] >= COMPACT_THRESHOLD * 2 and len(hist) > COMPACT_KEEP * 2:
            old_msgs = hist[: COMPACT_KEEP * 2]
            del hist[: COMPACT_KEEP * 2]
            meta["total_msgs"] = 0
            threading.Thread(target=_compact_async,
                             args=(session_id, old_msgs), daemon=True).start()
        # 拼接窗口：最多保留 MAX_HISTORY_TURNS 轮
        if len(hist) > MAX_HISTORY_TURNS * 2:
            del hist[: len(hist) - MAX_HISTORY_TURNS * 2]
        SESSIONS.move_to_end(session_id)
        while len(SESSIONS) > MAX_SESSIONS:
            dropped = SESSIONS.popitem(last=False)
            SESSIONS_META.pop(dropped[0], None)
        _persist_sessions()

_load_sessions()

HTML = r"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>aichat · 麒麟 AI</title>
<script src="https://cdn.jsdelivr.net/npm/marked@12/marked.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/dompurify@3/dist/purify.min.js"></script>
<style>
  :root {
    --bg: #ffffff;
    --surface: rgba(0,0,0,.035);
    --surface-2: rgba(0,0,0,.07);
    --border: rgba(0,0,0,.12);
    --text: #1a1a1a;
    --muted: #6b7280;
    --accent: #000000;
    --accent-2: #333333;
    --ok: #000000;
    --surface-solid: #ffffff;
    --header-bg: rgba(255,255,255,.85);
    --input-bg: #ffffff;
    --bubble-user: #f0f0f0;
    --bubble-ai: rgba(0,0,0,.03);
    --modal-bg: #ffffff;
    --modal-text: #1a1a1a;
    --modal-border: #ddd;
    --modal-input: #ffffff;
    --modal-label: #666;
  }
  [data-theme="dark"] {
    --bg: #1c1c1e;
    --surface: rgba(255,255,255,.06);
    --surface-2: rgba(255,255,255,.1);
    --border: rgba(255,255,255,.14);
    --text: #f2f2f2;
    --muted: #a1a1a6;
    --accent: #ffffff;
    --accent-2: #d1d1d6;
    --ok: #4cd964;
    --surface-solid: #2c2c2e;
    --header-bg: rgba(28,28,30,.85);
    --input-bg: #2c2c2e;
    --bubble-user: #2c2c2e;
    --bubble-ai: rgba(255,255,255,.06);
    --modal-bg: #2c2c2e;
    --modal-text: #f2f2f2;
    --modal-border: rgba(255,255,255,.16);
    --modal-input: #3a3a3c;
    --modal-label: #a1a1a6;
  }
  * { box-sizing: border-box; }
  html, body { height: 100%; }
  body {
    margin: 0;
    font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", "Segoe UI",
                 "Microsoft YaHei", sans-serif;
    color: var(--text);
    background:
      radial-gradient(1200px 600px at 15% -10%, rgba(0,0,0,.045), transparent 60%),
      radial-gradient(1000px 500px at 100% 0%, rgba(0,0,0,.03), transparent 55%),
      var(--bg);
    display: flex;
    flex-direction: column;
  }
  header {
    position: sticky; top: 0; z-index: 10;
    display: flex; align-items: center; gap: 10px;
    padding: 13px 22px;
    background: var(--header-bg);
    backdrop-filter: blur(14px); -webkit-backdrop-filter: blur(14px);
    border-bottom: 1px solid var(--border);
  }
  .dot { width: 9px; height: 9px; border-radius: 50%; background: var(--ok);
         box-shadow: 0 0 10px var(--ok); flex: none; }
  .brand { font-size: 16px; font-weight: 650; letter-spacing: .2px; }
  .brand em { font-style: normal; color: var(--accent-2); }
  .sub { font-size: 12px; color: var(--muted); }
  .spacer { flex: 1; }
  .icon-btn {
    border: 1px solid var(--border); background: var(--surface);
    color: var(--muted); border-radius: 9px; padding: 6px 12px;
    font-size: 12.5px; cursor: pointer; transition: .18s;
  }
  .icon-btn:hover { color: var(--text); border-color: var(--surface-2); background: var(--surface-2); }
  main { flex: 1; overflow-y: auto; width: 100%; padding: 26px 0 20px; }
  .wrap { max-width: 800px; margin: 0 auto; padding: 0 20px;
          display: flex; flex-direction: column; gap: 20px; }
  .empty { color: var(--muted); text-align: center; margin-top: 12vh; }
  .empty h1 { font-size: 24px; font-weight: 650; margin: 0 0 8px; color: var(--text); }
  .empty p { margin: 4px 0; font-size: 14px; line-height: 1.7; }
  .row { display: flex; flex-direction: column; animation: rise .28s ease; }
  @keyframes rise { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: none; } }
  .who { font-size: 11.5px; font-weight: 600; letter-spacing: .4px;
         margin-bottom: 5px; color: var(--muted); }
  .row.user { align-items: flex-end; }
  .row.user .who { color: var(--accent); }
  .row.assistant .who { color: var(--ok); }
  .bubble {
    max-width: 88%; padding: 11px 15px; border-radius: 15px;
    font-size: 14.5px; line-height: 1.75; word-break: break-word;
  }
  .row.user .bubble {
    background: linear-gradient(135deg, #2a2a2a, #000000);
    color: #fff; border-bottom-right-radius: 5px;
    box-shadow: 0 6px 20px -8px rgba(0,0,0,.25);
    white-space: pre-wrap;
  }
  .row.assistant .bubble {
    background: var(--surface); border: 1px solid var(--border);
    border-bottom-left-radius: 5px;
  }
  .md > *:first-child { margin-top: 0; }
  .md > *:last-child { margin-bottom: 0; }
  .md p { margin: .55em 0; }
  .md h1,.md h2,.md h3,.md h4 { margin: .9em 0 .4em; line-height: 1.35; }
  .md h1 { font-size: 1.3em; } .md h2 { font-size: 1.18em; } .md h3 { font-size: 1.06em; }
  .md ul,.md ol { margin: .5em 0; padding-left: 1.4em; }
  .md li { margin: .25em 0; }
  .md code { font-family: "SF Mono", ui-monospace, Menlo, Consolas, monospace;
             font-size: .88em; background: rgba(0,0,0,.06);
             padding: .12em .42em; border-radius: 5px; }
  .md pre { background: #f5f5f5; border: 1px solid var(--border);
            padding: 12px 14px; border-radius: 10px; overflow-x: auto; }
  .md pre code { background: none; padding: 0; }
  .md blockquote { margin: .6em 0; padding: .2em 1em; color: var(--muted);
                   border-left: 3px solid var(--accent); }
  .md a { color: #111111; text-decoration: underline; }
  .md table { border-collapse: collapse; margin: .7em 0; font-size: .92em; }
  .md th,.md td { border: 1px solid var(--border); padding: 6px 11px; }
  .md th { background: var(--surface-2); }
  .cursor { display: inline-block; width: 8px; height: 1.05em; margin-left: 2px;
            background: var(--accent-2); vertical-align: -2px;
            animation: blink .9s steps(2, start) infinite; }
  @keyframes blink { to { visibility: hidden; } }
  .layout { display: flex; height: 100vh; }
  .sidebar { width: 230px; min-width: 230px; background: var(--surface-solid);
             border-right: 1px solid var(--border); display: flex; flex-direction: column; }
  .banner { display: flex; align-items: center; gap: 10px; padding: 14px 14px;
             border-bottom: 1px solid var(--border); position: relative; }
  .banner-icon { font-size: 26px; flex: none; }
  .banner-text { flex: 1; min-width: 0; }
  .banner-title { font-size: 15px; font-weight: 700; letter-spacing: .3px;
                  white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .banner-sub { font-size: 11px; opacity: .75; margin-top: 2px;
                white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .banner-edit { background: none; border: none; color: inherit; opacity: .45;
                 cursor: pointer; font-size: 13px; padding: 2px 4px; border-radius: 4px; }
  .banner-edit:hover { opacity: 1; background: rgba(255,255,255,.15); }
  .banner-modal { position: fixed; inset: 0; background: rgba(0,0,0,.45); z-index: 99;
                  display: none; align-items: center; justify-content: center; }
  .banner-modal-box { background: var(--modal-bg); color: var(--modal-text); border-radius: 12px; padding: 18px 20px;
                      width: 320px; box-shadow: 0 18px 50px rgba(0,0,0,.3); }
  .banner-modal-box h3 { margin: 0 0 12px; font-size: 15px; color: var(--modal-text); }
  .banner-modal-box label { display: block; font-size: 12px; color: var(--modal-label); margin: 8px 0 3px; }
  .banner-modal-box input[type=text] { width: 100%; padding: 6px 8px; border: 1px solid var(--modal-border);
                      background: var(--modal-input); color: var(--modal-text); border-radius: 6px; font-size: 13px; box-sizing: border-box; }
  .banner-modal-box .row { display: flex; gap: 8px; }
  .banner-modal-box .row > div { flex: 1; }
  .banner-modal-box .btns { display: flex; gap: 8px; margin-top: 14px; }
  .banner-modal-box .btns button { flex: 1; padding: 7px; border-radius: 6px; border: 1px solid var(--modal-border);
                      background: var(--modal-input); color: var(--modal-text); cursor: pointer; font-size: 13px; }
  .banner-modal-box .btns .save { background: var(--accent); color: var(--bg); border-color: var(--accent); }
  .banner-modal-box .chk { display: flex; align-items: center; gap: 6px; margin-top: 10px; font-size: 13px; color: var(--modal-label); }
  .tabbar { display: flex; gap: 4px; border-bottom: 1px solid #eee; margin-bottom: 12px; }
  .tabbar .tab { flex: 1; padding: 7px 4px; border: none; background: none; cursor: pointer;
                 font-size: 13px; color: var(--modal-label); border-bottom: 2px solid transparent; }
  .tabbar .tab.active { color: var(--text); font-weight: 600; border-bottom-color: var(--accent); }
  .banner-modal-box .field-hint { font-size: 11px; color: #999; margin-top: 2px; }
  .floating-settings { position: fixed; right: 18px; bottom: 18px; width: 48px; height: 48px;
                       border-radius: 50%; background: linear-gradient(135deg,#333,#000);
                       color: #fff; border: none; font-size: 21px; cursor: pointer;
                       box-shadow: 0 6px 20px rgba(0,0,0,.3); z-index: 50;
                       transition: transform .15s; }
  .floating-settings:hover { transform: scale(1.08); }
  .model-select { padding: 5px 10px; border: 1px solid var(--border); background: var(--surface);
                  color: var(--text); border-radius: 8px; font-size: 12.5px; cursor: pointer; }
  .theme-btn { border: 1px solid var(--border); background: var(--surface); color: var(--muted);
               border-radius: 8px; padding: 5px 9px; font-size: 13px; cursor: pointer; }
  .theme-btn:hover { color: var(--text); }
  .msg-actions { display: flex; gap: 6px; margin-top: 6px; opacity: 0; transition: opacity .15s; }
  .bubble:hover .msg-actions { opacity: 1; }
  .msg-actions button { border: none; background: none; color: var(--muted); cursor: pointer;
                        font-size: 12px; padding: 2px 6px; border-radius: 5px; }
  .msg-actions button:hover { background: var(--surface-2); color: var(--text); }
  .msg-actions .voted { color: #4cd964; }
  .confirm-box { border: 1px solid var(--border); border-radius: 10px; padding: 12px 14px;
                 background: var(--surface); margin-top: 4px; }
  .confirm-title { font-weight: 650; font-size: 13.5px; margin-bottom: 8px; }
  .confirm-tool { font-size: 12.5px; color: var(--text); margin-bottom: 4px; }
  .confirm-params pre { background: var(--surface-2); padding: 8px; border-radius: 6px;
                        font-size: 11.5px; margin: 6px 0; overflow-x: auto; color: var(--text); }
  .confirm-btns { display: flex; gap: 8px; margin-top: 10px; }
  .confirm-btns button { flex: 1; padding: 7px; border-radius: 8px; border: 1px solid var(--border);
                         cursor: pointer; font-size: 13px; background: var(--surface-2); color: var(--text); }
  .confirm-btns .confirm-yes { background: #1a1a1a; color: #fff; border-color: #1a1a1a; }
  [data-theme="dark"] .confirm-btns .confirm-yes { background: #fff; color: #1c1c1e; }
  .sidebar .brand { padding: 14px 16px; border-bottom: 1px solid var(--border); }
  .sidebar .newchat { margin: 10px 12px; padding: 8px; border: 1px solid var(--accent);
             border-radius: 8px; background: rgba(0,0,0,.05); color: var(--text);
             cursor: pointer; font-size: 13px; text-align: center; }
  .sidebar .newchat:hover { background: rgba(0,0,0,.1); }
  .sess-list { flex: 1; overflow-y: auto; padding: 4px; }
  .sess-item { padding: 8px 10px; margin: 2px 4px; border-radius: 6px; font-size: 12.5px;
             color: var(--muted); cursor: pointer; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .sess-item:hover, .sess-item.active { background: var(--surface-2); color: var(--text); }
  .main { flex: 1; display: flex; flex-direction: column; min-width: 0; }
  .panel { width: 240px; min-width: 240px; background: var(--surface-solid);
             border-left: 1px solid var(--border); overflow-y: auto; padding: 10px; }
  .panel h3 { font-size: 12px; color: var(--muted); margin: 8px 0 6px; letter-spacing: .5px; }
  .mem-item { font-size: 12px; color: var(--text); padding: 6px 8px; background: var(--surface);
             border: 1px solid var(--border); border-radius: 6px; margin-bottom: 6px; line-height: 1.5; }
  .log-item { font-size: 11.5px; padding: 5px 8px; border-radius: 5px; margin-bottom: 5px;
             background: var(--surface); border: 1px solid var(--border); }
  .log-item .tool { color: var(--accent-2); }
  .log-item.ok { border-left: 3px solid var(--ok); }
  .log-item.err { border-left: 3px solid #000000; background: rgba(0,0,0,.08); }
  footer {
    position: sticky; bottom: 0;
    background: rgba(255,255,255,.85);
    backdrop-filter: blur(14px); -webkit-backdrop-filter: blur(14px);
    border-top: 1px solid var(--border); padding: 12px 0 16px;
  }
  .inputbar { max-width: 800px; margin: 0 auto; padding: 0 20px;
              display: flex; align-items: flex-end; gap: 10px; }
  textarea {
    flex: 1; resize: none; border: 1px solid var(--border);
    background: var(--surface); color: var(--text);
    border-radius: 14px; padding: 12px 15px; font-size: 14.5px;
    font-family: inherit; line-height: 1.6; max-height: 180px;
    transition: border-color .18s, box-shadow .18s;
  }
  textarea:focus { outline: none; border-color: var(--accent);
                   box-shadow: 0 0 0 3px rgba(0,0,0,.12); }
  button#send {
    border: none; border-radius: 13px; padding: 12px 22px; font-size: 14.5px;
    font-weight: 600; color: #fff; cursor: pointer; flex: none;
    background: linear-gradient(135deg, #333333, #000000);
    box-shadow: 0 8px 22px -10px rgba(0,0,0,.35); transition: .18s;
  }
  button#send:hover { transform: translateY(-1px); filter: brightness(1.08); }
  button#send:disabled { opacity: .45; cursor: not-allowed; transform: none; }
  .hint { max-width: 800px; margin: 8px auto 0; padding: 0 20px;
          font-size: 11.5px; color: var(--muted); }
</style>
</head>
<body>
<div class="layout">
  <aside class="sidebar">
    <div class="banner" id="banner">
      <div class="banner-icon" id="bannerIcon">🤖</div>
      <div class="banner-text">
        <div class="banner-title" id="bannerTitle">麒麟 AI</div>
        <div class="banner-sub" id="bannerSub">记忆增强 · 系统工具</div>
      </div>

    </div>
    <div class="banner-modal" id="bannerModal">
      <div class="banner-modal-box">
        <h3>Banner 配置</h3>
        <label>图标（Emoji）</label>
        <input type="text" id="bCfgIcon" maxlength="8" placeholder="🤖">
        <div class="row">
          <div>
            <label>标题</label>
            <input type="text" id="bCfgTitle" maxlength="20" placeholder="麒麟 AI">
          </div>
          <div>
            <label>副标题</label>
            <input type="text" id="bCfgSub" maxlength="30" placeholder="记忆增强 · 系统工具">
          </div>
        </div>
        <div class="row">
          <div>
            <label>背景（色值/渐变）</label>
            <input type="text" id="bCfgBg" maxlength="80" placeholder="linear-gradient(135deg,#1a1a1a,#333)">
          </div>
          <div>
            <label>文字颜色</label>
            <input type="text" id="bCfgText" maxlength="20" placeholder="#ffffff">
          </div>
        </div>
        <label class="chk"><input type="checkbox" id="bCfgEnabled"> 启用 Banner</label>
        <div class="btns">
          <button id="bCfgCancel">取消</button>
          <button class="save" id="bCfgSave">保存</button>
        </div>
      </div>
    </div>
    <div class="banner-modal" id="settingsModal">
      <div class="banner-modal-box" style="width:360px;">
        <h3>设置</h3>
        <div class="tabbar">
          <button class="tab active" data-tab="model">🤖 模型</button>
          <button class="tab" data-tab="skills">⚙️ 技能</button>
        </div>

        <div class="tabpane" id="tab-model" style="display:none;">
          <label>模型提供方</label>
          <select id="llmProvider" style="width:100%;padding:6px;border:1px solid #ddd;border-radius:6px;font-size:13px;">
            <option value="sdk">麒麟 SDK（默认，零 Key）</option>
            <option value="api">自定义 API（OpenAI 兼容）</option>
          </select>
          <div id="llmSdkHint" style="font-size:12px;color:#888;margin:8px 0;padding:8px;background:#f5f5f5;border-radius:6px;">
            ✅ 麒麟 SDK 零 Key，无需填写模型与 API Key，保存即可使用
          </div>
          <div id="llmApiFields">
            <label>Base URL</label>
            <input type="text" id="llmBaseUrl" placeholder="https://api.deepseek.com/v1">
            <label>API Key</label>
            <input type="password" id="llmApiKey" placeholder="填写 API Key">
            <label>模型名</label>
            <input type="text" id="llmModel" placeholder="deepseek-chat">
          </div>
          <div class="row">
            <div>
              <label>Temperature</label>
              <input type="text" id="llmTemperature" placeholder="0.7（0~2）">
            </div>
            <div style="display:flex;align-items:flex-end;justify-content:center;padding:6px 0;">
              <span id="tempValue" style="font-size:13px;color:var(--modal-label);">0.7</span>
            </div>
          </div>
          <div class="btns">
            <button id="llmClose">关闭</button>
            <button class="save" id="llmSave">💾 保存模型配置</button>
          </div>
          <div id="llmStatus" style="font-size:12px;color:var(--modal-label);margin-top:6px;"></div>
        </div>
        <div class="tabpane" id="tab-skills" style="display:none;">
          <label>配置名（如：时区规则）</label>
          <input type="text" id="skillName" placeholder="配置名">
          <label>配置内容 / 常用提示词</label>
          <textarea id="skillContent" rows="3" placeholder="配置内容…" style="width:100%;padding:6px;border:1px solid #ddd;border-radius:6px;font-size:13px;resize:vertical;box-sizing:border-box;"></textarea>
          <div class="btns">
            <button id="skillClose">关闭</button>
            <button class="save" id="skillAdd">＋ 存入长期记忆</button>
          </div>
          <div class="field-hint">同名配置自动版本化覆盖</div>
          <div id="skillPanel" style="margin-top:8px;"></div>
        </div>
      </div>
    </div>
    <div class="brand">aichat<em> · 麒麟 AI</em></div>
    <div class="newchat" id="newChat">＋ 新会话</div>
    <div class="sess-list" id="sessList"></div>
  </aside>
  <div class="main">
    <header>
      <span class="dot"></span>
      <span class="brand">aichat<em> · 麒麟 AI</em></span>
      <span class="sub">记忆增强 · 系统工具</span>
      <span class="spacer"></span>
      <select class="model-select" id="headerModel" title="切换模型"></select>
      <select class="model-select" id="headerLang" title="切换语言">
        <option value="zh">中</option>
        <option value="en">EN</option>
      </select>
      <button class="theme-btn" id="themeToggle" title="切换主题">🌙</button>
      <button class="icon-btn" id="clearMem" title="清空 AI 关于你的记忆">清空记忆</button>
      <button class="icon-btn" id="clear" title="清空当前会话">清空</button>
    </header>
    <main><div class="wrap" id="messages">
      <div class="empty" id="empty">
        <h1>你好，我是麒麟 AI</h1>
        <p>我会记住你的偏好，也能调用服务器上的系统工具。</p>
        <p>Enter 发送 · Shift+Enter 换行 · 支持 Markdown</p>
      </div>
    </div></main>
    <footer>
      <div class="inputbar">
        <textarea id="input" rows="1" placeholder="输入消息…（可让我改时区、查系统信息等）"></textarea>
        <button id="send">发送</button>
      </div>
      <div class="hint">Enter 发送 · Shift+Enter 换行 · 回复流式输出 · 对话会自动写入记忆</div>
    </footer>
  </div>
  <aside class="panel">
    <h3 id="memTitle">🧠 记忆</h3>
    <div id="memPanel"><div class="mem-item">（加载中…）</div></div>
    <h3 id="toolTitle">🔧 工具调用</h3>
    <div id="toolPanel"><div class="log-item">（暂无）</div></div>
  </aside>
</div>

<button class="floating-settings" id="floatingSettings" title="设置（外观/模型/技能）">⚙</button>

<script>
const msgs = document.getElementById('messages');
const empty = document.getElementById('empty');
const input = document.getElementById('input');
const send = document.getElementById('send');
const SKEY = 'aichat_session_v1';
// history 按会话隔离（新会话不再显示旧会话消息）
const histKey = (sid) => `aichat_history_v1_${sid || sessionId}`;
const draftKey = (sid) => `aichat_draft_v1_${sid || sessionId}`;
const saveDraft = () => { try { localStorage.setItem(draftKey(), input.value); } catch (e) {} };
const clearDraft = () => { try { localStorage.removeItem(draftKey()); } catch (e) {} };
const loadDraft = (sid) => {
  const v = localStorage.getItem(draftKey(sid)) || '';
  input.value = v;
  input.style.height = 'auto';
  input.style.height = v ? Math.min(input.scrollHeight, 180) + 'px' : 'auto';
};
const RENAME_KEY = 'aichat_rename_v1';
const getNames = () => { try { return JSON.parse(localStorage.getItem(RENAME_KEY) || '{}'); } catch (e) { return {}; } };
const saveName = (sid, name) => { const m = getNames(); m[sid] = name; localStorage.setItem(RENAME_KEY, JSON.stringify(m)); };
const hasMD = typeof marked !== 'undefined';
const hasPurify = typeof DOMPurify !== 'undefined';
const mdOpts = { breaks: true, gfm: true };

let history = [];
try { history = JSON.parse(localStorage.getItem(histKey()) || '[]'); } catch (e) { history = []; }
let busy = false;
// token 支持: URL ?token= 或 localStorage，之后所有请求自动携带
const API_TOKEN = new URLSearchParams(location.search).get('token')
  || localStorage.getItem('aichat_token_v1') || '';
if (API_TOKEN) localStorage.setItem('aichat_token_v1', API_TOKEN);
const apiHeaders = { 'Content-Type': 'application/json' };
if (API_TOKEN) apiHeaders['X-Api-Token'] = API_TOKEN;

let sessionId = localStorage.getItem(SKEY);
if (!sessionId) {
  sessionId = Math.random().toString(36).slice(2) + Date.now().toString(36);
  localStorage.setItem(SKEY, sessionId);
}
loadDraft(sessionId);                  // 恢复当前会话草稿

function scrollBottom() { msgs.scrollTop = msgs.scrollHeight; }
function save() { try { localStorage.setItem(histKey(), JSON.stringify(history)); } catch (e) {} }

function renderMd(el, text) {
  if (hasMD) {
    let html = marked.parse(text || '', mdOpts);
    if (hasPurify) html = DOMPurify.sanitize(html);
    el.innerHTML = html;
  } else {
    el.textContent = text;
  }
}

function addRow(role, text) {
  if (empty && role === 'user') empty.remove();
  const row = document.createElement('div');
  row.className = 'row ' + (role === 'user' ? 'user' : 'assistant');
  const who = document.createElement('div');
  who.className = 'who';
  who.textContent = role === 'user' ? '你' : 'AI';
  const bubble = document.createElement('div');
  bubble.className = 'bubble';
  if (role === 'user') {
    bubble.textContent = text;
  } else {
    const md = document.createElement('div');
    md.className = 'md';
    renderMd(md, text);
    bubble.appendChild(md);
    // ---- 消息操作：复制 / 👍 / 👎（仿 dsh message-feedback）----
    const acts = document.createElement('div');
    acts.className = 'msg-actions';
    const key = 'fb_' + sessionId + '_' + (history.length);
    const saved = localStorage.getItem(key);
    const mk = (t, icon) => {
      const b = document.createElement('button');
      b.textContent = icon;
      b.title = t;
      b.dataset.v = t;
      if (saved === t) b.classList.add('voted');
      return b;
    };
    const bCopy = mk('复制', '📋');
    const bUp = mk('有用', '👍');
    const bDown = mk('没用', '👎');
    bCopy.onclick = async () => {
      try {
        await navigator.clipboard.writeText(text);
        bCopy.textContent = '✅';
        setTimeout(() => { bCopy.textContent = '📋'; }, 1200);
      } catch (e) {}
    };
    bUp.onclick = () => { localStorage.setItem(key, '👍'); bUp.classList.add('voted'); bDown.classList.remove('voted'); };
    bDown.onclick = () => { localStorage.setItem(key, '👎'); bDown.classList.add('voted'); bUp.classList.remove('voted'); };
    acts.appendChild(bCopy);
    acts.appendChild(bUp);
    acts.appendChild(bDown);
    bubble.appendChild(acts);
  }
  row.appendChild(who);
  row.appendChild(bubble);
  msgs.appendChild(row);
  scrollBottom();
  return row;
}

function renderConfirmCard(md, req, originalText) {
  md.innerHTML = '';
  const box = document.createElement('div');
  box.className = 'confirm-box';
  box.innerHTML =
    '<div class="confirm-title">⚠️ 该操作需要您确认</div>' +
    '<div class="confirm-tool">工具：<b>' + req.tool + '</b></div>' +
    '<div class="confirm-params">参数：<pre>' +
      JSON.stringify(req.params || {}, null, 2).replace(/</g, '&lt;') +
    '</pre></div>' +
    '<div class="confirm-btns">' +
      '<button class="confirm-yes">✓ 确认执行</button>' +
      '<button class="confirm-no">✕ 拒绝</button>' +
    '</div>';
  md.appendChild(box);
  const finish = (msg) => {
    renderMd(md, msg);
    history.push({ role: 'assistant', text: msg });
    save();
  };
  box.querySelector('.confirm-yes').onclick = async () => {
    box.innerHTML = '<div class="confirm-title">⏳ 执行中…</div>';
    try {
      const r = await fetch('/api/tool/confirm', {
        method: 'POST', headers: apiHeaders,
        body: JSON.stringify({ token: req.token, action: 'approve' }),
      });
      const d = await r.json();
      finish(d.ok ? d.reply : ('执行失败: ' + (d.error || '')));
    } catch (e) { finish('请求失败: ' + e); }
  };
  box.querySelector('.confirm-no').onclick = async () => {
    try {
      await fetch('/api/tool/confirm', {
        method: 'POST', headers: apiHeaders,
        body: JSON.stringify({ token: req.token, action: 'reject' }),
      });
    } catch (e) {}
    finish('已取消该操作。');
  };
}

function streamInto(md, text) {
  return new Promise(resolve => {
    let i = 0;
    const cursor = document.createElement('span');
    cursor.className = 'cursor';
    md.appendChild(cursor);
    const step = () => {
      i = Math.min(text.length, i + 2);
      renderMd(md, text.slice(0, i));
      md.appendChild(cursor);
      scrollBottom();
      if (i < text.length) setTimeout(step, 14);
      else { cursor.remove(); resolve(); }
    };
    step();
  });
}

async function submit() {
  const text = input.value.trim();
  if (!text || busy) return;
  busy = true;
  send.disabled = true;
  input.value = '';
  input.style.height = 'auto';
  clearDraft();                        // 已发送，清除草稿

  history.push({ role: 'user', text });
  addRow('user', text);
  save();

  const row = document.createElement('div');
  row.className = 'row assistant';
  row.innerHTML = '<div class="who">AI</div><div class="bubble"><div class="md"></div></div>';
  msgs.appendChild(row);
  scrollBottom();
  const md = row.querySelector('.md');
  const cursor = document.createElement('span');
  cursor.className = 'cursor';
  md.appendChild(cursor);

  try {
    // ---- 普通非流式回复 ----
    const r = await fetch('/api/chat', {
      method: 'POST',
      headers: apiHeaders,
      body: JSON.stringify({ message: text, session_id: sessionId })
    });
    const data = await r.json();
    cursor.remove();
    const reply = data.reply || '(无回复)';
    // ---- 工具确认卡片（dsh ask 模式）----
    const cm = reply.match(/\[TOOL_CONFIRM\] (\{.*\})/);
    if (cm) {
      try {
        const req = JSON.parse(cm[1]);
        renderConfirmCard(md, req, reply);
        history.push({ role: 'assistant', text: '⚠️ 请求确认执行工具 ' + req.tool });
        save();
        return;
      } catch (e2) {}
    }
    renderMd(md, reply);
    history.push({ role: 'assistant', text: reply });
    save();
  } catch (e) {
    cursor.remove();
    renderMd(md, '**请求失败**：' + e);
  } finally {
    busy = false;
    send.disabled = false;
    input.focus();
  }
}

function restore() {
  if (!history.length) return;
  empty.remove();
  history.forEach(m => addRow(m.role, m.text));
  scrollBottom();
}
restore();

// ---- CODEX 风格：会话侧栏 + 右侧面板 ----
function renderHistory() {
  msgs.innerHTML = '';
  if (!history.length) {
    const d = document.createElement('div');
    d.className = 'empty'; d.id = 'empty';
    d.innerHTML = '<h1>你好，我是麒麟 AI</h1><p>我会记住你的偏好，也能调用服务器上的系统工具。</p><p>Enter 发送 · Shift+Enter 换行 · 支持 Markdown</p>';
    msgs.appendChild(d);
  } else {
    history.forEach(m => addRow(m.role, m.text));
  }
  scrollBottom();
}
function switchSession(sid) {
  saveDraft();                       // 保存当前会话草稿
  sessionId = sid;
  localStorage.setItem(SKEY, sid);
  history = [];
  try { history = JSON.parse(localStorage.getItem(histKey(sid)) || '[]'); } catch (e) { history = []; }
  if (!history.length) {
    // localStorage 无本地历史（如重启后服务端恢复的会话）→ 从服务端拉取
    fetch('/api/history?session_id=' + encodeURIComponent(sid), { headers: apiHeaders })
      .then(r => r.json()).then(d => {
        if (d.messages && d.messages.length) {
          history = d.messages;
          renderHistory();
          refreshSessions();
        }
      }).catch(() => {});
  }
  renderHistory();
  refreshSessions();
  loadDraft(sid);                     // 加载目标会话草稿
}
async function refreshSessions() {
  try {
    const r = await fetch('/api/sessions', { headers: apiHeaders });
    const d = await r.json();
    const list = document.getElementById('sessList');
    list.innerHTML = '';
    (d.sessions || []).forEach(s => {
      const el = document.createElement('div');
      el.className = 'sess-item' + (s.session_id === sessionId ? ' active' : '');
      el.textContent = (s.preview || s.session_id.slice(0, 12)) + ` (${s.turns})`;
      const names = getNames();
      el.onclick = () => { switchSession(s.session_id); };
      el.title = '点击切换 · 悬停可重命名';
      el.innerHTML = `<span style="flex:1;overflow:hidden;text-overflow:ellipsis;">${names[s.session_id] || s.preview || s.session_id.slice(0,12)}</span>
        <span style="display:none;margin-left:4px;color:var(--accent-2);cursor:pointer;" class="renameBtn">✎</span>
        <span style="display:none;margin-left:4px;color:#c0392b;cursor:pointer;" class="delBtn">🗑</span>`;
      el.style.display = 'flex'; el.style.alignItems = 'center';
      el.onmouseenter = () => { el.querySelector('.renameBtn').style.display = 'inline'; el.querySelector('.delBtn').style.display = 'inline'; };
      el.onmouseleave = () => { el.querySelector('.renameBtn').style.display = 'none'; el.querySelector('.delBtn').style.display = 'none'; };
      el.querySelector('.renameBtn').onclick = (e) => { e.stopPropagation(); renameSession(s.session_id, el); };
      el.querySelector('.delBtn').onclick = (e) => { e.stopPropagation(); deleteSession(s.session_id); };
      list.appendChild(el);
    });
  } catch (e) {}
}
async function deleteSession(sid) {
  if (!confirm('确定删除该会话？此操作不可恢复。')) return;
  try {
    const r = await fetch('/api/sessions/delete', {
      method: 'POST', headers: apiHeaders,
      body: JSON.stringify({ session_id: sid }),
    });
    const d = await r.json();
    if (d.ok && sid === sessionId) {
      // 删除的是当前会话 → 新建空会话
      saveDraft();
      sessionId = Math.random().toString(36).slice(2) + Date.now().toString(36);
      localStorage.setItem(SKEY, sessionId);
      history = [];
      msgs.innerHTML = '';
      renderEmptyMsg();
    }
    refreshSessions();
  } catch (e) { alert('删除失败: ' + e); }
}

async function clearCurrentSession() {
  if (!confirm('确定清空当前对话内容？历史将清空，会话保留。')) return;
  try {
    const r = await fetch('/api/sessions/clear', {
      method: 'POST', headers: apiHeaders,
      body: JSON.stringify({ session_id: sessionId }),
    });
    const d = await r.json();
    if (d.ok) {
      history = [];
      msgs.innerHTML = '';
      renderEmptyMsg();
      refreshSessions();
    } else { alert(d.note || '清空失败'); }
  } catch (e) { alert('清空失败: ' + e); }
}

function renameSession(sid, el) {
  const names = getNames();
  const cur = names[sid] || '';
  const name = prompt('会话重命名（留空恢复默认）:', cur);
  if (name === null) return;  // 取消
  const trimmed = name.trim();
  if (trimmed) saveName(sid, trimmed);
  else { const m = getNames(); delete m[sid]; localStorage.setItem(RENAME_KEY, JSON.stringify(m)); }
  refreshSessions();
}
async function refreshPanels() {
  try {
    const [m, t] = await Promise.all([
      fetch('/api/memories', { headers: apiHeaders }).then(r => r.json()),
      fetch('/api/tool_logs', { headers: apiHeaders }).then(r => r.json()),
    ]);
    const mp = document.getElementById('memPanel');
    mp.innerHTML = (m.memories && m.memories.length)
      ? m.memories.map(x => {
          const icon = x.level === 'high' ? '🔴' : x.level === 'medium' ? '🟡' : '⚪';
          return `<div class="mem-item">${icon} ${x.text}</div>`;
        }).join('')
      : '<div class="mem-item">（暂无记忆）</div>';
    const tp = document.getElementById('toolPanel');
    tp.innerHTML = (t.logs && t.logs.length)
      ? t.logs.slice().reverse().map(l =>
          `<div class="log-item ${l.status === 'verified' || l.status === 'success' ? 'ok' : 'err'}">
             <span class="tool">${l.tool}</span> · ${l.status} · ${l.duration_ms}ms
             ${l.error ? `<br><span style="color:#111111">${l.error.slice(0, 60)}</span>` : ''}
           </div>`).join('')
      : '<div class="log-item">（暂无）</div>';
  } catch (e) {}
}
// ---- 模型配置（默认麒麟 SDK，可切自定义 API）----
// ---- 语言（中文/English，仿 dsh locale）----
const I18N = {
  send: { zh: '发送', en: 'Send' },
  newChat: { zh: '＋ 新会话', en: '＋ New Chat' },
  clear: { zh: '清空', en: 'Clear' },
  clearMem: { zh: '清空记忆', en: 'Clear Memory' },
  inputPh: { zh: '输入消息…（可让我改时区、查系统信息等）', en: 'Type a message… (e.g. check CPU usage)' },
  welcome: { zh: '你好，我是麒麟 AI', en: 'Hello, I\'m Kylin AI' },
  welcomeSub: { zh: '我会记住你的偏好，也能调用服务器上的系统工具。', en: 'I remember your preferences and can use system tools.' },
  hint: { zh: 'Enter 发送 · Shift+Enter 换行 · 回复流式输出 · 对话会自动写入记忆', en: 'Enter send · Shift+Enter newline · streaming · auto memory' },
  memTitle: { zh: '🧠 记忆', en: '🧠 Memory' },
  toolTitle: { zh: '🔧 工具调用', en: '🔧 Tools' },
};
let LANG = localStorage.getItem('aichat_lang') || 'zh';
function t(key) { return ((I18N[key] || {})[LANG] || (I18N[key] || {}).zh || key); }
function renderEmptyMsg() {
  const e = document.getElementById('empty');
  if (e) e.innerHTML = '<h1>' + t('welcome') + '</h1><p>' + t('welcomeSub') + '</p><p>' + t('hint') + '</p>';
}
function applyLang() {
  LANG = localStorage.getItem('aichat_lang') || 'zh';
  document.getElementById('send').textContent = t('send');
  document.getElementById('newChat').textContent = t('newChat');
  document.getElementById('clear').textContent = t('clear');
  document.getElementById('clearMem').textContent = t('clearMem');
  document.getElementById('input').placeholder = t('inputPh');
  const h = document.querySelector('.hint'); if (h) h.textContent = t('hint');
  document.getElementById('memTitle').textContent = t('memTitle');
  document.getElementById('toolTitle').textContent = t('toolTitle');
  renderEmptyMsg();
}
document.getElementById('headerLang').onchange = () => {
  localStorage.setItem('aichat_lang', document.getElementById('headerLang').value);
  applyLang();
};
function loadLang() {
  document.getElementById('headerLang').value = LANG;
  applyLang();
}

// ---- 主题（深色/浅色/跟随系统）----
function applyTheme(t) {
  if (t === 'auto') {
    t = window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
  }
  document.documentElement.setAttribute('data-theme', t);
  document.getElementById('themeToggle').textContent = t === 'dark' ? '☀️' : '🌙';
}
function loadTheme() {
  const t = localStorage.getItem('aichat_theme') || 'light';
  applyTheme(t);
}
document.getElementById('themeToggle').onclick = () => {
  const cur = document.documentElement.getAttribute('data-theme') || 'light';
  const next = cur === 'dark' ? 'light' : 'dark';
  localStorage.setItem('aichat_theme', next);
  applyTheme(next);
};

// ---- 顶栏模型选择器 ----
async function loadHeaderModel() {
  try {
    const r = await fetch('/api/llm_config', { headers: apiHeaders });
    const d = await r.json();
    const sel = document.getElementById('headerModel');
    sel.innerHTML = '';
    const optSdk = document.createElement('option');
    optSdk.value = 'sdk'; optSdk.textContent = '🤖 麒麟 SDK（零 Key）';
    sel.appendChild(optSdk);
    if (d.model) {
      const optApi = document.createElement('option');
      optApi.value = 'api';
      optApi.textContent = '⚡ ' + (d.model || '自定义 API');
      sel.appendChild(optApi);
    }
    sel.value = d.provider === 'api' && d.model ? 'api' : 'sdk';
  } catch (e) {}
}
document.getElementById('headerModel').onchange = async (e) => {
  const v = e.target.value;
  try {
    const r = await fetch('/api/llm_config', { headers: apiHeaders });
    const cfg = await r.json();
    const body = { provider: v, base_url: cfg.base_url || '', model: cfg.model || '', api_key: '' };
    if (v === 'sdk') body.api_key = '';
    await fetch('/api/llm_config', {
      method: 'POST', headers: apiHeaders,
      body: JSON.stringify(body),
    });
  } catch (err) {}
};
loadHeaderModel();
loadTheme();
loadLang();

function toggleLlmFields() {
  const isSdk = document.getElementById('llmProvider').value === 'sdk';
  document.getElementById('llmSdkHint').style.display = isSdk ? '' : 'none';
  document.getElementById('llmApiFields').style.display = isSdk ? 'none' : '';
}
async function refreshLlmConfig() {
  try {
    const r = await fetch('/api/llm_config', { headers: apiHeaders });
    const d = await r.json();
    document.getElementById('llmProvider').value = d.provider || 'sdk';
    document.getElementById('llmBaseUrl').value = d.base_url || '';
    document.getElementById('llmApiKey').value = d.api_key_set ? '******' : '';
    document.getElementById('llmModel').value = d.model || '';
    document.getElementById('llmTemperature').value = d.temperature != null ? d.temperature : 0.7;
    document.getElementById('tempValue').textContent = d.temperature != null ? d.temperature : 0.7;
    toggleLlmFields();
  } catch (e) {}
}
document.getElementById('llmTemperature').oninput = () => {
  document.getElementById('tempValue').textContent = document.getElementById('llmTemperature').value || '';
};
document.getElementById('llmProvider').onchange = toggleLlmFields;
document.getElementById('llmSave').onclick = async () => {
  const btn = document.getElementById('llmSave');
  btn.disabled = true;
  let key = document.getElementById('llmApiKey').value.trim();
  if (key === '******') key = '';  // 占位符=未修改，保留旧 key
  const body = {
    provider: document.getElementById('llmProvider').value,
    base_url: document.getElementById('llmBaseUrl').value.trim(),
    api_key: key,
    model: document.getElementById('llmModel').value.trim(),
    temperature: parseFloat(document.getElementById('llmTemperature').value) || 0.7,
  };
  try {
    const r = await fetch('/api/llm_config', {
      method: 'POST', headers: apiHeaders,
      body: JSON.stringify(body),
    });
    const d = await r.json();
    document.getElementById('llmStatus').textContent = d.ok ? '✅ 已保存，下次对话生效' : ('❌ ' + (d.error || '失败'));
    refreshLlmConfig();
  } catch (e) {
    document.getElementById('llmStatus').textContent = '❌ 保存失败';
  }
  btn.disabled = false;
};
refreshLlmConfig();

// ---- 配置面板（网页输入 → 长期记忆）----
async function refreshSkills() {
  try {
    const r = await fetch('/api/skills', { headers: apiHeaders });
    const d = await r.json();
    const sp = document.getElementById('skillPanel');
    sp.innerHTML = (d.skills && d.skills.length)
      ? d.skills.map(s =>
          `<div class="mem-item" style="position:relative;">
             <b>${s.name}</b> <span style="color:var(--muted)">v${s.version}</span>
             ${(s.tags||[]).map(t=>`<span style="font-size:10px;background:var(--accent);padding:1px 5px;border-radius:4px;margin-left:3px;">${t}</span>`).join('')}
             <div style="font-size:11px;color:var(--muted);margin-top:3px;">${s.content.slice(0,60)}</div>
             <span style="position:absolute;top:4px;right:6px;cursor:pointer;color:#000000;" onclick="deleteSkill('${s.name}')">✕</span>
           </div>`).join('')
      : '<div class="mem-item">（暂无配置，输入后点击存入）</div>';
  } catch (e) {}
}
async function deleteSkill(name) {
  await fetch('/api/skills', { method: 'POST', headers: apiHeaders,
    body: JSON.stringify({ action: 'delete', name }) });
  refreshSkills();
}
document.getElementById('skillAdd').onclick = async () => {
  const name = document.getElementById('skillName').value.trim();
  const content = document.getElementById('skillContent').value.trim();
  if (!name || !content) { alert('请输入配置名和内容'); return; }
  const r = await fetch('/api/skills', { method: 'POST', headers: apiHeaders,
    body: JSON.stringify({ name, content }) });
  const d = await r.json();
  if (d.ok) {
    document.getElementById('skillName').value = '';
    document.getElementById('skillContent').value = '';
    refreshSkills();
    alert(d.conflict ? `已存入（覆盖旧版本 v${d.skill.version}）` : '已存入长期记忆');
  } else { alert('失败: ' + (d.error || '')); }
};
refreshSkills();
document.getElementById('newChat').onclick = () => {
  saveDraft();
  input.value = '';
  sessionId = Math.random().toString(36).slice(2) + Date.now().toString(36);
  localStorage.setItem(SKEY, sessionId);
  history = [];
  renderHistory();          // 清空页面（不整页刷新）
  refreshSessions();
  input.focus();
};
refreshSessions();
// ---- Banner 加载与配置 ----
async function loadBanner() {
  try {
    const r = await fetch('/api/banner', { headers: apiHeaders });
    const cfg = await r.json();
    window._bannerCfg = cfg;
    const b = document.getElementById('banner');
    if (!cfg.enabled) { b.style.display = 'none'; return; }
    b.style.display = 'flex';
    b.style.background = cfg.bg || '#1a1a1a';
    b.style.color = cfg.text_color || '#ffffff';
    document.getElementById('bannerIcon').textContent = cfg.icon || '🤖';
    document.getElementById('bannerTitle').textContent = cfg.title || '';
    document.getElementById('bannerSub').textContent = cfg.subtitle || '';
  } catch (e) {}
}
// ---- 设置弹窗（外观 / 模型 / 技能 三 tab）----
function showTab(tab) {
  document.querySelectorAll('.tabbar .tab').forEach(t => t.classList.toggle('active', t.dataset.tab === tab));
  ['model', 'skills'].forEach(t => {
    document.getElementById('tab-' + t).style.display = (t === tab) ? '' : 'none';
  });
}
function openSettings(tab) {
  showTab(tab || 'model');
  document.getElementById('settingsModal').style.display = 'flex';
  if (tab === 'model') refreshLlmConfig();
  if (tab === 'skills') refreshSkills();
}
document.querySelectorAll('.tabbar .tab').forEach(t => {
  t.onclick = () => {
    showTab(t.dataset.tab);
    if (t.dataset.tab === 'model') refreshLlmConfig();
    if (t.dataset.tab === 'skills') refreshSkills();
  };
});
document.getElementById('floatingSettings').onclick = () => openSettings('appearance');
// 遮罩点击不关闭（防止误关设置）；仅通过关闭按钮关闭

document.getElementById('llmClose').onclick = () => {
  document.getElementById('settingsModal').style.display = 'none';
};
document.getElementById('skillClose').onclick = () => {
  document.getElementById('settingsModal').style.display = 'none';
};

loadBanner();
setInterval(refreshPanels, 4000);
send.onclick = submit;
input.addEventListener('keydown', e => {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); submit(); }
});
input.addEventListener('input', () => {
  input.style.height = 'auto';
  input.style.height = Math.min(input.scrollHeight, 180) + 'px';
  saveDraft();                         // 实时保存当前会话草稿
});
document.getElementById('clear').onclick = () => {
  if (busy) return;
  history = [];
  save();
  saveDraft();
  input.value = '';
  sessionId = Math.random().toString(36).slice(2) + Date.now().toString(36);
  localStorage.setItem(SKEY, sessionId);
  msgs.innerHTML = '';
  const d = document.createElement('div');
  d.className = 'empty';
  d.id = 'empty';
  d.innerHTML = '<h1>' + t('welcome') + '</h1><p>' + t('welcomeSub') + '</p><p>' + t('hint') + '</p>';
  msgs.appendChild(d);
  input.focus();
};
document.getElementById('clearMem').onclick = () => {
  document.getElementById('clearMemModal').style.display = 'flex';
};
document.getElementById('clearMemCancel').onclick = () => {
  document.getElementById('clearMemModal').style.display = 'none';
};
document.getElementById('clearMemModal').onclick = (e) => {
  if (e.target === document.getElementById('clearMemModal'))
    document.getElementById('clearMemModal').style.display = 'none';
};
document.getElementById('clearMemConfirm').onclick = async () => {
  try {
    await fetch('/api/mem/clear', { method: 'POST', headers: apiHeaders });
    alert('已清空 AI 关于你的记忆');
  } catch (e) {
    alert('清空记忆失败: ' + e);
  }
  document.getElementById('clearMemModal').style.display = 'none';
  refreshPanels();
};
</script>
<div class="banner-modal" id="clearMemModal">
  <div class="banner-modal-box" style="width:320px;">
    <h3>⚠️ 清空记忆</h3>
    <p style="font-size:12.5px;color:var(--modal-label);margin:6px 0 12px;">
      确定清空 AI 关于你的<strong>全部长期记忆</strong>吗？<br>此操作不可恢复。
    </p>
    <div class="btns">
      <button id="clearMemCancel">取消</button>
      <button class="save" id="clearMemConfirm" style="background:#c0392b;color:#fff;border-color:#c0392b;">确认清空</button>
    </div>
  </div>
</div>
</body>
</html>
"""


def _clean(reply: str) -> str:
    """去掉 ai_text 输出里的引用标记，如 [1][2]、[无]、[工具结果]、[系统] 等。"""
    s = (reply or "").strip()
    # 过滤独立引用标记 [xxx]；前瞻 (?!\() 排除 markdown 链接 [文字](url)
    s = re.sub(r"[ \t]*\[[^\]]*\](?!\()", "", s)
    return s.strip()


def _clean_json(raw: str) -> str:
    """清洗 AI 生成的 JSON：全角引号、单引号键、裸键、尾随逗号等常见畸形。"""
    s = (raw or "").strip()
    s = s.replace("\u201c", '"').replace("\u201d", '"')  # “ ”
    s = s.replace("\u2018", "'").replace("\u2019", "'")  # ‘ ’
    s = re.sub(r"'(\\u[0-9a-fA-F]{4}|[^']*)':", r'"\1":', s)          # 单引号键
    s = re.sub(r"([{,])\s*([A-Za-z_][A-Za-z0-9_]*)\s*:", r'\1"\2":', s)  # 裸键
    s = re.sub(r"(:)\s*\x27([^\x27]*?)\x27\s*([,}])", r'\1"\2"\3', s)   # 单引号值→双引号
    s = re.sub(r'"tool"\s*:\s*([A-Za-z_][A-Za-z0-9_.-]*)\s*([,}])', r'"tool": "\1"\2', s)  # tool 裸值补引号
    s = re.sub(r",\s*([}\]])", r"\1", s)                              # 尾随逗号
    return s


def _retrieve_memory(query: str) -> str:
    """召回记忆，去重后拼成提示文本。"""
    store = _get_mem0()
    if store is None:
        return ""
    try:
        items = store.search(query)
    except Exception as e:
        print(f"[mem] 检索失败: {e}", flush=True)
        return ""
    seen, lines = set(), []
    for it in items:
        mem = str(it.get("memory", "")).strip()
        if mem and mem not in seen:
            seen.add(mem)
            lines.append(f"- {mem}")
    return "[用户相关记忆]\n" + "\n".join(lines) if lines else ""


def _remember(messages):
    store = _get_mem0()
    if store is None:
        return
    # ---- 融入 QiLinOS 记忆流转：LLM 回合级审查，只保存持久信息 ----
    # 开关 NEX_MEMORY_REVIEW=0 可关闭（默认开）
    try:
        if os.getenv("NEX_MEMORY_REVIEW", "1").strip().lower() not in ("0", "false", "off"):
            from src.memory.memory_lifecycle import review_and_save_memory
            _u = str((messages or [{}])[0].get("content") or "").strip()
            _a = str((messages or [{}])[1].get("content") or "").strip() if len(messages or []) > 1 else ""
            # 仅对正常对话做审查（工具结果/快照跳过，避免污染）
            if _u and not any(mk in _a for mk in ("✅ 工具", "❌", "状态：", "**输出**")):
                review_and_save_memory(_u, _a, store)
    except Exception as _e:
        print(f"[mem] 审查跳过: {_e}", flush=True)
    try:
        with _mem_lock:
            store.add(messages)
        # ④ 偏好类记忆同步写入知识图谱（KG 积累）
        try:
            from src.memory.preferences import is_preference
            _um = str((messages or [{}])[0].get("content") or "").strip()
            if _um and is_preference(_um):
                from src.memory_engine.knowledge_graph import KnowledgeGraph
                _kg_path = os.path.expanduser("~/.nex-agent/memory_kg.json")
                _kg = KnowledgeGraph.load(_kg_path) if os.path.exists(_kg_path) else KnowledgeGraph()
                _kg.add_node(label="preference", text=_um[:100], strength=0.8)
                _kg.save(_kg_path)
        except Exception:
            pass
    except Exception as e:
        print(f"[mem] 写入失败: {e}", flush=True)


_TOOL_LOGS: list = []  # 工具调用日志（前端面板展示）
_MAX_TOOL_LOGS = 50


def _log_tool(tool_name: str, status: str, duration_ms: float, error: str = ""):
    _TOOL_LOGS.append({
        "tool": tool_name, "status": status,
        "duration_ms": round(duration_ms, 1), "error": error or "",
        "ts": datetime.now().strftime("%H:%M:%S"),
    })
    del _TOOL_LOGS[: max(0, len(_TOOL_LOGS) - _MAX_TOOL_LOGS)]


# ---------- 工具确认（dsh ask 模式）：requires_approval 的工具先请求用户确认 ----------
PENDING_TOOLS: dict = {}          # token -> {tool, params, session_id, ts}
_pending_lock = threading.Lock()
_PENDING_TTL = 300                # 确认请求 5 分钟有效
_pending_seq = 0


def _new_pending_token() -> str:
    global _pending_seq
    with _pending_lock:
        _pending_seq += 1
        return f"t{int(time.time())}{_pending_seq}"


def _request_tool_confirm(tool: str, params: dict, session_id: str) -> str:
    """登记待确认工具调用，返回给前端的标记文本。"""
    token = _new_pending_token()
    with _pending_lock:
        PENDING_TOOLS[token] = {"tool": tool, "params": params,
                                "session_id": session_id, "ts": time.time()}
    payload = {"token": token, "tool": tool, "params": params}
    return "[TOOL_CONFIRM] " + json.dumps(payload, ensure_ascii=False)


def _pop_pending(token: str) -> dict | None:
    with _pending_lock:
        item = PENDING_TOOLS.pop(token, None)
        if item and time.time() - item.get("ts", 0) > _PENDING_TTL:
            return None
        return item


def _handle_tool_confirm(self) -> None:
    """POST /api/tool/confirm：用户批准/拒绝待执行工具。"""
    try:
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length) or b"{}")
    except Exception:
        body = {}
    token = (body.get("token") or "").strip()
    action = (body.get("action") or "").strip().lower()
    item = _pop_pending(token)
    if not item:
        return self._json(404, {"ok": False, "error": "确认请求不存在或已过期"})
    tool, params = item.get("tool"), item.get("params") or {}
    session_id = item.get("session_id") or "default"
    if action == "reject":
        try:
            log_reader.append_record("tool", "", tool=tool, status="rejected",
                                     summary="用户拒绝执行")
        except Exception:
            pass
        return self._json(200, {"ok": True, "reply": f"已取消执行「{tool}」操作。"})
    if action != "approve":
        return self._json(400, {"ok": False, "error": "action 必须是 approve 或 reject"})
    # 批准：执行工具（confirmed=True）
    try:
        res = _run_tool(tool, params)
        try:
            log_reader.append_record("tool", "", tool=tool, status=res.status.value,
                                     summary=str(getattr(res, "output", ""))[:200])
        except Exception:
            pass
        reply = _render_tool_result(res)
        return self._json(200, {"ok": True, "reply": reply})
    except Exception as e:
        return self._json(500, {"ok": False, "error": f"执行失败: {e}"})


def _run_tool(tool_name: str, params: dict):
    import time as _t
    _t0 = _t.time()
    # P0 修复：网页端禁止不可逆/中断类系统操作，仅可 SSH 人工执行
    if tool_name in WEB_DISALLOWED_TOOLS:
        print(f"[tool] 已拦截网页端危险工具: {tool_name} {params}", flush=True)
        _log_tool(tool_name, "rejected", 0)
        return ToolResult(
            tool_name=tool_name,
            status=ToolStatus.REJECTED,
            error=f"网页端已禁用 {tool_name}（危险/中断性操作），请通过 SSH 手动执行",
        )
    with _tool_lock:
        async def _run():
            return await EXECUTOR.run(tool_name, confirmed=True, **params)
        res = asyncio.run(_run())
    _log_tool(tool_name, res.status.value, (_t.time() - _t0) * 1000,
              getattr(res, "error", "") or "")
    return res


_STATUS_LABEL = {
    "verified": "成功（已闭环验证）",
    "success": "成功（未验证）",
    "degraded": "降级模式",
    "timeout": "超时",
    "rejected": "被拒绝",
    "failed": "失败",
}


def _render_tool_result(res) -> str:
    """把 ToolResult 渲染成准确、完整的结果说明。"""
    status = res.status.value
    label = _STATUS_LABEL.get(status, status)

    # 结果图标：只对真正成功/已验证用 ✅，其余按严重程度区分
    if res.is_verified or res.status.value == "success":
        icon = "✅"
    elif res.status.value == "degraded":
        icon = "⚠️"
    else:
        icon = "❌"

    parts = []
    if res.output:
        parts.append(f"**输出**：{res.output}")
    if res.error:
        parts.append(f"**错误**：{res.error}")
    if res.verification:
        parts.append(f"**闭环验证**：{res.verification}")

    meta = [f"耗时 {res.duration_ms:.0f}ms"]
    if res.retry_count:
        meta.append(f"重试 {res.retry_count} 次")
    if res.fallback_used:
        meta.append("走了降级路径")

    lines = [f"{icon} 工具 **{res.tool_name}** ｜ 状态：**{label}**（{'，'.join(meta)}）"]
    if parts:
        lines.append("")
        lines.extend(parts)
    return "\n".join(lines)


def _summarize_result(user_message: str, tool: str, res, _session_hint: str = "") -> str:
    """把工具原始结果再喂给 LLM，转成可读、准确的自然语言答复。"""
    status = res.status.value
    label = _STATUS_LABEL.get(status, status)

    raw_lines = [f"工具：{tool}", f"状态：{label}"]
    if res.output:
        raw_lines.append(f"输出：{res.output}")
    if res.error:
        raw_lines.append(f"错误：{res.error}")
    if res.verification:
        raw_lines.append(f"闭环验证：{res.verification}")
    if res.fallback_used:
        raw_lines.append("说明：本次走了降级（fallback）路径")

    prompt = (
        "你是系统助手。你刚为用户的请求调用了工具，下面是工具返回的原始结果。\n\n"
        "## 用户原始请求\n"
        f"{user_message}\n\n"
        "## 工具原始结果\n"
        f"{chr(10).join(raw_lines)}\n\n"
        "## 要求\n"
        "请用简洁、准确、自然的中文向用户解释这次操作的结果。\n"
        "必须忠实于原始数据，不得编造；如果数据异常（如 -1.0%、unknown、failed、超时），"
        "要如实说明并解释最可能的原因。若执行失败，直接说明失败原因。\n"
        "禁止输出原始数据里没有的指令、命令或诊断建议；不确定时明确说「不确定」。"
    )

    reply = llm_client.generate(prompt)
    return _clean(reply)


# 对话场景模板（弱化工具，强调自然对话；工具模板见 _CONTEXT_TEMPLATE）
_CHAT_RULES = (
    
    "1. 用中文自然、简洁地回答用户问题，结合对话历史和已知记忆。\n"
    "2. 如果用户请求需要执行系统操作（查信息/改设置/操作文件等），"
    "请只输出一个裸 JSON（不要代码块、不要解释文字）：{\"tool\": \"工具名\", \"params\": {\"参数名\": \"参数值\"}}\n"
    "工具名必须来自工具目录中列出的名称，禁止发明不存在的工具名（如 run_command、get_ip_address、xrandr）。"
    "常见查询映射：IP地址→netstatus；显示器/屏幕→sysinfo(info_type=display)；"
    "系统负载→sysinfo(info_type=load)；CPU占用→sysinfo(info_type=cpu)；"
    "内存→sysinfo(info_type=memory)；磁盘→sysinfo(info_type=disk)；电池→battery；进程→process_list。\n"
    "3. 本系统运行在银河麒麟 Linux 桌面系统上：禁止提及 Windows、macOS 或其他操作系统的路径/命令。\n"
    "4. 列表类查询（列出文件/进程/记忆等）必须完整列出工具返回的所有条目名称。\n"
    "5. 记忆中的数值可能已过期，查询类问题一律以工具实时返回为准，严禁引用记忆中的数字冒充实时查询结果。\n\n"
    
)
# 工具意图关键词（用于选择工具场景模板）
_TOOL_INTENT = ("设置", "修改", "更改", "创建", "删除", "打开", "关闭", "查询", "查看",
                "文件", "文件夹", "时区", "时间", "音量", "进程", "安装", "配置",
                "状态", "有哪些", "多少", "最大", "列表", "电量", "网络", "蓝牙",
                "壁纸", "截图", "开机", "关机", "重启", "清理", "记住", "忘记")


def _render(template: str, **ctx) -> str:
    """把 <<VAR>> 占位符替换为对应值（对齐 NexAgent 的 apply_prompt_template 机制）。"""
    return re.sub(r"<<([^>>]+)>>", lambda m: str(ctx.get(m.group(1), "")), template)


import re as _re_mod  # noqa

def _route_intent(message: str) -> str:
    """结构化意图分流（融入 QiLinOS coordinator 规则）。

    返回: tool | memory_query | preference | chat | forget | planning | web
    规则优先（零 LLM 成本），规则未命中时用 LLM 分类（失败回退 chat）。
    """
    msg = (message or "").strip()
    if not msg:
        return "chat"
    low = msg.lower()
    # 1) 遗忘类（交给 ForgetFlow 处理）
    from src.memory_engine.forget_api import extract_forget_target
    if extract_forget_target(msg) or (
            any(w in msg for w in ("记忆", "记住", "偏好")) and
            any(w in msg for w in ("删", "忘", "清", "remove", "delete", "forget"))):
        return "forget"
    # 2) 工具/系统操作（对齐 _TOOL_INTENT，优先于 web）
    if any(k in msg for k in _TOOL_INTENT):
        return "tool"
    # 3) 外部能力/实时信息 → 搜索
    if any(k in msg for k in ("搜索", "搜一下", "最新", "新闻", "天气", "股价",
                               "网址", "网页", "http", "www.")):
        return "web"
    # 4) 记忆查询（用户已知记忆/偏好）
    if any(k in msg for k in ("我记得", "我的偏好", "我的习惯", "我喜欢", "我讨厌",
                               "我以前", "我上次", "我之前")):
        return "memory_query"
    # 5) LLM 分类兜底（默认开启，可用 NEX_LLM_ROUTING=0 关闭）
    if os.getenv("NEX_LLM_ROUTING", "1").strip().lower() not in ("0", "false", "off"):
        try:
            _route_prompt = (
                "你是意图路由器。将用户消息分类为："
                "tool(系统操作/查询/文件) | web(搜索/网页/外部信息) | "
                "memory_query(询问记忆/偏好/历史) | forget(删除/遗忘记忆) | "
                "chat(闲聊/问答/其他)。只输出一个词。\n用户消息：" + msg[:200])
            _r = llm_client.generate(_route_prompt).strip().lower()
            for k in ("forget", "memory_query", "web", "tool"):
                if k in _r:
                    return k
        except Exception:
            pass
    return "chat"


# 上下文模板：用 <<VAR>> 占位符（而非 str.format），避免与规则里的 JSON 花括号冲突
_TOOL_RULES = (
    
    "1. 如果用户请求需要执行系统操作（改时区、查硬件/进程/电池、建文件夹/文件等），"
    "且上面有对应工具，请**只输出**一个 JSON，不要输出其它内容：\n"
    '{"tool": "工具名", "params": {"参数名": "参数值"}}\n'
    "JSON 必须裸输出：不要用 ```json 代码块包裹，也不要附带任何解释文字。"
    "参数名必须与工具目录描述中出现的名称完全一致（如 file 工具：action/path/paths/count/ext），禁止自创参数名。"
    "params 必须把工具所需的全部参数填全（例如 timezone 工具必须带 timezone 参数，"
    "值为 'Asia/Shanghai' 这类合法时区）；若用户没给出必要参数，"
    "不要输出 JSON，用中文反问用户补齐。\n"
    "常见查询映射：IP地址→netstatus；显示器/屏幕→sysinfo(info_type=display)；"
    "系统负载→sysinfo(info_type=load)；CPU占用→sysinfo(info_type=cpu)；"
    "内存→sysinfo(info_type=memory)；磁盘→sysinfo(info_type=disk)；"
    "电池→battery；进程→process_list；网速→sysinfo(info_type=netspeed)；温度→sysinfo(info_type=temp)；识别图片/文字→ocr。\n"
    "2. 若用户请求是具体的系统操作（建文件夹、列目录、查看文件、复制/移动等），"
    "但上面没有对应工具，请改用 shell 工具执行一条白名单命令，仍然**只输出** JSON：\n"
    '{"tool": "shell", "params": {"cmd": "白名单命令"}}\n'
    "命令只能用 shell 工具描述里列出的白名单命令，路径写完整（如 ~/桌面/xxx）。\n"
    "3. 否则，结合对话历史，用中文简洁、自然地回答用户问题。\n"
    "4. 本系统运行在银河麒麟 Linux 桌面系统上：禁止提及 Windows、macOS 或其他操作系统的路径/命令。\n"
    "5. 列表类查询（列出文件/进程/记忆等）必须完整列出工具返回的所有条目名称，不得省略或只摘录少数。\n"
    "6. 创建「一个文件夹内含多个文件」时（如 10 个空 markdown 文件），"
    "必须用 file 工具一步完成：action=mkdir + path + count=N + ext=后缀（如 count=10, ext=md 生成 10 个 .md 空文件）；"
    "禁止用 shell 的 ';' 或 '&&' 拼接多条命令，也不要只创建文件夹而不生成文件。\n"
    "7. 工具名必须来自工具目录中列出的名称，禁止发明不存在的工具名（如 run_command）；"
    "记忆中的内容可能已过期，查询类问题一律以工具实时返回为准，不得用记忆数据冒充当前查询结果。\n"
    "8b. 文件/文本查询映射："
    "查看/读取文件内容 → file 工具 action=read path=完整路径（或 shell cat 路径）；"
    "查找【内容】包含某关键词的文件 → shell 工具 grep -l 关键词 路径/*（grep 匹配内容，find -name 只匹配文件名，不要混用）；"
    "统计文件数量 → shell ls 路径 | wc -l 或 file list；"
    "列出目录 → file action=list path=路径（或 shell ls）。"
    "工具返回后必须把具体文件名、内容、数量原样转述，禁止只说'已成功'。\n"
    "示例（务必模仿此格式）：\n"
    "  用户：查找 /tmp 下包含 project_dev1 的文件\n"
    "  工具：{\"tool\": \"shell\", \"params\": {\"cmd\": \"grep -l project_dev1 /tmp/* 2>/dev/null | head -10\"}}\n"
    "  工具返回：/tmp/测试文本.txt\n"
    "  正确回答：找到包含 project_dev1 的文件：/tmp/测试文本.txt\n"
    "  错误回答：已成功查找（没有列出文件名）\n"
    "  用户：查看桌面测试文档.txt 的内容\n"
    "  工具：{\"tool\": \"file\", \"params\": {\"action\": \"read\", \"path\": \"~/桌面/测试文档.txt\"}}\n"
    "  工具返回：第一行：hello world\n"
    "  正确回答：测试文档.txt 的内容：第一行：hello world（原样转述）\n"
    "  查找【内容】用 grep -l；查找【文件名】用 find -name。\n"
    "8. 路径必须是用户原话或工具返回的精确路径，禁止自行拼接、添加或修改修饰词"
    "（如用户提到「测试文件夹」，路径只能用用户提供的原词；目录名与路径不要混入「文件夹」等描述词）。\n"
    "9. 查询最大文件/目录、文件大小、磁盘占用排名等，**必须调用 shell 工具执行管道命令**"
    "（禁止用 file list 代替，禁止只凭记忆回答，禁止重定向 >）："
    "du -sh 路径/* | sort -rn | head -N 或 find 路径 -type f -printf '%s %p\\n' | sort -rn | head -N；"
    "shell 管道允许 2>/dev/null 丢弃错误输出。注意：桌面路径是 ~/桌面（中文，不是 ~/Desktop）。\n"
    "10. 调用工具后必须把工具返回的具体结果转述给用户（文件名、数值、列表等），"
    "禁止只回答「已成功/已执行」而不给出结果内容；若工具未返回结果请如实说明并换一种方式重试。\n\n"
    
)

def _skill_prompt_block() -> str:
    """技能/长期记忆配置 → 提示词分节（dsh: 配置即长期记忆，须遵守）。"""
    try:
        sm = _get_skill_memory()
        skills = sm.list_skills()
        if not skills:
            return ""
        lines = []
        for sk in skills:
            name = getattr(sk, "name", "")
            content = getattr(sk, "content", "")
            cond = getattr(sk, "condition", "") or ""
            tag_txt = ",".join(getattr(sk, "tags", []) or [])
            if name and content:
                head = name + (f"（适用: {cond}）" if cond else "")
                if tag_txt:
                    head += f" [{tag_txt}]"
                lines.append(f"- {head}: {content[:200]}")
        return "\n".join(lines) if lines else ""
    except Exception:
        return ""


def _build_context(message: str, session_id: str) -> str:
    """统一拼接上下文（dsh 分节式：身份/工具/记忆/画像/技能/历史/规则/用户）。"""
    memory = _retrieve_memory(message)
    profile = _db_user_profile()  # DB 用户画像（借鉴 AgentProject）
    skills = _skill_prompt_block()  # ③ 技能配置注入（dsh: 配置即长期记忆）
    history = _session_history(session_id)
    meta = SESSIONS_META.get(session_id, {}) or {}
    _summary = (meta.get("summary") or "").strip()
    _recent = "\n".join(
        f"{'用户' if h['role'] == 'user' else '助手'}：{h['content']}"
        for h in history
    )
    hist_block = ""
    if _summary:
        hist_block += f"[早期对话摘要]\n{_summary}\n\n"
    hist_block += _recent or "（暂无）"

    # 分场景：含工具意图 → 工具规则（含完整工具目录）；否则对话规则
    # 融入 QiLinOS coordinator 分流：_route_intent 结构化分类（规则+LLM兜底）
    is_tool = _route_intent(message) in ("tool", "web", "forget")
    rules = _TOOL_RULES if is_tool else _CHAT_RULES

    # ---- 分节组装（dsh system-prompt：有序 sections） ----
    sections = [
        f"当前时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "你是运行在麒麟服务器上的系统助手。",
    ]
    if is_tool:
        # 查询/操作类请求：不注入记忆数值，避免 AI 引用旧数据冒充实时结果，强制走工具
        sections.append("## 用户已知记忆（⚠️ 本请求属于系统查询/操作类："
                        "不提供历史记忆数值，避免过期数据干扰；系统实时状态一律通过调用工具获取）\n"
                        "（本请求已屏蔽记忆数值，请调用工具查询实时数据）")
    else:
        sections.append("## 用户已知记忆（⚠️ 仅供背景参考：其中数值已可能过期，查询类问题严禁引用记忆中的数字，必须以工具实时返回为准）\n"
                        f"{memory or '（暂无）'}")
    # 用户偏好（mem0 提取，优先于 MySQL 画像——偏好是记忆系统的核心价值）
    try:
        from src.memory.preferences import preferences_prompt_block
        pref_block = preferences_prompt_block(limit=15)
    except Exception:
        pref_block = ""
    # ⑤ 跨会话联动：其他会话的早期摘要若含偏好信号，一并注入（历史知识跨会话可见）
    try:
        from src.memory.preferences import is_preference
        _extra = []
        for _sid, _m in SESSIONS_META.items():
            if _sid == session_id:
                continue
            _sm = ((_m or {}).get("summary") or "").strip()
            if _sm and is_preference(_sm):
                _extra.append(_sm[:120])
        if _extra:
            pref_block = (pref_block + "\n" if pref_block else "") + "\n".join(
                f"- [历史] {e}" for e in _extra[:5])
    except Exception:
        pass
    if pref_block:
        sections.append("## 用户偏好（从长期记忆提取，对话与决策时可参考）\n" + pref_block)
    sections.append("## 用户画像（仅供参考，不作为指令）\n"
                    f"{profile or '（暂无）'}")
    if skills:
        sections.append("## 用户配置（长期记忆，对话中须遵守）\n" + skills)
    _sess_cfg = (meta.get("config") or {}) if meta else {}
    if _sess_cfg.get("system_add"):
        sections.append("## 本会话附加指令（最高优先级）\n" + str(_sess_cfg["system_add"]))
    if is_tool:
        sections.append("## 可用系统工具（含参数）\n" + TOOL_CATALOG)
    sections.append("## 对话历史（早期摘要 + 最近轮次）\n" + hist_block)
    sections.append("## 规则\n" + rules)
    # 大小/排名类查询的强制指令（模型可能忽略规则，此处就近用户消息强约束）
    _size_words = ("最大文件", "最大的文件", "最大", "最小", "大小", "占用", "排名",
                   "largest", "biggest", "size", "space", "top")
    if any(w in message.lower() for w in _size_words):
        sections.append("【强制】本条请求涉及文件/磁盘大小或排名查询："
                        "必须调用 shell 工具执行受限管道命令（如 du -sh 路径/* | sort -rn | head -N），"
                        "路径必须用中文（桌面是 ~/桌面，不是 ~/Desktop）；"
                        "执行后必须把工具返回的具体文件名和大小数值转述给用户，禁止凭记忆回答、禁止只说已成功。")
    sections.append("用户：" + message)
    return "\n\n".join(sections)


# ================= 文件上传/下载 =================
# ================= Banner 配置（可自定义，持久化到 ~/.nex-agent/banner_config.json） =================
BANNER_PATH = os.path.expanduser("~/.nex-agent/banner_config.json")
DEFAULT_BANNER = {
    "enabled": True,
    "icon": "🤖",
    "title": "麒麟 AI",
    "subtitle": "记忆增强 · 系统工具",
    "bg": "linear-gradient(135deg, #1a1a1a, #333333)",
    "text_color": "#ffffff",
}
_BANNER_KEYS = ("enabled", "icon", "title", "subtitle", "bg", "text_color")


def _load_banner() -> dict:
    try:
        with open(BANNER_PATH, encoding="utf-8") as f:
            cfg = json.load(f)
        return {**DEFAULT_BANNER, **{k: cfg[k] for k in _BANNER_KEYS if k in cfg}}
    except Exception:
        return dict(DEFAULT_BANNER)


def _save_banner(cfg: dict) -> dict:
    merged = {**DEFAULT_BANNER, **{k: cfg[k] for k in _BANNER_KEYS if k in cfg}}
    merged["enabled"] = bool(merged.get("enabled", True))
    try:
        os.makedirs(os.path.dirname(BANNER_PATH), exist_ok=True)
        with open(BANNER_PATH, "w", encoding="utf-8") as f:
            json.dump(merged, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[banner] 保存失败: {e}", flush=True)
    return merged


UPLOAD_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)
MAX_UPLOAD_SIZE = 50 * 1024 * 1024  # 50MB
# 允许的文件类型（按扩展名白名单）
ALLOWED_EXT = {
    ".txt", ".md", ".pdf", ".docx", ".xlsx", ".csv", ".json", ".log",
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".py", ".xml", ".yaml", ".yml", ".toml",
}

def _safe_filename(name: str) -> str:
    """文件名消毒：只保留 basename + 去危险字符（防路径穿越/注入）。"""
    import re as _re
    base = os.path.basename((name or "").replace("\\", "/"))
    # 去控制字符/路径分隔/引号等危险字符，保留中文/字母数字/._-
    safe = _re.sub(r"[^\w.\u4e00-\u9fa5\-]", "_", base)
    safe = safe.strip("._ ")
    return safe[:120] or "file"

def _handle_upload(self) -> None:
    """POST /api/upload：multipart 单文件上传，保存到 uploads/。"""
    try:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return self._json(400, {"ok": False, "error": "空请求"})
        if length > MAX_UPLOAD_SIZE:
            return self._json(413, {"ok": False, "error": "文件过大（上限 50MB）"})
        import cgi
        form = cgi.FieldStorage(
            fp=self.rfile, headers=self.headers,
            environ={"REQUEST_METHOD": "POST", "CONTENT_TYPE": self.headers.get("Content-Type", "")},
        )
        f = form["file"]
        if f is None or not getattr(f, "filename", None):
            return self._json(400, {"ok": False, "error": "缺少文件字段 file"})
        raw_name = f.filename
        ext = os.path.splitext(raw_name)[1].lower()
        if ext not in ALLOWED_EXT:
            return self._json(400, {"ok": False, "error": f"不支持的文件类型 {ext or '(无扩展名)'}"})
        data = f.file.read()
        if len(data) > MAX_UPLOAD_SIZE:
            return self._json(413, {"ok": False, "error": "文件过大（上限 50MB）"})
        fname = _safe_filename(raw_name)
        path = os.path.join(UPLOAD_DIR, fname)
        with open(path, "wb") as out:
            out.write(data)
        size_kb = round(len(data) / 1024, 1)
        print(f"[upload] 已保存: {fname} ({size_kb} KB)", flush=True)
        return self._json(200, {"ok": True, "filename": fname, "size_kb": size_kb,
                                "note": f"已上传 {fname}（{size_kb} KB），可在对话中让我分析它"})
    except Exception as e:
        print(f"[upload] 失败: {e}", flush=True)
        return self._json(500, {"ok": False, "error": f"上传失败: {e}"})

def _handle_download(self, filename: str) -> None:
    """GET /api/download/<filename>：下载 uploads/ 下的文件（防路径穿越）。"""
    try:
        safe = _safe_filename(filename)
        path = os.path.join(UPLOAD_DIR, safe)
        if not os.path.isfile(path):
            return self._json(404, {"ok": False, "error": "文件不存在"})
        with open(path, "rb") as f:
            data = f.read()
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Content-Disposition", f"attachment; filename=\"{safe}\"")
        self.end_headers()
        self.wfile.write(data)
    except Exception as e:
        print(f"[download] 失败: {e}", flush=True)
        return self._json(500, {"ok": False, "error": f"下载失败: {e}"})


def _stream_chunks(text: str, size: int = 4):
    """把完整回复切成 SSE 小块：优先按标点边界，再按固定大小。"""
    if not text:
        return [""]
    # 先按句末标点切分
    parts = re.split(r"(?<=[。！？；\n，,.!?;])", text)
    chunks: list[str] = []
    buf = ""
    for part in parts:
        buf += part
        if len(buf) >= size or buf.rstrip().endswith(("。", "！", "？", "；", "\n")):
            chunks.append(buf)
            buf = ""
    if buf:
        chunks.append(buf)
    return chunks or [text]


def _chat(message: str, session_id: str = "default"):
    """统一上下文 → 让 AI 编排 → 执行工具 / 直接回答。"""
    # ---- 精准遗忘流程（coordinator_node → forget_node）----
    # 命中遗忘交互时不再走 LLM 编排：确认/取消/展示候选都由 ForgetFlow 处理
    try:
        _f_reply, _f_handled = _get_forget_flow().handle(message, session_id)
        if _f_handled:
            log_reader.append_record("user", message)
            return _f_reply
    except Exception as _f_e:
        print(f"[forget] 遗忘流程异常，回退正常对话: {_f_e}", flush=True)
    log_reader.append_record("user", message)
    prompt = _build_context(message, session_id)
    # ⑤ 会话级模型覆盖（dsh scope）：该会话指定模型时临时覆盖全局配置
    _sess_cfg = (SESSIONS_META.get(session_id, {}) or {}).get("config") or {}
    if _sess_cfg.get("model"):
        try:
            from src import llm_client as _lc
            _cfg = _lc.load_config()
            _cfg["model"] = _sess_cfg["model"]
            _gen = lambda p: _lc.generate(p, _cfg)
        except Exception:
            _gen = llm_client.generate
    else:
        _gen = llm_client.generate

    raw = _gen(prompt)
    raw = _clean(raw)

    # 尝试解析工具编排 JSON
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if m:
        try:
            plan = json.loads(_clean_json(m.group(0)))
            tool = plan.get("tool")
            if tool:
                if tool not in REGISTRY.list_all():
                    # AI 编造了不存在的工具：不返回原始 JSON，给友好提示
                    return (f"我无法执行「{tool}」这个操作，它不在我可用的工具列表中。"
                            f"请换个说法描述您的需求，例如：系统 CPU 占用情况、当前内存使用、磁盘空间等。")
                params = plan.get("params") or {}
                step = plan.get("step")
                total_steps = plan.get("total_steps") or plan.get("all_step")
                # ---- dsh ask 模式：requires_approval 的工具先请求用户确认 ----
                _td = REGISTRY.get(tool)
                if _td is not None and getattr(_td, "requires_approval", False):
                    confirm_text = _request_tool_confirm(tool, params, session_id)
                    try:
                        log_reader.append_record("tool", "", tool=tool, status="pending",
                                                 summary="等待用户确认")
                    except Exception:
                        pass
                    return (f"⚠️ 该操作需要您确认：\n"
                            f"**工具**：{tool}\n"
                            f"**参数**：{json.dumps(params, ensure_ascii=False)}\n"
                            f"\n{confirm_text}")
                res = _run_tool(tool, params)
                try:
                    log_reader.append_record("tool", "", tool=tool,
                                             status=res.status.value,
                                             summary=str(getattr(res, "output", ""))[:200])
                except Exception:
                    pass
                # 忠实透传工具结果（不经 LLM 美化——LLM 二次总结会丢数据/空泛化）
                reply = _render_tool_result(res)
                if step is not None and total_steps:
                    reply = f"（步骤 {step}/{total_steps}）" + reply
                return reply
        except Exception as e:
            print(f"[tool] 编排执行失败: {e}", flush=True)
            # AI 输出畸形 JSON（如 "files":} 缺值）：用 LLM 修正重试一次
            if '"tool"' in raw or "'tool'" in raw:
                try:
                    retry_raw = _gen(
                            prompt + "\n\n注意：您上一次输出的工具调用 JSON 格式不完整或无效。"
                            "请重新输出，必须是一个完整合法的 JSON 对象，所有字段都要有值。"
                        )
                    m2 = re.search(r"\{.*\}", retry_raw, re.DOTALL)
                    if m2:
                        plan2 = json.loads(_clean_json(m2.group(0)))
                        tool2 = plan2.get("tool")
                        if tool2 in REGISTRY.list_all():
                            res2 = _run_tool(tool2, plan2.get("params") or {})
                            return _summarize_result(message, tool2, res2)
                except Exception as e2:
                    print(f"[tool] JSON 修正重试失败: {e2}", flush=True)
                return ("您的请求我理解到了，但生成的操作指令不完整。"
                        "请换个说法再试一次，例如："
                        "「在桌面新建文件夹 test，里面放 10 个空的 .md 文件」")

    return raw


class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True


class Handler(BaseHTTPRequestHandler):
    def _auth_ok(self) -> bool:
        """token 校验：未配置 WEBCHAT_TOKEN 时放行，配置后要求 X-Api-Token 匹配。"""
        if not WEBCHAT_TOKEN:
            return True
        return self.headers.get("X-Api-Token") == WEBCHAT_TOKEN

    def _send(self, code, body: bytes, ctype: str):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code, obj):
        try:
            body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            self._send(code, body, "application/json; charset=utf-8")
        except Exception as e:
            print(f"[webchat] json 输出失败: {e}", flush=True)
            self._send(500, b'{"error":"internal"}', "application/json; charset=utf-8")

    def _handle_chat_stream(self):
        """POST /api/chat/stream：SSE 流式对话回复。"""
        import time as _t
        try:
            length = int(self.headers.get("Content-Length") or 0)
            data = json.loads(self.rfile.read(length) or b"{}")
        except Exception:
            data = {}
        prompt = (data.get("message") or "").strip()
        if not prompt:
            return self._json(200, {"reply": "(空消息)"})
        session_id = (data.get("session_id") or "default").strip() or "default"

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()

        def _emit(obj: dict):
            try:
                self.wfile.write(("data: " + json.dumps(obj, ensure_ascii=False) + "\n\n").encode("utf-8"))
                self.wfile.flush()
            except Exception:
                pass

        try:
            reply = _chat(prompt, session_id)
        except Exception as e:
            reply = f"(SDK 调用失败: {e})"

        # 流式发送回复块（打字机效果）
        for chunk in _stream_chunks(reply):
            _emit({"chunk": chunk})
            _t.sleep(0.02)
        _emit({"done": True})
        try:
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
        except Exception:
            pass

        # 与 /api/chat 一致：会话记录 + 记忆流转 + 异步写记忆
        try:
            _session_append(session_id, "user", prompt)
            _session_append(session_id, "assistant", reply)
        except Exception:
            pass
        try:
            _flow_after_chat(session_id, prompt, reply)
        except Exception:
            pass
        try:
            threading.Thread(
                target=_remember,
                args=([{"role": "user", "content": prompt},
                       {"role": "assistant", "content": reply}],),
                daemon=True,
            ).start()
        except Exception:
            pass
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self._send(code, body, "application/json; charset=utf-8")

    def do_GET(self):
        # P0 加固：GET /api/* 同样需要 token（否则记忆等敏感数据可被匿名读取）
        if self.path.startswith("/api/") and not self._auth_ok():
            return self._json(403, {"error": "forbidden: 缺少或错误的 X-Api-Token"})
        if self.path in ("/", "/index.html"):
            self._send(200, HTML.encode("utf-8"), "text/html; charset=utf-8")
        elif self.path == "/api/sessions":
            with _sessions_lock:
                sess = [
                    {"session_id": sid, "turns": len(hist),
                     "title": (SESSIONS_META.get(sid, {}) or {}).get("title", ""),
                     "preview": (hist[-1]["content"][:24] if hist else "")}
                    for sid, hist in SESSIONS.items()
                ]
            self._json(200, {"sessions": sess})
        elif self.path.startswith("/api/history"):
            from urllib.parse import urlparse, parse_qs
            qs = parse_qs(urlparse(self.path).query)
            sid = (qs.get("session_id") or [""])[0]
            hist = _session_history(sid)
            self._json(200, {"messages": [
                {"role": h["role"], "text": h["content"]} for h in hist
            ]})
        elif self.path == "/api/tool_logs":
            self._json(200, {"logs": list(_TOOL_LOGS)})
        elif self.path == "/api/llm_config":
            _cfg = llm_client.load_config()
            self._json(200, {
                "provider": _cfg.get("provider", "sdk"),
                "base_url": _cfg.get("base_url", ""),
                "model": _cfg.get("model", ""),
                "api_key_set": bool(_cfg.get("api_key")),
                "temperature": _cfg.get("temperature", 0.7),
            })
        elif self.path == "/api/skills":
            sm = _get_skill_memory()
            items = [{"name": s.name, "content": s.content, "tags": s.tags,
                      "version": s.version, "condition": s.condition}
                     for s in sm.list_skills()]
            self._json(200, {"skills": items, "conflicts": len(sm.conflicts())})
        elif self.path.startswith("/api/session/config"):
            from urllib.parse import urlparse, parse_qs
            qs = parse_qs(urlparse(self.path).query)
            sid = (qs.get("session_id") or [""])[0]
            cfg = (SESSIONS_META.get(sid, {}) or {}).get("config") or {}
            self._json(200, {"session_id": sid, "config": cfg})
        elif self.path == "/api/banner":
            self._json(200, _load_banner())
        elif self.path.startswith("/api/download/"):
            from urllib.parse import unquote
            fname = unquote(self.path[len("/api/download/"):])
            return _handle_download(self, fname)
        elif self.path == "/api/preferences":
            try:
                from src.memory.preferences import query_preferences
                prefs = query_preferences(limit=50)
            except Exception as e:
                prefs = []
                print(f"[prefs] 查询失败: {e}", flush=True)
            self._json(200, {"preferences": prefs})
        elif self.path == "/api/memories":
            store = _get_mem0()
            items = []
            if store is not None:
                try:
                    from src.memory.priority import prioritize_items
                    raw = store.list_all(top_k=200)
                    for it in prioritize_items(raw):
                        items.append({
                            "text": str(it.get("memory", ""))[:80],
                            "level": it.get("priority_level", "low"),
                            "score": it.get("priority", 0),
                        })
                except Exception:
                    pass
            self._json(200, {"memories": items})
        else:
            self._send(404, b"not found", "text/plain; charset=utf-8")

    def do_POST(self):
        if not self._auth_ok():
            return self._json(403, {"error": "forbidden: 缺少或错误的 X-Api-Token"})
        if self.path == "/api/session/config":
            try:
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length) or b"{}")
            except Exception:
                body = {}
            sid = (body.get("session_id") or "").strip()
            if not sid:
                return self._json(400, {"ok": False, "error": "缺少 session_id"})
            with _sessions_lock:
                meta = SESSIONS_META.setdefault(sid, {"summary": "", "title": ""})
                cfg = dict(meta.get("config") or {})
                if body.get("system_add") is not None:
                    cfg["system_add"] = str(body["system_add"]).strip()[:2000]
                if body.get("model"):
                    cfg["model"] = str(body["model"]).strip()[:80]
                meta["config"] = cfg
                _persist_sessions()
            return self._json(200, {"ok": True, "config": cfg})
        if self.path == "/api/banner":
            try:
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length) or b"{}")
            except Exception:
                body = {}
            saved = _save_banner(body)
            return self._json(200, {"ok": True, **saved})
        if self.path == "/api/tool/confirm":
            return _handle_tool_confirm(self)
        if self.path == "/api/chat/stream":
            return self._handle_chat_stream()
        if self.path == "/api/upload":
            return _handle_upload(self)
        if self.path == "/api/sessions/delete":
            try:
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length) or b"{}")
            except Exception:
                body = {}
            sid = (body.get("session_id") or "").strip()
            if not sid:
                return self._json(400, {"ok": False, "error": "缺少 session_id"})
            ok = _delete_session(sid)
            return self._json(200, {"ok": ok, "note": "会话已删除" if ok else "会话不存在"})

        if self.path == "/api/sessions/clear":
            try:
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length) or b"{}")
            except Exception:
                body = {}
            sid = (body.get("session_id") or "").strip()
            if not sid:
                return self._json(400, {"ok": False, "error": "缺少 session_id"})
            ok = _clear_session(sid)
            return self._json(200, {"ok": ok, "note": "对话已清空" if ok else "会话不存在"})

        if self.path == "/api/llm_config":
            try:
                _length = int(self.headers.get("Content-Length") or 0)
                _body = json.loads(self.rfile.read(_length) or b"{}")
            except Exception:
                _body = {}
            _cfg = llm_client.load_config()
            if _body.get("provider") in ("sdk", "api"):
                _cfg["provider"] = _body["provider"]
            if _body.get("base_url"):
                _cfg["base_url"] = _body["base_url"].strip()
            if _body.get("api_key"):
                _cfg["api_key"] = _body["api_key"].strip()
            if _body.get("model"):
                _cfg["model"] = _body["model"].strip()
            if _body.get("temperature") is not None:
                try:
                    _cfg["temperature"] = max(0.0, min(2.0, float(_body["temperature"])))
                except Exception:
                    pass
            if _cfg["provider"] == "api" and not _cfg.get("api_key"):
                return self._json(400, {"ok": False, "error": "API 模式必须提供 API Key"})
            llm_client.save_config(_cfg)
            return self._json(200, {"ok": True})
        if self.path == "/api/skills":
            try:
                length = int(self.headers.get("Content-Length") or 0)
                data = json.loads(self.rfile.read(length) or b"{}")
            except Exception:
                data = {}
            sm = _get_skill_memory()
            if data.get("action") == "delete":
                ok = sm.delete_skill((data.get("name") or "").strip())
                return self._json(200, {"ok": ok})
            skill = sm.add_skill(
                name=(data.get("name") or "").strip(),
                content=(data.get("content") or "").strip(),
                tags=data.get("tags") or [],
                condition=data.get("condition") or "",
            )
            if skill is None:
                return self._json(400, {"error": "配置为空或被安全审查拦截"})
            return self._json(200, {
                "ok": True, "skill": skill.to_dict(),
                "conflict": sm.has_conflict(skill.name),
                "note": "配置已存入长期记忆（同名更新版本化）",
            })

        if self.path == "/api/mem/clear":
            store = _get_mem0()
            if store is None:
                return self._json(200, {"ok": True, "note": "no-memory 模式，记忆未启用"})
            try:
                store.delete_all()
                return self._json(200, {"ok": True})
            except Exception as e:
                return self._json(500, {"error": str(e)})

        if self.path != "/api/chat":
            return self._send(404, b"not found", "text/plain; charset=utf-8")

        try:
            length = int(self.headers.get("Content-Length") or 0)
            data = json.loads(self.rfile.read(length) or b"{}")
        except Exception:
            data = {}
        prompt = (data.get("message") or "").strip()
        if not prompt:
            return self._json(200, {"reply": "(空消息)"})

        session_id = (data.get("session_id") or "default").strip() or "default"

        try:
            reply = _chat(prompt, session_id)
        except Exception as e:
            reply = f"(SDK 调用失败: {e})"

        # 记入会话上下文（供下一轮拼接历史）
        _session_append(session_id, "user", prompt)
        _session_append(session_id, "assistant", reply)

        # 记忆流转：短期 → 中期 → 长期（自动）
        try:
            _flow_after_chat(session_id, prompt, reply)
        except Exception:
            pass

        # 异步写入记忆（不阻塞回复）
        threading.Thread(
            target=_remember,
            args=([{"role": "user", "content": prompt},
                   {"role": "assistant", "content": reply}],),
            daemon=True,
        ).start()

        self._json(200, {"reply": reply})

    def do_OPTIONS(self):
        # 明确拒绝跨域预检：浏览器跨站发 JSON POST 会先 OPTIONS，直接 403 防 CSRF
        self._send(403, b"forbidden", "text/plain; charset=utf-8")

    def log_message(self, fmt, *args):
        print(f"[webchat] {self.address_string()} {fmt % args}", flush=True)


def _log_reader_loop():
    """后台线程：定期扫描 conversation.log，把动作类事件写入长期记忆。"""
    import time
    while True:
        try:
            events, more = log_reader.scan_events(top_n=10)
            if events:
                store = _get_mem0()
                if store is not None:
                    for e in events:
                        store.add([{"role": "user", "content": e["text"]}])
                    print(f"[log_reader] 已从日志写入 {len(events)} 条记忆")
        except Exception as e:
            print(f"[log_reader] 扫描异常: {e}")
        # 定期快照裁剪（约每 30 轮 ≈ 90 分钟）：治语义重复膨胀
        _rounds = globals().get("_log_reader_rounds", 0) + 1
        globals()["_log_reader_rounds"] = _rounds
        if _rounds % 30 == 0:
            try:
                store = _get_mem0()
                if store is not None:
                    store.dedupe_categories()
            except Exception as e:
                print(f"[log_reader] 快照裁剪异常: {e}")
        time.sleep(180)


def _dump_modules(signum, frame):
    """调试: SIGUSR1 时把已加载模块写盘（分析运行时依赖用）。"""
    import signal as _sig
    try:
        with open("/tmp/webchat_modules_dump.txt", "w", encoding="utf-8") as f:
            f.write("\n".join(sorted(sys.modules.keys())))
        print("[debug] 模块快照已写 /tmp/webchat_modules_dump.txt", flush=True)
    except Exception as e:
        print(f"[debug] dump 失败: {e}", flush=True)


if __name__ == "__main__":
    import signal as _sig2
    _sig2.signal(_sig2.SIGUSR1, _dump_modules)
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
    print(f"webchat（记忆增强 + 系统工具）已启动: http://{WEBCHAT_HOST}:{port}", flush=True)
    print(f"安全配置: host={WEBCHAT_HOST} token=" + ("已启用" if WEBCHAT_TOKEN else "未启用(仅本机绑定)") + " 禁用网页端工具={" + ",".join(sorted(WEB_DISALLOWED_TOOLS)) + "}", flush=True)
    print(f"记忆模式: {'无记忆(--no-memory)' if _NO_MEMORY else '启用(mem0 持久化)'}", flush=True)
    threading.Thread(target=_log_reader_loop, daemon=True).start()
    ThreadingHTTPServer((WEBCHAT_HOST, port), Handler).serve_forever()
