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
from collections import OrderedDict
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from src.sdk import ai_text  # noqa: E402
# mem0 惰性初始化：--no-memory 启动时完全不加载（P1-2）
_NO_MEMORY = "--no-memory" in sys.argv
_mem0 = None

def _get_mem0():
    """惰性获取 mem0 单例；--no-memory 模式返回 None。"""
    global _mem0
    if _NO_MEMORY:
        return None
    if _mem0 is None:
        from src.memory.mem0_store import mem0_store
        _mem0 = mem0_store
    return _mem0
from src.toolkit.init_tools import init_all_tools  # noqa: E402
from src.toolkit.base import get_registry, ToolResult, ToolStatus  # noqa: E402
from src.toolkit.executor import ClosedLoopExecutor  # noqa: E402

# ---------- 初始化工具 ----------
init_all_tools()
REGISTRY = get_registry()
EXECUTOR = ClosedLoopExecutor(registry=REGISTRY, max_retries=1)

TOOL_CATALOG = "\n".join(
    f"- {name}: {REGISTRY.get(name).description}"
    for name in REGISTRY.list_all()
)

# ---------- 配置即长期记忆（类似 Codex AGENTS.md）----------
_skill_memory = None


def _get_skill_memory():
    """惰性获取配置记忆（SKILL 持久化到 ~/.nex-agent/skills.json）。"""
    global _skill_memory
    if _skill_memory is None:
        from src.memory_engine.skill_memory import SkillMemory
        _skill_memory = SkillMemory()
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
        # 写入短期（用户消息 + AI 回复）
        overflow += flow.add_short(prompt, session_id)
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
SESSIONS: "OrderedDict[str, list]" = OrderedDict()
_sessions_lock = threading.Lock()


def _session_history(session_id: str):
    with _sessions_lock:
        return list(SESSIONS.get(session_id, []))


