from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timezone
from typing import Iterable, Mapping
from uuid import NAMESPACE_URL, uuid5

from .contracts import (
    ConditionRelation,
    ImpactAction,
    LifecycleStatus,
    MemoryCandidate,
    StrictImpact,
    StrictMemory,
)
from .conflict import condition_relation


class SlotImpactMemoryUpdater:
    module_id = "memory_update.slot_impact_rule.v1"

    def __init__(self, config: Mapping[str, object] | None = None):
        values = dict(config or {})
        self.behavior_dynamic_min_support = int(
            values.get("behavior_dynamic_min_support", 3)
        )

    def apply(
        self,
        candidates: Iterable[MemoryCandidate],
        memories: Iterable[StrictMemory],
        *,
        now: str | None = None,
    ) -> tuple[list[StrictImpact], list[StrictMemory]]:
        timestamp = now or datetime.now(timezone.utc).isoformat()
        state = {memory.memory_id: memory for memory in memories}
        impacts: list[StrictImpact] = []
        for candidate in sorted(
            candidates,
            key=lambda item: (
                str(item.signals.get("observed_time") or item.valid_from),
                item.candidate_id,
            ),
        ):
            candidate_impacts, changes = self._apply_one(
                candidate,
                state,
                timestamp,
            )
            impacts.extend(candidate_impacts)
            state.update({memory.memory_id: memory for memory in changes})
        return impacts, list(state.values())

    def _apply_one(
        self,
        candidate: MemoryCandidate,
        state: dict[str, StrictMemory],
        timestamp: str,
    ) -> tuple[list[StrictImpact], list[StrictMemory]]:
        slot_memories = [
            memory
            for memory in state.values()
            if memory.user_id == candidate.user_id
            and memory.slot_key == candidate.slot_key
            and memory.status
            not in {LifecycleStatus.BLOCKED, LifecycleStatus.DELETED}
        ]
        exact = next(
            (
                memory
                for memory in slot_memories
                if memory.semantic_value == candidate.semantic_value
                and condition_relation(memory.condition, candidate.condition)
                is ConditionRelation.EQUAL
            ),
            None,
        )
        if exact is not None:
            impacts, changes = self._update_exact(
                candidate,
                exact,
                timestamp,
            )
            return self._apply_behavior_drift(
                candidate,
                state,
                impacts,
                changes,
                timestamp,
            )

        if candidate.polarity == "oppose":
            target = next(
                (
                    memory
                    for memory in slot_memories
                    if memory.semantic_value == candidate.semantic_value
                ),
                None,
            )
            if target is None:
                return [
                    _impact(
                        candidate,
                        target_memory_id="unresolved:" + candidate.slot_key,
                        action=ImpactAction.UNRESOLVED,
                        reason="opposition_without_matching_memory",
                        before={},
                        after={},
                        timestamp=timestamp,
                    )
                ], []
            return self._update_exact(candidate, target, timestamp)

        created = _new_memory(candidate, timestamp)
        impacts = [
            _impact(
                candidate,
                target_memory_id=created.memory_id,
                action=ImpactAction.CREATE,
                reason="no_equivalent_memory",
                before={},
                after=created.to_dict(),
                timestamp=timestamp,
            )
        ]
        changes = [created]
        for existing in slot_memories:
            relation = condition_relation(
                existing.condition,
                candidate.condition,
            )
            if relation is ConditionRelation.DISJOINT:
                impacts.append(
                    _impact(
                        candidate,
                        target_memory_id=existing.memory_id,
                        action=ImpactAction.SPECIALIZE,
                        reason="disjoint_condition_partition",
                        before=existing.to_dict(),
                        after=existing.to_dict(),
                        timestamp=timestamp,
                    )
                )
                continue
            if candidate.cardinality == "multi" or existing.cardinality == "multi":
                impacts.append(
                    _impact(
                        candidate,
                        target_memory_id=existing.memory_id,
                        action=ImpactAction.NOOP,
                        reason="multi_cardinality_coexistence",
                        before=existing.to_dict(),
                        after=existing.to_dict(),
                        timestamp=timestamp,
                    )
                )
                continue
            if _strong_dynamic(candidate):
                historical = replace(
                    existing,
                    status=LifecycleStatus.HISTORICAL,
                    valid_to=candidate.valid_from or timestamp,
                    successor_memory_ids=_append_unique(
                        existing.successor_memory_ids,
                        created.memory_id,
                    ),
                    applicable_unit_ids=_append_unique(
                        existing.applicable_unit_ids,
                        candidate.independent_unit_id,
                    ),
                    version=existing.version + 1,
                    updated_at=timestamp,
                )
                created = replace(
                    created,
                    predecessor_memory_ids=_append_unique(
                        created.predecessor_memory_ids,
                        existing.memory_id,
                    ),
                    provenance={
                        **created.provenance,
                        "dynamic_successor": True,
                    },
                )
                changes[0] = created
                changes.append(historical)
                impacts.append(
                    _impact(
                        candidate,
                        target_memory_id=existing.memory_id,
                        action=ImpactAction.SUPERSEDE,
                        reason="explicit_time_or_version_signal",
                        before=existing.to_dict(),
                        after=historical.to_dict(),
                        timestamp=timestamp,
                    )
                )
            else:
                contradicted = replace(
                    existing,
                    applicable_unit_ids=_append_unique(
                        existing.applicable_unit_ids,
                        candidate.independent_unit_id,
                    ),
                    version=existing.version + 1,
                    updated_at=timestamp,
                )
                changes.append(contradicted)
                impacts.append(
                    _impact(
                        candidate,
                        target_memory_id=existing.memory_id,
                        action=ImpactAction.CONTRADICT,
                        reason="incompatible_value_overlapping_condition",
                        before=existing.to_dict(),
                        after=contradicted.to_dict(),
                        timestamp=timestamp,
                    )
                )
        return impacts, changes

    def _apply_behavior_drift(
        self,
        candidate: MemoryCandidate,
        state: dict[str, StrictMemory],
        impacts: list[StrictImpact],
        changes: list[StrictMemory],
        timestamp: str,
    ) -> tuple[list[StrictImpact], list[StrictMemory]]:
        if (
            candidate.signals.get("evidence_type") != "observed_behavior"
            or candidate.cardinality != "single"
        ):
            return impacts, changes
        updated = next(
            (
                memory
                for memory in changes
                if memory.slot_key == candidate.slot_key
                and memory.semantic_value == candidate.semantic_value
                and condition_relation(
                    memory.condition,
                    candidate.condition,
                )
                is ConditionRelation.EQUAL
            ),
            None,
        )
        if (
            updated is None
            or len(updated.support_unit_ids)
            < self.behavior_dynamic_min_support
        ):
            return impacts, changes
        updated_times = _observed_times(updated)
        if not updated_times:
            return impacts, changes
        new_window_start = min(updated_times)
        change_by_id = {memory.memory_id: memory for memory in changes}
        for existing in state.values():
            if (
                existing.memory_id == updated.memory_id
                or existing.user_id != candidate.user_id
                or existing.slot_key != candidate.slot_key
                or existing.semantic_value == candidate.semantic_value
                or existing.cardinality != "single"
                or existing.status
                in {
                    LifecycleStatus.HISTORICAL,
                    LifecycleStatus.BLOCKED,
                    LifecycleStatus.DELETED,
                    LifecycleStatus.ARCHIVE,
                }
                or condition_relation(
                    existing.condition,
                    candidate.condition,
                )
                is not ConditionRelation.EQUAL
            ):
                continue
            existing_times = _observed_times(existing)
            if (
                not existing_times
                or max(existing_times) >= new_window_start
            ):
                continue
            historical = replace(
                existing,
                status=LifecycleStatus.HISTORICAL,
                valid_to=updated.valid_from,
                successor_memory_ids=_append_unique(
                    existing.successor_memory_ids,
                    updated.memory_id,
                ),
                version=existing.version + 1,
                updated_at=timestamp,
            )
            updated = replace(
                updated,
                predecessor_memory_ids=_append_unique(
                    updated.predecessor_memory_ids,
                    existing.memory_id,
                ),
                provenance={
                    **updated.provenance,
                    "dynamic_successor": True,
                    "dynamic_reason": "recent_window_behavior_drift",
                    "dynamic_min_support": (
                        self.behavior_dynamic_min_support
                    ),
                    "dynamic_window_start": new_window_start.isoformat(),
                },
                version=updated.version + 1,
                updated_at=timestamp,
            )
            change_by_id[updated.memory_id] = updated
            change_by_id[historical.memory_id] = historical
            impacts.append(
                _impact(
                    candidate,
                    target_memory_id=existing.memory_id,
                    action=ImpactAction.SUPERSEDE,
                    reason="recent_window_behavior_drift",
                    before=existing.to_dict(),
                    after=historical.to_dict(),
                    timestamp=timestamp,
                )
            )
        return impacts, list(change_by_id.values())

    def _update_exact(
        self,
        candidate: MemoryCandidate,
        memory: StrictMemory,
        timestamp: str,
    ) -> tuple[list[StrictImpact], list[StrictMemory]]:
        supporting = candidate.polarity != "oppose"
        units = (
            memory.support_unit_ids if supporting else memory.oppose_unit_ids
        )
        if candidate.independent_unit_id in units:
            return [
                _impact(
                    candidate,
                    target_memory_id=memory.memory_id,
                    action=ImpactAction.NOOP,
                    reason="independent_unit_already_counted",
                    before=memory.to_dict(),
                    after=memory.to_dict(),
                    timestamp=timestamp,
                )
            ], []

        updated = replace(
            memory,
            evidence_ids=_append_unique(memory.evidence_ids, candidate.evidence_id),
            support_unit_ids=(
                _append_unique(
                    memory.support_unit_ids,
                    candidate.independent_unit_id,
                )
                if supporting
                else memory.support_unit_ids
            ),
            oppose_unit_ids=(
                memory.oppose_unit_ids
                if supporting
                else _append_unique(
                    memory.oppose_unit_ids,
                    candidate.independent_unit_id,
                )
            ),
            applicable_unit_ids=_append_unique(
                memory.applicable_unit_ids,
                candidate.independent_unit_id,
            ),
            provenance={
                **memory.provenance,
                "latest_candidate_id": candidate.candidate_id,
                "latest_signal": dict(candidate.signals),
                "candidate_ids": list(
                    dict.fromkeys(
                        list(memory.provenance.get("candidate_ids") or [])
                        + [candidate.candidate_id]
                    )
                ),
                "observed_times": list(
                    dict.fromkeys(
                        list(memory.provenance.get("observed_times") or [])
                        + [candidate.signals.get("observed_time")]
                    )
                ),
                "preference_inference_forbidden": bool(
                    memory.provenance.get("preference_inference_forbidden")
                    or candidate.signals.get(
                        "preference_inference_forbidden"
                    )
                ),
            },
            version=memory.version + 1,
            updated_at=timestamp,
        )
        action = ImpactAction.SUPPORT if supporting else ImpactAction.CONTRADICT
        return [
            _impact(
                candidate,
                target_memory_id=memory.memory_id,
                action=action,
                reason=(
                    "new_independent_support"
                    if supporting
                    else "new_independent_opposition"
                ),
                before=memory.to_dict(),
                after=updated.to_dict(),
                timestamp=timestamp,
            )
        ], [updated]


