"""注册麒麟 Embedder 到 Mem0 Factory"""
from mem0.utils.factory import EmbedderFactory

EmbedderFactory.provider_to_class["kylin_onnx"] = (
    "src.memory.kylin_embedder.KylinEmbedder"
)