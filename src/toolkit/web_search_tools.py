"""网页搜索工具（Web Search）— 百度/Bing 双引擎 + 网页正文抓取（trafilatura）。

融入自 QiLinOS src/tools/web_search.py + search_bing.py（2026-08-24 适配）：
- 新增 Bing 搜索（search_bing.py 的 parse_html 逻辑）
- 新增网页正文抓取（trafilatura，QiLinOS web_search.collect_url 思路）
- 保留 dev1 原百度搜索 WebSearchTool（兼容已有注册名）
"""
from __future__ import annotations

import re

from .base import BaseTool, ToolResult, ToolStatus, RiskLevel

_ABSTRACT_MAX = 300


# ---------------------------------------------------------------- 百度搜索
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


# ---------------------------------------------------------------- Bing 搜索
_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Content-Type": "application/x-www-form-urlencoded",
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/68.0.3440.106 Safari/537.36"),
    "Referer": "https://www.bing.com/",
    "Accept-Encoding": "gzip, deflate",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}
_bing_host = "https://www.bing.com"
_bing_search_url = "https://www.bing.com/search?q="


def _parse_bing_page(url: str, rank_start: int = 0):
    """解析必应搜索结果页。返回 (结果列表, 下一页url)。"""
    import requests
    from bs4 import BeautifulSoup
    try:
        res = requests.get(url=url, headers=_HEADERS, timeout=15)
        res.encoding = "utf-8"
        root = BeautifulSoup(res.text, "lxml")
        list_data = []
        search_results = root.find("ol", id="b_results")
        if not search_results:
            return list_data, None
        for result in search_results.find_all("li", class_="b_algo"):
            title = url_ = abstract = ""
            try:
                title_elem = result.find("h2")
                if title_elem and title_elem.a:
                    title = title_elem.a.get_text(strip=True)
                    url_ = title_elem.a.get("href", "").strip()
                abstract_elem = result.find("div", class_="b_caption")
                if abstract_elem:
                    p_elem = abstract_elem.find("p")
                    abstract = p_elem.get_text(strip=True) if p_elem else abstract_elem.get_text(strip=True)
                if not abstract:
                    summary_elem = result.find("div", class_="b_snippet")
                    if summary_elem:
                        abstract = summary_elem.get_text(strip=True)
                if abstract and len(abstract) > _ABSTRACT_MAX:
                    abstract = abstract[:_ABSTRACT_MAX]
                if title:
                    rank_start += 1
                    list_data.append({"title": title, "abstract": abstract, "url": url_, "rank": rank_start})
            except Exception:
                continue
        next_btn = root.find("a", class_="sb_pagN") or root.find("a", title="Next page")
        next_url = (_bing_host + next_btn["href"]) if next_btn else None
        return list_data, next_url
    except Exception as e:
        print(f"[web_search] bing 解析失败: {e}", flush=True)
        return None, None


def _search_bing(query: str, num: int = 5) -> list[dict]:
    """Bing 搜索。返回 [{title, abstract, url}]；失败返回空。"""
    if not query:
        return []
    out, page = [], 1
    next_url = _bing_search_url + query
    while len(out) < num and next_url:
        data, next_url = _parse_bing_page(next_url, rank_start=len(out))
        if data:
            out += data
        if not next_url:
            break
        page += 1
        if page > 5:  # 安全上限
            break
    return out[:num]


# ---------------------------------------------------------------- 网页正文抓取
def _fetch_page_content(url: str, max_chars: int = 3000) -> str:
    """抓取网页正文（trafilatura）。失败返回空串。"""
    try:
        import trafilatura
        downloaded = trafilatura.fetch_url(url)
        if not downloaded:
            return ""
        text = trafilatura.extract(downloaded)
        if not text:
            return ""
        return text.strip()[:max_chars]
    except Exception as e:
        print(f"[web_search] 正文抓取失败: {e}", flush=True)
        return ""


# ---------------------------------------------------------------- 工具定义
class WebSearchTool(BaseTool):
    """网页搜索。参数 query=搜索关键词（必填），num=返回条数（默认5，最多10）。"""
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
            results = _search_bing(query, num)
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


class WebFetchTool(BaseTool):
    """网页正文抓取。参数 url=目标网址（必填），max_chars=最大字符数（默认3000）。"""
    name = "web_fetch"
    description = ("抓取网页正文内容。参数 url=目标网址（必填），max_chars=返回最大字符数（默认3000）。"
                   "适合：网页标题/摘要不够时获取完整正文。")
    risk = RiskLevel.LOW
    requires_approval = False
    timeout_s = 30.0

    def execute(self, **kwargs) -> ToolResult:
        url = str(kwargs.get("url") or "").strip()
        if not url:
            return self._fail("缺少 url 参数")
        if not re.match(r"^https?://", url):
            url = "https://" + url
        try:
            max_chars = int(kwargs.get("max_chars") or 3000)
        except Exception:
            max_chars = 3000
        max_chars = max(500, min(max_chars, 8000))

        text = _fetch_page_content(url, max_chars)
        if not text:
            return self._ok(f"无法抓取「{url}」的正文内容（可能被反爬或页面无正文）")
        return self._ok(f"「{url}」正文内容（{len(text)} 字）：\n\n{text}")

    def verify(self, **kwargs) -> bool:
        return True


def register_web_search_tools(registry=None):
    from .base import get_registry
    reg = registry or get_registry()
    reg.register(WebSearchTool())
    reg.register(WebFetchTool())
    return reg
