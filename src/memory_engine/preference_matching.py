from __future__ import annotations

import hashlib
import math
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Collection, Mapping, Protocol, Sequence

import numpy as np

from .span_matching import (
    HighRecallRoleHypothesisMatcher,
    JiebaSpanTokenizer,
    PrototypeEmbeddingScorer,
    RoleHypothesis,
    SpanTokenizer,
)
from .span_segmentation import (
    AdaptiveGlobalEmbeddingPartitionSegmenter,
    Segment,
    TextEmbedder,
    build_result,
    punctuation_boundaries,
)


@dataclass(frozen=True)
class CanonicalTag:
    tag_id: str
    name: str
    groups: tuple[str, ...]
    aliases: tuple[str, ...]
    prototypes: tuple[str, ...]


DEFAULT_CANONICAL_TAGS_V1: tuple[CanonicalTag, ...] = (
    CanonicalTag(
        "app:chatgpt_codex",
        "ChatGPT Codex",
        ("condition", "object"),
        (
            "ChatGPT Codex",
            "ChatGPT-codex",
            "ChatGPT codex",
            "OpenAI Codex",
            "Codex",
        ),
        (
            "用于编程和代码解释的人工智能助手",
            "具体的代码助手应用",
        ),
    ),
    CanonicalTag(
        "app:web_browser",
        "Web Browser",
        ("condition", "object"),
        ("浏览器", "Web Browser", "Chrome", "Edge", "Firefox"),
        ("用于网页访问和浏览器交互的应用",),
    ),
    CanonicalTag(
        "app:spreadsheet",
        "Spreadsheet",
        ("condition", "object"),
        ("Excel", "电子表格", "Spreadsheet", "WPS表格"),
        ("用于表格计算和数据分析的办公应用",),
    ),
    CanonicalTag(
        "app:word_processor",
        "Word Processor",
        ("condition", "object"),
        ("Word", "文字处理", "WPS文字"),
        ("用于文档撰写和文字处理的办公应用",),
    ),
    CanonicalTag(
        "app:presentation",
        "Presentation",
        ("condition", "object"),
        ("PowerPoint", "PPT", "演示文稿", "WPS演示"),
        ("用于制作和展示演示文稿的办公应用",),
    ),
    CanonicalTag(
        "app:terminal",
        "Terminal",
        ("condition", "object"),
        ("终端", "Terminal", "命令行", "PowerShell"),
        ("用于执行命令和开发操作的终端应用",),
    ),
    CanonicalTag(
        "task:financial_summary",
        "Financial Summary",
        ("condition",),
        ("财务汇总", "财务总结"),
        ("汇总财务数据和编写财务摘要的任务",),
    ),
    CanonicalTag(
        "task:budget_comparison",
        "Budget Comparison",
        ("condition",),
        ("预算比较", "预算对比"),
        ("比较预算方案或预算数据的工作场景",),
    ),
    CanonicalTag(
        "task:sales_trend",
        "Sales Trend Analysis",
        ("condition",),
        ("销售趋势", "销售走势"),
        ("分析销售趋势和业务走势的任务",),
    ),
    CanonicalTag(
        "task:code_explanation",
        "Code Explanation",
        ("condition",),
        ("代码解释", "代码讲解"),
        ("阅读并解释程序代码的任务",),
    ),
    CanonicalTag(
        "task:ordinary_chat",
        "Ordinary Chat",
        ("condition",),
        ("普通聊天", "日常聊天"),
        ("不涉及专业任务的普通聊天场景",),
    ),
    CanonicalTag(
        "task:quote_email",
        "Quote Email",
        ("condition", "object"),
        ("报价邮件",),
        ("撰写或处理报价邮件的工作任务",),
    ),
    CanonicalTag(
        "task:report",
        "Report Work",
        ("condition",),
        ("报告整理", "报告撰写", "本轮报告", "季度报告"),
        ("撰写整理或更新工作报告的任务",),
    ),
    CanonicalTag(
        "chart:bar",
        "Bar Chart",
        ("object",),
        ("柱状图", "柱形图", "bar chart"),
        ("以柱形或条形展示数据的图表类型",),
    ),
    CanonicalTag(
        "chart:line",
        "Line Chart",
        ("object",),
        ("折线图", "line chart"),
        ("以折线展示变化趋势的图表类型",),
    ),
    CanonicalTag(
        "document:template",
        "Document Template",
        ("object",),
        ("模板", "旧模板", "新模板", "这个模板"),
        ("文档或报告采用的模板和版式",),
    ),
    CanonicalTag(
        "setting:preference",
        "Preference Setting",
        ("object",),
        ("设置", "长期设置", "偏好设置"),
        ("应用或助手中的配置和偏好设置",),
    ),
    CanonicalTag(
        "artifact:budget_sheet",
        "Budget Sheet",
        ("object",),
        ("预算表", "六月预算表", "报价表"),
        ("包含预算或报价数据的办公表格文件",),
    ),
    CanonicalTag(
        "artifact:file",
        "Office File",
        ("object",),
        ("历史文件", "办公文件"),
        ("文档表格或其他办公文件产物",),
    ),
)


@dataclass(frozen=True)
class CanonicalMention:
    start: int
    end: int
    text: str
    tag_id: str
    groups: tuple[str, ...]


@dataclass(frozen=True)
class CanonicalRoleMatch:
    start: int
    end: int
    text: str
    group: str
    tag_id: str
    tag_name: str
    score: float
    similarity: float
    exact_alias: bool
    hypothesis_score: float
    sources: tuple[str, ...]
    competition_margin: float = 0.0


@dataclass(frozen=True)
class AttitudeValue:
    start: int
    end: int
    text: str
    value: float
    anchor: str
    confidence: float
    similarity: float
    hypothesis_score: float
    sources: tuple[str, ...]


@dataclass(frozen=True)
class TemporalValue:
    start: int
    end: int
    text: str
    label: str
    promotion_seed: float
    explicit_long_term: bool
    confidence: float
    hypothesis_score: float
    competition_margin: float
    sources: tuple[str, ...]


@dataclass(frozen=True)
class TemporalInitialization:
    label: str
    promotion_seed: float
    explicit_long_term: bool


TEMPORAL_INITIALIZATION_V1: Mapping[str, TemporalInitialization] = {
    "temporal_short": TemporalInitialization(
        "temporal_short",
        0.0,
        False,
    ),
    "temporal_medium": TemporalInitialization(
        "temporal_medium",
        1.0,
        False,
    ),
    "temporal_long": TemporalInitialization(
        "temporal_long",
        1.0,
        True,
    ),
}


@dataclass(frozen=True)
class PreferenceFrame:
    condition: CanonicalRoleMatch | None
    temporal: TemporalValue | None
    attitude: AttitudeValue
    object: CanonicalRoleMatch
    confidence: float
    relation_text: str
    source_start: int
    source_end: int


