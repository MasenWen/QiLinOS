import os
import asyncio
from lightrag import LightRAG, QueryParam
from lightrag.llm.openai import openai_embed
from lightrag.utils import setup_logger
from lightrag.kg.shared_storage import initialize_pipeline_status
from lightrag.utils import EmbeddingFunc
import numpy as np
from lightrag.llm.openai import openai_complete_if_cache, openai_embed

setup_logger("lightrag", level="INFO")

WORKING_DIR = "./rag_storage"
if not os.path.exists(WORKING_DIR):
    os.mkdir(WORKING_DIR)

async def llm_model_func(
    prompt, system_prompt=None, history_messages=[], keyword_extraction=False, **kwargs
) -> str:
    return await openai_complete_if_cache(
        "qwen3-max",  # 使用 Qwen3-Max 模型
        prompt,
        system_prompt=system_prompt,
        history_messages=history_messages,
        api_key=os.getenv("QWEN_API_KEY"),
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        **kwargs
    )

async def embedding_func(texts: list[str]) -> np.ndarray:
    return await openai_embed(
        texts,
        model="text-embedding-v3",  # 推荐使用 Qwen 的 text-embedding-v3 模型
        api_key=os.getenv("QWEN_API_KEY"),
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"
    )

async def initialize_rag():
    rag = LightRAG(
        working_dir=WORKING_DIR,
        llm_model_func=llm_model_func,
        embedding_func=EmbeddingFunc(
            embedding_dim=1024,  # text-embedding-v3 的维度是 3072
            func=embedding_func
        )
    )
    return rag

async def main():
    try:
        # Initialize RAG instance
        rag = await initialize_rag()
        
        # IMPORTANT: Both initialization calls are required!
        await rag.initialize_storages()  # Initialize storage backends  
        await initialize_pipeline_status()
        await rag.ainsert("姓名：李汉华、性别：男、学历：本科、名族：汉族、职业：软件工程师")

        # Perform hybrid search
        mode = "hybrid"
        print(
          await rag.aquery(
              "李汉华的职业是？",
              param=QueryParam(mode=mode)
          )
        )

    except Exception as e:
        print(f"An error occurred: {e}")
    finally:
        if rag:
            await rag.finalize_storages()

if __name__ == "__main__":
    asyncio.run(main())