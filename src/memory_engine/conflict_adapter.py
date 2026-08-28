"""strict 冲突分类能力适配现有四层库（C 方案，2026-08-28）。

把 strict/conflict.py 的 HierarchicalConflictClassifier + 三个 resolver
应用于现有 MemoryRecord 数据（memory_engine.db / 任意 MemoryEngineStore）：

  1. 槽位归一化（normalize_slot）：规则槽位（personal:location / preference:sport …）
     优先——「住在深圳」与「住在杭州」归入同槽位，冲突才可检测；
  2. 冲突分类 + 裁决（scan_conflicts）：同槽位多值 → classify → resolver 定 winner；
  3. 读侧仲裁（losers_map）：检索时 loser 文本 → 不注入上下文（矛盾旧值失效）。

只复用 strict 的分类/裁决逻辑（不实例化 StrictMemoryEngine、不碰 strict 存储）。
"""
from __future__ import annotations

from dataclasses import replace
from typing import Any, Mapping

from .extractors import _slot_for_fact
from .store import MemoryEngineStore
from .strict.contracts import (
    LifecycleStatus,
    StrictConflictGroup,
    StrictMemory,
)
from .strict.conflict import (
    ConditionPartitionResolver,
    ExplicitTimeRecentWindowDynamicResolver,
    HierarchicalConflictClassifier,
    SourceVersionCountStaticResolver,
)

_STATUS_MAP = {
    "candidate": LifecycleStatus.CANDIDATE,
    "stable": LifecycleStatus.STABLE,
    "historical": LifecycleStatus.HISTORICAL,
    "archive": LifecycleStatus.ARCHIVE,
    "recover": LifecycleStatus.RECOVER,
    "deleted": LifecycleStatus.DELETED,
    "blocked": LifecycleStatus.BLOCKED,
}


def normalize_slot(memory) -> str:
    """槽位归一化：规则槽位优先（语义归类），否则保留原 slot。"""
    try:
        slot = _slot_for_fact(memory.semantic_value)
    except Exception:
        slot = ""
    if slot and not slot.startswith("fact:"):
        return slot
    # 规则未命中：保留原 slot（旧记忆可能已是规则槽位或内容 hash）
    return memory.slot_key or slot


def _to_strict(memory) -> StrictMemory:
    """MemoryRecord → StrictMemory（只填分类/裁决所需字段，缺失给安全默认值）。"""
    status = _STATUS_MAP.get(str(getattr(memory, "status", "")), LifecycleStatus.CANDIDATE)
    provenance = dict(getattr(memory, "provenance", None) or {})
    provenance.setdefault("directness", "explicit_user")
    stats = dict(getattr(memory, "statistics", None) or {})
    return StrictMemory(
        memory_id=memory.memory_id,
        user_id=memory.user_id,
        memory_family=str(getattr(memory, "memory_family", "") or "knowledge"),
        candidate_kind=str(getattr(memory, "memory_category", "") or "fact"),
        slot_key=normalize_slot(memory),
        semantic_value=memory.semantic_value,
        condition=dict(getattr(memory, "condition", None) or {}),
        scope=dict(getattr(memory, "scope", None) or {}),
        cardinality="single",
        status=status,
        evidence_ids=tuple(getattr(memory, "evidence_ids", None) or ()),
        support_unit_ids=tuple(stats.get("support_unit_ids") or ()),
        oppose_unit_ids=(),
        applicable_unit_ids=(),
        valid_from=str(getattr(memory, "created_at", "") or ""),
        valid_to="",
        predecessor_memory_ids=(),
        successor_memory_ids=(),
        conflict_group_ids=(),
        confidence=dict(getattr(memory, "confidence", None) or {}),
        stability=dict(getattr(memory, "stability", None) or {}),
        provenance=provenance,
        version=int(getattr(memory, "version", 1) or 1),
        created_at=str(getattr(memory, "created_at", "") or ""),
        updated_at=str(getattr(memory, "updated_at", "") or ""),
    )


# 可冲突的【单值属性】槽位白名单（多值偏好不在此列，如运动/饮食可并存）
_SINGLE_VALUE_SLOTS = {
    "personal:location", "personal:pet", "personal:occupation",
    "preference:currency", "preference:response_style",
    "safety:external_send_confirmation", "preference:save_location",
    "preference:document_style", "preference:chart_type",
    "preference:development_workflow",
}


