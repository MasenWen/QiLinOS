# nex-agent Mem0 本地部署 + 麒麟 Embedding SDK 方案

## 一、架构

```
nex-agent
│
├─ Mem0 记忆层
│   ├─ Embedding:  麒麟 ONNX (gte-base, 768维, 本地推理)
│   ├─ 向量库:     Qdrant 本地模式 (~/.nex-agent/mem0/qdrant/)
│   └─ 事实提取:   Qwen3-Max (DashScope API)
│
├─ RAG 知识库 (保留)
│   └─ LightRAG + PostgreSQL + 麒麟 embedding
│
└─ Hermes Bridge (保留)
```

## 二、Python 依赖

```bash
pip install mem0ai qdrant-client onnxruntime tokenizers
```

## 三、需要新建的文件

| 文件 | 说明 |
|------|------|
| `src/memory/__init__.py` | 注册麒麟 embedder 到 Mem0 Factory + 绕过 Pydantic 白名单 |
| `src/memory/kylin_embedder.py` | 麒麟 ONNX → Mem0 EmbeddingBase |
| `src/memory/mem0_store.py` | Mem0 单例，对外暴露 `search()` / `add()` |

## 四、需要修改的文件

| 文件 | 位置 | 操作 |
|------|------|------|
| `agent.py` | 第 2 行 import 区域 | 加 `from src.memory.mem0_store import mem0_store` |
| `agent.py` | `run_workflow_with_review` 中，user_input 构建完成后 | 前置钩子：`mem0_store.search_as_prompt()` |
| `agent.py` | workflow 完成后，`update_session_state("none")` 之前 | 后置钩子：`mem0_store.add()` |

## 五、代码

### 5.1 `src/memory/kylin_embedder.py`

```python
"""麒麟 ONNX Embedder — Mem0 EmbeddingBase 接口"""
import numpy as np
from mem0.embeddings.base import EmbeddingBase
from mem0.configs.embeddings.base import BaseEmbedderConfig
from pathlib import Path
from typing import Optional, Literal

ONNX_PATH = (
    "/usr/share/kylin-ai/model-repository/embd_gte-base_uint8-text/1/"
    "gte-base-multilingual-model_QUInt8.onnx"
)
TOKENIZER_PATH = (
    "/usr/share/kylin-ai/model-repository/"
    "tokenizer_gte-base_uint8-text/tokenizer.json"
)


class KylinEmbedder(EmbeddingBase):

    def __init__(self, config: Optional[BaseEmbedderConfig] = None):
        super().__init__(config)
        import onnxruntime as ort
        from tokenizers import Tokenizer

        if not Path(ONNX_PATH).exists():
            raise FileNotFoundError(
                f"模型不存在: {ONNX_PATH}\n"
                f"请安装: sudo apt install kylin-ai-abstract-models"
            )

        self._session = ort.InferenceSession(ONNX_PATH)
        self._tokenizer = Tokenizer.from_file(TOKENIZER_PATH)
        self._tokenizer.enable_padding(pad_id=0, pad_token="[PAD]")
        self._tokenizer.enable_truncation(max_length=512)

    def embed(self, text, memory_action: Optional[Literal[
        "add", "search", "update"]] = None):
        return self.embed_batch([text], memory_action)[0]

    def embed_batch(self, texts, memory_action=None):
        result = []
        for text in texts:
            enc = self._tokenizer.encode(text)
            ids = np.array([enc.ids], dtype=np.int64)
            mask = np.array([enc.attention_mask], dtype=np.int64)
            out = self._session.run(
                None, {"input_ids": ids, "attention_mask": mask})
            m = mask[:, :, None].astype(np.float32)
            emb = (out[0] * m).sum(axis=1) / m.sum(axis=1).clip(min=1e-9)
            vec = emb[0].astype(np.float32)
            vec = vec / (np.linalg.norm(vec) + 1e-9)
            result.append(vec.tolist())
        return result
```

### 5.2 `src/memory/__init__.py`

