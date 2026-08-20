# -*- coding: utf-8 -*-
"""知识库工具（LightRAG + 麒麟 embedding + llm_client）。

用法:
  kb action=insert content=文本内容            # 文本入库
  kb action=insert path=~/文档/xx.txt          # 文件入库
  kb action=query question=问题               # 知识库问答
  kb action=stats                              # 统计
"""
from __future__ import annotations

import asyncio

from .base import BaseTool, RiskLevel, ToolResult


class KnowledgeBaseTool(BaseTool):
    """知识库：文档入库 + 检索问答（LightRAG）。"""
    name = "kb"
    description = ("知识库（RAG）。action=insert: 文档入库(content=文本 或 path=文件路径)；"
                   "action=query: 知识库问答(question=问题)；action=stats: 统计。"
                   "例: kb action=insert path=~/文档/手册.txt；kb action=query question=手册里写了什么")
    risk = RiskLevel.LOW
    timeout_s = 180.0

    def execute(self, **kwargs) -> ToolResult:
        from src.rag_ps import RAGEngine, get_engine
        action = (kwargs.get("action") or "").strip().lower()
        engine = get_engine()

        try:
            if action in ("insert", "add", "入库", "学习"):
                content = (kwargs.get("content") or kwargs.get("text") or "").strip()
                path = (kwargs.get("path") or "").strip()
                if path:
                    r = asyncio.run(engine.insert_file(path))
                elif content:
                    r = asyncio.run(engine.insert_document(content))
                else:
                    return self._fail("需要 content（文本）或 path（文件路径）")
                if r.get("status") == "ok":
                    return self._ok(f"知识库入库成功（第 {r['docs_total']} 篇文档）")
                if r.get("status") == "duplicate":
                    return self._ok("该文档已在知识库中（跳过重复入库）")
                return self._fail(f"入库失败: {r.get('error')}")

            if action in ("query", "ask", "查询", "问答"):
                question = (kwargs.get("question") or kwargs.get("q")
                            or kwargs.get("query") or "").strip()
                if not question:
                    return self._fail("需要 question 参数")
                answer = asyncio.run(engine.query(question))
                if answer.startswith("（知识库查询失败"):
                    return self._fail(answer)
                return self._ok(f"知识库回答:\n{answer}")

            if action in ("stats", "统计"):
                return self._ok(f"知识库统计: {engine.stats()}")

            return self._fail(f"未知操作: '{action}'。可用: insert, query, stats")
        except Exception as e:
            return self._fail(f"知识库操作失败: {e}")


def register_kb_tools(registry=None):
    """注册知识库工具。"""
    if registry is None:
        from .base import get_registry
        registry = get_registry()
    registry.register(KnowledgeBaseTool())
    return registry
