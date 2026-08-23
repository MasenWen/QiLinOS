"""网页搜索工具（Web Search）— 基于 baidusearch，返回标题+摘要+链接。"""
from __future__ import annotations

import re

from .base import BaseTool, ToolResult, ToolStatus, RiskLevel


def _search_baidu(query: str, num: int = 5) -> list[dict]:
    """百度搜索。返回 [{title, abstract, url}]；失败返回空。"""
    try:
        from baidusearch.baidusearch import search
        results = search(query, num_results=num)
        out = []
        for r in results or []:
            if isinstance(r, dict):
                out.append({
                    "title": str(r.get("title") or r.get("name") or "").strip(),
                    "abstract": str(r.get("abstract") or r.get("abs") or "").strip(),
                    "url": str(r.get("url") or "").strip(),
                })
            elif isinstance(r, (list, tuple)) and len(r) >= 3:
                out.append({"title": str(r[0]), "abstract": str(r[1]), "url": str(r[2])})
        return out
    except Exception as e:
        print(f"[web_search] baidu 搜索失败: {e}", flush=True)
        return []


class WebSearchTool(BaseTool):
    """网页搜索。查询信息、资料、新闻等。"""
    name = "web_search"
    description = ("网页搜索。参数 query=搜索关键词（必填），num=返回条数（默认5，最多10）。"
                   "返回标题/摘要/链接列表。适合查询资料、新闻、教程、最新信息。")
    risk = RiskLevel.LOW
    requires_approval = False
    timeout_s = 30.0

    def execute(self, **kwargs) -> ToolResult:
        query = str(kwargs.get("query") or kwargs.get("q") or "").strip()
        if not query:
            return self._fail("缺少 query 参数")
        try:
            num = int(kwargs.get("num") or 5)
        except Exception:
            num = 5
        num = max(1, min(num, 10))

        results = _search_baidu(query, num)
        if not results:
            return self._ok(f"搜索「{query}」无结果或搜索服务不可用")

        lines = [f"「{query}」搜索结果（{len(results)} 条）：", ""]
        for i, r in enumerate(results, 1):
            title = r.get("title") or "(无标题)"
            url = r.get("url") or ""
            abstract = r.get("abstract") or ""
            lines.append(f"{i}. {title}")
            if url:
                lines.append(f"   🔗 {url}")
            if abstract:
                lines.append(f"   {abstract[:120]}")
            lines.append("")
        return self._ok("\n".join(lines).strip())

    def verify(self, **kwargs) -> bool:
        return True


def register_web_search_tools(registry=None):
    from .base import get_registry
    reg = registry or get_registry()
    reg.register(WebSearchTool())
    return reg
