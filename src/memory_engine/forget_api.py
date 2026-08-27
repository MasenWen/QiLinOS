"""精准遗忘 API（指令「遗忘」：按用户指令对特定记忆/敏感信息精准遗忘）

高层封装：按指令文本、按目标文本、按敏感级别三类遗忘路径。
与 SensitivityRegistry 联动（敏感记忆一键遗忘），对接底层 store 删除接口。
"""
from __future__ import annotations

from typing import Any, Callable, Iterable

from security.sensitivity import SensitivityLevel, SensitivityRegistry

# 遗忘指令动词（中文习惯）
_FORGET_VERBS = (
    "忘记", "忘了", "忘掉", "删除", "删掉", "移除", "清除", "抹除", "别再记住",
    "不要再记", "取消记住", "forget", "remove", "delete",
)


def extract_forget_target(instruction: str) -> str:
    """从用户遗忘指令中提取目标内容（动词后的部分）。

    例："忘记打印机配置" → "打印机配置"；"删掉我对咖啡的偏好" → "我对咖啡的偏好"
    无动词/无目标时返回空串（安全：避免非遗忘指令误触发删除）。
    """
    text = (instruction or "").strip()
    if not text:
        return ""
    # 否定/非遗忘语境拦截：「别忘了」「不要忘记」「难忘」等不是删除记忆指令
    _NEG = ("别忘", "别忘了", "不要忘", "不要忘记", "别忘了", "没忘", "不忘",
            "难忘", "难以忘", "别忘记", "别忘掉", "别忘了")
    if any(n in text for n in _NEG):
        return ""
    for verb in _FORGET_VERBS:
        if text.startswith(verb):
            target = text[len(verb):].lstrip("，,、 的")
            if target:
                return target
        idx = text.find(verb)
        if idx >= 0:
            after = text[idx + len(verb):].lstrip("，,、 的")
            if after:
                return after
    return ""  # 未识别到遗忘动词：不视为遗忘指令


class PrecisionForgetting:
    """精准遗忘：三类路径 + 敏感联动。

    store 需提供:
      - list_memories(user_id) -> 可迭代记忆对象（含 memory_id/semantic_value/slot_key）
      - delete_memory(memory_id) -> 删除
    """

    def __init__(
        self,
        store: Any,
        registry: SensitivityRegistry | None = None,
        text_of: Callable[[Any], str] | None = None,
    ):
        self.store = store
        self.registry = registry or SensitivityRegistry()
        self._text_of = text_of or (lambda m: getattr(m, "semantic_value", "") or getattr(m, "slot_key", ""))

    # ---- 基础：按 id 删除 ----
    def forget_memory_ids(self, memory_ids: Iterable[str]) -> list[str]:
        deleted: list[str] = []
        for mid in memory_ids:
            try:
                self.store.delete_memory(mid)
                deleted.append(mid)
            except Exception:
                continue
        return deleted

    # ---- 按目标文本删除（记忆内容包含目标）----
    def forget_by_text(self, user_id: str, target: str, limit: int = 100) -> list[str]:
        target = (target or "").strip()
        if not target:
            return []
        matched: list[str] = []
        for memory in self.store.list_memories(user_id) or []:
            if len(matched) >= limit:
                break
            text = self._text_of(memory)
            if target.lower() in (text or "").lower():
                matched.append(getattr(memory, "memory_id", ""))
        return self.forget_memory_ids([mid for mid in matched if mid])

    # ---- 按用户指令删除（自动提取目标）----
    def forget_by_instruction(self, user_id: str, instruction: str) -> dict[str, Any]:
        target = extract_forget_target(instruction)
        if not target:
            return {"forgotten": [], "target": "", "note": "未能从指令提取遗忘目标"}
        deleted = self.forget_by_text(user_id, target)
        return {"forgotten": deleted, "target": target, "note": "按指令精准遗忘"}

    # ---- 按敏感级别删除（联动 SensitivityRegistry，删除后清空登记）----
    def forget_sensitive(self, min_level: SensitivityLevel = SensitivityLevel.HIGH) -> list[str]:
        ids = self.registry.forget_sensitive(min_level)  # 取出并清空登记
        return self.forget_memory_ids(ids)

    # ---- 组合：指令中若包含"敏感"则联动敏感遗忘 ----
    def forget(self, user_id: str, instruction: str) -> dict[str, Any]:
        result = self.forget_by_instruction(user_id, instruction)
        if any(k in instruction for k in ("敏感", "sensitive")):
            result["sensitive_forgotten"] = self.forget_sensitive()
        return result
