from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from .models import Evidence, MemoryRecord
from .store import MemoryEngineStore


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _stable_id(prefix: str, value: str) -> str:
    return f"{prefix}_{hashlib.sha256(value.encode('utf-8')).hexdigest()[:24]}"


def apply_evidence(store: MemoryEngineStore, evidence: Evidence) -> tuple[MemoryRecord, dict]:
    existing = store.find_memory(evidence.user_id, evidence.claim_slot, evidence.claim_value)
    now = _now()
    before = existing.to_dict() if existing else {}
    if existing:
        evidence_ids = sorted(set(existing.evidence_ids) | {evidence.evidence_id})
        support_count = len(evidence_ids)
        existing.evidence_ids = evidence_ids
        existing.statistics = {
            **dict(existing.statistics),
            "support_count": support_count,
            "contradict_count": int(existing.statistics.get("contradict_count", 0)),
        }
        existing.confidence = {
            "value": support_count / max(1, support_count + int(existing.statistics["contradict_count"])),
            "method": "independent_support_ratio.v1",
        }
        existing.stability = {
            "value": min(1.0, 0.35 + 0.25 * max(0, support_count - 1)),
            "method": "support_count_baseline.v1",
        }
        existing.status = "stable" if support_count >= 2 else "candidate"
        existing.version += 1
        existing.updated_at = now
        memory = existing
        action = "SUPPORT"
        reason = "matching_slot_and_value"
    else:
        competing = [
            candidate
            for candidate in store.list_slot_memories(evidence.user_id, evidence.claim_slot)
            if candidate.semantic_value != evidence.claim_value
            and candidate.status not in {"historical", "archive", "deleted", "blocked"}
        ]
        memory_id = _stable_id(
            "mem",
            f"{evidence.user_id}|{evidence.claim_slot}|{evidence.condition}|{evidence.claim_value}",
        )
        memory = MemoryRecord(
            memory_id=memory_id,
            user_id=evidence.user_id,
            memory_family=evidence.memory_family,
            memory_type=evidence.memory_type,
            memory_category=evidence.memory_category,
            status="candidate",
            slot_key=evidence.claim_slot,
            semantic_value=evidence.claim_value,
            evidence_ids=[evidence.evidence_id],
            condition=evidence.condition,
            scope={"user_id": evidence.user_id},
            statistics={"support_count": 1, "contradict_count": 0},
            confidence={"value": 1.0, "method": "independent_support_ratio.v1"},
            stability={"value": 0.35, "method": "support_count_baseline.v1"},
            provenance={"extractor": evidence.extractor},
            created_at=now,
            updated_at=now,
        )
        action = "CREATE"
        reason = "no_matching_memory"

    store.put_memory(memory)
    if not existing and competing:
        memory_ids = [memory.memory_id]
        conditional = bool(evidence.condition)
        for previous in competing:
            memory_ids.append(previous.memory_id)
            if not conditional:
                old_status = previous.status
                previous.status = "historical"
                previous.version += 1
                previous.updated_at = now
                store.put_memory(previous)
                store.put_lifecycle_event(
                    {
                        "event_id": _stable_id("life", f"{previous.memory_id}|historical|{evidence.evidence_id}"),
                        "memory_id": previous.memory_id,
                        "from_status": old_status,
                        "to_status": "historical",
                        "reason_code": "dynamic_conflict_superseded",
                        "created_at": now,
                    }
                )
        group_id = _stable_id("conflict", f"{evidence.user_id}|{evidence.claim_slot}")
        store.put_conflict_group(
            {
                "conflict_group_id": group_id,
                "slot_key": evidence.claim_slot,
                "conflict_type": "conditional" if conditional else "dynamic",
                "memory_ids": sorted(set(memory_ids)),
                "winner_memory_id": memory.memory_id if not conditional else None,
                "status": "resolved" if not conditional else "partitioned",
                "updated_at": now,
            }
        )
    impact = {
        "impact_id": _stable_id("impact", f"{evidence.evidence_id}|{memory.memory_id}|{action}"),
        "evidence_id": evidence.evidence_id,
        "target_memory_id": memory.memory_id,
        "action": action,
        "reason_code": reason,
        "before_snapshot": before,
        "after_snapshot": memory.to_dict(),
        "created_at": now,
    }
    store.put_impact(impact)
    return memory, impact
