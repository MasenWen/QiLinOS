from __future__ import annotations

import math
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol, Sequence

import numpy as np

from .span_segmentation import TextEmbedder


LABEL_PROTOTYPES: dict[str, tuple[str, ...]] = {
    "attitude_positive": (
        "用户明确表示偏好",
        "优先采用某种方式",
        "默认选择这个方案",
        "继续保持原来的做法",
        "认可并希望使用",
        "决定改用或换成另一个明确方案",
        "用户请求执行一项明确的办公操作",
        "要求在发送或执行操作前先获得用户确认批准",
        "创建计算填写修改或整理指定内容",
        "please create calculate fill update or organize the requested work",
    ),
    "attitude_negative": (
        "用户明确表示不喜欢",
        "要求避免某种方式",
        "不要继续使用",
        "不适合并希望更换",
        "撤销之前的选择",
    ),
    "attitude_uncertain": (
        "态度不确定还要考虑",
        "或许可以暂时这样",
        "勉强可以接受",
        "尚未决定是否使用",
        "以后再讨论",
    ),
    "temporal_short": (
        "当前",
        "本次或这一次",
        "仅限当前会话或本轮任务",
        "今天或今晚",
        "临时或暂时有效",
        "刚才提到的或先前这次选择",
        "只在当前对象的这次操作中有效",
        "到本次任务结束时失效",
        "only for this task or session",
    ),
    "temporal_medium": (
        "近期",
        "后续",
        "这周或这个月",
        "接下来一段时间",
        "下次或下个月开始的一段时期",
        "后续几个阶段或未来几次任务",
        "在指定项目期间持续有效",
        "在同一个文件或项目中继续使用",
        "for the current project or a limited period",
    ),
    "temporal_long": (
        "以后",
        "今后",
        "每次",
        "今后默认执行",
        "以后所有类似任务都这样",
        "每次遇到这种情况都采用",
        "长期作为固定偏好",
        "始终作为通用规则",
        "适用于所有文件和项目",
        "跨不同文件和任务持续有效",
        "by default for all future tasks and objects",
    ),
    "object": (
        "具体办公应用或智能助手",
        "软件工具的具体名称",
        "图表类型或呈现形式",
        "文档模板或配置选项",
        "办公文件或工作产物",
        "任务采用的工具或方法",
    ),
    "condition": (
        "具体办公任务或工作场景",
        "执行某项工作时的适用条件",
        "文档撰写与报告整理任务",
        "业务数据分析与方案比较场景",
        "技术内容阅读与讲解任务",
        "日常沟通与信息交流场景",
        "邮件编写或会议记录任务",
        "经营数据与业务走势分析任务",
        "某类业务环节中的适用范围",
    ),
    "residual": (
        "礼貌性的请求",
        "与偏好无关的普通陈述",
        "催促尽快完成",
        "系统运行事实",
        "没有可提取的标签",
        "动作或流程关系而不是办公对象",
        "连接前后成分的普通动词",
    ),
}

PRIMARY_LABELS = tuple(
    label for label in LABEL_PROTOTYPES if label != "residual"
)
OUTPUT_ROLE_GROUPS = ("condition", "temporal", "attitude", "object")

CONSERVATIVE_GROUP_SCORE_THRESHOLDS_V1: dict[str, float] = {
    "temporal": 0.760,
    "attitude": 0.740,
    "object": 0.665,
}

FOUR_ROLE_GROUP_SCORE_THRESHOLDS_V1: dict[str, float] = {
    "condition": 0.590,
    "temporal": 0.760,
    "attitude": 0.670,
    "object": 0.660,
}

HIGH_RECALL_GROUP_MIN_SIMILARITY_V1: dict[str, float] = {
    "condition": 0.46,
    "temporal": 0.50,
    "attitude": 0.48,
    "object": 0.46,
}

HIGH_RECALL_GROUP_MIN_NULL_MARGIN_V1: dict[str, float] = {
    "condition": -0.08,
    "temporal": -0.06,
    "attitude": -0.08,
    "object": -0.10,
}


class SpanTokenizer(Protocol):
    def tokenize(self, text: str) -> Sequence["LexicalToken"]: ...


@dataclass(frozen=True)
class LexicalToken:
    text: str
    start: int
    end: int


@dataclass(frozen=True)
class CandidateSpan:
    start: int
    end: int
    text: str
    token_count: int


@dataclass(frozen=True)
class CandidateAssessment:
    candidate: CandidateSpan
    label: str
    similarity: float
    margin: float
    label_scores: Mapping[str, float]
    accepted: bool


