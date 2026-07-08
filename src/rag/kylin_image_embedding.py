"""
麒麟 AI SDK 图片向量化 — 严格对应《麒麟SDK开发指南》9.4.3.2 节

头文件:   #include <coreai/embedding/embedding.h>
库文件:   libkysdk-coreai-embedding.so

模型: CN-CLIP ViT-B/16 INT8, 512维, 图文跨模态对齐
模型路径: /usr/share/kylin-ai/model-repository/embd_cn-clip_512-uint8-image/

API:
  image_embedding_create_session()                  → ImageEmbeddingSession*
  image_embedding_init_session(session)              → int (0=成功)
  image_embedding_init_model(session, name)          → int
  image_embedding_by_image_file(session, path, &r)   → bool (图片→向量)
  image_embedding_by_base64_image_data(s, data, len, &r) → bool
  text_embedding_by_image_model(session, text, &r)   → bool (跨模态: 文本→同一空间)
  embedding_result_get_vector_data/error_code/...    → 同文本向量化
  image_embedding_destroy_session(&session)          → void
"""
import ctypes
import numpy as np
from typing import Optional

_lib = ctypes.CDLL("libkysdk-coreai-embedding.so.1")

# ============================================================
# 不透明结构体
# ============================================================
class _ImageEmbeddingSession(ctypes.Structure):
    pass

class _EmbeddingResult(ctypes.Structure):
    pass

# ============================================================
# 函数签名 (PDF 9.4.3.2)
# ============================================================

# --- 会话管理 ---
_lib.image_embedding_create_session.restype = ctypes.POINTER(_ImageEmbeddingSession)

_lib.image_embedding_init_session.argtypes = [ctypes.POINTER(_ImageEmbeddingSession)]
_lib.image_embedding_init_session.restype = ctypes.c_int

_lib.image_embedding_destroy_session.argtypes = [
    ctypes.POINTER(ctypes.POINTER(_ImageEmbeddingSession))]

# --- 模型信息 ---
_lib.image_embedding_get_model_info.argtypes = [
    ctypes.POINTER(_ImageEmbeddingSession), ctypes.POINTER(ctypes.c_char_p)]
_lib.image_embedding_get_model_info.restype = ctypes.c_bool

_lib.image_embedding_init_model.argtypes = [
    ctypes.POINTER(_ImageEmbeddingSession), ctypes.c_char_p]
_lib.image_embedding_init_model.restype = ctypes.c_int

# --- 同步向量化 ---
_lib.image_embedding_by_image_file.argtypes = [
    ctypes.POINTER(_ImageEmbeddingSession),
    ctypes.c_char_p,
    ctypes.POINTER(ctypes.POINTER(_EmbeddingResult)),
]
_lib.image_embedding_by_image_file.restype = ctypes.c_bool

_lib.text_embedding_by_image_model.argtypes = [
    ctypes.POINTER(_ImageEmbeddingSession),
    ctypes.c_char_p,
    ctypes.POINTER(ctypes.POINTER(_EmbeddingResult)),
]
_lib.text_embedding_by_image_model.restype = ctypes.c_bool

# --- 结果解析 (同 9.4.3.1 文本向量化) ---
_lib.embedding_result_get_vector_data.argtypes = [ctypes.POINTER(_EmbeddingResult)]
_lib.embedding_result_get_vector_data.restype = ctypes.POINTER(ctypes.c_float)

_lib.embedding_result_get_vector_length.argtypes = [ctypes.POINTER(_EmbeddingResult)]
_lib.embedding_result_get_vector_length.restype = ctypes.c_int

_lib.embedding_result_get_error_code.argtypes = [ctypes.POINTER(_EmbeddingResult)]
_lib.embedding_result_get_error_code.restype = ctypes.c_int

_lib.embedding_result_get_error_message.argtypes = [ctypes.POINTER(_EmbeddingResult)]
_lib.embedding_result_get_error_message.restype = ctypes.c_char_p

_lib.embedding_result_destroy.argtypes = [
    ctypes.POINTER(ctypes.POINTER(_EmbeddingResult))]


# ============================================================
# Python 封装
# ============================================================

