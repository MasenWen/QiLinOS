"""注册麒麟 Embedder + 向量数据库 到 Mem0 Factory"""
from mem0.utils.factory import EmbedderFactory, VectorStoreFactory

EmbedderFactory.provider_to_class["kylin_sdk"] = (
    "src.memory.kylin_embedder.KylinEmbedder"
)

# 新增这一行
# EmbedderFactory.provider_to_class["gte_zh_onnx"] = (
#     "src.memory.gte_zh_embedder.GteZhOnnxEmbedder"
# )

# 麒麟向量数据库适配器
VectorStoreFactory.provider_to_class["kylin_vectordb"] = (
    "src.memory.kylin_mem0_adapter.KylinMem0Adapter"
)