def _session_append(session_id: str, role: str, content: str):
    with _sessions_lock:
        hist = SESSIONS.setdefault(session_id, [])
        hist.append({"role": role, "content": (content or "")[:MAX_TURN_CHARS]})
        if len(hist) > MAX_HISTORY_TURNS * 2:
            del hist[: len(hist) - MAX_HISTORY_TURNS * 2]
        SESSIONS.move_to_end(session_id)
        while len(SESSIONS) > MAX_SESSIONS:
            SESSIONS.popitem(last=False)

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
    --bg: #0a0d14;
    --surface: rgba(255,255,255,.045);
    --surface-2: rgba(255,255,255,.08);
    --border: rgba(255,255,255,.09);
    --text: #e7e9ee;
    --muted: #9aa3b2;
    --accent: #6366f1;
    --accent-2: #8b5cf6;
    --ok: #22c55e;
  }
  * { box-sizing: border-box; }
  html, body { height: 100%; }
  body {
    margin: 0;
    font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", "Segoe UI",
                 "Microsoft YaHei", sans-serif;
    color: var(--text);
    background:
      radial-gradient(1200px 600px at 15% -10%, rgba(99,102,241,.22), transparent 60%),
      radial-gradient(1000px 500px at 100% 0%, rgba(139,92,246,.18), transparent 55%),
      var(--bg);
    display: flex;
    flex-direction: column;
  }
  header {
    position: sticky; top: 0; z-index: 10;
    display: flex; align-items: center; gap: 10px;
    padding: 13px 22px;
    background: rgba(10,13,20,.72);
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
    background: linear-gradient(135deg, #2563eb, #7c3aed);
    color: #fff; border-bottom-right-radius: 5px;
    box-shadow: 0 6px 20px -8px rgba(99,102,241,.55);
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
             font-size: .88em; background: rgba(255,255,255,.09);
             padding: .12em .42em; border-radius: 5px; }
  .md pre { background: rgba(0,0,0,.35); border: 1px solid var(--border);
            padding: 12px 14px; border-radius: 10px; overflow-x: auto; }
  .md pre code { background: none; padding: 0; }
  .md blockquote { margin: .6em 0; padding: .2em 1em; color: var(--muted);
                   border-left: 3px solid var(--accent); }
  .md a { color: #93c5fd; }
  .md table { border-collapse: collapse; margin: .7em 0; font-size: .92em; }
  .md th,.md td { border: 1px solid var(--border); padding: 6px 11px; }
  .md th { background: var(--surface-2); }
  .cursor { display: inline-block; width: 8px; height: 1.05em; margin-left: 2px;
            background: var(--accent-2); vertical-align: -2px;
            animation: blink .9s steps(2, start) infinite; }
  @keyframes blink { to { visibility: hidden; } }
  .layout { display: flex; height: 100vh; }
  .sidebar { width: 230px; min-width: 230px; background: rgba(10,13,20,.9);
             border-right: 1px solid var(--border); display: flex; flex-direction: column; }
  .sidebar .brand { padding: 14px 16px; border-bottom: 1px solid var(--border); }
  .sidebar .newchat { margin: 10px 12px; padding: 8px; border: 1px solid var(--accent);
             border-radius: 8px; background: rgba(99,102,241,.12); color: var(--text);
             cursor: pointer; font-size: 13px; text-align: center; }
  .sidebar .newchat:hover { background: rgba(99,102,241,.25); }
  .sess-list { flex: 1; overflow-y: auto; padding: 4px; }
  .sess-item { padding: 8px 10px; margin: 2px 4px; border-radius: 6px; font-size: 12.5px;
             color: var(--muted); cursor: pointer; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .sess-item:hover, .sess-item.active { background: var(--surface-2); color: var(--text); }
  .main { flex: 1; display: flex; flex-direction: column; min-width: 0; }
  .panel { width: 240px; min-width: 240px; background: rgba(10,13,20,.9);
             border-left: 1px solid var(--border); overflow-y: auto; padding: 10px; }
  .panel h3 { font-size: 12px; color: var(--muted); margin: 8px 0 6px; letter-spacing: .5px; }
  .mem-item { font-size: 12px; color: var(--text); padding: 6px 8px; background: var(--surface);
             border: 1px solid var(--border); border-radius: 6px; margin-bottom: 6px; line-height: 1.5; }
  .log-item { font-size: 11.5px; padding: 5px 8px; border-radius: 5px; margin-bottom: 5px;
             background: var(--surface); border: 1px solid var(--border); }
  .log-item .tool { color: var(--accent-2); }
  .log-item.ok { border-left: 3px solid var(--ok); }
  .log-item.err { border-left: 3px solid #ef4444; }
  footer {
    position: sticky; bottom: 0;
    background: rgba(10,13,20,.72);
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
                   box-shadow: 0 0 0 3px rgba(99,102,241,.16); }
  button#send {
    border: none; border-radius: 13px; padding: 12px 22px; font-size: 14.5px;
    font-weight: 600; color: #fff; cursor: pointer; flex: none;
    background: linear-gradient(135deg, #6366f1, #8b5cf6);
    box-shadow: 0 8px 22px -10px rgba(99,102,241,.9); transition: .18s;
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
    <h3>🧠 记忆</h3>
    <div id="memPanel"><div class="mem-item">（加载中…）</div></div>
    <h3>⚙️ 配置（长期记忆）</h3>
    <div id="skillInput">
      <input id="skillName" placeholder="配置名（如：时区规则）" style="width:100%;margin-bottom:5px;padding:6px;border:1px solid var(--border);background:var(--surface);color:var(--text);border-radius:6px;font-size:12px;">
      <textarea id="skillContent" rows="2" placeholder="配置内容 / 常用提示词…" style="width:100%;margin-bottom:5px;padding:6px;border:1px solid var(--border);background:var(--surface);color:var(--text);border-radius:6px;font-size:12px;resize:vertical;"></textarea>
      <button id="skillAdd" class="icon-btn" style="width:100%;padding:7px;">＋ 存入长期记忆</button>
    </div>
    <div id="skillPanel" style="margin-top:8px;"></div>
    <h3>🔧 工具调用</h3>
    <div id="toolPanel"><div class="log-item">（暂无）</div></div>
  </aside>
</div>

<script>
const msgs = document.getElementById('messages');
const empty = document.getElementById('empty');
const input = document.getElementById('input');
const send = document.getElementById('send');
const SKEY = 'aichat_session_v1';
// history 按会话隔离（新会话不再显示旧会话消息）
const histKey = (sid) => `aichat_history_v1_${sid || sessionId}`;
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
  }
  row.appendChild(who);
  row.appendChild(bubble);
  msgs.appendChild(row);
  scrollBottom();
  return row;
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
    const r = await fetch('/api/chat', {
      method: 'POST',
      headers: apiHeaders,
      body: JSON.stringify({ message: text, session_id: sessionId })
    });
    const data = await r.json();
    cursor.remove();
    const reply = data.reply || '(无回复)';
    await streamInto(md, reply);
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
  sessionId = sid;
  localStorage.setItem(SKEY, sid);
  history = [];
  try { history = JSON.parse(localStorage.getItem(histKey(sid)) || '[]'); } catch (e) { history = []; }
  renderHistory();
  refreshSessions();
}
async function refreshSessions() {
  try {
    const r = await fetch('/api/sessions');
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
        <span style="display:none;margin-left:4px;color:var(--accent-2);cursor:pointer;" class="renameBtn">✎</span>`;
      el.style.display = 'flex'; el.style.alignItems = 'center';
      el.onmouseenter = () => { el.querySelector('.renameBtn').style.display = 'inline'; };
      el.onmouseleave = () => { el.querySelector('.renameBtn').style.display = 'none'; };
      el.querySelector('.renameBtn').onclick = (e) => { e.stopPropagation(); renameSession(s.session_id, el); };
      list.appendChild(el);
    });
  } catch (e) {}
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
      fetch('/api/memories').then(r => r.json()),
      fetch('/api/tool_logs').then(r => r.json()),
    ]);
    const mp = document.getElementById('memPanel');
    mp.innerHTML = (m.memories && m.memories.length)
      ? m.memories.map(x => `<div class="mem-item">${x}</div>`).join('')
      : '<div class="mem-item">（暂无记忆）</div>';
    const tp = document.getElementById('toolPanel');
    tp.innerHTML = (t.logs && t.logs.length)
      ? t.logs.slice().reverse().map(l =>
          `<div class="log-item ${l.status === 'verified' || l.status === 'success' ? 'ok' : 'err'}">
             <span class="tool">${l.tool}</span> · ${l.status} · ${l.duration_ms}ms
             ${l.error ? `<br><span style="color:#f87171">${l.error.slice(0, 60)}</span>` : ''}
           </div>`).join('')
      : '<div class="log-item">（暂无）</div>';
  } catch (e) {}
}
// ---- 配置面板（网页输入 → 长期记忆）----
async function refreshSkills() {
  try {
    const r = await fetch('/api/skills');
    const d = await r.json();
    const sp = document.getElementById('skillPanel');
    sp.innerHTML = (d.skills && d.skills.length)
      ? d.skills.map(s =>
          `<div class="mem-item" style="position:relative;">
             <b>${s.name}</b> <span style="color:var(--muted)">v${s.version}</span>
             ${(s.tags||[]).map(t=>`<span style="font-size:10px;background:var(--accent);padding:1px 5px;border-radius:4px;margin-left:3px;">${t}</span>`).join('')}
             <div style="font-size:11px;color:var(--muted);margin-top:3px;">${s.content.slice(0,60)}</div>
             <span style="position:absolute;top:4px;right:6px;cursor:pointer;color:#ef4444;" onclick="deleteSkill('${s.name}')">✕</span>
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
  sessionId = Math.random().toString(36).slice(2) + Date.now().toString(36);
  localStorage.setItem(SKEY, sessionId);
  history = [];
  renderHistory();          // 清空页面（不整页刷新）
  refreshSessions();
  input.focus();
};
refreshSessions();
setInterval(refreshPanels, 4000);
send.onclick = submit;
input.addEventListener('keydown', e => {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); submit(); }
});
input.addEventListener('input', () => {
  input.style.height = 'auto';
  input.style.height = Math.min(input.scrollHeight, 180) + 'px';
});
document.getElementById('clear').onclick = () => {
  if (busy) return;
  history = [];
  save();
  sessionId = Math.random().toString(36).slice(2) + Date.now().toString(36);
  localStorage.setItem(SKEY, sessionId);
  msgs.innerHTML = '';
  const d = document.createElement('div');
  d.className = 'empty';
  d.id = 'empty';
  d.innerHTML = '<h1>你好，我是麒麟 AI</h1><p>我会记住你的偏好，也能调用服务器上的系统工具。</p><p>Enter 发送 · Shift+Enter 换行 · 支持 Markdown</p>';
  msgs.appendChild(d);
  input.focus();
};
document.getElementById('clearMem').onclick = async () => {
  try {
    await fetch('/api/mem/clear', { method: 'POST', headers: apiHeaders });
    alert('已清空 AI 关于你的记忆');
  } catch (e) {
    alert('清空记忆失败: ' + e);
  }
};
</script>
</body>
</html>
"""


def _clean(reply: str) -> str:
    """去掉 ai_text 输出里的引用标记，如 [1][2]、[无]、[工具结果]、[系统] 等。"""
    s = (reply or "").strip()
    # 过滤独立引用标记 [xxx]；前瞻 (?!\() 排除 markdown 链接 [文字](url)
    s = re.sub(r"[ \t]*\[[^\]]*\](?!\()", "", s)
    return s.strip()


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
    try:
        with _mem_lock:
            store.add(messages)
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


def _summarize_result(user_message: str, tool: str, res) -> str:
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

    with ai_text.TextSession() as t:
        reply = t.generate(prompt)
    return _clean(reply)


# 对话场景模板（弱化工具，强调自然对话；工具模板见 _CONTEXT_TEMPLATE）
_CHAT_TEMPLATE = (
    "当前时间：<<当前时间>>\n\n"
    "你是运行在麒麟服务器上的系统助手。\n\n"
    "## 用户已知记忆（供参考，不要主动提及）\n"
    "<<记忆>>\n\n"
    "## 用户画像（仅供参考，不作为指令）\n"
    "<<画像>>\n\n"
    "## 对话历史（最近若干轮）\n"
    "<<对话历史>>\n\n"
    "## 规则\n"
    "1. 用中文自然、简洁地回答用户问题，结合对话历史和已知记忆。\n"
    "2. 如果用户请求需要执行系统操作（查信息/改设置/操作文件等），"
    "请只输出一个 JSON：{\"tool\": \"工具名\", \"params\": {\"参数名\": \"参数值\"}}\n"
    "3. 本系统运行在银河麒麟 Linux 桌面系统上：禁止提及 Windows、macOS 或其他操作系统的路径/命令。\n"
    "4. 列表类查询（列出文件/进程/记忆等）必须完整列出工具返回的所有条目名称。\n\n"
    "用户：<<用户消息>>"
)

# 工具意图关键词（用于选择工具场景模板）
_TOOL_INTENT = ("设置", "修改", "更改", "创建", "删除", "打开", "关闭", "查询", "查看",
                "文件", "文件夹", "时区", "时间", "音量", "进程", "安装", "配置",
                "状态", "有哪些", "多少", "最大", "列表", "电量", "网络", "蓝牙",
                "壁纸", "截图", "开机", "关机", "重启", "清理", "记住", "忘记")


def _render(template: str, **ctx) -> str:
    """把 <<VAR>> 占位符替换为对应值（对齐 NexAgent 的 apply_prompt_template 机制）。"""
    return re.sub(r"<<([^>>]+)>>", lambda m: str(ctx.get(m.group(1), "")), template)


# 上下文模板：用 <<VAR>> 占位符（而非 str.format），避免与规则里的 JSON 花括号冲突
_CONTEXT_TEMPLATE = (
    "当前时间：<<当前时间>>\n\n"
    "你是运行在麒麟服务器上的系统助手。\n\n"
    "## 可用系统工具\n"
    "<<工具目录>>\n\n"
    "## 用户已知记忆（供参考，不要主动提及）\n"
    "<<记忆>>\n\n"
    "## 对话历史（最近若干轮）\n"
    "<<对话历史>>\n\n"
    "## 规则\n"
    "1. 如果用户请求需要执行系统操作（改时区、查硬件/进程/电池、建文件夹/文件等），"
    "且上面有对应工具，请**只输出**一个 JSON，不要输出其它内容：\n"
    '{"tool": "工具名", "params": {"参数名": "参数值"}}\n'
    "params 必须把工具所需的全部参数填全（例如 timezone 工具必须带 timezone 参数，"
    "值为 'Asia/Shanghai' 这类合法时区）；若用户没给出必要参数，"
    "不要输出 JSON，用中文反问用户补齐。\n"
    "2. 若用户请求是具体的系统操作（建文件夹、列目录、查看文件、复制/移动等），"
    "但上面没有对应工具，请改用 shell 工具执行一条白名单命令，仍然**只输出** JSON：\n"
    '{"tool": "shell", "params": {"cmd": "白名单命令"}}\n'
    "命令只能用 shell 工具描述里列出的白名单命令，路径写完整（如 ~/桌面/xxx）。\n"
    "3. 否则，结合对话历史，用中文简洁、自然地回答用户问题。\n"
    "4. 本系统运行在银河麒麟 Linux 桌面系统上：禁止提及 Windows、macOS 或其他操作系统的路径/命令。\n"
    "5. 列表类查询（列出文件/进程/记忆等）必须完整列出工具返回的所有条目名称，不得省略或只摘录少数。\n\n"
    "用户：<<用户消息>>"
)


def _build_context(message: str, session_id: str) -> str:
    """统一拼接上下文：分场景模板 + 工具目录 + 记忆 + 画像 + 对话历史 + 当前消息。"""
    memory = _retrieve_memory(message)
    profile = _db_user_profile()  # DB 用户画像（借鉴 AgentProject）
    history = _session_history(session_id)
    hist_block = "\n".join(
        f"{'用户' if h['role'] == 'user' else '助手'}：{h['content']}"
        for h in history
    ) or "（暂无）"

    # 分场景模板：含工具意图 → 工具模板；否则对话模板
    is_tool = any(kw in message for kw in _TOOL_INTENT)
    template = _CONTEXT_TEMPLATE if is_tool else _CHAT_TEMPLATE

    ctx = dict(
        当前时间=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        工具目录=TOOL_CATALOG,
        记忆=memory or "（暂无）",
        画像=profile or "（暂无）",
        对话历史=hist_block,
        用户消息=message,
    )
    return _render(template, **ctx)


def _chat(message: str, session_id: str = "default"):
    """统一上下文 → 让 AI 编排 → 执行工具 / 直接回答。"""
    prompt = _build_context(message, session_id)

    with ai_text.TextSession() as t:
        raw = t.generate(prompt)
    raw = _clean(raw)

    # 尝试解析工具编排 JSON
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if m:
        try:
            plan = json.loads(m.group(0))
            tool = plan.get("tool")
            if tool:
                if tool not in REGISTRY.list_all():
                    # AI 编造了不存在的工具：不返回原始 JSON，给友好提示
                    return (f"我无法执行「{tool}」这个操作，它不在我可用的工具列表中。"
                            f"请换个说法描述您的需求，例如：系统 CPU 占用情况、当前内存使用、磁盘空间等。")
                params = plan.get("params") or {}
                step = plan.get("step")
                total_steps = plan.get("total_steps") or plan.get("all_step")
                res = _run_tool(tool, params)
                try:
                    reply = _summarize_result(message, tool, res)
                    # 步骤化编排：复杂任务回显进度（借鉴 AgentProject step/all_step）
                    if step is not None and total_steps:
                        reply = f"（步骤 {step}/{total_steps}）" + reply
                    return reply
                except Exception as e:
                    print(f"[tool] 结果二次生成失败，回退原始渲染: {e}", flush=True)
                    return _render_tool_result(res)
        except Exception as e:
            print(f"[tool] 编排执行失败: {e}", flush=True)

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
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self._send(code, body, "application/json; charset=utf-8")

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            self._send(200, HTML.encode("utf-8"), "text/html; charset=utf-8")
        elif self.path == "/api/sessions":
            with _sessions_lock:
                sess = [
                    {"session_id": sid, "turns": len(hist),
                     "preview": (hist[-1]["content"][:24] if hist else "")}
                    for sid, hist in SESSIONS.items()
                ]
            self._json(200, {"sessions": sess})
        elif self.path == "/api/tool_logs":
            self._json(200, {"logs": list(_TOOL_LOGS)})
        elif self.path == "/api/skills":
            sm = _get_skill_memory()
            items = [{"name": s.name, "content": s.content, "tags": s.tags,
                      "version": s.version, "condition": s.condition}
                     for s in sm.list_skills()]
            self._json(200, {"skills": items, "conflicts": len(sm.conflicts())})
        elif self.path == "/api/memories":
            store = _get_mem0()
            items = []
            if store is not None:
                try:
                    for it in store.search("", top_k=5):
                        items.append(str(it.get("memory", ""))[:80])
                except Exception:
                    pass
            self._json(200, {"memories": items})
        else:
            self._send(404, b"not found", "text/plain; charset=utf-8")

    def do_POST(self):
        if not self._auth_ok():
            return self._json(403, {"error": "forbidden: 缺少或错误的 X-Api-Token"})
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


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
    print(f"webchat（记忆增强 + 系统工具）已启动: http://{WEBCHAT_HOST}:{port}", flush=True)
    print(f"安全配置: host={WEBCHAT_HOST} token=" + ("已启用" if WEBCHAT_TOKEN else "未启用(仅本机绑定)") + " 禁用网页端工具={" + ",".join(sorted(WEB_DISALLOWED_TOOLS)) + "}", flush=True)
    print(f"记忆模式: {'无记忆(--no-memory)' if _NO_MEMORY else '启用(mem0 持久化)'}", flush=True)
    ThreadingHTTPServer((WEBCHAT_HOST, port), Handler).serve_forever()