def _new_memory(candidate: MemoryCandidate, timestamp: str) -> StrictMemory:
    condition_key = json.dumps(
        candidate.condition,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    identity = (
        f"{candidate.user_id}|{candidate.slot_key}|"
        f"{candidate.semantic_value}|{condition_key}"
    )
    memory_id = "smem-" + uuid5(NAMESPACE_URL, identity).hex
    return StrictMemory(
        memory_id=memory_id,
        user_id=candidate.user_id,
        memory_family=candidate.memory_family,
        candidate_kind=candidate.candidate_kind,
        slot_key=candidate.slot_key,
        semantic_value=candidate.semantic_value,
        condition=dict(candidate.condition),
        scope={"user_id": candidate.user_id},
        cardinality=candidate.cardinality,
        status=LifecycleStatus.CANDIDATE,
        evidence_ids=(candidate.evidence_id,),
        support_unit_ids=(candidate.independent_unit_id,),
        oppose_unit_ids=(),
        applicable_unit_ids=(candidate.independent_unit_id,),
        valid_from=candidate.valid_from,
        valid_to=candidate.valid_to,
        predecessor_memory_ids=(),
        successor_memory_ids=(),
        conflict_group_ids=(),
        confidence={},
        stability={},
        provenance={
            "candidate_ids": [candidate.candidate_id],
            "source_module_id": candidate.source_module_id,
            "directness": candidate.signals.get("directness"),
            "config_version": candidate.signals.get("config_version"),
            "explicit_temporal": candidate.signals.get("explicit_temporal"),
            "observed_times": [candidate.signals.get("observed_time")],
            "fallback": candidate.signals.get("fallback"),
            "preference_inference_forbidden": candidate.signals.get(
                "preference_inference_forbidden"
            ),
        },
        version=1,
        created_at=timestamp,
        updated_at=timestamp,
    )


def _strong_dynamic(candidate: MemoryCandidate) -> bool:
    if candidate.signals.get("fallback"):
        return False
    return bool(
        candidate.signals.get("explicit_temporal")
        or candidate.signals.get("config_version") not in (None, "")
    )


def _impact(
    candidate: MemoryCandidate,
    *,
    target_memory_id: str,
    action: ImpactAction,
    reason: str,
    before: Mapping[str, object],
    after: Mapping[str, object],
    timestamp: str,
) -> StrictImpact:
    identity = (
        f"{candidate.candidate_id}|{target_memory_id}|{action.value}|{reason}"
    )
    return StrictImpact(
        impact_id="impact-" + uuid5(NAMESPACE_URL, identity).hex,
        candidate_id=candidate.candidate_id,
        evidence_id=candidate.evidence_id,
        target_memory_id=target_memory_id,
        action=action,
        reason_code=reason,
        before_snapshot=dict(before),
        after_snapshot=dict(after),
        created_at=timestamp,
    )


def _append_unique(values: tuple[str, ...], value: str) -> tuple[str, ...]:
    return values if value in values else values + (value,)


def _observed_times(memory: StrictMemory) -> list[datetime]:
    result: list[datetime] = []
    for value in memory.provenance.get("observed_times") or ():
        if value in (None, ""):
            continue
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        result.append(parsed)
    return result
