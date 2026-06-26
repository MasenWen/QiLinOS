# nex-agent 自托管部署 Mem0 + 麒麟 Embedding SDK 方案

## 一、与嵌入式方案的区别

| | 嵌入式 (上一份文档) | 自托管 (本文档) |
|------|------|------|
| Qdrant | 本地文件模式 (`path=/tmp/...`) | **独立服务进程** (HTTP/gRPC) |
| Mem0 | Python 库内嵌 | **Python 库 + 外部 Qdrant 服务** |
| 数据持久化 | 文件级 | 服务级，支持多客户端 |
| 适用场景 | 单机开发 | **生产环境** |
| 麒麟 Embedding | 相同 | 相同 |

## 二、架构

```
┌─────────────────────────────────────────────────────┐
│                    nex-agent                         │
│  ┌──────────┐  ┌──────────┐  ┌───────────────────┐  │
│  │ agent.py │  │ mem0_store│  │ KylinEmbedder     │  │
│  │ (前置/后 │  │ .add()   │  │ (ONNX 本地推理)    │  │
│  │  置钩子) │  │ .search()│  │ gte-base 768维     │  │
│  └──────────┘  └────┬─────┘  └───────────────────┘  │
│                     │                                │
│                     │ HTTP (localhost:6333)           │
│                     ▼                                │
│  ┌──────────────────────────────────────────────┐    │
│  │         Qdrant Server (独立进程)              │    │
│  │         REST API :6333 / gRPC :6334          │    │
│  │         数据目录: ~/.nex-agent/qdrant_data/  │    │
│  └──────────────────────────────────────────────┘    │
│                                                      │
│  ┌──────────────────────────────────────────────┐    │
│  │         Mem0 (Python 库)                      │    │
│  │         LLM 事实提取: Qwen3-Max              │    │
│  │         History DB: ~/.nex-agent/mem0/       │    │
│  └──────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────┘
```

## 三、部署 Qdrant Server

### 3.1 方式 A：Docker（推荐）

```bash
docker run -d \
  --name qdrant \
  -p 6333:6333 \
  -p 6334:6334 \
  -v ~/.nex-agent/qdrant_data:/qdrant/storage \
  qdrant/qdrant:latest
```

### 3.2 方式 B：二进制部署

```bash
# 下载 Qdrant 二进制
wget https://github.com/qdrant/qdrant/releases/latest/download/qdrant-x86_64-unknown-linux-gnu.tar.gz
tar xzf qdrant-x86_64-unknown-linux-gnu.tar.gz

# 启动
./qdrant --storage-snapshots-path ~/.nex-agent/qdrant_data/snapshots \
         --storage-path ~/.nex-agent/qdrant_data
```

### 3.3 方式 C：pip 安装并启动（最简单，无需 Docker）

```bash
pip install qdrant-client

# Qdrant 自带二进制 runner（qdrant 0.11+ 支持）
# 或者用 Python 启动嵌入式服务模式：
python -c "
from qdrant_client import QdrantClient
# 启动后会监听 6333/6334 端口
"
```

> **注意**：pip 安装的 `qdrant-client` 只包含客户端库。要运行 Qdrant Server，需要 Docker 或二进制。
> 如果无法 Docker，最简单的自托管方式是使用 Qdrant 的 HTTP 模式连接麒麟系统上已有的服务。

### 3.4 方式 D：复用麒麟系统 Milvus（无需额外部署）

```python
# 直接用麒麟系统已有的 kylin-ai-vector-engine
# 替换 Qdrant，使用 Mem0 的 Milvus 适配器
"vector_store": {
    "provider": "milvus",
    "config": {
        "url": f"unix:/tmp/kylin-ai-vector-engine-{os.getuid()}.sock",
        ...
    },
}
```

> **Milvus 适配器需要二次开发**：Mem0 v2.0.7 内置的 Milvus 适配器使用 BM25 混合索引（SPARSE_FLOAT_VECTOR），kylin-ai-vector-engine (Milvus-Lite) 不支持。需要写精简适配器去掉 BM25 字段。代码见附录。

## 四、需要新建的文件

| 文件 | 说明 |
|------|------|
| `src/memory/__init__.py` | 注册麒麟 embedder |
| `src/memory/kylin_embedder.py` | 麒麟 ONNX → Mem0 EmbeddingBase |
| `src/memory/kylin_milvus_store.py` | **自托管专用** — Mem0 + 麒麟 Milvus 向量库 |
| `src/memory/mem0_store.py` | Mem0 单例（自动选择后端） |

## 五、代码

### 5.1 `src/memory/kylin_embedder.py`

```python
"""麒麟 ONNX Embedder — Mem0 EmbeddingBase"""
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

    def embed(self, text, memory_action=None):
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

### 5.3 `src/memory/kylin_milvus_store.py`

> 精简 Milvus 适配器 — 去掉 BM25，兼容 kylin-ai-vector-engine

```python
"""麒麟 Milvus 向量库 → Mem0 VectorStoreBase (无 BM25)"""
import logging, os
from typing import Dict, Optional
from pydantic import BaseModel
from mem0.vector_stores.base import VectorStoreBase
from pymilvus import MilvusClient, DataType
from pymilvus.milvus_client.index import IndexParams, IndexParam

