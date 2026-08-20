"""Mem0 记忆存储 — 麒麟 Embedding + 本地 Qdrant"""
import os
# 禁用 mem0 PostHog 遥测（P1-1 内存泄漏修复 + 隐私）：必须在 import mem0 前设置
os.environ["MEM0_TELEMETRY"] = "False"
from mem0 import Memory
from mem0.configs.base import MemoryConfig

import src.memory  # noqa: F401
from src.memory.threat_patterns import is_safe
import logging

MEM0_DIR = os.path.expanduser("~/.nex-agent/mem0")
os.makedirs(MEM0_DIR, exist_ok=True)

from dotenv import load_dotenv
load_dotenv()
QWEN_KEY = os.getenv("QWEN_API_KEY", "")

logger = logging.getLogger(__name__)
# 用 openai 做 provider 名通过 Pydantic 校验（实际类已被替换）
_config_dict = {
    "embedder": {
        "provider": "openai",
        "config": {"model": "gte-base", "embedding_dims": 768},
    },
    # "embedder": {
    #     "provider": "gte_zh_onnx",
    #     "config": {"model": "gte-base-zh", "embedding_dims": 768},
    # },
    "vector_store": {
        "provider": "qdrant",  # 绕过 Pydantic 校验，实际类已被替换
        "config": {
            "collection_name": "mem0_memories",
            "embedding_model_dims": 768,
            "path": os.path.expanduser("~/.nex-agent/mem0_vectordb.db"),
            "on_disk": True,
        },
    },
    "llm": {
        "provider": "openai",  # 占位通过 Pydantic 校验，实际后替换为 kylin_sdk
        "config": {
            "model": "qwen3.7-max",
        },
    },
    "history_db_path": os.path.join(MEM0_DIR, "history.db"),
    "version": "v1.1",
}


