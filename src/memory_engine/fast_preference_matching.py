from __future__ import annotations

import math
import re
import time
import unicodedata
from concurrent.futures import (
    Future,
    ThreadPoolExecutor,
    TimeoutError as FutureTimeoutError,
)
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Callable, Iterator, Mapping, Sequence

from .preference_matching import (
    ATTITUDE_VALUE_ANCHORS_V1,
    DEFAULT_CANONICAL_TAGS_V1,
    TEMPORAL_INITIALIZATION_V1,
    AttitudeValueMatcher,
    CanonicalEmbeddingMatcher,
    CanonicalMention,
    CanonicalRoleMatch,
    CanonicalTag,
    CanonicalTagRegistry,
    PreferenceFrameAssembler,
    PreferenceFrameResult,
    PreferenceObservationOptions,
    ScalarAnchor,
    TemporalInitialization,
    temporal_values,
    _merge_frame_attitudes,
)
from .span_matching import (
    CandidateSpan,
    JiebaSpanTokenizer,
    PrototypeEmbeddingScorer,
    RoleHypothesis,
    SpanTokenizer,
)
from .span_segmentation import Segment, TextEmbedder


class ObservationDeadlineExceeded(RuntimeError):
    """Raised before starting work that cannot fit the hard budget."""


@dataclass
class ObservationBudget:
    """Cooperative anytime budget shared by one Retrieval request."""

    started_at: float
    soft_limit_ms: float = 500.0
    hard_limit_ms: float = 800.0
    finalization_reserve_ms: float = 48.0
    clock: Callable[[], float] = time.perf_counter
    completed_embeddings: int = 0
    skipped_embeddings: int = 0
    skipped_candidates: int = 0
    hard_stop_reached: bool = False

    def __post_init__(self) -> None:
        if self.soft_limit_ms <= 0:
            raise ValueError("observation_soft_limit_must_be_positive")
        if self.hard_limit_ms <= self.soft_limit_ms:
            raise ValueError("observation_hard_limit_must_exceed_soft_limit")

    @property
    def elapsed_ms(self) -> float:
        return max(0.0, (self.clock() - self.started_at) * 1000.0)

    @property
    def remaining_ms(self) -> float:
        return max(0.0, self.hard_limit_ms - self.elapsed_ms)

    @property
    def phase(self) -> str:
        elapsed = self.elapsed_ms
        if elapsed < self.soft_limit_ms:
            return "full"
        if elapsed >= self.hard_limit_ms:
            return "expired"
        progress = (
            (elapsed - self.soft_limit_ms)
            / (self.hard_limit_ms - self.soft_limit_ms)
        )
        if progress < 0.35:
            return "selective"
        if progress < 0.70:
            return "strict"
        return "finalize"

    def allows_candidate(
        self,
        *,
        priority: float,
        group_count: int,
        cached: bool,
    ) -> bool:
        if cached:
            return self.phase != "expired"
        phase = self.phase
        if phase == "full":
            return True
        if phase == "selective":
            allowed = priority >= 0.58 or group_count >= 2
            if not allowed:
                self.skipped_candidates += 1
            return allowed
        if phase == "strict":
            allowed = priority >= 0.70 or (
                group_count >= 2 and priority >= 0.62
            )
            if not allowed:
                self.skipped_candidates += 1
            return allowed
        self.skipped_candidates += 1
        if phase == "expired":
            self.hard_stop_reached = True
        return False

    def allows_embedding(self, estimated_ms: float) -> bool:
        phase = self.phase
        needed = (
            max(1.0, estimated_ms) * 1.55
            + self.finalization_reserve_ms
        )
        allowed = phase not in {"finalize", "expired"} and (
            self.remaining_ms >= needed
        )
        if not allowed:
            self.skipped_embeddings += 1
            if phase == "expired" or self.remaining_ms <= 0:
                self.hard_stop_reached = True
        return allowed

    def allows_expansion_embedding(
        self,
        estimated_ms: float,
        *,
        checkpoint_ready: bool = False,
    ) -> bool:
        """Reserve enough time to turn candidates into a full checkpoint."""

        if self.phase in {"finalize", "expired"}:
            self.skipped_candidates += 1
            return False
        reserve_factor = 1.70 if checkpoint_ready else 3.0
        needed = (
            max(1.0, estimated_ms) * reserve_factor * 1.20
            + self.finalization_reserve_ms
        )
        allowed = self.remaining_ms >= needed
        if not allowed:
            self.skipped_candidates += 1
        return allowed

    def diagnostics(self) -> dict[str, Any]:
        return {
            "enabled": True,
            "soft_limit_ms": self.soft_limit_ms,
            "hard_limit_ms": self.hard_limit_ms,
            "elapsed_ms": self.elapsed_ms,
            "remaining_ms": self.remaining_ms,
            "phase": self.phase,
            "completed_embeddings": self.completed_embeddings,
            "skipped_embeddings": self.skipped_embeddings,
            "skipped_candidates": self.skipped_candidates,
            "hard_stop_reached": self.hard_stop_reached,
        }


_ACTIVE_OBSERVATION_BUDGET: ContextVar[ObservationBudget | None] = (
    ContextVar("active_observation_budget", default=None)
)


class MemoizingTextEmbedder:
    """Process-local cache required by the synchronous Kylin C API."""

    def __init__(self, backend: TextEmbedder):
        self.backend = backend
        self.cache: dict[str, Any] = {}
        self.requested = 0
        self.computed = 0
        self.estimated_embedding_ms = 140.0
        self._executor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="observation-embedding",
        )
        self._inflight: tuple[str, Future[Any], float] | None = None

    def is_cached(self, text: str) -> bool:
        return text in self.cache

    def cached_vector(self, text: str) -> Any | None:
        """Return an already computed vector without invoking the backend."""
        vector = self.cache.get(text)
        return vector.copy() if vector is not None else None

    @contextmanager
    def budget_scope(
        self,
        budget: ObservationBudget | None,
    ) -> Iterator[None]:
        token = _ACTIVE_OBSERVATION_BUDGET.set(budget)
        try:
            yield
        finally:
            _ACTIVE_OBSERVATION_BUDGET.reset(token)

    def embed(self, texts: list[str]) -> list[Any]:
        self.requested += len(texts)
        budget = _ACTIVE_OBSERVATION_BUDGET.get()
        if budget is not None:
            self._reap_inflight()
            self._wait_for_inflight_recovery(budget)
        missing = list(
            dict.fromkeys(
                text for text in texts if text not in self.cache
            )
        )
        if missing:
            if budget is None:
                vectors = self.backend.embed(missing)
                self.computed += len(missing)
                for text, vector in zip(missing, vectors):
                    self.cache[text] = vector.copy()
            else:
                for text in missing:
                    if self._inflight is not None:
                        budget.skipped_embeddings += 1
                        raise ObservationDeadlineExceeded(
                            "observation_embedding_worker_busy"
                        )
                    if not budget.allows_embedding(
                        self.estimated_embedding_ms
                    ):
                        raise ObservationDeadlineExceeded(
                            "observation_embedding_budget_exhausted"
                        )
                    started = budget.clock()
                    future = self._executor.submit(
                        self.backend.embed,
                        [text],
                    )
                    self._inflight = (text, future, started)
                    timeout_seconds = max(
                        0.001,
                        (
                            budget.remaining_ms
                            - budget.finalization_reserve_ms
                        )
                        / 1000.0,
                    )
                    try:
                        vectors = future.result(timeout=timeout_seconds)
                    except FutureTimeoutError as exc:
                        budget.skipped_embeddings += 1
                        budget.hard_stop_reached = True
                        raise ObservationDeadlineExceeded(
                            "observation_embedding_hard_timeout"
                        ) from exc
                    self._inflight = None
                    self._store_completed(
                        text,
                        vectors[0],
                        started,
                        budget=budget,
                    )
        return [self.cache[text] for text in texts]

    def _reap_inflight(self) -> None:
        if self._inflight is None:
            return
        text, future, started = self._inflight
        if not future.done():
            return
        self._inflight = None
        try:
            vectors = future.result()
        except Exception:
            return
        self._store_completed(text, vectors[0], started, budget=None)

    def _wait_for_inflight_recovery(
        self,
        budget: ObservationBudget,
    ) -> None:
        if self._inflight is None:
            return
        _, future, _ = self._inflight
        recoverable_ms = (
            budget.remaining_ms
            - self.estimated_embedding_ms
            - budget.finalization_reserve_ms
        )
        if recoverable_ms <= 0:
            return
        try:
            future.result(timeout=min(0.12, recoverable_ms / 1000.0))
        except FutureTimeoutError:
            return
        self._reap_inflight()

    def _store_completed(
        self,
        text: str,
        vector: Any,
        started: float,
        *,
        budget: ObservationBudget | None,
    ) -> None:
        clock = budget.clock if budget is not None else time.perf_counter
        elapsed_ms = max(0.0, (clock() - started) * 1000.0)
        bounded_elapsed_ms = min(240.0, max(40.0, elapsed_ms))
        self.estimated_embedding_ms = min(
            220.0,
            max(
                80.0,
                0.80 * self.estimated_embedding_ms
                + 0.20 * bounded_elapsed_ms,
            ),
        )
        self.computed += 1
        if budget is not None:
            budget.completed_embeddings += 1
        self.cache[text] = vector.copy()