logger = logging.getLogger(__name__)


class OutputData(BaseModel):
    id: Optional[str]
    score: Optional[float]
    payload: Optional[Dict]


class KylinMilvusDB(VectorStoreBase):
    """精简 Milvus 适配器 — 无 BM25，兼容麒麟向量引擎"""

    def __init__(self, url, token, collection_name,
                 embedding_model_dims, metric_type, db_name):
        self.collection_name = collection_name
        self.embedding_model_dims = embedding_model_dims
        self.metric_type = metric_type
        self.client = MilvusClient(uri=url)
        self.create_col(collection_name, embedding_model_dims, metric_type)

    def create_col(self, name, dim, metric="COSINE"):
        if self.client.has_collection(name):
            self.client.load_collection(name)
            return
        self.client.create_collection(
            collection_name=name, dimension=dim,
            metric_type=metric, auto_id=False,
            datatype=DataType.FLOAT_VECTOR,
        )
        idx = IndexParams([IndexParam(
            field_name="vector", index_type="HNSW", index_name="hnsw",
            metric_type=metric,
            params={"M": 16, "efConstruction": 200},
        )])
        self.client.create_index(collection_name=name, index_params=idx)
        self.client.load_collection(name)

    def insert(self, ids, vectors, payloads, **kwargs):
        data = []
        for i, vec, meta in zip(ids, vectors, payloads):
            data.append({
                "id": str(i), "vector": vec,
                "metadata": meta or {},
            })
        self.client.insert(collection_name=self.collection_name, data=data)

    def _create_filter(self, filters):
        if not filters:
            return None
        parts = []
        for k, v in filters.items():
            if isinstance(v, str):
                parts.append(f'(metadata["{k}"] == "{v}")')
            else:
                parts.append(f'(metadata["{k}"] == {v})')
        return " and ".join(parts) if parts else None

    def _parse_output(self, data):
        result = []
        for item in data:
            raw = item.get("distance")
            score = 1.0 / (1.0 + raw) if raw and self.metric_type == "L2" else raw
            result.append(OutputData(
                id=item.get("id"), score=score,
                payload=item.get("entity", {}).get("metadata"),
            ))
        return result

    def search(self, query, vectors, top_k=5, filters=None):
        qf = self._create_filter(filters) if filters else None
        hits = self.client.search(
            collection_name=self.collection_name,
            data=[vectors], limit=top_k,
            filter=qf, output_fields=["*"],
        )
        return self._parse_output(hits[0])

    def keyword_search(self, query, top_k=5, filters=None):
        return None

    def delete(self, vector_id):
        self.client.delete(
            collection_name=self.collection_name, ids=[str(vector_id)])

    def update(self, vector_id=None, vector=None, payload=None):
        if vector is None or payload is None:
            existing = self.client.get(
                collection_name=self.collection_name, ids=[str(vector_id)])
            if not existing:
                raise ValueError(f"ID {vector_id} 不存在")
            vector = vector or existing[0].get("vector")
            payload = payload or existing[0].get("metadata")
        self.client.upsert(
            collection_name=self.collection_name,
            data=[{"id": str(vector_id), "vector": vector, "metadata": payload}],
        )

    def get(self, vector_id):
        result = self.client.get(
            collection_name=self.collection_name, ids=[str(vector_id)])
        if not result:
            return None
        return OutputData(
            id=result[0].get("id"), score=None,
            payload=result[0].get("metadata"),
        )

    def list_cols(self):
        return self.client.list_collections()

    def delete_col(self):
        self.client.drop_collection(collection_name=self.collection_name)

    def col_info(self):
        return self.client.get_collection_stats(
            collection_name=self.collection_name)

    def list(self, filters=None, top_k=100):
        qf = self._create_filter(filters) if filters else None
        result = self.client.query(
            collection_name=self.collection_name,
            filter=qf, limit=top_k, output_fields=["*"],
        )
        return [[OutputData(
            id=r.get("id"), score=None, payload=r.get("metadata"),
        ) for r in result]]

    def reset(self):
        self.delete_col()
        self.create_col(
            self.collection_name,
            self.embedding_model_dims,
            self.metric_type,
        )
```

**注册到 Mem0 Factory：** 在 `src/memory/__init__.py` 中添加：

```python
from mem0.utils.factory import VectorStoreFactory

VectorStoreFactory.provider_to_class["kylin_milvus"] = (
    "src.memory.kylin_milvus_store.KylinMilvusDB"
)
```

### 5.4 `src/memory/mem0_store.py`

```python
"""Mem0 记忆存储 — 麒麟 Embedding + 麒麟向量数据库（自托管）"""
import os
from mem0 import Memory
from mem0.configs.base import MemoryConfig

import src.memory  # noqa: F401

