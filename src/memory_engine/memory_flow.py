"""记忆流转（指令「记忆流转-重要」：短期 ↔ 中期 ↔ 长期数据流转）

MemoryFlow 编排三档记忆流转：
- 短 → 中（promote）：短期上下文溢出时，把关键信息（偏好/配置/流程）提升到中期
- 中 → 短（demote）：按当前查询检索相关中期记忆，注入短期上下文
- 中 → 长（consolidate）：时间老化/容量触发，中期归档到长期
"""
from __future__ import annotations

import io
import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Iterable, Mapping

# 重要性关键词（提升到中期的信号）
_IMPORTANT_MARKERS = ("偏好", "喜欢", "习惯", "默认", "配置", "流程", "模板", "每次", "以后", "prefer", "always")

SHORT_CAPACITY_DEFAULT = 8  # 短期（上下文窗口）容量


@dataclass
class FlowItem:
    content: str
    source: str = "short"       # short | midterm | longterm
    session_id: str = ""
    created_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    importance: float = 0.0

    def to_dict(self) -> dict:
        return {"content": self.content, "source": self.source,
                "session_id": self.session_id, "created_at": self.created_at,
                "importance": self.importance}


def default_importance(content: str) -> float:
    """基于关键词的重要性评分（0~1）。"""
    text = (content or "").lower()
    hits = sum(1 for kw in _IMPORTANT_MARKERS if kw in text)
    if hits >= 3:
        return 0.9
    if hits == 2:
        return 0.7
    if hits == 1:
        return 0.5
    return 0.2


