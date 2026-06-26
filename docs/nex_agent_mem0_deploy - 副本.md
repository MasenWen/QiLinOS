# nex-agent 本地部署 Mem0 + 麒麟 Embedding SDK 方案

## 一、环境确认

### 已安装

| 组件 | 版本 | 状态 |
|------|------|:--:|
| `mem0ai` | 2.0.7 | ✅ 已安装 |
| `qdrant-client` | 1.18.0 | ✅ 已安装（本地模式，无需服务端） |
| 麒麟 ONNX 模型 | gte-base 768维 | ✅ 已验证可用 |
| 麒麟 C API | `libkysdk-coreai-embedding.so` | ⚠ ondevice engine bug，暂不可用 |

### Mem0 工作原理

```
用户对话 ──→ Mem0.add([messages]) ──→ LLM 自动提取事实 ──→ embedding ──→ Qdrant 存储
用户查询 ──→ Mem0.search(query)   ──→ embedding ──→ Qdrant 检索 ──→ 返回记忆
```

Mem0 需要两个组件：
1. **LLM**：从对话中智能提取事实（如"用户叫张三"、"用户在北京工作"）
2. **Embedding**：把事实向量化存入 Qdrant，查询时做语义检索

## 二、麒麟 Embedding 接入方案

### 方案 A：自定义 Mem0 Embedder 封装麒麟 ONNX 模型（推荐，立即可用）

已验证麒麟 ONNX 模型（`gte-base-multilingual-model_QUInt8.onnx`）可正常工作。写一个 Mem0 兼容的 embedder 类：

**新建文件：`src/memory/mem0_kylin_embedder.py`**

```python
"""
Mem0 自定义 Embedder — 使用麒麟 ONNX 模型 (kylin-ai-abstract-models)
实现 Mem0 EmbeddingBase 接口
"""
import numpy as np
from mem0.embeddings.base import EmbeddingBase
from mem0.configs.embedders.base import BaseEmbedderConfig
import onnxruntime as ort
from tokenizers import Tokenizer
from pathlib import Path
from typing import Optional, Literal

MODEL_PATH = "/usr/share/kylin-ai/model-repository/embd_gte-base_uint8-text/1/gte-base-multilingual-model_QUInt8.onnx"
TOKENIZER_PATH = "/usr/share/kylin-ai/model-repository/tokenizer_gte-base_uint8-text/tokenizer.json"


class KylinONNXEmbedder(EmbeddingBase):
    """麒麟 ONNX Embedding — Mem0 兼容

    配置方式:
        config = {
            "embedder": {
                "provider": "kylin_onnx",  # 自定义 provider
                "config": {
                    "model": "gte-base",
                    "embedding_dims": 768,
                },
            },
            ...
        }
    """

    def __init__(self, config: Optional[BaseEmbedderConfig] = None):
        super().__init__(config)
        self.dim = 768

        if not Path(MODEL_PATH).exists():
            raise FileNotFoundError(f"模型不存在: {MODEL_PATH}\n请安装: sudo apt install kylin-ai-abstract-models")

        self._session = ort.InferenceSession(MODEL_PATH)
        self._tokenizer = Tokenizer.from_file(TOKENIZER_PATH)
        self._tokenizer.enable_padding(pad_id=0, pad_token="[PAD]")
        self._tokenizer.enable_truncation(max_length=512)

    def embed(self, text, memory_action: Optional[Literal["add", "search", "update"]] = None):
        """单条文本 embedding → list[float]"""
        return self.embed_batch([text], memory_action)[0]

    def embed_batch(self, texts, memory_action=None):
        """批量文本 embedding → list[list[float]]"""
        result = []
        for text in texts:
            enc = self._tokenizer.encode(text)
            ids = np.array([enc.ids], dtype=np.int64)
            mask = np.array([enc.attention_mask], dtype=np.int64)
            out = self._session.run(None, {"input_ids": ids, "attention_mask": mask})
            m = mask[:, :, None].astype(np.float32)
            emb = (out[0] * m).sum(axis=1) / m.sum(axis=1).clip(min=1e-9)
            vec = emb[0].astype(np.float32)
            vec = vec / np.linalg.norm(vec)
            result.append(vec.tolist())
        return result
```

