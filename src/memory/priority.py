"""记忆优先级判定（Memory Priority）— 多因子综合打分

设计目标：为每条记忆计算 0~100 的优先级分数与 高/中/低 等级，
用于：①检索加权 ②淘汰保护（低优先级先淘汰）③记忆面板展示排序。

打分因子（权重可调）:
  1. 用户强调 (0.35)  — 文本含强调词（务必/重要/永远/always/prefer…）
  2. 时间衰减 (0.25)  — 创建时间越近越高（指数衰减，半衰期 30 天）
  3. 敏感等级 (0.20)  — 高敏感记忆加权保护（不轻易淘汰）
  4. 信息密度 (0.10)  — 长度适中的记忆信息量更高
  5. 被引用频率 (0.10) — 调用方传入的命中/引用次数（如检索命中数）

用法:
  from src.memory.priority import compute_priority, PriorityLevel
  result = compute_priority("用户小张喜欢喝咖啡", created_at="2026-08-20 10:00:00")
  # -> {"score": 68.5, "level": "medium", "factors": {...}}
"""
from __future__ import annotations

import re
from datetime import datetime
from enum import StrEnum
from typing import Any, Optional

# ---------- 优先级等级 ----------
class PriorityLevel(StrEnum):
    HIGH = "high"        # 高：核心偏好/重要事实/敏感信息
    MEDIUM = "medium"    # 中：一般事实/习惯
    LOW = "low"          # 低：临时/快照/冗余

# ---------- 权重 ----------
W_EMPHASIS = 0.30
W_RECENCY = 0.20
W_SENSITIVITY = 0.30
W_DENSITY = 0.10
W_FREQUENCY = 0.10

# 强调词（中文 + 英文）
_EMPHASIS_WORDS = (
    "非常重要", "特别重要", "务必", "一定要", "千万", "永远", "一直",
    "记住", "牢记", "关键", "重要", "重点", "强调", "核心",
    "always", "never", "prefer", "must", "important", "essential", "favorite",
)

# 时间衰减半衰期（天）：30 天后权重降一半
HALF_LIFE_DAYS = 30.0

# 高敏感级别（与 security.sensitivity 对齐：high/critical）
_SENSITIVE_HIGH_RANK = 3  # SensitivityLevel rank: none=0 low=1 medium=2 high=3 critical=4


def _emphasis_score(text: str) -> float:
    """强调因子：命中强调词数量 → 0~1"""
    low = (text or "").lower()
    hits = sum(1 for w in _EMPHASIS_WORDS if w in low)
    if hits >= 3:
        return 1.0
    if hits == 2:
        return 0.8
    if hits == 1:
        return 0.55
    return 0.15


def _recency_score(created_at: Optional[str]) -> float:
    """时间衰减因子：指数衰减 exp(-age_days / HALF_LIFE) → 0~1"""
    if not created_at:
        return 0.5  # 无时间信息给中值
    try:
        ts = created_at
        if isinstance(ts, (int, float)):
            dt = datetime.fromtimestamp(ts)
        else:
            dt = datetime.strptime(str(ts)[:19], "%Y-%m-%d %H:%M:%S")
        age_days = max(0.0, (datetime.now() - dt).total_seconds() / 86400.0)
        import math
        return math.exp(-age_days / HALF_LIFE_DAYS)
    except Exception:
        return 0.5


def _sensitivity_score(sensitivity_level: Any) -> float:
    """敏感因子：高/极敏感记忆加权（需保护，不轻易淘汰）"""
    try:
        from security.sensitivity import SensitivityLevel, _LEVEL_RANK
        rank = _LEVEL_RANK.get(sensitivity_level, 0)
        return min(1.0, rank / 4.0)
    except Exception:
        return 0.0


def _density_score(text: str) -> float:
    """信息密度因子：长度适中（20~120 字）信息量最高"""
    n = len(text or "")
    if 20 <= n <= 120:
        return 1.0
    if 5 <= n < 20 or 120 < n <= 200:
        return 0.6
    return 0.3


def _frequency_score(hits: int) -> float:
    """频率因子：被引用/命中次数 → 0~1（封顶 5 次）"""
    return min(1.0, max(0.0, (hits or 0)) / 5.0)


