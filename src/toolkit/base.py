"""
Kylin ToolKit — Base abstractions for SDK-first tool execution.

Patterns borrowed from OpenWorker's tool registry + permission engine:
- Every tool has a ``RiskLevel`` (LOW / MEDIUM / CONSEQUENTIAL)
- ``ToolRegistry`` is a central singleton for discovery
- ``ToolResult`` is a typed, loggable outcome carrying full audit info
- ``BaseTool.run()`` runs execute → verify in one shot
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, Optional, List
from abc import ABC, abstractmethod
import logging
import time


# ---------------------------------------------------------------------------
# Risk / Status enums
# ---------------------------------------------------------------------------

class RiskLevel(Enum):
    """OpenWorker-style risk classification."""
    LOW = "low"                      # read-only (system info, status queries)
    MEDIUM = "medium"                # reversible (volume, brightness, wallpaper)
    CONSEQUENTIAL = "consequential"  # irreversible / dangerous (reboot, timezone change)


class ToolStatus(Enum):
    SUCCESS = "success"              # execute() returned ok, no verify
    FAILED = "failed"                # execute() returned error
    VERIFIED = "verified"            # execute() ok AND verify() confirmed
    DEGRADED = "degraded"            # SDK unavailable, fallback used
    TIMEOUT = "timeout"             # execution exceeded timeout
    REJECTED = "rejected"            # safety check or permission denied


# ---------------------------------------------------------------------------
# ToolResult
# ---------------------------------------------------------------------------

@dataclass
class ToolResult:
    """
    Every tool call returns this typed, self-documenting result.

    Contains everything needed for logging, auditing, and agent decision-making.
    """
    tool_name: str
    status: ToolStatus
    output: str = ""
    error: Optional[str] = None
    verification: Optional[str] = None       # what verify() found
    fallback_used: bool = False               # True if SDK failed, shell used
    duration_ms: float = 0.0
    retry_count: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        """True if the operation succeeded at any level."""
        return self.status in (
            ToolStatus.SUCCESS, ToolStatus.VERIFIED, ToolStatus.DEGRADED,
        )

    @property
    def is_verified(self) -> bool:
        """True only if verify() confirmed the result."""
        return self.status == ToolStatus.VERIFIED

    @property
    def needs_attention(self) -> bool:
        """True if a human should look — failed, degraded, or unverified."""
        return self.status in (
            ToolStatus.FAILED, ToolStatus.DEGRADED, ToolStatus.TIMEOUT,
        )

    def to_log(self) -> str:
        """One-line structured log for greppable audit trails."""
        parts = [
            f"[{self.tool_name}]",
            f"status={self.status.value}",
            f"dur={self.duration_ms:.0f}ms",
        ]
        if self.retry_count:
            parts.append(f"retries={self.retry_count}")
        if self.fallback_used:
            parts.append("via=fallback")
        if self.verification:
            parts.append(f"verify=({self.verification[:80]})")
        if self.error:
            parts.append(f"err=({self.error[:120]})")
        return " | ".join(parts)

    def to_agent_summary(self) -> str:
        """Human-readable summary for agent consumption."""
        if self.is_verified:
            return f"✓ {self.tool_name}: {self.output[:200]} [已确认]"
        if self.status == ToolStatus.DEGRADED:
            return f"⚠ {self.tool_name}: {self.output[:200]} [降级模式]"
        if self.ok:
            return f"✓ {self.tool_name}: {self.output[:200]}"
        return f"✗ {self.tool_name} 失败: {self.error or '未知错误'}"


# ---------------------------------------------------------------------------
# BaseTool
# ---------------------------------------------------------------------------

class BaseTool(ABC):
    """
    Abstract tool — SDK-first, shell-fallback, with built-in verify + rollback.

    Subclasses MUST implement ``execute()``.
    Override ``verify()`` and ``rollback()`` when the action has observable side effects.

    Pattern::

        class VolumeTool(BaseTool):
            name = "volume"
            risk = RiskLevel.MEDIUM

            def execute(self, **kwargs):
                # Try SDK first
                if sdk_available():
                    return self._ok("音量已设置")
                # Fallback to shell
                return self._fallback("amixer set Master 50%")

            def verify(self, **kwargs):
                # Check actual volume level
                current = get_current_volume()
                return abs(current - target) < 5
    """

    # --- Subclass must set these ---
    name: str = "base_tool"
    description: str = ""
    risk: RiskLevel = RiskLevel.MEDIUM
    requires_approval: bool = False
    timeout_s: float = 30.0

    def __init__(self):
        self.logger = logging.getLogger(f"toolkit.{self.name}")
        self._last_result: Optional[ToolResult] = None

    # ---- Abstract / overridable ----

    @abstractmethod
    def execute(self, **kwargs) -> ToolResult:
        """
        Perform the action.  **SDK-first, shell-fallback.**

        Must return a ToolResult.  Use the helpers:

        - ``self._ok(output)`` → ToolResult(SUCCESS)
        - ``self._fallback(output)`` → ToolResult(DEGRADED)
        - ``self._fail(error)`` → ToolResult(FAILED)
        """
        ...

    def verify(self, **kwargs) -> bool:
        """
        Confirm the action had the expected effect.

        Returns True if the post-condition holds.
        Default: optimistic (returns True) — override for stateful tools.
        """
        return True

    def rollback(self, **kwargs) -> bool:
        """
        Undo the action on failure.

        Returns True if rollback succeeded.
        Default: no-op — override for reversible tools.
        """
        return False

    # ---- Helpers for subclasses ----

    def _ok(self, output: str, **meta) -> ToolResult:
        return ToolResult(
            tool_name=self.name,
            status=ToolStatus.SUCCESS,
            output=output,
            metadata=meta,
        )

    def _fail(self, error: str, output: str = "", **meta) -> ToolResult:
        return ToolResult(
            tool_name=self.name,
            status=ToolStatus.FAILED,
            error=error,
            output=output,
            metadata=meta,
        )

    def _fallback(self, output: str, **meta) -> ToolResult:
        return ToolResult(
            tool_name=self.name,
            status=ToolStatus.DEGRADED,
            output=output,
            fallback_used=True,
            metadata=meta,
        )

    def _rejected(self, reason: str) -> ToolResult:
        return ToolResult(
            tool_name=self.name,
            status=ToolStatus.REJECTED,
            error=reason,
        )

    # ---- Single-shot runner (no retries) ----

    def run(self, **kwargs) -> ToolResult:
        """
        execute() → verify() in one call.

        Does NOT retry — use ``ClosedLoopExecutor`` for that.
        """
        t0 = time.time()

        # 1. Execute
        try:
            result = self.execute(**kwargs)
        except Exception as e:
            elapsed = (time.time() - t0) * 1000
            self.logger.error("[%s] execute crashed: %s", self.name, e, exc_info=True)
            result = ToolResult(
                tool_name=self.name,
                status=ToolStatus.FAILED,
                error=f"{type(e).__name__}: {e}",
                duration_ms=elapsed,
            )
            self._last_result = result
            return result

        result.duration_ms = (time.time() - t0) * 1000

        # 2. Verify (only if execute succeeded)
        if result.ok:
            try:
                verified = self.verify(**kwargs)
                if verified:
                    result.status = ToolStatus.VERIFIED
                    result.verification = "confirmed"
                else:
                    result.verification = "MISMATCH: action reported success but post-condition check failed"
                    self.logger.warning(
                        "[%s] verification FAILED — action claimed success but state doesn't match",
                        self.name,
                    )
            except Exception as ve:
                result.verification = f"verify error: {ve}"
                self.logger.error("[%s] verify() crashed: %s", self.name, ve)

        # 3. Log
        self.logger.info(result.to_log())
        self._last_result = result
        return result


# ---------------------------------------------------------------------------
# ToolRegistry — OpenWorker-style central registry
# ---------------------------------------------------------------------------

class ToolRegistry:
    """
    Central registry for all tools in the system.

    Follows OpenWorker's ToolRegistry pattern:
    - Tools are registered by name
    - Risk-level indexing for permission gating
    - Agent-callable tools filtered by max risk level
    """

    def __init__(self):
        self._tools: Dict[str, BaseTool] = {}
        self._by_risk: Dict[RiskLevel, List[str]] = {
            RiskLevel.LOW: [],
            RiskLevel.MEDIUM: [],
            RiskLevel.CONSEQUENTIAL: [],
        }

    def register(self, tool: BaseTool) -> None:
        """Register a tool.  Replaces any existing tool with the same name."""
        self._tools[tool.name] = tool
        self._by_risk[tool.risk].append(tool.name)
        logging.getLogger("toolkit").info(
            "Registered tool: %s (risk=%s)", tool.name, tool.risk.value
        )

    def register_many(self, tools: List[BaseTool]) -> None:
        for t in tools:
            self.register(t)

    def get(self, name: str) -> Optional[BaseTool]:
        return self._tools.get(name)

    def list_all(self) -> List[str]:
        return sorted(self._tools.keys())

    def list_by_risk(self, risk: RiskLevel) -> List[str]:
        return self._by_risk.get(risk, [])

    def get_tools_for_agent(
        self, max_risk: RiskLevel = RiskLevel.MEDIUM
    ) -> List[BaseTool]:
        """
        Return tools safe for agent auto-use.

        Risk ordering: LOW < MEDIUM < CONSEQUENTIAL.
        Tools up to ``max_risk`` are included.
        """
        risk_order = [RiskLevel.LOW, RiskLevel.MEDIUM, RiskLevel.CONSEQUENTIAL]
        allowed_names: set = set()
        for r in risk_order:
            allowed_names.update(self._by_risk.get(r, []))
            if r == max_risk:
                break
        return [self._tools[n] for n in sorted(allowed_names) if n in self._tools]

    def describe_for_agent(self, max_risk: RiskLevel = RiskLevel.MEDIUM) -> str:
        """Return a markdown list of tools for agent system prompts."""
        lines = []
        for tool in self.get_tools_for_agent(max_risk):
            risk_icon = {"low": "📖", "medium": "🔧", "consequential": "⚠️"}[tool.risk.value]
            lines.append(f"- **{tool.name}** {risk_icon}: {tool.description}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Global singleton
# ---------------------------------------------------------------------------

_registry: Optional[ToolRegistry] = None


def get_registry() -> ToolRegistry:
    """Return the global ToolRegistry singleton."""
    global _registry
    if _registry is None:
        _registry = ToolRegistry()
    return _registry