class Mem0Store:
    """Mem0 记忆存储 — 全局单例"""

    def __init__(self):
        cfg = MemoryConfig(**_config_dict)
        # 替换为麒麟后端（绕过 Pydantic 白名单校验）
        cfg.embedder.provider = "kylin_sdk"
        cfg.vector_store.provider = "kylin_vectordb"
        cfg.llm.provider = "kylin_sdk"  # 麒麟千问，零 key
        self._default_user = "nex_user"
        self._degraded = False
        # 禁用 mem0 遥测(PostHog 客户端+后台队列) — P1-1 内存泄漏修复
        try:
            self._memory = Memory(cfg)
        except Exception as e:
            # MilvusLite 单实例锁：向量库文件被其它进程独占 →
            # 降级到临时向量库，保证服务可多实例启动（数据不持久）
            import tempfile
            db_path = _config_dict["vector_store"]["config"]["path"]
            tmp_db = os.path.join(tempfile.mkdtemp(prefix="mem0_degraded_"), "mem0_vectordb.db")
            logger.warning("[Mem0] 向量库 %s 被占用，降级到临时库（重启后记忆不保留）: %s", db_path, e)
            cfg.vector_store.config.path = tmp_db  # QdrantConfig 是 pydantic 对象，属性赋值
            self._memory = Memory(cfg)
            self._degraded = True
        
        self._default_user = "nex_user"

    def search(self, query: str, user_id: str = None, top_k: int = 5):
        try:
            result = self._memory.search(
                query,
                filters={"user_id": user_id or self._default_user},
                limit=top_k,
                threshold=0.5,
            )
            items = result.get("results", []) if isinstance(result, dict) else []
            print(f"[Mem0] search '{query[:20]}' → {len(items)} 条")
            for it in items:
                print(f"  [{it.get('score', 0):.4f}] {it.get('memory', '')[:50]}")
            return items
        except Exception as e:
            print(f"[Mem0] search 失败: {e}")
            return []

    def list_all(self, user_id: str = None, top_k: int = 100) -> list:
        """列出全部记忆（用于记忆面板）。"""
        try:
            result = self._memory.get_all(
                filters={"user_id": user_id or self._default_user},
                top_k=top_k,
            )
            items = result.get("results", []) if isinstance(result, dict) else (result or [])
            print(f"[Mem0] list_all -> {len(items)} 条")
            return items
        except Exception as e:
            print(f"[Mem0] list_all 失败: {e}")
            return []

    def search_as_prompt(self, query: str, user_id: str = None) -> str:
        results = self.search(query, user_id)
        if not results:
            return ""
        return "[用户相关记忆]\n" + "\n".join(
            f"- {r['memory']}" for r in results
        )

    MAX_MEMORIES = 200  # 长期记忆上限，超出自动淘汰最旧（防存储爆炸）
    # 快照类关键词: 同类只保留最新 N 条（治语义重复膨胀）
    SNAPSHOT_CATS = {
        "桌面": 3, "CPU": 3, "负载": 3, "内存": 3, "进程": 3,
        "网络": 4, "时区": 3, "磁盘": 3, "存储": 3, "电池": 2, "时间": 2,
    }

    def _created_key(self, it):
        return str(it.get("created_at") or it.get("id") or "")

    def _enforce_cap(self, user_id=None):
        """记忆条数上限：超过 MAX_MEMORIES 删除最旧的。"""
        try:
            items = self.list_all(user_id=user_id, top_k=self.MAX_MEMORIES + 100)
            if len(items) > self.MAX_MEMORIES:
                items_sorted = sorted(items, key=self._created_key)
                over = items_sorted[: len(items) - self.MAX_MEMORIES]
                for it in over:
                    m_id = it.get("id")
                    if m_id:
                        try:
                            self._memory.delete(memory_id=m_id)
                        except Exception:
                            pass
                print(f"[Mem0] 上限控制: 从 {len(items)} 裁剪到 {self.MAX_MEMORIES}")
        except Exception as e:
            print(f"[Mem0] 上限控制失败: {e}")

    def dedupe_categories(self, user_id=None):
        """同类快照记忆只保留最新 N 条，防止语义重复膨胀。"""
        try:
            items = self.list_all(user_id=user_id, top_k=500)
            items_sorted = sorted(items, key=self._created_key)
            to_delete = set()
            for cat, keep in self.SNAPSHOT_CATS.items():
                hits = [it for it in items_sorted
                        if cat in (it.get("memory") or "")]
                for it in hits[:-keep]:
                    m_id = it.get("id")
                    if m_id:
                        to_delete.add(m_id)
            for m_id in to_delete:
                try:
                    self._memory.delete(memory_id=m_id)
                except Exception:
                    pass
            if to_delete:
                print(f"[Mem0] 快照裁剪: 删除 {len(to_delete)} 条")
            return len(to_delete)
        except Exception as e:
            print(f"[Mem0] 快照裁剪失败: {e}")
            return 0

    def add(self, messages: list[dict], user_id: str = None):
        try:
            # 去重：检查是否已有高度相似的记忆
            user_msg = messages[0]["content"] if messages else ""
            if user_msg:
                existing = self.search(user_msg, user_id=user_id, top_k=2)
                if existing and existing[0].get("score", 0) > 0.87:
                    print(f"[Mem0] 跳过重复: {user_msg[:30]}...")
                    return

                # --- 新增：威胁扫描 (写入前扫描)---
                if not is_safe(user_msg):
                    print(f"[Mem0] ⚠ 跳过不安全内容: {user_msg[:30]}...")
                    logger.warning("[Mem0] 拦截威胁内容: %s", user_msg[:60])
                    return

            result = self._memory.add(
                messages,
                user_id=user_id or self._default_user,
                prompt="请用中文提取并存储用户的事实信息，只提取用户明确表达的个人偏好/习惯/信息，"
                       "不要记录系统的猜测、推荐、提醒或临时任务。",
            )
            print(f"[Mem0] add 成功: {len(result) if result else 0} 条记忆")
            self._enforce_cap(user_id)
        except Exception as e:
            print(f"[Mem0] add 失败: {e}")

    def add_fact(self, fact: str, user_id: str = None):
        self._memory.add(fact, user_id=user_id or self._default_user)

    def delete_all(self, user_id: str = None):
        self._memory.delete_all(user_id=user_id or self._default_user)


mem0_store = Mem0Store()

# # 消除 QdrantClient.__del__ 在 Python 退出时的报错
# # 根因: qdrant-client 本地模式在 close() 中 import portalocker，
# # 但 Python 退出时 import 机制已卸载 → ImportError
# # 解决: atexit 中提前关闭（此时 import 仍可用），然后禁用 __del__
# import atexit
# from qdrant_client import QdrantClient
# _qdrant_del = QdrantClient.__del__
# QdrantClient.__del__ = lambda self: None  # 禁用自动清理
#
# def _cleanup():
#     try:
#         _qdrant_del(mem0_store._memory.vector_store.client)
#     except Exception:
#         pass
# atexit.register(_cleanup)
