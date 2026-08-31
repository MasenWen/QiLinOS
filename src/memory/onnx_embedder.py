#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""本地 ONNX Embedder — Mem0 EmbeddingBase 接口（去 genai 依赖）。

使用项目已有的 KylinONNXEmbedding（embedding_onnx.py），
本地 ONNX Runtime 直接推理 gte-base 模型（768 维），不经过 kylin-ai-runtime。
"""
import logging
import threading

import numpy as np
from mem0.embeddings.base import EmbeddingBase
from mem0.configs.embeddings.base import BaseEmbedderConfig

logger = logging.getLogger("memory.onnx_embedder")

_lock = threading.Lock()
_engine = None


def _get_engine():
    global _engine
    with _lock:
        if _engine is None:
            from src.memory.embedding_onnx import KylinONNXEmbedding
            _engine = KylinONNXEmbedding()
            logger.info("本地 ONNX embedding 引擎已加载 (gte-base 768维)")
        return _engine


class OnnxEmbedder(EmbeddingBase):
    """本地 ONNX embedding — mem0 工厂可用，替代 kylin_sdk 麒麟依赖。"""

    def __init__(self, config: BaseEmbedderConfig | None = None):
        super().__init__(config=config or BaseEmbedderConfig(embedding_dims=768))
        self._engine = None

    @property
    def model_config(self):
        return self.config.model_dump(serialize_as_any=True)

    def embed(self, text, memory_action=None):
        """单条 embedding → list[float]"""
        return self.embed_batch([text], memory_action)[0]

    def embed_batch(self, texts, memory_action=None):
        """批量 embedding → list[list[float]]"""
        engine = _get_engine()
        if isinstance(texts, str):
            texts = [texts]
        texts = [t or " " for t in texts]
        vectors = engine.embed(texts)
        return [vec.tolist() for vec in vectors]


def get_embedder(config=None):
    return OnnxEmbedder(config)