```python
"""注册麒麟 Embedder 到 Mem0 Factory"""
from mem0.utils.factory import EmbedderFactory

EmbedderFactory.provider_to_class["kylin_onnx"] = (
    "src.memory.kylin_embedder.KylinEmbedder"
)
```

### 5.3 `src/memory/mem0_store.py`

```python
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
            return self._memory.search(
                query, user_id=user_id or self._default_user,
                limit=top_k, threshold=0.3,
            )
        except Exception:
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
            self._memory.add(
                messages, user_id=user_id or self._default_user)
        except Exception:
            pass

    def add_fact(self, fact: str, user_id: str = None):
        self._memory.add(fact, user_id=user_id or self._default_user)

    def delete_all(self, user_id: str = None):
        self._memory.delete_all(user_id=user_id or self._default_user)


mem0_store = Mem0Store()
```

### 5.4 `agent.py` 修改点

**文件顶部添加 import：**

```python
from src.memory.mem0_store import mem0_store
```

**前置钩子（约 line 272，`db_manager.update_session_state(session_id, "running")` 之后）：**

```python
        # === Mem0 前置钩子：自动注入用户记忆 ===
        try:
            memory_ctx = mem0_store.search_as_prompt(user_input)
            if memory_ctx:
                user_input = memory_ctx + "\n\n" + user_input
        except Exception:
            pass
```

**后置钩子（约 line 424，`update_session_state(session_id, "none")` 之后，`break` 之前）：**

```python
                        # === Mem0 后置钩子：自动提取记忆 ===
                        try:
                            msgs = value.get("messages", [])
                            if len(msgs) >= 2:
                                mem0_store.add([
                                    {"role": "user", "content": str(msgs[-2].content)[:500]},
                                    {"role": "assistant", "content": str(msgs[-1].content)[:500]},
                                ])
                        except Exception:
                            pass
```

## 六、关键技术点

### 6.1 Pydantic 白名单绕过

Mem0 v2.0.7 的 `EmbedderConfig` 用 Pydantic validator 限制了 provider 只能是 `openai / ollama / huggingface / ...`。绕过方式：

```python
cfg = MemoryConfig(provider="openai", ...)   # 用 openai 通过校验
cfg.embedder.provider = "kylin_onnx"          # 构造后替换
Memory(cfg)  → EmbedderFactory.create("kylin_onnx", ...) → 找到我们的 KylinEmbedder
```

### 6.2 Embedding 后端选择

| 方案 | provider 名 | 文件 |
|------|:-----------:|------|
| 麒麟 ONNX (当前可用) | `kylin_onnx` | `kylin_embedder.py` |
| 麒麟 C API (待引擎修复) | `kylin_sdk` | 封装 `kylin_embedding_sdk.py` |

### 6.3 Qdrant 生产模式

当前文档用 Qdrant 本地模式。如果需要用 `kylin-ai-vector-engine` (Milvus)，替换 vector_store 配置段为：

```python
"vector_store": {
    "provider": "kylin_milvus",
    "config": {
        "url": f"unix:/tmp/kylin-ai-vector-engine-{os.getuid()}.sock",
        "token": "",
        "collection_name": "mem0_memories",
        "embedding_model_dims": 768,
        "metric_type": "COSINE",
        "db_name": "",
    },
}
```

需同时写一个精简的 Milvus vector store 适配器（无 BM25），替换掉 Mem0 内置的版本。

## 七、验证

```bash
uv run python -c "
import src.memory
from src.memory.mem0_store import mem0_store

mem0_store.add([
    {'role':'user','content':'我叫张三，在北京工作'},
    {'role':'assistant','content':'好的记住了'}
])
for r in mem0_store.search('这个人叫什么'):
    print(f\"[{r['score']:.2f}] {r['memory']}\")
mem0_store.delete_all()
"
```

## 八、调用时机

| 触发点 | 操作 | 位置 |
|--------|------|------|
| 用户消息到达 | `search_as_prompt(query)` → 注入记忆 | agent.py 前置钩子 |
| 工作流完成 | `add([{user}, {assistant}])` → 提取事实 | agent.py 后置钩子 |

**全部自动，用户无感知。**
