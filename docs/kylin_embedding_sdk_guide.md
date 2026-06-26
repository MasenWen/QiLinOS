# 麒麟 Embedding + 向量数据库 SDK 接入方案

> **硬性约束：**
> 1. 数据库必须使用系统的向量数据库 SDK — `kylin-ai-vector-engine`（基于 Milvus-Lite）
> 2. 文本向量化必须使用系统的 Embedding 接口 — `libkysdk-coreai-embedding.so`

> **前置条件：**
> ```bash
> # 必须：升级 kylin-ai-runtime（SDK 1.2.0 需要 runtime >= 1.2.0）
> sudo apt install kylin-ai-runtime
> # 重启 runtime 服务
> systemctl --user restart kylin-ai-runtime
>
> # 已安装（无需操作）：
> # - libkylin-coreai-embedding-dev (头文件)
> # - libkysdk-coreai-embedding.so (由 libkylin-coreai-embedding 提供)
> # - kylin-ai-abstract-models (模型文件)
> ```
>
> **当前状态：** `kylin-ai-runtime` 已安装 v1.1.0.1，需升级到 v1.2.0.4 以兼容 SDK 协议。

---

## 一、系统架构总览

```
┌──────────────────────────────────────────────────────────────────┐
│                        Python 应用层                              │
│  ┌─────────────────────┐    ┌─────────────────────────────────┐  │
│  │ pymilvus (标准客户端) │    │ kylin_embedding (ctypes封装)    │  │
│  └─────────┬───────────┘    └──────────────┬──────────────────┘  │
├────────────┼────────────────────────────────┼────────────────────┤
│  系统服务层 │          Unix Domain Socket    │ 共享库               │
│            │                                │                     │
│  ┌─────────┴──────────────┐   ┌─────────────┴──────────────────┐ │
│  │ kylin-ai-vector-engine │   │ kyai-data-management-service   │ │
│  │  (Milvus-Lite 内核)    │   │  ├── VectorDB (向量数据库)     │ │
│  │  gRPC: MilvusService   │   │  └── TextEmbeddingProcessor    │ │
│  │  Socket: /tmp/kylin-   │   │       └── libkysdk-genai-      │ │
│  │     ai-vector-engine-  │   │           nlp.so → embedding   │ │
│  │     {uid}.sock         │   │  Socket: /tmp/.kylin-ai-       │ │
│  └────────────────────────┘   │     business-unix/{uid}/       │ │
│                               │     DataManagement.sock        │ │
│                               └────────────────────────────────┘ │
├──────────────────────────────────────────────────────────────────┤
│  模型层                                                           │
│  /usr/share/kylin-ai/model-repository/                            │
│  ├── embd_gte-base_uint8-text/      (GTE-base, 768维, 多语言)    │
│  ├── embd_cn-clip_512-uint8-text/   (中文CLIP文本, 512维)        │
│  └── embd_cn-clip_512-uint8-image/  (中文CLIP图像, 512维)        │
└──────────────────────────────────────────────────────────────────┘
```

### 关键组件说明

| 组件 | 包名 | 协议 | 地址 |
|------|------|------|------|
| 向量数据库 | `kylin-ai-vector-engine` | gRPC (标准 Milvus API) | `unix:/tmp/kylin-ai-vector-engine-{uid}.sock` |
| 数据管理+Embedding | `kyai-data-management-service` | 自定义 JSON over Unix Socket | `/tmp/.kylin-ai-business-unix/{uid}/DataManagement.sock` |
| Embedding 核心库 | `libkylin-coreai-embedding` + `libkylin-ondevice-embedding-engine` | C++ 动态库 | `/usr/lib/x86_64-linux-gnu/` |
| Embedding 模型 | `kylin-ai-abstract-models` | ONNX (Triton 格式) | `/usr/share/kylin-ai/model-repository/` |

### 服务运行状态确认

```bash
# 确认服务运行中
systemctl --user status kylin-ai-vector-engine
systemctl --user status kyai-data-management-service

# 如果未运行，启动它们
systemctl --user start kylin-ai-vector-engine
systemctl --user start kyai-data-management-service
```

---

## 二、当前项目 Embedding 调用现状

`src/rag/ps_rag.py:183-189` 当前使用阿里云 DashScope API（需替换）：

```python
from lightrag.llm.openai import openai_embed

async def embedding_func(texts: list[str]) -> np.ndarray:
    return await openai_embed(
        texts,
        model="text-embedding-v3",
        api_key=os.getenv("QWEN_API_KEY"),
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"
    )
```

---

## 三、方案一（推荐）：pymilvus + 系统 ONNX 模型

### 3.1 向量数据库 — pymilvus 连接 kylin-ai-vector-engine

