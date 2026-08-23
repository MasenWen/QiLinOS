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
import threading

from .base import BaseTool, RiskLevel, ToolResult


def _run_async(coro) -> dict:
    """在独立线程执行 asyncio.run（避免 executor 的 running-loop 嵌套报错）。"""
    box: dict = {}
    def runner():
        try:
            box["v"] = asyncio.run(coro)
        except Exception as e:
            box["e"] = e
    t = threading.Thread(target=runner, daemon=True)
    t.start()
    t.join()
    if "e" in box:
        raise box["e"]
    return box["v"]


class KnowledgeBaseTool(BaseTool):
    """知识库：文档入库 + 检索问答（LightRAG）。"""
    name = "kb"
    description = ("知识库（RAG）。action=insert: 文档入库(content=文本 或 path=文件路径)；"
                   "action=query: 知识库问答(question=问题)；action=stats: 统计；"
                   "action=user_info: 按用户查询画像(user=用户标识)；"
                   "action=extract: 从文档提取用户信息(content=文本，可选先入库)。"
                   "例: kb action=insert path=~/文档/手册.txt；kb action=user_info user=小张")
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
                    r = _run_async(engine.insert_file(path))
                elif content:
                    r = _run_async(engine.insert_document(content))
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
                answer = _run_async(engine.query(question))
                if answer.startswith("（知识库查询失败"):
                    return self._fail(answer)
                return self._ok(f"知识库回答:\n{answer}")

            if action in ("stats", "统计"):
                return self._ok(f"知识库统计: {engine.stats()}")

            if action in ("user_info", "用户画像", "画像"):
                user = (kwargs.get("user") or kwargs.get("name") or "小张").strip()
                r = _run_async(engine.query_user_info(user))
                if r.get("success"):
                    return self._ok(f"用户画像（{user}）:\n{r['result']}")
                return self._fail(r.get("error", "查询失败"))

            if action in ("extract", "提取"):
                content = (kwargs.get("content") or kwargs.get("text") or "").strip()
                r = _run_async(engine.extract_user_info(content or None))
                if r.get("success"):
                    lines = [f"{k}: {v[:120]}" for k, v in r["extracted_info"].items()]
                    return self._ok("用户信息提取:\n" + "\n".join(lines))
                return self._fail(r.get("error", "提取失败"))

            return self._fail(f"未知操作: '{action}'。可用: insert, query, stats, user_info, extract")
        except Exception as e:
            return self._fail(f"知识库操作失败: {e}")


def register_kb_tools(registry=None):
    """注册知识库工具。"""
    if registry is None:
        from .base import get_registry
        registry = get_registry()
    registry.register(KnowledgeBaseTool())
    return registry
