"""配置即 SKILL 记忆模块（指令「配置」：SKILL/常用提示词融入长期记忆）

- Skill 条目：名称/内容/标签/条件/版本（配置或常用提示词的持久化形态）
- 写入前走 MemoryGuard（威胁扫描 + 敏感标注）
- 冲突处理：同名配置 → 版本化演进（保留历史，标记冲突已解决）
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Sequence

from security.memory_guard import MemoryGuard
from security.sensitivity import SensitivityLevel


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


@dataclass
class Skill:
    skill_id: str
    name: str
    content: str
    tags: list[str] = field(default_factory=list)
    condition: str = ""
    version: int = 1
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)
    sensitivity: SensitivityLevel = SensitivityLevel.NONE
    sensitive_types: list[str] = field(default_factory=list)
    predecessor: str | None = None  # 被本版本替代的 skill_id

    def to_dict(self) -> dict[str, Any]:
        return {
            "skill_id": self.skill_id,
            "name": self.name,
            "content": self.content,
            "tags": self.tags,
            "condition": self.condition,
            "version": self.version,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "sensitivity": self.sensitivity.value,
            "sensitive_types": self.sensitive_types,
            "predecessor": self.predecessor,
        }


class SkillConflict:
    """配置冲突记录：同名配置版本化替代时登记。"""

    def __init__(self, name: str, old_version: int, new_version: int, reason: str):
        self.name = name
        self.old_version = old_version
        self.new_version = new_version
        self.reason = reason

    def to_dict(self) -> dict:
        return {"name": self.name, "old_version": self.old_version,
                "new_version": self.new_version, "reason": self.reason}


class SkillMemory:
    """SKILL 记忆：配置/常用提示词的长期记忆容器（含冲突版本化）。"""

    def __init__(self, guard: MemoryGuard | None = None):
        self.guard = guard or MemoryGuard()
        self._skills: dict[str, list[Skill]] = {}   # name -> 版本列表（升序）
        self._conflicts: list[SkillConflict] = []
        self._seq = 0

    def _next_id(self, name: str) -> str:
        self._seq += 1
        return f"skill_{name}_{self._seq}"

    # ---- 写入（走 guard 审查 + 冲突版本化）----
    def add_skill(
        self,
        name: str,
        content: str,
        tags: Sequence[str] | None = None,
        condition: str = "",
        user_id: str = "",
    ) -> Skill | None:
        name = (name or "").strip()
        if not name or not content:
            return None
        # 写入前安全审查（威胁拦截 + 敏感标注）
        review = self.guard.review(content)
        if not review.allowed:
            return None  # 威胁内容拒绝写入
        existing = self._skills.get(name, [])
        new_version = (existing[-1].version + 1) if existing else 1
        predecessor = existing[-1].skill_id if existing else None
        skill = Skill(
            skill_id=self._next_id(name),
            name=name,
            content=content,
            tags=list(tags or []),
            condition=condition,
            version=new_version,
            sensitivity=review.sensitivity,
            sensitive_types=review.sensitive_types,
            predecessor=predecessor,
        )
        self._skills.setdefault(name, []).append(skill)
        if predecessor:
            # 冲突记录：同名配置被新版本替代
            self._conflicts.append(SkillConflict(
                name=name,
                old_version=new_version - 1,
                new_version=new_version,
                reason="同名配置更新，版本化替代（冲突已解决）",
            ))
        return skill

    # ---- 读取 ----
    def get_skill(self, name: str, version: int | None = None) -> Skill | None:
        versions = self._skills.get(name, [])
        if not versions:
            return None
        if version is None:
            return versions[-1]  # 最新版
        for s in versions:
            if s.version == version:
                return s
        return None

    def list_skills(self, tag: str | None = None) -> list[Skill]:
        out = []
        for versions in self._skills.values():
            s = versions[-1]
            if tag is None or tag in s.tags:
                out.append(s)
        return out

    # ---- 冲突查询 ----
    def conflicts(self) -> list[SkillConflict]:
        return list(self._conflicts)

    def has_conflict(self, name: str) -> bool:
        return len(self._skills.get(name, [])) > 1

    # ---- 删除 ----
    def delete_skill(self, name: str, version: int | None = None) -> bool:
        versions = self._skills.get(name)
        if not versions:
            return False
        if version is None:
            del self._skills[name]
        else:
            versions = [s for s in versions if s.version != version]
            if versions:
                self._skills[name] = versions
            else:
                del self._skills[name]
        return True

    def __len__(self) -> int:
        return sum(len(v) for v in self._skills.values())