@dataclass(frozen=True)
class GreedySemanticCandidate:
    candidate: CandidateSpan
    group: str
    priority: float
    source: str


@dataclass(frozen=True)
class SemanticRange:
    start: int
    end: int
    source: str


@dataclass(frozen=True)
class GreedySemanticProposal:
    candidates: tuple[GreedySemanticCandidate, ...]
    thresholds: Mapping[str, float]
    dominant_language: str
    language_atoms: tuple[SemanticRange, ...]
    soft_ranges: tuple[SemanticRange, ...]


FORMATION_GATE_PROTOTYPES_V1: Mapping[str, tuple[str, ...]] = {
    "formation": (
        "用户已经表达了明确或有范围的偏好选择",
        "用户要求使用避免修改或保留一个具体办公对象",
        "用户决定当前任务采用一种可识别的方案",
        "用户请求执行一项明确的办公操作",
        "不要使用这个对象",
        "避免采用这种方案",
        "改用另一个工具",
        "先保留当前选择",
        "发送之前让我确认",
        "继续沿用原来的做法",
        "the user asks to use avoid change or keep a specific work option",
    ),
    "residual": (
        "系统日志只记录已经发生的运行事实",
        "只是描述文件包含哪些内容而没有表达偏好",
        "明确说明这不是偏好或者不要记住这次操作",
        "等待用户确认所以尚未形成用户决定",
        "使用这个那个等指代但无法确定态度针对什么对象",
        "系统已经生成了一个对象",
        "文件里面包含一些对象",
        "应用程序包创建了进程",
        "这不是我的偏好",
        "不用记住这个操作",
        "a system event or factual status without a user preference",
    ),
}


AMBIGUITY_GATE_PROTOTYPES_V1: Mapping[str, tuple[str, ...]] = {
    "ambiguous": (
        "沿用之前的方式处理，但没有说明具体是哪一种操作",
        "照上次的规则继续做，当前文本无法确定工作流",
        "把这个结果按以前的口径补好，没有给出动作和范围",
        "使用历史方案的模糊指代，需要用户进一步澄清",
        "reuse the prior workflow without specifying the actual task",
    ),
    "residual": (
        "明确说明文件、工作表、列、范围以及要执行的具体操作",
        "给出计算公式、目标位置、输出格式和不能修改的内容",
        "分别列出多个文件及每个文件需要完成的任务",
        "具体要求创建、复制、排序、填充、计算或设置某个对象",
        "a concrete task with an explicit object action scope and output",
    ),
}


TEMPORAL_EVIDENCE_PROTOTYPES_V1: Mapping[str, tuple[str, ...]] = {
    "temporal": (
        "仅限当前会话或本轮任务",
        "今天今晚或者暂时有效",
        "这周下个月或近期有效",
        "后续一段时间继续有效",
        "从下次开始的一段时期",
        "以后今后每次都长期有效",
        "从今以后统一适用于同类任务",
        "在一个项目期间持续有效",
        "only for this session this week or future tasks",
    ),
    "residual": (
        "默认使用一个对象但没有说明时间",
        "继续沿用某种方案但没有说明时间",
        "继续用某个对象",
        "销售趋势等任务名称",
        "改用或者换成另一个对象",
        "不要使用或避免某种做法",
        "任务场景名称不是时间表达",
        "应用工具和对象名称不是时间表达",
    ),
}

_TEMPORAL_SCOPE_CUE = re.compile(
    r"(?:当前(?:会话|任务|文件|本轮)?|本次|这次|这回|本轮|"
    r"今天|今晚|暂时|眼下|近期|这周|本周|下周|下个月|"
    r"后续|以后|今后|长期|一直|每次|从今往后|从下次开始|"
    r"项目期间|一段时间|之前|上次|原来|照旧|沿用|"
    r"\b(?:currently|today|tonight|temporarily|for\s+now|"
    r"this\s+(?:time|task|session|round)|"
    r"next\s+(?:week|month)|in\s+the\s+future|from\s+now\s+on|"
    r"always|every\s+time|as\s+before|same\s+as\s+before|"
    r"previously|usual(?:ly)?)\b)",
    re.IGNORECASE,
)


def _has_temporal_scope_cue(text: str) -> bool:
    return bool(_TEMPORAL_SCOPE_CUE.search(text))


def _has_local_temporal_scope_cue(
    text: str,
    candidate: CandidateSpan,
) -> bool:
    return _has_temporal_scope_cue(
        text[
            max(0, candidate.start - 4) :
            min(len(text), candidate.end + 4)
        ]
    )


@dataclass(frozen=True)
class FormationGateAssessment:
    text: str
    formation_similarity: float
    residual_similarity: float
    margin: float
    rejected: bool


class EmbeddingFormationGate:
    """Contrast committed user intent with factual or non-memory text."""

    def __init__(
        self,
        embedder: TextEmbedder,
        *,
        min_residual_similarity: float = 0.62,
        min_residual_margin: float = 0.04,
    ):
        self.scorer = PrototypeEmbeddingScorer(
            embedder,
            prototypes=FORMATION_GATE_PROTOTYPES_V1,
        )
        self.min_residual_similarity = min_residual_similarity
        self.min_residual_margin = min_residual_margin

    def assess(
        self,
        texts: Sequence[str],
    ) -> tuple[FormationGateAssessment, ...]:
        unique = tuple(dict.fromkeys(text.strip() for text in texts if text.strip()))
        candidates = tuple(
            CandidateSpan(
                start=0,
                end=len(text),
                text=text,
                token_count=1,
            )
            for text in unique
        )
        values = []
        for assessment in self.scorer.assess(candidates):
            formation = float(assessment.label_scores["formation"])
            residual = float(assessment.label_scores["residual"])
            margin = residual - formation
            values.append(
                FormationGateAssessment(
                    text=assessment.candidate.text,
                    formation_similarity=formation,
                    residual_similarity=residual,
                    margin=margin,
                    rejected=(
                        residual >= self.min_residual_similarity
                        and margin >= self.min_residual_margin
                    ),
                )
            )
        return tuple(values)


def _content(text: str) -> bool:
    return any(
        not character.isspace()
        and not unicodedata.category(character).startswith("P")
        for character in text
    )