@dataclass(frozen=True)
class GroupCandidateAssessment:
    candidate: CandidateSpan
    group: str
    label: str
    similarity: float
    null_similarity: float
    null_margin: float
    competition_margin: float
    label_scores: Mapping[str, float]
    accepted: bool


@dataclass(frozen=True)
class SpanMatch:
    start: int
    end: int
    text: str
    label: str
    score: float
    similarity: float
    margin: float
    source: str


@dataclass(frozen=True)
class SpanMatchingResult:
    algorithm: str
    text: str
    matches: tuple[SpanMatch, ...]
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def assert_valid(self) -> None:
        ordered = sorted(self.matches, key=lambda match: (match.start, match.end))
        for match in ordered:
            if not 0 <= match.start < match.end <= len(self.text):
                raise ValueError("span_match_outside_text")
            if self.text[match.start : match.end] != match.text:
                raise ValueError("span_match_offsets_do_not_match_text")
        for left, right in zip(ordered, ordered[1:]):
            if left.end > right.start:
                raise ValueError("span_matches_must_not_overlap")


@dataclass(frozen=True)
class RoleHypothesis:
    start: int
    end: int
    text: str
    group: str
    label: str
    score: float
    similarity: float
    null_margin: float
    competition_margin: float
    sources: tuple[str, ...]


@dataclass(frozen=True)
class RoleHypothesisResult:
    algorithm: str
    text: str
    hypotheses: tuple[RoleHypothesis, ...]
    diagnostics: Mapping[str, Any] = field(default_factory=dict)

    def assert_valid(self, *, offset: int = 0) -> None:
        for hypothesis in self.hypotheses:
            local_start = hypothesis.start - offset
            local_end = hypothesis.end - offset
            if not 0 <= local_start < local_end <= len(self.text):
                raise ValueError("role_hypothesis_outside_text")
            if self.text[local_start:local_end] != hypothesis.text:
                raise ValueError("role_hypothesis_offsets_do_not_match_text")
            if hypothesis.group not in OUTPUT_ROLE_GROUPS:
                raise ValueError("unknown_role_hypothesis_group")


class JiebaSpanTokenizer:
    """Candidate boundary adapter over Jieba's mature CJK tokenizer."""

    def __init__(self, tokenizer: Any | None = None):
        if tokenizer is None:
            try:
                import jieba
            except ImportError as exc:
                raise RuntimeError(
                    "jieba_is_required_for_span_matching_candidates"
                ) from exc
            tokenizer = jieba
        self.tokenizer = tokenizer

    def tokenize(self, text: str) -> tuple[LexicalToken, ...]:
        values = self.tokenizer.tokenize(text, HMM=True)
        tokens = tuple(
            LexicalToken(str(token), int(start), int(end))
            for token, start, end in values
            if int(start) < int(end)
        )
        if "".join(
            text[token.start : token.end]
            for token in tokens
            if not text[token.start : token.end].isspace()
        ).replace(" ", "") == "":
            return ()
        return tokens


class CharacterSpanTokenizer:
    """Dependency-free fallback for tests; every character is a token."""

    def tokenize(self, text: str) -> tuple[LexicalToken, ...]:
        return tuple(
            LexicalToken(character, index, index + 1)
            for index, character in enumerate(text)
        )


def _is_content(text: str) -> bool:
    return any(
        not character.isspace()
        and not unicodedata.category(character).startswith("P")
        for character in text
    )


def _content_length(text: str) -> int:
    return sum(
        not character.isspace()
        and not unicodedata.category(character).startswith("P")
        for character in text
    )


def _crosses_separator(text: str) -> bool:
    return any(
        character in "\n\r，,；;。！？!?"
        for character in text
    )


def enumerate_candidate_spans(
    text: str,
    tokenizer: SpanTokenizer,
    *,
    max_tokens: int = 4,
    max_chars: int = 28,
) -> tuple[CandidateSpan, ...]:
    tokens = [
        token
        for token in tokenizer.tokenize(text)
        if _is_content(text[token.start : token.end])
    ]
    candidates: dict[tuple[int, int], CandidateSpan] = {}
    for start_index, first in enumerate(tokens):
        for end_index in range(
            start_index,
            min(len(tokens), start_index + max_tokens),
        ):
            last = tokens[end_index]
            value = text[first.start : last.end]
            if _crosses_separator(value):
                break
            if len(value) > max_chars:
                break
            if _content_length(value) < 2:
                continue
            key = (first.start, last.end)
            candidates[key] = CandidateSpan(
                start=first.start,
                end=last.end,
                text=value,
                token_count=end_index - start_index + 1,
            )
    return tuple(
        candidates[key]
        for key in sorted(candidates, key=lambda value: (value[0], value[1]))
    )


