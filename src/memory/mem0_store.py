"""Mem0 记忆存储 — 麒麟 Embedding + 本地 Qdrant"""
import os
from mem0 import Memory
from mem0.configs.base import MemoryConfig

import src.memory  # noqa: F401

MEM0_DIR = os.path.expanduser("~/.nex-agent/mem0")
os.makedirs(MEM0_DIR, exist_ok=True)

from dotenv import load_dotenv
load_dotenv()
QWEN_KEY = os.getenv("QWEN_API_KEY", "")

# 用 openai 做 provider 名通过 Pydantic 校验（实际类已被替换）
_config_dict = {
    "embedder": {
        "provider": "openai",
        "config": {"model": "gte-base", "embedding_dims": 768},
    },
    "vector_store": {
        "provider": "qdrant",
        "config": {
            "path": os.path.join(MEM0_DIR, "qdrant"),
            "embedding_model_dims": 768,
            "on_disk": True,
        },
    },
    "llm": {
        "provider": "openai",
        "config": {
            "model": "qwen3-max",
            "api_key": QWEN_KEY,
            "openai_base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        },
    },
    "history_db_path": os.path.join(MEM0_DIR, "history.db"),
    "version": "v1.1",
}


class Mem0Store:
    """Mem0 记忆存储 — 全局单例"""

    def __init__(self):
        cfg = MemoryConfig(**_config_dict)
        # 替换为麒麟 embedder（绕过 Pydantic 白名单校验）
        cfg.embedder.provider = "kylin_onnx"
        self._memory = Memory(cfg)
        self._default_user = "nex_user"

    def search(self, query: str, user_id: str = None, top_k: int = 5):
        try:
            result = self._memory.search(
                query,
                filters={"user_id": user_id or self._default_user},
                limit=top_k,
                threshold=0.3,
            )
            items = result.get("results", []) if isinstance(result, dict) else []
            print(f"[Mem0] search '{query[:20]}' → {len(items)} 条")
            return items
        except Exception as e:
            print(f"[Mem0] search 失败: {e}")
            return []

    def search_as_prompt(self, query: str, user_id: str = None) -> str:
        results = self.search(query, user_id)
        if not results:
            return ""
        return "[用户相关记忆]\n" + "\n".join(
            f"- {r['memory']}" for r in results
        )

    def add(self, messages: list[dict], user_id: str = None):
        try:
            result = self._memory.add(
                messages,
                user_id=user_id or self._default_user,
                prompt="请用中文提取并存储用户的事实信息。",  # 强制中文输出
            )
            print(f"[Mem0] add 成功: {len(result) if result else 0} 条记忆")
        except Exception as e:
            print(f"[Mem0] add 失败: {e}")

    def add_fact(self, fact: str, user_id: str = None):
        self._memory.add(fact, user_id=user_id or self._default_user)

    def delete_all(self, user_id: str = None):
        self._memory.delete_all(user_id=user_id or self._default_user)


mem0_store = Mem0Store()

# 消除 QdrantClient.__del__ 在 Python 退出时的报错
# 根因: qdrant-client 本地模式在 close() 中 import portalocker，
# 但 Python 退出时 import 机制已卸载 → ImportError
# 解决: atexit 中提前关闭（此时 import 仍可用），然后禁用 __del__
import atexit
from qdrant_client import QdrantClient
_qdrant_del = QdrantClient.__del__
QdrantClient.__del__ = lambda self: None  # 禁用自动清理

def _cleanup():
    try:
        _qdrant_del(mem0_store._memory.vector_store.client)
    except Exception:
        pass
atexit.register(_cleanup)