@dataclass(frozen=True)
class PreferenceFrameResult:
    algorithm: str
    text: str
    hypotheses: tuple[RoleHypothesis, ...]
    canonical_matches: tuple[CanonicalRoleMatch, ...]
    attitudes: tuple[AttitudeValue, ...]
    temporals: tuple[TemporalValue, ...]
    frames: tuple[PreferenceFrame, ...]
    diagnostics: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PreferenceObservationOptions:
    condition_tag_ids: tuple[str, ...] = ()
    object_tag_ids: tuple[str, ...] = ()
    temporal_labels: tuple[str, ...] = ()


class PreferenceFrameMatching(Protocol):
    def match(
        self,
        text: str,
        *,
        options: PreferenceObservationOptions | None = None,
    ) -> PreferenceFrameResult: ...


@dataclass(frozen=True)
class PreferenceSourceObservation:
    observation_id: str
    source_event_id: str
    user_id: str
    session_id: str
    event_time: str
    content: str
    source_reliability: float = 1.0
    privacy: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PreferenceObservationEvidence:
    evidence_id: str
    user_id: str
    evidence_type: str
    memory_family: str
    memory_type: str
    memory_category: str
    claim_subject: str
    claim_slot: str
    claim_value: str
    claim_polarity: str
    observed_time: str
    source_observation_ids: tuple[str, ...]
    independent_unit_id: str
    valid_from: str
    directness: str
    source_reliability: float
    extraction_confidence: float
    condition: Mapping[str, Any] = field(default_factory=dict)
    statistics: Mapping[str, Any] = field(default_factory=dict)
    extractor: Mapping[str, Any] = field(default_factory=dict)
    privacy: Mapping[str, Any] = field(default_factory=dict)
    status: str = "active"
    schema_version: str = "preference.observation_evidence.v1"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PreferenceObservationMemory:
    memory_id: str
    observation_id: str
    source_event_id: str
    user_id: str
    session_id: str
    observed_time: str
    source_text: str
    condition_tag_id: str
    condition_name: str
    condition_text: str
    object_tag_id: str
    object_name: str
    object_text: str
    attitude_value: float
    attitude_anchor: str
    attitude_confidence: float
    temporal_label: str
    promotion_seed: float
    explicit_long_term: bool
    extraction_confidence: float
    source_start: int
    source_end: int
    schema_version: str = "preference.observation_memory.v1"

    def to_evidence(
        self,
        *,
        source_reliability: float,
        privacy: Mapping[str, Any],
    ) -> PreferenceObservationEvidence:
        if self.explicit_long_term:
            memory_type = "long_term"
        elif self.promotion_seed >= 1.0:
            memory_type = "mid_term"
        else:
            memory_type = "short_term"
        if self.attitude_value > 0.10:
            polarity = "support"
        elif self.attitude_value < -0.10:
            polarity = "oppose"
        else:
            polarity = "uncertain"
        condition = {}
        if self.condition_tag_id:
            condition = {
                "canonical_id": self.condition_tag_id,
                "name": self.condition_name,
                "source_text": self.condition_text,
            }
        evidence_id = _stable_identifier(
            "ev_pref",
            (
                f"{self.observation_id}|{self.object_tag_id}|"
                f"{self.source_start}|{self.source_end}"
            ),
        )
        return PreferenceObservationEvidence(
            evidence_id=evidence_id,
            user_id=self.user_id,
            evidence_type="explicit_statement",
            memory_family="preference",
            memory_type=memory_type,
            memory_category=(
                "scenario_preference"
                if condition
                else "explicit_preference"
            ),
            claim_subject=self.user_id,
            claim_slot=_preference_slot(self.object_tag_id),
            claim_value=self.object_tag_id,
            claim_polarity=polarity,
            observed_time=self.observed_time,
            source_observation_ids=(self.observation_id,),
            independent_unit_id=self.session_id or self.source_event_id,
            valid_from=self.observed_time,
            directness="explicit",
            source_reliability=source_reliability,
            extraction_confidence=self.extraction_confidence,
            condition=condition,
            statistics={
                "source_text": self.source_text,
                "object_name": self.object_name,
                "object_text": self.object_text,
                "attitude_value": self.attitude_value,
                "attitude_anchor": self.attitude_anchor,
                "attitude_confidence": self.attitude_confidence,
                "temporal_label": self.temporal_label,
                "promotion_seed": self.promotion_seed,
                "explicit_long_term": self.explicit_long_term,
                "observation_memory_id": self.memory_id,
            },
            extractor={
                "method": "kylin_dual_path_preference_frame",
                "version": "1.0.0",
            },
            privacy=dict(privacy),
        )


@dataclass(frozen=True)
class PreferenceObservationExtraction:
    observation_id: str
    memories: tuple[PreferenceObservationMemory, ...]
    evidence: tuple[PreferenceObservationEvidence, ...]
    frame_result: PreferenceFrameResult


def _stable_identifier(prefix: str, value: str) -> str:
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:24]
    return f"{prefix}_{digest}"


def _preference_slot(object_tag_id: str) -> str:
    namespace = object_tag_id.split(":", 1)[0]
    return {
        "app": "preference:tool",
        "chart": "preference:chart_type",
        "document": "preference:document_template",
        "setting": "preference:setting",
        "artifact": "preference:artifact",
        "task": "preference:workflow",
    }.get(namespace, f"preference:{namespace or 'object'}")


def _unit_rows(values: Any) -> np.ndarray:
    matrix = np.asarray(values, dtype=np.float32)
    if matrix.ndim == 1:
        matrix = matrix.reshape(1, -1)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    return matrix / np.clip(norms, 1e-9, None)


def _class_similarity(vector: np.ndarray, prototypes: np.ndarray) -> float:
    similarities = np.sort(prototypes @ vector)[::-1]
    top = similarities[: min(2, len(similarities))]
    return float(0.70 * similarities[0] + 0.30 * np.mean(top))


def _normalized_alias(value: str) -> str:
    return re.sub(r"[\s_-]+", "", value.casefold())


def _alias_pattern(alias: str) -> re.Pattern[str]:
    pieces = [
        re.escape(piece)
        for piece in re.split(r"[\s_-]+", alias.strip())
        if piece
    ]
    return re.compile(r"[\s_-]*".join(pieces), re.IGNORECASE)


