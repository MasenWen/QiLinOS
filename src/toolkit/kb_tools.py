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
    description = ("知识库。provider=kylin(默认,麒麟知识库SDK) 或 lightrag(旧)。"
                   "麒麟库: action=create(name=库名)/delete(name=库名)/insert(content=文本 或 path=文件)/"
                   "query(question=问题, name=库名, 默认default)/stats；"
                   "例: kb action=insert content=手册内容；kb action=query question=手册里写了什么")
    risk = RiskLevel.LOW
    timeout_s = 180.0

    def _kylin_kb(self, action: str, kwargs: dict) -> ToolResult:
        """麒麟知识库 SDK 操作（服务需注册到 D-Bus，SSH 无桌面会话时不可用）。"""
        try:
            from src.rag_kykb import get_kb, KnowledgeBaseUnavailable
            kb = get_kb()
        except ImportError as e:
            return self._fail(f"麒麟知识库模块缺失: {e}")
        name = (kwargs.get("name") or kwargs.get("kb_name") or "default").strip()
        try:
            if action in ("create", "新建", "建库"):
                r = kb.create_knowledge_base(name)
                return self._ok(f"知识库已创建: {name}（{r}）")
            if action in ("delete", "删除", "删库"):
                r = kb.delete_knowledge_base(name)
                return self._ok(f"知识库已删除: {name}（{r}）")
            if action in ("insert", "add", "入库", "学习"):
                path = (kwargs.get("path") or "").strip()
                content = (kwargs.get("content") or kwargs.get("text") or "").strip()
                if path:
                    import os as _os
                    if not _os.path.isfile(_os.path.expanduser(path)):
                        return self._fail(f"文件不存在: {path}")
                    r = kb.add_text_files(name, _os.path.expanduser(path))
                    return self._ok(f"已入库到知识库「{name}」: {r}")
                if content:
                    r = kb.add_text_content(name, content)
                    return self._ok(f"已入库到知识库「{name}」: {r}")
                return self._fail("需要 content（文本）或 path（文件路径）")
            if action in ("query", "ask", "查询", "问答"):
                question = (kwargs.get("question") or kwargs.get("q")
                            or kwargs.get("query") or "").strip()
                if not question:
                    return self._fail("需要 question 参数")
                top_k = int(kwargs.get("top_k") or 5)
                r = kb.similarity_search(name, question, top_k=top_k)
                text = str(r)
                if len(text) > 2000:
                    text = text[:2000] + "..."
                return self._ok(f"知识库「{name}」检索结果:\n{text}")
            if action in ("stats", "统计"):
                return self._ok(f"麒麟知识库（服务:{kb.available()}，库名:{name}）")
            return self._fail(f"未知操作: '{action}'。麒麟库可用: create, delete, insert, query, stats")
        except KnowledgeBaseUnavailable as e:
            return self._fail(f"麒麟知识库服务不可用: {e}")
        except Exception as e:
            return self._fail(f"麒麟知识库操作失败: {e}")

    def execute(self, **kwargs) -> ToolResult:
        action = (kwargs.get("action") or "").strip().lower()
        provider = (kwargs.get("provider") or "kylin").strip().lower()

        # ---- 麒麟知识库 SDK（默认，替代 LightRAG）----
        if provider in ("kylin", "kykb", "麒麟"):
            return self._kylin_kb(action, kwargs)

        # ---- LightRAG（旧，provider=lightrag 显式使用）----
        from src.rag_ps import RAGEngine, get_engine
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
