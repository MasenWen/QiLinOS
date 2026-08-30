# -*- coding: utf-8 -*-
"""后台 LLM 槽位判断（2026-08-30，替代正则规则的语义精修）。

写入记忆时规则 _slot_for_fact 先快速定槽（同步零延迟）；本模块在后台
用 LLM 判断更准确的槽位并回写 store，供冲突检测（scan_conflicts）复用。

设计要点：
- 只修正【可冲突单值槽位】与【多值偏好】的归类，不改变记忆内容
- LLM 失败/超时静默返回 None，保留规则槽位（不阻塞、不降级）
- 每记忆只判断一次（已修正过的跳过），线程池限并发
"""
from __future__ import annotations

import json
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

logger = logging.getLogger("memory_engine.slot_llm")

# 槽位枚举（供 LLM 选择；单值槽位可冲突，多值/事实不冲突）
_SLOT_SCHEMA = {
    "personal:location": "居住地或工作地（单值属性：住在深圳、在杭州工作、搬到上海）",
    "personal:occupation": "职业或工作（单值属性：我是老师、从事设计、在银行上班）",
    "personal:pet": "宠物（单值属性：养了只猫、宠物叫旺财）",
    "preference:response_style": "回复风格偏好（单值：偏好简洁/详细回复）",
    "preference:currency": "币种偏好（单值：偏好美元/人民币）",
    "preference:save_location": "保存位置偏好（单值：默认保存到桌面）",
    "preference:document_style": "文档格式偏好（单值：标题字体字号）",
    "preference:chart_type": "图表偏好（单值：折线图/柱状图）",
    "preference:development_workflow": "开发工作流偏好（单值：用vscode/终端）",
    "preference:other": "其他多值偏好（喜欢打篮球、爱喝茶，可并存不冲突）",
    "fact": "其他事实（无冲突语义的陈述）",
}

_PROMPT_TMPL = (
    "你是记忆槽位分类器。判断下面这条记忆属于哪个槽位。\n"
    "可选槽位：\n{slots}\n"
    "规则：\n"
    "- 居住地/职业/宠物是单值属性，同一槽位多条不同值视为冲突（如住深圳 vs 住杭州）\n"
    "- 喜欢/爱好/偏好类若是可并存的多值（运动、饮食、音乐），归 preference:other 或具体 preference:*\n"
    "- 无法归类的陈述归 fact\n"
    "只输出 JSON：{{\"slot\": \"槽位名\"}}\n\n"
    "记忆：{memory}"
)

# 单值可冲突槽位白名单（与 conflict_adapter._SINGLE_VALUE_SLOTS 对齐）
_SINGLE_VALUE = {
    "personal:location", "personal:pet", "personal:occupation",
    "preference:currency", "preference:response_style",
    "safety:external_send_confirmation", "preference:save_location",
    "preference:document_style", "preference:chart_type",
    "preference:development_workflow",
}

# 已修正记忆缓存（内存态，避免重复 LLM）
_slot_cache: dict[str, str] = {}
_cache_lock = threading.Lock()
_pool: Optional[ThreadPoolExecutor] = None
_pool_lock = threading.Lock()


def _get_pool() -> ThreadPoolExecutor:
    global _pool
    with _pool_lock:
        if _pool is None:
            _pool = ThreadPoolExecutor(max_workers=2)
        return _pool


def _llm_classify(memory_text: str) -> Optional[str]:
    """LLM 判断槽位；失败返回 None。"""
    try:
        from src import llm_client
        slots = "\n".join(f"- {k}: {v}" for k, v in _SLOT_SCHEMA.items())
        prompt = _PROMPT_TMPL.format(slots=slots, memory=(memory_text or "")[:200])
        raw = llm_client.generate(prompt)
        start, end = raw.find("{"), raw.rfind("}")
        if start >= 0 and end > start:
            obj = json.loads(raw[start:end + 1])
            slot = str(obj.get("slot") or "").strip()
            if slot in _SLOT_SCHEMA:
                return slot
    except Exception as e:
        logger.warning("[slot_llm] 分类失败: %s", str(e)[:80])
    return None


def _apply_slot(memory_id: str, memory_text: str):
    """后台任务：LLM 判断槽位并回写 store。"""
    try:
        with _cache_lock:
            if memory_id in _slot_cache:
                return
        slot = _llm_classify(memory_text)
        if slot is None:
            return
        with _cache_lock:
            _slot_cache[memory_id] = slot
        from .store import MemoryEngineStore
        store = MemoryEngineStore()
        store.update_memory_slot(memory_id, slot)
        print(f"[slot_llm] 记忆 {memory_id[:12]} 槽位修正: -> {slot} "
              f"({memory_text[:30]})", flush=True)
    except Exception as e:
        logger.warning("[slot_llm] 回写失败: %s", str(e)[:80])


def schedule_slot_review(memory_id: str, memory_text: str):
    """写入后异步触发槽位精修（非阻塞）。"""
    try:
        _get_pool().submit(_apply_slot, memory_id, memory_text)
    except Exception:
        pass


def is_single_value_slot(slot: str) -> bool:
    """槽位是否单值可冲突。"""
    return slot in _SINGLE_VALUE

