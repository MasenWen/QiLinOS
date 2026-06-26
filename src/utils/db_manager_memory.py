import sqlite3
import threading
import logging
import time
import json
import os
from datetime import datetime
from typing import Optional, List, Dict, Any

DB_PATH = "mcp_server.db"

class SqliteManager:
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
            
            # 内存数据库连接
            self.memory_conn = None
            self._memory_lock = threading.RLock()  # 改为可重入锁
            
            # 持久化相关
            self.persist_interval = 30  # 30秒持久化一次
            self.last_persist = time.time()
            self.persist_thread = None
            self.running = True
            self._dirty = False  # 标记数据是否有变更
            
            # 初始化内存数据库
            self._init_memory_db()
            self._start_persist_thread()
            
            logging.info("内存数据库管理器初始化完成")

    def _init_memory_db(self):
        """初始化内存数据库"""
        with self._memory_lock:
            self.memory_conn = sqlite3.connect(':memory:', check_same_thread=False)
            c = self.memory_conn.cursor()

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
            
            self.memory_conn.commit()

            # 从文件加载数据（如果存在）
            self._load_from_file()
            
            # 初始化默认会话 - 直接在这里检查，避免递归锁
            c.execute("SELECT COUNT(*) FROM chat_sessions")
            count = c.fetchone()[0]
            if count == 0:
                c.execute("INSERT INTO chat_sessions (name) VALUES ('默认会话')")
                self.memory_conn.commit()
                self._mark_dirty()

    def _ensure_file_db_tables(self, conn):
        """确保文件数据库的表结构存在"""
        c = conn.cursor()

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

    def _load_from_file(self):
        """从文件数据库加载数据到内存"""
        if not os.path.exists(self.db_path):
            logging.info("文件数据库不存在，创建新数据库")
            return
        
        try:
            logging.info("从文件数据库加载数据到内存...")
            file_conn = sqlite3.connect(self.db_path)
            
            # 确保文件数据库的表结构存在
            self._ensure_file_db_tables(file_conn)
            
            memory_conn = self.memory_conn
            
            # 获取文件数据库中的所有表
            file_cursor = file_conn.cursor()
            file_cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = [row[0] for row in file_cursor.fetchall()]
            
            for table in tables:
                # 跳过sqlite_sequence表
                if table == 'sqlite_sequence':
                    continue
                    
                # 从文件数据库读取数据
                file_cursor.execute(f"SELECT * FROM {table}")
                rows = file_cursor.fetchall()
                columns = [desc[0] for desc in file_cursor.description]
                
                if rows:
                    # 插入到内存数据库
                    placeholders = ', '.join(['?' for _ in columns])
                    columns_str = ', '.join(columns)
                    memory_cursor = memory_conn.cursor()
                    
                    for row in rows:
                        try:
                            memory_cursor.execute(
                                f"INSERT OR REPLACE INTO {table} ({columns_str}) VALUES ({placeholders})",
                                row
                            )
                        except Exception as e:
                            logging.warning(f"加载表 {table} 数据时出错: {e}")
                            continue
            
            memory_conn.commit()
            file_conn.close()
            logging.info(f"从文件数据库加载了 {len(tables)} 个表的数据")
            
        except Exception as e:
            logging.error(f"从文件数据库加载数据失败: {e}")

    def _save_to_file(self):
        """将内存数据保存到文件"""
        if not self._dirty:
            return
            
        try:
            logging.info("将内存数据保存到文件...")
            file_conn = sqlite3.connect(self.db_path)
            
            # 确保文件数据库的表结构存在
            self._ensure_file_db_tables(file_conn)
            
            memory_conn = self.memory_conn
            
            # 获取内存数据库中的所有表
            memory_cursor = memory_conn.cursor()
            memory_cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = [row[0] for row in memory_cursor.fetchall()]
            
            for table in tables:
                # 跳过sqlite_sequence表
                if table == 'sqlite_sequence':
                    continue
                    
                # 清空文件数据库中的表
                file_cursor = file_conn.cursor()
                try:
                    file_cursor.execute(f"DELETE FROM {table}")
                except Exception as e:
                    logging.warning(f"清空表 {table} 时出错: {e}")
                    # 如果表不存在，创建它
                    self._ensure_file_db_tables(file_conn)
                    file_cursor.execute(f"DELETE FROM {table}")
                
                # 从内存数据库读取数据
                memory_cursor.execute(f"SELECT * FROM {table}")
                rows = memory_cursor.fetchall()
                columns = [desc[0] for desc in memory_cursor.description]
                
                if rows:
                    # 插入到文件数据库
                    placeholders = ', '.join(['?' for _ in columns])
                    columns_str = ', '.join(columns)
                    
                    for row in rows:
                        try:
                            file_cursor.execute(
                                f"INSERT INTO {table} ({columns_str}) VALUES ({placeholders})",
                                row
                            )
                        except Exception as e:
                            logging.warning(f"插入表 {table} 数据时出错: {e}")
                            continue
            
            file_conn.commit()
            file_conn.close()
            self._dirty = False
            logging.info(f"内存数据已保存到文件，共 {len(tables)} 个表")
            
        except Exception as e:
            logging.error(f"保存数据到文件失败: {e}")

    def _start_persist_thread(self):
        """启动持久化线程"""
        self.persist_thread = threading.Thread(
            target=self._persist_worker,
            daemon=True,
            name="DBPersistThread"
        )
        self.persist_thread.start()
        logging.info("持久化线程已启动")

    def _persist_worker(self):
        """持久化工作线程"""
        while self.running:
            try:
                time.sleep(self.persist_interval)
                current_time = time.time()
                
                # 检查是否需要持久化
                if self._dirty and (current_time - self.last_persist >= self.persist_interval):
                    self._save_to_file()
                    self.last_persist = current_time
                    
            except Exception as e:
                logging.error(f"持久化线程错误: {e}")
                time.sleep(1)

    def _mark_dirty(self):
        """标记数据有变更"""
        self._dirty = True

    def _execute_write(self, query: str, params: tuple = ()):
        """执行写入操作"""
        with self._memory_lock:
            try:
                c = self.memory_conn.cursor()
                c.execute(query, params)
                self.memory_conn.commit()
                self._mark_dirty()
                return True
            except Exception as e:
                logging.error(f"内存数据库写入失败: {e}, 查询: {query}")
                return False

    def _execute_query(self, query: str, params: tuple = ()) -> List[Dict]:
        """执行查询操作"""
        with self._memory_lock:
            try:
                c = self.memory_conn.cursor()
                c.execute(query, params)
                rows = c.fetchall()
                
                if not rows:
                    return []
                
                # 转换为字典列表
                columns = [desc[0] for desc in c.description]
                return [dict(zip(columns, row)) for row in rows]
                
            except Exception as e:
                logging.error(f"内存数据库查询失败: {e}, 查询: {query}")
                return []

    # ========= 会话管理 =========
    def create_session(self, name: str) -> int:
        """创建会话"""
        with self._memory_lock:
            c = self.memory_conn.cursor()
            c.execute("INSERT INTO chat_sessions (name) VALUES (?)", (name,))
            self.memory_conn.commit()
            self._mark_dirty()
            return c.lastrowid

    def list_sessions(self):
        """查询会话列表"""
        return self._execute_query(
            "SELECT id, name, created_at FROM chat_sessions ORDER BY id DESC"
        )

    def rename_session(self, session_id: int, name: str):
        """重命名会话"""
        self._execute_write(
            "UPDATE chat_sessions SET name=? WHERE id=?",
            (name, session_id)
        )

    def delete_session(self, session_id: int):
        """删除会话"""
        with self._memory_lock:
            try:
                c = self.memory_conn.cursor()
                c.execute("DELETE FROM chat_sessions WHERE id=?", (session_id,))
                c.execute("DELETE FROM chat_logs WHERE session_id=?", (session_id,))
                c.execute("DELETE FROM uploaded_files WHERE session_id=?", (session_id,))
                c.execute("DELETE FROM session_states WHERE session_id=?", (session_id,))
                self.memory_conn.commit()
                self._mark_dirty()
            except Exception as e:
                logging.error(f"删除会话失败: {e}")

    # ========= 聊天记录 =========
    def save_chat_log(self, role: str, content: str, server_name: str | None, session_id: int):
        """保存聊天记录"""
        print(f"save_chat_log: {session_id}, {role}, {content}")
        self._execute_write(
            "INSERT INTO chat_logs (session_id, server_name, role, content) VALUES (?, ?, ?, ?)",
            (session_id, server_name, role, content)
        )

    def list_chat_logs(self, session_id: int):
        """查询聊天记录"""
        return self._execute_query(
            """
            SELECT role, content, server_name, created_at
            FROM chat_logs
            WHERE session_id=?
            ORDER BY id ASC
            """,
            (session_id,)
        )

    # ========= 调用日志 =========
    def add_call_log(self, action: str, detail: str, *,
                     session_id: int | None, correlation_id: str | None,
                     server_name: str | None = None, level: str = "info"):
        """添加调用日志"""
        print(f"add_call_log: {action}, {detail}")
        self._execute_write(
            "INSERT INTO call_logs (session_id, correlation_id, level, server_name, action, detail) VALUES (?, ?, ?, ?, ?, ?)",
            (session_id, correlation_id, level, server_name, action, detail)
        )

    def list_call_logs(self, session_id: int, limit: int = 50):
        """查询调用日志"""
        return self._execute_query(
            """
            SELECT server_name, action, detail, created_at, level, correlation_id
            FROM call_logs
            WHERE session_id=?
            ORDER BY id DESC
            LIMIT ?
            """,
            (session_id, limit)
        )

    # ========= 服务器管理 =========
    def add_server(self, name: str, filename: str, path: str):
        """添加服务器"""
        self._execute_write(
            "INSERT OR IGNORE INTO servers (name, filename, path) VALUES (?, ?, ?)",
            (name, filename, path)
        )

    def add_or_update_server(self, name: str, filename: str, path: str, description: str = "") -> str:
        """添加或更新服务器"""
        with self._memory_lock:
            try:
                c = self.memory_conn.cursor()
                c.execute("SELECT name, path, description FROM servers WHERE filename=?", (filename,))
                row = c.fetchone()
                if row is None:
                    c.execute(
                        "INSERT INTO servers (name, filename, path, description) VALUES (?, ?, ?, ?)",
                        (name, filename, path, description or "")
                    )
                    self.memory_conn.commit()
                    self._mark_dirty()
                    return "inserted"

                old_name, old_path, old_desc = row[0] or "", row[1] or "", row[2] or ""
                if old_name == (name or "") and old_path == (path or "") and old_desc == (description or ""):
                    return "noop"

                c.execute(
                    "UPDATE servers SET name=?, path=?, description=? WHERE filename=?",
                    (name, path, description or "", filename)
                )
                self.memory_conn.commit()
                self._mark_dirty()
                return "updated"
            except Exception as e:
                logging.error(f"添加或更新服务器失败: {e}")
                return "error"

    def list_servers(self):
        """查询服务器列表"""
        return self._execute_query("SELECT name, filename, path, status FROM servers")

    def update_status(self, name: str, status: str):
        """更新服务器状态"""
        self._execute_write(
            "UPDATE servers SET status=? WHERE name=?",
            (status, name)
        )

    def get_server(self, name: str):
        """获取服务器信息"""
        result = self._execute_query(
            "SELECT name, filename, path, status FROM servers WHERE name=?",
            (name,)
        )
        return result[0] if result else None

    def update_server_by_filename(self, filename: str, name: str, path: str):
        """通过文件名更新服务器"""
        self._execute_write(
            "UPDATE servers SET name=?, path=? WHERE filename=?",
            (name, path, filename)
        )

    def rename_server(self, old_name: str, new_name: str):
        """重命名服务器"""
        self._execute_write(
            "UPDATE servers SET name=? WHERE name=?",
            (new_name, old_name)
        )

    def list_all_servers(self):
        """查询所有服务器"""
        return self._execute_query(
            "SELECT id, name, filename, path, status, description FROM servers ORDER BY id ASC"
        )

    def list_running_servers(self):
        """查询运行中的服务器"""
        return self._execute_query(
            """
            SELECT id, name, filename, path, status, description
            FROM servers
            WHERE status='running'
            ORDER BY id ASC
            """
        )

    def get_all_filenames(self):
        """获取所有文件名"""
        result = self._execute_query("SELECT filename FROM servers")
        return set(row['filename'] for row in result)

    def save_uploaded_file(self, session_id: int, filename: str, path: str, size: int):
        """保存上传文件记录"""
        self._execute_write(
            "INSERT INTO uploaded_files (session_id, filename, path, size) VALUES (?, ?, ?, ?)",
            (session_id, filename, path, size)
        )

    def list_uploaded_files(self, session_id: int):
        """查询上传文件"""
        return self._execute_query(
            """
            SELECT id, filename, path, size, uploaded_at
            FROM uploaded_files
            WHERE session_id=?
            ORDER BY id DESC
            """,
            (session_id,)
        )

    def save_file_message(self, session_id: int, filename: str, size: int, role: str):
        """保存文件消息"""
        content = f"[文件] {filename} ({size / 1024:.1f} KB)"
        self._execute_write(
            "INSERT INTO chat_logs (session_id, server_name, role, content) VALUES (?, ?, ?, ?)",
            (session_id, None, role, content)
        )

    def get_session_state(self, session_id: int) -> str:
        """获取会话状态"""
        result = self._execute_query(
            "SELECT state FROM session_states WHERE session_id=?",
            (session_id,)
        )
        return result[0]['state'] if result else 'idle'

    def update_session_state(self, session_id: int, state: str):
        """更新会话状态"""
        self._execute_write(
            """
            INSERT INTO session_states (session_id, state)
            VALUES (?, ?)
            ON CONFLICT(session_id)
            DO UPDATE SET state=excluded.state, updated_at=datetime('now', '+8 hours')
            """,
            (session_id, state)
        )

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
        # 立即保存所有数据
        self._save_to_file()
        if self.memory_conn:
            self.memory_conn.close()
        logging.info("内存数据库管理器已关闭")


import logging

def split_str_partition(text):
    """解析日志消息格式"""
    first, sep, second = text.partition("-=-")
    if sep == "":  # 如果没有找到分隔符
        return 0, text
    else:
        return int(first), second

class NexLogHandler(logging.Handler):
    """日志处理器"""
    
    def __init__(self, db: SqliteManager):
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
db_manager = SqliteManager()
log_handler = NexLogHandler(db_manager)
log_handler.setLevel(logging.DEBUG)

# 注册退出时的清理函数
import atexit
atexit.register(db_manager.close)