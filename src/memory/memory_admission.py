"""记忆准入判定（参考 strict Evidence admission 机制，2026-08-29）。

strict 的 admission 思想：只有带长期标记（记住/总是/一直…）的陈述才进入长期记忆，
瞬时信息（明天/待办/会议…）只做短期处理。本模块把该思想用于审查/写入层——
防止 mem0 提取的瞬时信息（如「明天有会议」）污染长期记忆。

判定规则（保守，不误杀）：
  - 含瞬时标记且不含长期标记 → temporary（不写入）
  - 含长期标记（无论是否含瞬时）→ long_term（写入）
  - 无标记 → neutral（放行，保持现状）
"""
from __future__ import annotations

# 瞬时信息标记（时间性/任务性）
_TEMPORARY_MARKERS = (
    "明天", "今天", "今晚", "昨天", "下周", "这周", "这个月", "月底", "下个月",
    "临时", "待办", "会议", "安排", "计划", "预约", "提醒", "截止", "过期",
    "deadline", "tmr", "today", "tomorrow", "next week", "later",
    "上午", "下午", "晚上", "点钟", "几点",
)
# 长期信息标记（持久属性/偏好/身份）
_LONG_TERM_MARKERS = (
    "喜欢", "偏好", "偏爱", "住在", "居住", "职业", "工作", "名字", "叫",
    "养了", "习惯", "通常", "总是", "一直", "记住", "擅长", "最爱", "家在",
    "prefer", "always", "remember", "喜欢喝", "喜欢打", "爱好",
)


def admission_decision(text: str) -> str:
    """返回 long_term / temporary / neutral。"""
    lowered = (text or "").lower()
    has_temp = any(m in lowered for m in _TEMPORARY_MARKERS)
    has_long = any(m in lowered for m in _LONG_TERM_MARKERS)
    if has_long:
        return "long_term"
    if has_temp:
        return "temporary"
    return "neutral"


def should_persist(text: str) -> bool:
    """是否应持久化（temporary → False，其余 True）。"""
    return admission_decision(text) != "temporary"
