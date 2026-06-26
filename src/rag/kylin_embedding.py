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