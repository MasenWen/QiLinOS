from __future__ import annotations

import re


INVISIBLE_CHARS = frozenset(
    {
        "\u200b", "\u200c", "\u200d", "\u2060", "\u2062", "\u2063", "\u2064",
        "\ufeff", "\u202a", "\u202b", "\u202c", "\u202d", "\u202e",
        "\u2066", "\u2067", "\u2068", "\u2069",
    }
)

SECRET_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"sk-[A-Za-z0-9_-]{20,}",
        r"ghp_[A-Za-z0-9]{20,}",
        r"(?:api[_-]?key|token|secret|password|密钥)\s*[=:：]\s*[^\s]{20,}",
    )
)


def is_engine_safe(text: str) -> bool:
    if not text:
        return True
    if set(text) & INVISIBLE_CHARS:
        return False
    return not any(pattern.search(text) for pattern in SECRET_PATTERNS)