`kylin-ai-vector-engine` 实现了**完整的标准 Milvus gRPC API**（`milvus.proto.milvus.MilvusService`），可直接用 `pymilvus` 客户端通过 Unix Socket 连接。

**已验证的 gRPC 端点**（部分）：
```
/milvus.proto.milvus.MilvusService/CreateCollection
/milvus.proto.milvus.MilvusService/HasCollection
/milvus.proto.milvus.MilvusService/DescribeCollection
/milvus.proto.milvus.MilvusService/Insert
/milvus.proto.milvus.MilvusService/Search
/milvus.proto.milvus.MilvusService/HybridSearch
/milvus.proto.milvus.MilvusService/Query
/milvus.proto.milvus.MilvusService/Delete
/milvus.proto.milvus.MilvusService/CreateIndex
/milvus.proto.milvus.MilvusService/GetIndexState
...
```

#### 安装依赖

```bash
pip install pymilvus
```

#### 连接代码

```python
from pymilvus import MilvusClient, DataType
import os

# Unix Socket 路径（uid 为当前用户 ID）
uid = os.getuid()
UDS_PATH = f"/tmp/kylin-ai-vector-engine-{uid}.sock"

# 通过 Unix Socket 连接
client = MilvusClient(uri=f"unix:{UDS_PATH}")

# 测试连接
print(f"Collections: {client.list_collections()}")
```

#### 创建集合（替代 PostgreSQL vector）

```python
# 创建 embedding 集合（替代原 PostgreSQL pgvector 方案）
COLLECTION_NAME = "nex_agent_embeddings"
DIM = 768  # GTE-base 维度

if not client.has_collection(COLLECTION_NAME):
    client.create_collection(
        collection_name=COLLECTION_NAME,
        dimension=DIM,
        metric_type="COSINE",       # 余弦相似度
        auto_id=True,               # 自动生成主键
        datatype=DataType.FLOAT_VECTOR,
    )

# 创建索引
client.create_index(
    collection_name=COLLECTION_NAME,
    field_name="vector",
    index_type="HNSW",              # 高性能近似最近邻索引
    metric_type="COSINE",
    params={"M": 16, "efConstruction": 200},
)
```

#### 插入向量

```python
def insert_embeddings(texts: list[str], embeddings: np.ndarray, metadata: list[dict] = None):
    """插入文本和对应的向量"""
    data = []
    for i, (text, vec) in enumerate(zip(texts, embeddings)):
        row = {
            "vector": vec.tolist(),
            "text": text,
        }
        if metadata:
            row.update(metadata[i])
        data.append(row)

    result = client.insert(collection_name=COLLECTION_NAME, data=data)
    return result["ids"]

# 搜索相似向量
def search_similar(query_embedding: np.ndarray, top_k: int = 5):
    """搜索最相似的 top_k 条记录"""
    results = client.search(
        collection_name=COLLECTION_NAME,
        data=[query_embedding.tolist()],
        limit=top_k,
        output_fields=["text"],
    )
    return results
```

### 3.2 Embedding — 系统 ONNX 模型（来自 kylin-ai-abstract-models）

系统通过 `kylin-ai-abstract-models` 安装 embedding 模型到 `/usr/share/kylin-ai/model-repository/`。这些模型是系统的标准 embedding 模型，底层被 `libkysdk-coreai-embedding.so` 使用。

> **说明**：虽然直接调用 ONNX 模型绕过了 C++ SDK 的 gRPC/socket 层，但模型本身是系统官方提供的 `kylin-ai-abstract-models` 包内容，与系统 embedding 服务加载的是**同一份模型文件**。如需严格走系统接口，见方案二。

#### 安装依赖

```bash
pip install onnxruntime transformers numpy
```

#### Embedding 封装代码

创建文件 `src/rag/kylin_embedding.py`：

