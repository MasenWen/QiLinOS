"""Phase 2: Memory Security Filter — S0-S3 sensitivity classification.

Bridges SDK binding levels + security permission levels + toolkit RiskLevel
into a unified memory sensitivity classification that controls how tool
results are stored (full / redacted / summarized / blocked).

Sensitivity levels:
  S0 PUBLIC      — full storage, no redaction
  S1 INTERNAL    — PII redaction via MemoryGuard
  S2 CONFIDENTIAL — redact + truncate 200 chars + mask parameters
  S3 RESTRICTED  — block entirely, audit log
"""

from __future__ import annotations

import re

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger("memory_engine.security")


# ============================================================================
# Sensitivity classification
# ============================================================================

class Sensitivity(Enum):
    """Memory sensitivity level derived from tool risk + permission + SDK layer."""
    S0 = "public"        # full storage
    S1 = "internal"      # redact PII
    S2 = "confidential"  # redact + summarize
    S3 = "restricted"    # block entirely


# ============================================================================
# Mapping matrix
# ============================================================================

# (RiskLevel, PermissionLevel, SDKBindingLevel) → Sensitivity
SENSITIVITY_MAP = {
    # LOW risk
    ("low", "L0", "L0"): Sensitivity.S0,     # safe read-only
    ("low", "L0", "L1"): Sensitivity.S1,     # shell output may contain artifacts
    ("low", "L0", "L2"): Sensitivity.S2,     # cloud API, privacy concern
    ("low", "L1", "L0"): Sensitivity.S1,     # needs confirm but safe bind
    ("low", "L1", "L1"): Sensitivity.S1,     # shell + confirm
    ("low", "L1", "L2"): Sensitivity.S2,     # cloud + confirm
    # MEDIUM risk
    ("medium", "L0", "L0"): Sensitivity.S1,  # reversible but system-modifying
    ("medium", "L0", "L1"): Sensitivity.S2,  # subprocess + reversible
    ("medium", "L0", "L2"): Sensitivity.S2,  # cloud + reversible
    ("medium", "L1", "L0"): Sensitivity.S2,  # confirmed + ctypes
    ("medium", "L1", "L1"): Sensitivity.S2,  # confirmed + subprocess
    ("medium", "L1", "L2"): Sensitivity.S2,  # confirmed + cloud
    # CONSEQUENTIAL risk
    ("consequential", "L0", "L0"): Sensitivity.S2,  # dangerous, audit
    ("consequential", "L0", "L1"): Sensitivity.S2,
    ("consequential", "L0", "L2"): Sensitivity.S2,
    ("consequential", "L1", "L0"): Sensitivity.S3,  # block
    ("consequential", "L1", "L1"): Sensitivity.S3,  # block
    ("consequential", "L1", "L2"): Sensitivity.S3,  # block
    # L2 permission = always RESTRICTED
    ("low", "L2", "L0"): Sensitivity.S3,
    ("medium", "L2", "L0"): Sensitivity.S3,
    ("consequential", "L2", "L0"): Sensitivity.S3,
}

# Default for unknown combinations: S1 (safe default with PII redaction)
DEFAULT_SENSITIVITY = Sensitivity.S1

# Max content length for S2 (confidential summary)
S2_MAX_CONTENT_LENGTH = 200


# ============================================================================
# Filtered observation
# ============================================================================

@dataclass
class FilteredObservation:
    """Result of applying the memory security filter to a tool observation."""
    allowed: bool
    sensitivity: Sensitivity
    event: Optional[Dict[str, Any]]  # None if blocked (S3)
    redactions: List[str] = field(default_factory=list)
    reason: str = ""


# ============================================================================
# MemorySecurityFilter
# ============================================================================