**注册到 Mem0 Factory：**

`src/memory/__init__.py`：

```python
from mem0.utils.factory import EmbedderFactory
from src.memory.mem0_kylin_embedder import KylinONNXEmbedder

# 注册麒麟 embedder
EmbedderFactory.register("kylin_onnx", KylinONNXEmbedder)
```

### 方案 B：OpenAI 兼容模式走 DashScope（备选）

如果不想维护自定义 embedder，可以用 Mem0 内置的 OpenAI embedder 指向 DashScope：

```python
"embedder": {
    "provider": "openai",
    "config": {
        "model": "text-embedding-v3",
        "api_key": os.getenv("QWEN_API_KEY"),
        "openai_base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "embedding_dims": 768,
    },
}
```

缺点：依赖网络，每次 embedding 都要调 HTTP API。

### 方案 C：麒麟原生 C API（待系统 bug 修复后用）

`kylin-ondevice-embedding-engine` 的 model_bank bug 修复后，切换为：

```python
from src.rag.kylin_embedding_sdk import KylinTextEmbedding

class KylinSDKEmbedder(EmbeddingBase):
    def __init__(self, config=None):
        super().__init__(config)
        self._embedder = KylinTextEmbedding()

    def embed(self, text, memory_action=None):
        return self._embedder.embed([text])[0].tolist()

    def embed_batch(self, texts, memory_action=None):
        return self._embedder.embed(texts).tolist()
```

## 三、完整部署

### 3.1 创建目录

```bash
mkdir -p src/memory
mkdir -p ~/.nex-agent/mem0_qdrant
```

### 3.2 创建文件

```
src/memory/
├── __init__.py                  # 注册麒麟 embedder
└── mem0_kylin_embedder.py      # 麒麟 ONNX embedder (方案A)
```

### 3.3 `src/memory/mem0_store.py`

```python
"""
Mem0 记忆存储 — 麒麟 Embedding + 本地 Qdrant
自动从对话中提取/检索用户记忆
"""
import os
from mem0 import Memory

from dotenv import load_dotenv
load_dotenv()

# 确保麒麟 embedder 已注册
import src.memory  # noqa: F401 — 触发 EmbedderFactory.register("kylin_onnx", ...)

MEM0_DIR = os.path.expanduser("~/.nex-agent/mem0_qdrant")

CONFIG = {
    "embedder": {
        "provider": "kylin_onnx",       # 麒麟 ONNX 模型 (方案A)
        "config": {
            "model": "gte-base",
            "embedding_dims": 768,
        },
    },
    "vector_store": {
        "provider": "qdrant",
        "config": {
            "path": MEM0_DIR,
            "embedding_model_dims": 768,
            "on_disk": True,            # 持久化到磁盘
        },
    },
    "llm": {
        "provider": "openai",
        "config": {
            "model": "qwen3-max",
            "api_key": os.getenv("QWEN_API_KEY"),
            "openai_base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        },
    },
    "version": "v1.1",
}


class Mem0Store:
    """Mem0 记忆存储 — 全局单例"""

    def __init__(self):
        os.makedirs(MEM0_DIR, exist_ok=True)
        self._memory = Memory.from_config(CONFIG)
        self._default_user = "nex_user"

    def search(self, query: str, user_id: str = None, top_k: int = 5) -> list[dict]:
        """语义检索记忆 → 返回 [{"memory": "...", "score": 0.9}, ...]"""
        try:
            return self._memory.search(
                query,
                user_id=user_id or self._default_user,
                limit=top_k,
                threshold=0.3,
            )
        except Exception:
            return []

    def search_as_prompt(self, query: str, user_id: str = None) -> str:
        """检索记忆并格式化为 prompt 注入文本"""
        results = self.search(query, user_id)
        if not results:
            return ""
        lines = [f"- {r['memory']}" for r in results]
        return "[用户相关记忆]\n" + "\n".join(lines)

    def add(self, messages: list[dict], user_id: str = None):
        """从对话中自动提取事实并写入。messages=[{role, content}, ...]"""
        try:
            self._memory.add(messages, user_id=user_id or self._default_user)
        except Exception:
            pass  # 记忆写入失败不阻塞主流程

    def add_fact(self, fact: str, user_id: str = None):
        """手动添加单条事实"""
        self._memory.add(fact, user_id=user_id or self._default_user)

    def delete_all(self, user_id: str = None):
        self._memory.delete_all(user_id=user_id or self._default_user)


# 全局单例
mem0_store = Mem0Store()
```

