"""麒麟 ONNX Embedder — Mem0 EmbeddingBase 接口"""
import numpy as np
from mem0.embeddings.base import EmbeddingBase
from mem0.configs.embeddings.base import BaseEmbedderConfig
from pathlib import Path
from typing import Optional, Literal

ONNX_PATH = (
    "/usr/share/kylin-ai/model-repository/embd_gte-base_uint8-text/1/"
    "gte-base-multilingual-model_QUInt8.onnx"
)
TOKENIZER_PATH = (
    "/usr/share/kylin-ai/model-repository/"
    "tokenizer_gte-base_uint8-text/tokenizer.json"
)


class KylinEmbedder(EmbeddingBase):

    def __init__(self, config: Optional[BaseEmbedderConfig] = None):
        super().__init__(config)
        import onnxruntime as ort
        from tokenizers import Tokenizer

        if not Path(ONNX_PATH).exists():
            raise FileNotFoundError(
                f"模型不存在: {ONNX_PATH}\n"
                f"请安装: sudo apt install kylin-ai-abstract-models"
            )

        self._session = ort.InferenceSession(ONNX_PATH)
        self._tokenizer = Tokenizer.from_file(TOKENIZER_PATH)
        self._tokenizer.enable_padding(pad_id=0, pad_token="[PAD]")
        self._tokenizer.enable_truncation(max_length=512)

    def embed(self, text, memory_action: Optional[Literal[
        "add", "search", "update"]] = None):
        return self.embed_batch([text], memory_action)[0]

    def embed_batch(self, texts, memory_action=None):
        result = []
        for text in texts:
            enc = self._tokenizer.encode(text)
            ids = np.array([enc.ids], dtype=np.int64)
            mask = np.array([enc.attention_mask], dtype=np.int64)
            out = self._session.run(
                None, {"input_ids": ids, "attention_mask": mask})
            m = mask[:, :, None].astype(np.float32)
            emb = (out[0] * m).sum(axis=1) / m.sum(axis=1).clip(min=1e-9)
            vec = emb[0].astype(np.float32)
            vec = vec / (np.linalg.norm(vec) + 1e-9)
            result.append(vec.tolist())
        return result