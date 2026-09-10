from __future__ import annotations

import json
import re
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any, Mapping
from uuid import NAMESPACE_URL, uuid5

from .contracts import (
    ConditionRelation,
    ConflictType,
    LifecycleStatus,
    StrictConflictGroup,
    StrictMemory,
)


def condition_relation(
    left: Mapping[str, Any],
    right: Mapping[str, Any],
) -> ConditionRelation:
    left_items = _condition_items(left)
    right_items = _condition_items(right)
    if left_items == right_items:
        return ConditionRelation.EQUAL
    if not left_items and right_items:
        return ConditionRelation.SUPERSET
    if left_items and not right_items:
        return ConditionRelation.SUBSET
    shared_keys = set(left) & set(right)
    if any(left[key] != right[key] for key in shared_keys):
        return ConditionRelation.DISJOINT
    if left_items > right_items:
        return ConditionRelation.SUBSET
    if right_items > left_items:
        return ConditionRelation.SUPERSET
    if shared_keys or (left_items and right_items):
        return ConditionRelation.OVERLAP
    return ConditionRelation.UNKNOWN


class HierarchicalConflictClassifier:
    module_id = "conflict.hierarchical_rule.v1"

    def classify(
        self,
        memories: list[StrictMemory],
        *,
        now: str | None = None,
    ) -> list[StrictConflictGroup]:
        timestamp = now or datetime.now(timezone.utc).isoformat()
        grouped: dict[tuple[str, str], list[StrictMemory]] = {}
        for memory in memories:
            if memory.status in {
                LifecycleStatus.BLOCKED,
                LifecycleStatus.DELETED,
                LifecycleStatus.ARCHIVE,
            }:
                continue
            grouped.setdefault((memory.user_id, memory.slot_key), []).append(memory)

        conflicts: list[StrictConflictGroup] = []
        for (user_id, slot_key), slot_memories in grouped.items():
            for conflict_set in _conflict_sets(slot_memories):
                relations = _pair_relations(conflict_set)
                conflict_type, reason = _classify_type(
                    conflict_set,
                    relations,
                )
                identity = (
                    f"{user_id}|{slot_key}|"
                    + "|".join(
                        sorted(item.memory_id for item in conflict_set)
                    )
                )
                conflicts.append(
                    StrictConflictGroup(
                        conflict_group_id="conflict-"
                        + uuid5(NAMESPACE_URL, identity).hex,
                        user_id=user_id,
                        slot_key=slot_key,
                        conflict_type=conflict_type,
                        memory_ids=tuple(
                            sorted(
                                item.memory_id
                                for item in conflict_set
                            )
                        ),
                        condition_relations=relations,
                        condition_partition=_condition_partition(
                            conflict_set
                        ),
                        timeline=tuple(
                            {
                                "memory_id": item.memory_id,
                                "value": item.semantic_value,
                                "valid_from": item.valid_from,
                                "valid_to": item.valid_to,
                                "status": item.status.value,
                            }
                            for item in sorted(
                                conflict_set,
                                key=lambda memory: (
                                    memory.valid_from,
                                    memory.memory_id,
                                ),
                            )
                        ),
                        winner_memory_id="",
                        unresolved_reason=reason,
                        status="unresolved",
                        confidence={},
                        updated_at=timestamp,
                    )
                )
        return conflicts


class SourceVersionCountStaticResolver:
    module_id = "conflict.static.source_version_count.v1"

    def resolve(
        self,
        group: StrictConflictGroup,
        memories: Mapping[str, StrictMemory],
    ) -> StrictConflictGroup:
        if group.conflict_type is not ConflictType.STATIC:
            return group
        candidates = [memories[memory_id] for memory_id in group.memory_ids]
        ranked = sorted(
            candidates,
            key=lambda item: (
                _source_priority(item),
                len(item.support_unit_ids),
                item.valid_from,
            ),
            reverse=True,
        )
        if len(ranked) > 1 and _static_rank(ranked[0]) == _static_rank(ranked[1]):
            return replace(
                group,
                unresolved_reason="static_priority_tie",
                status="unresolved",
            )
        return replace(
            group,
            winner_memory_id=ranked[0].memory_id,
            unresolved_reason="",
            status="resolved",
        )


