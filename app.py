import os
import re
import threading
import asyncio
import json
import logging
from flask import Flask, jsonify, request, render_template, Response, stream_with_context
from mcp_server.client import MCPClient, EventBus
from src.utils.file_process import make_safe_filename
from agent import NexAgent

# from src.utils.msg_process import safe_filename
# ========== Flask 初始化 ==========atp_ry7rwe1o3am3bzma08rcn2gz1jobg6qy
app = Flask(__name__, static_folder='mcp_server/static', template_folder='mcp_server/templates')
logging.getLogger('werkzeug').setLevel(logging.ERROR)

# ========== 初始化核心组件 ==========
event_bus = EventBus()

# 独立异步事件循环
loop = asyncio.new_event_loop()
threading.Thread(target=loop.run_forever, daemon=True).start()

# 注入 loop
mcp_client = MCPClient(event_bus, loop=loop)
nex_agent = NexAgent(event_bus)

# 保险：Flask 每个请求线程绑定 loop
@app.before_request
def bind_event_loop():
    try:
        asyncio.set_event_loop(loop)
    except Exception:
        pass


def run_async(coro):
    return asyncio.run_coroutine_threadsafe(coro, loop).result()


# =====================================================
# 🚀 系统启动前置逻辑
# =====================================================

def sync_servers():
    """同步 server 目录与数据库"""
    server_dir = "./mcp_server/server"
    desc_file = os.path.join(server_dir, "servers_description.json")
    os.makedirs(server_dir, exist_ok=True)

    descriptions = {}
    if os.path.exists(desc_file):
        try:
            with open(desc_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                descriptions = {item["filename"]: item["description"] for item in data}
        except Exception as e:
            print(f"⚠️ 读取 servers_description.json 失败: {e}")

    for fn in os.listdir(server_dir):
        if not fn.endswith((".py", ".js")):
            continue
        name = os.path.splitext(fn)[0]
        path = os.path.join(server_dir, fn)
        desc = descriptions.get(fn, "")
        action = mcp_client.sync_server_record(name, fn, path, desc)
        if action == "inserted":
            print(f"🆕 新增 server 记录：{fn}")
        elif action == "updated":
            print(f"🔄 更新 server 记录：{fn}")


def startup_sync():
    """恢复运行中的服务器"""
    nex_agent.update_session_state()
    servers = mcp_client.list_servers()
    for s in servers:
        if s["status"] == "running":
            path = s["path"]
            if os.path.exists(path):
                try:
                    print(f"🔄 自动重连服务器: {s['name']} ({path})")
                    run_async(mcp_client.connect_to_server(s["name"], path))
                except Exception as e:
                    print(f"⚠️ 无法重连 {s['name']}: {e}")
            else:
                print(f"⚠️ 路径不存在: {path}")


# =====================================================
# 📋 路由定义
# =====================================================

@app.route('/')
def index():
    return render_template('index.html')


# ========== 服务器管理 ==========
@app.route('/api/servers')
def list_servers():
    sync_servers()
    return jsonify({"servers": mcp_client.list_servers()})


@app.route('/api/toggle_server', methods=['POST'])
def toggle_server():
    data = request.get_json() or {}
    name = data.get('name')
    if not name:
        return jsonify({"error": "缺少参数 name"}), 400

    try:
        status = mcp_client.toggle_server(name)
        return jsonify({"status": status})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/servers/<name>/tools')
def get_tools(name):
    try:
        return jsonify({"tools": run_async(mcp_client.get_server_tools(name))})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/rename_server', methods=['POST'])
def rename_server():
    data = request.get_json() or {}
    try:
        mcp_client.rename_server(data.get('old_name'), data.get('new_name'))
        return jsonify({"status": "ok"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ========== 会话管理 ==========
@app.route('/api/sessions', methods=['GET'])
def list_sessions():
    return jsonify({"sessions": mcp_client.list_sessions()})


@app.route('/api/sessions/create', methods=['POST'])
def create_session():
    name = (request.get_json() or {}).get("name", "新会话")
    sid = mcp_client.create_session(name)
    return jsonify({"session_id": sid})


@app.route('/api/sessions/delete', methods=['POST'])
def delete_session():
    sid = (request.get_json() or {}).get("session_id")
    if not sid:
        return jsonify({"error": "缺少 session_id"}), 400
    mcp_client.delete_session(int(sid))
    return jsonify({"status": "ok"})


@app.route('/api/sessions/rename', methods=['POST'])
def rename_session():
    data = request.get_json() or {}
    sid, name = data.get("session_id"), data.get("name")
    if not sid or not name:
        return jsonify({"error": "缺少参数"}), 400
    mcp_client.rename_session(int(sid), name)
    return jsonify({"status": "ok"})


# ========== 聊天接口 ==========
@app.route('/api/chat', methods=['POST'])
def chat():
    data = request.get_json() or {}
    query = (data.get('query') or '').strip()
    session_id = data.get('session_id')
    corr = data.get('correlation_id')

    if not query:
        return jsonify({'error': 'empty query'}), 400
    if not session_id:
        return jsonify({'error': '缺少 session_id'}), 400

    try:
        resp, cid = run_async(nex_agent.process_query(query, int(session_id), corr))
        # resp, cid = run_async(mcp_client.process_query(query, int(session_id), corr))
        return jsonify({'response': resp, 'session_id': session_id, 'correlation_id': cid})
    except Exception as e:
        mcp_client.log_call(int(session_id), "process_query_error", f"{e}", level="error")
        return jsonify({'error': str(e)}), 500


# ========== 文件上传/下载 ==========
import uuid
from werkzeug.utils import secure_filename
from flask import send_from_directory

app.config['MAX_CONTENT_LENGTH'] = 64 * 1024 * 1024  # 64MB
UPLOAD_DIR = "./uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)


@app.route('/api/upload', methods=['POST'])
def upload_file():
    file = request.files.get('file')
    session_id = request.form.get('session_id', type=int)
    if not file or not session_id:
        return jsonify({"error": "缺少文件或 session_id"}), 400

    save_path = os.path.join(UPLOAD_DIR, str(session_id))
    os.makedirs(save_path, exist_ok=True)

    original_filename = file.filename or "unnamed"
    # 核心修复：安全文件名由 “安全化后的主文件名 + 原扩展名/猜测扩展名” 组成
    stored_filename = make_safe_filename(original_filename, file.mimetype, save_path)

    save_path = os.path.join(save_path, stored_filename)
    file.save(save_path)
    size = os.path.getsize(save_path)


    print(file.filename)
    print(stored_filename)
    print(save_path)
    # 传入“原始名 + 存储名”
    nex_agent.handle_file_upload(
        session_id=session_id,
        original_filename=original_filename,  # 聊天展示
        stored_filename=stored_filename,  # 实际文件/下载链接
        path=save_path,
        size=size
    )
    return jsonify({"ok": True})


@app.route('/api/download/<path:filename>', methods=['GET'])
def download_file(filename):
    # 下载按“存储名”访问
    print(filename)
    # safe = safe_filename(filename)
    fp = os.path.join(UPLOAD_DIR, filename)
    if not os.path.exists(fp):
        return jsonify({"error": "文件不存在"}), 404
    return send_from_directory(UPLOAD_DIR, filename, as_attachment=True)


# ========== 历史与日志 ==========
@app.route('/api/chat_history')
def chat_history():
    sid = request.args.get('session_id', type=int)
    if not sid:
        return jsonify({"error": "缺少 session_id"}), 400
    return jsonify({"logs": mcp_client.list_chat_logs(sid)})


@app.route('/api/logs')
def get_logs():
    sid = request.args.get('session_id', type=int)
    limit = request.args.get('limit', default=100, type=int)
    if not sid:
        return jsonify({"error": "缺少 session_id"}), 400
    rows = mcp_client.list_call_logs(sid, limit)
    for r in rows:
        if hasattr(r.get('created_at'), 'strftime'):
            r['created_at'] = r['created_at'].strftime('%Y-%m-%d %H:%M:%S')
    return jsonify({"logs": rows})


# ========== SSE 实时推送 ==========
@app.route('/sse/stream')
def sse_stream():
    sid = request.args.get('session_id', type=int)
    if not sid:
        return "missing session_id", 400
    q, unsubscribe = mcp_client.bus.subscribe(sid)

    def gen():
        try:
            yield "event: heartbeat\ndata: {}\n\n"
            while True:
                evt = q.get()
                yield f"data: {json.dumps(evt, ensure_ascii=False)}\n\n"
        finally:
            unsubscribe()

    return Response(stream_with_context(gen()), mimetype='text/event-stream')


@app.route('/api/session/state', methods=['GET'])
def get_session_state():
    sid = request.args.get('session_id', type=int)
    if not sid:
        return jsonify({"error": "缺少 session_id"}), 400
    return jsonify({"state": mcp_client.db.get_session_state(sid)})


@app.route('/api/session/state', methods=['POST'])
def set_session_state():
    data = request.get_json() or {}
    sid = data.get('session_id')
    state = data.get('state')
    if not sid or not state:
        return jsonify({"error": "参数不完整"}), 400
    
    try:
        if state in ["running", "resumed"]:
            run_async(nex_agent.resume_session_task(int(sid)))
        elif state == "paused":
            run_async(nex_agent.cancel_session_task(int(sid)))
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    
    # mcp_client.db.update_session_state(int(sid), state)
    return jsonify({"status": "ok", "state": state})


@app.route('/api/test_stream', methods=['POST'])
def api_test_stream():
    data = request.get_json() or {}
    sid = data.get('session_id')
    text = data.get('text') or "这是一个 test_stream 的流式测试内容……"

    if not sid:
        return jsonify({"error": "缺少 session_id"}), 400

    try:
        sid = int(sid)
    except ValueError:
        return jsonify({"error": "session_id 必须是整数"}), 400

    # 启动后台“假流式”任务，HTTP 这里立刻返回
    mcp_client.test_stream_text(sid, text)

    return jsonify({"ok": True})


@app.route('/api/test/add_message', methods=['POST'])
def test_add_message():
    """
    测试接口：插入一条聊天消息（可以用于测试 assistant_file）
    """
    try:
        data = request.get_json()
        session_id = data.get('session_id')
        role = data.get('role', 'assistant')
        content = data.get('content')
        server_name = data.get('server_name')

        if not session_id or not content:
            return jsonify({'error': 'Missing session_id or content'}), 400

        session_id = int(session_id)

        # 写入数据库
        mcp_client.db.save_chat_log(
            role=role,
            content=content,
            server_name=server_name,
            session_id=session_id
        )

        # 通知前端刷新（如果用 SSE）
        mcp_client.bus.publish(session_id, {"event": "chat_update", "session_id": session_id})

        return jsonify({'message': f'Test message logged successfully for session {session_id}'}), 200

    except Exception as e:
        print(f"Error in /api/test/add_message: {e}")
        return jsonify({'error': f'Internal Server Error: {str(e)}'}), 500


from werkzeug.utils import secure_filename
from flask import send_from_directory
import uuid

UPLOAD_DIR = "./uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)


@app.route('/api/test/send_file', methods=['POST'])
def test_send_file():
    file = request.files.get('file')
    role = request.form.get('role', 'assistant_file')
    session_id = request.form.get('session_id', type=int)

    if not file or not session_id:
        return jsonify({"error": "缺少文件或 session_id"}), 400

    original_filename = file.filename or "unnamed"
    stored_filename = secure_filename(original_filename)

    if not stored_filename or stored_filename.startswith('.'):
        ext = os.path.splitext(original_filename)[1]
        stored_filename = f"{uuid.uuid4().hex}{ext}"

    save_path = os.path.join(UPLOAD_DIR, stored_filename)
    file.save(save_path)
    size = os.path.getsize(save_path)

    href = f"/api/download/{stored_filename}"
    content = f"📦 [**{original_filename}**]({href}) · {size / 1024:.1f} KB"

    mcp_client.db.save_chat_log(role, content, None, session_id)

    mcp_client.bus.publish(session_id, {
        "event": "file_uploaded",
        "role": role,
        "filename": original_filename,
        "path": save_path,
        "size": size
    })

    return jsonify({
        "ok": True,
        "role": role,
        "filename": original_filename,
        "stored": stored_filename,
        "size": size
    })


# =====================================================
# 🏁 应用启动入口
# =====================================================
if __name__ == '__main__':
    try:
        print("🚀 NexAgent 基于意图识别与动态规划的系统操作多智能体已启动：http://127.0.0.1:50056")
        sync_servers()
        startup_sync()
        app.run(debug=False, host='0.0.0.0', port=50056, threaded=True)
    finally:
        try:
            run_async(mcp_client.cleanup())
        except Exception:
            pass
        loop.call_soon_threadsafe(loop.stop)
        print("🧹 事件循环已关闭。")