class CanonicalTagRegistry:
    def __init__(
        self,
        tags: Sequence[CanonicalTag] = DEFAULT_CANONICAL_TAGS_V1,
    ):
        self.tags = tuple(tags)
        self.by_id = {tag.tag_id: tag for tag in self.tags}
        if len(self.by_id) != len(self.tags):
            raise ValueError("duplicate_canonical_tag_id")

    def eligible(self, group: str) -> tuple[CanonicalTag, ...]:
        return tuple(tag for tag in self.tags if group in tag.groups)

    def exact_tag(self, text: str, group: str) -> CanonicalTag | None:
        normalized = _normalized_alias(text)
        matches = [
            tag
            for tag in self.eligible(group)
            if normalized
            in {
                _normalized_alias(tag.name),
                *(_normalized_alias(alias) for alias in tag.aliases),
            }
        ]
        return min(matches, key=lambda tag: tag.tag_id) if matches else None

    def find_mentions(self, text: str) -> tuple[CanonicalMention, ...]:
        mentions = []
        for tag in self.tags:
            aliases = tuple(dict.fromkeys((tag.name, *tag.aliases)))
            for alias in aliases:
                if not alias.strip():
                    continue
                for match in _alias_pattern(alias).finditer(text):
                    if match.start() == match.end():
                        continue
                    mentions.append(
                        CanonicalMention(
                            start=match.start(),
                            end=match.end(),
                            text=text[match.start() : match.end()],
                            tag_id=tag.tag_id,
                            groups=tag.groups,
                        )
                    )
        selected = []
        for mention in sorted(
            mentions,
            key=lambda value: (
                value.tag_id,
                value.start,
                -(value.end - value.start),
            ),
        ):
            if any(
                existing.tag_id == mention.tag_id
                and existing.start <= mention.start
                and existing.end >= mention.end
                for existing in selected
            ):
                continue
            selected.append(mention)
        return tuple(
            sorted(
                selected,
                key=lambda value: (
                    value.start,
                    value.end,
                    value.tag_id,
                ),
            )
        )


@dataclass(frozen=True)
class RoleCandidateBundle:
    hypotheses: tuple[RoleHypothesis, ...]
    segmentations: Mapping[str, tuple[Segment, ...]]


class DualPathRoleCandidateExtractor:
    name = "punctuation_and_kylin_adaptive_role_union"

    def __init__(
        self,
        matcher: HighRecallRoleHypothesisMatcher,
        adaptive: AdaptiveGlobalEmbeddingPartitionSegmenter,
        registry: CanonicalTagRegistry,
    ):
        self.matcher = matcher
        self.adaptive = adaptive
        self.registry = registry

    def extract(self, text: str) -> RoleCandidateBundle:
        punctuation = build_result(
            "punctuation_only",
            text,
            punctuation_boundaries(text),
        )
        results = {
            punctuation.algorithm: punctuation,
            self.adaptive.name: self.adaptive.segment(text),
        }
        hypotheses = []
        for name, result in results.items():
            for segment in result.segments:
                hypotheses.extend(
                    self.matcher.match(
                        segment.text,
                        offset=segment.start,
                        source=name,
                    ).hypotheses
                )
        for mention in self.registry.find_mentions(text):
            for group in mention.groups:
                hypotheses.append(
                    RoleHypothesis(
                        start=mention.start,
                        end=mention.end,
                        text=mention.text,
                        group=group,
                        label=f"{group}_canonical_mention",
                        score=1.0,
                        similarity=1.0,
                        null_margin=1.0,
                        competition_margin=0.0,
                        sources=("canonical_alias",),
                    )
                )
        merged: dict[tuple[int, int, str], RoleHypothesis] = {}
        for hypothesis in hypotheses:
            key = (
                hypothesis.start,
                hypothesis.end,
                hypothesis.group,
            )
            previous = merged.get(key)
            if previous is None or hypothesis.score > previous.score:
                merged[key] = hypothesis
            elif math.isclose(hypothesis.score, previous.score):
                merged[key] = RoleHypothesis(
                    **{
                        **previous.__dict__,
                        "sources": tuple(
                            sorted(
                                set(previous.sources)
                                | set(hypothesis.sources)
                            )
                        ),
                    }
                )
        return RoleCandidateBundle(
            hypotheses=tuple(
                sorted(
                    merged.values(),
                    key=lambda value: (
                        value.start,
                        value.end,
                        value.group,
                        -value.score,
                    ),
                )
            ),
            segmentations={
                name: result.segments
                for name, result in results.items()
            },
        )


class CanonicalEmbeddingMatcher:
    def __init__(
        self,
        embedder: TextEmbedder,
        registry: CanonicalTagRegistry,
        *,
        min_similarity: Mapping[str, float] | None = None,
        top_k_per_hypothesis: int = 2,
    ):
        self.embedder = embedder
        self.registry = registry
        self.min_similarity = {
            "condition": 0.50,
            "object": 0.50,
            **dict(min_similarity or {}),
        }
        self.top_k_per_hypothesis = top_k_per_hypothesis
        self.tag_vectors = {}
        for tag in registry.tags:
            values = tuple(
                dict.fromkeys((tag.name, *tag.aliases, *tag.prototypes))
            )
            self.tag_vectors[tag.tag_id] = _unit_rows(
                self.embedder.embed(list(values))
            )

    def match(
        self,
        hypotheses: Sequence[RoleHypothesis],
        *,
        allowed_tag_ids: Mapping[str, Collection[str]] | None = None,
        top_k_per_hypothesis: int | None = None,
        include_below_threshold: bool = False,
    ) -> tuple[CanonicalRoleMatch, ...]:
        top_k = (
            self.top_k_per_hypothesis
            if top_k_per_hypothesis is None
            else top_k_per_hypothesis
        )
        if top_k < 1:
            raise ValueError("top_k_per_hypothesis must be positive")
        relevant = [
            hypothesis
            for hypothesis in hypotheses
            if hypothesis.group in {"condition", "object"}
        ]
        if not relevant:
            return ()
        unique_texts = list(dict.fromkeys(item.text for item in relevant))
        vectors = _unit_rows(self.embedder.embed(unique_texts))
        by_text = dict(zip(unique_texts, vectors))
        matches = []
        for hypothesis in relevant:
            exact = self.registry.exact_tag(
                hypothesis.text,
                hypothesis.group,
            )
            eligible = self.registry.eligible(hypothesis.group)
            if allowed_tag_ids is not None:
                allowed = set(
                    allowed_tag_ids.get(hypothesis.group, ())
                )
                if allowed:
                    eligible = tuple(
                        tag for tag in eligible if tag.tag_id in allowed
                    )
            similarities = [
                (
                    _class_similarity(
                        by_text[hypothesis.text],
                        self.tag_vectors[tag.tag_id],
                    ),
                    tag,
                )
                for tag in eligible
            ]
            ranked = []
            for similarity, tag in similarities:
                alternatives = [
                    value
                    for value, other in similarities
                    if other.tag_id != tag.tag_id
                ]
                competition_margin = (
                    similarity - max(alternatives)
                    if alternatives
                    else similarity
                )
                exact_alias = exact is not None and tag.tag_id == exact.tag_id
                score = (
                    similarity
                    + (0.16 if exact_alias else 0.0)
                    + 0.10 * max(0.0, competition_margin)
                )
                if (
                    exact_alias
                    or include_below_threshold
                    or similarity
                    >= self.min_similarity[hypothesis.group]
                ):
                    ranked.append(
                        (
                            score,
                            similarity,
                            exact_alias,
                            competition_margin,
                            tag,
                        )
                    )
            for (
                score,
                similarity,
                exact_alias,
                competition_margin,
                tag,
            ) in sorted(
                ranked,
                key=lambda value: (-value[0], value[4].tag_id),
            )[:top_k]:
                matches.append(
                    CanonicalRoleMatch(
                        start=hypothesis.start,
                        end=hypothesis.end,
                        text=hypothesis.text,
                        group=hypothesis.group,
                        tag_id=tag.tag_id,
                        tag_name=tag.name,
                        score=score,
                        similarity=similarity,
                        exact_alias=exact_alias,
                        hypothesis_score=hypothesis.score,
                        sources=hypothesis.sources,
                        competition_margin=competition_margin,
                    )
                )
        deduplicated = {}
        for match in matches:
            key = (match.start, match.end, match.group, match.tag_id)
            previous = deduplicated.get(key)
            if previous is None or (
                match.score,
                match.hypothesis_score,
            ) > (
                previous.score,
                previous.hypothesis_score,
            ):
                deduplicated[key] = match
        return tuple(
            sorted(
                deduplicated.values(),
                key=lambda value: (
                    value.start,
                    value.end,
                    value.group,
                    -value.score,
                    value.tag_id,
                ),
            )
        )


