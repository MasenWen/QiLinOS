# ============================================================
# ⚠️ 预留组件（2025-08 审计）：未接入主流程，保留供后续启用；勿假设其生效
# ============================================================
from __future__ import annotations

import os
from typing import Any, Mapping


def record_runtime_event(event: Mapping[str, Any]) -> dict[str, Any]:
    """Best-effort hook: observation failures must never block the agent."""
    mode = os.getenv("NEX_MEMORY_OBSERVATION_MODE", "engine_v1").strip().lower()
    if mode in {"off", "disabled", "legacy"}:
        return {"status": "skipped", "reason": "observation_mode_disabled"}
    try:
        from .engine import MemoryEngine

        return MemoryEngine().ingest_event(event)
    except Exception as exc:
        return {
            "status": "error",
            "reason": "observation_hook_failed",
            "error_type": type(exc).__name__,
        }
