import sqlite3

DB_PATH = "mcp_server.db"


class DBManager:
    """SQLite 管理类：负责会话、聊天记录、调用日志与服务器信息"""

    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self._init_db()

    def _connect(self):
        # 每次调用建立新连接，保证线程安全
        return sqlite3.connect(self.db_path, timeout=5)

    def _init_db(self):
        conn = self._connect()
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
        conn.close()

        # 初始化默认会话，保证前端可立即使用
        if not self.list_sessions():
            self.create_session("默认会话")

    # ========= 会话管理 =========
    def create_session(self, name: str) -> int:
        conn = self._connect()
        c = conn.cursor()
        c.execute("INSERT INTO chat_sessions (name) VALUES (?)", (name,))
        conn.commit()
        sid = c.lastrowid
        conn.close()
        return sid

    def list_sessions(self):
        conn = self._connect()
        c = conn.cursor()
        c.execute("SELECT id, name, created_at FROM chat_sessions ORDER BY id DESC")
        rows = c.fetchall()
        conn.close()
        return [{"id": r[0], "name": r[1], "created_at": r[2]} for r in rows]

    def rename_session(self, session_id: int, name: str):
        conn = self._connect()
        c = conn.cursor()
        c.execute("UPDATE chat_sessions SET name=? WHERE id=?", (name, session_id))
        conn.commit()
        conn.close()

    def delete_session(self, session_id: int):
        conn = self._connect()
        c = conn.cursor()
        c.execute("DELETE FROM chat_sessions WHERE id=?", (session_id,))
        c.execute("DELETE FROM chat_logs WHERE session_id=?", (session_id,))
        conn.commit()
        conn.close()

    # ========= 聊天记录 =========
    def save_chat_log(self, role: str, content: str, server_name: str | None, session_id: int):
        conn = self._connect()
        c = conn.cursor()
        c.execute(
            "INSERT INTO chat_logs (session_id, server_name, role, content) VALUES (?, ?, ?, ?)",
            (session_id, server_name, role, content)
        )
        conn.commit()
        conn.close()

    def list_chat_logs(self, session_id: int):
        conn = self._connect()
        c = conn.cursor()
        c.execute("""
            SELECT role, content, server_name, created_at
            FROM chat_logs
            WHERE session_id=?
            ORDER BY id ASC
        """, (session_id,))
        rows = c.fetchall()
        conn.close()
        return [
            {"role": r[0], "content": r[1], "server_name": r[2], "created_at": r[3]}
            for r in rows
        ]

    # ========= 调用日志 =========
    def add_call_log(self, action: str, detail: str, *,
                     session_id: int | None, correlation_id: str | None,
                     server_name: str | None = None, level: str = "info"):
        conn = self._connect()
        c = conn.cursor()
        c.execute(
            "INSERT INTO call_logs (session_id, correlation_id, level, server_name, action, detail) VALUES (?, ?, ?, ?, ?, ?)",
            (session_id, correlation_id, level, server_name, action, detail)
        )
        conn.commit()
        conn.close()

    def list_call_logs(self, session_id: int, limit: int = 50):
        conn = self._connect()
        c = conn.cursor()
        c.execute("""
            SELECT server_name, action, detail, created_at, level, correlation_id
            FROM call_logs
            WHERE session_id=?
            ORDER BY id DESC
            LIMIT ?
        """, (session_id, limit))
        rows = c.fetchall()
        conn.close()
        return [
            {
                "server_name": r[0],
                "action": r[1],
                "detail": r[2],
                "created_at": r[3],
                "level": r[4],
                "correlation_id": r[5]
            }
            for r in rows
        ]

    # ========= 服务器管理 =========
    def add_server(self, name: str, filename: str, path: str):
        conn = self._connect()
        c = conn.cursor()
        c.execute(
            "INSERT OR IGNORE INTO servers (name, filename, path) VALUES (?, ?, ?)",
            (name, filename, path)
        )
        conn.commit()
        conn.close()

    def add_or_update_server(self, name: str, filename: str, path: str, description: str = "") -> str:
        conn = self._connect()
        c = conn.cursor()
        c.execute("SELECT name, path, description FROM servers WHERE filename=?", (filename,))
        row = c.fetchone()
        if row is None:
            c.execute(
                "INSERT INTO servers (name, filename, path, description) VALUES (?, ?, ?, ?)",
                (name, filename, path, description or "")
            )
            conn.commit()
            conn.close()
            return "inserted"

        old_name, old_path, old_desc = row[0] or "", row[1] or "", row[2] or ""
        if old_name == (name or "") and old_path == (path or "") and old_desc == (description or ""):
            conn.close()
            return "noop"

        c.execute(
            "UPDATE servers SET name=?, path=?, description=? WHERE filename=?",
            (name, path, description or "", filename)
        )
        conn.commit()
        conn.close()
        return "updated"

    def list_servers(self):
        conn = self._connect()
        c = conn.cursor()
        c.execute("SELECT name, filename, path, status FROM servers")
        rows = c.fetchall()
        conn.close()
        return [
            {"name": r[0], "filename": r[1], "path": r[2], "status": r[3]}
            for r in rows
        ]

    def update_status(self, name: str, status: str):
        conn = self._connect()
        c = conn.cursor()
        c.execute("UPDATE servers SET status=? WHERE name=?", (status, name))
        conn.commit()
        conn.close()

    def get_server(self, name: str):
        conn = self._connect()
        c = conn.cursor()
        c.execute("SELECT name, filename, path, status FROM servers WHERE name=?", (name,))
        row = c.fetchone()
        conn.close()
        if not row:
            return None
        return {"name": row[0], "filename": row[1], "path": row[2], "status": row[3]}

    def update_server_by_filename(self, filename: str, name: str, path: str):
        conn = self._connect()
        c = conn.cursor()
        c.execute("UPDATE servers SET name=?, path=? WHERE filename=?", (name, path, filename))
        conn.commit()
        conn.close()

    def rename_server(self, old_name: str, new_name: str):
        conn = self._connect()
        c = conn.cursor()
        c.execute("UPDATE servers SET name=? WHERE name=?", (new_name, old_name))
        conn.commit()
        conn.close()

    def list_all_servers(self):
        conn = self._connect()
        c = conn.cursor()
        c.execute("SELECT id, name, filename, path, status, description FROM servers ORDER BY id ASC")
        rows = c.fetchall()
        conn.close()
        return [
            {
                "id": r[0],
                "name": r[1],
                "filename": r[2],
                "path": r[3],
                "status": r[4],
                "description": r[5] or ""
            }
            for r in rows
        ]

    def list_running_servers(self):
        conn = self._connect()
        c = conn.cursor()
        c.execute("""
            SELECT id, name, filename, path, status, description
            FROM servers
            WHERE status='running'
            ORDER BY id ASC
        """)
        rows = c.fetchall()
        conn.close()
        return [
            {
                "id": r[0],
                "name": r[1],
                "filename": r[2],
                "path": r[3],
                "status": r[4],
                "description": r[5] or ""
            }
            for r in rows
        ]

    def get_all_filenames(self):
        conn = self._connect()
        c = conn.cursor()
        c.execute("SELECT filename FROM servers")
        rows = [r[0] for r in c.fetchall()]
        conn.close()
        return set(rows)

    def save_uploaded_file(self, session_id: int, filename: str, path: str, size: int):
        conn = self._connect()
        c = conn.cursor()
        c.execute(
            "INSERT INTO uploaded_files (session_id, filename, path, size) VALUES (?, ?, ?, ?)",
            (session_id, filename, path, size)
        )
        conn.commit()
        conn.close()

    def list_uploaded_files(self, session_id: int):
        conn = self._connect()
        c = conn.cursor()
        c.execute("""
            SELECT id, filename, path, size, uploaded_at
            FROM uploaded_files
            WHERE session_id=?
            ORDER BY id DESC
        """, (session_id,))
        rows = c.fetchall()
        conn.close()
        return [
            {"id": r[0], "filename": r[1], "path": r[2], "size": r[3], "uploaded_at": r[4]}
            for r in rows
        ]

    def save_file_message(self, session_id: int, filename: str, size: int, role: str):
        conn = self._connect()
        c = conn.cursor()
        content = f"[文件] {filename} ({size / 1024:.1f} KB)"
        c.execute(
            "INSERT INTO chat_logs (session_id, server_name, role, content) VALUES (?, ?, ?, ?)",
            (session_id, None, role, content)
        )
        conn.commit()
        conn.close()

    def get_session_state(self, session_id: int) -> str:
        conn = self._connect()
        c = conn.cursor()
        c.execute("SELECT state FROM session_states WHERE session_id=?", (session_id,))
        row = c.fetchone()
        conn.close()
        return row[0] if row else 'idle'

    def update_session_state(self, session_id: int, state: str):
        conn = self._connect()
        c = conn.cursor()
        c.execute("""
            INSERT INTO session_states (session_id, state)
            VALUES (?, ?)
            ON CONFLICT(session_id)
            DO UPDATE SET state=excluded.state, updated_at=datetime('now', '+8 hours')
        """, (session_id, state))
        conn.commit()
        conn.close()

