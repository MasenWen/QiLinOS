from __future__ import annotations

from .contracts import LifecycleStatus, StrictMemory


def render_memory(memory: StrictMemory) -> str:
    condition = " ".join(
        f"{key} {value}" for key, value in sorted(memory.condition.items())
    )
    tier = str(memory.scope.get("tier") or "mid_term")
    scope_text = (
        "短期记忆 最近上下文 当前任务 临时状态"
        if tier == "short_term"
        else "中期记忆 稳定模式 重复行为 习惯 例行"
    )
    history_text = (
        "历史旧记忆 变更前偏好"
        if memory.status is LifecycleStatus.HISTORICAL
        else "当前有效记忆"
    )
    support_text = (
        f"独立支持 {len(memory.support_unit_ids)} 次"
        if memory.support_unit_ids
        else ""
    )
    return " ".join(
        (
            scope_text,
            history_text,
            memory.slot_key.replace(":", " "),
            memory.semantic_value,
            memory.candidate_kind,
            support_text,
            condition,
        )
    )
