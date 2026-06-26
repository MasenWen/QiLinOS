"""
麒麟文本向量化 — ONNX Runtime 方案
直接加载系统模型（kylin-ai-abstract-models），不经过 kylin-ai-runtime

模型: gte-base-multilingual-model_QUInt8.onnx (324MB, 768维, INT8量化)
来源: kylin-ai-abstract-models 系统包
路径: /usr/share/kylin-ai/model-repository/
"""
import numpy as np
import asyncio
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

# 系统模型路径
ONNX_MODEL_PATH = (
    "/usr/share/kylin-ai/model-repository/embd_gte-base_uint8-text/1/"
    "gte-base-multilingual-model_QUInt8.onnx"
)
TOKENIZER_PATH = (
    "/usr/share/kylin-ai/model-repository/"
    "tokenizer_gte-base_uint8-text/tokenizer.json"
)


class KylinONNXEmbedding:
    """
    麒麟文本向量化 — ONNX Runtime 直接推理

    用法:
        embedder = KylinONNXEmbedding()
        vec = embedder.embed(["你好世界"])
    """

    def __init__(self):
        import onnxruntime as ort
        from tokenizers import Tokenizer

        if not Path(ONNX_MODEL_PATH).exists():
            raise FileNotFoundError(
                f"系统模型不存在: {ONNX_MODEL_PATH}\n"
                f"请安装: sudo apt install kylin-ai-abstract-models"
            )
        if not Path(TOKENIZER_PATH).exists():
            raise FileNotFoundError(
                f"Tokenizer 不存在: {TOKENIZER_PATH}\n"
                f"请安装: sudo apt install kylin-ai-abstract-models"
            )

        self.dim = 768
        self._session = ort.InferenceSession(ONNX_MODEL_PATH)
        self._tokenizer = Tokenizer.from_file(TOKENIZER_PATH)
        self._tokenizer.enable_padding(pad_id=0, pad_token="[PAD]")
        self._tokenizer.enable_truncation(max_length=512)

    def embed(self, texts: list[str]) -> np.ndarray:
        """文本 → 768维归一化向量"""
        if isinstance(texts, str):
            texts = [texts]
        result = []
        for text in texts:
            enc = self._tokenizer.encode(text)
            ids = np.array([enc.ids], dtype=np.int64)
            mask = np.array([enc.attention_mask], dtype=np.int64)
            out = self._session.run(
                None, {"input_ids": ids, "attention_mask": mask})
            m = mask[:, :, None].astype(np.float32)
            emb = (out[0] * m).sum(axis=1) / m.sum(axis=1).clip(min=1e-9)
            result.append(emb[0])
        embeddings = np.stack(result).astype(np.float32)
        norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
        return embeddings / norms.clip(min=1e-9)


# ============================================================
# LightRAG 集成
# ============================================================
_embedder: Optional[KylinONNXEmbedding] = None
_executor = ThreadPoolExecutor(max_workers=1)


def get_onnx_embedder() -> KylinONNXEmbedding:
    """获取全局 ONNX embedding 实例（懒加载）"""
    global _embedder
    if _embedder is None:
        _embedder = KylinONNXEmbedding()
    return _embedder


async def kylin_onnx_embedding_func(texts: list[str]) -> np.ndarray:
    """异步 embedding — 兼容 LightRAG EmbeddingFunc"""
    embedder = get_onnx_embedder()
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_executor, embedder.embed, texts)
