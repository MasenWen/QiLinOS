# Hermes 接入麒麟 Embedding + 向量数据库方案（v2）

## 一、v1 方案问题

v1 把 embedding SDK 写死在 `KylinMemoryProvider` 内部，导致：

- **只能记忆模块使用** — 技能匹配、Web 缓存、跨模块检索全部够不到
- **每个 Provider 各自加载模型** — 浪费内存（ONNX 模型 ~300MB/实例）
- **无法扩展新集合** — 每加一个集合要改 Provider 代码

## 二、v2 架构：`KylinSemanticStore` 独立语义层

```
agent._kylin_semantic  (挂载在 AIAgent 上，全局可访问)
│
├─ embed(text) → np.ndarray         ← 文本向量化
├─ search(query, collection, top_k) ← 多集合语义检索
├─ insert(texts, vectors, collection) ← 写入向量
└─ ensure_collection(name)          ← 初始化集合

        ▲           ▲            ▲
        │           │            │
   MemoryProvider  Skills      Web Cache
   (hermes_memory) (hermes_skills) (hermes_web_cache)
```

**关键变化：**

| | v1 | v2 |
|------|------|------|
| embedding 实例 | Provider 内部 | `agent._kylin_semantic` 单例 |
| 访问范围 | 仅 MemoryProvider | 所有模块 `agent._kylin_semantic.embed()` |
| 模型加载 | 每次初始化 | 一次加载，全局共享 |
| 集合隔离 | 写死 `hermes_memory` | 调用方传 `collection` 名，多集合并存 |

## 三、需要修改的文件

| 文件 | 操作 |
|------|------|
| `agent/kylin_semantic.py` | **新建** — `KylinSemanticStore` 类 |
| `agent/agent_init.py` | **修改** — 挂载 `agent._kylin_semantic` |
| `plugins/memory/kylin/__init__.py` | **新建** — 消费 `agent._kylin_semantic` |
| `plugins/memory/__init__.py` | **修改** — 注册 `kylin` provider |
| `~/.hermes/config.yaml` | **修改** — `memory.provider: kylin` |

## 四、核心代码

### 4.1 `agent/kylin_semantic.py`（全局语义层，新建）

```python
"""
麒麟语义存储 — 全局单例
所有模块通过 agent._kylin_semantic 调用
"""
import logging, os, numpy as np
from pathlib import Path
from pymilvus import MilvusClient, DataType
from pymilvus.milvus_client.index import IndexParams, IndexParam
import onnxruntime as ort
from tokenizers import Tokenizer

logger = logging.getLogger(__name__)

MODELS = {
    "gte-base": {
        "dim": 768,
        "onnx": "/usr/share/kylin-ai/model-repository/embd_gte-base_uint8-text/1/"
                "gte-base-multilingual-model_QUInt8.onnx",
        "tokenizer": "/usr/share/kylin-ai/model-repository/"
                     "tokenizer_gte-base_uint8-text/tokenizer.json",
    },
}


class KylinSemanticStore:
    """全局语义存储 — embedding + 多集合向量检索"""

    def __init__(self, model_key: str = "gte-base"):
        cfg = MODELS[model_key]
        self.dim = cfg["dim"]

        # Embedding: ONNX Runtime + tokenizers (Rust)
        self._session = ort.InferenceSession(cfg["onnx"])
        self._tokenizer = Tokenizer.from_file(cfg["tokenizer"])
        self._tokenizer.enable_padding(pad_id=0, pad_token="[PAD]")
        self._tokenizer.enable_truncation(max_length=512)

        # Vector DB: Milvus over Unix Socket
        uds = f"/tmp/kylin-ai-vector-engine-{os.getuid()}.sock"
        self._client = MilvusClient(uri=f"unix:{uds}")

        logger.info("KylinSemanticStore ready: %s dim=%d → %s",
                    model_key, self.dim, uds)

    # ---- Embedding ----
    def embed(self, texts: list[str]) -> np.ndarray:
        """文本 → 归一化向量，shape=(len(texts), dim)"""
        if isinstance(texts, str):
            texts = [texts]
        result = []
        for t in texts:
            enc = self._tokenizer.encode(t)
            ids = np.array([enc.ids], dtype=np.int64)
            mask = np.array([enc.attention_mask], dtype=np.int64)
            out = self._session.run(None,
                {"input_ids": ids, "attention_mask": mask})
            m = mask[:, :, None].astype(np.float32)
            emb = (out[0] * m).sum(axis=1) / m.sum(axis=1).clip(min=1e-9)
            result.append(emb[0])
        vecs = np.stack(result).astype(np.float32)
        return vecs / np.linalg.norm(vecs, axis=1, keepdims=True).clip(min=1e-9)

    # ---- 集合管理 ----
    def ensure_collection(self, name: str, drop: bool = False):
        if drop and self._client.has_collection(name):
            self._client.drop_collection(name)
        if not self._client.has_collection(name):
            self._client.create_collection(
                collection_name=name, dimension=self.dim,
                metric_type="COSINE", auto_id=True,
                datatype=DataType.FLOAT_VECTOR,
            )
            idx = IndexParams([IndexParam(
                field_name="vector", index_type="HNSW", index_name="hnsw",
                metric_type="COSINE",
                params={"M": 16, "efConstruction": 200},
            )])
            self._client.create_index(collection_name=name, index_params=idx)
        self._client.load_collection(name)

    # ---- 写入 ----
    def insert(self, collection: str, texts: list[str],
               vectors: np.ndarray = None, metadatas: list[dict] = None) -> list:
        if vectors is None:
            vectors = self.embed(texts)
        data = []
        for i, (t, v) in enumerate(zip(texts, vectors)):
            row = {"vector": v.tolist(), "text": t}
            if metadatas:
                row.update(metadatas[i])
            data.append(row)
        return self._client.insert(collection_name=collection, data=data)["ids"]

    # ---- 检索 ----
    def search(self, collection: str, query, top_k: int = 5,
               threshold: float = 0.3) -> list[dict]:
        if isinstance(query, str):
            query = self.embed([query])[0]
        elif query.ndim == 2:
            query = query[0]
        results = self._client.search(
            collection_name=collection, data=[query.tolist()],
            limit=top_k, output_fields=["text"],
        )
        return [
            {"score": r["distance"], "text": r["entity"]["text"]}
            for r in results[0] if r["distance"] >= threshold
        ]

    def close(self):
        self._client.close()
```

