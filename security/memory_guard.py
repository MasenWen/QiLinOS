"""Memory write guard — content review pipeline before persisting to memory."""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Optional

from .threat import get_threat_scanner, ThreatScanner
from .sensitivity import SensitivityLevel, classify as classify_sensitivity

logger = logging.getLogger(__name__)

# ========== PII / sensitive data patterns ==========
_PII_PATTERNS = [
    # Email
    (re.compile(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}'), '[EMAIL]'),
    # 中国手机号：按 category 采用两种掩码（见 _phone_mask）
    #   · 输出/日志（reply/general/log）→ 保留可辨识形式：138****0001
    #   · 写入记忆（memory）→ 不保留任何数字：[敏感信息]
    (re.compile(r'(?:\+?86)?1[3-9]\d{9}'), None),   # 占位：替换逻辑在 _apply_pii 中按 category 处理
    # 身份证号（18 位，无分隔符；置于银行卡之前避免被 13-19 位数字规则吞成 [BANK]）
    (re.compile(r'(?<![\d])\d{17}[\dXx](?![\d])'), '[ID]'),
    # Bank card (13-19 digits, optional space/dash separators)
    (re.compile(r'(?<![\d])(?:\d[ -]?){15,18}\d(?![\d])'), '[BANK]'),
    # API keys (common prefixes)
    (re.compile(r'sk-[A-Za-z0-9_-]{20,}'), '[API_KEY]'),
    (re.compile(r'ghp_[A-Za-z0-9]{20,}'), '[API_KEY]'),
    # 裸令牌字面量（如 TEST-TOKEN-000000）：无 key= 赋值形式也需脱敏
    (re.compile(r'(?:\bTEST-)?TOKEN[-_][A-Za-z0-9_-]{3,}\b', re.IGNORECASE), '[TOKEN]'),
    # Passwords in key=value form
    (re.compile(r'(?:password|passwd|pwd)\s*[=:：]\s*\S+', re.IGNORECASE), '[SECRET]'),
    # Token/secret assignments
    (re.compile(r'(?:api[_-]?key|token|secret|密钥)\s*[=:：]\s*\S+', re.IGNORECASE), '[API_KEY]'),
    # 中文赋值格式：密码是xxx / 密钥为xxx / token为xxx
    (re.compile(r'(?:密码|口令)\s*(?:是|为|[:：=])\s*\S+', re.IGNORECASE), '[SECRET]'),
    (re.compile(r'(?:密钥|token|令牌|secret)\s*(?:是|为|[:：=])\s*\S+', re.IGNORECASE), '[API_KEY]'),
]

# Control characters and null bytes
_CONTROL_RE = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f]')

# 手机号掩码：138****0001（保留前 3 位与后 4 位，中间 4 位打码）
_PHONE_RE = re.compile(r'(?:\+?86)?1[3-9]\d{9}')
_PHONE_MASK_MEMORY = "[敏感信息]"


def mask_phone(text: str, style: str = "output") -> str:
    """按风格掩码手机号。

    style="output" → 138****0001（界面/回复/日志：保留可辨识形式，不丢信息）
    style="memory" → [敏感信息]（写入长期记忆：不保留任何数字）
    """
    def _rep(m):
        raw = m.group()
        prefix = "+86" if raw.startswith("+86") else ("86" if raw.startswith("86") and len(raw) > 11 else "")
        core = raw[len(prefix):]
        if style == "memory":
            return prefix + _PHONE_MASK_MEMORY
        if len(core) >= 7:
            return prefix + core[:3] + "*" * (len(core) - 7) + core[-4:]
        return prefix + _PHONE_MASK_MEMORY
    return _PHONE_RE.sub(_rep, text or "")


def mask_pii(text: str) -> str:
    """对外脱敏（日志/会话历史用）：PII 一律替换为可辨识掩码，不丢信息。"""
    out = mask_phone(text or "", style="output")
    for pattern, replacement in _PII_PATTERNS:
        if replacement is None:
            continue
        out = pattern.sub(replacement, out)
    return out

MAX_CONTENT_LENGTH = 32 * 1024  # 32K


@dataclass
class ContentReviewResult:
    allowed: bool
    sanitized_text: str
    threat_ids: list[str] = field(default_factory=list)
    pii_redactions: int = 0
    truncated: bool = False
    reason: str = ""
    # 敏感标注（指令「敏感」：识别、控制、标注）
    sensitivity: SensitivityLevel = SensitivityLevel.NONE
    sensitive_types: list[str] = field(default_factory=list)


class MemoryGuard:
    """Four-layer content review pipeline:

    1. Threat scan (prompt injection, invisible Unicode, secret patterns)
    2. PII detection and sanitization
    3. Structural cleanup (null bytes, control characters)
    4. Length enforcement (32K truncation)
    """

    def __init__(self, scanner: Optional[ThreatScanner] = None):
        self._scanner = scanner

    @property
    def scanner(self) -> ThreatScanner:
        if self._scanner is None:
            self._scanner = get_threat_scanner()
        return self._scanner

    def review(self, content: str, category: str = "general", source: str = "") -> ContentReviewResult:
        """Run the full review pipeline on *content*.

        Returns a ContentReviewResult.  If ``allowed`` is False the content
        MUST NOT be persisted.
        """
        if not content:
            return ContentReviewResult(allowed=True, sanitized_text="")

        # ---- Layer 1: Threat scan ----
        threat_result = self.scanner.scan(content)
        if threat_result.severity in ("high", "critical"):
            return ContentReviewResult(
                allowed=False,
                sanitized_text="",
                threat_ids=threat_result.threat_ids,
                reason=f"内容包含 {threat_result.severity} 级别威胁: {', '.join(threat_result.threat_ids)}",
            )

        text = content

        # ---- Layer 2: PII detection and redaction ----
        # 手机号按用途分流：写记忆→[敏感信息]（不留数字）；其他→138****0001（保留可辨识形式）
        pii_count = 0
        _phone_style = "memory" if (category or "").lower() == "memory" else "output"
        text, _pn = _PHONE_RE.subn(lambda m: mask_phone(m.group(), style=_phone_style), text)
        pii_count += _pn
        for pattern, replacement in _PII_PATTERNS:
            if replacement is None:
                continue
            new_text, n = pattern.subn(replacement, text)
            if n > 0:
                pii_count += n
                text = new_text

        # ---- Layer 3: Structural cleanup ----
        text = _CONTROL_RE.sub('', text)

        # ---- Layer 4: Length limit ----
        truncated = False
        if len(text) > MAX_CONTENT_LENGTH:
            text = text[:MAX_CONTENT_LENGTH]
            truncated = True

        # 敏感标注：基于原文识别敏感级别（防脱敏后丢失原始标记），供遗忘联动与防泄漏
        sens = classify_sensitivity(content)
        return ContentReviewResult(
            allowed=True,
            sanitized_text=text,
            threat_ids=threat_result.threat_ids,
            pii_redactions=pii_count,
            truncated=truncated,
            reason="审查通过" if not threat_result.threat_ids else f"低风险威胁放行: {', '.join(threat_result.threat_ids)}",
            sensitivity=sens.level,
            sensitive_types=sens.sensitive_types,
        )


# ========== Module-level singleton ==========

_memory_guard: Optional[MemoryGuard] = None


def get_memory_guard() -> MemoryGuard:
    global _memory_guard
    if _memory_guard is None:
        _memory_guard = MemoryGuard()
    return _memory_guard