_CONDITION_CONTEXT_MARKER = re.compile(
    r"(?:如果|除非|时候|期间|过程中|场景|任务|工作|时|中|里|"
    r"\bwhen\b|\bwhile\b|\bduring\b|\bbefore\b|"
    r"\bin\s+the\s+context\s+of\b)",
    re.IGNORECASE,
)

_ACTION_OBJECT_MARKER = re.compile(
    r"(?:处理|整理|填写|填入|填充|补齐|补全|创建|新建|生成|"
    r"计算|统计|汇总|复制|导出|排序|调整|修改|设置|保留|"
    r"隐藏|拆分|拼接|核对|使用|采用|改用|换成|删除|清理|"
    r"转换|转置|标记|显示|绘制|制作|建立|插入|冻结|检查|"
    r"提取|"
    r"\b(?:copy|add|create|sort|fill|hide|resize|export|"
    r"calculate|build|clean|format|set|replace|remove|insert|"
    r"transpose|highlight|split|summarize|extract|assign|"
    r"reorder|freeze|show|keep|use|update|move|convert|"
    r"generate|apply|select|write|place|finish)\b)",
    re.IGNORECASE,
)


def _looks_like_condition_context(text: str) -> bool:
    return bool(_CONDITION_CONTEXT_MARKER.search(text))


def _is_cjk(character: str) -> bool:
    return "\u3400" <= character <= "\u9fff"


def _dominant_language(text: str) -> str:
    cjk_count = sum(_is_cjk(character) for character in text)
    latin_words = len(re.findall(r"[A-Za-z]+(?:[-'][A-Za-z]+)*", text))
    if cjk_count == 0:
        return "latin"
    if latin_words == 0:
        return "cjk"
    return "cjk" if cjk_count >= latin_words else "latin"


def _foreign_language_atoms(
    text: str,
    dominant_language: str,
) -> tuple[SemanticRange, ...]:
    foreign_language = "latin" if dominant_language == "cjk" else "cjk"
    if foreign_language == "latin":
        atoms = []
        for match in re.finditer(
            r"[A-Za-z0-9][A-Za-z0-9._:/!()#&+\-]*",
            text,
        ):
            start, end = _trim_interval(
                text,
                match.start(),
                match.end(),
            )
            if start < end and any(
                character.isalpha() for character in text[start:end]
            ):
                atoms.append(
                    SemanticRange(
                        start,
                        end,
                        "latin_language_atom",
                    )
                )
        merged = []
        for atom in atoms:
            if merged:
                previous = merged[-1]
                previous_text = text[previous.start : previous.end]
                atom_text = text[atom.start : atom.end]
                gap = text[previous.end : atom.start]
                if (
                    gap
                    and gap.isspace()
                    and re.fullmatch(
                        r"[A-Z][A-Za-z'-]*",
                        previous_text,
                    )
                    and re.fullmatch(
                        r"[A-Z][A-Za-z'-]*",
                        atom_text,
                    )
                ):
                    merged[-1] = SemanticRange(
                        previous.start,
                        atom.end,
                        "latin_language_atom",
                    )
                    continue
            merged.append(atom)
        return tuple(merged)

    def allowed(character: str) -> bool:
        return _is_cjk(character) or character.isspace()

    def contains_language(start: int, end: int) -> bool:
        return any(_is_cjk(character) for character in text[start:end])

    atoms = []
    cursor = 0
    while cursor < len(text):
        if not allowed(text[cursor]):
            cursor += 1
            continue
        end = cursor + 1
        while end < len(text) and allowed(text[end]):
            end += 1
        start, trimmed_end = _trim_interval(text, cursor, end)
        while start < trimmed_end and text[start].isspace():
            start += 1
        while start < trimmed_end and text[trimmed_end - 1].isspace():
            trimmed_end -= 1
        if (
            start < trimmed_end
            and contains_language(start, trimmed_end)
        ):
            atoms.append(
                SemanticRange(
                    start,
                    trimmed_end,
                    f"{foreign_language}_language_atom",
                )
            )
        cursor = end
    return tuple(atoms)


def _soft_semantic_ranges(
    text: str,
    hard_ranges: Sequence[tuple[int, int]],
    dominant_language: str,
    language_atoms: Sequence[SemanticRange],
) -> tuple[SemanticRange, ...]:
    ranges = []

    def append_dominant(start: int, end: int) -> None:
        start, end = _trim_interval(text, start, end)
        if start >= end:
            return
        if dominant_language != "cjk":
            ranges.append(
                SemanticRange(start, end, "latin_dominant_chunk")
            )
            return
        cursor = start
        for whitespace in re.finditer(r"\s+", text[start:end]):
            split_start = start + whitespace.start()
            split_end = start + whitespace.end()
            local_start, local_end = _trim_interval(
                text,
                cursor,
                split_start,
            )
            if local_start < local_end:
                ranges.append(
                    SemanticRange(
                        local_start,
                        local_end,
                        "cjk_space_chunk",
                    )
                )
            cursor = split_end
        local_start, local_end = _trim_interval(text, cursor, end)
        if local_start < local_end:
            ranges.append(
                SemanticRange(
                    local_start,
                    local_end,
                    "cjk_space_chunk",
                )
            )

    for hard_start, hard_end in hard_ranges:
        local_atoms = [
            atom
            for atom in language_atoms
            if hard_start <= atom.start and atom.end <= hard_end
        ]
        cursor = hard_start
        for atom in local_atoms:
            append_dominant(cursor, atom.start)
            ranges.append(atom)
            cursor = atom.end
        append_dominant(cursor, hard_end)
    if not ranges:
        return tuple(
            SemanticRange(start, end, "hard_clause")
            for start, end in hard_ranges
        )
    return tuple(
        sorted(
            {
                (value.start, value.end, value.source): value
                for value in ranges
            }.values(),
            key=lambda value: (value.start, value.end, value.source),
        )
    )


def _temporal_context_start(
    text: str,
    ranges: Sequence[SemanticRange],
    position: int,
) -> int:
    for index, value in enumerate(ranges):
        if not value.start <= position < value.end:
            continue
        if (
            value.source.endswith("_language_atom")
            and index > 0
            and not _content(text[ranges[index - 1].end : value.start])
        ):
            return ranges[index - 1].start
        return value.start
    return 0


def _semantic_source_ranges(
    text: str,
    hard_ranges: Sequence[tuple[int, int]],
    soft_ranges: Sequence[SemanticRange],
) -> tuple[tuple[int, int, float], ...]:
    sources = {}
    for hard_start, hard_end in hard_ranges:
        local = [
            value
            for value in soft_ranges
            if hard_start <= value.start and value.end <= hard_end
        ]
        if len(local) <= 1:
            sources[(hard_start, hard_end)] = 0.0
            continue
        for value in local:
            sources[(value.start, value.end)] = max(
                0.06,
                sources.get((value.start, value.end), 0.0),
            )
        for left, right in zip(local, local[1:]):
            gap_has_content = _content(text[left.end : right.start])
            one_is_language_atom = (
                left.source.endswith("_language_atom")
                != right.source.endswith("_language_atom")
            )
            if (
                one_is_language_atom
                and not gap_has_content
                and right.end - left.start <= 24
            ):
                sources[(left.start, right.end)] = max(
                    0.10,
                    sources.get((left.start, right.end), 0.0),
                )
            if (
                left.source != "cjk_space_chunk"
                or right.source != "cjk_space_chunk"
                or gap_has_content
                or (
                    (left.end - left.start)
                    + (right.end - right.start)
                    > 8
                )
            ):
                continue
            sources[(left.start, right.end)] = max(
                0.02,
                sources.get((left.start, right.end), 0.0),
            )
    return tuple(
        (start, end, bonus)
        for (start, end), bonus in sorted(sources.items())
    )


