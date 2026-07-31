"""Threat scanner — input content safety inspection.

Migrated from ``src/memory/threat_patterns.py`` and extended with
additional rules for command injection, path traversal, and sensitive
file-system access.
"""
from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)

# ========== Invisible Unicode characters ==========
INVISIBLE_CHARS = frozenset({
    '\u200b', '\u200c', '\u200d', '\u2060', '\u2062', '\u2063', '\u2064',
    '\ufeff', '\u202a', '\u202b', '\u202c', '\u202d', '\u202e',
    '\u2066', '\u2067', '\u2068', '\u2069',
})

# ========== Built-in threat rules ==========
_PATTERNS: list[Tuple[str, str, str]] = [
    # (regex, rule_id, severity)

    # --- Prompt injection (CN + EN) ---
    (r'(?:忽略|无视|忘记)\s*(?:(?:所有|任何|之前|上述|上面|这些|那些)\s*)*?(?:的\s*)?(?:指令|规则|限制|约束)', "prompt_injection_cn", "high"),
    (r'(?:ignore|disregard|forget)\s+(?:\w+\s+)*(?:all|previous|above|prior\s+)?(?:\w+\s+)*(?:instructions?|rules?|constraints?)', "prompt_injection_en", "high"),
    (r'(?:你\s*现在\s*是|假装\s*你是|扮演)\s*(?:一个|一名)', "role_hijack_cn", "high"),
    (r'(?:输出|打印|显示|告诉我)\s*(?:你的\s*)?(?:系统\s*)?(?:提示词|prompt|指令)', "leak_system_prompt_cn", "high"),
    (r'(?:不要|不准|禁止)\s*(?:告诉|通知|提示)\s*用户', "deception_hide_cn", "medium"),

    # --- Data exfiltration ---
    (r'curl\s+[^\n]*\$\{?\w*(?:KEY|TOKEN|SECRET|PASSWORD|API)', "exfil_curl", "high"),
    (r'wget\s+[^\n]*\$\{?\w*(?:KEY|TOKEN|SECRET|PASSWORD|API)', "exfil_wget", "high"),
    (r'cat\s+[^\n]*(?:\.env|credentials|\.netrc|\.pgpass)', "read_secrets", "high"),
    (r'(?:发送|上传|传输).*(?:对话|聊天)\s*(?:记录|历史|内容)|(?:对话|聊天)\s*(?:记录|历史|内容).*(?:发送|上传|传输)', "context_exfil_cn", "high"),

    # --- Hardcoded secrets ---
    (r'(?:api[_-]?key|token|secret|password|密钥|AK\s*ID)\s*[=:：]\s*["\'][A-Za-z0-9+/=_-]{20,}', "hardcoded_secret", "critical"),
    (r'sk-[A-Za-z0-9_-]{20,}', "openai_key_prefix", "critical"),
    (r'ghp_[A-Za-z0-9]{20,}', "github_token", "critical"),

    # --- Path traversal / backdoor ---
    (r'(?:\.\./)+\.\./(?:\.ssh|\.hermes|\.env)', "path_traversal", "high"),
    (r'authorized_keys', "ssh_backdoor", "high"),

    # --- Command injection (new) ---
    (r'[;&|]\s*(?:rm\s+-rf|shutdown|reboot|mkfs|dd\s+if)', "cmd_injection_destructive", "critical"),
    (r'\$\([^)]*\)', "cmd_injection_subshell", "medium"),
    (r'`[^`]+`', "cmd_injection_backtick", "medium"),

    # --- Path traversal (new, broad) ---
    (r'(?:\.\./){3,}', "path_traversal_deep", "high"),

    # --- Sensitive filesystem access (new) ---
    (r'/proc/(?:self|\d+)/', "sensitive_proc_access", "medium"),
    (r'/sys/kernel/', "sensitive_sys_access", "medium"),
]

# Config path for external rules
_CONFIG_PATH = Path(__file__).parent.parent / "config" / "threat_patterns.json"


# ========== Data classes ==========

