from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any

from .store import MemoryEngineStore


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _stable_id(prefix: str, value: str) -> str:
    return f"{prefix}_{hashlib.sha256(value.encode('utf-8')).hexdigest()[:24]}"


class LineageForgetter:
    VERSION = "forgetting.lineage.v1"

    def __init__(self, store: MemoryEngineStore, mem0_store_obj=None):
        self.store = store
        self.mem0_store_obj = mem0_store_obj

    def forget(self, keyword: str, user_id: str, dry_run: bool = True) -> dict[str, Any]:
        keyword = keyword.strip()
        if not keyword:
            return {"deleted": 0, "candidates": [], "message": "遗忘关键词为空"}
        memories = self.store.search_memories(user_id, keyword)
        candidates = [
            {
                "id": memory.memory_id,
                "text": memory.semantic_value,
                "slot_key": memory.slot_key,
                "status": memory.status,
                "evidence_ids": list(memory.evidence_ids),
                "tier": "MemoryEngine",
            }
            for memory in memories
        ]
        if not candidates:
            return {"deleted": 0, "candidates": [], "message": "未找到匹配的结构化记忆"}
        if dry_run:
            return {
                "deleted": 0,
                "candidates": candidates,
                "message": f"找到 {len(candidates)} 条候选记忆，请确认后删除",
                "version": self.VERSION,
            }

        started = _now()
        request_id = _stable_id("forget", f"{user_id}|{keyword}|{started}")
        request = {
            "request_id": request_id,
            "user_id": user_id,
            "keyword": keyword,
            "memory_ids": [memory.memory_id for memory in memories],
            "status": "blocking",
            "created_at": started,
        }
        self.store.put_forget_request(request)

        deleted = 0
        errors = []
        for memory in memories:
            old_status = memory.status
            blocked = self.store.set_memory_status(memory.memory_id, "blocked", _now())
            if not blocked:
                continue
            self.store.put_lifecycle_event(
                {
                    "event_id": _stable_id("life", f"{memory.memory_id}|blocked|{request_id}"),
                    "memory_id": memory.memory_id,
                    "from_status": old_status,
                    "to_status": "blocked",
                    "reason_code": "forget_request_block",
                    "created_at": _now(),
                }
            )
            self.store.retract_evidence(memory.evidence_ids)
            refs = self.store.get_index_refs(memory.memory_id)
            for ref in refs:
                try:
                    if self.mem0_store_obj is not None and ref["backend"] == "mem0":
                        self.mem0_store_obj._memory.delete(ref["backend_id"])
                except Exception as exc:
                    errors.append({"memory_id": memory.memory_id, "backend_id": ref["backend_id"], "error": str(exc)})
            if errors and any(error["memory_id"] == memory.memory_id for error in errors):
                continue
            self.store.set_index_ref_state(memory.memory_id, "deleted", _now())
            self.store.set_memory_status(memory.memory_id, "deleted", _now())
            self.store.put_lifecycle_event(
                {
                    "event_id": _stable_id("life", f"{memory.memory_id}|deleted|{request_id}"),
                    "memory_id": memory.memory_id,
                    "from_status": "blocked",
                    "to_status": "deleted",
                    "reason_code": "forget_lineage_complete",
                    "created_at": _now(),
                }
            )
            deleted += 1

        request["status"] = "completed" if not errors else "partial"
        request["completed_at"] = _now()
        request["errors"] = errors
        self.store.put_forget_request(request)
        return {
            "deleted": deleted,
            "candidates": candidates,
            "errors": errors,
            "request_id": request_id,
            "version": self.VERSION,
            "message": f"已删除 {deleted} 条结构化记忆",
        }