def _normalize_rows(values: Any) -> np.ndarray:
    matrix = np.asarray(values, dtype=np.float32)
    if matrix.ndim == 1:
        matrix = matrix.reshape(1, -1)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    return matrix / np.clip(norms, 1e-9, None)


class PrototypeEmbeddingScorer:
    """Multi-prototype contrastive scorer with an explicit null competitor."""

    def __init__(
        self,
        embedder: TextEmbedder,
        prototypes: Mapping[str, Sequence[str]] = LABEL_PROTOTYPES,
        *,
        min_similarity: float = 0.50,
        min_margin: float = 0.012,
    ):
        if "residual" not in prototypes:
            raise ValueError("prototype_set_requires_residual_class")
        self.embedder = embedder
        self.prototypes = {
            str(label): tuple(str(value) for value in values)
            for label, values in prototypes.items()
        }
        self.min_similarity = float(min_similarity)
        self.min_margin = float(min_margin)
        flattened = [
            value
            for values in self.prototypes.values()
            for value in values
        ]
        matrix = _normalize_rows(self.embedder.embed(flattened))
        self.prototype_vectors: dict[str, np.ndarray] = {}
        cursor = 0
        for label, values in self.prototypes.items():
            end = cursor + len(values)
            self.prototype_vectors[label] = matrix[cursor:end]
            cursor = end

    @staticmethod
    def _class_similarity(
        vector: np.ndarray,
        prototypes: np.ndarray,
    ) -> float:
        similarities = np.sort(prototypes @ vector)[::-1]
        top = similarities[: min(2, len(similarities))]
        return float(0.70 * similarities[0] + 0.30 * np.mean(top))

    def assess(
        self,
        candidates: Sequence[CandidateSpan],
    ) -> tuple[CandidateAssessment, ...]:
        if not candidates:
            return ()
        vectors = _normalize_rows(
            self.embedder.embed([candidate.text for candidate in candidates])
        )
        assessments = []
        for candidate, vector in zip(candidates, vectors):
            scores = {
                label: self._class_similarity(vector, prototypes)
                for label, prototypes in self.prototype_vectors.items()
            }
            ranked = sorted(
                scores,
                key=lambda label: (-scores[label], label),
            )
            label = ranked[0]
            similarity = scores[label]
            margin = similarity - scores[ranked[1]]
            assessments.append(
                CandidateAssessment(
                    candidate=candidate,
                    label=label,
                    similarity=similarity,
                    margin=margin,
                    label_scores=scores,
                    accepted=(
                        label != "residual"
                        and similarity >= self.min_similarity
                        and margin >= self.min_margin
                    ),
                )
            )
        return tuple(assessments)

    def assess_by_group(
        self,
        candidates: Sequence[CandidateSpan],
        *,
        groups: Sequence[str] = OUTPUT_ROLE_GROUPS,
        min_similarity_by_group: Mapping[str, float] | None = None,
        min_null_margin_by_group: Mapping[str, float] | None = None,
    ) -> tuple[GroupCandidateAssessment, ...]:
        """Retain one hypothesis per role instead of one global argmax.

        A role only competes with the explicit residual/null class at this
        stage. Cross-role competition is preserved as a diagnostic margin and
        deferred to the contextual frame decoder.
        """
        if not candidates:
            return ()
        similarity_thresholds = {
            **HIGH_RECALL_GROUP_MIN_SIMILARITY_V1,
            **dict(min_similarity_by_group or {}),
        }
        null_margin_thresholds = {
            **HIGH_RECALL_GROUP_MIN_NULL_MARGIN_V1,
            **dict(min_null_margin_by_group or {}),
        }
        normalized_groups = tuple(dict.fromkeys(str(group) for group in groups))
        labels_by_group = {
            group: tuple(
                label
                for label in PRIMARY_LABELS
                if label_group(label) == group
            )
            for group in normalized_groups
        }
        if any(not labels for labels in labels_by_group.values()):
            raise ValueError("role_group_has_no_prototypes")

        vectors = _normalize_rows(
            self.embedder.embed([candidate.text for candidate in candidates])
        )
        assessments = []
        for candidate, vector in zip(candidates, vectors):
            scores = {
                label: self._class_similarity(vector, prototypes)
                for label, prototypes in self.prototype_vectors.items()
            }
            null_similarity = scores["residual"]
            for group in normalized_groups:
                group_labels = labels_by_group[group]
                label = max(
                    group_labels,
                    key=lambda value: (scores[value], value),
                )
                similarity = scores[label]
                competitors = [
                    scores[value]
                    for value in PRIMARY_LABELS
                    if label_group(value) != group
                ]
                competition_similarity = (
                    max(competitors) if competitors else null_similarity
                )
                null_margin = similarity - null_similarity
                competition_margin = similarity - competition_similarity
                assessments.append(
                    GroupCandidateAssessment(
                        candidate=candidate,
                        group=group,
                        label=label,
                        similarity=similarity,
                        null_similarity=null_similarity,
                        null_margin=null_margin,
                        competition_margin=competition_margin,
                        label_scores=scores,
                        accepted=(
                            similarity
                            >= similarity_thresholds.get(
                                group,
                                self.min_similarity,
                            )
                            and null_margin
                            >= null_margin_thresholds.get(
                                group,
                                self.min_margin,
                            )
                        ),
                    )
                )
        return tuple(assessments)