### 4.2 挂载到 AIAgent（`agent/agent_init.py` 中插入）

```python
# 在 agent._memory_manager 初始化之后添加
try:
    from agent.kylin_semantic import KylinSemanticStore
    agent._kylin_semantic = KylinSemanticStore(model_key="gte-base")
    agent._kylin_semantic.ensure_collection("hermes_memory")
    logger.info("Kylin semantics store mounted")
except Exception as e:
    logger.warning("Kylin semantics store unavailable: %s", e)
    agent._kylin_semantic = None
```

### 4.3 MemoryProvider（精简版，`plugins/memory/kylin/__init__.py`）

```python
"""麒麟记忆插件 — 消费 agent._kylin_semantic"""
from agent.memory_provider import MemoryProvider
import logging
logger = logging.getLogger(__name__)

class KylinMemoryProvider(MemoryProvider):

    def __init__(self):
        self._agent = None

    @property
    def name(self) -> str:
        return "kylin"

    def is_available(self) -> bool:
        return True

    def initialize(self, session_id: str, **kwargs) -> None:
        from run_agent import _ra
        self._agent = _ra()
        self._agent._kylin_semantic.ensure_collection("hermes_memory")

    def prefetch(self, query: str, *, session_id: str = "") -> str:
        store = self._agent._kylin_semantic
        if store is None:
            return ""
        results = store.search("hermes_memory", query, top_k=5)
        if not results:
            return ""
        return "\n---\n".join(
            f"[{r['score']:.2f}] {r['text']}" for r in results
        )

    def sync_turn(self, user_msg: str, assistant_msg: str, **kwargs) -> None:
        store = self._agent._kylin_semantic
        if store is None or len(user_msg.strip()) < 10:
            return
        existing = store.search("hermes_memory", user_msg, top_k=1, threshold=0.95)
        if not existing:
            store.insert("hermes_memory", [user_msg])

    def get_tool_schemas(self) -> list:
        return []

    def handle_tool_call(self, name: str, args: dict, **kw) -> str:
        return "{}"

    def shutdown(self) -> None:
        pass

    def system_prompt_block(self) -> str:
        return "[Kylin semantic memory active — results ranked by meaning.]"
```

### 4.4 注册 + 配置

**`plugins/memory/__init__.py`** 中添加：
```python
if name == "kylin":
    from plugins.memory.kylin import KylinMemoryProvider
    return KylinMemoryProvider()
```

**`~/.hermes/config.yaml`**：
```yaml
memory:
  provider: kylin
```

## 五、其他模块使用示例

```python
# 技能匹配 — 根据用户意图搜索技能库
store = agent._kylin_semantic
store.ensure_collection("hermes_skills")
results = store.search("hermes_skills", "图片转素描", top_k=3)

# Web 缓存 — 检索之前爬过的内容
store.search("hermes_web_cache", query, top_k=3, threshold=0.7)

# 代码片段搜索
store.search("hermes_code_snippets", "数据库连接池配置", top_k=5)

# 任意模块写入
store.insert("hermes_memory", [user_msg], metadatas=[{"type": "fact"}])
```

所有集合共享同一个 `KylinSemanticStore` 实例，不需要各自加载 embedding 模型。

## 六、部署

```bash
# 1. 创建文件
touch ~/.hermes/hermes-agent/agent/kylin_semantic.py
mkdir -p ~/.hermes/hermes-agent/plugins/memory/kylin/
touch ~/.hermes/hermes-agent/plugins/memory/kylin/__init__.py

# 2. 安装 Python 依赖（Hermes 环境）
pip install onnxruntime pymilvus tokenizers numpy

# 3. 确保麒麟服务运行
systemctl --user status kylin-ai-vector-engine

# 4. 修改 ~/.hermes/config.yaml
#    memory.provider: kylin

# 5. 启动 Hermes，观察日志
#    应出现: KylinSemanticStore ready
#           KylinMemoryProvider 就绪
```