MEM0_DIR = os.path.expanduser("~/.nex-agent/mem0")
os.makedirs(MEM0_DIR, exist_ok=True)

from dotenv import load_dotenv
load_dotenv()
QWEN_KEY = os.getenv("QWEN_API_KEY", "")

# ============================================================
# 后端选择
# ============================================================
# VECTOR_BACKEND = "qdrant_server"   # Qdrant 独立服务 (Docker)
VECTOR_BACKEND = "kylin_milvus"      # 麒麟向量引擎 (默认)
# ============================================================

uid = os.getuid()

if VECTOR_BACKEND == "qdrant_server":
    _vector_config = {
        "provider": "qdrant",
        "config": {
            "host": "localhost",
            "port": 6333,
            "embedding_model_dims": 768,
        },
    }
else:
    _vector_config = {
        "provider": "kylin_milvus",
        "config": {
            "url": f"unix:/tmp/kylin-ai-vector-engine-{uid}.sock",
            "token": "",
            "collection_name": "mem0_memories",
            "embedding_model_dims": 768,
            "metric_type": "COSINE",
            "db_name": "",
        },
    }

_config_dict = {
    "embedder": {
        "provider": "openai",  # Pydantic 校验用，实际被替换
        "config": {"model": "gte-base", "embedding_dims": 768},
    },
    "vector_store": _vector_config,
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
        cfg.embedder.provider = "kylin_onnx"
        self._memory = Memory(cfg)
        self._default_user = "nex_user"

    def search(self, query, user_id=None, top_k=5):
        try:
            return self._memory.search(
                query, user_id=user_id or self._default_user,
                limit=top_k, threshold=0.3,
            )
        except Exception:
            return []

    def search_as_prompt(self, query, user_id=None):
        results = self.search(query, user_id)
        if not results:
            return ""
        return "[用户相关记忆]\n" + "\n".join(
            f"- {r['memory']}" for r in results
        )

    def add(self, messages, user_id=None):
        try:
            self._memory.add(
                messages, user_id=user_id or self._default_user)
        except Exception:
            pass

    def add_fact(self, fact, user_id=None):
        self._memory.add(fact, user_id=user_id or self._default_user)

    def delete_all(self, user_id=None):
        self._memory.delete_all(user_id=user_id or self._default_user)


mem0_store = Mem0Store()
```

### 5.5 `agent.py` 修改（同嵌入式方案）

**文件顶部：**
```python
from src.memory.mem0_store import mem0_store
```

**前置钩子（`db_manager.update_session_state(session_id, "running")` 之后）：**
```python
        try:
            memory_ctx = mem0_store.search_as_prompt(user_input)
            if memory_ctx:
                user_input = memory_ctx + "\n\n" + user_input
        except Exception:
            pass
```

**后置钩子（`update_session_state(session_id, "none")` 之后，`break` 之前）：**
```python
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

## 六、向量后端对比

| | 麒麟 Milvus (默认) | Qdrant Server | Qdrant 本地文件 |
|------|:--:|:--:|:--:|
| 部署 | 系统已装，零配置 | 需 Docker/二进制 | pip 安装 |
| 数据目录 | 引擎内部 | `~/.nex-agent/qdrant_data/` | `~/.nex-agent/mem0/qdrant/` |
| 多进程 | ✅ | ✅ | ❌ |
| BM25 | ❌ | ✅ | ✅ |
| 生产推荐 | ✅ | ✅ | ❌ |

## 七、部署步骤

```bash
# 1. 创建目录和文件
mkdir -p src/memory
mkdir -p ~/.nex-agent/mem0

# 2. Python 依赖
pip install mem0ai onnxruntime tokenizers numpy

# 3. (仅 Qdrant 后端) 启动 Qdrant Server
docker run -d --name qdrant -p 6333:6333 \
  -v ~/.nex-agent/qdrant_data:/qdrant/storage \
  qdrant/qdrant:latest

# 4. (麒麟 Milvus 后端) 确保服务运行
systemctl --user status kylin-ai-vector-engine

# 5. 创建文件（按 5.1-5.4）
# 6. 修改 agent.py（按 5.5）
# 7. 测试
uv run python -c "
import src.memory
from src.memory.mem0_store import mem0_store
mem0_store.add([{'role':'user','content':'我叫张三，在北京'},
                {'role':'assistant','content':'好的'}])
print(mem0_store.search('这个人叫什么'))
"
```

## 八、与嵌入式方案的差异总结

| | 嵌入式 | 自托管 |
|------|------|------|
| Qdrant 启动 | 自动（Python 内嵌） | 手动（Docker/Qdrant 服务） |
| 向量库 | Qdrant 本地文件 | **麒麟 Milvus** 或 Qdrant Server |
| 多客户端 | ❌ | ✅ |
| 数据可靠性 | 一般 | 高（事务/备份） |
| 需额外 ADAPTOR | 无 | **KylinMilvusDB** (精简版) |
| Embedding | 相同 | 相同 |
| LLM 事实提取 | 相同 | 相同 |
