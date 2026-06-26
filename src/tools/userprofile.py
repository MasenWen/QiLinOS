import sqlite3
import json
from typing import Dict, List, Optional, Any
from datetime import datetime

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
# sys.path.insert(0, str(Path(__file__).parent))
from src.utils.db_manager import db_manager

class SingleUserDatabase:
    """
    用户数据库管理系统
    存储单个用户的键值对格式的基本信息和行为模式
    """

    def __init__(self, db_path: str = "single_user_data.db"):
        """初始化数据库连接"""
        self.db_path = db_path
        self._init_database()

    def get_info(self, info_type: str = None, category: str = None) -> List[List[str]]:
        """
        获取用户信息

        Args:
            info_type: 信息类型，如果为None则获取所有信息
            category: 信息分类，如果提供则按分类筛选

        Returns:
            列表的列表格式：[['信息种类','具体值'], ...]
        """
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            if info_type:
                # 获取特定类型的信息
                cursor.execute('''
                SELECT info_type, info_value
                FROM user_info 
                WHERE info_type = ?
                ''', (info_type,))
                result = cursor.fetchone()
                conn.close()

                if result:
                    return [[result[0], result[1]]]
                return []
            else:
                # 获取所有信息或按分类获取
                if category:
                    cursor.execute('''
                    SELECT info_type, info_value
                    FROM user_info 
                    WHERE category = ?
                    ORDER BY info_type
                    ''', (category,))
                else:
                    cursor.execute('''
                    SELECT info_type, info_value
                    FROM user_info 
                    ORDER BY info_type
                    ''')

                results = cursor.fetchall()
                conn.close()

                # 转换为要求格式：列表的列表
                info_list = []
                for row in results:
                    info_list.append([row[0], row[1]])
                return info_list

        except Exception as e:
            print(f"获取信息失败: {e}")
            return []
    def _get_connection(self):
        """获取数据库连接"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row  # 使查询结果可以按列名访问
        return conn

    def _init_database(self):
        """初始化数据库和表结构"""
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            # 创建用户基本信息表（键值对格式）
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_info (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                info_type TEXT NOT NULL,      -- 信息种类（如：姓名、性别、年龄等）
                info_value TEXT,              -- 信息具体数值
                category TEXT DEFAULT 'basic', -- 信息分类（basic/contact/other等）
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(info_type)  -- 确保每种信息类型只有一条记录
            )
            ''')

            # 创建用户行为模式表（键值对格式）
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_behavior (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                behavior_type TEXT NOT NULL,  -- 行为种类/任务类型（如：数据分析、文件处理等）
                behavior_pattern TEXT NOT NULL, -- 具体的行为模式/解决方法
                description TEXT,             -- 行为描述或备注
                priority INTEGER DEFAULT 5,   -- 优先级（1-10，默认5）
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(behavior_type)  -- 确保每种行为类型只有一条记录
            )
            ''')

            # 创建索引以提高查询性能
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_info_type ON user_info(info_type)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_info_category ON user_info(category)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_behavior_type ON user_behavior(behavior_type)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_behavior_priority ON user_behavior(priority)')

            conn.commit()
            conn.close()
            print("用户数据库初始化成功！")

        except Exception as e:
            print(f"数据库初始化失败: {e}")

    # ==================== 用户基本信息操作 ====================

    def add_info(self, info_type: str, info_value: str, category: str = "basic") -> bool:
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
            conn = self._get_connection()
            cursor = conn.cursor()

            # 检查是否已存在该类型的信息
            cursor.execute("SELECT id FROM user_info WHERE info_type = ?", (info_type,))
            existing = cursor.fetchone()

            current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

            if existing:
                # 更新现有信息
                cursor.execute('''
                UPDATE user_info 
                SET info_value = ?, category = ?, updated_at = ?
                WHERE info_type = ?
                ''', (info_value, category, current_time, info_type))
                print(f"信息类型 '{info_type}' 已更新")
            else:
                # 添加新信息
                cursor.execute('''
                INSERT INTO user_info (info_type, info_value, category, updated_at)
                VALUES (?, ?, ?, ?)
                ''', (info_type, info_value, category, current_time))
                print(f"信息类型 '{info_type}' 已添加")

            conn.commit()
            conn.close()
            return True

        except Exception as e:
            print(f"添加/更新信息失败: {e}")
            return False

    def add_multiple_info(self, info_dict: Dict[str, Any], category: str = "basic") -> bool:
        """
        批量添加/更新用户信息

        Args:
            info_dict: 信息字典，格式为 {信息类型: 信息值, ...}
            category: 信息分类

        Returns:
            操作是否成功
        """
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

            for info_type, info_value in info_dict.items():
                # 检查是否已存在
                cursor.execute("SELECT id FROM user_info WHERE info_type = ?", (info_type,))
                existing = cursor.fetchone()

                if existing:
                    cursor.execute('''
                    UPDATE user_info 
                    SET info_value = ?, category = ?, updated_at = ?
                    WHERE info_type = ?
                    ''', (str(info_value), category, current_time, info_type))
                else:
                    cursor.execute('''
                    INSERT INTO user_info (info_type, info_value, category, updated_at)
                    VALUES (?, ?, ?, ?)
                    ''', (info_type, str(info_value), category, current_time))

            conn.commit()
            conn.close()
            print(f"批量添加/更新了 {len(info_dict)} 条信息")
            return True

        except Exception as e:
            print(f"批量添加/更新信息失败: {e}")
            return False

    def get_info(self, info_type: str = None, category: str = None) -> Optional[Dict]:
        """
        获取用户信息

        Args:
            info_type: 信息类型，如果为None则获取所有信息
            category: 信息分类，如果提供则按分类筛选

        Returns:
            单个信息或所有信息的字典
        """
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            if info_type:
                # 获取特定类型的信息
                cursor.execute('''
                SELECT info_type, info_value, category, updated_at 
                FROM user_info 
                WHERE info_type = ?
                ''', (info_type,))
                result = cursor.fetchone()
                conn.close()

                if result:
                    return dict(result)
                return None
            else:
                # 获取所有信息或按分类获取
                if category:
                    cursor.execute('''
                    SELECT info_type, info_value, category, updated_at 
                    FROM user_info 
                    WHERE category = ?
                    ORDER BY info_type
                    ''', (category,))
                else:
                    cursor.execute('''
                    SELECT info_type, info_value, category, updated_at 
                    FROM user_info 
                    ORDER BY category, info_type
                    ''')

                results = cursor.fetchall()
                conn.close()

                # 转换为字典格式
                info_dict = {}
                for row in results:
                    row_dict = dict(row)
                    info_dict[row_dict['info_type']] = {
                        'value': row_dict['info_value'],
                        'category': row_dict['category'],
                        'updated_at': row_dict['updated_at']
                    }
                return info_dict

        except Exception as e:
            print(f"获取信息失败: {e}")
            return None

    def get_info_simple(self, info_type: str = None, category: str = None) -> List[List[str]]:
        """
        获取用户信息

        Args:
            info_type: 信息类型，如果为None则获取所有信息
            category: 信息分类，如果提供则按分类筛选

        Returns:
            列表的列表格式：[['信息种类','具体值'], ...]
        """
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            if info_type:
                # 获取特定类型的信息
                cursor.execute('''
                SELECT info_type, info_value
                FROM user_info 
                WHERE info_type = ?
                ''', (info_type,))
                result = cursor.fetchone()
                conn.close()

                if result:
                    return [[result[0], result[1]]]
                return []
            else:
                # 获取所有信息或按分类获取
                if category:
                    cursor.execute('''
                    SELECT info_type, info_value
                    FROM user_info 
                    WHERE category = ?
                    ORDER BY info_type
                    ''', (category,))
                else:
                    cursor.execute('''
                    SELECT info_type, info_value
                    FROM user_info 
                    ORDER BY info_type
                    ''')

                results = cursor.fetchall()
                conn.close()

                # 转换为要求格式：列表的列表
                info_list = []
                for row in results:
                    info_list.append([row[0], row[1]])
                return info_list

        except Exception as e:
            print(f"获取信息失败: {e}")
            return []
    def delete_info(self, info_type: str) -> bool:
        """
        删除特定类型的信息

        Args:
            info_type: 要删除的信息类型

        Returns:
            操作是否成功
        """
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            cursor.execute("DELETE FROM user_info WHERE info_type = ?", (info_type,))

            conn.commit()
            conn.close()

            if cursor.rowcount > 0:
                print(f"信息类型 '{info_type}' 已删除")
                return True
            else:
                print(f"信息类型 '{info_type}' 不存在")
                return False

        except Exception as e:
            print(f"删除信息失败: {e}")
            return False

    def clear_all_info(self) -> bool:
        """清空所有用户信息"""
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            cursor.execute("DELETE FROM user_info")

            conn.commit()
            conn.close()

            print("所有用户信息已清空")
            return True

        except Exception as e:
            print(f"清空信息失败: {e}")
            return False

    # ==================== 用户行为模式操作 ====================

    def add_behavior(self, behavior_type: str, behavior_pattern: str,
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
            conn = self._get_connection()
            cursor = conn.cursor()

            # 检查是否已存在该类型的行为
            cursor.execute("SELECT id FROM user_behavior WHERE behavior_type = ?", (behavior_type,))
            existing = cursor.fetchone()

            current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

            if existing:
                # 更新现有行为
                cursor.execute('''
                UPDATE user_behavior 
                SET behavior_pattern = ?, description = ?, priority = ?, updated_at = ?
                WHERE behavior_type = ?
                ''', (behavior_pattern, description, priority, current_time, behavior_type))
                print(f"行为类型 '{behavior_type}' 已更新")
            else:
                # 添加新行为
                cursor.execute('''
                INSERT INTO user_behavior (behavior_type, behavior_pattern, description, priority, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ''', (behavior_type, behavior_pattern, description, priority, current_time))
                print(f"行为类型 '{behavior_type}' 已添加")

            conn.commit()
            conn.close()
            return True

        except Exception as e:
            print(f"添加/更新行为失败: {e}")
            return False

    def get_behavior(self, behavior_type: str = None) -> Optional[Dict]:
        """
        获取用户行为模式

        Args:
            behavior_type: 行为类型，如果为None则获取所有行为

        Returns:
            单个行为或所有行为的字典
        """
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            if behavior_type:
                # 获取特定类型的行为
                cursor.execute('''
                SELECT behavior_type, behavior_pattern, description, priority, updated_at 
                FROM user_behavior 
                WHERE behavior_type = ?
                ''', (behavior_type,))
                result = cursor.fetchone()
                conn.close()

                if result:
                    return dict(result)
                return None
            else:
                # 获取所有行为
                cursor.execute('''
                SELECT behavior_type, behavior_pattern, description, priority, updated_at 
                FROM user_behavior 
                ORDER BY priority DESC, behavior_type
                ''')

                results = cursor.fetchall()
                conn.close()

                # 转换为字典格式
                behavior_dict = {}
                for row in results:
                    row_dict = dict(row)
                    behavior_dict[row_dict['behavior_type']] = {
                        'pattern': row_dict['behavior_pattern'],
                        'description': row_dict['description'],
                        'priority': row_dict['priority'],
                        'updated_at': row_dict['updated_at']
                    }
                return behavior_dict

        except Exception as e:
            print(f"获取行为失败: {e}")
            return None

    def get_behavior_simple(self, behavior_type: str = None) -> List[List[str]]:
        """
        获取用户行为模式

        Args:
            behavior_type: 行为类型，如果为None则获取所有行为

        Returns:
            列表的列表格式：[['行为种类','具体行为模式'], ...]
        """
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            if behavior_type:
                # 获取特定类型的行为
                cursor.execute('''
                SELECT behavior_type, behavior_pattern
                FROM user_behavior 
                WHERE behavior_type = ?
                ''', (behavior_type,))
                result = cursor.fetchone()
                conn.close()

                if result:
                    return [[result[0], result[1]]]
                return []
            else:
                # 获取所有行为
                cursor.execute('''
                SELECT behavior_type, behavior_pattern
                FROM user_behavior 
                ORDER BY behavior_type
                ''')

                results = cursor.fetchall()
                conn.close()

                # 转换为要求格式：列表的列表
                behavior_list = []
                for row in results:
                    behavior_list.append([row[0], row[1]])
                return behavior_list

        except Exception as e:
            print(f"获取行为失败: {e}")
            return []
    def delete_behavior(self, behavior_type: str) -> bool:
        """
        删除特定类型的行为

        Args:
            behavior_type: 要删除的行为类型

        Returns:
            操作是否成功
        """
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            cursor.execute("DELETE FROM user_behavior WHERE behavior_type = ?", (behavior_type,))

            conn.commit()
            conn.close()

            if cursor.rowcount > 0:
                print(f"行为类型 '{behavior_type}' 已删除")
                return True
            else:
                print(f"行为类型 '{behavior_type}' 不存在")
                return False

        except Exception as e:
            print(f"删除行为失败: {e}")
            return False

    def clear_all_behavior(self) -> bool:
        """清空所有用户行为"""
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            cursor.execute("DELETE FROM user_behavior")

            conn.commit()
            conn.close()

            print("所有用户行为已清空")
            return True

        except Exception as e:
            print(f"清空行为失败: {e}")
            return False

    def search_behavior(self, keyword: str, search_field: str = "all") -> List[Dict]:
        """
        搜索用户行为

        Args:
            keyword: 搜索关键词
            search_field: 搜索字段（all/type/pattern/description）

        Returns:
            匹配的行为列表
        """
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            search_pattern = f"%{keyword}%"

            if search_field == "type":
                cursor.execute('''
                SELECT behavior_type, behavior_pattern, description, priority, updated_at 
                FROM user_behavior 
                WHERE behavior_type LIKE ?
                ORDER BY priority DESC
                ''', (search_pattern,))
            elif search_field == "pattern":
                cursor.execute('''
                SELECT behavior_type, behavior_pattern, description, priority, updated_at 
                FROM user_behavior 
                WHERE behavior_pattern LIKE ?
                ORDER BY priority DESC
                ''', (search_pattern,))
            elif search_field == "description":
                cursor.execute('''
                SELECT behavior_type, behavior_pattern, description, priority, updated_at 
                FROM user_behavior 
                WHERE description LIKE ?
                ORDER BY priority DESC
                ''', (search_pattern,))
            else:  # all fields
                cursor.execute('''
                SELECT behavior_type, behavior_pattern, description, priority, updated_at 
                FROM user_behavior 
                WHERE behavior_type LIKE ? OR behavior_pattern LIKE ? OR description LIKE ?
                ORDER BY priority DESC
                ''', (search_pattern, search_pattern, search_pattern))

            results = cursor.fetchall()
            conn.close()

            return [dict(row) for row in results]

        except Exception as e:
            print(f"搜索行为失败: {e}")
            return []


    def export_to_json(self, file_path: str = "user_data_export.json") -> bool:
        """
        导出所有数据到JSON文件

        Args:
            file_path: 导出文件路径

        Returns:
            操作是否成功
        """
        try:
            # 获取所有数据
            all_info = self.get_info() or {}
            all_behavior = self.get_behavior() or {}

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
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT category, COUNT(*) as count FROM user_info GROUP BY category")
            category_stats = cursor.fetchall()
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

    def import_from_json(self, file_path: str) -> bool:
        """
        从JSON文件导入数据

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
                        self.add_info(
                            info_type=info_type,
                            info_value=info_data.get('value', ''),
                            category=info_data.get('category', 'basic')
                        )
                    else:
                        self.add_info(
                            info_type=info_type,
                            info_value=str(info_data),
                            category='basic'
                        )

            # 导入用户行为
            if "user_behavior" in import_data:
                for behavior_type, behavior_data in import_data["user_behavior"].items():
                    if isinstance(behavior_data, dict):
                        self.add_behavior(
                            behavior_type=behavior_type,
                            behavior_pattern=behavior_data.get('pattern', ''),
                            description=behavior_data.get('description'),
                            priority=behavior_data.get('priority', 5)
                        )
                    else:
                        self.add_behavior(
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

    def backup_database(self, backup_path: str = None) -> bool:
        """
        备份数据库

        Args:
            backup_path: 备份文件路径

        Returns:
            操作是否成功
        """
        try:
            if backup_path is None:
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                backup_path = f"user_data_backup_{timestamp}.db"

            import shutil
            shutil.copy2(self.db_path, backup_path)

            print(f"数据库已备份到: {backup_path}")
            return True

        except Exception as e:
            print(f"备份数据库失败: {e}")
            return False

    def get_statistics(self) -> Dict:
        """
        获取数据统计信息

        Returns:
            统计信息字典
        """
        try:
            conn = self._get_connection()
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
            stats['avg_priority'] = round(cursor.fetchone()[0] or 0, 2)

            # 按分类统计信息
            cursor.execute('''
            SELECT category, COUNT(*) as count 
            FROM user_info 
            GROUP BY category 
            ORDER BY count DESC
            ''')
            stats['info_by_category'] = [dict(row) for row in cursor.fetchall()]

            # 最近更新时间
            cursor.execute('''
            SELECT MAX(updated_at) as last_info_update FROM user_info
            UNION ALL
            SELECT MAX(updated_at) as last_behavior_update FROM user_behavior
            ''')
            update_times = cursor.fetchall()
            stats['last_info_update'] = update_times[0][0]
            stats['last_behavior_update'] = update_times[1][0]

            conn.close()
            return stats

        except Exception as e:
            print(f"获取统计信息失败: {e}")
            return {}



def example_usage():
    """使用示例"""
    print("=" * 50)
    print("用户数据库管理系统示例")
    print("=" * 50)

    # 创建数据库实例
    db = SingleUserDatabase("example_user.db")

    try:
        # 1. 添加用户基本信息
        print("\n1. 添加用户基本信息:")
        db.add_info("name", "张三", "basic")
        db.add_info("gender", "男", "basic")
        db.add_info("age", "28", "basic")
        db.add_info("email", "zhangsan@example.com", "contact")
        db.add_info("phone", "13800138000", "contact")
        db.add_info("occupation", "软件工程师", "work")

        # 批量添加信息
        additional_info = {
            "birthday": "1995-05-15",
            "address": "北京市朝阳区",
            "education": "本科",
            "hobby": "编程、阅读、运动"
        }
        db.add_multiple_info(additional_info, "personal")

        # 2. 获取和显示用户信息
        print("\n2. 获取所有用户信息:")
        all_info = db.get_info()
        for info_type, info_data in all_info.items():
            print(f"  {info_type}: {info_data['value']} ({info_data['category']})")

        # 3. 添加用户行为模式
        print("\n3. 添加用户行为模式:")
        db.add_behavior(
            behavior_type="数据分析",
            behavior_pattern="使用Python pandas进行数据处理，matplotlib进行可视化",
            description="喜欢用Jupyter Notebook进行探索性数据分析",
            priority=8
        )

        db.add_behavior(
            behavior_type="文件处理",
            behavior_pattern="使用Python os和shutil库进行批量文件操作",
            description="习惯将常用操作封装成函数",
            priority=6
        )

        db.add_behavior(
            behavior_type="问题解决",
            behavior_pattern="先分析问题，再查找资料，最后编写代码实现",
            description="喜欢系统化的问题解决方法",
            priority=9
        )

        db.add_behavior(
            behavior_type="学习新技术",
            behavior_pattern="先看官方文档，再做小项目实践，最后总结分享",
            priority=7
        )

        # 4. 获取和显示用户行为
        print("\n4. 获取所有用户行为:")
        all_behavior = db.get_behavior()
        for behavior_type, behavior_data in all_behavior.items():
            print(f"  {behavior_type}:")
            print(f"    模式: {behavior_data['pattern']}")
            print(f"    优先级: {behavior_data['priority']}")
            if behavior_data['description']:
                print(f"    描述: {behavior_data['description']}")

        # 5. 搜索行为
        print("\n5. 搜索包含'Python'的行为:")
        search_results = db.search_behavior("Python")
        for result in search_results:
            print(f"  {result['behavior_type']}: {result['behavior_pattern'][:50]}...")

        # 6. 更新信息
        print("\n6. 更新用户年龄:")
        db.add_info("age", "29", "basic")

        # 7. 获取特定分类的信息
        print("\n7. 获取联系信息:")
        contact_info = db.get_info(category="contact")
        for info_type, info_data in contact_info.items():
            print(f"  {info_type}: {info_data['value']}")

        # 8. 获取统计信息
        print("\n8. 数据统计信息:")
        stats = db.get_statistics()
        print(f"  基本信息数量: {stats.get('total_info', 0)}")
        print(f"  行为模式数量: {stats.get('total_behavior', 0)}")
        print(f"  信息分类数量: {stats.get('info_categories', 0)}")
        print(f"  行为平均优先级: {stats.get('avg_priority', 0)}")

        # 9. 导出数据
        print("\n9. 导出数据到JSON文件:")
        db.export_to_json("user_data_example.json")

        # 10. 备份数据库
        print("\n10. 备份数据库:")
        db.backup_database()

        print("\n示例完成！")

    except Exception as e:
        print(f"示例执行过程中出错: {e}")


import json
from typing import Dict, List, Optional, Tuple, Any
from openai import OpenAI
from dotenv import load_dotenv
import os
load_dotenv()

API = os.getenv('BASIC_API_KEY')
BASE_URL = os.getenv("BASIC_BASE_URL")
MODEL = os.getenv("BASIC_MODEL")
class UserAssistant:
    """个人助手系统，结合本地数据库和大模型"""

    def __init__(self, db, openai_api_key: str=API, model: str = MODEL):
        """
        初始化助手

        Args:
            db: 数据库实例
            openai_api_key: OpenAI API密钥
            model: 使用的模型
        """
        self.db = db
        self.client = OpenAI(api_key=openai_api_key, base_url=BASE_URL)
        self.model = model

    def _format_info_for_prompt(self, info_list: List[List[str]]) -> str:
        """格式化信息列表为提示词字符串"""
        if not info_list:
            return "无"

        formatted = []
        for item in info_list:
            if len(item) >= 2:
                formatted.append(f"{item[0]}: {item[1]}")
        return "; ".join(formatted)

    def _format_behavior_for_prompt(self, behavior_list: List[List[str]]) -> str:
        """格式化行为模式列表为提示词字符串"""
        if not behavior_list:
            return "无"

        formatted = []
        for item in behavior_list:
            if len(item) >= 2:
                formatted.append(f"任务类型: {item[0]}, 解决方法: {item[1]}")
        return "; ".join(formatted)

    def analyze_query_with_llm(self, query: str) -> Dict[str, Any]:
        """
        使用大模型分析用户query，返回分析结果

        Returns:
            包含分析结果的字典
        """
        try:
            # 获取本地存储的信息
            user_info = self.db.get_info_simple()  # 格式: [['信息种类','具体值'], ...]
            user_behavior = self.db.get_behavior_simple()  # 格式: [['行为种类','具体模式'], ...]


            # 构建分析提示词
            analysis_prompt = f"""
            请分析用户的query，并返回JSON格式的分析结果。query是：{query}

            已知用户的个人信息：{user_info}
            已知用户的行为模式：{user_behavior}

            请分析以下方面，并返回JSON格式的结果：
            1. query中是否包含新的个人信息？如果有，提取出来
            2. query是否需要用到的个人信息？如果需要，指出需要哪些信息
            3. query是否与已知的任务类型相似？如果是，返回相似的任务类型和解决方法

            JSON格式要求：
            {{
                "query_analysis": "对query的分析描述",
                "needs_personal_info": true/false,
                "needed_info_types": ["需要的信息类型1", "需要的信息类型2", ...],
                "contains_new_info": true/false,
                "new_info": [["新信息类型1", "新信息值1"], ["新信息类型2", "新信息值2"], ...],
                "similar_to_known_task": true/false,
                "similar_task_types": ["相似任务类型1", "相似任务类型2", ...],
                "suggested_behavior_patterns": [["任务类型1", "解决方法1"], ["任务类型2", "解决方法2"], ...]
            }}

            注意：
            1. 如果query不需要个人信息，needs_personal_info为false，needed_info_types为空数组
            2. 如果没有新信息，contains_new_info为false，new_info为空数组
            3. 如果没有相似任务，similar_to_known_task为false，其他相关字段为空数组
            4. 确保返回的是有效的JSON格式
            """

            # 调用大模型进行分析
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": "你是一个专业的query分析助手，擅长分析用户需求并提取结构化信息。请只返回JSON格式的结果，不要添加其他内容。"
                    },
                    {
                        "role": "user",
                        "content": analysis_prompt
                    }
                ],
                temperature=0.1,  # 低温度以获得更确定的输出
                stream=False
            )

            # 解析JSON响应
            response_text = response.choices[0].message.content.strip()

            # 尝试从响应中提取JSON
            try:
                # 如果响应包含代码块标记，提取JSON部分
                if "```json" in response_text:
                    json_str = response_text.split("```json")[1].split("```")[0].strip()
                elif "```" in response_text:
                    json_str = response_text.split("```")[1].split("```")[0].strip()
                else:
                    json_str = response_text

                analysis_result = json.loads(json_str)
                return analysis_result

            except json.JSONDecodeError as e:
                print(f"解析大模型响应失败: {e}")
                print(f"响应内容: {response_text}")

                # 返回默认的分析结果
                return {
                    "query_analysis": "无法解析query",
                    "needs_personal_info": False,
                    "needed_info_types": [],
                    "contains_new_info": False,
                    "new_info": [],
                    "similar_to_known_task": False,
                    "similar_task_types": [],
                    "suggested_behavior_patterns": []
                }

        except Exception as e:
            print(f"分析query时出错: {e}")
            return {
                "query_analysis": f"分析过程中出错: {str(e)}",
                "needs_personal_info": False,
                "needed_info_types": [],
                "contains_new_info": False,
                "new_info": [],
                "similar_to_known_task": False,
                "similar_task_types": [],
                "suggested_behavior_patterns": []
            }
        
    def get_plan_from_chat(self,query: str, plan:str) -> Dict[str, Any]:
        """
        根据用户对话记录提取用户行为特征

        Args:
            query: 用户query
            plan: 初始计划
            change：用户修改意见

        Returns:
            最终回答
        """
        try:
            user_behavior = self.db.get_behavior_simple()
            behavior_analysis_prompt = f"""
                        请提取用户的行为特征。query是：{query}
    
                        规划：{plan}
                        本地保存的用户行为特征：{user_behavior}
                        请按照以下要求提取信息，并返回JSON格式的结果：
                        1. query的任务类型可以稍微具体一些，比如：ppt制作、写一篇文稿等等。
                        2. 规划中提取出主要的信息，比如使用了哪些工具，以及使用工具的顺序等。
                        3. 检索本地保存的用户行为特征中是否有类似的任务类型，比对规划是否与本地保存的规划类似（使用的工具和使用工具的顺序），如果不一样则需要更新本地保存的信息。
                        
                        JSON格式要求：
                        {{
                            "need_add_or_update": true/false,
                            "behavior_pattern": ["任务类型", "解决方法"]
                        }}
    
                        注意：
                        如果需要添加或更新用户行为信息，则"need_add_or_update"为true，且"behavior_pattern"包含任务类型和具体解决办法;
                        否则，"need_add_or_update"为false,且"behavior_pattern"为空。
                        """
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": "你是一个专业的用户行为分析助手，擅长分析并提取用户解决问题的思路。请只返回JSON格式的结果，不要添加其他内容。"
                    },
                    {
                        "role": "user",
                        "content": behavior_analysis_prompt
                    }
                ],
                temperature=0.1,  # 低温度以获得更确定的输出
                stream=False
            )
            response_text = response.choices[0].message.content.strip()
            # 尝试从响应中提取JSON
            try:
                # 如果响应包含代码块标记，提取JSON部分
                if "```json" in response_text:
                    json_str = response_text.split("```json")[1].split("```")[0].strip()
                elif "```" in response_text:
                    json_str = response_text.split("```")[1].split("```")[0].strip()
                else:
                    json_str = response_text

                analysis_result = json.loads(json_str)
                return analysis_result

            except json.JSONDecodeError as e:
                print(f"解析失败: {e}")
                print(f"响应内容: {response_text}")

                # 返回默认的分析结果
                return {
                            "need_add_or_update": False,
                            "behavior_pattern": []
                        }

        except Exception as e:
            print(f"分析query时出错: {e}")
            return {
                "need_add_or_update": False,
                "behavior_pattern": []
            }
    def get_answer_with_info(self, query: str, analysis_result: Dict[str, Any]) -> str:
        """
        基于分析结果获取最终回答，包含相关信息

        Args:
            query: 用户query
            analysis_result: 分析结果

        Returns:
            最终回答
        """
        try:
            # 获取本地存储的信息
            user_info = self.db.get_info_simple()
            user_behavior = self.db.get_behavior_simple()

            # 提取需要的信息
            needed_info = []
            if analysis_result.get("needs_personal_info", False):
                needed_types = analysis_result.get("needed_info_types", [])
                for info_type in needed_types:
                    # 从本地信息中查找
                    for info_item in user_info:
                        if info_item[0] == info_type:
                            needed_info.append(f"{info_type}: {info_item[1]}")
                            break

            # 提取相似的行为模式
            similar_behaviors = []
            if analysis_result.get("similar_to_known_task", False):
                suggested_patterns = analysis_result.get("suggested_behavior_patterns", [])
                for pattern in suggested_patterns:
                    if len(pattern) >= 2:
                        similar_behaviors.append(f"{pattern[0]}: {pattern[1]}")

            # 构建回答提示词
            info_context = ""
            if needed_info:
                info_context = f"用户的以下信息可能相关：{'; '.join(needed_info)}。"

            behavior_context = ""
            if similar_behaviors:
                behavior_context = f"用户之前处理类似任务的方式：{'; '.join(similar_behaviors)}。"

            answer_prompt = f"""
            请根据以下上下文回答用户的问题。

            用户问题：{query}

            {info_context}
            {behavior_context}

            请给出一个有帮助的回答。如果上下文中有相关信息，请在回答中使用这些信息。
            如果没有相关信息，就按照你的知识回答。
            """

            # 调用大模型获取回答
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": "你是一个有帮助的个人助手，善于利用已知信息回答问题。"
                    },
                    {
                        "role": "user",
                        "content": answer_prompt
                    }
                ],
                stream=False
            )

            return response.choices[0].message.content

        except Exception as e:
            print(f"获取回答时出错: {e}")
            return "抱歉，我在处理你的问题时遇到了困难。"

    def process_new_info(self, new_info_list: List[List[str]]) -> None:
        """
        处理并保存新信息到数据库

        Args:
            new_info_list: 新信息列表，格式[['信息类型', '信息值'], ...]
        """
        if not new_info_list:
            return

        for info_item in new_info_list:
            if len(info_item) >= 2:
                info_type = info_item[0].strip()
                info_value = info_item[1].strip()

                if info_type and info_value:
                    # 确定信息分类（简单分类逻辑）
                    category = self._determine_category(info_type)
                    # 添加到数据库
                    self.db.add_info(info_type, info_value, category)
                    print(f"已添加新信息: {info_type} = {info_value} (分类: {category})")

    def _determine_category(self, info_type: str) -> str:
        """根据信息类型确定分类"""
        info_type_lower = info_type.lower()

        # 基本信息分类
        if any(keyword in info_type_lower for keyword in ['name', '姓名', '名字']):
            return 'basic'
        elif any(keyword in info_type_lower for keyword in ['age', '年龄', '岁']):
            return 'basic'
        elif any(keyword in info_type_lower for keyword in ['gender', '性别']):
            return 'basic'
        elif any(keyword in info_type_lower for keyword in ['email', '邮箱', '邮件']):
            return 'contact'
        elif any(keyword in info_type_lower for keyword in ['phone', '电话', '手机']):
            return 'contact'
        elif any(keyword in info_type_lower for keyword in ['address', '地址', '住址']):
            return 'contact'
        elif any(keyword in info_type_lower for keyword in ['occupation', '职业', '工作']):
            return 'work'
        elif any(keyword in info_type_lower for keyword in ['hobby', '爱好', '兴趣']):
            return 'personal'
        else:
            return 'other'

    def process_new_behavior(self, query: str) -> None:
        """
        分析query并可能添加新的行为模式

        Args:
            query: 用户query
        """
        try:
            # 检查是否是任务类型的query
            task_keywords = ['如何', '怎么', '怎样', '方法', '解决', '处理', '步骤', '流程']
            if not any(keyword in query for keyword in task_keywords):
                return

            # 使用大模型提取任务类型和解决方法
            extraction_prompt = f"""
            请从用户的query中提取任务类型和推荐的解决方法。

            用户query: {query}

            请返回JSON格式：
            {{
                "is_task_query": true/false,
                "task_type": "提取出的任务类型",
                "solution_pattern": "推荐的解决方法"
            }}

            如果这不是一个任务查询，is_task_query为false。
            """

            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": "你擅长从用户问题中提取任务类型和解决方法。请只返回JSON。"
                    },
                    {
                        "role": "user",
                        "content": extraction_prompt
                    }
                ],
                temperature=0.1,
                stream=False
            )

            response_text = response.choices[0].message.content.strip()

            try:
                # 提取JSON
                if "```json" in response_text:
                    json_str = response_text.split("```json")[1].split("```")[0].strip()
                elif "```" in response_text:
                    json_str = response_text.split("```")[1].split("```")[0].strip()
                else:
                    json_str = response_text

                result = json.loads(json_str)

                if result.get("is_task_query", False):
                    task_type = result.get("task_type", "")
                    solution_pattern = result.get("solution_pattern", "")

                    if task_type and solution_pattern:
                        # 添加到行为模式数据库
                        self.db.add_behavior(
                            behavior_type=task_type,
                            behavior_pattern=solution_pattern,
                            description=f"从用户query中提取: {query}",
                            priority=5
                        )
                        print(f"已添加新的行为模式: {task_type}")

            except json.JSONDecodeError:
                print("无法解析行为模式提取结果")

        except Exception as e:
            print(f"处理新行为模式时出错: {e}")

    def handle_query(self, query: str) -> Tuple[str, Dict[str, Any]]:
        """
        处理用户query的主函数

        Args:
            query: 用户query

        Returns:
            (answer, analysis_result): 回答和分析结果
        """

        print("开始提取用户输入相关信息")
        analysis_result = self.analyze_query_with_llm(query)


        if analysis_result.get("contains_new_info", False):
            new_info = analysis_result.get("new_info", [])
            self.process_new_info(new_info)

        self.process_new_behavior(query)
        # answer = self.get_answer_with_info(query, analysis_result)
        print(analysis_result)
        return analysis_result

    def interactive_mode(self):
        """交互式模式"""
        print("=" * 50)
        print("个人助手系统")
        print("输入 '退出' 或 'exit' 结束对话")
        print("=" * 50)

        while True:
            try:
                query = input("\n请输入你的问题: ").strip()

                if query.lower() in ['退出', 'exit', 'quit', 'q']:
                    print("再见！")
                    break

                if not query:
                    continue

                # 处理query
                answer, analysis_result = self.handle_query(query)

                # 显示回答
                print("\n" + "=" * 50)
                print("助手回答:")
                print(answer)
                print("=" * 50)

                # 显示分析摘要（可选）
                show_details = input("\n是否查看分析详情? (y/n): ").strip().lower()
                if show_details == 'y':
                    print("\n分析详情:")
                    print(f"查询分析: {analysis_result.get('query_analysis', '无')}")
                    print(f"需要个人信息: {analysis_result.get('needs_personal_info', False)}")
                    print(f"需要的信息类型: {analysis_result.get('needed_info_types', [])}")
                    print(f"包含新信息: {analysis_result.get('contains_new_info', False)}")
                    print(f"新信息: {analysis_result.get('new_info', [])}")
                    print(f"相似任务: {analysis_result.get('similar_to_known_task', False)}")
                    print(f"相似任务类型: {analysis_result.get('similar_task_types', [])}")

            except KeyboardInterrupt:
                print("\n\n对话已结束")
                break
            except Exception as e:
                print(f"处理过程中出错: {e}")


