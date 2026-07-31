"""
Kylin ToolKit — SDK-first tool abstraction layer.

Inspired by OpenWorker's tool registry + permission engine pattern.
Every system operation is wrapped as a Tool with:
- execute(): perform the action (SDK-first, shell-fallback)
- verify(): confirm the action had the expected effect
- rollback(): undo on failure (when possible)
- ClosedLoopExecutor: retry with escalating fallback

Usage::

    from src.toolkit import get_registry, ClosedLoopExecutor
    from src.toolkit.system_tools import TimezoneTool

    registry = get_registry()
    registry.register(TimezoneTool())

    executor = ClosedLoopExecutor(registry)
    result = await executor.run("timezone", timezone="Asia/Singapore")
    if result.ok:
        print(f"✓ {result.verification}")
    else:
        print(f"✗ {result.error}")
"""

from .base import (
    BaseTool,
    ToolResult,
    ToolStatus,
    ToolRegistry,
    RiskLevel,
    get_registry,
)
from .executor import ClosedLoopExecutor

__all__ = [
    "BaseTool",
    "ToolResult",
    "ToolStatus",
    "ToolRegistry",
    "RiskLevel",
    "get_registry",
    "ClosedLoopExecutor",
]
