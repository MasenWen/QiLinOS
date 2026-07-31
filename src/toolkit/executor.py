"""
Closed-loop executor — the heart of SDK-first tool execution.

Implements the loop::

    execute → verify → OK? → log success → done
                   ↓
                 FAIL? → log warning → retry with fallback?
                            ↓
                          still FAIL? → log ERROR → escalate to agent

The executor handles:
- Up to ``max_retries`` attempts per tool call
- Automatic fallback escalation (SDK → shell → actuator)
- Full audit trail via ``ExecutionTrace``
- Configurable severity thresholds for escalation

Usage::

    from src.toolkit import get_registry, ClosedLoopExecutor

    registry = get_registry()
    registry.register(TimezoneTool())

    executor = ClosedLoopExecutor(registry)
    result = await executor.run("timezone", timezone="Asia/Singapore")
    # → result.status is VERIFIED or FAILED, with full trace
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from .base import BaseTool, ToolResult, ToolStatus, ToolRegistry, RiskLevel

logger = logging.getLogger("toolkit.executor")


# ---------------------------------------------------------------------------
# Severity levels for log escalation
# ---------------------------------------------------------------------------

class Severity(Enum):
    INFO = "info"        # normal operation
    WARN = "warn"        # retry needed, fallback used
    ERROR = "error"      # all retries exhausted, human attention needed
    CRITICAL = "critical"  # safety / security concern


# ---------------------------------------------------------------------------
# ExecutionTrace — full audit trail for a single tool run
# ---------------------------------------------------------------------------

@dataclass
class ExecutionTrace:
    """Complete record of a tool execution with all retries."""
    tool_name: str
    started_at: float = field(default_factory=time.time)
    finished_at: float = 0.0
    attempts: List[ToolResult] = field(default_factory=list)
    final_result: Optional[ToolResult] = None
    rollback_attempted: bool = False
    rollback_success: bool = False
    severity: Severity = Severity.INFO

    @property
    def total_retries(self) -> int:
        return max(0, len(self.attempts) - 1)

    @property
    def total_duration_ms(self) -> float:
        return (self.finished_at - self.started_at) * 1000

    def to_summary(self) -> str:
        """Human-readable summary."""
        lines = [
            f"{'='*50}",
            f"Execution Trace: {self.tool_name}",
            f"  结果: {self.final_result.status.value if self.final_result else 'N/A'}",
            f"  尝试次数: {len(self.attempts)}",
            f"  耗时: {self.total_duration_ms:.0f}ms",
            f"  严重程度: {self.severity.value}",
        ]
        if self.rollback_attempted:
            lines.append(f"  回滚: {'成功' if self.rollback_success else '失败'}")
        lines.append(f"{'='*50}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# ClosedLoopExecutor
# ---------------------------------------------------------------------------

class ClosedLoopExecutor:
    """
    Execute a tool with closed-loop verification and fallback escalation.

    Loop logic::

        for attempt in range(max_retries + 1):
            result = tool.run(**kwargs)
            if result.is_verified:
                → DONE, return success
            if result.ok (but not verified):
                → log WARN, retry (maybe fallback degraded?)
            if result.failed:
                → try rollback, escalate fallback, retry
        → all attempts exhausted: log ERROR, return failure
    """

    def __init__(
        self,
        registry: Optional[ToolRegistry] = None,
        max_retries: int = 2,
        default_timeout: float = 60.0,
    ):
        self.registry = registry
        self.max_retries = max_retries
        self.default_timeout = default_timeout
        self._traces: List[ExecutionTrace] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def run(self, tool_name: str, **kwargs) -> ToolResult:
        """
        Execute a tool by name through the closed loop.

        Parameters
        ----------
        tool_name : str
            Name of the registered tool.
        **kwargs
            Passed to tool.execute() and tool.verify().

        Returns
        -------
        ToolResult
        """
        tool = self._resolve_tool(tool_name)
        if tool is None:
            return ToolResult(
                tool_name=tool_name,
                status=ToolStatus.FAILED,
                error=f"Tool '{tool_name}' not found in registry",
            )

        trace = ExecutionTrace(tool_name=tool_name)

        result: Optional[ToolResult] = None

        for attempt in range(self.max_retries + 1):
            result = tool.run(**kwargs)
            result.retry_count = attempt
            trace.attempts.append(result)

            # --- SUCCESS (verified) ---
            if result.is_verified:
                trace.final_result = result
                trace.finished_at = time.time()
                trace.severity = Severity.INFO
                self._traces.append(trace)
                logger.info(
                    "✓ [%s] 执行成功 (attempt %d/%d, %.0fms, verified)",
                    tool_name, attempt + 1, self.max_retries + 1,
                    result.duration_ms,
                )
                return result

            # --- SUCCESS (not verified) ---
            if result.ok:
                if result.status == ToolStatus.DEGRADED:
                    logger.warning(
                        "⚠ [%s] 降级模式 (attempt %d/%d): %s",
                        tool_name, attempt + 1, self.max_retries + 1,
                        result.output[:150],
                    )
                else:
                    logger.warning(
                        "⚠ [%s] 执行成功但验证未通过 (attempt %d/%d). 重试...",
                        tool_name, attempt + 1, self.max_retries + 1,
                    )
                # Will retry
                await asyncio.sleep(0.5 * (attempt + 1))  # exponential backoff
                continue

            # --- FAILURE ---
            # Try rollback if first failure
            if attempt == 0:
                try:
                    rollback_ok = await asyncio.wait_for(
                        asyncio.to_thread(tool.rollback, **kwargs),
                        timeout=10.0,
                    )
                    trace.rollback_attempted = True
                    trace.rollback_success = rollback_ok
                    if rollback_ok:
                        logger.info("[%s] 回滚成功", tool_name)
                    else:
                        logger.warning("[%s] 回滚失败", tool_name)
                except (asyncio.TimeoutError, Exception) as re:
                    logger.error("[%s] 回滚异常: %s", tool_name, re)

            logger.error(
                "✗ [%s] 执行失败 (attempt %d/%d): %s",
                tool_name, attempt + 1, self.max_retries + 1,
                result.error or result.output[:150],
            )

            if attempt < self.max_retries:
                await asyncio.sleep(1.0 * (attempt + 1))
                logger.info("[%s] 准备重试 (attempt %d)...", tool_name, attempt + 2)

        # All attempts exhausted
        trace.final_result = result or ToolResult(
            tool_name=tool_name,
            status=ToolStatus.FAILED,
            error="所有重试均已耗尽",
        )
        trace.finished_at = time.time()

        # Escalate severity
        if tool.risk == RiskLevel.CONSEQUENTIAL:
            trace.severity = Severity.CRITICAL
        else:
            trace.severity = Severity.ERROR

        self._traces.append(trace)

        logger.error(
            "✗✗✗ [%s] CRITICAL: 所有 %d 次尝试均失败. 最终状态: %s. 请人工介入.",
            tool_name, self.max_retries + 1,
            trace.final_result.status.value,
        )
        return trace.final_result

    async def run_and_confirm(self, tool_name: str, **kwargs) -> ToolResult:
        """
        Same as run(), but also runs verify() one extra time after a delay.

        This is useful for actions that have asynchronous side effects
        (e.g. timezone changes that take a moment to propagate).
        """
        result = await self.run(tool_name, **kwargs)

        if result.is_verified:
            # Double-check after delay
            await asyncio.sleep(2.0)
            tool = self._resolve_tool(tool_name)
            if tool is not None:
                try:
                    confirmed = await asyncio.wait_for(
                        asyncio.to_thread(tool.verify, **kwargs),
                        timeout=10.0,
                    )
                    if confirmed:
                        result.verification = "confirmed (double-check passed)"
                    else:
                        result.verification = "CONFIRMATION FAILED: 第二次验证未通过，状态可能未持久化"
                        logger.error("[%s] %s", tool_name, result.verification)
                except Exception as e:
                    result.verification = f"double-check error: {e}"

        return result

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _resolve_tool(self, tool_name: str) -> Optional[BaseTool]:
        """Find a tool by name from registry or imports."""
        if self.registry is not None:
            tool = self.registry.get(tool_name)
            if tool is not None:
                return tool
        # Last resort: try importing common tool modules
        return None

    @property
    def traces(self) -> List[ExecutionTrace]:
        return list(self._traces)

    def last_trace(self) -> Optional[ExecutionTrace]:
        return self._traces[-1] if self._traces else None

    def clear_traces(self) -> None:
        self._traces.clear()


# ---------------------------------------------------------------------------
# Module-level convenience
# ---------------------------------------------------------------------------

_default_executor: Optional[ClosedLoopExecutor] = None


def get_executor(registry: Optional[ToolRegistry] = None) -> ClosedLoopExecutor:
    global _default_executor
    if _default_executor is None:
        _default_executor = ClosedLoopExecutor(registry=registry)
    return _default_executor