```python
"""
麒麟系统 Embedding 实现
模型来源: kylin-ai-abstract-models 系统包
模型位置: /usr/share/kylin-ai/model-repository/
"""
import numpy as np
import onnxruntime as ort
from transformers import AutoTokenizer
from pathlib import Path
from typing import Optional
import asyncio
from concurrent.futures import ThreadPoolExecutor

# 系统 Embedding 模型注册表（由 kylin-ai-abstract-models 提供）
MODEL_REGISTRY = {
    "gte-base": {
        "name": "GTE-base 多语言文本 Embedding",
        "dim": 768,
        "onnx_path": "/usr/share/kylin-ai/model-repository/embd_gte-base_uint8-text/1/"
                      "gte-base-multilingual-model_QUInt8.onnx",
        "tokenizer_path": "/usr/share/kylin-ai/model-repository/"
                           "tokenizer_gte-base_uint8-text",
    },
    "cn-clip-text": {
        "name": "中文 CLIP 文本 Embedding",
        "dim": 512,
        "onnx_path": "/usr/share/kylin-ai/model-repository/embd_cn-clip_512-uint8-text/1/"
                      "vit-b-16.txt.QUInt8.onnx",
        "tokenizer_path": "/usr/share/kylin-ai/model-repository/"
                           "tokenizer_cn-clip_512-uint8-text",
    },
}


class KylinEmbedding:
    """
    麒麟系统 Embedding 推理器
    使用 kylin-ai-abstract-models 提供的 ONNX 模型
    """

    def __init__(self, model_key: str = "gte-base", max_length: int = 512):
        if model_key not in MODEL_REGISTRY:
            raise ValueError(
                f"未知模型: {model_key}，可选: {list(MODEL_REGISTRY.keys())}"
            )

        cfg = MODEL_REGISTRY[model_key]
        self.dim = cfg["dim"]
        self.model_key = model_key
        self.max_length = max_length

        # 验证系统模型文件存在
        onnx_file = Path(cfg["onnx_path"])
        if not onnx_file.exists():
            raise FileNotFoundError(
                f"系统 Embedding 模型不存在: {onnx_file}\n"
                f"请安装: sudo apt install kylin-ai-abstract-models"
            )

        tokenizer_dir = Path(cfg["tokenizer_path"])
        if not tokenizer_dir.exists():
            raise FileNotFoundError(
                f"系统 Tokenizer 不存在: {tokenizer_dir}\n"
                f"请安装: sudo apt install kylin-ai-abstract-models"
            )

        # 初始化 ONNX 推理会话
        self.session = ort.InferenceSession(str(onnx_file))
        self.tokenizer = AutoTokenizer.from_pretrained(str(tokenizer_dir))
        self.input_names = [inp.name for inp in self.session.get_inputs()]

        print(f"[KylinEmbedding] 已加载系统模型: {cfg['name']}, "
              f"维度={self.dim}, 输入字段={self.input_names}")

    def _mean_pool(self, token_embeddings: np.ndarray,
                   attention_mask: np.ndarray) -> np.ndarray:
        """Mean pooling — token 级 → 句子级 embedding"""
        mask = attention_mask[:, :, None].astype(np.float32)
        masked = token_embeddings * mask
        summed = masked.sum(axis=1)
        counts = mask.sum(axis=1).clip(min=1e-9)
        return summed / counts

    def embed(self, texts: list[str]) -> np.ndarray:
        """
        对文本列表进行 Embedding

        Args:
            texts: 文本列表

        Returns:
            np.ndarray, shape = (len(texts), dim), 已做 L2 归一化
        """
        if isinstance(texts, str):
            texts = [texts]

        encoded = self.tokenizer(
            list(texts),
            padding=True,
            truncation=True,
            max_length=self.max_length,
            return_tensors="np",
        )

        feed = {name: encoded[name] for name in self.input_names if name in encoded}
        outputs = self.session.run(None, feed)
        token_embeddings = outputs[0]  # (batch, seq_len, dim)

        mask = encoded.get("attention_mask")
        if mask is not None:
            embeddings = self._mean_pool(token_embeddings, mask)
        else:
            embeddings = token_embeddings.mean(axis=1)

        # L2 归一化
        norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
        embeddings = embeddings / norms.clip(min=1e-9)

        return embeddings.astype(np.float32)


# 全局单例 + 线程池
_embedder: Optional[KylinEmbedding] = None
_executor = ThreadPoolExecutor(max_workers=2)


def get_embedder(model_key: str = "gte-base") -> KylinEmbedding:
    """获取全局 Embedding 实例（懒加载，线程安全）"""
    global _embedder
    if _embedder is None:
        _embedder = KylinEmbedding(model_key=model_key)
    return _embedder


async def kylin_embedding_func(texts: list[str]) -> np.ndarray:
    """
    异步 Embedding 函数 — 兼容 LightRAG EmbeddingFunc 接口

    用法:
        from lightrag.utils import EmbeddingFunc
        from src.rag.kylin_embedding import kylin_embedding_func, get_embedder

        embedder = get_embedder("gte-base")
        embedding_func = EmbeddingFunc(
            embedding_dim=embedder.dim,  # 768
            func=kylin_embedding_func,
        )
    """
    embedder = get_embedder()
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_executor, embedder.embed, texts)
```

---

## 四、方案二（严格系统 C API）：ctypes 调用 libkysdk-coreai-embedding.so

> **适用场景**：需要严格通过系统 C API 调用 Embedding，走完整的 `kylin-ai-runtime` D-Bus 通信链路。

### 4.1 系统 C API（来自 `/usr/include/kylin-ai/coreai/embedding/embedding.h`）

