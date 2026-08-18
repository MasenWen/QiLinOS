"""配置克隆无冲突约束（报告 11.3）

配置克隆(clones)前执行 make sure no conflict 硬约束：
比较克隆源与目标的 key/label/obj 映射是否冲突，输出冲突报告。
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Mapping, Sequence


@dataclass
class ConflictItem:
    item: str
    source_value: Any
    target_value: Any
    kind: str = "value_mismatch"  # value_mismatch | duplicate_key | obj_conflict

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class CloneConflictReport:
    ok: bool
    conflicts: list[ConflictItem] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"ok": self.ok, "conflicts": [c.to_dict() for c in self.conflicts]}


def check_clone_conflicts(
    source: Mapping[str, Any],
    target: Mapping[str, Any],
    *,
    conflict_keys: Sequence[str] = ("key", "label", "obj"),
) -> CloneConflictReport:
    """检查克隆源到目标是否无冲突。

    - 相同 key/label/obj 但值不同 → value_mismatch 冲突；
    - target 中重复 key → duplicate_key 冲突；
    - target 的 obj 映射与 source 不一致 → obj_conflict。
    """
    conflicts: list[ConflictItem] = []
    for k in conflict_keys:
        sv = source.get(k)
        tv = target.get(k)
        if sv is not None and tv is not None and sv != tv:
            conflicts.append(ConflictItem(item=k, source_value=sv, target_value=tv, kind="value_mismatch"))

    # obj → Table/Version 映射一致性
    src_objs = source.get("obj_mapping", {})
    tgt_objs = target.get("obj_mapping", {})
    for o in set(src_objs) & set(tgt_objs):
        if src_objs[o] != tgt_objs[o]:
            conflicts.append(ConflictItem(item=f"obj_mapping[{o}]", source_value=src_objs[o], target_value=tgt_objs[o], kind="obj_conflict"))

    return CloneConflictReport(ok=len(conflicts) == 0, conflicts=conflicts)