# ==================== 使用示例 ====================

def example_usage():
    """使用示例"""

    # 初始化数据库
    

    # 添加一些初始信息
    initial_info = {
        "姓名": "张三",
        "年龄": "28",
        "职业": "软件工程师",
        "邮箱": "zhangsan@example.com"
    }
    for info_type, info_value in initial_info.items():
        db_manager.add_info(info_type, info_value)

    # 添加一些初始行为模式
    initial_behaviors = [
        ("数据分析", "使用Python pandas库"),
        ("文件处理", "使用Python os和shutil库"),
        ("问题解决", "先分析再实现")
    ]
    for behavior_type, behavior_pattern in initial_behaviors:
        db_manager.add_behavior(behavior_type, behavior_pattern)

    # 2. 初始化助手（需要OpenAI API密钥）
    # 请替换为您的实际API密钥
    OPENAI_API_KEY = API

    if OPENAI_API_KEY == "your-openai-api-key-here":
        print("请先设置正确的OpenAI API密钥")
        return

    assistant = UserAssistant(db_manager, API, model=MODEL)

    # 3. 测试示例查询
    test_queries = [
        "我的年龄是多少？",
        "我今年40岁了",  # 更新年龄
        "我的年龄是多少？",
        "如何分析数据？",
    ]

    for query in test_queries:
        print(f"\n{'=' * 60}")
        print(f"测试查询: {query}")
        print(f"{'=' * 60}")

        answer, analysis = assistant.handle_query(query)
        print(f"\n助手回答: {answer}")

    # 4. 查看更新后的数据库
    print(f"\n{'=' * 60}")
    print("更新后的用户信息:")
    all_info = db_manager.get_info()
    for info in all_info:
        print(f"  {info[0]}: {info[1]}")

    print(f"\n更新后的行为模式:")
    all_behavior = db_manager.get_behavior()
    for behavior in all_behavior:
        print(f"  {behavior[0]}: {behavior[1]}")

    # 5. 启动交互模式（可选）
    # assistant.interactive_mode()


if __name__ == "__main__":
    # 运行示例
    example_usage()
    # 注意：实际使用时需要设置正确的OpenAI API密钥