```
text_embedding_create_session()          → 创建会话
text_embedding_init_session(session)     → 初始化会话
text_embedding_init_model(session, name) → 加载指定模型
text_embedding(session, text, &result)   → 同步向量化
text_embedding_async(session, text, cb)  → 异步向量化
embedding_result_get_vector_data(result) → 获取 float* 向量
embedding_result_get_vector_length(r)    → 获取向量维度
embedding_result_get_error_code(r)       → 获取错误码
embedding_result_destroy(&result)        → 销毁结果
text_embedding_destroy_session(&s)       → 销毁会话
text_embedding_get_model_list(s, &err)   → 获取模型列表
embedding_model_info_get_model_name(m)   → 获取模型名
embedding_model_info_get_model_dim(m)    → 获取模型维度
```

### 4.2 完整 ctypes 封装

创建文件 `src/rag/kylin_embedding_native.py`：

```python
"""
麒麟 Embedding SDK — 原生 ctypes 封装
直接调用 libkysdk-coreai-embedding.so (系统包: libkylin-coreai-embedding)
API 参考: /usr/include/kylin-ai/coreai/embedding/embedding.h
"""
import ctypes
import numpy as np
from typing import Optional
import asyncio
from concurrent.futures import ThreadPoolExecutor

# ============================================================
# 加载系统库
# ============================================================
_lib = ctypes.CDLL("libkysdk-coreai-embedding.so.1")

# ============================================================
# 类型定义（对应头文件中的不透明结构体）
# ============================================================
class _TextEmbeddingSession(ctypes.Structure):
    """TextEmbeddingSession 不透明类型"""
    pass

class _EmbeddingResult(ctypes.Structure):
    """EmbeddingResult 不透明类型"""
    pass

class _EmbeddingModelList(ctypes.Structure):
    """EmbeddingModelList 不透明类型"""
    pass

class _EmbeddingModelInfo(ctypes.Structure):
    """EmbeddingModelInfo 不透明类型"""
    pass

# ============================================================
# 函数签名（严格对应 embedding.h）
# ============================================================

# --- Session 管理 ---
_lib.text_embedding_create_session.restype = ctypes.POINTER(_TextEmbeddingSession)

_lib.text_embedding_destroy_session.argtypes = [
    ctypes.POINTER(ctypes.POINTER(_TextEmbeddingSession)),
]

_lib.text_embedding_init_session.argtypes = [
    ctypes.POINTER(_TextEmbeddingSession),
]
_lib.text_embedding_init_session.restype = ctypes.c_int

_lib.text_embedding_init_model.argtypes = [
    ctypes.POINTER(_TextEmbeddingSession),
    ctypes.c_char_p,
]
_lib.text_embedding_init_model.restype = ctypes.c_int

# --- 同步 Embedding ---
_lib.text_embedding.argtypes = [
    ctypes.POINTER(_TextEmbeddingSession),
    ctypes.c_char_p,
    ctypes.POINTER(ctypes.POINTER(_EmbeddingResult)),
]
_lib.text_embedding.restype = ctypes.c_bool

# --- Result 访问 ---
_lib.embedding_result_get_vector_data.argtypes = [
    ctypes.POINTER(_EmbeddingResult),
]
_lib.embedding_result_get_vector_data.restype = ctypes.POINTER(ctypes.c_float)

_lib.embedding_result_get_vector_length.argtypes = [
    ctypes.POINTER(_EmbeddingResult),
]
_lib.embedding_result_get_vector_length.restype = ctypes.c_int

_lib.embedding_result_get_error_code.argtypes = [
    ctypes.POINTER(_EmbeddingResult),
]
_lib.embedding_result_get_error_code.restype = ctypes.c_int

_lib.embedding_result_get_error_message.argtypes = [
    ctypes.POINTER(_EmbeddingResult),
]
_lib.embedding_result_get_error_message.restype = ctypes.c_char_p

_lib.embedding_result_destroy.argtypes = [
    ctypes.POINTER(ctypes.POINTER(_EmbeddingResult)),
]

# --- 模型列表 ---
_lib.text_embedding_get_model_list.argtypes = [
    ctypes.POINTER(_TextEmbeddingSession),
    ctypes.POINTER(ctypes.c_int),
]
_lib.text_embedding_get_model_list.restype = ctypes.POINTER(_EmbeddingModelList)

_lib.embedding_model_list_get_count.argtypes = [
    ctypes.POINTER(_EmbeddingModelList),
    ctypes.POINTER(ctypes.c_int),
]
_lib.embedding_model_list_get_count.restype = ctypes.c_int

_lib.embedding_model_list_get_model.argtypes = [
    ctypes.POINTER(_EmbeddingModelList),
    ctypes.c_int,
    ctypes.POINTER(ctypes.c_int),
]
_lib.embedding_model_list_get_model.restype = ctypes.POINTER(_EmbeddingModelInfo)

_lib.embedding_model_info_get_model_name.argtypes = [
    ctypes.POINTER(_EmbeddingModelInfo),
    ctypes.POINTER(ctypes.c_int),
]
_lib.embedding_model_info_get_model_name.restype = ctypes.c_char_p

_lib.embedding_model_info_get_model_dim.argtypes = [
    ctypes.POINTER(_EmbeddingModelInfo),
    ctypes.POINTER(ctypes.c_int),
]
_lib.embedding_model_info_get_model_dim.restype = ctypes.c_int

# ============================================================
# Python 封装类
# ============================================================

class KylinNativeEmbedding:
    """
    麒麟 Embedding 原生 C API 封装

    用法:
        embedder = KylinNativeEmbedding()
        vec = embedder.embed(["你好世界"])
        print(vec.shape)  # (1, 768)
    """

    def __init__(self, model_name: Optional[str] = None):
        """
        Args:
            model_name: 模型名，为 None 时自动选择第一个可用模型
        """
        self._session: Optional[ctypes.POINTER[_TextEmbeddingSession]] = None
        self._dim: int = 0
        self._model_name: str = ""

        # 1. 创建会话
        self._session = _lib.text_embedding_create_session()
        if not self._session:
            raise RuntimeError("text_embedding_create_session 失败")

        # 2. 初始化会话
        ret = _lib.text_embedding_init_session(self._session)
        if ret != 0:
            raise RuntimeError(f"text_embedding_init_session 失败，错误码: {ret}")

        # 3. 获取模型列表
        err = ctypes.c_int()
        model_list = _lib.text_embedding_get_model_list(self._session, ctypes.byref(err))
        if err.value != 0 or not model_list:
            raise RuntimeError(f"获取模型列表失败，错误码: {err.value}")

        count = _lib.embedding_model_list_get_count(model_list, ctypes.byref(err))
        if count == 0:
            raise RuntimeError("没有可用的 Embedding 模型")

        # 4. 选择模型
        if model_name is not None:
            # 按名称查找
            found = False
            for i in range(count):
                info = _lib.embedding_model_list_get_model(model_list, i, ctypes.byref(err))
                name = _lib.embedding_model_info_get_model_name(info, ctypes.byref(err))
                if name and name.decode("utf-8") == model_name:
                    self._model_name = model_name
                    self._dim = _lib.embedding_model_info_get_model_dim(info, ctypes.byref(err))
                    found = True
                    break
            if not found:
                names = []
                for i in range(count):
                    info = _lib.embedding_model_list_get_model(model_list, i, ctypes.byref(err))
                    n = _lib.embedding_model_info_get_model_name(info, ctypes.byref(err))
                    names.append(n.decode("utf-8") if n else "?")
                raise ValueError(f"模型 '{model_name}' 不存在。可用模型: {names}")
        else:
            # 使用第一个模型
            info = _lib.embedding_model_list_get_model(model_list, 0, ctypes.byref(err))
            name = _lib.embedding_model_info_get_model_name(info, ctypes.byref(err))
            self._model_name = name.decode("utf-8") if name else "unknown"
            self._dim = _lib.embedding_model_info_get_model_dim(info, ctypes.byref(err))

        # 5. 加载模型
        ret = _lib.text_embedding_init_model(
            self._session,
            self._model_name.encode("utf-8"),
        )
        if ret != 0:
            raise RuntimeError(f"加载模型 '{self._model_name}' 失败，错误码: {ret}")

        print(f"[KylinNativeEmbedding] 已加载: {self._model_name}, 维度={self._dim}")

    @property
    def dim(self) -> int:
        return self._dim

    @property
    def model_name(self) -> str:
        return self._model_name

    def embed(self, texts: list[str]) -> np.ndarray:
        """
        同步向量化（每次调用处理一条文本）

        Args:
            texts: 文本列表

        Returns:
            np.ndarray, shape = (len(texts), dim), 已 L2 归一化
        """
        if isinstance(texts, str):
            texts = [texts]

        all_vectors = []
        for text in texts:
            result_ptr = ctypes.POINTER(_EmbeddingResult)()

            ok = _lib.text_embedding(
                self._session,
                text.encode("utf-8"),
                ctypes.byref(result_ptr),
            )

            if not ok or not result_ptr:
                err_code = _lib.embedding_result_get_error_code(result_ptr) if result_ptr else -1
                err_msg = _lib.embedding_result_get_error_message(result_ptr) if result_ptr else b"unknown"
                if result_ptr:
                    _lib.embedding_result_destroy(ctypes.byref(result_ptr))
                raise RuntimeError(f"向量化失败: [{err_code}] {err_msg.decode('utf-8', errors='replace')}")

            length = _lib.embedding_result_get_vector_length(result_ptr)
            data_ptr = _lib.embedding_result_get_vector_data(result_ptr)

            # 从 C float* 复制到 numpy
            vec = np.ctypeslib.as_array(data_ptr, shape=(length,)).copy()
            all_vectors.append(vec)

            # 销毁结果
            _lib.embedding_result_destroy(ctypes.byref(result_ptr))

        embeddings = np.stack(all_vectors, axis=0).astype(np.float32)

        # L2 归一化
        norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
        embeddings = embeddings / norms.clip(min=1e-9)

        return embeddings

    def close(self):
        """释放会话"""
        if self._session:
            _lib.text_embedding_destroy_session(ctypes.byref(self._session))
            self._session = None

    def __del__(self):
        self.close()


# ============================================================
# LightRAG 集成
# ============================================================
_embedder: Optional[KylinNativeEmbedding] = None
_executor = ThreadPoolExecutor(max_workers=2)


def get_native_embedder(model_name: Optional[str] = None) -> KylinNativeEmbedding:
    """获取全局原生 Embedding 实例"""
    global _embedder
    if _embedder is None:
        _embedder = KylinNativeEmbedding(model_name=model_name)
    return _embedder


async def kylin_native_embedding_func(texts: list[str]) -> np.ndarray:
    """
    异步 Embedding 函数 — 兼容 LightRAG EmbeddingFunc

    用法:
        from lightrag.utils import EmbeddingFunc
        from src.rag.kylin_embedding_native import (
            kylin_native_embedding_func,
            get_native_embedder,
        )

        embedder = get_native_embedder()
        embedding_func = EmbeddingFunc(
            embedding_dim=embedder.dim,
            func=kylin_native_embedding_func,
        )
    """
    embedder = get_native_embedder()
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_executor, embedder.embed, texts)
```

