"""四层记忆生命周期自动流转（参考 strict lifecycle 状态机，2026-08-29）。

strict 的 lifecycle 思想：CANDIDATE → STABLE（支持度达标）→ ARCHIVE（超龄/低强度）
→ RECOVER（新证据恢复）。现有四层记忆只有被动降级（competing→historical、
遗忘→deleted），缺自动老化归档——长期不用的弱记忆永远占着候选位。

本模块实现四层 memories 的定时流转（阈值可 env 配置）：
  - candidate: stability.value >= NEX_LC_PROMOTE(0.6) → stable
  - stable: 超龄（updated_at 距今 > NEX_LC_ARCHIVE_DAYS=30）→ archive
  - stable: stability.value < NEX_LC_DEMOTE(0.3) → candidate（降级）
  - archive: 不主动恢复（新证据由 apply_evidence 恢复为 candidate）

注意：archive 状态的记忆读侧仲裁将过滤（与 strict hard_filter 一致），
即「老化归档 = 不再注入对话」（遗忘曲线之外的第二道弱化机制）。
"""
from __future__ import annotations

import os
import threading
from datetime import datetime, timezone

from .store import MemoryEngineStore

PROMOTE = float(os.getenv("NEX_LC_PROMOTE", "0.6"))
DEMOTE = float(os.getenv("NEX_LC_DEMOTE", "0.3"))
ARCHIVE_DAYS = int(os.getenv("NEX_LC_ARCHIVE_DAYS", "30"))
INTERVAL_SEC = int(os.getenv("NEX_LC_INTERVAL", "3600"))  # 1 小时

_lock = threading.Lock()
_last_run = 0.0


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _age_days(iso_str: str, now: datetime) -> int:
    try:
        dt = datetime.fromisoformat(str(iso_str))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return max(0, int((now - dt).total_seconds() // 86400))
    except Exception:
        return 0


def run_lifecycle(store: MemoryEngineStore | None = None,
                  user_id: str = "nex_user") -> list[dict]:
    """执行一次生命周期流转，返回事件列表（只处理 active 记忆）。"""
    store = store or MemoryEngineStore()
    now = datetime.now(timezone.utc)
    events: list[dict] = []
    try:
        memories = store.list_memories(user_id) or []
    except Exception:
        return events
    for m in memories:
        status = str(getattr(m, "status", "") or "")
        if status in ("deleted", "blocked", "archive"):
            continue
        stability = float((getattr(m, "stability", None) or {}).get("value", 0.0))
        target = ""
        reason = ""
        if status == "candidate":
            if stability >= PROMOTE:
                target, reason = "stable", f"stability_promote({stability:.2f})"
        elif status == "stable":
            age = _age_days(getattr(m, "updated_at", "") or "", now)
            if age >= ARCHIVE_DAYS:
                target, reason = "archive", f"age_archive({age}d)"
            elif stability < DEMOTE:
                target, reason = "candidate", f"stability_demote({stability:.2f})"
        if target:
            try:
                store.set_memory_status(m.memory_id, target, _now_iso())
                events.append({
                    "memory_id": m.memory_id,
                    "text": str(m.semantic_value)[:40],
                    "from": status,
                    "to": target,
                    "reason": reason,
                })
            except Exception:
                pass
    return events


def maybe_run(store: MemoryEngineStore | None = None) -> list[dict]:
    """节流触发（INTERVAL_SEC 内不重复执行）。"""
    global _last_run
    import time
    now = time.time()
    with _lock:
        if now - _last_run < INTERVAL_SEC:
            return []
        _last_run = now
    return run_lifecycle(store)
