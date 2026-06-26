import os
import json
import asyncio
import threading
import time
import uuid
from contextlib import AsyncExitStack
from urllib.parse import quote
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from openai import OpenAI
from dotenv import load_dotenv
from src.utils.db_manager import DBManager


# =========================================================
# 事件总线
# =========================================================
class EventBus:
    """事件总线：用于 SSE 推送"""

    def __init__(self):
        from queue import Queue
        self.Queue = Queue
        self.subscribers: dict[int, list] = {}

    def subscribe(self, session_id: int):
        q = self.Queue()
        self.subscribers.setdefault(session_id, []).append(q)

        def unsubscribe():
            arr = self.subscribers.get(session_id, [])
            if q in arr:
                arr.remove(q)

        return q, unsubscribe

    def publish(self, session_id: int, event: dict):
        arr = list(self.subscribers.get(session_id, []))
        for q in arr:
            try:
                if hasattr(q, "put_nowait"):
                    q.put_nowait(event)
                else:
                    q.put(event, block=False)
            except Exception:
                pass


# =========================================================
# MCP Client 主类
# =========================================================
class MCPClient:
    """核心客户端：负责服务器管理、日志记录、LLM交互、会话与文件绑定"""

    def __init__(self, event_bus: EventBus, loop=None):
        load_dotenv()
        self.bus = event_bus
        self.db = DBManager()

        self.API_KEY = os.getenv("DS_API_KEY")
        self.BASE_URL = os.getenv("DS_API_BASE")
        self.MODEL = os.getenv("DS_API_MODEL")
        if not all([self.API_KEY, self.BASE_URL, self.MODEL]):
            raise RuntimeError("请设置 DS_API_KEY、DS_API_BASE、DS_API_MODEL")

        self.openai = OpenAI(api_key=self.API_KEY, base_url=self.BASE_URL)

        # 状态容器
        self.sessions: dict[str, ClientSession] = {}
        self.tasks: dict[str, asyncio.Task] = {}
        self.stop_flags: dict[str, asyncio.Event] = {}
        self.preserve_status_on_close: dict[str, bool] = {}

        # 异步事件循环（由 app 注入）
        self.loop = loop

    # ========== Loop 注入 / 执行 ==========
    def set_event_loop(self, loop):
        self.loop = loop

    def _submit(self, coro):
        """统一提交协程到指定事件循环"""
        if not self.loop:
            raise RuntimeError("MCPClient.loop 未设置，请在 app.py 注入事件循环。")
        return asyncio.run_coroutine_threadsafe(coro, self.loop)

    # =========================================================
    # 🧩 会话管理
    # =========================================================
    def list_sessions(self):
        return self.db.list_sessions()

    def create_session(self, name: str):
        return self.db.create_session(name)

    def delete_session(self, sid: int):
        self.db.delete_session(sid)

    def rename_session(self, sid: int, name: str):
        self.db.rename_session(sid, name)

    # =========================================================
    # 💬 聊天与日志管理
    # =========================================================
    def list_chat_logs(self, sid: int):
        return self.db.list_chat_logs(sid)

    def list_call_logs(self, sid: int, limit: int = 100):
        return self.db.list_call_logs(sid, limit)

    def log_chat(self, sid: int, role: str, content: str, server_name=None):
        self.db.save_chat_log(role, content, server_name, sid)
        self.bus.publish(sid, {"type": "chat", "payload": {"role": role, "content": content}})

    def log_call(self, sid, action, detail, *, server_name=None, correlation_id=None, level="info"):
        self.db.add_call_log(action, detail, session_id=sid, correlation_id=correlation_id,
                             server_name=server_name, level=level)
        if sid:
            self.bus.publish(sid, {"type": "log", "payload": {"action": action, "detail": detail}})

    # =========================================================
    # ⚙️ 服务器管理
    # =========================================================
    def list_servers(self):
        return self.db.list_servers()

    def get_server(self, name: str):
        return self.db.get_server(name)

    def rename_server(self, old_name: str, new_name: str):
        self.db.rename_server(old_name, new_name)

    def sync_server_record(self, name, filename, path, desc=""):
        return self.db.add_or_update_server(name, filename, path, desc)

    async def connect_to_server(self, name, path):
        if name in self.sessions:
            self.log_call(None, "connect_skip", f"⚠️ {name} 已连接，跳过")
            return

        stop_event = asyncio.Event()
        self.stop_flags[name] = stop_event

        async def server_task():
            params = StdioServerParameters(
                command="python" if path.endswith(".py") else "node",
                args=[path],
            )
            async with AsyncExitStack() as stack:
                try:
                    stdio, write = await stack.enter_async_context(stdio_client(params))
                    sess = await stack.enter_async_context(ClientSession(stdio, write))
                    await sess.initialize()
                    self.sessions[name] = sess
                    self.db.update_status(name, "running")
                    self.log_call(None, "connect", f"✅ 已连接服务器: {name}")
                    await stop_event.wait()
                finally:
                    await stack.aclose()
                    self.sessions.pop(name, None)
                    self.stop_flags.pop(name, None)

                    preserve = self.preserve_status_on_close.pop(name, False)
                    if not preserve:
                        self.db.update_status(name, "stopped")

                    self.log_call(None, "disconnect", f"❎ 已断开服务器: {name}")

        task = asyncio.create_task(server_task())
        self.tasks[name] = task

    async def disconnect_server(self, name):
        flag = self.stop_flags.get(name)
        if not flag:
            self.log_call(None, "disconnect_fail", f"⚠️ {name} 未连接")
            return
        flag.set()
        self.log_call(None, "disconnect_request", f"🔌 请求断开 {name}")

    def toggle_server(self, name: str):
        """切换服务器运行状态"""
        server = self.db.get_server(name)
        if not server:
            raise ValueError(f"未找到服务器 {name}")

        if server["status"] == "running":
            self._submit(self.disconnect_server(name))
            self.db.update_status(name, "stopped")
            return "stopped"
        else:
            self._submit(self.connect_to_server(name, server["path"]))
            self.db.update_status(name, "running")
            return "running"

    async def get_server_tools(self, name: str):
        if name not in self.sessions:
            return []
        sess = self.sessions[name]
        tools = await sess.list_tools()
        return [
            {"name": t.name, "description": t.description, "inputSchema": getattr(t, "inputSchema", None)}
            for t in tools.tools
        ]

    # =========================================================
    # 📂 文件上传
    # =========================================================
    def handle_file_upload(self, session_id: int, original_filename: str, stored_filename: str, path: str, size: int):
        self.db.save_uploaded_file(session_id, stored_filename, path, size)
        href = f"/api/download/{quote(stored_filename)}"
        size_str = f"{size / 1024:.1f} KB"
        content = f"📎 [**{original_filename}**]({href}) · {size_str}"
        self.db.save_chat_log("user_file", content, None, session_id)
        self.bus.publish(session_id, {"event": "file_uploaded", "filename": original_filename,
                                      "stored": stored_filename, "path": path, "size": size})

    def list_uploaded_files(self, sid: int):
        return self.db.list_uploaded_files(sid)

    # =========================================================
    # 🧹 清理
    # =========================================================
    async def cleanup(self):
        # 给每个正在跑的 server 标记：这次关闭是“可恢复”的
        for name, flag in list(self.stop_flags.items()):
            self.preserve_status_on_close[name] = True  # ← 新增：告诉 finally 不要把状态写成 stopped
            flag.set()  # 触发任务退出（server_task 的 finally 会跑）
        await asyncio.sleep(0.2)
        self.log_call(None, "cleanup", "🧹 已触发断开信号（保留状态，便于下次恢复）")

    # =========================================================
    # 🧩 工具调用 / LLM 逻辑
    # =========================================================
    async def _gather_tools(self):
        defs = []
        for nm, sess in self.sessions.items():
            try:
                resp = await sess.list_tools()
                for t in resp.tools:
                    defs.append({
                        "type": "function",
                        "function": {
                            "name": t.name,
                            "description": f"[{nm}] {t.description}",
                            "parameters": getattr(t, "inputSchema", {"type": "object"})
                        },
                        "server_name": nm
                    })
            except Exception as e:
                self.log_call(None, "tool_list_fail", f"⚠️ 工具列出失败: {nm} → {e}", server_name=nm, level="warn")
        return defs

    async def process_query(self, query: str, session_id: int, correlation_id: str | None = None):
        correlation_id = correlation_id or uuid.uuid4().hex
        if not self.sessions:
            msg = "❌ 当前没有连接任何服务器，请先连接后重试。"
            self.log_call(session_id, "query_fail", msg, correlation_id=correlation_id, level="warn")
            self.log_chat(session_id, "user", query)
            self.log_chat(session_id, "assistant", msg)
            return msg, correlation_id

        self.log_chat(session_id, "user", query)
        self.log_call(session_id, "user_query", f"🧠 用户提问: {query}", correlation_id=correlation_id)

        messages = [{"role": "user", "content": query}]
        all_tools = await self._gather_tools()
        openai_tools = [{"type": "function", "function": t["function"]} for t in all_tools]

        try:
            resp = await asyncio.to_thread(
                lambda: self.openai.chat.completions.create(
                    model=self.MODEL, messages=messages, tools=openai_tools, max_tokens=1000
                )
            )
            choice = resp.choices[0].message
            self.log_call(session_id, "model_call", "✅ 模型初次调用成功", correlation_id=correlation_id)
        except Exception as e:
            msg = f"❌ 模型调用失败: {e}"
            self.log_call(session_id, "model_fail", msg, correlation_id=correlation_id, level="error")
            self.log_chat(session_id, "assistant", "模型调用失败，请重试。")
            return "模型调用失败，请重试。", correlation_id

        if not getattr(choice, "tool_calls", None):
            content = (choice.content or "").strip()
            self.log_chat(session_id, "assistant", content)
            self.log_call(session_id, "assistant_reply", f"🤖 回复: {content}", correlation_id=correlation_id)
            return content, correlation_id

        call = choice.tool_calls[0]
        tool_name = call.function.name
        args = json.loads(call.function.arguments or "{}")

        provider, sess = None, None
        for nm, s in self.sessions.items():
            resp = await s.list_tools()
            if tool_name in [t.name for t in resp.tools]:
                provider, sess = nm, s
                break
        if not sess:
            msg = f"❌ 工具 {tool_name} 未找到"
            self.log_call(session_id, "tool_missing", msg, correlation_id=correlation_id, level="error")
            self.log_chat(session_id, "assistant", msg)
            return msg, correlation_id

        try:
            raw = await sess.call_tool(tool_name, args)
            output = str(raw.content[0].text if hasattr(raw, "content") else str(raw))
            self.log_call(session_id, "tool_call", f"🧩 {tool_name} args={args}",
                          server_name=f"{provider}", correlation_id=correlation_id)
            self.log_chat(session_id, "mcp_server", output, server_name=f"{provider}-{tool_name}")
        except Exception as e:
            msg = f"❌ 工具调用失败: {e}"
            self.log_call(session_id, "tool_fail", msg, server_name=f"{provider}-{tool_name}",
                          correlation_id=correlation_id, level="error")
            self.log_chat(session_id, "assistant", "工具调用失败，请重试。")
            return "工具调用失败，请重试。", correlation_id

        messages.extend([
            {"role": "assistant", "content": None, "tool_calls": [call.model_dump()]},
            {"role": "tool", "content": output, "tool_call_id": call.id}
        ])
        try:
            def _stream_final():
                pieces: list[str] = []

                stream = self.openai.chat.completions.create(
                    model=self.MODEL,
                    messages=messages,
                    max_tokens=1000,
                    stream=True,
                )

                for chunk in stream:
                    choice = chunk.choices[0]
                    delta = getattr(choice, "delta", None)
                    token = getattr(delta, "content", None) if delta else None
                    if not token:
                        continue

                    pieces.append(token)

                    try:
                        self.bus.publish(
                            session_id,
                            {
                                "type": "chat_stream",
                                "payload": {
                                    "role": "assistant",
                                    "content": "".join(pieces),
                                },
                            },
                        )
                    except Exception:
                        pass

                return "".join(pieces).strip()

            resp_text = await asyncio.to_thread(_stream_final)

            self.log_chat(session_id, "assistant", resp_text)
            self.log_call(session_id, "final_reply", "✅ 模型最终回复", correlation_id=correlation_id)

            return resp_text, correlation_id

        except Exception as e:
            msg = f"❌ 二次调用失败: {e}"
            self.log_call(session_id, "model_final_fail", msg, correlation_id=correlation_id, level="error")
            self.log_chat(session_id, "assistant", "生成最终回答失败，请稍后再试。")
            return "生成最终回答失败，请稍后再试。", correlation_id

    # =========================================================
    # 测试 / 自定义流式输出（不走大模型）
    # =========================================================
    def test_stream_text(self, session_id: int, text: str, delay: float = 0.1):
        """
        在当前 session 上模拟一个助手的流式回复
        （完全不调用 LLM，纯自定义内容）
        """

        def worker():
            pieces = []

            for ch in text:
                pieces.append(ch)

                # 每次把“目前为止的完整内容”推给前端
                self.bus.publish(
                    session_id,
                    {
                        "type": "chat_stream",
                        "payload": {
                            "role": "assistant",
                            "content": "".join(pieces),
                        },
                    },
                )

                # 控制一下速度，看着像在打字
                time.sleep(delay)

            # 结束以后，按正常聊天逻辑落一条完整记录
            self.log_chat(session_id, "assistant", text)

        # 后台线程跑这个 worker，不堵住 Flask 请求
        threading.Thread(target=worker, daemon=True).start()
