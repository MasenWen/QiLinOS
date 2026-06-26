

import sqlite3
import threading
import logging
import time
import queue
import os
from typing import Optional, List, Dict, Any

DB_PATH = "mcp_server.db"

class SQliteManager:
    """
    SQLite 管理类：负责会话、聊天记录、调用日志与服务器信息
    """

    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls, db_path: str = DB_PATH):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
            return cls._instance

    def __init__(self, db_path: str = DB_PATH):
        if not hasattr(self, '_initialized'):
            self.db_path = db_path
            self.bus = None
            self._initialized = True
            
            # 写入队列和线程
            self.write_queue = queue.Queue()
            self.writer_thread = None
            self.running = True
            
            self._init_db()
            self._start_writer_thread()
            logging.info("SQLite 管理器初始化完成")

    def _create_connection(self):
        """创建新的数据库连接"""
        return sqlite3.connect(self.db_path, timeout=10, check_same_thread=False)

    def _init_db(self):
        """初始化数据库（主线程）"""
        conn = self._create_connection()
        c = conn.cursor()

        # 启用 WAL 模式和其他优化
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA synchronous=NORMAL")
        c.execute("PRAGMA cache_size=-64000")  # 64MB
        c.execute("PRAGMA busy_timeout=5000")
        c.execute("PRAGMA temp_store=MEMORY")

        # === servers 表 ===
        c.execute("""
        CREATE TABLE IF NOT EXISTS servers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            filename TEXT,
            path TEXT,
            status TEXT DEFAULT 'stopped',
            description TEXT DEFAULT ''
        )
        """)
        c.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_servers_filename ON servers(filename)")

        # === chat_sessions 表 ===
        c.execute("""
        CREATE TABLE IF NOT EXISTS chat_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            created_at TIMESTAMP DEFAULT (datetime('now', '+8 hours'))
        )
        """)

        # === chat_logs 表 ===
        c.execute("""
        CREATE TABLE IF NOT EXISTS chat_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER,
            server_name TEXT,
            role TEXT,
            content TEXT,
            created_at TIMESTAMP DEFAULT (datetime('now', '+8 hours'))
        )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_chat_logs_session ON chat_logs(session_id, id)")

        # === call_logs 表 ===
        c.execute("""
        CREATE TABLE IF NOT EXISTS call_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER,
            correlation_id TEXT,
            level TEXT DEFAULT 'info',
            server_name TEXT,
            action TEXT,
            detail TEXT,
            created_at TIMESTAMP DEFAULT (datetime('now', '+8 hours'))
        )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_call_logs_session ON call_logs(session_id, id)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_call_logs_corr ON call_logs(correlation_id)")

        # === uploaded_files 表 ===
        c.execute("""
        CREATE TABLE IF NOT EXISTS uploaded_files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER,
            filename TEXT,
            path TEXT,
            size INTEGER,
            uploaded_at TIMESTAMP DEFAULT (datetime('now', '+8 hours'))
        )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_uploaded_files_session ON uploaded_files(session_id)")

        # === session 状态 ===
        c.execute("""
        CREATE TABLE IF NOT EXISTS session_states (
            session_id INTEGER PRIMARY KEY,
            state TEXT DEFAULT 'active',  -- active | paused | stopped
            updated_at TIMESTAMP DEFAULT (datetime('now', '+8 hours'))
        )
        """)
        conn.commit()
        conn.close()

        # 初始化默认会话，保证前端可立即使用
        if not self._has_sessions():
            self.create_session("默认会话")

    def _has_sessions(self):
        """检查是否有会话"""
        conn = self._create_connection()
        try:
            c = conn.cursor()
            c.execute("SELECT COUNT(*) FROM chat_sessions")
            count = c.fetchone()[0]
            return count > 0
        finally:
            conn.close()

    def _start_writer_thread(self):
        """启动专用的写入线程"""
        self.writer_thread = threading.Thread(
            target=self._write_worker,
            daemon=True,
            name="DBWriterThread"
        )
        self.writer_thread.start()
        logging.info("数据库写入线程已启动")

    def _write_worker(self):
        """专用的写入工作线程"""
        batch = []
        batch_size = 1
        max_wait_time = 0.5  # 最大等待时间（秒）
        last_write_time = time.time()
        
        while self.running or not self.write_queue.empty():
            try:
                # 收集批量操作
                timeout = 0.1 if batch else 1.0
                try:
                    operation = self.write_queue.get(timeout=timeout)
                    print(f"SQL: {operation}")
                    batch.append(operation)
                    
                except queue.Empty:
                    pass
                
                
                current_time = time.time()
                time_since_last_write = current_time - last_write_time
                if time_since_last_write >= 10:
                        print("NO SQL in 10s") 
                # 达到批量大小或超时，执行写入
                if (len(batch) >= batch_size or 
                    (time_since_last_write >= max_wait_time and batch)):
                    self._execute_batch(batch)
                    batch = []
                    last_write_time = current_time
                    
            except Exception as e:
                logging.error(f"写入工作线程错误: {e}")
            time.sleep(0.1)
        print("退出write SQL 循环")
        # 处理剩余操作
        if batch:
            try:
                self._execute_batch(batch)
            except Exception as e:
                logging.error(f"处理最后一批操作失败: {e}")

    def _execute_batch(self, operations: List[tuple]):
        """执行批量操作"""
        if not operations:
            return
            
        conn = self._create_connection()
        try:
            c = conn.cursor()
            success_count = 0
            total_count = len(operations)
            
            for op_type, query, params in operations:
                try:
                    c.execute(query, params)
                    success_count += 1
                except Exception as e:
                    logging.error(f"执行操作失败: {e}, 查询: {query}")
            
            conn.commit()
            if success_count < total_count:
                logging.warning(f"批量写入: {success_count}/{total_count} 成功")
            else:
                logging.debug(f"批量写入完成: {success_count} 条记录")
                
        except Exception as e:
            logging.error(f"批量执行失败: {e}")
            conn.rollback()
        finally:
            conn.close()

    def _queue_operation(self, query: str, params: tuple = ()):
        """将操作加入队列"""
        self.write_queue.put(('execute', query, params))

    # ========= 异步写入方法 =========
    def create_session(self, name: str) -> int:
        """创建会话（异步）"""
        conn = self._create_connection()
        try:
            c = conn.cursor()
            c.execute("INSERT INTO chat_sessions (name) VALUES (?)", (name,))
            conn.commit()
            return c.lastrowid
        finally:
            conn.close()

    def save_chat_log(self, role: str, content: str, server_name: str | None, session_id: int):
        """保存聊天记录（异步）"""
        print(f"add_call_log: {session_id}, {role}, {content}")
        self._queue_operation(
            "INSERT INTO chat_logs (session_id, server_name, role, content) VALUES (?, ?, ?, ?)",
            (session_id, server_name, role, content)
        )

    def add_call_log(self, action: str, detail: str, *,
                     session_id: int | None, correlation_id: str | None,
                     server_name: str | None = None, level: str = "info"):
        """添加调用日志（异步）"""
        print(f"add_call_log: {action}, {detail}")
        self._queue_operation(
            "INSERT INTO call_logs (session_id, correlation_id, level, server_name, action, detail) VALUES (?, ?, ?, ?, ?, ?)",
            (session_id, correlation_id, level, server_name, action, detail)
        )

    def add_server(self, name: str, filename: str, path: str):
        """添加服务器（异步）"""
        self._queue_operation(
            "INSERT OR IGNORE INTO servers (name, filename, path) VALUES (?, ?, ?)",
            (name, filename, path)
        )

    def add_or_update_server(self, name: str, filename: str, path: str, description: str = "") -> str:
        """添加或更新服务器（异步）"""
        # 这个需要同步执行，因为需要返回值
        conn = self._create_connection()
        try:
            c = conn.cursor()
            c.execute("SELECT name, path, description FROM servers WHERE filename=?", (filename,))
            row = c.fetchone()
            if row is None:
                c.execute(
                    "INSERT INTO servers (name, filename, path, description) VALUES (?, ?, ?, ?)",
                    (name, filename, path, description or "")
                )
                conn.commit()
                return "inserted"

            old_name, old_path, old_desc = row[0] or "", row[1] or "", row[2] or ""
            if old_name == (name or "") and old_path == (path or "") and old_desc == (description or ""):
                return "noop"

            c.execute(
                "UPDATE servers SET name=?, path=?, description=? WHERE filename=?",
                (name, path, description or "", filename)
            )
            conn.commit()
            return "updated"
        finally:
            conn.close()

    def update_status(self, name: str, status: str):
        """更新服务器状态（异步）"""
        self._queue_operation(
            "UPDATE servers SET status=? WHERE name=?",
            (status, name)
        )

    def update_server_by_filename(self, filename: str, name: str, path: str):
        """通过文件名更新服务器（异步）"""
        self._queue_operation(
            "UPDATE servers SET name=?, path=? WHERE filename=?",
            (name, path, filename)
        )

    def rename_server(self, old_name: str, new_name: str):
        """重命名服务器（异步）"""
        self._queue_operation(
            "UPDATE servers SET name=? WHERE name=?",
            (new_name, old_name)
        )

    def save_uploaded_file(self, session_id: int, filename: str, path: str, size: int):
        """保存上传文件记录（异步）"""
        self._queue_operation(
            "INSERT INTO uploaded_files (session_id, filename, path, size) VALUES (?, ?, ?, ?)",
            (session_id, filename, path, size)
        )

    def save_file_message(self, session_id: int, filename: str, size: int, role: str):
        """保存文件消息（异步）"""
        content = f"[文件] {filename} ({size / 1024:.1f} KB)"
        self._queue_operation(
            "INSERT INTO chat_logs (session_id, server_name, role, content) VALUES (?, ?, ?, ?)",
            (session_id, None, role, content)
        )

    def update_session_state(self, session_id: int, state: str):
        """更新会话状态（异步）"""
        self._queue_operation(
            """
            INSERT INTO session_states (session_id, state)
            VALUES (?, ?)
            ON CONFLICT(session_id)
            DO UPDATE SET state=excluded.state, updated_at=datetime('now', '+8 hours')
            """,
            (session_id, state)
        )

    def rename_session(self, session_id: int, name: str):
        """重命名会话（异步）"""
        self._queue_operation(
            "UPDATE chat_sessions SET name=? WHERE id=?",
            (name, session_id)
        )

    def delete_session(self, session_id: int):
        """删除会话（异步）"""
        # 需要按顺序执行多个操作
        operations = [
            ('execute', "DELETE FROM chat_sessions WHERE id=?", (session_id,)),
            ('execute', "DELETE FROM chat_logs WHERE session_id=?", (session_id,)),
            ('execute', "DELETE FROM uploaded_files WHERE session_id=?", (session_id,)),
            ('execute', "DELETE FROM session_states WHERE session_id=?", (session_id,))
        ]
        for op in operations:
            self.write_queue.put(op)

    # ========= 同步查询方法 =========
    def list_sessions(self):
        """查询会话列表（同步）"""
        return self._execute_sync_query(
            "SELECT id, name, created_at FROM chat_sessions ORDER BY id DESC"
        )

    def list_chat_logs(self, session_id: int):
        """查询聊天记录（同步）"""
        return self._execute_sync_query(
            """
            SELECT role, content, server_name, created_at
            FROM chat_logs
            WHERE session_id=?
            ORDER BY id ASC
            """,
            (session_id,)
        )

    def list_call_logs(self, session_id: int, limit: int = 50):
        """查询调用日志（同步）"""
        return self._execute_sync_query(
            """
            SELECT server_name, action, detail, created_at, level, correlation_id
            FROM call_logs
            WHERE session_id=?
            ORDER BY id DESC
            LIMIT ?
            """,
            (session_id, limit)
        )

    def list_servers(self):
        """查询服务器列表（同步）"""
        return self._execute_sync_query(
            "SELECT name, filename, path, status FROM servers"
        )

    def get_server(self, name: str):
        """获取服务器信息（同步）"""
        result = self._execute_sync_query(
            "SELECT name, filename, path, status FROM servers WHERE name=?",
            (name,)
        )
        return result[0] if result else None

    def list_all_servers(self):
        """查询所有服务器（同步）"""
        return self._execute_sync_query(
            "SELECT id, name, filename, path, status, description FROM servers ORDER BY id ASC"
        )

    def list_running_servers(self):
        """查询运行中的服务器（同步）"""
        return self._execute_sync_query(
            """
            SELECT id, name, filename, path, status, description
            FROM servers
            WHERE status='running'
            ORDER BY id ASC
            """
        )

    def get_all_filenames(self):
        """获取所有文件名（同步）"""
        conn = self._create_connection()
        try:
            c = conn.cursor()
            c.execute("SELECT filename FROM servers")
            rows = [r[0] for r in c.fetchall()]
            return set(rows)
        finally:
            conn.close()

    def list_uploaded_files(self, session_id: int):
        """查询上传文件（同步）"""
        return self._execute_sync_query(
            """
            SELECT id, filename, path, size, uploaded_at
            FROM uploaded_files
            WHERE session_id=?
            ORDER BY id DESC
            """,
            (session_id,)
        )

    def get_session_state(self, session_id: int) -> str:
        """获取会话状态（同步）"""
        result = self._execute_sync_query(
            "SELECT state FROM session_states WHERE session_id=?",
            (session_id,)
        )
        return result[0]['state'] if result else 'idle'

    def _execute_sync_query(self, query: str, params: tuple = ()) -> List[Dict]:
        """执行同步查询"""
        conn = self._create_connection()
        try:
            c = conn.cursor()
            c.execute(query, params)
            rows = c.fetchall()
            
            if not rows:
                return []
            
            # 转换为字典列表
            columns = [desc[0] for desc in c.description]
            return [dict(zip(columns, row)) for row in rows]
            
        except Exception as e:
            logging.error(f"同步查询失败: {e}, 查询: {query}")
            return []
        finally:
            conn.close()

    # ========= 事件总线相关方法 =========
    def set_bus(self, bus):
        self.bus = bus

    def publish(self, session_id: int, event: dict):
        if self.bus:
            self.bus.publish(session_id, event)

    def add_chat(self, sid: int, role: str, content: str, server_name=None):
        """添加聊天记录并发布事件"""

        self.save_chat_log(role, content, server_name, sid)
        if self.bus:
            self.bus.publish(sid, {"type": "chat", "payload": {"role": role, "content": content}})

    def add_log(self, sid, action, detail, *, server_name=None, correlation_id=None, level="info"):
        """添加调用日志并发布事件"""
        self.add_call_log(action, detail, session_id=sid, correlation_id=correlation_id,
                         server_name=server_name, level=level)
        if sid and self.bus:
            self.bus.publish(sid, {"type": "log", "payload": {"action": action, "detail": detail}})

    def close(self):
        """关闭管理器"""
        self.running = False
        if self.writer_thread:
            self.writer_thread.join(timeout=5)
        logging.info("SQLite 管理器已关闭")


import logging

def split_str_partition(text):
    """解析日志消息格式"""
    first, sep, second = text.partition("-=-")
    if sep == "":  # 如果没有找到分隔符
        return 0, text
    else:
        return int(first), second

class NexLogHandler(logging.Handler):
    """改进的日志处理器 - 使用改进的数据库管理器"""
    
    def __init__(self, db: SQliteManager):
        super().__init__()
        self.db = db
        self.last_session_id = 0
        
    def emit(self, record):
        try:
            # 获取日志消息
            message = self.format(record)
            # 将标准 logging 记录转发到自定义日志系统
            session_id, content = split_str_partition(message)
            if session_id == 0:
                session_id = self.last_session_id
            else:
                self.last_session_id = session_id
            if "-----" in content:
                pass
            else:
                self.db.add_log(session_id, record.name, content)
        except Exception:
            self.handleError(record)


# 创建全局实例
db_manager = SQliteManager()
log_handler = NexLogHandler(db_manager)
log_handler.setLevel(logging.DEBUG)