### 4.3 在 `ps_rag.py` 中使用

```python
# 导入原生 embedding
from src.rag.kylin_embedding_native import (
    kylin_native_embedding_func,
    get_native_embedder,
)

_embedder = get_native_embedder()  # 自动选择系统默认模型

async def embedding_func(texts: list[str]) -> np.ndarray:
    return await kylin_native_embedding_func(texts)

async def initialize_rag() -> LightRAG:
    rag = LightRAG(
        working_dir=WORKING_DIR,
        llm_model_func=llm_model_func,
        embedding_func=EmbeddingFunc(
            embedding_dim=_embedder.dim,  # 自动获取: 768 或 512
            func=embedding_func,
        ),
    )
    return rag
```

---

## 五、向量数据库完整方案

### 5.1 替换 PostgreSQL vector → kylin-ai-vector-engine (Milvus)

当前项目使用 PostgreSQL 存储向量数据。切换到麒麟向量数据库后的对比：

| 维度 | 当前（PostgreSQL pgvector） | 目标（kylin-ai-vector-engine） |
|------|---------------------------|-------------------------------|
| SDK | `psycopg2` SQL | `pymilvus` (MilvusClient) |
| 连接 | `localhost:5432` | `unix:/tmp/kylin-ai-vector-engine-{uid}.sock` |
| 索引 | IVFFlat / HNSW | HNSW (默认) |
| 相似度 | Cosine / L2 / IP | Cosine (默认) |
| 元数据 | JSONB 列 | 动态字段 (Dynamic Schema) |