@dataclass(frozen=True)
class ScalarAnchor:
    name: str
    value: float
    prototypes: tuple[str, ...]


ATTITUDE_VALUE_ANCHORS_V1: tuple[ScalarAnchor, ...] = (
    ScalarAnchor(
        "strong_negative",
        -1.0,
        ("强烈反对绝对不要", "明确禁止任何情况下都不要"),
    ),
    ScalarAnchor(
        "negative",
        -0.70,
        ("明确不喜欢并要求避免", "不适合希望更换"),
    ),
    ScalarAnchor(
        "weak_negative",
        -0.35,
        ("不太喜欢最好少用", "倾向于不要采用"),
    ),
    ScalarAnchor(
        "uncertain",
        0.0,
        ("态度不确定还要考虑", "随意都可以尚未决定"),
    ),
    ScalarAnchor(
        "weak_positive",
        0.35,
        (
            "勉强可以或许采用",
            "可以考虑暂时使用",
            "或许应该换成另一个明确方案",
        ),
    ),
    ScalarAnchor(
        "positive",
        0.70,
        (
            "明确偏好并优先采用",
            "认可并希望继续使用",
            "决定改用或换成指定对象",
            "请求执行创建计算填写修改等明确操作",
            "要求在发送或执行操作前先获得用户确认批准",
            "please perform the requested create calculate fill or update action",
        ),
    ),
    ScalarAnchor(
        "strong_positive",
        1.0,
        ("强烈偏好必须优先使用", "始终默认固定采用"),
    ),
)


class AttitudeValueMatcher:
    def __init__(
        self,
        embedder: TextEmbedder,
        *,
        anchors: Sequence[ScalarAnchor] = ATTITUDE_VALUE_ANCHORS_V1,
        temperature: float = 0.08,
    ):
        self.embedder = embedder
        self.anchors = tuple(anchors)
        self.temperature = temperature
        flattened = [
            prototype
            for anchor in self.anchors
            for prototype in anchor.prototypes
        ]
        matrix = _unit_rows(self.embedder.embed(flattened))
        self.anchor_vectors = {}
        cursor = 0
        for anchor in self.anchors:
            end = cursor + len(anchor.prototypes)
            self.anchor_vectors[anchor.name] = matrix[cursor:end]
            cursor = end

    def match(
        self,
        hypotheses: Sequence[RoleHypothesis],
    ) -> tuple[AttitudeValue, ...]:
        relevant = [
            hypothesis
            for hypothesis in hypotheses
            if hypothesis.group == "attitude"
        ]
        if not relevant:
            return ()
        unique_texts = list(dict.fromkeys(item.text for item in relevant))
        vectors = _unit_rows(self.embedder.embed(unique_texts))
        by_text = dict(zip(unique_texts, vectors))
        values = []
        for hypothesis in relevant:
            scores = []
            for anchor in self.anchors:
                similarity = _class_similarity(
                    by_text[hypothesis.text],
                    self.anchor_vectors[anchor.name],
                )
                if (
                    hypothesis.label == "attitude_positive"
                    and anchor.value > 0
                ):
                    similarity += 0.035
                elif (
                    hypothesis.label == "attitude_negative"
                    and anchor.value < 0
                ):
                    similarity += 0.035
                elif (
                    hypothesis.label == "attitude_uncertain"
                    and anchor.value == 0
                ):
                    similarity += 0.035
                scores.append(similarity)
            maximum = max(scores)
            weights = np.exp(
                (np.asarray(scores, dtype=np.float64) - maximum)
                / self.temperature
            )
            weights /= np.sum(weights)
            value = float(
                sum(
                    weight * anchor.value
                    for weight, anchor in zip(weights, self.anchors)
                )
            )
            best_index = max(
                range(len(self.anchors)),
                key=lambda index: (scores[index], -index),
            )
            if abs(value) <= 0.10:
                best_anchor_value = self.anchors[best_index].value
                if best_anchor_value > 0:
                    value = 0.14
                elif best_anchor_value < 0:
                    value = -0.14
            values.append(
                AttitudeValue(
                    start=hypothesis.start,
                    end=hypothesis.end,
                    text=hypothesis.text,
                    value=max(-1.0, min(1.0, value)),
                    anchor=self.anchors[best_index].name,
                    confidence=float(weights[best_index]),
                    similarity=float(scores[best_index]),
                    hypothesis_score=hypothesis.score,
                    sources=hypothesis.sources,
                )
            )
        return tuple(
            sorted(
                values,
                key=lambda value: (
                    value.start,
                    value.end,
                    -value.hypothesis_score,
                ),
            )
        )


def temporal_values(
    hypotheses: Sequence[RoleHypothesis],
    initialization: Mapping[
        str,
        TemporalInitialization,
    ] = TEMPORAL_INITIALIZATION_V1,
) -> tuple[TemporalValue, ...]:
    values = []
    for hypothesis in hypotheses:
        if hypothesis.group != "temporal":
            continue
        policy = initialization.get(hypothesis.label)
        if policy is None:
            continue
        confidence = max(
            0.0,
            min(1.0, (hypothesis.similarity - 0.42) / 0.45),
        )
        values.append(
            TemporalValue(
                start=hypothesis.start,
                end=hypothesis.end,
                text=hypothesis.text,
                label=hypothesis.label,
                promotion_seed=policy.promotion_seed,
                explicit_long_term=policy.explicit_long_term,
                confidence=confidence,
                hypothesis_score=hypothesis.score,
                competition_margin=hypothesis.competition_margin,
                sources=hypothesis.sources,
            )
        )
    deduplicated = {}
    for value in values:
        key = (value.start, value.end, value.label)
        previous = deduplicated.get(key)
        if previous is None or value.confidence > previous.confidence:
            deduplicated[key] = value
    return tuple(
        sorted(
            deduplicated.values(),
            key=lambda value: (value.start, value.end, value.label),
        )
    )


