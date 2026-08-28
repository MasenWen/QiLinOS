"""Strict MemoryEngine implementation derived from the formal design.

This package is deliberately independent from ``src.memory_engine`` baseline
internals. Compatibility and experiment routing belong outside this package.
"""

# ============================================================
# ⚠️ 预留组件（2025-08 审计）：未接入主流程，保留供后续启用；勿假设其生效
# ============================================================
from .config import StrictMemoryEngineConfig
from .engine import StrictMemoryEngine
from .errors import (
    IdempotencyConflictError,
    StrictConfigurationError,
    StrictMemoryEngineError,
    StrictStageUnavailableError,
)

__all__ = [
    "IdempotencyConflictError",
    "StrictConfigurationError",
    "StrictMemoryEngine",
    "StrictMemoryEngineConfig",
    "StrictMemoryEngineError",
    "StrictStageUnavailableError",
]
