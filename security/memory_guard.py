"""Memory write guard — content review pipeline before persisting to memory."""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Optional

from .threat import get_threat_scanner, ThreatScanner

logger = logging.getLogger(__name__)

# ========== PII / sensitive data patterns ==========
_PII_PATTERNS = [
    # Email
    (re.compile(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}'), '[EMAIL]'),
    # Chinese mobile
    (re.compile(r'(?:\+?86)?1[3-9]\d{9}'), '[PHONE]'),
    # API keys (common prefixes)
    (re.compile(r'sk-[A-Za-z0-9_-]{20,}'), '[API_KEY]'),
    (re.compile(r'ghp_[A-Za-z0-9]{20,}'), '[API_KEY]'),
    # Passwords in key=value form
    (re.compile(r'(?:password|passwd|pwd)\s*[=:：]\s*\S+', re.IGNORECASE), '[SECRET]'),
    # Token/secret assignments
    (re.compile(r'(?:api[_-]?key|token|secret|密钥)\s*[=:：]\s*\S+', re.IGNORECASE), '[API_KEY]'),
]

# Control characters and null bytes
_CONTROL_RE = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f]')

MAX_CONTENT_LENGTH = 32 * 1024  # 32K


@dataclass
class ContentReviewResult:
    allowed: bool
    sanitized_text: str
    threat_ids: list[str] = field(default_factory=list)
    pii_redactions: int = 0
    truncated: bool = False
    reason: str = ""


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
        pii_count = 0
        for pattern, replacement in _PII_PATTERNS:
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

        return ContentReviewResult(
            allowed=True,
            sanitized_text=text,
            threat_ids=threat_result.threat_ids,
            pii_redactions=pii_count,
            truncated=truncated,
            reason="审查通过" if not threat_result.threat_ids else f"低风险威胁放行: {', '.join(threat_result.threat_ids)}",
        )


# ========== Module-level singleton ==========

_memory_guard: Optional[MemoryGuard] = None


def get_memory_guard() -> MemoryGuard:
    global _memory_guard
    if _memory_guard is None:
        _memory_guard = MemoryGuard()
    return _memory_guard