def _gap(left_start: int, left_end: int, right_start: int, right_end: int) -> int:
    if left_start < right_end and right_start < left_end:
        return 0
    if left_end <= right_start:
        return right_start - left_end
    return left_start - right_end


def _same_clause(text: str, left_end: int, right_start: int) -> bool:
    start, end = sorted((left_end, right_start))
    return not any(
        character in "，,；;：:。！？!?\n"
        for character in text[start:end]
    )


def _clause_ranges(text: str) -> tuple[tuple[int, int], ...]:
    ranges = []
    start = 0
    for index, character in enumerate(text):
        if character not in "，,；;：:。！？!?\n":
            continue
        end = index + 1
        if start < end:
            ranges.append((start, end))
        start = end
    if start < len(text):
        ranges.append((start, len(text)))
    return tuple(ranges)


_CJK_REQUEST_MARKER = re.compile(
    r"(?:请|麻烦|帮(?:我)?|我(?:想|要|需要|希望)|"
    r"按(?:照)?|沿用|继续|接着|还是|仍然|这次|本次|先|再|然后)"
)
_CJK_COMMAND_VERB = re.compile(
    r"(?:处理|整理|填(?:写|入|好|满)?|补(?:齐|全|上|完整)?|"
    r"创建|新建|生成|计算|统计|汇总|复制|导出|排序|调整|"
    r"修改|设置|保留|隐藏|拆分|拼接|核对|使用|采用|改用|"
    r"换成|删除|清理|转换|转置|标记|显示|绘制|制作|建立|"
    r"插入|冻结|缩小|放大|完成|算出|安排|检查|提取)"
)
_CJK_NEGATIVE_COMMAND = re.compile(
    r"(?:不要|别|避免|禁止|不再|无需).{0,6}$"
)
_ENGLISH_REQUEST_MARKER = re.compile(
    r"\b(?:please|help\s+me|could\s+you|would\s+you|can\s+you|"
    r"i\s+(?:need|want|would\s+like)|let(?:'s|\s+us)|"
    r"need\s+to|have\s+to)\b",
    re.IGNORECASE,
)
_ENGLISH_COMMAND_VERB = re.compile(
    r"\b(?:copy|add|create|sort|fill|hide|resize|export|calculate|"
    r"build|clean|format|set|replace|remove|insert|transpose|"
    r"highlight|split|summarize|extract|assign|reorder|pad|freeze|"
    r"zoom|show|keep|use|update|make|move|convert|generate|apply|"
    r"select|write|place|finish)\b",
    re.IGNORECASE,
)
_ENGLISH_NEGATIVE_COMMAND = re.compile(
    r"\b(?:do\s+not|don't|never|avoid|must\s+not)\b.{0,24}$",
    re.IGNORECASE,
)
_FACTUAL_EVENT_MARKER = re.compile(
    r"(?:系统日志|系统事件|程序包|应用程序.{0,8}进程|服务.{0,8}"
    r"(?:同步|通知|记录)|已经.{0,12}(?:创建|完成|设置|同步)|"
    r"\b(?:service|system|package|process)\b.{0,32}"
    r"\b(?:received|created|set|synchronized|recorded|reported)\b)",
    re.IGNORECASE,
)