def compute_priority(
    text: str,
    created_at: Optional[str] = None,
    sensitivity_level: Any = None,
    hits: int = 0,
) -> dict[str, Any]:
    """综合打分 → {score, level, factors}"""
    em = _emphasis_score(text)
    re_ = _recency_score(created_at)
    se = _sensitivity_score(sensitivity_level)
    de = _density_score(text)
    fr = _frequency_score(hits)

    score = (W_EMPHASIS * em + W_RECENCY * re_ + W_SENSITIVITY * se
             + W_DENSITY * de + W_FREQUENCY * fr) * 100.0

    if score >= 60:
        level = PriorityLevel.HIGH
    elif score >= 35:
        level = PriorityLevel.MEDIUM
    else:
        level = PriorityLevel.LOW

    # ---- 等级覆盖规则（保护性）----
    # ① 高/极敏感记忆（手机号/身份证/密码/密钥）：至少 MEDIUM，防止被当作低价值淘汰
    if se >= 0.75:  # rank >= 3 (HIGH/CRITICAL)
        if level == PriorityLevel.LOW:
            level = PriorityLevel.MEDIUM
    # ② 用户强强调（命中 >= 3 个强调词）：直接 HIGH
    if em >= 1.0:
        level = PriorityLevel.HIGH
    elif em >= 0.8:
        if level == PriorityLevel.LOW:
            level = PriorityLevel.MEDIUM

    return {
        "score": round(score, 1),
        "level": level.value,
        "factors": {
            "emphasis": round(em, 3),
            "recency": round(re_, 3),
            "sensitivity": round(se, 3),
            "density": round(de, 3),
            "frequency": round(fr, 3),
        },
    }


def prioritize_items(items: list[dict], text_key: str = "memory") -> list[dict]:
    """批量：给记忆条目列表附加 priority 字段并排序（高→低）。

    输入条目需含 text_key 文本；可选 created_at / sensitivity 字段。
    返回新列表（不修改原条目）。
    """
    out: list[dict] = []
    for it in items or []:
        text = str(it.get(text_key) or "")
        created_at = it.get("created_at") or it.get("updated_at") or ""
        sens = it.get("sensitivity") or it.get("sensitive_level")
        pr = compute_priority(text, created_at=created_at, sensitivity_level=sens)
        out.append({**it, "priority": pr["score"], "priority_level": pr["level"]})
    out.sort(key=lambda x: x.get("priority", 0), reverse=True)
    return out


def lowest_priority_ids(items: list[dict], keep: int, text_key: str = "memory") -> list[str]:
    """淘汰选择：返回应淘汰的 id 列表（低优先级优先，同优先级按时间旧优先）。

    用于 mem0 上限淘汰：先淘汰 LOW 级最旧，再 MEDIUM 级最旧，最后 HIGH 级最旧。
    """
    ranked = prioritize_items(items, text_key=text_key)
    if len(ranked) <= keep:
        return []
    # 敏感记忆淘汰保护：HIGH/CRITICAL 敏感记忆默认不淘汰（除非候选不足）
    def _is_sensitive(it):
        try:
            from security.sensitivity import _LEVEL_RANK, SensitivityLevel
            lv = it.get("sensitivity") or it.get("sensitive_level") or SensitivityLevel.NONE
            return _LEVEL_RANK.get(lv, 0) >= 3
        except Exception:
            return False

    protected = [it for it in ranked if _is_sensitive(it)]
    candidates = [it for it in ranked if not _is_sensitive(it)]
    need = max(0, len(ranked) - keep)
    # 按 (level 排序权重, created_at 旧→新) 排
    level_order = {"low": 0, "medium": 1, "high": 2}

    def _sort_key(it):
        return (level_order.get(it.get("priority_level", "low"), 0),
                it.get("created_at") or it.get("updated_at") or "")

    victims = sorted(candidates, key=_sort_key)[:need]
    if len(victims) < need:
        # 非敏感候选不足时，才允许淘汰敏感中最低级的
        extra = sorted(protected, key=_sort_key)[: need - len(victims)]
        victims += extra
    return [v.get("id") or v.get("memory_id") for v in victims if v.get("id") or v.get("memory_id")]
