"""四主标签结构化匹配管线（报告第 5 章）

流程：TagClassifier(四主标签分类) → MatchingList(逐标签匹配) → CalcMatchingRate(加权综合) → ThresholdFilter(漏斗过滤) → Matched
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable, Mapping

from .matched import Matched, _stable_key

# ---- 四主标签 ----
LABELS = ("condition", "obj", "preferences", "lastingtime")

# ---- 标签判定规则（关键词 + 正则）----
LABEL_RULES: dict[str, list[str]] = {
    "condition": ["当", "如果", "若", "when", "if", "超过", "低于", "达到", "不足", "期间"],
    "obj": ["修改", "设置", "打开", "关闭", "创建", "删除", "查看", "查询", "安装", "配置",
            "打印机", "文件夹", "文件", "桌面", "系统", "网络", "服务", "应用", "软件"],
    "preferences": ["喜欢", "偏好", "习惯", "希望", "默认", "通常", "简洁", "详细", "prefer",
                    "喜欢用", "更爱", "倾向"],
    "lastingtime": ["每", "持续", "每隔", "天", "小时", "分钟", "周", "月", "always", "every",
                    "持续", "永久", "临时", "直到"],
}


class TagClassifier:
    """把输入文本分类到四主标签，返回各标签的命中关键词与原始片段。"""

    def classify(self, text: str) -> dict[str, list[str]]:
        text = text or ""
        hits: dict[str, list[str]] = {k: [] for k in LABELS}
        for label, keywords in LABEL_RULES.items():
            for kw in keywords:
                if kw in text:
                    hits[label].append(kw)
        return hits


@dataclass
class MatchingList:
    """单个标签的匹配候选列表（词或短语，均可向量化）。"""

    label: str
    items: list[str] = field(default_factory=list)
    weights: dict[str, float] = field(default_factory=dict)

    def add(self, item: str, weight: float = 1.0) -> None:
        if item not in self.items:
            self.items.append(item)
            self.weights[item] = weight

    def match_score(self, text: str) -> float:
        """词面匹配率：命中的候选加权和 / 候选总数（0~1）。"""
        if not self.items:
            return 0.0
        hit = sum(
            self.weights.get(item, 1.0) for item in self.items if item.lower() in text.lower()
        )
        total = sum(self.weights.get(item, 1.0) for item in self.items)
        return min(1.0, hit / total) if total else 0.0


class TagMatcher:
    """对四个标签分别计算匹配率。"""

    DEFAULT_WEIGHTS = {"condition": 0.3, "obj": 0.3, "preferences": 0.2, "lastingtime": 0.2}

    def __init__(self, lists: Mapping[str, MatchingList], weights: Mapping[str, float] | None = None):
        self.lists = dict(lists)
        self.weights = dict(weights or self.DEFAULT_WEIGHTS)

    def score(self, text: str) -> tuple[dict[str, float], float]:
        label_scores = {
            label: (self.lists[label].match_score(text) if label in self.lists else 0.0)
            for label in LABELS
        }
        total_w = sum(self.weights.get(l, 0) for l in LABELS) or 1.0
        overall = sum(label_scores[l] * self.weights.get(l, 0) for l in LABELS) / total_w
        return label_scores, round(overall, 4)


class ThresholdFilter:
    """漏斗式过滤：低于阈值的结果被剔除。"""

    def __init__(self, threshold: float = 0.5):
        self.threshold = threshold

    def passes(self, overall_rate: float) -> bool:
        return overall_rate >= self.threshold


def run_tag_pipeline(
    text: str,
    matching_lists: Mapping[str, MatchingList],
    weights: Mapping[str, float] | None = None,
    threshold: float = 0.5,
    classifier: TagClassifier | None = None,
) -> Matched | None:
    """执行完整四主标签匹配管线，返回 Matched 或 None（被过滤）。"""
    classifier = classifier or TagClassifier()
    hits = classifier.classify(text)
    matcher = TagMatcher(matching_lists, weights)
    label_scores, overall = matcher.score(text)
    if not ThresholdFilter(threshold).passes(overall):
        return None

    condition = ", ".join(hits["condition"]) or ""
    obj = ", ".join(hits["obj"]) or ""
    preference = ", ".join(hits["preferences"]) or ""
    lasttime = ", ".join(hits["lastingtime"]) or ""
    return Matched(
        key=_stable_key(text, obj),
        condition=condition,
        obj=obj,
        preference=preference,
        lasttime=lasttime,
        text_input=text,
        matched_rate=overall,
        label_scores=label_scores,
    )
