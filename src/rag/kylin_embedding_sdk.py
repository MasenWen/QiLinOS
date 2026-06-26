"""
麒麟 AI SDK 文本向量化 — 严格对应《麒麟SDK开发指南》9.4.3.1 节

头文件:   #include <coreai/embedding/embedding.h>
库文件:   libkysdk-coreai-embedding.so
pkg-config: kysdk-coreai-embedding

API:
  text_embedding_create_session()          → TextEmbeddingSession*
  text_embedding_init_session(session)     → int (0=成功)
  text_embedding(session, text, &result)   → bool (同步向量化)
  embedding_result_get_vector_data(result) → float*
  embedding_result_get_vector_length(r)    → int
  embedding_result_get_error_code(r)       → int
  embedding_result_get_error_message(r)    → const char*
  embedding_result_destroy(&result)        → void
  text_embedding_destroy_session(&session) → void
"""
import ctypes
import numpy as np
import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

# ============================================================
# 加载系统库
# ============================================================
_lib = ctypes.CDLL("libkysdk-coreai-embedding.so.1")

# ============================================================
# 不透明结构体（对应 embedding.h）
# ============================================================
class _TextEmbeddingSession(ctypes.Structure):
    pass

class _EmbeddingResult(ctypes.Structure):
    pass

# ============================================================
# 函数签名（严格对应 PDF 9.4.3.1）
# ============================================================

# --- 会话管理 ---
_lib.text_embedding_create_session.restype = ctypes.POINTER(_TextEmbeddingSession)

_lib.text_embedding_init_session.argtypes = [ctypes.POINTER(_TextEmbeddingSession)]
_lib.text_embedding_init_session.restype = ctypes.c_int

_lib.text_embedding_destroy_session.argtypes = [
    ctypes.POINTER(ctypes.POINTER(_TextEmbeddingSession)),
]

# --- 同步向量化 ---
_lib.text_embedding.argtypes = [
    ctypes.POINTER(_TextEmbeddingSession),
    ctypes.c_char_p,
    ctypes.POINTER(ctypes.POINTER(_EmbeddingResult)),
]
_lib.text_embedding.restype = ctypes.c_bool

# --- 结果解析 ---
_lib.embedding_result_get_vector_data.argtypes = [ctypes.POINTER(_EmbeddingResult)]
_lib.embedding_result_get_vector_data.restype = ctypes.POINTER(ctypes.c_float)

_lib.embedding_result_get_vector_length.argtypes = [ctypes.POINTER(_EmbeddingResult)]
_lib.embedding_result_get_vector_length.restype = ctypes.c_int

_lib.embedding_result_get_error_code.argtypes = [ctypes.POINTER(_EmbeddingResult)]
_lib.embedding_result_get_error_code.restype = ctypes.c_int

_lib.embedding_result_get_error_message.argtypes = [ctypes.POINTER(_EmbeddingResult)]
_lib.embedding_result_get_error_message.restype = ctypes.c_char_p

_lib.embedding_result_destroy.argtypes = [
    ctypes.POINTER(ctypes.POINTER(_EmbeddingResult)),
]

# --- 模型信息（deprecated，兼容旧 runtime） ---
_lib.text_embedding_get_model_info.argtypes = [
    ctypes.POINTER(_TextEmbeddingSession),
    ctypes.POINTER(ctypes.c_char_p),
]
_lib.text_embedding_get_model_info.restype = ctypes.c_bool

# --- 模型加载 ---
_lib.text_embedding_init_model.argtypes = [
    ctypes.POINTER(_TextEmbeddingSession),
    ctypes.c_char_p,
]
_lib.text_embedding_init_model.restype = ctypes.c_int


# ============================================================
# Python 封装
# ============================================================

class KylinTextEmbedding:
    """
    麒麟文本向量化 — 原生 C API

    用法（同步）:
        embedder = KylinTextEmbedding()
        vec = embedder.embed(["你好世界"])
        embedder.close()
    """

    def __init__(self):
        # 1. 创建会话 (PDF: text_embedding_create_session)
        self._session = _lib.text_embedding_create_session()
        if not self._session:
            raise RuntimeError("text_embedding_create_session 失败")

        # 2. 初始化 (PDF: text_embedding_init_session)
        ret = _lib.text_embedding_init_session(self._session)
        if ret != 0:
            raise RuntimeError(
                f"text_embedding_init_session 失败，错误码: {ret}"
            )

        # 3. 获取模型信息 (PDF: text_embedding_get_model_info)
        info_ptr = ctypes.c_char_p()
        ok = _lib.text_embedding_get_model_info(
            self._session, ctypes.byref(info_ptr))
        if ok and info_ptr and info_ptr.value:
            import json
            info = json.loads(info_ptr.value.decode("utf-8"))
            self._model_name = info["name"]
            self.dim = info["dim"]
        else:
            self._model_name = "unknown"
            self.dim = 768

        # 4. 加载模型
        ret = _lib.text_embedding_init_model(
            self._session, self._model_name.encode("utf-8"))
        if ret != 0:
            raise RuntimeError(
                f"text_embedding_init_model 失败，错误码: {ret}。\n"
                f"当前可用模型: {self._model_name} (dim={self.dim})"
            )

    def embed(self, texts: list[str]) -> np.ndarray:
        """
        同步向量化 (PDF 示例):
          text_embedding(session, text, &result)
          float *vec = embedding_result_get_vector_data(result)
          int len = embedding_result_get_vector_length(result)
        """
        if isinstance(texts, str):
            texts = [texts]
        result = []
        for text in texts:
            result_ptr = ctypes.POINTER(_EmbeddingResult)()
            ok = _lib.text_embedding(
                self._session,
                text.encode("utf-8"),
                ctypes.byref(result_ptr),
            )
            if not ok:
                code = _lib.embedding_result_get_error_code(result_ptr)
                msg_ptr = _lib.embedding_result_get_error_message(result_ptr)
                msg = msg_ptr.decode("utf-8", errors="replace") if msg_ptr else "?"
                _lib.embedding_result_destroy(ctypes.byref(result_ptr))
                raise RuntimeError(f"向量化失败 [{code}]: {msg}")

            length = _lib.embedding_result_get_vector_length(result_ptr)
            data = _lib.embedding_result_get_vector_data(result_ptr)
            vec = np.ctypeslib.as_array(data, shape=(length,)).copy()
            result.append(vec)
            _lib.embedding_result_destroy(ctypes.byref(result_ptr))

        embeddings = np.stack(result).astype(np.float32)
        norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
        return embeddings / norms.clip(min=1e-9)

    def close(self):
        """销毁会话 (PDF: text_embedding_destroy_session)"""
        if self._session:
            _lib.text_embedding_destroy_session(ctypes.byref(self._session))
            self._session = None


# ============================================================
# LightRAG 集成
# ============================================================
_embedder: Optional[KylinTextEmbedding] = None
_executor = ThreadPoolExecutor(max_workers=1)


def get_kylin_embedder() -> KylinTextEmbedding:
    """获取全局 embedding 实例（懒加载）"""
    global _embedder
    if _embedder is None:
        _embedder = KylinTextEmbedding()
    return _embedder


async def kylin_sdk_embedding_func(texts: list[str]) -> np.ndarray:
    """异步 embedding — 兼容 LightRAG EmbeddingFunc"""
    embedder = get_kylin_embedder()
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_executor, embedder.embed, texts)
