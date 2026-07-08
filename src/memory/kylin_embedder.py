"""
麒麟 Embedder — Mem0 EmbeddingBase 接口（原生 C API）
对应《麒麟SDK开发指南》9.4.3.1 节

头文件:   #include <coreai/embedding/embedding.h>
库文件:   libkysdk-coreai-embedding.so
"""
import ctypes
import numpy as np
from mem0.embeddings.base import EmbeddingBase
from mem0.configs.embeddings.base import BaseEmbedderConfig
from typing import Optional, Literal

# ============================================================
# 加载系统库 — 与 kylin_embedding_sdk.py 完全一致
# ============================================================
_lib = ctypes.CDLL("libkysdk-coreai-embedding.so.1")

# ============================================================
# 不透明结构体
# ============================================================
class _TextEmbeddingSession(ctypes.Structure):
    pass

class _EmbeddingResult(ctypes.Structure):
    pass

# ============================================================
# 函数签名
# ============================================================
_lib.text_embedding_create_session.restype = ctypes.POINTER(_TextEmbeddingSession)

_lib.text_embedding_init_session.argtypes = [
    ctypes.POINTER(_TextEmbeddingSession)]
_lib.text_embedding_init_session.restype = ctypes.c_int

_lib.text_embedding_destroy_session.argtypes = [
    ctypes.POINTER(ctypes.POINTER(_TextEmbeddingSession))]

_lib.text_embedding.argtypes = [
    ctypes.POINTER(_TextEmbeddingSession),
    ctypes.c_char_p,
    ctypes.POINTER(ctypes.POINTER(_EmbeddingResult)),
]
_lib.text_embedding.restype = ctypes.c_bool

_lib.embedding_result_get_vector_data.argtypes = [
    ctypes.POINTER(_EmbeddingResult)]
_lib.embedding_result_get_vector_data.restype = ctypes.POINTER(ctypes.c_float)

_lib.embedding_result_get_vector_length.argtypes = [
    ctypes.POINTER(_EmbeddingResult)]
_lib.embedding_result_get_vector_length.restype = ctypes.c_int

_lib.embedding_result_get_error_code.argtypes = [
    ctypes.POINTER(_EmbeddingResult)]
_lib.embedding_result_get_error_code.restype = ctypes.c_int

_lib.embedding_result_get_error_message.argtypes = [
    ctypes.POINTER(_EmbeddingResult)]
_lib.embedding_result_get_error_message.restype = ctypes.c_char_p

_lib.embedding_result_destroy.argtypes = [
    ctypes.POINTER(ctypes.POINTER(_EmbeddingResult))]

_lib.text_embedding_get_model_info.argtypes = [
    ctypes.POINTER(_TextEmbeddingSession),
    ctypes.POINTER(ctypes.c_char_p),
]
_lib.text_embedding_get_model_info.restype = ctypes.c_bool

_lib.text_embedding_init_model.argtypes = [
    ctypes.POINTER(_TextEmbeddingSession),
    ctypes.c_char_p,
]
_lib.text_embedding_init_model.restype = ctypes.c_int


# ============================================================
# Mem0 EmbeddingBase 封装
# ============================================================

class KylinEmbedder(EmbeddingBase):
    """麒麟原生 C API Embedder — Mem0 兼容"""

    def __init__(self, config: Optional[BaseEmbedderConfig] = None):
        super().__init__(config)

        # 1. 创建会话 (PDF: text_embedding_create_session)
        self._session = _lib.text_embedding_create_session()
        if not self._session:
            raise RuntimeError("text_embedding_create_session 失败")

        # 2. 初始化 (PDF: text_embedding_init_session)
        ret = _lib.text_embedding_init_session(self._session)
        if ret != 0:
            raise RuntimeError(
                f"text_embedding_init_session 失败，错误码: {ret}")

        # 3. 获取模型信息 (PDF: text_embedding_get_model_info)
        info_ptr = ctypes.c_char_p()
        ok = _lib.text_embedding_get_model_info(
            self._session, ctypes.byref(info_ptr))
        if ok and info_ptr and info_ptr.value:
            import json
            info = json.loads(info_ptr.value.decode("utf-8"))
            model_name = info["name"]
        else:
            model_name = "unknown"

        # 4. 加载模型 (PDF: text_embedding_init_model)
        ret = _lib.text_embedding_init_model(
            self._session, model_name.encode("utf-8"))
        if ret != 0:
            raise RuntimeError(
                f"text_embedding_init_model 失败，错误码: {ret}。\n"
                f"模型: {model_name}")

    def embed(self, text, memory_action: Optional[Literal[
        "add", "search", "update"]] = None):
        """单条 embedding → list[float]"""
        return self.embed_batch([text], memory_action)[0]

    def embed_batch(self, texts, memory_action=None):
        """批量 embedding → list[list[float]]"""
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
                msg = msg_ptr.decode("utf-8",
                    errors="replace") if msg_ptr else "?"
                _lib.embedding_result_destroy(ctypes.byref(result_ptr))
                raise RuntimeError(f"向量化失败 [{code}]: {msg}")

            length = _lib.embedding_result_get_vector_length(result_ptr)
            data = _lib.embedding_result_get_vector_data(result_ptr)
            vec = np.ctypeslib.as_array(data, shape=(length,)).copy()
            result.append(vec.tolist())
            _lib.embedding_result_destroy(ctypes.byref(result_ptr))

        # L2 归一化
        arr = np.array(result, dtype=np.float32)
        norms = np.linalg.norm(arr, axis=1, keepdims=True)
        arr = arr / (norms + 1e-9)
        return arr.tolist()

    def __del__(self):
        if hasattr(self, '_session') and self._session:
            try:
                _lib.text_embedding_destroy_session(
                    ctypes.byref(self._session))
            except Exception:
                pass