class ExplicitTimeRecentWindowDynamicResolver:
    module_id = "conflict.dynamic.explicit_time_recent_window.v1"

    def resolve(
        self,
        group: StrictConflictGroup,
        memories: Mapping[str, StrictMemory],
    ) -> StrictConflictGroup:
        if group.conflict_type is not ConflictType.DYNAMIC:
            return group
        active = [
            memories[memory_id]
            for memory_id in group.memory_ids
            if memories[memory_id].status is not LifecycleStatus.HISTORICAL
        ]
        if len(active) != 1:
            return replace(
                group,
                unresolved_reason="dynamic_active_successor_not_unique",
                status="unresolved",
            )
        winner = active[0]
        strong = bool(
            winner.provenance.get("explicit_temporal")
            or winner.provenance.get("config_version") not in (None, "")
            or winner.provenance.get("dynamic_successor")
        )
        if not strong:
            return replace(
                group,
                unresolved_reason="dynamic_change_lacks_strong_signal",
                status="unresolved",
            )
        return replace(
            group,
            winner_memory_id=winner.memory_id,
            unresolved_reason="",
            status="resolved",
        )


class ConditionPartitionResolver:
    module_id = "conflict.conditional.condition_partition.v1"

    def resolve(
        self,
        group: StrictConflictGroup,
        memories: Mapping[str, StrictMemory],
    ) -> StrictConflictGroup:
        if group.conflict_type is not ConflictType.CONDITIONAL:
            return group
        branches = [memories[memory_id] for memory_id in group.memory_ids]
        if any(not item.condition for item in branches):
            return replace(
                group,
                unresolved_reason="conditional_branch_missing_meaningful_condition",
                status="unresolved",
            )
        if any(not item.support_unit_ids for item in branches):
            return replace(
                group,
                unresolved_reason="conditional_branch_without_support",
                status="unresolved",
            )
        return replace(
            group,
            winner_memory_id="",
            unresolved_reason="query_condition_required",
            status="partitioned",
        )


def _condition_items(condition: Mapping[str, Any]) -> set[tuple[str, str]]:
    return {
        (
            str(key),
            json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            ),
        )
        for key, value in condition.items()
    }


def _pair_relations(memories: list[StrictMemory]) -> dict[str, str]:
    relations: dict[str, str] = {}
    for index, left in enumerate(memories):
        for right in memories[index + 1 :]:
            key = "|".join(sorted((left.memory_id, right.memory_id)))
            relations[key] = condition_relation(
                left.condition,
                right.condition,
            ).value
    return relations