class MemoryFlow:
    """三档记忆流转编排。

    短期：当前会话上下文列表（容量受限）
    中期：按 session 分组的过渡记忆
    长期：持久化沉淀（由 consolidate 归档）
    """

    def __init__(
        self,
        short_capacity: int = SHORT_CAPACITY_DEFAULT,
        importance_fn: Callable[[str], float] = default_importance,
        persist_path: str | None = None,
    ):
        self.short_capacity = short_capacity
        self.importance_fn = importance_fn
        self._short: list[FlowItem] = []          # 短期（当前上下文）
        self._midterm: dict[str, list[FlowItem]] = {}  # session_id -> 中期记忆
        self._longterm: list[FlowItem] = []       # 长期
        self._flow_log: list[str] = []            # 流转审计
        self.persist_path = persist_path or os.path.expanduser(
            "~/.nex-agent/memory_flow.json")
        self.load()  # 启动恢复

    # ---- 持久化（短期/中期/长期 → JSON）----
    def save(self) -> None:
        try:
            os.makedirs(os.path.dirname(self.persist_path), exist_ok=True)
            tmp = self.persist_path + ".tmp"
            with io.open(tmp, "w", encoding="utf-8") as f:
                json.dump({
                    "short": [it.to_dict() for it in self._short],
                    "midterm": {k: [it.to_dict() for it in v]
                                for k, v in self._midterm.items()},
                    "longterm": [it.to_dict() for it in self._longterm],
                }, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.persist_path)
        except OSError:
            pass

    def load(self) -> None:
        try:
            with io.open(self.persist_path, encoding="utf-8") as f:
                data = json.load(f)
            self._short = [FlowItem(**it) for it in data.get("short", [])]
            self._midterm = {
                k: [FlowItem(**it) for it in v]
                for k, v in data.get("midterm", {}).items()
            }
            self._longterm = [FlowItem(**it) for it in data.get("longterm", [])]
        except (OSError, ValueError, TypeError):
            pass

    # ---- 短期：写入 + 溢出检测 ----
    def add_short(self, content: str, session_id: str = "") -> list[FlowItem]:
        """写入短期上下文。若超出容量，返回需提升的项（由调用方决定 promote）。"""
        item = FlowItem(content=content, source="short", session_id=session_id,
                        importance=self.importance_fn(content))
        self._short.append(item)
        overflow: list[FlowItem] = []
        if len(self._short) > self.short_capacity:
            # 溢出：按重要性【降序】取容量外的项返回（重要项也参与 promote 分流）
            # 修复前按升序取"最不重要"的作 overflow → promote(>=0.45) 永远不通过 → 流转中断
            self._short.sort(key=lambda x: x.importance, reverse=True)
            overflow = self._short[self.short_capacity:]
            self._short = self._short[: self.short_capacity]
        return overflow

    # ---- 短 → 中：提升 ----
    def promote(self, session_id: str, items: Iterable[FlowItem] | None = None) -> list[str]:
        """把短期项提升到中期（默认提升溢出项或显式指定项）。"""
        targets = list(items) if items is not None else self._short
        promoted: list[str] = []
        for it in targets:
            if it.importance >= 0.45:  # 重要信息才提升
                it.source = "midterm"
                it.session_id = session_id
                self._midterm.setdefault(session_id, []).append(it)
                promoted.append(it.content[:40])
        self._flow_log.append(f"promote->midterm({session_id}): {len(promoted)} 项")
        self.save()
        return promoted

    # ---- 中 → 短：按查询注入 ----
    def demote(self, session_id: str, query: str, top_k: int = 3) -> list[FlowItem]:
        """按查询关键词检索中期记忆，注入短期上下文（中文友好：连续字块/英文词切分）。"""
        import re as _re

        def _blocks(s):
            return [b for b in _re.findall(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]+", (s or "").lower()) if len(b) > 1]

        def _overlap(a, b):
            # 2-gram 交叠（中文/英文通用）
            ga = {a[i:i + 2] for i in range(max(0, len(a) - 1))}
            gb = {b[i:i + 2] for i in range(max(0, len(b) - 1))}
            return len(ga & gb)

        q_blocks = _blocks(query)
        scored: list[tuple[float, FlowItem]] = []
        for it in self._midterm.get(session_id, []):
            m_blocks = _blocks(it.content)
            score = sum(_overlap(q, m) for q in q_blocks for m in m_blocks)
            scored.append((score, it))
        scored.sort(key=lambda x: -x[0])
        hits = [it for s, it in scored if s > 0][:top_k]
        for it in hits:
            it.source = "short"
            if it not in self._short:
                self._short.append(it)
        self._flow_log.append(f"demote->short({session_id}): {len(hits)} 项")
        return hits

    # ---- 中 → 长：归档（时间老化/容量）----
    def consolidate(
        self,
        session_id: str,
        max_age_days: int = 30,
        capacity: int = 100,
        now: str | None = None,
    ) -> list[FlowItem]:
        """中期记忆归档到长期：超龄或超容量时触发。"""
        from datetime import datetime, timedelta
        ref = datetime.fromisoformat(now) if now else datetime.now()
        items = self._midterm.get(session_id, [])
        archived: list[FlowItem] = []
        keep: list[FlowItem] = []
        for it in items:
            try:
                age = (ref - datetime.fromisoformat(it.created_at)).days
            except Exception:
                age = 0
            if age >= max_age_days or len(items) > capacity:
                it.source = "longterm"
                it.session_id = ""
                self._longterm.append(it)
                archived.append(it)
            else:
                keep.append(it)
        self._midterm[session_id] = keep
        self._flow_log.append(f"consolidate->longterm({session_id}): {len(archived)} 项")
        self.save()
        return archived

    # ---- 查询 ----
    def short_context(self) -> list[str]:
        return [it.content for it in self._short]

    def midterm_count(self, session_id: str | None = None) -> int:
        if session_id is None:
            return sum(len(v) for v in self._midterm.values())
        return len(self._midterm.get(session_id, []))

    def longterm_count(self) -> int:
        return len(self._longterm)

    def flow_log(self) -> list[str]:
        return list(self._flow_log)

    def reset(self) -> None:
        self._short.clear()
        self._midterm.clear()
        self._longterm.clear()
        self._flow_log.clear()