class PreferenceFrameAssembler:
    def __init__(
        self,
        *,
        max_role_distance: int = 48,
        min_attitude_similarity: float = 0.50,
        min_attitude_hypothesis_score: float = 0.645,
    ):
        self.max_role_distance = max_role_distance
        self.min_attitude_similarity = min_attitude_similarity
        self.min_attitude_hypothesis_score = (
            min_attitude_hypothesis_score
        )

    def assemble(
        self,
        text: str,
        canonical: Sequence[CanonicalRoleMatch],
        attitudes: Sequence[AttitudeValue],
        temporals: Sequence[TemporalValue],
    ) -> tuple[PreferenceFrame, ...]:
        anchors = self._attitude_anchors(attitudes)
        conditions = self._canonical_mentions(
            canonical,
            group="condition",
        )
        objects = self._canonical_mentions(
            canonical,
            group="object",
        )
        anchors = self._with_command_attitudes(
            text,
            anchors,
            conditions,
            objects,
        )
        frames = []
        previous_object = None
        previous_conditions: list[CanonicalRoleMatch] = []
        clause_ranges = _clause_ranges(text)
        for clause_index, (clause_start, clause_end) in enumerate(
            clause_ranges
        ):
            local_attitudes = [
                attitude
                for attitude in anchors
                if clause_start <= attitude.start < clause_end
            ]
            local_objects = [
                match
                for match in objects
                if clause_start <= match.start < clause_end
            ]
            local_conditions = [
                match
                for match in conditions
                if clause_start <= match.start < clause_end
            ]
            available_conditions = [
                *local_conditions,
                *previous_conditions,
            ]
            if (
                not available_conditions
                and clause_index + 1 < len(clause_ranges)
            ):
                next_start, next_end = clause_ranges[clause_index + 1]
                available_conditions.extend(
                    match
                    for match in conditions
                    if next_start <= match.start < next_end
                    and not match.tag_id.startswith("condition:")
                )
            if previous_object is not None:
                available_conditions = [
                    match
                    for match in available_conditions
                    if not (
                        match.tag_id == previous_object.tag_id
                        and match.start == previous_object.start
                        and match.end == previous_object.end
                    )
                ]
            if local_conditions:
                previous_conditions = local_conditions
            pair_candidates = []
            for attitude in local_attitudes:
                for object_match in local_objects:
                    pair_candidates.append(
                        (
                            self._pair_score(
                                text,
                                attitude,
                                object_match,
                            ),
                            attitude,
                            object_match,
                        )
                    )
            used_attitudes: list[AttitudeValue] = []
            used_objects: list[CanonicalRoleMatch] = []
            for _, attitude, object_match in sorted(
                pair_candidates,
                key=lambda value: (
                    -value[0],
                    value[1].start,
                    value[2].start,
                    value[2].tag_id,
                ),
            ):
                if any(
                    attitude.start < existing.end
                    and existing.start < attitude.end
                    for existing in used_attitudes
                ):
                    continue
                if any(
                    object_match.start < existing.end
                    and existing.start < object_match.end
                    for existing in used_objects
                ):
                    continue
                frames.append(
                    self._build_frame(
                        text,
                        attitude,
                        object_match,
                        available_conditions,
                        temporals,
                    )
                )
                used_attitudes.append(attitude)
                used_objects.append(object_match)
                previous_object = object_match

            if local_objects or previous_object is None:
                continue
            carry_candidates = [
                attitude
                for attitude in local_attitudes
                if (
                    not any(
                        condition.start < attitude.end
                        and attitude.start < condition.end
                        for condition in local_conditions
                    )
                    and (
                        attitude.anchor == "uncertain"
                        or attitude.value <= -0.10
                        or bool(available_conditions)
                        or (
                            attitude.value >= 0.10
                            and attitude.hypothesis_score >= 0.76
                            and attitude.similarity >= 0.66
                        )
                    )
                )
            ]
            if not carry_candidates:
                continue
            attitude = max(
                carry_candidates,
                key=lambda value: (
                    value.hypothesis_score
                    + 0.12 * value.similarity
                    + 0.08 * value.confidence,
                    value.end - value.start,
                    -value.start,
                ),
            )
            frames.append(
                self._build_frame(
                    text,
                    attitude,
                    previous_object,
                    available_conditions,
                    temporals,
                )
            )
        deduplicated = {}
        for frame in frames:
            key = (
                frame.attitude.start,
                frame.attitude.end,
                frame.object.start,
                frame.object.end,
                frame.object.tag_id,
            )
            previous = deduplicated.get(key)
            if previous is None or frame.confidence > previous.confidence:
                deduplicated[key] = frame
        return tuple(
            sorted(
                deduplicated.values(),
                key=lambda value: (
                    value.source_start,
                    value.source_end,
                    -value.confidence,
                ),
            )
        )

    @staticmethod
    def _canonical_mentions(
        values: Sequence[CanonicalRoleMatch],
        *,
        group: str,
    ) -> list[CanonicalRoleMatch]:
        relevant = [
            value
            for value in values
            if value.group == group
            and (
                value.exact_alias
                or (
                    value.hypothesis_score >= 0.55
                    and (
                        (
                            value.similarity >= 0.66
                            and value.competition_margin >= 0.02
                        )
                        or (
                            value.similarity >= 0.60
                            and value.competition_margin >= 0.05
                        )
                    )
                )
            )
        ]
        deduplicated = {}
        for value in relevant:
            key = (value.start, value.end, value.tag_id)
            previous = deduplicated.get(key)
            if previous is None or (
                value.exact_alias,
                value.score,
                value.hypothesis_score,
            ) > (
                previous.exact_alias,
                previous.score,
                previous.hypothesis_score,
            ):
                deduplicated[key] = value
        ranked = sorted(
            deduplicated.values(),
            key=lambda value: (
                not value.exact_alias,
                -value.score,
                -(value.end - value.start),
                value.start,
                value.tag_id,
            ),
        )
        selected = []
        for value in ranked:
            if any(
                existing.tag_id == value.tag_id
                and existing.start <= value.start
                and existing.end >= value.end
                for existing in selected
            ):
                continue
            selected.append(value)
        return sorted(
            selected,
            key=lambda value: (
                value.start,
                value.end,
                value.tag_id,
            ),
        )

    def _with_command_attitudes(
        self,
        text: str,
        attitudes: Sequence[AttitudeValue],
        conditions: Sequence[CanonicalRoleMatch],
        objects: Sequence[CanonicalRoleMatch],
    ) -> list[AttitudeValue]:
        values = list(attitudes)
        candidates: dict[
            tuple[int, int, str],
            tuple[CanonicalRoleMatch, AttitudeValue],
        ] = {}
        for object_match in objects:
            if any(
                condition.start < object_match.end
                and object_match.start < condition.end
                for condition in conditions
            ):
                continue
            clause_start, clause_end = self._containing_clause(
                text,
                object_match.start,
            )
            nearby_attitudes = [
                attitude
                for attitude in values
                if (
                    clause_start <= attitude.start < clause_end
                    and _gap(
                        attitude.start,
                        attitude.end,
                        object_match.start,
                        object_match.end,
                    )
                    <= self.max_role_distance
                )
            ]
            fallback = self._command_attitude(
                text,
                clause_start,
                clause_end,
                object_match,
            )
            if fallback is None:
                continue
            contradictory = [
                attitude
                for attitude in nearby_attitudes
                if (
                    attitude.start == fallback.start
                    and attitude.end == fallback.end
                    and attitude.value * fallback.value < 0.0
                )
            ]
            if nearby_attitudes and not contradictory:
                continue
            if contradictory:
                values = [
                    attitude
                    for attitude in values
                    if attitude not in contradictory
                ]
            if any(
                clause_start <= attitude.start < clause_end
                and _gap(
                    attitude.start,
                    attitude.end,
                    object_match.start,
                    object_match.end,
                )
                <= self.max_role_distance
                for attitude in values
            ):
                continue
            key = (clause_start, clause_end, object_match.tag_id)
            previous = candidates.get(key)
            if previous is None or self._fallback_object_rank(
                object_match
            ) > self._fallback_object_rank(previous[0]):
                candidates[key] = (object_match, fallback)
        values.extend(
            fallback
            for _, fallback in candidates.values()
        )
        return sorted(
            values,
            key=lambda value: (
                value.start,
                value.end,
                -value.hypothesis_score,
            ),
        )

    @staticmethod
    def _fallback_object_rank(
        value: CanonicalRoleMatch,
    ) -> tuple[float, float, float, int]:
        return (
            value.score,
            value.similarity,
            value.competition_margin,
            -(value.end - value.start),
        )

    @staticmethod
    def _containing_clause(
        text: str,
        position: int,
    ) -> tuple[int, int]:
        for start, end in _clause_ranges(text):
            if start <= position < end:
                return start, end
        return 0, len(text)

    @staticmethod
    def _command_attitude(
        text: str,
        clause_start: int,
        clause_end: int,
        object_match: CanonicalRoleMatch,
    ) -> AttitudeValue | None:
        clause = text[clause_start:clause_end]
        explicit_request = (
            _CJK_REQUEST_MARKER.search(clause)
            or _ENGLISH_REQUEST_MARKER.search(clause)
        )
        if _FACTUAL_EVENT_MARKER.search(clause) and explicit_request is None:
            return None

        marker = explicit_request
        if marker is None:
            marker = (
                _CJK_COMMAND_VERB.search(clause)
                or _ENGLISH_COMMAND_VERB.search(clause)
            )
        if marker is None:
            return None

        local_start = marker.start()
        local_end = marker.end()
        prefix = clause[max(0, local_start - 24) : local_start]
        negative = bool(
            _CJK_NEGATIVE_COMMAND.search(prefix)
            or _ENGLISH_NEGATIVE_COMMAND.search(prefix)
        )
        if not negative:
            negative = bool(
                re.fullmatch(
                    r"(?:不要|别|避免|禁止|不再|无需)",
                    marker.group(0),
                )
                or re.fullmatch(
                    r"(?:do\s+not|don't|never|avoid|must\s+not)",
                    marker.group(0),
                    re.IGNORECASE,
                )
            )
        start = clause_start + local_start
        end = clause_start + local_end
        if not (
            clause_start <= object_match.start < clause_end
            and start < end
        ):
            return None
        return AttitudeValue(
            start=start,
            end=end,
            text=text[start:end],
            value=-0.42 if negative else 0.42,
            anchor="weak_negative" if negative else "positive",
            confidence=0.68,
            similarity=0.72,
            hypothesis_score=0.72,
            sources=("command_attitude_fallback",),
        )

    def _attitude_anchors(
        self,
        values: Sequence[AttitudeValue],
    ) -> list[AttitudeValue]:
        return sorted(
            (
                value
                for value in values
                if (
                    value.similarity >= self.min_attitude_similarity
                    and value.hypothesis_score
                    >= self.min_attitude_hypothesis_score
                    and not (
                        value.value >= 0.10
                        and value.hypothesis_score < 0.65
                    )
                )
            ),
            key=lambda value: (
                value.start,
                value.end,
                -value.hypothesis_score,
            ),
        )

    def _pair_score(
        self,
        text: str,
        attitude: AttitudeValue,
        object_match: CanonicalRoleMatch,
    ) -> float:
        distance = _gap(
            attitude.start,
            attitude.end,
            object_match.start,
            object_match.end,
        )
        return (
            0.48 * attitude.hypothesis_score
            + 0.17 * attitude.similarity
            + 0.08 * attitude.confidence
            + 0.20 * object_match.score
            + 0.07 * object_match.hypothesis_score
            + 0.08 * max(0.0, object_match.competition_margin)
            + (0.16 if object_match.exact_alias else 0.0)
            + self._structural_bonus(
                text,
                attitude,
                object_match,
                "object",
            )
            - 0.012 * distance
        )

    def _build_frame(
        self,
        text: str,
        attitude: AttitudeValue,
        object_match: CanonicalRoleMatch,
        conditions: Sequence[CanonicalRoleMatch],
        temporals: Sequence[TemporalValue],
    ) -> PreferenceFrame:
        condition = self._best_role(
            text,
            attitude,
            [
                match
                for match in conditions
                if not (
                    match.start == object_match.start
                    and match.end == object_match.end
                )
            ],
            group="condition",
        )
        temporal = self._best_temporal(text, attitude, temporals)
        source_start = min(
            value
            for value in (
                attitude.start,
                object_match.start,
                condition.start if condition else attitude.start,
                temporal.start if temporal else attitude.start,
            )
        )
        source_end = max(
            value
            for value in (
                attitude.end,
                object_match.end,
                condition.end if condition else attitude.end,
                temporal.end if temporal else attitude.end,
            )
        )
        relation_text = text[
            min(attitude.end, object_match.end) :
            max(attitude.start, object_match.start)
        ].strip()
        confidence = (
            0.42 * min(1.0, attitude.similarity)
            + 0.38 * min(1.0, object_match.score)
            + 0.12
            * (
                min(1.0, condition.score)
                if condition is not None
                else 0.5
            )
            + 0.08
            * (
                temporal.confidence
                if temporal is not None
                else 0.5
            )
            + (0.14 if object_match.exact_alias else 0.0)
            + 0.12
            * min(
                1.0,
                max(0.0, object_match.competition_margin) / 0.12,
            )
            + (
                0.06
                if (
                    not object_match.exact_alias
                    and object_match.similarity >= 0.70
                    and object_match.competition_margin >= 0.08
                )
                else 0.0
            )
        )
        return PreferenceFrame(
            condition=condition,
            temporal=temporal,
            attitude=attitude,
            object=object_match,
            confidence=max(
                0.0,
                min(
                    1.0 if object_match.exact_alias else 0.98,
                    confidence,
                ),
            ),
            relation_text=relation_text,
            source_start=source_start,
            source_end=source_end,
        )

    def _best_role(
        self,
        text: str,
        attitude: AttitudeValue,
        matches: Sequence[CanonicalRoleMatch],
        *,
        group: str,
    ) -> CanonicalRoleMatch | None:
        ranked = []
        for match in matches:
            distance = _gap(
                attitude.start,
                attitude.end,
                match.start,
                match.end,
            )
            if distance > self._distance_limit(
                text,
                attitude.start,
                match.start,
            ):
                continue
            if not _same_clause(text, attitude.end, match.start):
                distance += 12
            structural = self._structural_bonus(
                text,
                attitude,
                match,
                group,
            )
            score = (
                0.62 * match.score
                + 0.25 * match.hypothesis_score
                + structural
                - 0.012 * distance
            )
            ranked.append((score, -distance, match))
        if not ranked:
            return None
        return max(
            ranked,
            key=lambda value: (
                value[0],
                value[1],
                value[2].exact_alias,
                -value[2].start,
                value[2].tag_id,
            ),
        )[2]

    @staticmethod
    def _structural_bonus(
        text: str,
        attitude: AttitudeValue,
        match: CanonicalRoleMatch,
        group: str,
    ) -> float:
        if group == "object":
            overlaps = (
                attitude.start < match.end
                and match.start < attitude.end
            )
            if overlaps:
                if (
                    "semantic_task_core" in attitude.sources
                    and "semantic_task_core" in match.sources
                ):
                    return 0.04
                return -0.22
            bonus = 0.10 if match.start >= attitude.end else 0.06
            between = text[
                min(attitude.end, match.end) :
                max(attitude.start, match.start)
            ]
            if any(
                marker in between
                for marker in ("用", "采用", "换成", "交给", "选择", "按")
            ):
                bonus += 0.14
            if match.start == attitude.end:
                bonus += 0.18
            elif (
                match.start >= attitude.end
                and match.start - attitude.end <= 4
            ):
                bonus += 0.10
            elif attitude.start == match.end:
                bonus += 0.22
            return bonus

        bonus = 0.10 if match.end <= attitude.start else 0.02
        prefix = text[max(0, match.start - 2) : match.start]
        suffix = text[match.end : min(len(text), match.end + 2)]
        if "在" in prefix or any(
            marker in suffix for marker in ("中", "里", "内", "时")
        ):
            bonus += 0.16
        return bonus

    def _distance_limit(
        self,
        text: str,
        left_position: int,
        right_position: int,
    ) -> int:
        for start, end in _clause_ranges(text):
            if (
                start <= left_position < end
                and start <= right_position < end
            ):
                return max(self.max_role_distance, end - start)
        return self.max_role_distance

    def _best_temporal(
        self,
        text: str,
        attitude: AttitudeValue,
        values: Sequence[TemporalValue],
    ) -> TemporalValue | None:
        candidates = []
        for value in values:
            overlaps_attitude = (
                value.start < attitude.end
                and attitude.start < value.end
            )
            distance = _gap(
                attitude.start,
                attitude.end,
                value.start,
                value.end,
            )
            if distance > self._distance_limit(
                text,
                attitude.start,
                value.start,
            ):
                continue
            preceding_bonus = 0.12 if value.end <= attitude.start else 0.0
            score = (
                0.42 * value.hypothesis_score
                + 0.28 * value.confidence
                + 0.30 * value.competition_margin
                + preceding_bonus
                - 0.012 * distance
                - 0.006 * len(value.text)
                - (0.08 if overlaps_attitude else 0.0)
            )
            candidates.append((score, -distance, value))
        return (
            max(
                candidates,
                key=lambda item: (
                    item[0],
                    item[1],
                    item[2].explicit_long_term,
                    -item[2].start,
                ),
            )[2]
            if candidates
            else None
        )