def _overlaps(left: CandidateSpan, right: CandidateSpan) -> bool:
    return left.start < right.end and right.start < left.end


def _match_score(assessment: CandidateAssessment) -> float:
    length_penalty = 0.004 * max(0, len(assessment.candidate.text) - 6)
    return (
        assessment.similarity
        + 1.5 * assessment.margin
        - length_penalty
    )


def _group_score_thresholds(
    values: Mapping[str, float] | None,
) -> dict[str, float]:
    thresholds = {
        str(group): float(score)
        for group, score in (values or {}).items()
    }
    for group, score in thresholds.items():
        if not group or not math.isfinite(score):
            raise ValueError("invalid_group_score_threshold")
    return thresholds


def _passes_group_score_threshold(
    assessment: CandidateAssessment,
    thresholds: Mapping[str, float],
) -> bool:
    threshold = thresholds.get(label_group(assessment.label))
    return threshold is None or _match_score(assessment) >= threshold


class MultiPrototypeContrastiveMatcher:
    """Independent contrastive span scoring followed by conservative packing."""

    name = "kylin_multi_prototype_contrastive"
    embedding_backed = True

    def __init__(
        self,
        scorer: PrototypeEmbeddingScorer,
        tokenizer: SpanTokenizer,
        *,
        max_tokens: int = 4,
        max_chars: int = 28,
        max_matches: int = 10,
        group_score_thresholds: Mapping[str, float] | None = None,
    ):
        self.scorer = scorer
        self.tokenizer = tokenizer
        self.max_tokens = max_tokens
        self.max_chars = max_chars
        self.max_matches = max_matches
        self.group_score_thresholds = _group_score_thresholds(
            group_score_thresholds
        )

    def match(self, text: str, *, offset: int = 0) -> SpanMatchingResult:
        candidates = enumerate_candidate_spans(
            text,
            self.tokenizer,
            max_tokens=self.max_tokens,
            max_chars=self.max_chars,
        )
        assessments = self.scorer.assess(candidates)
        accepted = [
            assessment
            for assessment in assessments
            if assessment.accepted
            and _passes_group_score_threshold(
                assessment,
                self.group_score_thresholds,
            )
        ]
        ranked = sorted(
            accepted,
            key=lambda assessment: (
                -_match_score(assessment),
                len(assessment.candidate.text),
                assessment.candidate.start,
                assessment.label,
            ),
        )
        selected: list[CandidateAssessment] = []
        for assessment in ranked:
            if any(
                _overlaps(assessment.candidate, existing.candidate)
                for existing in selected
            ):
                continue
            selected.append(assessment)
            if len(selected) >= self.max_matches:
                break
        matches = tuple(
            SpanMatch(
                start=offset + assessment.candidate.start,
                end=offset + assessment.candidate.end,
                text=assessment.candidate.text,
                label=assessment.label,
                score=_match_score(assessment),
                similarity=assessment.similarity,
                margin=assessment.margin,
                source=self.name,
            )
            for assessment in sorted(
                selected,
                key=lambda value: value.candidate.start,
            )
        )
        result = SpanMatchingResult(
            algorithm=self.name,
            text=text,
            matches=matches,
            diagnostics={
                "candidate_count": len(candidates),
                "accepted_candidate_count": len(accepted),
                "selected_count": len(matches),
                "group_score_thresholds": self.group_score_thresholds,
            },
        )
        _assert_result_with_offset(result, offset)
        return result