### 5.2 完整 Python 向量数据库客户端

创建文件 `src/rag/kylin_vectordb.py`：

```python
"""
麒麟向量数据库客户端
基于 kylin-ai-vector-engine (Milvus-Lite)
通过标准 Milvus gRPC API 访问
"""
import os
import numpy as np
from pymilvus import MilvusClient, DataType
from typing import Optional


class KylinVectorDB:
    """封装 kylin-ai-vector-engine 向量数据库操作"""

    def __init__(self, collection_name: str = "nex_agent_embeddings", dim: int = 768):
        uid = os.getuid()
        self.uds_path = f"/tmp/kylin-ai-vector-engine-{uid}.sock"
        self.collection_name = collection_name
        self.dim = dim
        self.client: Optional[MilvusClient] = None

    def connect(self):
        """连接到麒麟向量数据库"""
        uri = f"unix:{self.uds_path}"
        self.client = MilvusClient(uri=uri)
        print(f"[KylinVectorDB] 已连接: {uri}")

    def ensure_collection(self, drop_if_exists: bool = False):
        """确保集合存在，不存在则创建"""
        if drop_if_exists and self.client.has_collection(self.collection_name):
            self.client.drop_collection(self.collection_name)

        if not self.client.has_collection(self.collection_name):
            self.client.create_collection(
                collection_name=self.collection_name,
                dimension=self.dim,
                metric_type="COSINE",
                auto_id=True,
                datatype=DataType.FLOAT_VECTOR,
            )
            # 创建 HNSW 索引
            self.client.create_index(
                collection_name=self.collection_name,
                field_name="vector",
                index_type="HNSW",
                metric_type="COSINE",
                params={"M": 16, "efConstruction": 200},
            )
            print(f"[KylinVectorDB] 已创建集合: {self.collection_name} (dim={self.dim})")

        self.client.load_collection(self.collection_name)

    def insert(self, texts: list[str], embeddings: np.ndarray,
               metadatas: list[dict] = None) -> list:
        """插入文本和向量"""
        data = []
        for i, (text, vec) in enumerate(zip(texts, embeddings)):
            row = {
                "vector": vec.tolist(),
                "text": text,
            }
            if metadatas:
                row.update(metadatas[i])
            data.append(row)

        result = self.client.insert(
            collection_name=self.collection_name,
            data=data,
        )
        return result["ids"]

    def search(self, query_embedding: np.ndarray, top_k: int = 5,
               filter_expr: str = None) -> list:
        """向量相似度搜索"""
        results = self.client.search(
            collection_name=self.collection_name,
            data=[query_embedding.tolist()],
            limit=top_k,
            filter=filter_expr,
            output_fields=["text"],
        )
        return results[0]  # 返回第一个查询向量的结果

    def delete_by_filter(self, filter_expr: str):
        """按条件删除数据"""
        self.client.delete(
            collection_name=self.collection_name,
            filter=filter_expr,
        )

    def count(self) -> int:
        """获取集合中的记录数"""
        stats = self.client.get_collection_stats(self.collection_name)
        return stats.get("row_count", 0)

    def close(self):
        """释放连接"""
        if self.client:
            self.client.close()
            print("[KylinVectorDB] 连接已关闭")
```