def scan_conflicts(
    store: MemoryEngineStore | None = None,
    user_id: str = "nex_user",
) -> list[StrictConflictGroup]:
    """扫描四层库 active 记忆 → strict 冲突分类 + 裁决，返回带 winner 的冲突组。

    只读操作，不写库。记忆量小（<200 条）时毫秒级。
    兜底裁决：STATIC 平局（strict resolver 判 unresolved）时，单值槽位按
    「最新表述优先」定 winner（用户最新表达代表当前事实，如住址更新）。
    """
    store = store or MemoryEngineStore()
    memories = [
        m for m in (store.list_memories(user_id) or [])
        if str(getattr(m, "status", "") or "") not in ("deleted", "blocked")
    ]
    if len(memories) < 2:
        return []
    strict_memories = [_to_strict(m) for m in memories]
    by_id = {m.memory_id: m for m in strict_memories}
    groups = HierarchicalConflictClassifier().classify(strict_memories)
    resolved: list[StrictConflictGroup] = []
    for group in groups:
        for resolver in (
            SourceVersionCountStaticResolver(),
            ExplicitTimeRecentWindowDynamicResolver(),
            ConditionPartitionResolver(),
        ):
            group = resolver.resolve(group, by_id)
            if group.status in ("resolved", "partitioned"):
                break
        if group.status == "unresolved" and group.slot_key in _SINGLE_VALUE_SLOTS:
            # 兜底：单值槽位静态平局 → 最新 valid_from 优先（更新换代语义）
            _members = [by_id[mid] for mid in group.memory_ids if mid in by_id]
            if _members:
                winner = max(_members, key=lambda m: (m.valid_from or "", m.memory_id))
                group = replace(
                    group,
                    winner_memory_id=winner.memory_id,
                    unresolved_reason="latest_expression_wins",
                    status="resolved",
                )
        resolved.append(group)
    return resolved


def slot_winners(
    store: MemoryEngineStore | None = None,
    user_id: str = "nex_user",
) -> dict[str, str]:
    """{单值槽位: winner 文本}：从已裁决冲突组提取。

    槽位级仲裁用——检索文本若属于某单值槽位且不是 winner 文本，
    一律视为矛盾旧值剔除（覆盖变体文本：如「用户小张住在杭州，使用
    银河麒麟操作系统」vs winner「用户住在深圳」，文本匹配不上但槽位相同）。
    """
    store = store or MemoryEngineStore()
    memories = {m.memory_id: m for m in (store.list_memories(user_id) or [])}
    result: dict[str, str] = {}
    for group in scan_conflicts(store, user_id):
        if group.status != "resolved" or not group.winner_memory_id:
            continue
        if group.slot_key not in _SINGLE_VALUE_SLOTS:
            continue
        winner = memories.get(group.winner_memory_id)
        if winner is not None:
            result[group.slot_key] = str(winner.semantic_value)
    return result


def slot_for_text(text: str) -> str | None:
    """文本 → 单值规则槽位（非单值槽位返回 None）。"""
    text = (text or "").strip()
    if not text:
        return None
    try:
        slot = _slot_for_fact(text)
    except Exception:
        return None
    return slot if slot in _SINGLE_VALUE_SLOTS else None


def loser_for_text(
    text: str,
    store: MemoryEngineStore | None = None,
    user_id: str = "nex_user",
) -> dict[str, Any] | None:
    """模糊匹配：检索文本是否命中某个 loser（归一化后相等/互相包含）。

    mem0 提取文本常是四层语义值的扩展/插入修饰（如「用户目前住在杭州，
    该信息更新于…」vs「用户住在杭州」）→ 精确匹配会漏；
    用归一化（去时间戳/修饰词）后的相等或互相包含判定。
    """
    text = (text or "").strip()
    if not text:
        return None
    from .store import _normalize_mem_text
    norm = _normalize_mem_text(text)
    if not norm:
        return None
    for loser_text, info in losers_map(store, user_id).items():
        if not loser_text:
            continue
        l_norm = _normalize_mem_text(loser_text)
        if l_norm and (l_norm == norm or l_norm in norm or norm in l_norm):
            return info
    return None


def losers_map(
    store: MemoryEngineStore | None = None,
    user_id: str = "nex_user",
) -> dict[str, dict[str, Any]]:
    """一次扫描全部冲突 loser：{loser_text: {winner_text, group_id, conflict_type}}。

    读侧仲裁用：检索结果命中 loser_text → 不注入上下文。
    """
    store = store or MemoryEngineStore()
    memories = list(store.list_memories(user_id) or [])
    by_id = {m.memory_id: m for m in memories}
    result: dict[str, dict[str, Any]] = {}
    for group in scan_conflicts(store, user_id):
        if group.status != "resolved" or not group.winner_memory_id:
            continue
        winner = by_id.get(group.winner_memory_id)
        if winner is None:
            continue
        for mid in group.memory_ids:
            if mid == group.winner_memory_id:
                continue
            loser = by_id.get(mid)
            if loser is None:
                continue
            result[str(loser.semantic_value)] = {
                "winner_text": str(winner.semantic_value),
                "group_id": str(group.conflict_group_id),
                "conflict_type": str(getattr(group.conflict_type, "value", "")),
            }
    return result