def _role_hypothesis_score(
    assessment: GroupCandidateAssessment,
) -> float:
    length_penalty = 0.003 * max(
        0,
        len(assessment.candidate.text) - 10,
    )
    return (
        assessment.similarity
        + 0.55 * assessment.null_margin
        + 0.15 * assessment.competition_margin
        - length_penalty
    )


class HighRecallRoleHypothesisMatcher:
    """Generate overlapping role hypotheses for contextual decoding."""

    name = "kylin_high_recall_role_hypotheses"
    embedding_backed = True

    def __init__(
        self,
        scorer: PrototypeEmbeddingScorer,
        tokenizer: SpanTokenizer,
        *,
        max_tokens: int = 6,
        max_chars: int = 40,
        max_hypotheses_per_group: int = 24,
        min_similarity_by_group: Mapping[str, float] | None = None,
        min_null_margin_by_group: Mapping[str, float] | None = None,
    ):
        self.scorer = scorer
        self.tokenizer = tokenizer
        self.max_tokens = max_tokens
        self.max_chars = max_chars
        self.max_hypotheses_per_group = max_hypotheses_per_group
        self.min_similarity_by_group = dict(
            min_similarity_by_group or {}
        )
        self.min_null_margin_by_group = dict(
            min_null_margin_by_group or {}
        )

    def match(
        self,
        text: str,
        *,
        offset: int = 0,
        source: str = "",
    ) -> RoleHypothesisResult:
        candidates = enumerate_candidate_spans(
            text,
            self.tokenizer,
            max_tokens=self.max_tokens,
            max_chars=self.max_chars,
        )
        assessments = self.scorer.assess_by_group(
            candidates,
            min_similarity_by_group=self.min_similarity_by_group,
            min_null_margin_by_group=self.min_null_margin_by_group,
        )
        accepted_by_group = {
            group: [
                assessment
                for assessment in assessments
                if assessment.group == group and assessment.accepted
            ]
            for group in OUTPUT_ROLE_GROUPS
        }
        selected = []
        for group in OUTPUT_ROLE_GROUPS:
            ranked = sorted(
                accepted_by_group[group],
                key=lambda assessment: (
                    -_role_hypothesis_score(assessment),
                    -len(assessment.candidate.text),
                    assessment.candidate.start,
                    assessment.label,
                ),
            )
            selected.extend(ranked[: self.max_hypotheses_per_group])

        source_name = source or self.name
        hypotheses = tuple(
            RoleHypothesis(
                start=offset + assessment.candidate.start,
                end=offset + assessment.candidate.end,
                text=assessment.candidate.text,
                group=assessment.group,
                label=assessment.label,
                score=_role_hypothesis_score(assessment),
                similarity=assessment.similarity,
                null_margin=assessment.null_margin,
                competition_margin=assessment.competition_margin,
                sources=(source_name,),
            )
            for assessment in sorted(
                selected,
                key=lambda value: (
                    value.candidate.start,
                    value.candidate.end,
                    value.group,
                    value.label,
                ),
            )
        )
        result = RoleHypothesisResult(
            algorithm=self.name,
            text=text,
            hypotheses=hypotheses,
            diagnostics={
                "candidate_count": len(candidates),
                "assessment_count": len(assessments),
                "accepted_by_group": {
                    group: len(values)
                    for group, values in accepted_by_group.items()
                },
                "selected_count": len(hypotheses),
            },
        )
        result.assert_valid(offset=offset)
        return result


def _label_family(label: str) -> str:
    return label.split("_", 1)[0]


TRANSITION_BONUSES: dict[tuple[str, str], float] = {
    ("condition", "attitude"): 0.035,
    ("temporal", "attitude"): 0.035,
    ("attitude", "object"): 0.055,
    ("condition", "object"): 0.020,
    ("object", "attitude"): 0.015,
}


def _transition_score(previous: str, current: str) -> float:
    previous_family = _label_family(previous) if previous else ""
    current_family = _label_family(current)
    if previous_family == current_family:
        return -0.060
    return TRANSITION_BONUSES.get(
        (previous_family, current_family),
        0.0,
    )


def _lattice_emission(
    assessment: CandidateAssessment,
    min_similarity: float,
) -> float:
    length_penalty = 0.003 * max(0, len(assessment.candidate.text) - 8)
    return (
        2.5 * (assessment.similarity - min_similarity)
        + 2.0 * assessment.margin
        - 0.025
        - length_penalty
    )