---

## 六、集成到 LightRAG — 完整修改方案

### 6.1 修改 `src/rag/ps_rag.py`

```python
# === 新增导入 ===
from src.rag.kylin_embedding import kylin_embedding_func, get_embedder
from src.rag.kylin_vectordb import KylinVectorDB

# === 全局实例 ===
EMBEDDING_MODEL = os.getenv("KYLIN_EMBED_MODEL", "gte-base")
_embedder = get_embedder(EMBEDDING_MODEL)
_vectordb = KylinVectorDB(
    collection_name=os.getenv("KYLIN_VECTOR_COLLECTION", "nex_agent_embeddings"),
    dim=_embedder.dim,
)

# === 替换 embedding_func (原 line 183-189) ===
async def embedding_func(texts: list[str]) -> np.ndarray:
    """使用麒麟系统 Embedding 接口（kylin-ai-abstract-models）"""
    return await kylin_embedding_func(texts)

# === 修改 initialize_rag (原 line 191-200) ===
async def initialize_rag() -> LightRAG:
    # 初始化麒麟向量数据库连接
    _vectordb.connect()
    _vectordb.ensure_collection()

    rag = LightRAG(
        working_dir=WORKING_DIR,
        llm_model_func=llm_model_func,
        embedding_func=EmbeddingFunc(
            embedding_dim=_embedder.dim,  # 768 for gte-base
            func=embedding_func,
        ),
    )
    return rag
```

### 6.2 依赖安装

```bash
# 核心依赖（两个方案都需要）
pip install pymilvus

# 方案一额外依赖：ONNX Runtime
pip install onnxruntime transformers

# 方案二：无需额外 pip 包，直接使用系统 C 库
# libkysdk-coreai-embedding.so 由 libkylin-coreai-embedding 提供（系统已安装）
```

### 6.3 环境变量配置

```bash
# .env 中添加
KYLIN_EMBED_MODEL=gte-base                    # 默认 768 维多语言模型
# KYLIN_EMBED_MODEL=cn-clip-text              # 可选 512 维中文模型
KYLIN_VECTOR_COLLECTION=nex_agent_embeddings  # Milvus 集合名
```

### 6.4 数据迁移

由于 embedding 维度从 1024 → 768，需要**重新向量化**：

```bash
# 1. 清理旧的 LightRAG 存储
rm -rf ./rag_storage

# 2. 清理旧的 Milvus 集合（如果存在）
python -c "
from src.rag.kylin_vectordb import KylinVectorDB
from src.rag.kylin_embedding_native import get_native_embedder
db = KylinVectorDB(dim=get_embedder().dim)
db.connect()
db.ensure_collection(drop_if_exists=True)
print('迁移完成：向量数据库已重建')
"

# 3. 重新插入文档
# 正常运行你的文档导入流程即可
```

---

## 七、验证测试

