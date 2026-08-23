# -*- coding: utf-8 -*-
"""知识库 RAG（移植自 QiLinOS/src/rag/ps_rag.py，适配本项目）。

差异点：
- LLM：使用本项目的 llm_client（麒麟 SDK 优先，可配置切 DeepSeek/OpenAI 兼容 API）
- Embedding：本项目 KylinEmbedder（麒麟 SDK GTE-base 768 维）
- 存储：MilvusLite 向量库（~/.nex-agent/rag_vectordb.db）+ NetworkX 图 + JSON KV
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from typing import Any

import numpy as np

logger = logging.getLogger("rag")

WORKING_DIR = os.path.expanduser("~/.nex-agent/rag_storage")
VECTOR_DB = os.path.expanduser("~/.nex-agent/rag_vectordb.db")


# ---------- Embedding（麒麟 SDK）----------
def get_kylin_embedder():
    from src.memory.kylin_embedder import KylinEmbedder
    return KylinEmbedder()


async def embedding_func(texts: list[str]) -> np.ndarray:
    """异步 Embedding — 三级降级链（融入 QiLinOS ONNX 直载系统模型）:
        ① 麒麟 SDK（GTE-base 768 维）
        ② ONNX Runtime 直载系统模型（kylin-ai-abstract-models，SDK 不可用时）
        ③ 零向量兜底（保证流程不中断）
    """
    loop = asyncio.get_event_loop()
    # ① SDK
    try:
        arr = await loop.run_in_executor(None, lambda: np.asarray(
            get_kylin_embedder().embed_batch([t[:500] for t in texts])))
        return np.asarray(arr, dtype=np.float32)
    except Exception as e:
        logger.warning("SDK 嵌入失败，尝试 ONNX 直载系统模型: %s", e)
    # ② ONNX 直载系统模型（零新增依赖，服务器预装 kylin-ai-abstract-models）
    try:
        from src.memory.embedding_onnx import kylin_onnx_embedding_func
        arr = await kylin_onnx_embedding_func([t[:500] for t in texts])
        return np.asarray(arr, dtype=np.float32)
    except Exception as e2:
        logger.error("ONNX 嵌入失败: %s", e2)
    # ③ 零向量兜底
    return np.zeros((len(texts), 768), dtype=np.float32)


# ---------- LLM（复用本项目 llm_client）----------
async def llm_model_func(
    prompt,
    system_prompt=None,
    history_messages=None,
    keyword_extraction=False,
    **kwargs,
) -> str:
    """异步 LLM：麒麟 SDK 或配置的 API（DeepSeek 等）。"""
    from src import llm_client
    full = ""
    if system_prompt:
        full += system_prompt + "\n"
    if history_messages:
        for h in history_messages or []:
            full += f"{h.get('role', 'user')}: {h.get('content', '')}\n"
    full += prompt
    loop = asyncio.get_event_loop()
    try:
        return await loop.run_in_executor(None, lambda: llm_client.generate(full))
    except Exception as e:
        logger.error("LLM 失败: %s", e)
        return f"（RAG 生成失败: {e}）"


# ---------- LightRAG 初始化 ----------
_rag_instance = None
_rag_lock = asyncio.Lock()


async def initialize_rag() -> Any:
    """初始化 LightRAG（MilvusLite 向量库 + NetworkX 图 + JSON KV）。"""
    os.makedirs(WORKING_DIR, exist_ok=True)
    os.environ["MILVUS_URI"] = "file://" + VECTOR_DB  # MilvusLite 本地库需 file:// 前缀
    os.environ["MILVUS_DB_NAME"] = "rag"  # MilvusVectorDBStorage 要求该变量
    from lightrag import LightRAG, QueryParam
    from lightrag.utils import EmbeddingFunc
    rag = LightRAG(
        working_dir=WORKING_DIR,
        llm_model_func=llm_model_func,
        embedding_func=EmbeddingFunc(
            embedding_dim=768,
            func=embedding_func,
        ),
        vector_storage="FaissVectorDBStorage",
        graph_storage="NetworkXStorage",
        kv_storage="JsonKVStorage",
        doc_status_storage="JsonDocStatusStorage",
    )
    return rag


# ---------- RAG 引擎 ----------
class RAGEngine:
    """知识库引擎：文档入库 + 混合检索问答（单例惰性初始化）。"""

    def __init__(self):
        self.rag = None
        self.init = False
        self.registry_file = os.path.join(WORKING_DIR, "document_registry.json")
        self.docs = self._load_registry()

    def _load_registry(self) -> dict:
        try:
            with open(self.registry_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def _save_registry(self) -> None:
        try:
            os.makedirs(WORKING_DIR, exist_ok=True)
            with open(self.registry_file, "w", encoding="utf-8") as f:
                json.dump(self.docs, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error("注册表保存失败: %s", e)

    async def ensure_init(self) -> None:
        if not self.init:
            async with _rag_lock:
                if not self.init:
                    self.rag = await initialize_rag()
                    # LightRAG 1.x: 初始化存储 + 处理管道（缺一不可）
                    from lightrag.kg.shared_storage import initialize_pipeline_status
                    await self.rag.initialize_storages()
                    await initialize_pipeline_status()
                    self.init = True

    async def insert_document(self, content: str, path: str = "") -> dict:
        """文档入库（可重复插入，按内容去重）。"""
        await self.ensure_init()
        doc_id = str(hash(content))
        if doc_id in self.docs:
            return {"status": "duplicate", "id": doc_id}
        await self.rag.ainsert(content)
        self.docs[doc_id] = {"path": path, "ts": time.time(), "len": len(content)}
        self._save_registry()
        return {"status": "ok", "id": doc_id, "docs_total": len(self.docs)}

    async def insert_file(self, path: str) -> dict:
        """从文件读取并入库。"""
        full = os.path.expanduser(path)
        if not os.path.isfile(full):
            return {"status": "error", "error": f"文件不存在: {full}"}
        try:
            with open(full, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
        except Exception as e:
            return {"status": "error", "error": f"读取失败: {e}"}
        if not content.strip():
            return {"status": "error", "error": "文件为空"}
        return await self.insert_document(content, path=full)

    async def query(self, question: str, mode: str = "hybrid") -> str:
        """混合检索问答。mode: hybrid / local / global / naive / mix。"""
        await self.ensure_init()
        from lightrag import QueryParam
        param = QueryParam(mode=mode, top_k=10)
        loop = asyncio.get_event_loop()
        try:
            return await loop.run_in_executor(
                None, lambda: asyncio.run(self.rag.aquery(question, param=param)))
        except Exception as e:
            logger.error("RAG 查询失败: %s", e)
            return f"（知识库查询失败: {e}）"

    async def query_user_info(self, user_identifier: str, mode: str = "hybrid") -> dict:
        """按用户标识从知识库查询用户画像（融入 QiLinOS query_user_info）。

        构造「关于 X 的个人信息/工作/教育/联系方式」查询 → LightRAG 检索。
        """
        await self.ensure_init()
        from lightrag import QueryParam
        query = f"关于{user_identifier}的个人信息、工作信息、教育背景、联系方式等详细信息是什么？"
        loop = asyncio.get_event_loop()
        try:
            result = await loop.run_in_executor(
                None, lambda: asyncio.run(self.rag.aquery(
                    query, param=QueryParam(mode=mode, top_k=10, response_type="中文回答"))))
            text = str(result).strip()
            if text:
                return {"success": True, "result": text, "query": query, "mode": mode}
            return {"success": False, "error": "查询返回空结果（知识库中可能没有该用户的信息）"}
        except Exception as e:
            logger.error("用户画像查询失败: %s", e)
            return {"success": False, "error": f"用户画像查询失败: {e}"}

    async def extract_user_info(self, document_content: str | None = None) -> dict:
        """从知识库提取用户相关信息（融入 QiLinOS extract_user_info_from_document）。

        若提供 document_content 且未入库，先入库再提取；否则从现有知识库提取。
        四类查询：个人信息 / 工作教育 / 组织机构 / 重要日期事件。
        """
        if document_content and document_content.strip():
            r = await self.insert_document(document_content)
            if r.get("status") not in ("ok", "duplicate"):
                return {"success": False, "error": f"文档入库失败: {r.get('error')}"}
        await self.ensure_init()
        from lightrag import QueryParam
        user_queries = [
            "文档中提到的个人信息有哪些？包括姓名、联系方式、地址等",
            "文档中的工作和教育信息是什么？",
            "文档中涉及的组织机构有哪些？",
            "文档中的重要日期和事件有哪些？",
        ]
        extracted: dict = {}
        loop = asyncio.get_event_loop()
        for query in user_queries:
            try:
                result = await loop.run_in_executor(
                    None, lambda q=query: asyncio.run(self.rag.aquery(
                        q, param=QueryParam(mode="local", top_k=5, response_type="中文回答"))))
                text = str(result).strip()
                if text:
                    key = query.split("？")[0].replace("文档中", "").replace("的", "").strip() or "信息"
                    extracted[key] = text[:300]
            except Exception as e:
                logger.warning("提取查询失败 %s: %s", query[:12], e)
        if not extracted:
            return {"success": False, "error": "未能从知识库提取到用户信息（库中可能没有相关文档）"}
        return {"success": True, "extracted_info": extracted}

    def stats(self) -> dict:
        return {"docs": len(self.docs), "working_dir": WORKING_DIR}


_engine: "RAGEngine | None" = None


def get_engine() -> "RAGEngine":
    global _engine
    if _engine is None:
        _engine = RAGEngine()
    return _engine


def reset_engine() -> None:
    global _engine
    _engine = None