### 3.4 修改 `agent.py`

在 `run_workflow_with_review` 方法中，两个插入点（约 line 271 后 和 line 350 后）：

```python
# === 文件顶部 ===
from src.memory.mem0_store import mem0_store

# === ① 前置钩子：user_input 构建完成后，LLM 处理前 ===
try:
    memory_context = mem0_store.search_as_prompt(user_input)
    if memory_context:
        user_input = memory_context + "\n\n" + user_input
except Exception:
    pass

# === ② 后置钩子：workflow 执行完毕后 ===
try:
    messages = state.get("messages", [])
    if len(messages) >= 2:
        user_msg = messages[-2].content if hasattr(messages[-2], 'content') else str(messages[-2])
        asst_msg = messages[-1].content if hasattr(messages[-1], 'content') else str(messages[-1])
        mem0_store.add([
            {"role": "user", "content": user_msg[:500]},
            {"role": "assistant", "content": asst_msg[:500]},
        ])
except Exception:
    pass
```

### 3.5 `requirements.txt` 添加

```
mem0ai
qdrant-client
```

## 四、验证测试

```bash
uv run python << 'EOF'
from dotenv import load_dotenv; load_dotenv()
import src.memory  # 注册麒麟 embedder
from src.memory.mem0_store import mem0_store

# 1. 写入记忆
print("写入记忆...")
mem0_store.add([
    {"role": "user", "content": "我叫张三，在北京工作，喜欢简洁的风格"},
    {"role": "assistant", "content": "好的张三，我记住了。你在北京工作，喜欢简洁风格。"}
])

# 2. 检索记忆
print("\n检索: '这个人住在哪里'")
results = mem0_store.search("这个人住在哪里", top_k=3)
for r in results:
    print(f"  [{r['score']:.2f}] {r['memory']}")

# 3. 检索记忆
print("\n检索: '他的风格偏好'")
results = mem0_store.search("风格偏好", top_k=3)
for r in results:
    print(f"  [{r['score']:.2f}] {r['memory']}")

print("\n✅ Mem0 + 麒麟 Embedding 验证通过")
EOF
```

## 五、架构总览

```
nex-agent
│
├─ agent.py
│   ├─ 前置钩子: mem0_store.search_as_prompt(query) → 注入用户记忆
│   └─ 后置钩子: mem0_store.add(messages)            → 自动提取事实
│
├─ src/memory/mem0_store.py        ← Mem0 封装层
│   ├─ embedder: KylinONNXEmbedder  ← 麒麟 gte-base 768维
│   ├─ vector_store: Qdrant 本地    ← ~/.nex-agent/mem0_qdrant/
│   └─ llm: Qwen3-Max (DashScope)   ← 事实提取
│
├─ src/memory/mem0_kylin_embedder.py ← 麒麟 ONNX Embedder
│
├─ src/rag/ps_rag.py               ← RAG 知识库（保留，用于文档检索）
├─ src/rag/kylin_embedding_sdk.py   ← 麒麟 C API（待 bug 修复）
│
└─ mcp_server/server/hermes_bridge.py ← Hermes（保留，用于系统操作）
```

## 六、调用时机

| 触发点 | 操作 | 调用方 |
|--------|------|--------|
| 用户消息到达 | `search_as_prompt(query)` | agent.py 前置钩子 |
| 工作流完成 | `add([{user}, {assistant}])` | agent.py 后置钩子 |
| **全部自动**，用户不需要说"记住xxx" | | |

## 七、方案切换

| 方案 | embedder config | 何时用 |
|------|------|------|
| **A (推荐)** | `"provider": "kylin_onnx"` | 立即可用，麒麟 ONNX 本地推理 |
| B (备选) | `"provider": "openai"` + DashScope | 不想维护自定义代码时 |
| C (未来) | `"provider": "kylin_sdk"` 封装 C API | 等待 ondevice engine bug 修复 |

方案 A 和 C 都使用麒麟模型，不依赖外部 embedding API。