def _clause_ranges(
    text: str,
    protected_ranges: Sequence[SemanticRange] = (),
) -> tuple[tuple[int, int], ...]:
    ranges = []
    start = 0
    for index, character in enumerate(text):
        if character not in "，,；;：:。！？!?\n":
            continue
        if any(
            value.start <= index < value.end
            for value in protected_ranges
        ):
            continue
        end = index + 1
        if start < end:
            ranges.append((start, end))
        start = end
    if start < len(text):
        ranges.append((start, len(text)))
    return tuple(ranges)


def _containing_clause(
    ranges: Sequence[tuple[int, int]],
    position: int,
) -> tuple[int, int]:
    for start, end in ranges:
        if start <= position < end:
            return start, end
    return 0, ranges[-1][1] if ranges else 0


def _trim_interval(
    text: str,
    start: int,
    end: int,
) -> tuple[int, int]:
    while start < end and (
        text[start].isspace()
        or unicodedata.category(text[start]).startswith("P")
    ):
        start += 1
    while start < end and (
        text[end - 1].isspace()
        or unicodedata.category(text[end - 1]).startswith("P")
    ):
        end -= 1
    return start, end


class GreedyOptionAnchoredSpanProposer:
    """Propose local spans with density thresholds instead of global caps."""

    def __init__(
        self,
        tokenizer: SpanTokenizer,
        *,
        max_attitude_tokens: int = 4,
        max_temporal_tokens: int = 4,
        semantic_window_tokens: int = 10,
        semantic_step_tokens: int = 6,
    ):
        self.tokenizer = tokenizer
        self.max_attitude_tokens = max_attitude_tokens
        self.max_temporal_tokens = max_temporal_tokens
        self.semantic_window_tokens = semantic_window_tokens
        self.semantic_step_tokens = semantic_step_tokens

    def propose(
        self,
        text: str,
        mentions: Sequence[CanonicalMention],
        *,
        condition_ids: set[str],
        object_ids: set[str],
    ) -> GreedySemanticProposal:
        dominant_language = _dominant_language(text)
        language_atoms = _foreign_language_atoms(
            text,
            dominant_language,
        )
        clauses = _clause_ranges(text, language_atoms)
        soft_ranges = _soft_semantic_ranges(
            text,
            clauses,
            dominant_language,
            language_atoms,
        )
        condition_mentions = [
            mention
            for mention in mentions
            if mention.tag_id in condition_ids
        ]
        object_mentions = [
            mention
            for mention in mentions
            if mention.tag_id in object_ids
        ]
        attitude = []
        all_mentions = sorted(
            {*condition_mentions, *object_mentions},
            key=lambda value: (value.start, value.end, value.tag_id),
        )
        for mention in object_mentions:
            clause_start, clause_end = _containing_clause(
                clauses,
                mention.start,
            )
            previous_end = max(
                (
                    value.end
                    for value in all_mentions
                    if (
                        clause_start <= value.end <= mention.start
                        and value != mention
                    )
                ),
                default=clause_start,
            )
            following_start = min(
                (
                    value.start
                    for value in all_mentions
                    if (
                        mention.end <= value.start < clause_end
                        and value != mention
                    )
                ),
                default=clause_end,
            )
            left = self._edge_candidate(
                text,
                previous_end,
                mention.start,
                group="attitude",
                take_from_end=True,
                max_tokens=self.max_attitude_tokens,
                source="before_object",
            )
            right = self._edge_candidate(
                text,
                mention.end,
                following_start,
                group="attitude",
                take_from_end=False,
                max_tokens=self.max_attitude_tokens,
                source="after_object",
            )
            if left is not None:
                attitude.append(left)
                compact_left = self._edge_candidate(
                    text,
                    previous_end,
                    mention.start,
                    group="attitude",
                    take_from_end=True,
                    max_tokens=2,
                    source="before_object_compact",
                )
                if compact_left is not None:
                    attitude.append(compact_left)
            if right is not None:
                attitude.append(right)

        temporal = []
        temporal_anchors = sorted(
            {*condition_mentions, *object_mentions},
            key=lambda value: (value.start, value.end, value.tag_id),
        )
        for mention in temporal_anchors:
            semantic_start = _temporal_context_start(
                text,
                soft_ranges,
                mention.start,
            )
            for take_from_end, max_tokens, source in (
                (
                    True,
                    self.max_temporal_tokens,
                    "clause_prefix",
                ),
                (True, 2, "clause_prefix_tail"),
                (False, 2, "clause_prefix_head"),
            ):
                candidate = self._edge_candidate(
                    text,
                    semantic_start,
                    mention.start,
                    group="temporal",
                    take_from_end=take_from_end,
                    max_tokens=max_tokens,
                    source=source,
                    trim_tail_tokens={"在", "于", "从", "当", "用"},
                )
                if candidate is not None:
                    temporal.append(candidate)
        semantic_objects = []
        semantic_attitudes = []
        semantic_conditions = []
        semantic_sources = _semantic_source_ranges(
            text,
            clauses,
            soft_ranges,
        )
        for clause_start, clause_end, range_bonus in semantic_sources:
            hard_start, hard_end = _containing_clause(
                clauses,
                clause_start,
            )
            has_condition_mention = any(
                mention.tag_id in condition_ids
                and mention.start < hard_end
                and hard_start < mention.end
                for mention in condition_mentions
            )
            for candidate, priority in self._semantic_clause_candidates(
                text,
                clause_start,
                clause_end,
                all_mentions,
            ):
                looks_like_condition = _looks_like_condition_context(
                    candidate.text
                )
                if (
                    not has_condition_mention
                    and looks_like_condition
                ):
                    semantic_conditions.append(
                        GreedySemanticCandidate(
                            candidate,
                            "condition",
                            min(1.0, priority + range_bonus),
                            "semantic_condition_context",
                        )
                    )
                semantic_attitudes.append(
                    GreedySemanticCandidate(
                        candidate,
                        "attitude",
                        min(1.0, priority + range_bonus),
                        "semantic_task_core",
                    )
                )
                if (
                    looks_like_condition
                    and not _ACTION_OBJECT_MARKER.search(candidate.text)
                ):
                    continue
                semantic_objects.append(
                    GreedySemanticCandidate(
                        candidate,
                        "object",
                        min(1.0, priority + range_bonus),
                        "semantic_task_core",
                    )
                )
        by_group = {
            "condition": semantic_conditions,
            "attitude": [*attitude, *semantic_attitudes],
            "object": semantic_objects,
            "temporal": temporal,
        }
        selected = []
        thresholds = {}
        for group, values in by_group.items():
            retained, threshold = self._select_dynamic(
                values,
                text=text,
                clauses=(
                    clauses
                    if group in {"condition", "attitude"}
                    else tuple(
                        (value.start, value.end)
                        for value in soft_ranges
                    )
                ),
                group=group,
            )
            selected.extend(retained)
            thresholds[group] = threshold
        deduplicated = {}
        for value in selected:
            key = (
                value.candidate.start,
                value.candidate.end,
                value.group,
            )
            previous = deduplicated.get(key)
            if previous is None or value.priority > previous.priority:
                deduplicated[key] = value
        return GreedySemanticProposal(
            candidates=tuple(
                sorted(
                    deduplicated.values(),
                    key=lambda value: (
                        value.candidate.start,
                        value.candidate.end,
                        value.group,
                    ),
                )
            ),
            thresholds=thresholds,
            dominant_language=dominant_language,
            language_atoms=tuple(language_atoms),
            soft_ranges=tuple(soft_ranges),
        )

    def _semantic_clause_candidates(
        self,
        text: str,
        start: int,
        end: int,
        mentions: Sequence[CanonicalMention],
    ) -> tuple[tuple[CandidateSpan, float], ...]:
        start, end = _trim_interval(text, start, end)
        if start >= end:
            return ()
        candidates = {}
        intervals = []
        cursor = start
        for mention in sorted(
            (
                value
                for value in mentions
                if value.start < end and start < value.end
            ),
            key=lambda value: (value.start, value.end),
        ):
            if cursor < mention.start:
                intervals.append((cursor, min(end, mention.start)))
            cursor = max(cursor, mention.end)
        if cursor < end:
            intervals.append((cursor, end))
        if not intervals:
            return ()
        for interval_start, interval_end in intervals:
            interval_start, interval_end = _trim_interval(
                text,
                interval_start,
                interval_end,
            )
            if interval_start >= interval_end:
                continue
            local = text[interval_start:interval_end]
            tokens = [
                token
                for token in self.tokenizer.tokenize(local)
                if _content(local[token.start : token.end])
            ]
            if not tokens:
                continue
            windows = []
            if len(tokens) <= self.semantic_window_tokens:
                windows.append((0, len(tokens), 0.78))
            else:
                window = self.semantic_window_tokens
                for token_start in range(
                    0,
                    len(tokens),
                    self.semantic_step_tokens,
                ):
                    token_end = min(len(tokens), token_start + window)
                    priority = (
                        0.72
                        if token_start == 0
                        else max(0.56, 0.65 - 0.004 * token_start)
                    )
                    windows.append(
                        (token_start, token_end, priority)
                    )
                    if token_end == len(tokens):
                        break
                tail_start = max(0, len(tokens) - window)
                windows.append((tail_start, len(tokens), 0.70))
                if len(local) <= 96:
                    whole_priority = 0.76 if len(local) <= 64 else 0.69
                    windows.append(
                        (0, len(tokens), whole_priority)
                    )
            for token_start, token_end, priority in windows:
                chosen = tokens[token_start:token_end]
                candidate_start = interval_start + chosen[0].start
                candidate_end = interval_start + chosen[-1].end
                value = text[candidate_start:candidate_end]
                if len(value.strip()) < 2:
                    continue
                candidate = CandidateSpan(
                    start=candidate_start,
                    end=candidate_end,
                    text=value,
                    token_count=len(chosen),
                )
                key = (candidate.start, candidate.end)
                previous = candidates.get(key)
                if previous is None or priority > previous[1]:
                    candidates[key] = (candidate, priority)
        return tuple(candidates.values())

    def _edge_candidate(
        self,
        text: str,
        start: int,
        end: int,
        *,
        group: str,
        take_from_end: bool,
        max_tokens: int,
        source: str,
        trim_tail_tokens: set[str] | None = None,
    ) -> GreedySemanticCandidate | None:
        start, end = _trim_interval(text, start, end)
        if start >= end:
            return None
        local = text[start:end]
        tokens = [
            token
            for token in self.tokenizer.tokenize(local)
            if _content(local[token.start : token.end])
        ]
        if trim_tail_tokens:
            while tokens and tokens[-1].text in trim_tail_tokens:
                tokens.pop()
        if not tokens:
            return None
        chosen = (
            tokens[-max_tokens:]
            if take_from_end
            else tokens[:max_tokens]
        )
        candidate_start = start + chosen[0].start
        candidate_end = start + chosen[-1].end
        value = text[candidate_start:candidate_end]
        if len(value.strip()) < 2:
            return None
        distance_priority = 1.0 / (1.0 + max(0, len(tokens) - len(chosen)))
        compactness = 1.0 / (1.0 + max(0, len(value) - 8))
        return GreedySemanticCandidate(
            candidate=CandidateSpan(
                start=candidate_start,
                end=candidate_end,
                text=value,
                token_count=len(chosen),
            ),
            group=group,
            priority=0.65 * distance_priority + 0.35 * compactness,
            source=source,
        )

    @staticmethod
    def _select_dynamic(
        values: Sequence[GreedySemanticCandidate],
        *,
        text: str,
        clauses: Sequence[tuple[int, int]],
        group: str,
    ) -> tuple[list[GreedySemanticCandidate], float]:
        deduplicated = {}
        for value in values:
            key = (
                value.candidate.start,
                value.candidate.end,
                value.group,
                value.source,
            )
            previous = deduplicated.get(key)
            if previous is None or value.priority > previous.priority:
                deduplicated[key] = value
        unique = list(deduplicated.values())
        if not unique:
            return [], 1.0
        length_units = max(1.0, len(text) / 72.0)
        density = len(unique) / length_units
        base = {
            "condition": 0.48,
            "attitude": 0.42,
            "object": 0.48,
            "temporal": 0.46,
        }[group]
        density_threshold = min(
            0.74,
            base + 0.025 * max(0.0, density - 5.0),
        )
        populated_clauses = sum(
            any(
                start <= value.candidate.start < end
                for value in unique
            )
            for start, end in clauses
        )
        opportunity_count = max(
            1,
            populated_clauses,
            math.ceil(len(text) / 32.0),
        )
        ranked_priorities = sorted(
            (value.priority for value in unique),
            reverse=True,
        )
        rank_threshold = ranked_priorities[
            min(opportunity_count, len(ranked_priorities)) - 1
        ]
        threshold = max(density_threshold, rank_threshold)
        retained = [
            value for value in unique if value.priority >= threshold
        ]
        # Every populated clause keeps its strongest local opportunity. The
        # semantic matcher can still reject it; no global candidate count is
        # imposed, so longer multi-task inputs receive proportionally more.
        for clause_start, clause_end in clauses:
            local = [
                value
                for value in unique
                if clause_start <= value.candidate.start < clause_end
            ]
            if not local:
                continue
            best = max(
                local,
                key=lambda value: (
                    value.priority,
                    -(value.candidate.end - value.candidate.start),
                    -value.candidate.start,
                ),
            )
            if best not in retained:
                retained.append(best)
            if group == "attitude":
                anchored = [
                    value
                    for value in local
                    if (
                        value.source.startswith("before_object")
                        or value.source.startswith("after_object")
                    )
                ]
                if anchored:
                    best_anchored = max(
                        anchored,
                        key=lambda value: (
                            value.priority,
                            -(
                                value.candidate.end
                                - value.candidate.start
                            ),
                            -value.candidate.start,
                        ),
                    )
                    if best_anchored not in retained:
                        retained.append(best_anchored)
        return sorted(
            retained,
            key=lambda value: (
                -value.priority,
                value.candidate.start,
                value.candidate.end,
            ),
        ), threshold


