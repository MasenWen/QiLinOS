# -*- coding: utf-8 -*-
"""麒麟文本向量化 — ONNX Runtime 直载系统模型（降级链第 2 级）。

移植自 QiLinOS/src/rag/kylin_embedding_onnx.py（2026-07-09 版），适配本项目：
- 仅保留核心类与异步函数（LightRAG EmbeddingFunc 兼容）
- 日志使用本项目 logging
- 模型: gte-base-multilingual-model_QUInt8.onnx (324MB, 768维, INT8量化)
- 来源: kylin-ai-abstract-models 系统包
"""
from __future__ import annotations

import asyncio
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

import numpy as np

logger = logging.getLogger("rag.onnx")

# 系统模型路径（kylin-ai-abstract-models）
ONNX_MODEL_PATH = (
    "/usr/share/kylin-ai/model-repository/embd_gte-base_uint8-text/1/"
    "gte-base-multilingual-model_QUInt8.onnx"
)
TOKENIZER_PATH = (
    "/usr/share/kylin-ai/model-repository/"
    "tokenizer_gte-base_uint8-text/tokenizer.json"
)


class KylinONNXEmbedding:
    """麒麟文本向量化 — ONNX Runtime 直接推理（不经过 kylin-ai-runtime）。"""

    def __init__(self):
        import onnxruntime as ort
        from tokenizers import Tokenizer

        if not __import__("os").path.exists(ONNX_MODEL_PATH):
            raise FileNotFoundError(
                f"系统模型不存在: {ONNX_MODEL_PATH}\n"
                f"请安装: sudo apt install kylin-ai-abstract-models"
            )
        if not __import__("os").path.exists(TOKENIZER_PATH):
            raise FileNotFoundError(f"Tokenizer 不存在: {TOKENIZER_PATH}")

        self.dim = 768
        self._session = ort.InferenceSession(ONNX_MODEL_PATH)
        self._tokenizer = Tokenizer.from_file(TOKENIZER_PATH)
        self._tokenizer.enable_padding(pad_id=0, pad_token="[PAD]")
        self._tokenizer.enable_truncation(max_length=512)

    def embed(self, texts: list[str]) -> np.ndarray:
        """文本 → 768 维归一化向量。"""
        if isinstance(texts, str):
            texts = [texts]
        result = []
        for text in texts:
            enc = self._tokenizer.encode(text)
            ids = np.array([enc.ids], dtype=np.int64)
            mask = np.array([enc.attention_mask], dtype=np.int64)
            out = self._session.run(None, {"input_ids": ids, "attention_mask": mask})
            m = mask[:, :, None].astype(np.float32)
            emb = (out[0] * m).sum(axis=1) / m.sum(axis=1).clip(min=1e-9)
            result.append(emb[0])
        embeddings = np.stack(result).astype(np.float32)
        norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
        return embeddings / norms.clip(min=1e-9)


# ---------- 单例 + 异步包装 ----------
_embedder: Optional[KylinONNXEmbedding] = None
_embed_lock = threading.Lock()
_executor = ThreadPoolExecutor(max_workers=1)


def get_onnx_embedder() -> KylinONNXEmbedding:
    """全局 ONNX embedding 实例（懒加载 + 线程安全）。"""
    global _embedder
    if _embedder is None:
        with _embed_lock:
            if _embedder is None:
                _embedder = KylinONNXEmbedding()
                logger.info("ONNX 嵌入已加载（系统模型直载，768 维）")
    return _embedder


async def kylin_onnx_embedding_func(texts: list[str]) -> np.ndarray:
    """异步 embedding — 兼容 LightRAG EmbeddingFunc。"""
    try:
        embedder = get_onnx_embedder()
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(_executor, embedder.embed, texts)
    except Exception as e:
        logger.error("ONNX 嵌入失败: %s", e)
        raise
