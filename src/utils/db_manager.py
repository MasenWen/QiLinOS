import mysql.connector
from mysql.connector import Error
import logging
from typing import List, Dict, Any, Optional, Set
import threading
import json
from datetime import datetime
DB_CONFIG = {
    "host": "127.0.0.1",
    "user": "root",
    "password": "jh123123",
    "database": "mcp_server"
}

class DBManager:
    """MySQL 管理类：负责会话、聊天记录、调用日志与服务器信息"""

    def __init__(self, db_config: Dict[str, Any] = None):
        self.db_config = db_config or DB_CONFIG
        self.bus = None
        self._local = threading.local()
        self._ensure_database_exists()
        self._init_db()

    def _ensure_database_exists(self):
        """确保数据库存在，如果不存在则创建"""
        try:
            # 先尝试连接数据库
            conn = mysql.connector.connect(**self.db_config)
            conn.close()
        except Error as e:
            if e.errno == 1049:  # Unknown database
                print(f"数据库 {self.db_config['database']} 不存在，正在创建...")
                self._create_database()
            else:
                raise e

    def _create_database(self):
        """创建数据库"""
        # 复制配置但不指定数据库
        temp_config = self.db_config.copy()
        database_name = temp_config.pop('database', 'mcp_server')
        
        try:
            conn = mysql.connector.connect(**temp_config)
            cursor = conn.cursor()
            cursor.execute(f"CREATE DATABASE {database_name} CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
            print(f"数据库 {database_name} 创建成功")
            cursor.close()
            conn.close()
        except Error as e:
            print(f"创建数据库失败: {e}")
            raise
        
    def _connect(self):
        """建立数据库连接"""
        try:
            conn = mysql.connector.connect(**self.db_config)
            return conn
        except Error as e:
            logging.error(f"数据库连接失败: {e}")
            raise

    def _init_db(self):
        conn = self._connect()
        cursor = conn.cursor()

        # === servers 表 ===
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS servers (
            id INT AUTO_INCREMENT PRIMARY KEY,
            name VARCHAR(255),
            filename VARCHAR(255),
            path TEXT,
            status VARCHAR(50) DEFAULT 'stopped',
            description TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
        )
        """)

        # === chat_sessions 表 ===
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS chat_sessions (
            id INT AUTO_INCREMENT PRIMARY KEY,
            name VARCHAR(255),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)

        # === chat_logs 表 ===
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS chat_logs (
            id INT AUTO_INCREMENT PRIMARY KEY,
            session_id INT,
            server_name VARCHAR(255),
            role VARCHAR(50),
            content TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)

        # === call_logs 表 ===
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS call_logs (
            id INT AUTO_INCREMENT PRIMARY KEY,
            session_id INT,
            correlation_id VARCHAR(255),
            level VARCHAR(20) DEFAULT 'info',
            server_name VARCHAR(255),
            action VARCHAR(255),
            detail TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)

        # === uploaded_files 表 ===
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS uploaded_files (
            id INT AUTO_INCREMENT PRIMARY KEY,
            session_id INT,
            filename VARCHAR(255),
            path TEXT,
            size INT,
            uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)

        # === session 状态 ===
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS session_states (
            session_id INT PRIMARY KEY,
            state VARCHAR(50) DEFAULT 'active',
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
        )
        """)

        # === NodeState 相关表 ===
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS session_nodes (
            session_id INT PRIMARY KEY,
            node_name VARCHAR(255) NOT NULL DEFAULT '__start__',
            last_node_name VARCHAR(255) NOT NULL DEFAULT '__start__',
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
        )
        """)

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS session_stops (
            session_id INT PRIMARY KEY,
            stop_flag BOOLEAN NOT NULL DEFAULT FALSE,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
        )
        """)

        # 修改 user_feedbacks 表，移除 TEXT 字段的默认值
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_feedbacks (
            session_id INT PRIMARY KEY,
            feedback TEXT NOT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
        )
        """)

        # 修改 full_plan 表，移除 TEXT 字段的默认值
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS full_plan (
            session_id INT PRIMARY KEY,
            fullplan TEXT NOT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
        )
        """)

        # 修改 wait_feedback_node 表，移除 TEXT 字段的默认值
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS wait_feedback_node (
            session_id INT PRIMARY KEY,
            wait_feedback_node TEXT NOT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
        )
        """)

                # === 缓存配置表 ===
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS cache_config (
            config_key VARCHAR(255) PRIMARY KEY,
            config_value TEXT,
            last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)

        # === 用户基本信息表（键值对格式） ===
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_info (
            id INT AUTO_INCREMENT PRIMARY KEY,
            info_type VARCHAR(255) NOT NULL,
            info_value TEXT,
            category VARCHAR(100) DEFAULT 'basic',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            UNIQUE KEY uk_info_type (info_type)
        )
        """)

        # === 用户行为模式表（键值对格式） ===
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_behavior (
            id INT AUTO_INCREMENT PRIMARY KEY,
            behavior_type VARCHAR(255) NOT NULL,
            behavior_pattern TEXT NOT NULL,
            description TEXT,
            priority INT DEFAULT 5,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            UNIQUE KEY uk_behavior_type (behavior_type)
        )
        """)

        # 创建索引
        self._create_index_if_not_exists(cursor, "servers", "idx_servers_filename", "filename", True)
        self._create_index_if_not_exists(cursor, "chat_logs", "idx_chat_logs_session", "session_id, id")
        self._create_index_if_not_exists(cursor, "call_logs", "idx_call_logs_session", "session_id, id")
        self._create_index_if_not_exists(cursor, "call_logs", "idx_call_logs_corr", "correlation_id")
        self._create_index_if_not_exists(cursor, "uploaded_files", "idx_uploaded_files_session", "session_id")
        self._create_index_if_not_exists(cursor, "user_info", "idx_info_type", "info_type")
        self._create_index_if_not_exists(cursor, "user_info", "idx_info_category", "category")
        self._create_index_if_not_exists(cursor, "user_behavior", "idx_behavior_type", "behavior_type")
        self._create_index_if_not_exists(cursor, "user_behavior", "idx_behavior_priority", "priority")

        # 插入默认缓存配置
        cursor.execute("""
            INSERT IGNORE INTO cache_config (config_key, config_value) 
            VALUES (%s, %s)
        """, ("km_updated", json.dumps(True)))
        
        cursor.execute("""
            INSERT IGNORE INTO cache_config (config_key, config_value) 
            VALUES (%s, %s)
        """, ("people_info", json.dumps("None")))

        conn.commit()
        cursor.close()
        conn.close()

        # 初始化默认会话，保证前端可立即使用
        if not self.list_sessions():
            self.create_session("默认会话")

    def _create_index_if_not_exists(self, cursor, table_name, index_name, columns, unique=False):
        """检查索引是否存在，如果不存在则创建"""
        try:
            # 检查索引是否存在
            cursor.execute(f"""
                SELECT COUNT(1) 
                FROM information_schema.statistics 
                WHERE table_schema = DATABASE() 
                AND table_name = '{table_name}' 
                AND index_name = '{index_name}'
            """)
            index_exists = cursor.fetchone()[0] > 0
            
            if not index_exists:
                if unique:
                    cursor.execute(f"CREATE UNIQUE INDEX {index_name} ON {table_name}({columns})")
                else:
                    cursor.execute(f"CREATE INDEX {index_name} ON {table_name}({columns})")
                print(f"索引 {index_name} 创建成功")
        except Exception as e:
            print(f"创建索引 {index_name} 时出错: {e}")

    # ========= 缓存配置管理 =========
    def get_cache_config(self, config_key: str, default_value: Any = None) -> Any:
        """获取缓存配置值"""
        conn = self._connect()
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT config_value FROM cache_config WHERE config_key = %s", (config_key,))
            result = cursor.fetchone()
            if result and result[0]:
                return json.loads(result[0])
            return default_value
        except Error as e:
            logging.error(f"获取缓存配置失败 {config_key}: {e}")
            return default_value
        finally:
            cursor.close()
            conn.close()

    def set_cache_config(self, config_key: str, config_value: Any) -> bool:
        """设置缓存配置值"""
        conn = self._connect()
        cursor = conn.cursor()
        try:
            cursor.execute("""
                INSERT INTO cache_config (config_key, config_value)
                VALUES (%s, %s)
                ON DUPLICATE KEY UPDATE config_value = %s
            """, (config_key, json.dumps(config_value), json.dumps(config_value)))
            conn.commit()
            return True
        except Error as e:
            logging.error(f"设置缓存配置失败 {config_key}: {e}")
            conn.rollback()
            return False
        finally:
            cursor.close()
            conn.close()
    # ========= Form_People_info 相关方法 =========
    
    def is_km_updated(self) -> bool:
        """检查知识库是否已更新"""
        return self.get_cache_config("km_updated", True)
    
    def get_people_info(self) -> str:
        """获取人员信息"""
        return self.get_cache_config("people_info", "None")
    
    def set_km_updated(self, updated: bool = True) -> None:
        """设置知识库更新状态"""
        self.set_cache_config("km_updated", updated)
    
    def set_people_info(self, people_info: str) -> None:
        """设置人员信息"""
        self.set_cache_config("people_info", people_info)
        # 设置人员信息时，标记知识库需要更新
        self.set_cache_config("km_updated", False)

    # ========= 会话管理 =========
    def create_session(self, name: str) -> int:
        conn = self._connect()
        cursor = conn.cursor()
        cursor.execute("INSERT INTO chat_sessions (name) VALUES (%s)", (name,))
        conn.commit()
        sid = cursor.lastrowid
        cursor.close()
        conn.close()
        return sid

    def list_sessions(self) -> List[Dict[str, Any]]:
        conn = self._connect()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT id, name, created_at FROM chat_sessions ORDER BY id DESC")
        rows = cursor.fetchall()
        cursor.close()
        conn.close()
        return rows

    def rename_session(self, session_id: int, name: str):
        if len(name) > 12:
            name = name[:12] + "..."
        conn = self._connect()
        cursor = conn.cursor()
        cursor.execute("UPDATE chat_sessions SET name=%s WHERE id=%s", (name, session_id))
        conn.commit()
        cursor.close()
        conn.close()

    def delete_session(self, session_id: int):
        conn = self._connect()
        cursor = conn.cursor()
        # 使用事务确保所有相关数据都被删除
        try:
            cursor.execute("DELETE FROM chat_sessions WHERE id=%s", (session_id,))
            cursor.execute("DELETE FROM chat_logs WHERE session_id=%s", (session_id,))
            cursor.execute("DELETE FROM call_logs WHERE session_id=%s", (session_id,))
            cursor.execute("DELETE FROM uploaded_files WHERE session_id=%s", (session_id,))
            cursor.execute("DELETE FROM session_states WHERE session_id=%s", (session_id,))
            cursor.execute("DELETE FROM session_nodes WHERE session_id=%s", (session_id,))
            cursor.execute("DELETE FROM session_stops WHERE session_id=%s", (session_id,))
            cursor.execute("DELETE FROM user_feedbacks WHERE session_id=%s", (session_id,))
            conn.commit()
        except Error as e:
            conn.rollback()
            raise e
        finally:
            cursor.close()
            conn.close()

    # ========= 聊天记录 =========
    def save_chat_log(self, role: str, content: str, server_name: Optional[str], session_id: int):
        conn = self._connect()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO chat_logs (session_id, server_name, role, content) VALUES (%s, %s, %s, %s)",
            (session_id, server_name, role, content)
        )
        conn.commit()
        cursor.close()
        conn.close()

    def list_chat_logs(self, session_id: int) -> List[Dict[str, Any]]:
        conn = self._connect()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT role, content, server_name, created_at
            FROM chat_logs
            WHERE session_id=%s
            ORDER BY id ASC
        """, (session_id,))
        rows = cursor.fetchall()
        cursor.close()
        conn.close()
        return rows

    # ========= 调用日志 =========
    def add_call_log(self, action: str, detail: str, *,
                     session_id: Optional[int], correlation_id: Optional[str],
                     server_name: Optional[str] = None, level: str = "info"):
        conn = self._connect()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO call_logs (session_id, correlation_id, level, server_name, action, detail) VALUES (%s, %s, %s, %s, %s, %s)",
            (session_id, correlation_id, level, server_name, action, detail)
        )
        conn.commit()
        cursor.close()
        conn.close()

    def list_call_logs(self, session_id: int, limit: int = 50) -> List[Dict[str, Any]]:
        conn = self._connect()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT server_name, action, detail, created_at, level, correlation_id
            FROM call_logs
            WHERE session_id=%s
            ORDER BY id DESC
            LIMIT %s
        """, (session_id, limit))
        rows = cursor.fetchall()
        cursor.close()
        conn.close()
        return rows

    # ========= 服务器管理 =========
    def add_server(self, name: str, filename: str, path: str):
        conn = self._connect()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT IGNORE INTO servers (name, filename, path) VALUES (%s, %s, %s)",
            (name, filename, path)
        )
        conn.commit()
        cursor.close()
        conn.close()

    def add_or_update_server(self, name: str, filename: str, path: str, description: str = "") -> str:
        conn = self._connect()
        cursor = conn.cursor()
        cursor.execute("SELECT name, path, description FROM servers WHERE filename=%s", (filename,))
        row = cursor.fetchone()
        
        if row is None:
            cursor.execute(
                "INSERT INTO servers (name, filename, path, description) VALUES (%s, %s, %s, %s)",
                (name, filename, path, description or "")
            )
            conn.commit()
            cursor.close()
            conn.close()
            return "inserted"

        old_name, old_path, old_desc = row[0] or "", row[1] or "", row[2] or ""
        if old_name == (name or "") and old_path == (path or "") and old_desc == (description or ""):
            cursor.close()
            conn.close()
            return "noop"

        cursor.execute(
            "UPDATE servers SET name=%s, path=%s, description=%s WHERE filename=%s",
            (name, path, description or "", filename)
        )
        conn.commit()
        cursor.close()
        conn.close()
        return "updated"

    def list_servers(self) -> List[Dict[str, Any]]:
        conn = self._connect()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT name, filename, path, status FROM servers")
        rows = cursor.fetchall()
        cursor.close()
        conn.close()
        return rows

    def update_status(self, name: str, status: str):
        conn = self._connect()
        cursor = conn.cursor()
        cursor.execute("UPDATE servers SET status=%s WHERE name=%s", (status, name))
        conn.commit()
        cursor.close()
        conn.close()

    def get_server(self, name: str) -> Optional[Dict[str, Any]]:
        conn = self._connect()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT name, filename, path, status FROM servers WHERE name=%s", (name,))
        row = cursor.fetchone()
        cursor.close()
        conn.close()
        return row

    def update_server_by_filename(self, filename: str, name: str, path: str):
        conn = self._connect()
        cursor = conn.cursor()
        cursor.execute("UPDATE servers SET name=%s, path=%s WHERE filename=%s", (name, path, filename))
        conn.commit()
        cursor.close()
        conn.close()

    def rename_server(self, old_name: str, new_name: str):
        conn = self._connect()
        cursor = conn.cursor()
        cursor.execute("UPDATE servers SET name=%s WHERE name=%s", (new_name, old_name))
        conn.commit()
        cursor.close()
        conn.close()

    def list_all_servers(self) -> List[Dict[str, Any]]:
        conn = self._connect()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT id, name, filename, path, status, description FROM servers ORDER BY id ASC")
        rows = cursor.fetchall()
        cursor.close()
        conn.close()
        return rows

    def list_running_servers(self) -> List[Dict[str, Any]]:
        conn = self._connect()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT id, name, filename, path, status, description
            FROM servers
            WHERE status='running'
            ORDER BY id ASC
        """)
        rows = cursor.fetchall()
        cursor.close()
        conn.close()
        return rows

    def get_all_filenames(self) -> Set[str]:
        conn = self._connect()
        cursor = conn.cursor()
        cursor.execute("SELECT filename FROM servers")
        rows = {r[0] for r in cursor.fetchall()}
        cursor.close()
        conn.close()
        return rows

    def save_uploaded_file(self, session_id: int, filename: str, path: str, size: int):
        conn = self._connect()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO uploaded_files (session_id, filename, path, size) VALUES (%s, %s, %s, %s)",
            (session_id, filename, path, size)
        )
        conn.commit()
        cursor.close()
        conn.close()

    def list_uploaded_files(self, session_id: int) -> List[Dict[str, Any]]:
        conn = self._connect()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT id, filename, path, size, uploaded_at
            FROM uploaded_files
            WHERE session_id=%s
            ORDER BY id DESC
        """, (session_id,))
        rows = cursor.fetchall()
        cursor.close()
        conn.close()
        return rows

    def save_file_message(self, session_id: int, filename: str, size: int, role: str):
        conn = self._connect()
        cursor = conn.cursor()
        content = f"[文件] {filename} ({size / 1024:.1f} KB)"
        cursor.execute(
            "INSERT INTO chat_logs (session_id, server_name, role, content) VALUES (%s, %s, %s, %s)",
            (session_id, None, role, content)
        )
        conn.commit()
        cursor.close()
        conn.close()

    def get_session_state(self, session_id: int) -> str:
        conn = self._connect()
        cursor = conn.cursor()
        cursor.execute("SELECT state FROM session_states WHERE session_id=%s", (session_id,))
        row = cursor.fetchone()
        cursor.close()
        conn.close()
        return row[0] if row else 'idle'

    def update_session_state(self, session_id: int, state: str):
        conn = self._connect()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO session_states (session_id, state)
            VALUES (%s, %s)
            ON DUPLICATE KEY UPDATE state=%s, updated_at=CURRENT_TIMESTAMP
        """, (session_id, state, state))
        conn.commit()
        cursor.close()
        conn.close()
        
    # ========= NodeState 功能 =========
    def get_last_session_node(self, session_id: int) -> str:
        """获取会话的当前节点"""
        conn = self._connect()
        cursor = conn.cursor()
        cursor.execute("SELECT last_node_name FROM session_nodes WHERE session_id = %s", (session_id,))
        result = cursor.fetchone()
        cursor.close()
        conn.close()
        return result[0] if result else "__start__"
    
    def set_session_node(self, session_id: int, node_name: str) -> None:
        """设置会话的当前节点"""
        origin_node_name = self.get_session_node(session_id)
        if origin_node_name == node_name:
            return
        else:
            conn = self._connect()
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO session_nodes (session_id, node_name, last_node_name)
                VALUES (%s, %s, %s)
                ON DUPLICATE KEY UPDATE node_name=%s, last_node_name=%s, updated_at=CURRENT_TIMESTAMP
            """, (session_id, node_name, origin_node_name, node_name, origin_node_name))
            conn.commit()
            cursor.close()
            conn.close()

    def get_session_node(self, session_id: int) -> str:
        """获取会话的当前节点"""
        conn = self._connect()
        cursor = conn.cursor()
        cursor.execute("SELECT node_name FROM session_nodes WHERE session_id = %s", (session_id,))
        result = cursor.fetchone()
        cursor.close()
        conn.close()
        return result[0] if result else "__start__"

    def set_full_plan(self, session_id: int, full_plan: str) -> None:
        """设置计划"""
        conn = self._connect()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO full_plan (session_id, fullplan)
            VALUES (%s, %s)
            ON DUPLICATE KEY UPDATE fullplan=%s, updated_at=CURRENT_TIMESTAMP
        """, (session_id, full_plan, full_plan))
        conn.commit()
        cursor.close()
        conn.close()

    def get_full_plan(self, session_id: int) -> str:
        """获取计划"""
        conn = self._connect()
        cursor = conn.cursor()
        cursor.execute("SELECT fullplan FROM full_plan WHERE session_id = %s", (session_id,))
        result = cursor.fetchone()
        cursor.close()
        conn.close()
        return result[0] if result else ""
    
    def set_user_feedback(self, session_id: int, feedback: str) -> None:
        """设置用户反馈"""
        conn = self._connect()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO user_feedbacks (session_id, feedback)
            VALUES (%s, %s)
            ON DUPLICATE KEY UPDATE feedback=%s, updated_at=CURRENT_TIMESTAMP
        """, (session_id, feedback, feedback))
        conn.commit()
        cursor.close()
        conn.close()

    def get_user_feedback(self, session_id: int) -> str:
        """获取用户反馈"""
        conn = self._connect()
        cursor = conn.cursor()
        cursor.execute("SELECT feedback FROM user_feedbacks WHERE session_id = %s", (session_id,))
        result = cursor.fetchone()
        cursor.close()
        conn.close()
        return result[0] if result else "同意"
    

    def set_wait_feedback_node(self, session_id: int, node: str) -> None:
        """设置用户反馈"""
        conn = self._connect()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO wait_feedback_node (session_id, wait_feedback_node)
            VALUES (%s, %s)
            ON DUPLICATE KEY UPDATE wait_feedback_node=%s, updated_at=CURRENT_TIMESTAMP
        """, (session_id, node, node))
        conn.commit()
        cursor.close()
        conn.close()

    def get_wait_feedback_node(self, session_id: int) -> str:
        """获取用户反馈"""
        conn = self._connect()
        cursor = conn.cursor()
        cursor.execute("SELECT wait_feedback_node FROM wait_feedback_node WHERE session_id = %s", (session_id,))
        result = cursor.fetchone()
        cursor.close()
        conn.close()
        return result[0] if result else "planner"

    def set_session_stop(self, session_id: int, stop: bool) -> None:
        """设置会话停止标志"""
        conn = self._connect()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO session_stops (session_id, stop_flag)
            VALUES (%s, %s)
            ON DUPLICATE KEY UPDATE stop_flag=%s, updated_at=CURRENT_TIMESTAMP
        """, (session_id, stop, stop))
        conn.commit()
        cursor.close()
        conn.close()

    def get_session_stop(self, session_id: int) -> bool:
        """获取会话停止标志"""
        conn = self._connect()
        cursor = conn.cursor()
        cursor.execute("SELECT stop_flag FROM session_stops WHERE session_id = %s", (session_id,))
        result = cursor.fetchone()
        cursor.close()
        conn.close()
        return bool(result[0]) if result else False
    
    # ==================== 用户基本信息操作 ====================

    def add_user_info(self, info_type: str, info_value: str, category: str = "basic") -> bool:
        """
        添加或更新用户基本信息

        Args:
            info_type: 信息种类（如：name, gender, age, email等）
            info_value: 信息具体数值
            category: 信息分类（basic/contact/work/other等）

        Returns:
            操作是否成功
        """
        try:
            conn = self._connect()
            cursor = conn.cursor()

            # 检查是否已存在该类型的信息
            cursor.execute("SELECT id FROM user_info WHERE info_type = %s", (info_type,))
            existing = cursor.fetchone()

            current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

            if existing:
                # 更新现有信息
                cursor.execute('''
                UPDATE user_info 
                SET info_value = %s, category = %s, updated_at = %s
                WHERE info_type = %s
                ''', (info_value, category, current_time, info_type))
                print(f"信息类型 '{info_type}' 已更新")
            else:
                # 添加新信息
                cursor.execute('''
                INSERT INTO user_info (info_type, info_value, category, updated_at)
                VALUES (%s, %s, %s, %s)
                ''', (info_type, info_value, category, current_time))
                print(f"信息类型 '{info_type}' 已添加")

            conn.commit()
            cursor.close()
            conn.close()
            return True

        except Exception as e:
            print(f"添加/更新信息失败: {e}")
            return False

    def add_multiple_user_info(self, info_dict: Dict[str, Any], category: str = "basic") -> bool:
        """
        批量添加/更新用户信息

        Args:
            info_dict: 信息字典，格式为 {信息类型: 信息值, ...}
            category: 信息分类

        Returns:
            操作是否成功
        """
        try:
            conn = self._connect()
            cursor = conn.cursor()

            current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

            for info_type, info_value in info_dict.items():
                # 检查是否已存在
                cursor.execute("SELECT id FROM user_info WHERE info_type = %s", (info_type,))
                existing = cursor.fetchone()

                if existing:
                    cursor.execute('''
                    UPDATE user_info 
                    SET info_value = %s, category = %s, updated_at = %s
                    WHERE info_type = %s
                    ''', (str(info_value), category, current_time, info_type))
                else:
                    cursor.execute('''
                    INSERT INTO user_info (info_type, info_value, category, updated_at)
                    VALUES (%s, %s, %s, %s)
                    ''', (info_type, str(info_value), category, current_time))

            conn.commit()
            cursor.close()
            conn.close()
            print(f"批量添加/更新了 {len(info_dict)} 条信息")
            return True

        except Exception as e:
            print(f"批量添加/更新信息失败: {e}")
            return False

    def get_user_info(self, info_type: str = None, category: str = None) -> Optional[Dict]:
        """
        获取用户信息

        Args:
            info_type: 信息类型，如果为None则获取所有信息
            category: 信息分类，如果提供则按分类筛选

        Returns:
            单个信息或所有信息的字典
        """
        try:
            conn = self._connect()
            cursor = conn.cursor()

            if info_type:
                # 获取特定类型的信息
                cursor.execute('''
                SELECT info_type, info_value, category, updated_at 
                FROM user_info 
                WHERE info_type = %s
                ''', (info_type,))
                result = cursor.fetchone()
                cursor.close()
                conn.close()

                if result:
                    return {
                        'info_type': result[0],
                        'info_value': result[1],
                        'category': result[2],
                        'updated_at': result[3]
                    }
                return None
            else:
                # 获取所有信息或按分类获取
                if category:
                    cursor.execute('''
                    SELECT info_type, info_value, category, updated_at 
                    FROM user_info 
                    WHERE category = %s
                    ORDER BY info_type
                    ''', (category,))
                else:
                    cursor.execute('''
                    SELECT info_type, info_value, category, updated_at 
                    FROM user_info 
                    ORDER BY category, info_type
                    ''')

                results = cursor.fetchall()
                cursor.close()
                conn.close()

                # 转换为字典格式
                info_dict = {}
                for row in results:
                    info_dict[row[0]] = {
                        'value': row[1],
                        'category': row[2],
                        'updated_at': row[3]
                    }
                return info_dict

        except Exception as e:
            print(f"获取信息失败: {e}")
            return None

    def get_user_info_simple(self, info_type: str = None, category: str = None) -> List[List[str]]:
        """
        获取用户信息（简化格式）

        Args:
            info_type: 信息类型，如果为None则获取所有信息
            category: 信息分类，如果提供则按分类筛选

        Returns:
            列表的列表格式：[['信息种类','具体值'], ...]
        """
        try:
            conn = self._connect()
            cursor = conn.cursor()

            if info_type:
                # 获取特定类型的信息
                cursor.execute('''
                SELECT info_type, info_value
                FROM user_info 
                WHERE info_type = %s
                ''', (info_type,))
                result = cursor.fetchone()
                cursor.close()
                conn.close()

                if result:
                    return [[result[0], result[1]]]
                return None
            else:
                # 获取所有信息或按分类获取
                if category:
                    cursor.execute('''
                    SELECT info_type, info_value
                    FROM user_info 
                    WHERE category = %s
                    ORDER BY info_type
                    ''', (category,))
                else:
                    cursor.execute('''
                    SELECT info_type, info_value
                    FROM user_info 
                    ORDER BY info_type
                    ''')

                results = cursor.fetchall()
                cursor.close()
                conn.close()

                # 转换为要求格式：列表的列表
                info_list = []
                for row in results:
                    info_list.append([row[0], row[1]])
                return info_list

        except Exception as e:
            print(f"获取信息失败: {e}")
            return None

    def delete_user_info(self, info_type: str) -> bool:
        """
        删除特定类型的信息

        Args:
            info_type: 要删除的信息类型

        Returns:
            操作是否成功
        """
        try:
            conn = self._connect()
            cursor = conn.cursor()

            cursor.execute("DELETE FROM user_info WHERE info_type = %s", (info_type,))
            affected_rows = cursor.rowcount

            conn.commit()
            cursor.close()
            conn.close()

            if affected_rows > 0:
                print(f"信息类型 '{info_type}' 已删除")
                return True
            else:
                print(f"信息类型 '{info_type}' 不存在")
                return False

        except Exception as e:
            print(f"删除信息失败: {e}")
            return False

    def clear_all_user_info(self) -> bool:
        """清空所有用户信息"""
        try:
            conn = self._connect()
            cursor = conn.cursor()

            cursor.execute("DELETE FROM user_info")
            affected_rows = cursor.rowcount

            conn.commit()
            cursor.close()
            conn.close()

            print(f"已清空 {affected_rows} 条用户信息")
            return True

        except Exception as e:
            print(f"清空信息失败: {e}")
            return False

    # ==================== 用户行为模式操作 ====================

    def add_user_behavior(self, behavior_type: str, behavior_pattern: str,
                         description: str = None, priority: int = 5) -> bool:
        """
        添加或更新用户行为模式

        Args:
            behavior_type: 行为种类/任务类型
            behavior_pattern: 具体的行为模式/解决方法
            description: 行为描述或备注
            priority: 优先级（1-10）

        Returns:
            操作是否成功
        """
        try:
            conn = self._connect()
            cursor = conn.cursor()

            # 检查是否已存在该类型的行为
            cursor.execute("SELECT id FROM user_behavior WHERE behavior_type = %s", (behavior_type,))
            existing = cursor.fetchone()

            current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

            if existing:
                # 更新现有行为
                cursor.execute('''
                UPDATE user_behavior 
                SET behavior_pattern = %s, description = %s, priority = %s, updated_at = %s
                WHERE behavior_type = %s
                ''', (behavior_pattern, description, priority, current_time, behavior_type))
                print(f"行为类型 '{behavior_type}' 已更新")
            else:
                # 添加新行为
                cursor.execute('''
                INSERT INTO user_behavior (behavior_type, behavior_pattern, description, priority, updated_at)
                VALUES (%s, %s, %s, %s, %s)
                ''', (behavior_type, behavior_pattern, description, priority, current_time))
                print(f"行为类型 '{behavior_type}' 已添加")

            conn.commit()
            cursor.close()
            conn.close()
            return True

        except Exception as e:
            print(f"添加/更新行为失败: {e}")
            return False

    def get_user_behavior(self, behavior_type: str = None) -> Optional[Dict]:
        """
        获取用户行为模式

        Args:
            behavior_type: 行为类型，如果为None则获取所有行为

        Returns:
            单个行为或所有行为的字典
        """
        try:
            conn = self._connect()
            cursor = conn.cursor()

            if behavior_type:
                # 获取特定类型的行为
                cursor.execute('''
                SELECT behavior_type, behavior_pattern, description, priority, updated_at 
                FROM user_behavior 
                WHERE behavior_type = %s
                ''', (behavior_type,))
                result = cursor.fetchone()
                cursor.close()
                conn.close()

                if result:
                    return {
                        'behavior_type': result[0],
                        'behavior_pattern': result[1],
                        'description': result[2],
                        'priority': result[3],
                        'updated_at': result[4]
                    }
                return None
            else:
                # 获取所有行为
                cursor.execute('''
                SELECT behavior_type, behavior_pattern, description, priority, updated_at 
                FROM user_behavior 
                ORDER BY priority DESC, behavior_type
                ''')

                results = cursor.fetchall()
                cursor.close()
                conn.close()

                # 转换为字典格式
                behavior_dict = {}
                for row in results:
                    behavior_dict[row[0]] = {
                        'pattern': row[1],
                        'description': row[2],
                        'priority': row[3],
                        'updated_at': row[4]
                    }
                return behavior_dict

        except Exception as e:
            print(f"获取行为失败: {e}")
            return None

    def get_user_behavior_simple(self, behavior_type: str = None) -> List[List[str]]:
        """
        获取用户行为模式（简化格式）

        Args:
            behavior_type: 行为类型，如果为None则获取所有行为

        Returns:
            列表的列表格式：[['行为种类','具体行为模式'], ...]
        """
        try:
            conn = self._connect()
            cursor = conn.cursor()

            if behavior_type:
                # 获取特定类型的行为
                cursor.execute('''
                SELECT behavior_type, behavior_pattern
                FROM user_behavior 
                WHERE behavior_type = %s
                ''', (behavior_type,))
                result = cursor.fetchone()
                cursor.close()
                conn.close()

                if result:
                    return [[result[0], result[1]]]
                return None
            else:
                # 获取所有行为
                cursor.execute('''
                SELECT behavior_type, behavior_pattern
                FROM user_behavior 
                ORDER BY behavior_type
                ''')

                results = cursor.fetchall()
                cursor.close()
                conn.close()

                # 转换为要求格式：列表的列表
                behavior_list = []
                for row in results:
                    behavior_list.append([row[0], row[1]])
                return behavior_list

        except Exception as e:
            print(f"获取行为失败: {e}")
            return None

    def delete_user_behavior(self, behavior_type: str) -> bool:
        """
        删除特定类型的行为

        Args:
            behavior_type: 要删除的行为类型

        Returns:
            操作是否成功
        """
        try:
            conn = self._connect()
            cursor = conn.cursor()

            cursor.execute("DELETE FROM user_behavior WHERE behavior_type = %s", (behavior_type,))
            affected_rows = cursor.rowcount

            conn.commit()
            cursor.close()
            conn.close()

            if affected_rows > 0:
                print(f"行为类型 '{behavior_type}' 已删除")
                return True
            else:
                print(f"行为类型 '{behavior_type}' 不存在")
                return False

        except Exception as e:
            print(f"删除行为失败: {e}")
            return False

    def clear_all_user_behavior(self) -> bool:
        """清空所有用户行为"""
        try:
            conn = self._connect()
            cursor = conn.cursor()

            cursor.execute("DELETE FROM user_behavior")
            affected_rows = cursor.rowcount

            conn.commit()
            cursor.close()
            conn.close()

            print(f"已清空 {affected_rows} 条用户行为")
            return True

        except Exception as e:
            print(f"清空行为失败: {e}")
            return False

    def search_user_behavior(self, keyword: str, search_field: str = "all") -> List[Dict]:
        """
        搜索用户行为

        Args:
            keyword: 搜索关键词
            search_field: 搜索字段（all/type/pattern/description）

        Returns:
            匹配的行为列表
        """
        try:
            conn = self._connect()
            cursor = conn.cursor()

            search_pattern = f"%{keyword}%"

            if search_field == "type":
                cursor.execute('''
                SELECT behavior_type, behavior_pattern, description, priority, updated_at 
                FROM user_behavior 
                WHERE behavior_type LIKE %s
                ORDER BY priority DESC
                ''', (search_pattern,))
            elif search_field == "pattern":
                cursor.execute('''
                SELECT behavior_type, behavior_pattern, description, priority, updated_at 
                FROM user_behavior 
                WHERE behavior_pattern LIKE %s
                ORDER BY priority DESC
                ''', (search_pattern,))
            elif search_field == "description":
                cursor.execute('''
                SELECT behavior_type, behavior_pattern, description, priority, updated_at 
                FROM user_behavior 
                WHERE description LIKE %s
                ORDER BY priority DESC
                ''', (search_pattern,))
            else:  # all fields
                cursor.execute('''
                SELECT behavior_type, behavior_pattern, description, priority, updated_at 
                FROM user_behavior 
                WHERE behavior_type LIKE %s OR behavior_pattern LIKE %s OR description LIKE %s
                ORDER BY priority DESC
                ''', (search_pattern, search_pattern, search_pattern))

            results = cursor.fetchall()
            cursor.close()
            conn.close()

            return [{
                'behavior_type': row[0],
                'behavior_pattern': row[1],
                'description': row[2],
                'priority': row[3],
                'updated_at': row[4]
            } for row in results]

        except Exception as e:
            print(f"搜索行为失败: {e}")
            return []

    # ==================== 数据导出导入 ====================

    def export_user_data_to_json(self, file_path: str = "user_data_export.json") -> bool:
        """
        导出所有用户数据到JSON文件

        Args:
            file_path: 导出文件路径

        Returns:
            操作是否成功
        """
        try:
            # 获取所有数据
            all_info = self.get_user_info() or {}
            all_behavior = self.get_user_behavior() or {}

            export_data = {
                "export_time": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                "user_info": all_info,
                "user_behavior": all_behavior,
                "summary": {
                    "info_count": len(all_info),
                    "behavior_count": len(all_behavior),
                    "categories": {}
                }
            }

            # 统计信息分类
            conn = self._connect()
            cursor = conn.cursor()
            cursor.execute("SELECT category, COUNT(*) as count FROM user_info GROUP BY category")
            category_stats = cursor.fetchall()
            cursor.close()
            conn.close()

            for row in category_stats:
                export_data["summary"]["categories"][row[0]] = row[1]

            # 写入文件
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(export_data, f, ensure_ascii=False, indent=2)

            print(f"数据已成功导出到: {file_path}")
            return True

        except Exception as e:
            print(f"导出数据失败: {e}")
            return False

    def import_user_data_from_json(self, file_path: str) -> bool:
        """
        从JSON文件导入用户数据

        Args:
            file_path: 导入文件路径

        Returns:
            操作是否成功
        """
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                import_data = json.load(f)

            # 导入用户信息
            if "user_info" in import_data:
                for info_type, info_data in import_data["user_info"].items():
                    if isinstance(info_data, dict):
                        self.add_user_info(
                            info_type=info_type,
                            info_value=info_data.get('value', ''),
                            category=info_data.get('category', 'basic')
                        )
                    else:
                        self.add_user_info(
                            info_type=info_type,
                            info_value=str(info_data),
                            category='basic'
                        )

            # 导入用户行为
            if "user_behavior" in import_data:
                for behavior_type, behavior_data in import_data["user_behavior"].items():
                    if isinstance(behavior_data, dict):
                        self.add_user_behavior(
                            behavior_type=behavior_type,
                            behavior_pattern=behavior_data.get('pattern', ''),
                            description=behavior_data.get('description'),
                            priority=behavior_data.get('priority', 5)
                        )
                    else:
                        self.add_user_behavior(
                            behavior_type=behavior_type,
                            behavior_pattern=str(behavior_data),
                            description=None,
                            priority=5
                        )

            print(f"数据已成功从 {file_path} 导入")
            return True

        except Exception as e:
            print(f"导入数据失败: {e}")
            return False

    # ==================== 数据统计 ====================

    def get_user_statistics(self) -> Dict:
        """
        获取用户数据统计信息

        Returns:
            统计信息字典
        """
        try:
            conn = self._connect()
            cursor = conn.cursor()

            stats = {}

            # 基本信息统计
            cursor.execute("SELECT COUNT(*) as count FROM user_info")
            stats['total_info'] = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(DISTINCT category) as count FROM user_info")
            stats['info_categories'] = cursor.fetchone()[0]

            # 行为信息统计
            cursor.execute("SELECT COUNT(*) as count FROM user_behavior")
            stats['total_behavior'] = cursor.fetchone()[0]

            cursor.execute("SELECT AVG(priority) as avg_priority FROM user_behavior")
            avg_priority = cursor.fetchone()[0]
            stats['avg_priority'] = round(avg_priority or 0, 2)

            # 按分类统计信息
            cursor.execute('''
            SELECT category, COUNT(*) as count 
            FROM user_info 
            GROUP BY category 
            ORDER BY count DESC
            ''')
            stats['info_by_category'] = []
            for row in cursor.fetchall():
                stats['info_by_category'].append({
                    'category': row[0],
                    'count': row[1]
                })

            # 最近更新时间
            cursor.execute('''
            SELECT MAX(updated_at) as last_info_update FROM user_info
            ''')
            info_update = cursor.fetchone()[0]
            
            cursor.execute('''
            SELECT MAX(updated_at) as last_behavior_update FROM user_behavior
            ''')
            behavior_update = cursor.fetchone()[0]
            
            stats['last_info_update'] = info_update
            stats['last_behavior_update'] = behavior_update

            cursor.close()
            conn.close()
            return stats

        except Exception as e:
            print(f"获取统计信息失败: {e}")
            return {}

    # ========= 事件总线相关方法 =========
    def set_bus(self, bus):
        self.bus = bus

    def publish(self, session_id: int, event: dict):
        if self.bus:
            self.bus.publish(session_id, event)

    def add_chat(self, sid: int, role: str, content: str, server_name=None):
        self.save_chat_log(role, content, server_name, sid)
        if self.bus:
            self.bus.publish(sid, {"type": "chat", "payload": {"role": role, "content": content}})

    def add_log(self, sid, action, detail, *, server_name=None, correlation_id=None, level="info"):
        self.add_call_log(action, detail, session_id=sid, correlation_id=correlation_id,
                             server_name=server_name, level=level)
        if sid and self.bus:
            self.bus.publish(sid, {"type": "log", "payload": {"action": action, "detail": detail}})

    add_info = add_user_info
    add_multiple_info = add_multiple_user_info
    get_info = get_user_info
    get_info_simple = get_user_info_simple
    delete_info = delete_user_info
    clear_all_info = clear_all_user_info
    
    add_behavior = add_user_behavior
    get_behavior = get_user_behavior
    get_behavior_simple = get_user_behavior_simple
    delete_behavior = delete_user_behavior
    clear_all_behavior = clear_all_user_behavior
    search_behavior = search_user_behavior
    
    export_to_json = export_user_data_to_json
    import_from_json = import_user_data_from_json
    get_statistics = get_user_statistics

class Node_State:
    def __init__(self):
        print("init Node_state")
        self.session_id = 1

    def set_session_id(self, session_id):
        self.session_id = session_id

    def get_session_id(self):
        return self.session_id
    
    def __str__(self):
        # 用户友好的显示
        return f"{self.session_id}"
    
class PPT_State:
    def __init__(self):
        print("init Node_state")
        self.session_id = 1

    def set_session_id(self, session_id):
        self.session_id = session_id

    def get_session_id(self):
        return self.session_id
    
    def __str__(self):
        # 用户友好的显示
        return f"{self.session_id}"



def split_id_partition(text, sep):
    first, sep, second = text.partition(sep)
    if sep == "":  # 如果没有找到分隔符
        return 0, text
    else:
        return int(first), second
    
def split_str_partition(text, sep):
    first, sep, second = text.partition(sep)
    if sep == "":  # 如果没有找到分隔符
        return 0, text
    else:
        return first, second

node_state = Node_State()
ppt_state = PPT_State()

class NexLogHandler(logging.Handler):
    def __init__(self, db: DBManager):
        super().__init__()
        self.db = db
        self.last_session_id = 0
        
    def emit(self, record):
        try:
            # 获取日志消息
            message = self.format(record)
            # 将标准 logging 记录转发到你的自定义日志系统
            session_id, content = split_id_partition(message, "-=-")
            role, content = split_str_partition(content, "===")
            if session_id == 0:
                session_id = node_state.session_id
            else:
                self.last_session_id = session_id
            if "-----" in content:
                pass
            else:
                self.db.add_log(session_id, role, content)
        except Exception:
            self.handleError(record)




db_manager = DBManager(DB_CONFIG)
log_handler = NexLogHandler(db_manager)
log_handler.setLevel(logging.DEBUG)
