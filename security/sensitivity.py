"""敏感信息识别与标注（指令「敏感」：识别、控制、标注，防泄漏、辅助遗忘）

独立模块，供 memory_guard（写入守卫）与遗忘模块（按标注精准遗忘）复用。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Sequence


class SensitivityLevel(StrEnum):
    NONE = "none"            # 无敏感信息
    LOW = "low"              # 低敏感（结构异常等）
    MEDIUM = "medium"        # 中敏感（联系方式等）
    HIGH = "high"            # 高敏感（身份信息等）
    CRITICAL = "critical"    # 极敏感（凭据/密钥等，必须脱敏或拒存）


@dataclass(frozen=True)
class SensitivityRule:
    level: SensitivityLevel
    pattern: re.Pattern
    label: str


# ========== 敏感规则（按级别分级） ==========
_SENSITIVITY_RULES: tuple[SensitivityRule, ...] = (
    # --- CRITICAL：凭据类 ---
    SensitivityRule(SensitivityLevel.CRITICAL, re.compile(r"sk-[A-Za-z0-9_-]{20,}"), "api_key"),
    SensitivityRule(SensitivityLevel.CRITICAL, re.compile(r"ghp_[A-Za-z0-9]{20,}"), "api_key"),
    SensitivityRule(SensitivityLevel.CRITICAL, re.compile(r"(?:password|passwd|pwd)\s*[=:：]\s*\S+", re.IGNORECASE), "password"),
    SensitivityRule(SensitivityLevel.CRITICAL, re.compile(r"(?:api[_-]?key|token|secret|密钥)\s*[=:：]\s*\S+", re.IGNORECASE), "secret"),
    # --- HIGH：身份类 ---
    SensitivityRule(SensitivityLevel.HIGH, re.compile(r"(?:\+?86)?1[3-9]\d{9}"), "phone"),
    SensitivityRule(SensitivityLevel.HIGH, re.compile(r"\d{17}[\dXx]"), "id_card"),
    # 银行卡（13-19 位，可选空格/连字符分隔；16-19 位主流）
    # 负向后瞻/前瞻防与身份证（18 位无分隔）误匹配：银行卡允许分隔符，身份证无
    SensitivityRule(SensitivityLevel.HIGH, re.compile(r"(?<![\d])(?:\d[ -]?){15,18}\d(?![\d])"), "bank_card"),
    # --- MEDIUM：联系方式 ---
    SensitivityRule(SensitivityLevel.MEDIUM, re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), "email"),
    # --- LOW：结构异常（控制字符等）---
    SensitivityRule(SensitivityLevel.LOW, re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]"), "control_chars"),
)

_LEVEL_RANK = {
    SensitivityLevel.NONE: 0,
    SensitivityLevel.LOW: 1,
    SensitivityLevel.MEDIUM: 2,
    SensitivityLevel.HIGH: 3,
    SensitivityLevel.CRITICAL: 4,
}


def _luhn_valid(digits: str) -> bool:
    """Luhn 校验（银行卡号真实性校验）：从左到右，偶数位×2（>9 减 9），总和 %10==0。"""
    try:
        total = 0
        for i, ch in enumerate(reversed(digits)):
            d = int(ch)
            if i % 2 == 1:
                d *= 2
                if d > 9:
                    d -= 9
            total += d
        return total % 10 == 0
    except Exception:
        return False


@dataclass
class SensitivityResult:
    """敏感识别结果：最高级别 + 命中的敏感类型。"""

    level: SensitivityLevel = SensitivityLevel.NONE
    sensitive_types: list[str] = field(default_factory=list)
    matches: list[str] = field(default_factory=list)

    @property
    def is_sensitive(self) -> bool:
        return self.level != SensitivityLevel.NONE

    def to_dict(self) -> dict:
        return {
            "level": self.level.value,
            "sensitive_types": self.sensitive_types,
            "matches": self.matches,
        }


def classify(content: str) -> SensitivityResult:
    """识别内容敏感级别与命中类型。"""
    if not content:
        return SensitivityResult()
    result = SensitivityResult()
    for rule in _SENSITIVITY_RULES:
        m = rule.pattern.search(content)
        if m:
            # 银行卡 Luhn 校验：18 位连续数字（身份证）不通过则不算银行卡
            if rule.label == "bank_card":
                digits = re.sub(r"[ -]", "", m.group(0))
                if not (13 <= len(digits) <= 19) or not _luhn_valid(digits):
                    continue
            result.sensitive_types.append(rule.label)
            result.matches.append(m.group(0)[:32])
            if _LEVEL_RANK[rule.level] > _LEVEL_RANK[result.level]:
                result.level = rule.level
    return result


def sanitize(content: str, level: SensitivityLevel = SensitivityLevel.CRITICAL) -> str:
    """按级别脱敏：对 ≤ 给定级别的敏感内容做占位符替换（防泄漏）。"""
    if not content:
        return ""
    out = content
    for rule in _SENSITIVITY_RULES:
        if _LEVEL_RANK[rule.level] <= _LEVEL_RANK[level]:
            out = rule.pattern.sub(f"[{rule.label.upper()}]", out)
    return out


def sensitivity_label(level: SensitivityLevel) -> str:
    """中文标签（便于记忆标注展示）。"""
    return {
        SensitivityLevel.NONE: "无",
        SensitivityLevel.LOW: "低",
        SensitivityLevel.MEDIUM: "中",
        SensitivityLevel.HIGH: "高",
        SensitivityLevel.CRITICAL: "极",
    }[level]


class SensitivityRegistry:
    """敏感记忆登记：记录 memory_id → 敏感级别，供精准遗忘联动。"""

    def __init__(self) -> None:
        self._index: dict[str, SensitivityLevel] = {}

    def record(self, memory_id: str, level: SensitivityLevel) -> None:
        if level != SensitivityLevel.NONE:
            self._index[memory_id] = level
        else:
            self._index.pop(memory_id, None)

    def sensitive_ids(self, min_level: SensitivityLevel = SensitivityLevel.HIGH) -> list[str]:
        return [mid for mid, lv in self._index.items() if _LEVEL_RANK[lv] >= _LEVEL_RANK[min_level]]

    def forget_sensitive(self, min_level: SensitivityLevel = SensitivityLevel.HIGH) -> list[str]:
        ids = self.sensitive_ids(min_level)
        for mid in ids:
            self._index.pop(mid, None)
        return ids

    def __len__(self) -> int:
        return len(self._index)