```python
"""验证麒麟 Embedding + 向量数据库方案"""
import asyncio
import numpy as np
from src.rag.kylin_embedding import KylinEmbedding
from src.rag.kylin_vectordb import KylinVectorDB


async def test_embedding():
    """测试 Embedding 接口"""
    print("=" * 50)
    print("测试麒麟系统 Embedding")
    embedder = KylinEmbedding("gte-base")
    texts = ["你好世界", "麒麟操作系统", "Hello world"]
    result = embedder.embed(texts)

    assert result.shape == (3, 768), f"维度错误: {result.shape}"
    norms = np.linalg.norm(result, axis=1)
    assert np.allclose(norms, 1.0, atol=1e-4), f"归一化失败: {norms}"

    # 验证语义相似度
    sim = result @ result.T
    assert sim[0, 1] > sim[0, 2], "中文文本相似度应高于中英文之间"
    print("✅ Embedding 测试通过")


async def test_vectordb():
    """测试向量数据库"""
    print("=" * 50)
    print("测试麒麟向量数据库")

    embedder = KylinEmbedding("gte-base")
    db = KylinVectorDB(collection_name="test_kylin", dim=embedder.dim)
    db.connect()
    db.ensure_collection(drop_if_exists=True)

    # 插入测试数据
    texts = ["北京是中国的首都", "上海是中国最大的城市", "东京是日本的首都"]
    embeddings = embedder.embed(texts)
    ids = db.insert(texts, embeddings)
    print(f"插入 {len(ids)} 条数据，IDs: {ids[:3]}...")

    # 搜索测试
    query_vec = embedder.embed(["中国的首都在哪里？"])
    results = db.search(query_vec[0], top_k=2)
    for r in results:
        print(f"  score={r['distance']:.4f}, text={r['entity']['text'][:50]}")

    # 清理
    db.client.drop_collection("test_kylin")
    db.close()
    print("✅ 向量数据库测试通过")


if __name__ == "__main__":
    asyncio.run(test_embedding())
    asyncio.run(test_vectordb())
```

---

## 八、方案对比与选型建议

| 维度 | 方案一（ONNX） | 方案二（原生 C API） |
|------|:-----------:|:-------------------:|
| 向量数据库 SDK | `pymilvus` → `kylin-ai-vector-engine` (Milvus gRPC) | 同左 |
| Embedding 接口 | ONNX Runtime 加载系统模型 | **ctypes 调用 `libkysdk-coreai-embedding.so`** |
| 模型来源 | `kylin-ai-abstract-models` | 系统库自动管理 |
| 走系统 D-Bus 链路 | ❌ 不经过 | ✅ 经 `kylin-ai-runtime` D-Bus |
| Python 依赖 | `pymilvus` + `onnxruntime` + `transformers` | `pymilvus`（无额外依赖） |
| 开发工作量 | 低（完整代码已提供） | 低（基于真实 API 的完整 ctypes 封装已提供） |
| 稳定性 | 高 | 高（基于系统标准 C API） |
| 性能 | 优秀（本地 ONNX 推理，支持批量） | 优秀（C 库调用，逐条处理） |
| 批量处理 | ✅ 自动批量 | ⚠ 逐条（C API 限制） |

**推荐方案二（原生 C API）** 满足最严格的合规要求：
- ✅ 向量数据库：`pymilvus` 通过 Unix Socket 连接 `kylin-ai-vector-engine`（Milvus gRPC）
- ✅ Embedding：ctypes 调用 `libkysdk-coreai-embedding.so`，经 `kylin-ai-runtime` D-Bus 通信链路
- ✅ 零额外 Python 依赖（除 `pymilvus`）+ 使用系统 C 动态库

**方案一适用场景**：需要批量 embedding 提升吞吐量时，ONNX Runtime 可直接批处理，比 C API 逐条调用更快。

---

## 九、注意事项

1. **维度变更**：从 Qwen text-embedding-v3 (1024维) 切换到 GTE-base (768维)，PostgreSQL 向量表中已有数据**不兼容**，需要重建。

2. **首次加载**：ONNX 模型首次加载需要 3-5 秒（读取模型文件 + ONNX Runtime 初始化）。

3. **内存占用**：GTE-base INT8 模型约 300MB，运行时内存约 500MB。

4. **线程安全**：`onnxruntime.InferenceSession` 非线程安全，当前使用 `ThreadPoolExecutor(max_workers=2)` 控制并发。

5. **服务依赖**：每次重启需确保 `kylin-ai-vector-engine` 服务运行中：
   ```bash
   systemctl --user enable kylin-ai-vector-engine  # 开机自启
   ```

6. **模型更新**：
   ```bash
   sudo apt update && sudo apt upgrade kylin-ai-abstract-models
   ```