class PreferenceFrameMatcher:
    name = "kylin_dual_path_preference_frame_v1"

    def __init__(
        self,
        embedder: TextEmbedder,
        *,
        tokenizer: SpanTokenizer | None = None,
        tags: Sequence[CanonicalTag] = DEFAULT_CANONICAL_TAGS_V1,
        attitude_anchors: Sequence[
            ScalarAnchor
        ] = ATTITUDE_VALUE_ANCHORS_V1,
        temporal_initialization: Mapping[
            str,
            TemporalInitialization,
        ] = TEMPORAL_INITIALIZATION_V1,
    ):
        tokenizer = tokenizer or JiebaSpanTokenizer()
        registry = CanonicalTagRegistry(tags)
        scorer = PrototypeEmbeddingScorer(embedder)
        role_matcher = HighRecallRoleHypothesisMatcher(scorer, tokenizer)
        adaptive = AdaptiveGlobalEmbeddingPartitionSegmenter(
            embedder,
            min_window_chars=4,
            max_window_chars=8,
            step_chars=1,
            min_segment_windows=2,
            slope_multiplier=2.0,
        )
        self.extractor = DualPathRoleCandidateExtractor(
            role_matcher,
            adaptive,
            registry,
        )
        self.canonical_matcher = CanonicalEmbeddingMatcher(
            embedder,
            registry,
        )
        self.attitude_matcher = AttitudeValueMatcher(
            embedder,
            anchors=attitude_anchors,
        )
        self.temporal_initialization = dict(
            temporal_initialization
        )
        self.assembler = PreferenceFrameAssembler()

    def match(
        self,
        text: str,
        *,
        options: PreferenceObservationOptions | None = None,
    ) -> PreferenceFrameResult:
        bundle = self.extractor.extract(text)
        canonical = self.canonical_matcher.match(bundle.hypotheses)
        if options is not None:
            condition_ids = set(options.condition_tag_ids)
            object_ids = set(options.object_tag_ids)
            canonical = tuple(
                match
                for match in canonical
                if (
                    match.group == "condition"
                    and (
                        not condition_ids
                        or match.tag_id in condition_ids
                    )
                )
                or (
                    match.group == "object"
                    and (
                        not object_ids
                        or match.tag_id in object_ids
                    )
                )
            )
        attitudes = self.attitude_matcher.match(bundle.hypotheses)
        temporals = temporal_values(
            bundle.hypotheses,
            self.temporal_initialization,
        )
        if options is not None and options.temporal_labels:
            allowed_temporal = set(options.temporal_labels)
            temporals = tuple(
                value
                for value in temporals
                if value.label in allowed_temporal
            )
        frames = self.assembler.assemble(
            text,
            canonical,
            attitudes,
            temporals,
        )
        attitudes = _merge_frame_attitudes(attitudes, frames)
        return PreferenceFrameResult(
            algorithm=self.name,
            text=text,
            hypotheses=bundle.hypotheses,
            canonical_matches=canonical,
            attitudes=attitudes,
            temporals=temporals,
            frames=frames,
            diagnostics={
                "segmentations": {
                    name: [
                        {
                            "start": segment.start,
                            "end": segment.end,
                            "text": segment.text,
                        }
                        for segment in segments
                    ]
                    for name, segments in bundle.segmentations.items()
                },
                "hypothesis_count": len(bundle.hypotheses),
                "canonical_match_count": len(canonical),
                "attitude_count": len(attitudes),
                "temporal_count": len(temporals),
                "frame_count": len(frames),
                "option_constraints": {
                    "condition_tag_ids": (
                        list(options.condition_tag_ids)
                        if options is not None
                        else []
                    ),
                    "object_tag_ids": (
                        list(options.object_tag_ids)
                        if options is not None
                        else []
                    ),
                    "temporal_labels": (
                        list(options.temporal_labels)
                        if options is not None
                        else []
                    ),
                },
            },
        )