class SemiMarkovSpanLatticeMatcher:
    """Jointly decodes non-overlapping spans with a residual/null path."""

    name = "kylin_span_lattice_semimarkov"
    embedding_backed = True

    def __init__(
        self,
        scorer: PrototypeEmbeddingScorer,
        tokenizer: SpanTokenizer,
        *,
        max_tokens: int = 4,
        max_chars: int = 28,
        group_score_thresholds: Mapping[str, float] | None = None,
    ):
        self.scorer = scorer
        self.tokenizer = tokenizer
        self.max_tokens = max_tokens
        self.max_chars = max_chars
        self.group_score_thresholds = _group_score_thresholds(
            group_score_thresholds
        )

    def match(self, text: str, *, offset: int = 0) -> SpanMatchingResult:
        candidates = enumerate_candidate_spans(
            text,
            self.tokenizer,
            max_tokens=self.max_tokens,
            max_chars=self.max_chars,
        )
        assessments = self.scorer.assess(candidates)
        edges_by_start: dict[int, list[CandidateAssessment]] = {}
        for assessment in assessments:
            if (
                not assessment.accepted
                or not _passes_group_score_threshold(
                    assessment,
                    self.group_score_thresholds,
                )
            ):
                continue
            emission = _lattice_emission(
                assessment,
                self.scorer.min_similarity,
            )
            if emission <= 0.0:
                continue
            edges_by_start.setdefault(
                assessment.candidate.start,
                [],
            ).append(assessment)

        states: list[
            dict[str, tuple[float, tuple[CandidateAssessment, ...]]]
        ] = [dict() for _ in range(len(text) + 1)]
        states[0][""] = (0.0, ())
        for position in range(len(text)):
            if not states[position]:
                continue
            for previous, (score, path) in tuple(states[position].items()):
                self._update_state(
                    states[position + 1],
                    previous,
                    score,
                    path,
                )
                for assessment in edges_by_start.get(position, ()):
                    emission = _lattice_emission(
                        assessment,
                        self.scorer.min_similarity,
                    )
                    next_score = (
                        score
                        + emission
                        + _transition_score(previous, assessment.label)
                    )
                    self._update_state(
                        states[assessment.candidate.end],
                        assessment.label,
                        next_score,
                        (*path, assessment),
                    )

        final_states = states[len(text)]
        if final_states:
            best_score, selected = max(
                final_states.values(),
                key=lambda value: (value[0], -len(value[1])),
            )
        else:
            best_score, selected = 0.0, ()
        matches = tuple(
            SpanMatch(
                start=offset + assessment.candidate.start,
                end=offset + assessment.candidate.end,
                text=assessment.candidate.text,
                label=assessment.label,
                score=_match_score(assessment),
                similarity=assessment.similarity,
                margin=assessment.margin,
                source=self.name,
            )
            for assessment in selected
        )
        result = SpanMatchingResult(
            algorithm=self.name,
            text=text,
            matches=matches,
            diagnostics={
                "candidate_count": len(candidates),
                "lattice_edge_count": sum(
                    len(values) for values in edges_by_start.values()
                ),
                "selected_count": len(matches),
                "path_score": best_score,
                "group_score_thresholds": self.group_score_thresholds,
            },
        )
        _assert_result_with_offset(result, offset)
        return result

    @staticmethod
    def _update_state(
        target: dict[str, tuple[float, tuple[CandidateAssessment, ...]]],
        label: str,
        score: float,
        path: tuple[CandidateAssessment, ...],
    ) -> None:
        previous = target.get(label)
        if previous is None or (score, -len(path)) > (
            previous[0],
            -len(previous[1]),
        ):
            target[label] = (score, path)


def _assert_result_with_offset(
    result: SpanMatchingResult,
    offset: int,
) -> None:
    local_matches = tuple(
        SpanMatch(
            start=match.start - offset,
            end=match.end - offset,
            text=match.text,
            label=match.label,
            score=match.score,
            similarity=match.similarity,
            margin=match.margin,
            source=match.source,
        )
        for match in result.matches
    )
    SpanMatchingResult(
        algorithm=result.algorithm,
        text=result.text,
        matches=local_matches,
        diagnostics=result.diagnostics,
    ).assert_valid()


def label_group(label: str) -> str:
    if label.startswith("attitude_"):
        return "attitude"
    if label.startswith("temporal_"):
        return "temporal"
    return label
