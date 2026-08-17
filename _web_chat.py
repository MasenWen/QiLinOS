#!/usr/bin/env python3
"""极简 AI 网页聊天 — 零 pip 依赖。

用 Python 标准库 http.server 起一个网页，浏览器打开即可与服务器上的
麒麟 AI SDK（ai_text / libkysdk-genai-nlp）对话，无需命令行。

运行:  python3 _web_chat.py [端口]    (默认 8080)
"""
import json
import os
import re
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from src.sdk import ai_text  # noqa: E402

HTML = """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AI 聊天</title>
<style>
  * { box-sizing: border-box; }
  html, body { height: 100%; }
  body { margin: 0; font-family: -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif;
         background: #f5f6f8; display: flex; flex-direction: column; }
  header { background: #1f2937; color: #fff; padding: 14px 20px; font-size: 16px;
           font-weight: 600; display: flex; align-items: center; gap: 9px; }
  header .dot { width: 9px; height: 9px; border-radius: 50%; background: #22c55e; box-shadow: 0 0 6px #22c55e; }
  header .sub { font-weight: 400; font-size: 12px; color: #9ca3af; }
  #messages { flex: 1; overflow-y: auto; padding: 22px; display: flex; flex-direction: column; gap: 12px; }
  .msg { max-width: 74%; padding: 10px 14px; border-radius: 13px; line-height: 1.65;
         white-space: pre-wrap; word-break: break-word; font-size: 15px; }
  .user { align-self: flex-end; background: #2563eb; color: #fff; border-bottom-right-radius: 4px; }
  .assistant { align-self: flex-start; background: #fff; color: #1f2937; border: 1px solid #e5e7eb;
               border-bottom-left-radius: 4px; box-shadow: 0 1px 2px rgba(0,0,0,.04); }
  .assistant.thinking { color: #6b7280; font-style: italic; }
  .empty { color: #9ca3af; text-align: center; margin: auto; }
  #inputbar { display: flex; gap: 10px; padding: 14px 20px; background: #fff; border-top: 1px solid #e5e7eb; }
  #input { flex: 1; resize: none; border: 1px solid #d1d5db; border-radius: 10px; padding: 10px 12px;
           font-size: 15px; font-family: inherit; max-height: 160px; }
  #input:focus { outline: none; border-color: #2563eb; box-shadow: 0 0 0 3px rgba(37,99,235,.12); }
  #send { background: #2563eb; color: #fff; border: none; border-radius: 10px; padding: 0 22px;
          font-size: 15px; cursor: pointer; }
  #send:disabled { background: #93c5fd; cursor: not-allowed; }
</style>
</head>
<body>
<header><span class="dot"></span>AI 聊天 <span class="sub">libkysdk-genai-nlp</span></header>
<div id="messages"><div class="empty">输入消息，开始和 AI 对话</div></div>
<div id="inputbar">
  <textarea id="input" rows="1" placeholder="输入消息，Enter 发送，Shift+Enter 换行"></textarea>
  <button id="send">发送</button>
</div>
<script>
  const msgs = document.getElementById('messages');
  const input = document.getElementById('input');
  const send = document.getElementById('send');

  function add(text, cls) {
    const d = document.createElement('div');
    d.className = 'msg ' + cls;
    d.textContent = text;
    msgs.appendChild(d);
    msgs.scrollTop = msgs.scrollHeight;
    return d;
  }

  async function submit() {
    const text = input.value.trim();
    if (!text || send.disabled) return;
    const empty = msgs.querySelector('.empty');
    if (empty) empty.remove();
    add(text, 'user');
    input.value = '';
    input.style.height = 'auto';
    const el = add('思考中…', 'assistant thinking');
    send.disabled = true;
    try {
      const r = await fetch('/api/chat', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({message: text})
      });
      const data = await r.json();
      el.textContent = data.reply || '(无回复)';
      el.classList.remove('thinking');
    } catch (e) {
      el.textContent = '请求失败: ' + e;
      el.classList.remove('thinking');
    } finally {
      send.disabled = false;
      input.focus();
    }
  }

  send.onclick = submit;
  input.addEventListener('keydown', e => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); submit(); }
  });
  input.addEventListener('input', () => {
    input.style.height = 'auto';
    input.style.height = Math.min(input.scrollHeight, 160) + 'px';
  });
</script>
</body>
</html>
"""


def _clean(reply: str) -> str:
    """去掉 ai_text 末尾常见的引用标记，如 [1][2][3] 。"""
    s = (reply or '').strip()
    s = re.sub(r"(?:\[\d+\])+\s*$", "", s)
    return s.strip()


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body: bytes, ctype: str):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            self._send(200, HTML.encode("utf-8"), "text/html; charset=utf-8")
        else:
            self._send(404, b"not found", "text/plain; charset=utf-8")

    def do_POST(self):
        if self.path != "/api/chat":
            return self._send(404, b"not found", "text/plain; charset=utf-8")
        try:
            length = int(self.headers.get("Content-Length") or 0)
            data = json.loads(self.rfile.read(length) or b"{}")
        except Exception:
            data = {}
        prompt = (data.get("message") or "").strip()
        if not prompt:
            return self._send(200, json.dumps({"reply": "(空消息)"}, ensure_ascii=False).encode(), "application/json; charset=utf-8")
        try:
            with ai_text.TextSession() as t:
                reply = t.generate(prompt)
            reply = _clean(reply)
        except Exception as e:
            reply = f"(SDK 调用失败: {e})"
        body = json.dumps({"reply": reply}, ensure_ascii=False).encode("utf-8")
        self._send(200, body, "application/json; charset=utf-8")

    def log_message(self, fmt, *args):
        print(f"[web_chat] {self.address_string()} {fmt % args}", flush=True)


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
    print(f"AI 聊天已启动: http://<服务器IP>:{port}", flush=True)
    HTTPServer(("0.0.0.0", port), Handler).serve_forever()