def _conflict_sets(
    memories: list[StrictMemory],
) -> list[list[StrictMemory]]:
    if len({item.semantic_value for item in memories}) < 2:
        return []
    branches: dict[str, list[StrictMemory]] = {}
    for memory in memories:
        key = json.dumps(
            memory.condition,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        branches.setdefault(key, []).append(memory)
    branch_values = list(branches.values())
    if len(branch_values) == 1:
        return [memories]
    cross_disjoint = all(
        condition_relation(left[0].condition, right[0].condition)
        is ConditionRelation.DISJOINT
        for index, left in enumerate(branch_values)
        for right in branch_values[index + 1 :]
    )
    if not cross_disjoint:
        return [memories]
    internal_conflicts = [
        branch
        for branch in branch_values
        if len({item.semantic_value for item in branch}) > 1
    ]
    return internal_conflicts or [memories]


def _classify_type(
    memories: list[StrictMemory],
    relations: Mapping[str, str],
) -> tuple[ConflictType, str]:
    relation_values = {ConditionRelation(value) for value in relations.values()}
    conditions = [memory.condition for memory in memories]
    if (
        ConditionRelation.DISJOINT in relation_values
        and all(conditions)
    ):
        return ConflictType.CONDITIONAL, "condition_partition_precedes_time"
    if any(
        memory.status is LifecycleStatus.HISTORICAL
        or memory.predecessor_memory_ids
        or memory.successor_memory_ids
        for memory in memories
    ):
        return ConflictType.DYNAMIC, "explicit_successor_timeline"
    if relation_values <= {
        ConditionRelation.EQUAL,
        ConditionRelation.SUBSET,
        ConditionRelation.SUPERSET,
        ConditionRelation.OVERLAP,
    } and _validity_overlaps(memories):
        return ConflictType.STATIC, "overlapping_scope_and_validity"
    return ConflictType.UNRESOLVED, "insufficient_conflict_structure"


def _validity_overlaps(memories: list[StrictMemory]) -> bool:
    starts = [
        datetime.fromisoformat(item.valid_from)
        for item in memories
        if item.valid_from
    ]
    ends = [
        datetime.fromisoformat(item.valid_to)
        for item in memories
        if item.valid_to
    ]
    if not starts:
        return True
    latest_start = max(starts)
    earliest_end = min(ends) if ends else None
    return earliest_end is None or latest_start <= earliest_end


def _condition_partition(
    memories: list[StrictMemory],
) -> dict[str, Any]:
    return {
        memory.memory_id: dict(memory.condition)
        for memory in memories
    }


_CONFIG_VERSION_PATTERN = re.compile(r"[_\-]?[Vv](\d+)$")
_TEMPORARY_MARKERS = (
    "临时做法",
    "临时变通",
    "临时改动",
    "应急处理",
    "特批",
    "只此一次",
    "先别照着用",
    "不要照着用",
    "不沿用",
)


def _config_version_number(memory: StrictMemory) -> int:
    """从 provenance.config_version 末段解析版本号（如 …_V2 → 2）；无则 0。"""
    raw = str((memory.provenance or {}).get("config_version") or "")
    if not raw:
        return 0
    match = _CONFIG_VERSION_PATTERN.search(raw.strip())
    if match:
        return int(match.group(1))
    return 0


def _is_temporary_memory(memory: StrictMemory) -> bool:
    """是否为"临时做法 / 例外"类记忆（未要求恢复时不应压过常规做法）。"""
    provenance = memory.provenance or {}
    if provenance.get("temporary") or provenance.get("exception"):
        return True
    parts = [str(memory.semantic_value or "")]
    condition = memory.condition or {}
    try:
        parts.append(json.dumps(condition, ensure_ascii=False))
    except (TypeError, ValueError):
        parts.append(str(condition))
    condition_text = str((condition or {}).get("text") or "")
    if condition_text:
        parts.append(condition_text)
    blob = " ".join(parts)
    return any(marker in blob for marker in _TEMPORARY_MARKERS)


def _active_config_rank(memory: StrictMemory) -> tuple[int, int, int, int, str]:
    """静态冲突排序键（越大越优先）。

    与 v1 的差异：在来源优先级之后先看**配置版本号**，再看支撑单元数量；
    并把"临时做法/例外"整体降到最低一档。
    """
    return (
        0 if _is_temporary_memory(memory) else 1,
        _source_priority(memory),
        _config_version_number(memory),
        len(memory.support_unit_ids),
        str(memory.valid_from or ""),
    )


class ActiveConfigRecencyStaticResolver:
    """静态冲突解析：生效配置（最新配置版本）优先，临时做法降级。

    对应评测结论 v0.7：系统可通过"配置版本 + 更新时刻"推导生效状态，
    无需新增字段即可让裁决层识别"当前生效配置"。
    """

    module_id = "conflict.static.active_config_recency.v2"

    def resolve(
        self,
        group: StrictConflictGroup,
        memories: Mapping[str, StrictMemory],
    ) -> StrictConflictGroup:
        if group.conflict_type is not ConflictType.STATIC:
            return group
        candidates = [memories[memory_id] for memory_id in group.memory_ids]
        ranked = sorted(candidates, key=_active_config_rank, reverse=True)
        if len(ranked) > 1 and _active_config_rank(ranked[0]) == _active_config_rank(ranked[1]):
            return replace(
                group,
                unresolved_reason="static_priority_tie",
                status="unresolved",
            )
        return replace(
            group,
            winner_memory_id=ranked[0].memory_id,
            unresolved_reason="",
            status="resolved",
        )


def _source_priority(memory: StrictMemory) -> int:
    directness = str(memory.provenance.get("directness") or "")
    if directness == "explicit_user":
        return 4
    if memory.provenance.get("config_version") not in (None, ""):
        return 3
    if directness == "verified_system":
        return 2
    return 1


def _static_rank(memory: StrictMemory) -> tuple[int, int]:
    return _source_priority(memory), len(memory.support_unit_ids)