def _role_score(
    similarity: float,
    null_margin: float,
    competition_margin: float,
    text: str,
) -> float:
    return (
        similarity
        + 0.55 * null_margin
        + 0.15 * competition_margin
        - 0.003 * max(0, len(text) - 10)
    )


class FastPreferenceFrameMatcher:
    """Closed-choice fast path; the full matcher remains the baseline."""

    name = "kylin_fast_dynamic_preference_frame_v2"

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
        min_frame_confidence: float = 0.78,
    ):
        self.embedder = MemoizingTextEmbedder(embedder)
        self.tokenizer = tokenizer or JiebaSpanTokenizer()
        self.tokenizer.tokenize("初始化")
        self.registry = CanonicalTagRegistry(tags)
        self.scorer = PrototypeEmbeddingScorer(self.embedder)
        self.formation_gate = EmbeddingFormationGate(self.embedder)
        self.ambiguity_gate = PrototypeEmbeddingScorer(
            self.embedder,
            prototypes=AMBIGUITY_GATE_PROTOTYPES_V1,
        )
        self.temporal_gate = PrototypeEmbeddingScorer(
            self.embedder,
            prototypes=TEMPORAL_EVIDENCE_PROTOTYPES_V1,
            min_similarity=0.55,
            min_margin=0.02,
        )
        self.canonical_matcher = CanonicalEmbeddingMatcher(
            self.embedder,
            self.registry,
            min_similarity={"condition": 0.54, "object": 0.54},
            top_k_per_hypothesis=2,
        )
        self.attitude_matcher = AttitudeValueMatcher(
            self.embedder,
            anchors=attitude_anchors,
        )
        self.temporal_initialization = dict(temporal_initialization)
        self.min_frame_confidence = min_frame_confidence
        self.proposer = GreedyOptionAnchoredSpanProposer(
            self.tokenizer
        )
        self.assembler = PreferenceFrameAssembler(
            min_attitude_similarity=0.46,
            min_attitude_hypothesis_score=0.58,
        )

    def match(
        self,
        text: str,
        *,
        options: PreferenceObservationOptions | None = None,
        budget: ObservationBudget | None = None,
    ) -> PreferenceFrameResult:
        with self.embedder.budget_scope(budget):
            return self._match(text, options=options, budget=budget)

    def _match(
        self,
        text: str,
        *,
        options: PreferenceObservationOptions | None,
        budget: ObservationBudget | None,
    ) -> PreferenceFrameResult:
        if options is None:
            raise ValueError("fast_preference_matcher_requires_options")
        requested_before = self.embedder.requested
        computed_before = self.embedder.computed
        condition_ids = set(options.condition_tag_ids)
        object_ids = set(options.object_tag_ids)
        mentions = tuple(
            mention
            for mention in self.registry.find_mentions(text)
            if (
                mention.tag_id in condition_ids
                or mention.tag_id in object_ids
            )
        )
        proposal = self.proposer.propose(
            text,
            mentions,
            condition_ids=condition_ids,
            object_ids=object_ids,
        )
        proposed_candidates = proposal.candidates
        greedy = tuple(
            value
            for value in proposed_candidates
            if (
                value.group != "temporal"
                or _has_local_temporal_scope_cue(
                    text,
                    value.candidate,
                )
            )
        )
        if budget is not None and text.strip():
            stripped = text.strip()
            stripped_start = len(text) - len(text.lstrip())
            checkpoint_candidate = CandidateSpan(
                start=stripped_start,
                end=stripped_start + len(stripped),
                text=stripped,
                token_count=1,
            )
            checkpoint_groups = ["attitude", "object"]
            if _has_temporal_scope_cue(stripped):
                checkpoint_groups.append("temporal")
            greedy = (
                *(
                    GreedySemanticCandidate(
                        candidate=checkpoint_candidate,
                        group=group,
                        priority=0.80,
                        source="budget_checkpoint_full_text",
                    )
                    for group in checkpoint_groups
                ),
                *greedy,
            )
        unique_candidates = tuple(
            {
                (
                    value.candidate.start,
                    value.candidate.end,
                ): value.candidate
                for value in greedy
            }.values()
        )
        if budget is None:
            assessments = self.scorer.assess_by_group(
                unique_candidates,
                min_similarity_by_group={"temporal": 0.62},
                min_null_margin_by_group={"temporal": 0.05},
            )
        else:
            metadata = {}
            for value in greedy:
                key = (value.candidate.start, value.candidate.end)
                entry = metadata.setdefault(
                    key,
                    {
                        "candidate": value.candidate,
                        "priority": value.priority,
                        "groups": set(),
                    },
                )
                entry["priority"] = max(
                    float(entry["priority"]),
                    value.priority,
                )
                entry["groups"].add(value.group)
            ranked = sorted(
                metadata.values(),
                key=lambda value: (
                    -len(value["groups"]),
                    -float(value["priority"]),
                    value["candidate"].start,
                    value["candidate"].end,
                ),
            )
            candidate_clauses = _clause_ranges(
                text,
                proposal.language_atoms,
            )
            coverage = {}
            for value in ranked:
                clause = _containing_clause(
                    candidate_clauses,
                    value["candidate"].start,
                )
                coverage.setdefault(clause, value)
            coverage_values = sorted(
                coverage.values(),
                key=lambda value: (
                    -len(value["groups"]),
                    -float(value["priority"]),
                    value["candidate"].start,
                ),
            )
            coverage_ids = {id(value) for value in coverage_values}
            ordered = [
                *coverage_values,
                *(
                    value
                    for value in ranked
                    if id(value) not in coverage_ids
                ),
            ]
            incremental = []
            formation_prefetched = self.embedder.is_cached(text.strip())
            evaluated_candidates = 0
            for value in ordered:
                candidate = value["candidate"]
                if not budget.allows_candidate(
                    priority=float(value["priority"]),
                    group_count=len(value["groups"]),
                    cached=self.embedder.is_cached(candidate.text),
                ):
                    continue
                if (
                    not self.embedder.is_cached(candidate.text)
                    and not budget.allows_expansion_embedding(
                        self.embedder.estimated_embedding_ms,
                        checkpoint_ready=formation_prefetched,
                    )
                ):
                    continue
                try:
                    candidate_assessments = self.scorer.assess_by_group(
                        (candidate,),
                        min_similarity_by_group={"temporal": 0.62},
                        min_null_margin_by_group={"temporal": 0.05},
                    )
                except ObservationDeadlineExceeded:
                    break
                incremental.extend(candidate_assessments)
                evaluated_candidates += 1
                if (
                    evaluated_candidates >= 1
                    and not formation_prefetched
                ):
                    try:
                        self.formation_gate.assess((text.strip(),))
                    except ObservationDeadlineExceeded:
                        break
                    formation_prefetched = True
            assessments = tuple(incremental)
            if not formation_prefetched:
                try:
                    self.formation_gate.assess((text.strip(),))
                except ObservationDeadlineExceeded:
                    pass
        assessed_candidate_keys = {
            (value.candidate.start, value.candidate.end)
            for value in assessments
        }
        temporal_candidates = tuple(
            {
                (
                    value.candidate.start,
                    value.candidate.end,
                ): value.candidate
                for value in greedy
                if (
                    value.group == "temporal"
                    and (
                        value.candidate.start,
                        value.candidate.end,
                    ) in assessed_candidate_keys
                )
            }.values()
        )
        try:
            temporal_assessments = self.temporal_gate.assess(
                temporal_candidates
            )
        except ObservationDeadlineExceeded:
            temporal_assessments = ()
        temporal_evidence = {
            (value.candidate.start, value.candidate.end): value
            for value in temporal_assessments
        }
        allowed_group = {
            (
                value.candidate.start,
                value.candidate.end,
                value.group,
            ): value
            for value in greedy
        }
        assessments_by_key = {
            (
                value.candidate.start,
                value.candidate.end,
                value.group,
            ): value
            for value in assessments
        }
        hypotheses = []
        for assessment in assessments:
            proposed = allowed_group.get(
                (
                    assessment.candidate.start,
                    assessment.candidate.end,
                    assessment.group,
                )
            )
            command_mention_fallback = (
                proposed is not None
                and proposed.source == "object_command_mention"
                and assessment.group == "attitude"
                and assessment.similarity >= 0.44
                and assessment.null_margin >= -0.14
            )
            assessment_accepted = assessment.accepted
            if assessment.group == "temporal":
                evidence = temporal_evidence.get(
                    (
                        assessment.candidate.start,
                        assessment.candidate.end,
                    )
                )
                assessment_accepted = bool(
                    evidence
                    and evidence.accepted
                    and evidence.label == "temporal"
                )
            if (
                proposed is None
                or (
                    not assessment_accepted
                    and not command_mention_fallback
                )
            ):
                continue
            hypotheses.append(
                RoleHypothesis(
                    start=assessment.candidate.start,
                    end=assessment.candidate.end,
                    text=assessment.candidate.text,
                    group=assessment.group,
                    label=assessment.label,
                    score=max(
                        0.58 if command_mention_fallback else 0.0,
                        0.62
                        if (
                            assessment.group == "temporal"
                            and assessment_accepted
                        )
                        else 0.0,
                        _role_score(
                            assessment.similarity,
                            assessment.null_margin,
                            assessment.competition_margin,
                            assessment.candidate.text,
                        ),
                    ),
                    similarity=assessment.similarity,
                    null_margin=assessment.null_margin,
                    competition_margin=assessment.competition_margin,
                    sources=("fast_greedy", proposed.source),
                )
            )

        existing_hypothesis_scores = {
            (value.start, value.end, value.group): value.score
            for value in hypotheses
        }
        for proposed in greedy:
            if (
                proposed.group not in {"condition", "object"}
                or proposed.source
                not in {
                    "semantic_condition_context",
                    "semantic_task_core",
                    "budget_checkpoint_full_text",
                }
                or (
                    existing_hypothesis_scores.get(
                        (
                            proposed.candidate.start,
                            proposed.candidate.end,
                            proposed.group,
                        ),
                        float("-inf"),
                    )
                    >= 0.58
                )
            ):
                continue
            assessment = assessments_by_key.get(
                (
                    proposed.candidate.start,
                    proposed.candidate.end,
                    proposed.group,
                )
            )
            if assessment is None:
                continue
            hypotheses.append(
                RoleHypothesis(
                    start=proposed.candidate.start,
                    end=proposed.candidate.end,
                    text=proposed.candidate.text,
                    group=proposed.group,
                    label=f"{proposed.group}_semantic_candidate",
                    score=max(
                        0.58,
                        _role_score(
                            assessment.similarity,
                            assessment.null_margin,
                            assessment.competition_margin,
                            proposed.candidate.text,
                        ),
                    ),
                    similarity=assessment.similarity,
                    null_margin=assessment.null_margin,
                    competition_margin=assessment.competition_margin,
                    sources=("fast_greedy", proposed.source),
                )
            )

        canonical = []
        for mention in mentions:
            tag = self.registry.by_id[mention.tag_id]
            for group, allowed in (
                ("condition", condition_ids),
                ("object", object_ids),
            ):
                if mention.tag_id not in allowed or group not in tag.groups:
                    continue
                hypothesis = RoleHypothesis(
                    start=mention.start,
                    end=mention.end,
                    text=mention.text,
                    group=group,
                    label=f"{group}_canonical_mention",
                    score=1.0,
                    similarity=1.0,
                    null_margin=1.0,
                    competition_margin=0.0,
                    sources=("fast_exact_option",),
                )
                hypotheses.append(hypothesis)
                canonical.append(
                    CanonicalRoleMatch(
                        start=mention.start,
                        end=mention.end,
                        text=mention.text,
                        group=group,
                        tag_id=tag.tag_id,
                        tag_name=tag.name,
                        score=1.16,
                        similarity=1.0,
                        exact_alias=True,
                        hypothesis_score=1.0,
                        sources=hypothesis.sources,
                    )
                )

        semantic_hypotheses = hypotheses
        if budget is not None:
            semantic_hypotheses = [
                value
                for value in hypotheses
                if "fast_exact_option" not in value.sources
            ]
        try:
            semantic_canonical = self.canonical_matcher.match(
                semantic_hypotheses,
                allowed_tag_ids={
                    "condition": condition_ids,
                    "object": object_ids,
                },
            )
        except ObservationDeadlineExceeded:
            semantic_canonical = ()
        ambiguity_matches = ()
        ambiguity_evidence = None
        ambiguity_guard = False
        stripped = text.strip()
        ambiguous_tag_id = "object:ambiguous_prior_workflow"
        if (
            ambiguous_tag_id in object_ids
            and stripped
            and self.embedder.is_cached(stripped)
        ):
            stripped_start = len(text) - len(text.lstrip())
            ambiguity_hypothesis = RoleHypothesis(
                start=stripped_start,
                end=stripped_start + len(stripped),
                text=stripped,
                group="object",
                label="object_full_text_ambiguity_probe",
                score=0.62,
                similarity=0.62,
                null_margin=0.0,
                competition_margin=0.0,
                sources=("full_text_ambiguity_probe",),
            )
            try:
                ambiguity_matches = self.canonical_matcher.match(
                    (ambiguity_hypothesis,),
                    allowed_tag_ids={"object": object_ids},
                    top_k_per_hypothesis=5,
                    include_below_threshold=True,
                )
            except ObservationDeadlineExceeded:
                ambiguity_matches = ()
            if ambiguity_matches:
                ranked_ambiguity = sorted(
                    ambiguity_matches,
                    key=lambda value: (-value.score, value.tag_id),
                )
                ambiguous_match = next(
                    (
                        value
                        for value in ranked_ambiguity
                        if value.tag_id == ambiguous_tag_id
                    ),
                    None,
                )
                has_exact_concrete_object = any(
                    mention.tag_id in object_ids
                    and mention.tag_id != ambiguous_tag_id
                    for mention in mentions
                )
                ambiguity_guard = bool(
                    ambiguous_match is not None
                    and not has_exact_concrete_object
                    and ambiguous_match.score
                    >= ranked_ambiguity[0].score - 0.05
                )
        exact_ambiguous_mention = any(
            mention.tag_id == ambiguous_tag_id
            for mention in mentions
        )
        exact_concrete_object_mention = any(
            mention.tag_id in object_ids
            and mention.tag_id != ambiguous_tag_id
            for mention in mentions
        )
        if stripped and self.embedder.is_cached(stripped):
            stripped_start = len(text) - len(text.lstrip())
            try:
                evidence = self.ambiguity_gate.assess(
                    (
                        CandidateSpan(
                            start=stripped_start,
                            end=stripped_start + len(stripped),
                            text=stripped,
                            token_count=1,
                        ),
                    )
                )
            except ObservationDeadlineExceeded:
                evidence = ()
            if evidence:
                value = evidence[0]
                ambiguous_score = float(
                    value.label_scores["ambiguous"]
                )
                specific_score = float(
                    value.label_scores["residual"]
                )
                ambiguity_evidence = {
                    "ambiguous_similarity": ambiguous_score,
                    "specific_similarity": specific_score,
                    "margin": ambiguous_score - specific_score,
                }
                ambiguity_guard = ambiguity_guard or bool(
                    ambiguous_score >= 0.56
                    and ambiguous_score - specific_score >= 0.02
                )
        ambiguity_guard = ambiguity_guard or bool(
            exact_ambiguous_mention
            and not exact_concrete_object_mention
        )
        canonical_by_key = {
            (
                value.start,
                value.end,
                value.group,
                value.tag_id,
            ): value
            for value in [*canonical, *semantic_canonical]
        }
        canonical = list(canonical_by_key.values())

        try:
            attitudes = self.attitude_matcher.match(hypotheses)
        except ObservationDeadlineExceeded:
            attitudes = ()
        temporals = temporal_values(
            hypotheses,
            self.temporal_initialization,
        )
        if options.temporal_labels:
            allowed_temporal = set(options.temporal_labels)
            temporals = tuple(
                value
                for value in temporals
                if value.label in allowed_temporal
            )
        assembled_frames = self.assembler.assemble(
            text,
            canonical,
            attitudes,
            temporals,
        )
        attitudes = _merge_frame_attitudes(
            attitudes,
            assembled_frames,
        )
        frames, formation_gate, full_text_formation_gate = self._select_frames(
            text,
            assembled_frames,
            budget=budget,
            suppress_unconditioned_objects=ambiguity_guard,
        )
        requested_delta = self.embedder.requested - requested_before
        computed_delta = self.embedder.computed - computed_before
        clauses = tuple(
            Segment(start, end, text[start:end])
            for start, end in _clause_ranges(text)
        )
        return PreferenceFrameResult(
            algorithm=self.name,
            text=text,
            hypotheses=tuple(
                sorted(
                    hypotheses,
                    key=lambda value: (
                        value.start,
                        value.end,
                        value.group,
                    ),
                )
            ),
            canonical_matches=tuple(canonical),
            attitudes=attitudes,
            temporals=temporals,
            frames=frames,
            diagnostics={
                "segmentations": {
                    "punctuation_only": [
                        {
                            "start": clause.start,
                            "end": clause.end,
                            "text": clause.text,
                        }
                        for clause in clauses
                    ]
                },
                "greedy_candidates": [
                    {
                        "start": value.candidate.start,
                        "end": value.candidate.end,
                        "text": value.candidate.text,
                        "group": value.group,
                        "priority": value.priority,
                        "source": value.source,
                    }
                    for value in greedy
                ],
                "proposed_candidate_count": len(proposed_candidates),
                "temporal_structural_pruned_count": (
                    len(proposed_candidates) - len(greedy)
                ),
                "greedy_candidate_count": len(greedy),
                "embedding_candidate_count": len(unique_candidates),
                "evaluated_embedding_candidate_count": len(
                    assessed_candidate_keys
                ),
                "dynamic_candidate_thresholds": dict(
                    proposal.thresholds
                ),
                "formation_gate": formation_gate,
                "full_text_formation_gate": full_text_formation_gate,
                "ambiguity_guard": {
                    "activated": ambiguity_guard,
                    "contrastive_evidence": ambiguity_evidence,
                    "matches": [
                        {
                            "tag_id": value.tag_id,
                            "score": value.score,
                            "similarity": value.similarity,
                        }
                        for value in ambiguity_matches
                    ],
                },
                "temporal_evidence_gate": [
                    {
                        "start": value.candidate.start,
                        "end": value.candidate.end,
                        "text": value.candidate.text,
                        "label": value.label,
                        "similarity": value.similarity,
                        "margin": value.margin,
                        "accepted": value.accepted,
                    }
                    for value in temporal_evidence.values()
                ],
                "assembled_frames": [
                    {
                        "condition_tag_id": (
                            frame.condition.tag_id
                            if frame.condition is not None
                            else None
                        ),
                        "object_tag_id": frame.object.tag_id,
                        "object_text": frame.object.text,
                        "attitude_text": frame.attitude.text,
                        "attitude_value": frame.attitude.value,
                        "temporal_label": (
                            frame.temporal.label
                            if frame.temporal is not None
                            else None
                        ),
                        "confidence": frame.confidence,
                    }
                    for frame in assembled_frames
                ],
                "command_attitude_fallbacks": [
                    {
                        "start": value.start,
                        "end": value.end,
                        "text": value.text,
                        "value": value.value,
                    }
                    for frame in assembled_frames
                    for value in (frame.attitude,)
                    if "command_attitude_fallback" in value.sources
                ],
                "dominant_language": proposal.dominant_language,
                "language_atoms": [
                    {
                        "start": value.start,
                        "end": value.end,
                        "text": text[value.start : value.end],
                        "source": value.source,
                    }
                    for value in proposal.language_atoms
                ],
                "soft_ranges": [
                    {
                        "start": value.start,
                        "end": value.end,
                        "text": text[value.start : value.end],
                        "source": value.source,
                    }
                    for value in proposal.soft_ranges
                ],
                "hypothesis_count": len(hypotheses),
                "canonical_match_count": len(canonical),
                "attitude_count": len(attitudes),
                "temporal_count": len(temporals),
                "frame_count": len(frames),
                "embedding_requested_delta": requested_delta,
                "embedding_computed_delta": computed_delta,
                "observation_budget": (
                    budget.diagnostics()
                    if budget is not None
                    else {"enabled": False}
                ),
            },
        )

    def _select_frames(
        self,
        text: str,
        frames: Sequence[Any],
        *,
        budget: ObservationBudget | None = None,
        suppress_unconditioned_objects: bool = False,
    ) -> tuple[
        tuple[Any, ...],
        list[dict[str, Any]],
        dict[str, Any] | None,
    ]:
        confidence_eligible = [
            frame
            for frame in frames
            if frame.confidence >= self.min_frame_confidence
        ]
        stripped = text.strip()
        local_contexts = [
            self._frame_context(text, frame)
            for frame in confidence_eligible
        ]
        formation_texts = tuple(
            dict.fromkeys((stripped, *local_contexts))
        )
        if budget is None:
            assessed = {
                value.text: value
                for value in self.formation_gate.assess(formation_texts)
            }
        else:
            assessed = {}
            for index, formation_text in enumerate(formation_texts):
                if (
                    index > 0
                    and not self.embedder.is_cached(formation_text)
                ):
                    continue
                try:
                    values = self.formation_gate.assess(
                        (formation_text,)
                    )
                except ObservationDeadlineExceeded:
                    continue
                if values:
                    assessed[values[0].text] = values[0]
        full_assessment = assessed.get(stripped)
        full_diagnostics = (
            {
                "text": full_assessment.text,
                "formation_similarity": (
                    full_assessment.formation_similarity
                ),
                "residual_similarity": (
                    full_assessment.residual_similarity
                ),
                "residual_margin": full_assessment.margin,
                "rejected": full_assessment.rejected,
            }
            if full_assessment is not None
            else None
        )
        eligible = []
        gate_diagnostics = []
        for frame, context in zip(confidence_eligible, local_contexts):
            local_assessment = assessed.get(context)
            local = local_assessment or full_assessment
            local_fallback = (
                context not in assessed and full_assessment is not None
            )
            local_rejected = local is None or local.rejected
            full_rejected = bool(
                (
                    full_assessment is None
                    and local_assessment is None
                )
                or (
                    full_assessment is not None
                    and
                    full_assessment.residual_similarity >= 0.66
                    and full_assessment.margin >= 0.10
                )
            )
            rejected = local_rejected or full_rejected
            gate_diagnostics.append(
                {
                    "context": context,
                    "object_tag_id": frame.object.tag_id,
                    "condition_tag_id": (
                        frame.condition.tag_id
                        if frame.condition is not None
                        else None
                    ),
                    "confidence": frame.confidence,
                    "formation_similarity": (
                        local.formation_similarity if local else None
                    ),
                    "residual_similarity": (
                        local.residual_similarity if local else None
                    ),
                    "residual_margin": local.margin if local else None,
                    "local_rejected": local_rejected,
                    "local_full_text_fallback": local_fallback,
                    "full_rejected": full_rejected,
                    "rejected": rejected,
                }
            )
            if not rejected:
                eligible.append(frame)
        if suppress_unconditioned_objects:
            eligible = [
                frame
                for frame in eligible
                if (
                    frame.condition is not None
                    or frame.object.tag_id
                    == "object:ambiguous_prior_workflow"
                )
            ]
        grouped = {}
        for frame in eligible:
            key = (
                (
                    frame.condition.tag_id
                    if frame.condition is not None
                    else None
                ),
                frame.object.tag_id,
            )
            grouped.setdefault(key, []).append(frame)
        selected = []
        for values in grouped.values():
            positive = [
                value
                for value in values
                if value.attitude.value >= 0.10
            ]
            pool = positive or values
            selected.append(
                max(
                    pool,
                    key=lambda value: (
                        value.confidence,
                        value.object.exact_alias,
                        value.attitude.hypothesis_score,
                        -(value.source_end - value.source_start),
                    ),
                )
            )
        conditioned_objects = {
            frame.object.tag_id
            for frame in selected
            if frame.condition is not None
        }
        condition_tags = {
            frame.condition.tag_id
            for frame in selected
            if frame.condition is not None
        }
        selected = [
            frame
            for frame in selected
            if (
                (
                    frame.condition is not None
                    or frame.object.tag_id not in conditioned_objects
                )
                and not (
                    frame.condition is None
                    and frame.object.tag_id in condition_tags
                )
            )
        ]
        return (
            tuple(
                sorted(
                    selected,
                    key=lambda value: (
                        value.source_start,
                        value.source_end,
                        -value.confidence,
                    ),
                )
            ),
            gate_diagnostics,
            full_diagnostics,
        )

    @staticmethod
    def _frame_context(text: str, frame: Any) -> str:
        anchor = min(frame.attitude.start, frame.object.start)
        for start, end in _clause_ranges(text):
            if start <= anchor < end:
                return text[start:end].strip()
        return text[
            min(frame.source_start, len(text)) :
            min(frame.source_end, len(text))
        ].strip()