def _merge_frame_attitudes(
    attitudes: Sequence[AttitudeValue],
    frames: Sequence[PreferenceFrame],
) -> tuple[AttitudeValue, ...]:
    merged = {
        (
            value.start,
            value.end,
            value.anchor,
            value.sources,
        ): value
        for value in attitudes
    }
    for frame in frames:
        value = frame.attitude
        merged.setdefault(
            (
                value.start,
                value.end,
                value.anchor,
                value.sources,
            ),
            value,
        )
    return tuple(
        sorted(
            merged.values(),
            key=lambda value: (
                value.start,
                value.end,
                value.anchor,
            ),
        )
    )


class PreferenceObservationMemoryExtractor:
    """Turn one source Observation into auditable preference evidence."""

    def __init__(self, matcher: PreferenceFrameMatching):
        self.matcher = matcher

    def extract(
        self,
        observation: PreferenceSourceObservation,
        *,
        options: PreferenceObservationOptions | None = None,
    ) -> PreferenceObservationExtraction:
        result = self.matcher.match(
            observation.content,
            options=options,
        )
        memories = []
        for frame in result.frames:
            temporal = frame.temporal
            condition = frame.condition
            identity = (
                f"{observation.observation_id}|"
                f"{frame.object.tag_id}|"
                f"{frame.attitude.start}|{frame.attitude.end}|"
                f"{frame.object.start}|{frame.object.end}"
            )
            memories.append(
                PreferenceObservationMemory(
                    memory_id=_stable_identifier("obs_pref", identity),
                    observation_id=observation.observation_id,
                    source_event_id=observation.source_event_id,
                    user_id=observation.user_id,
                    session_id=observation.session_id,
                    observed_time=observation.event_time,
                    source_text=observation.content,
                    condition_tag_id=(
                        condition.tag_id if condition is not None else ""
                    ),
                    condition_name=(
                        condition.tag_name if condition is not None else ""
                    ),
                    condition_text=(
                        condition.text if condition is not None else ""
                    ),
                    object_tag_id=frame.object.tag_id,
                    object_name=frame.object.tag_name,
                    object_text=frame.object.text,
                    attitude_value=frame.attitude.value,
                    attitude_anchor=frame.attitude.anchor,
                    attitude_confidence=frame.attitude.confidence,
                    temporal_label=(
                        temporal.label if temporal is not None else ""
                    ),
                    promotion_seed=(
                        temporal.promotion_seed
                        if temporal is not None
                        else 0.0
                    ),
                    explicit_long_term=bool(
                        temporal is not None
                        and temporal.explicit_long_term
                    ),
                    extraction_confidence=frame.confidence,
                    source_start=frame.source_start,
                    source_end=frame.source_end,
                )
            )
        evidence = tuple(
            memory.to_evidence(
                source_reliability=observation.source_reliability,
                privacy=observation.privacy,
            )
            for memory in memories
        )
        return PreferenceObservationExtraction(
            observation_id=observation.observation_id,
            memories=tuple(memories),
            evidence=evidence,
            frame_result=result,
        )
