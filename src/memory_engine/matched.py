"""MATCHED 六字段输出模型（报告第 6 章）

KEY / CONDITION / OBJ / PREFERENCE / LASTTIME / TEXT INPUT
"""
from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Mapping


def _stable_key(text: str, obj: str = "") -> str:
    """稳定主键：基于原始文本与对象哈希。"""
    raw = f"{obj}|{text}".strip("|")
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


@dataclass
class Matched:
    """结构化匹配结果（MATCHED）。"""

    key: str
    condition: str = ""
    obj: str = ""
    preference: str = ""
    lasttime: str = ""
    text_input: str = ""
    matched_rate: float = 0.0
    label_scores: dict[str, float] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "Matched":
        d = dict(data)
        text = str(d.get("text_input", d.get("TEXT INPUT", "")))
        obj = str(d.get("obj", d.get("OBJ", "")))
        return cls(
            key=str(d.get("key", d.get("KEY", _stable_key(text, obj)))),
            condition=str(d.get("condition", d.get("CONDITION", ""))),
            obj=obj,
            preference=str(d.get("preference", d.get("PREFERENCE", ""))),
            lasttime=str(d.get("lasttime", d.get("LASTTIME", d.get("last_time", "")))),
            text_input=text,
            matched_rate=float(d.get("matched_rate", d.get("matching_rate", 0.0)) or 0.0),
            label_scores=dict(d.get("label_scores", {}) or {}),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def as_prompt(self) -> str:
        parts = [
            f"KEY: {self.key}",
            f"CONDITION: {self.condition or '（无）'}",
            f"OBJ: {self.obj or '（无）'}",
            f"PREFERENCE: {self.preference or '（无）'}",
            f"LASTTIME: {self.lasttime or '（无）'}",
            f"TEXT INPUT: {self.text_input}",
        ]
        return "\n".join(parts)
