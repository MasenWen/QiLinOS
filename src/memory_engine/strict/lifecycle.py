from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping
from uuid import NAMESPACE_URL, uuid5

from .contracts import (
    LifecycleStatus,
    StrictLifecycleEvent,
    StrictMemory,
)


class StabilityThresholdLifecycle:
    module_id = "lifecycle.stability_thresholds.v1"

    def __init__(self, config: Mapping[str, Any]):
        self.promote = float(config["promote_threshold"])
        self.demote = float(config["demote_threshold"])
        self.archive = float(config["archive_threshold"])
        self.recover = float(config["recover_threshold"])

    def apply(
        self,
        memories: Iterable[StrictMemory],
        *,
        now: str | None = None,
    ) -> tuple[list[StrictMemory], list[StrictLifecycleEvent]]:
        timestamp = now or datetime.now(timezone.utc).isoformat()
        updated: list[StrictMemory] = []
        events: list[StrictLifecycleEvent] = []
        for memory in memories:
            target, reason = self._transition(memory)
            if target is memory.status:
                updated.append(memory)
                continue
            changed = replace(
                memory,
                status=target,
                version=memory.version + 1,
                updated_at=timestamp,
            )
            updated.append(changed)
            identity = (
                f"{memory.memory_id}|{memory.status.value}|"
                f"{target.value}|{memory.version + 1}"
            )
            events.append(
                StrictLifecycleEvent(
                    event_id="lifecycle-" + uuid5(NAMESPACE_URL, identity).hex,
                    memory_id=memory.memory_id,
                    from_status=memory.status,
                    to_status=target,
                    reason_code=reason,
                    created_at=timestamp,
                )
            )
        return updated, events

    def _transition(
        self,
        memory: StrictMemory,
    ) -> tuple[LifecycleStatus, str]:
        if memory.status in {
            LifecycleStatus.HISTORICAL,
            LifecycleStatus.BLOCKED,
            LifecycleStatus.DELETED,
        }:
            return memory.status, "hard_exception"
        value = float(memory.stability.get("value", 0.0))
        archive_eligible = bool(
            memory.stability.get("eligible_for_archive")
        )
        if memory.status is LifecycleStatus.CANDIDATE:
            if value >= self.promote:
                return LifecycleStatus.STABLE, "stability_promote"
            if archive_eligible and value < self.archive:
                return LifecycleStatus.ARCHIVE, "stability_archive"
        elif memory.status is LifecycleStatus.STABLE:
            if archive_eligible and value < self.archive:
                return LifecycleStatus.ARCHIVE, "stability_archive"
            if value < self.demote:
                return LifecycleStatus.CANDIDATE, "stability_demote"
        elif memory.status is LifecycleStatus.ARCHIVE:
            if value >= self.recover:
                return LifecycleStatus.RECOVER, "new_support_recover"
        elif memory.status is LifecycleStatus.RECOVER:
            if value >= self.promote:
                return LifecycleStatus.STABLE, "recover_promote"
            return LifecycleStatus.CANDIDATE, "recover_recheck"
        return memory.status, "no_transition"