@dataclass
class ThreatResult:
    """Result of a threat scan."""
    safe: bool
    threat_ids: list[str] = field(default_factory=list)
    severity: str = ""           # highest severity found: low / medium / high / critical
    description: str = ""

    SEVERITY_ORDER = {"low": 0, "medium": 1, "high": 2, "critical": 3}


# ========== Scanner ==========

class ThreatScanner:
    """Compiled threat-pattern scanner with hot-reload support."""

    def __init__(self):
        self._file_mtime: float = 0.0
        self._compiled: list[tuple[re.Pattern, str, str]] = []
        self._reload()

    # ------------------------------------------------------------------
    # Pattern management
    # ------------------------------------------------------------------

    def _reload(self):
        """Merge built-in rules with external config file."""
        merged = list(_PATTERNS)
        if _CONFIG_PATH.exists():
            try:
                with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
                    data = json.load(f)
                for item in data.get("patterns", []):
                    severity = item.get("severity", "medium")
                    merged.append((item["pattern"], item["id"], severity))
            except (json.JSONDecodeError, KeyError) as e:
                logger.error(f"Failed to load threat patterns config: {e}")

        self._compiled = [
            (re.compile(p, re.IGNORECASE), pid, sev)
            for p, pid, sev in merged
        ]

    def _check_reload(self):
        """Hot-reload if the config file changed on disk."""
        try:
            current = _CONFIG_PATH.stat().st_mtime
        except FileNotFoundError:
            current = 0.0
        if current != self._file_mtime:
            logger.info("threat_patterns.json changed, reloading...")
            self._reload()
        try:
            self._file_mtime = _CONFIG_PATH.stat().st_mtime
        except FileNotFoundError:
            self._file_mtime = 0.0

    # ------------------------------------------------------------------
    # Scanning
    # ------------------------------------------------------------------

    def scan(self, text: str) -> ThreatResult:
        """Scan *text* and return a structured ThreatResult."""
        if not text:
            return ThreatResult(safe=True)

        self._check_reload()

        threat_ids: list[str] = []
        severities: list[str] = []

        # Invisible Unicode
        char_set = set(text)
        for ch in char_set & INVISIBLE_CHARS:
            threat_ids.append(f"invisible_unicode_U+{ord(ch):04X}")
            severities.append("high")

        # Regex patterns
        for compiled, pid, severity in self._compiled:
            if compiled.search(text):
                threat_ids.append(pid)
                severities.append(severity)

        if not threat_ids:
            return ThreatResult(safe=True)

        max_sev = max(severities, key=lambda s: ThreatResult.SEVERITY_ORDER.get(s, 0))
        return ThreatResult(
            safe=False,
            threat_ids=threat_ids,
            severity=max_sev,
            description=self._describe(threat_ids[0]),
        )

    def is_safe(self, text: str) -> bool:
        return self.scan(text).safe

    def first_threat(self, text: str) -> Optional[str]:
        result = self.scan(text)
        if result.safe:
            return None
        return self._describe(result.threat_ids[0])

    @staticmethod
    def _describe(pid: str) -> str:
        if pid.startswith("invisible_unicode_"):
            return f"内容包含隐形 Unicode 字符 {pid.replace('invisible_unicode_', '')}，疑似注入攻击"
        return f"内容匹配威胁模式 '{pid}'，已拦截"


# ========== Module-level singleton ==========

_threat_scanner: Optional[ThreatScanner] = None


def get_threat_scanner() -> ThreatScanner:
    global _threat_scanner
    if _threat_scanner is None:
        _threat_scanner = ThreatScanner()
    return _threat_scanner


# ========== Backwards-compatible module-level functions ==========

def scan_content(text: str) -> List[str]:
    """Backwards-compatible: return list of matched threat IDs."""
    return get_threat_scanner().scan(text).threat_ids


def is_safe(text: str) -> bool:
    return get_threat_scanner().is_safe(text)


def first_threat(text: str) -> Optional[str]:
    return get_threat_scanner().first_threat(text)
