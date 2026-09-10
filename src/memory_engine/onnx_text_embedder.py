#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""本地 ONNX 文本嵌入（onnxruntime + tokenizers），用于没有麒麟运行时的机器。

仓库自带 models/bge-small-zh-v1.5/{onnx_model_quantized.onnx,tokenizer.json}
（512 维，last_hidden_state）。本模块把它包成与 EmbeddingService/
KylinEmbedder 兼容的最小接口：embed(text) / embed_batch(texts) → np.ndarray。

可通过环境变量覆盖路径：
  NEX_ONNX_MODEL_PATH      默认 models/bge-small-zh-v1.5/onnx_model_quantized.onnx
  NEX_ONNX_TOKENIZER_PATH  默认 models/bge-small-zh-v1.5/tokenizer.json
  NEX_ONNX_POOLING         cls|mean（默认：bge* 用 cls，其余 mean）
"""
from __future__ import annotations

import os
import threading
from pathlib import Path

import numpy as np

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DIR = _REPO_ROOT / "models" / "bge-small-zh-v1.5"

_lock = threading.Lock()
_instances: dict[tuple[str, str, str], "OnnxTextEmbedder"] = {}


def default_model_path() -> str:
    return os.getenv("NEX_ONNX_MODEL_PATH",
                     str(_DEFAULT_DIR / "onnx_model_quantized.onnx"))


def default_tokenizer_path() -> str:
    return os.getenv("NEX_ONNX_TOKENIZER_PATH",
                     str(_DEFAULT_DIR / "tokenizer.json"))


class OnnxTextEmbedder:
    """最小可用的本地 ONNX 文本嵌入。"""

    backend_id = "local_onnx_text"

    def __init__(self, model_path: str | None = None, tokenizer_path: str | None = None,
                 pooling: str | None = None, max_length: int = 512):
        import onnxruntime as ort
        from tokenizers import Tokenizer

        self.model_path = model_path or default_model_path()
        self.tokenizer_path = tokenizer_path or default_tokenizer_path()
        if not os.path.exists(self.model_path):
            raise FileNotFoundError("ONNX 模型不存在: %s" % self.model_path)
        if not os.path.exists(self.tokenizer_path):
            raise FileNotFoundError("tokenizer 不存在: %s" % self.tokenizer_path)

        self._session = ort.InferenceSession(self.model_path,
                                             providers=["CPUExecutionProvider"])
        self._tok = Tokenizer.from_file(self.tokenizer_path)
        self._tok.enable_truncation(max_length=max_length)
        self._tok.enable_padding(pad_id=0, pad_token="[PAD]")
        self._input_names = {i.name for i in self._session.get_inputs()}
        out_shape = self._session.get_outputs()[0].shape
        self.dim = int(out_shape[-1]) if isinstance(out_shape[-1], int) else 512
        self._pooling = (pooling or os.getenv("NEX_ONNX_POOLING") or
                         ("cls" if "bge" in self.model_path.lower() else "mean")).lower()
        self.backend_id = "local_onnx(%s)" % Path(self.model_path).parent.name

    @staticmethod
    def get(model_path: str | None = None, tokenizer_path: str | None = None) -> "OnnxTextEmbedder":
        """按路径缓存单例（避免重复加载 30~100MB 模型）。"""
        key = (model_path or default_model_path(), tokenizer_path or default_tokenizer_path(),
               os.getenv("NEX_ONNX_POOLING", ""))
        with _lock:
            inst = _instances.get(key)
            if inst is None:
                inst = OnnxTextEmbedder(key[0], key[1])
                _instances[key] = inst
            return inst

    @staticmethod
    def is_available(model_path: str | None = None, tokenizer_path: str | None = None) -> bool:
        mp = model_path or default_model_path()
        tp = tokenizer_path or default_tokenizer_path()
        if not (os.path.exists(mp) and os.path.exists(tp)):
            return False
        try:
            import onnxruntime  # noqa: F401
            from tokenizers import Tokenizer  # noqa: F401
        except Exception:
            return False
        return True

    def _encode(self, texts: list[str]):
        encs = self._tok.encode_batch([t if t and t.strip() else " " for t in texts])
        input_ids = np.array([e.ids for e in encs], dtype=np.int64)
        attention = np.array([e.attention_mask for e in encs], dtype=np.int64)
        feed = {"input_ids": input_ids, "attention_mask": attention}
        if "token_type_ids" in self._input_names:
            feed["token_type_ids"] = np.zeros_like(input_ids)
        feed = {k: v for k, v in feed.items() if k in self._input_names}
        hidden = self._session.run(None, feed)[0]           # (batch, seq, dim)
        mask = attention[..., None].astype(np.float32)      # (batch, seq, 1)
        if self._pooling == "cls":
            vecs = hidden[:, 0, :]
        else:
            summed = (hidden * mask).sum(axis=1)
            counts = np.clip(mask.sum(axis=1), 1e-6, None)
            vecs = summed / counts
        norms = np.linalg.norm(vecs, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return (vecs / norms).astype(np.float32)

    def embed(self, text: str) -> list[float]:
        return self.embed_batch([text])[0].tolist()

    def embed_batch(self, texts, memory_action=None) -> np.ndarray:
        if isinstance(texts, str):
            texts = [texts]
        return self._encode(list(texts))
