"""注册麒麟 Embedder + 向量数据库 + LLM 到 Mem0 Factory"""
from mem0.utils.factory import EmbedderFactory, VectorStoreFactory, LlmFactory

EmbedderFactory.provider_to_class["kylin_sdk"] = (
    "src.memory.kylin_embedder.KylinEmbedder"
)

# 本地 ONNX embedding（去 genai 依赖，2026-08-31）
EmbedderFactory.provider_to_class["local_onnx"] = (
    "src.memory.onnx_embedder.OnnxEmbedder"
)

# 新增这一行
# EmbedderFactory.provider_to_class["gte_zh_onnx"] = (
#     "src.memory.gte_zh_embedder.GteZhOnnxEmbedder"
# )

# 麒麟向量数据库适配器（provider 名 kylin_vectordb 由 KylinMem0Adapter 实现）
VectorStoreFactory.provider_to_class["kylin_vectordb"] = (
    "src.memory.kylin_mem0_adapter.KylinMem0Adapter"
)

# 麒麟千问 LLM 适配器（零 key）
LlmFactory.register_provider("kylin_sdk", "src.memory.kylin_llm.KylinLLM")