class KylinImageEmbedding:
    """
    麒麟图片向量化 — CN-CLIP ViT-B/16 512维，支持图文跨模态

    用法:
        e = KylinImageEmbedding()
        img_vec = e.embed_image("/path/to/img.png")            # 图片→512维
        txt_vec = e.embed_text("一只猫")                       # 文本→同一空间
        sim    = float(img_vec @ txt_vec)                      # 图文相似度
        e.close()
    """

    def __init__(self):
        # 1. 创建会话 (PDF: image_embedding_create_session)
        self._session = _lib.image_embedding_create_session()
        if not self._session:
            raise RuntimeError("image_embedding_create_session 失败")

        # 2. 初始化 (PDF: image_embedding_init_session)
        ret = _lib.image_embedding_init_session(self._session)
        if ret != 0:
            raise RuntimeError(f"image_embedding_init_session 失败: {ret}")

        # 3. 获取模型信息 (PDF: image_embedding_get_model_info)
        # 返回: {"dim":1024, "image_name":"embd_cn-clip_512-uint8-image",
        #         "image_text_name":"ensemble-embd_cn-clip_512-uint8-text"}
        info_ptr = ctypes.c_char_p()
        ok = _lib.image_embedding_get_model_info(
            self._session, ctypes.byref(info_ptr))
        if ok and info_ptr and info_ptr.value:
            import json
            info = json.loads(info_ptr.value.decode("utf-8"))
            self._image_model = info["image_name"]        # 图片模型
            self._text_model = info["image_text_name"]    # 跨模态文本模型
            self.dim = info["dim"]                        # 1024
        else:
            self._image_model = "unknown"
            self._text_model = "unknown"
            self.dim = 1024

        # 4. runtime 自动加载默认模型
        # 与 PDF 9.4.3.1 文本向量化示例一致

    def embed_image(self, image_path: str) -> np.ndarray:
        """
        图片文件 → 1024维向量
        参考官方 C++ 示例: 读文件 → base64 → image_embedding_by_base64_image_data
        """
        import base64
        with open(image_path, "rb") as f:
            data = f.read()
        b64 = base64.b64encode(data)
        return self.embed_base64(b64)

    def embed_base64(self, base64_data: bytes) -> np.ndarray:
        """
        base64 图片数据 → 1024维向量 (PDF: image_embedding_by_base64_image_data)
        """
        result_ptr = ctypes.POINTER(_EmbeddingResult)()
        ok = _lib.image_embedding_by_base64_image_data(
            self._session,
            base64_data,
            len(base64_data),
            ctypes.byref(result_ptr),
        )
        return self._parse_result(result_ptr, ok)

    def embed_image_by_path(self, image_path: str) -> np.ndarray:
        """
        图片文件 → 1024维向量 (PDF: image_embedding_by_image_file)
        直接传路径，不走 base64 编码
        """
        result_ptr = ctypes.POINTER(_EmbeddingResult)()
        ok = _lib.image_embedding_by_image_file(
            self._session,
            image_path.encode("utf-8"),
            ctypes.byref(result_ptr),
        )
        return self._parse_result(result_ptr, ok)

    def embed_text(self, text: str) -> np.ndarray:
        """
        文本 → 同一512维空间 (PDF: text_embedding_by_image_model)
        用于跨模态检索: 文字→图片搜索
        """
        result_ptr = ctypes.POINTER(_EmbeddingResult)()
        ok = _lib.text_embedding_by_image_model(
            self._session,
            text.encode("utf-8"),
            ctypes.byref(result_ptr),
        )
        return self._parse_result(result_ptr, ok)

    def embed_texts(self, texts: list[str]) -> np.ndarray:
        """批量文本 → 512维向量"""
        return np.stack([self.embed_text(t) for t in texts])

    def _parse_result(self, result_ptr, ok) -> np.ndarray:
        if not ok:
            code = _lib.embedding_result_get_error_code(result_ptr)
            msg_ptr = _lib.embedding_result_get_error_message(result_ptr)
            msg = msg_ptr.decode("utf-8", errors="replace") if msg_ptr else "?"
            _lib.embedding_result_destroy(ctypes.byref(result_ptr))
            raise RuntimeError(f"图片向量化失败 [{code}]: {msg}")

        length = _lib.embedding_result_get_vector_length(result_ptr)
        data = _lib.embedding_result_get_vector_data(result_ptr)
        vec = np.ctypeslib.as_array(data, shape=(length,)).copy()
        _lib.embedding_result_destroy(ctypes.byref(result_ptr))
        vec = vec.astype(np.float32)
        return vec / (np.linalg.norm(vec) + 1e-9)

    def close(self):
        """销毁会话 (PDF: image_embedding_destroy_session)"""
        if self._session:
            _lib.image_embedding_destroy_session(ctypes.byref(self._session))
            self._session = None
