"""注册麒麟 Embedder + 向量数据库 + LLM 到 Mem0 Factory"""
from mem0.utils.factory import EmbedderFactory, VectorStoreFactory, LlmFactory

EmbedderFactory.provider_to_class["kylin_sdk"] = (
    "src.memory.kylin_embedder.KylinEmbedder"
)

# 本地 ONNX embedding（去 genai 依赖，2026-08-31）
EmbedderFactory.provider_to_class["local_onnx"] = (
    "src.memory.onnx_embedder.OnnxEmbedder"
)

# （历史登记示例：gte_zh_onnx 曾按 dict 赋值方式注册，现以本地 local_onnx 为主）

# 麒麟向量数据库适配器（provider 名 kylin_vectordb 由 KylinMem0Adapter 实现）
VectorStoreFactory.provider_to_class["kylin_vectordb"] = (
    "src.memory.kylin_mem0_adapter.KylinMem0Adapter"
)

# 麒麟千问 LLM 适配器（零 key，provider=sdk 时使用）
LlmFactory.register_provider("kylin_sdk", "src.memory.kylin_llm.KylinLLM")

# 统一 LLM 适配器（2026-09-10）：mem0 内部 LLM 也走 src/llm_client 的同一把 key
LlmFactory.register_provider("unified", "src.memory.unified_llm.UnifiedLLM")