class MemorySecurityFilter:
    """Classifies tool results and applies appropriate storage rules.

    Flow:
      ToolResult + tool metadata → classify sensitivity → apply rules → return
       - S0: return event as-is
       - S1: PII redaction via MemoryGuard
       - S2: redact + truncate + mask params → summarized event
       - S3: return None (blocked), log audit
    """

    def __init__(self):
        self._audit_events: List[Dict] = []
        self._overrides: Dict[str, Sensitivity] = {}  # tool_name → override

    # ------------------------------------------------------------------
    # Public: main entry point
    # ------------------------------------------------------------------

    def filter(
        self,
        event: Dict[str, Any],
        *,
        tool: Any = None,
        sdk_level: str = "L0",
        permission_level: str = "L0",
        risk_level: str = "low",
    ) -> Optional[Dict[str, Any]]:
        """Apply security filter to an observation event.

        Parameters
        ----------
        event : dict
            The observation event from ToolResult.to_observation().
        tool : BaseTool or None
            The tool instance, used to read risk/name.
        sdk_level : str
            SDK binding level ("L0"/"L1"/"L2").
        permission_level : str
            Security permission level ("L0"/"L1"/"L2").
        risk_level : str
            Toolkit RiskLevel value ("low"/"medium"/"consequential").

        Returns
        -------
        dict or None
            Filtered event, or None if blocked (S3).
        """
        # Override from tool metadata
        if tool is not None:
            risk_level = getattr(tool, "risk", None)
            if hasattr(risk_level, "value"):
                risk_level = risk_level.value

        # Check for tool-specific override
        tool_name = event.get("tool_name", "")
        if tool_name in self._overrides:
            sensitivity = self._overrides[tool_name]
        else:
            sensitivity = self._classify(risk_level, permission_level, sdk_level)

        logger.debug(
            "Memory security: tool=%s risk=%s perm=%s sdk=%s → %s",
            tool_name, risk_level, permission_level, sdk_level, sensitivity.value,
        )

        # --- S0: PUBLIC — store as-is ---
        if sensitivity == Sensitivity.S0:
            return event

        # --- S1: INTERNAL — PII redaction ---
        if sensitivity == Sensitivity.S1:
            return self._apply_s1(event)

        # --- S2: CONFIDENTIAL — redact + summarize ---
        if sensitivity == Sensitivity.S2:
            return self._apply_s2(event)

        # --- S3: RESTRICTED — block ---
        if sensitivity == Sensitivity.S3:
            self._audit_events.append({
                "tool": tool_name,
                "sensitivity": sensitivity.value,
                "action": "BLOCKED",
                "reason": f"S3: risk={risk_level} perm={permission_level} sdk={sdk_level}",
            })
            logger.warning(
                "Memory recording BLOCKED (S3): tool=%s risk=%s perm=%s sdk=%s",
                tool_name, risk_level, permission_level, sdk_level,
            )
            return None

        # Fallback
        return event

    # ------------------------------------------------------------------
    # Classification
    # ------------------------------------------------------------------

    def _classify(self, risk: str, perm: str, sdk: str) -> Sensitivity:
        """Look up sensitivity from the mapping matrix."""
        key = (risk.lower(), perm.upper(), sdk.upper())
        if key in SENSITIVITY_MAP:
            return SENSITIVITY_MAP[key]
        # Try wildcard matching
        for pattern, level in SENSITIVITY_MAP.items():
            if self._match_key(key, pattern):
                return level
        return DEFAULT_SENSITIVITY

    @staticmethod
    def _match_key(key: tuple, pattern: tuple) -> bool:
        for k, p in zip(key, pattern):
            if p != "*" and k != p:
                return False
        return True

    # ------------------------------------------------------------------
    # S1: Internal — PII redaction
    # ------------------------------------------------------------------

    def _apply_s1(self, event: Dict[str, Any]) -> Dict[str, Any]:
        """Apply PII redaction to event content."""
        try:
            from security.memory_guard import get_memory_guard
            guard = get_memory_guard()
            content = event.get("content", "")
            if content:
                review = guard.review(content, category="tool_result", source="security_filter")
                event["content"] = review.sanitized_text
                event["output"] = guard.review(
                    event.get("output", ""),
                    category="tool_output",
                    source="security_filter",
                ).sanitized_text
        except Exception:
            # Fallback: basic redaction
            event["content"] = self._basic_pii_redact(event.get("content", ""))
            event["output"] = self._basic_pii_redact(event.get("output", ""))
        event["memory_sensitivity"] = "S1"
        return event

    # ------------------------------------------------------------------
    # S2: Confidential — redact + summarize
    # ------------------------------------------------------------------

    def _apply_s2(self, event: Dict[str, Any]) -> Dict[str, Any]:
        """Redact + truncate + mask parameters."""
        # First, apply S1 redaction
        event = self._apply_s1(event)
        event["memory_sensitivity"] = "S2"

        # Truncate content
        content = event.get("content", "")
        if len(content) > S2_MAX_CONTENT_LENGTH:
            event["content"] = content[:S2_MAX_CONTENT_LENGTH] + "…[TRUNCATED]"

        # Truncate output
        output = event.get("output", "")
        if len(output) > S2_MAX_CONTENT_LENGTH:
            event["output"] = output[:S2_MAX_CONTENT_LENGTH] + "…[TRUNCATED]"

        # Mask error signature (may contain sensitive paths/IPs)
        if event.get("error_signature"):
            event["error_signature"] = "[REDACTED_S2]"

        return event

    # ------------------------------------------------------------------
    # Basic fallback redaction (no MemoryGuard dependency)
    # ------------------------------------------------------------------

    @staticmethod
    def _basic_pii_redact(text: str) -> str:
        """Minimal PII redaction when MemoryGuard is unavailable."""
        import re
        if not text:
            return text
        # Email
        text = re.sub(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', '[EMAIL]', text)
        # Chinese phone
        text = re.sub(r'1[3-9]\d{9}', '[PHONE]', text)
        # API keys
        text = re.sub(r'sk-[A-Za-z0-9_-]{20,}', '[API_KEY]', text)
        text = re.sub(r'ghp_[A-Za-z0-9]{20,}', '[TOKEN]', text)
        # IP addresses
        text = re.sub(r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}', '[IP_ADDR]', text)
        return text

    # ------------------------------------------------------------------
    # Tool-specific overrides
    # ------------------------------------------------------------------

    def set_override(self, tool_name: str, sensitivity: Sensitivity) -> None:
        """Set a tool-specific sensitivity override."""
        self._overrides[tool_name] = sensitivity
        logger.info("Security override: %s → %s", tool_name, sensitivity.value)

    def clear_overrides(self) -> None:
        self._overrides.clear()

    @property
    def audit_log(self) -> List[Dict]:
        return list(self._audit_events)


# ============================================================================
# Singleton
# ============================================================================

_security_filter: Optional[MemorySecurityFilter] = None


def get_memory_security_filter() -> MemorySecurityFilter:
    """Get or create the global MemorySecurityFilter singleton."""
    global _security_filter
    if _security_filter is None:
        _security_filter = MemorySecurityFilter()
    return _security_filter


# ============================================================================
# Backward-compatible exports from original security.py
# ============================================================================

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
    """Check if text is safe for memory engine ingestion (backward-compatible).

    Detects invisible Unicode characters and common secret patterns.
    """
    if not text:
        return True
    if set(text) & INVISIBLE_CHARS:
        return False
    return not any(pattern.search(text) for pattern in SECRET_PATTERNS)
