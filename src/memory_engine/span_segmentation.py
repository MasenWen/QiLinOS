from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Protocol, Sequence


SAFE_PUNCTUATION = frozenset("，,；;。！？!?\n")
SYNTACTIC_SPLIT_RELATIONS = frozenset(
    {
        "SBV",
        "VOB",
        "IOB",
        "FOB",
        "DBL",
        "ADV",
        "CMP",
        "COO",
        "POB",
        "nsubj",
        "obj",
        "iobj",
        "obl",
        "advmod",
        "advcl",
        "ccomp",
        "xcomp",
        "conj",
    }
)


class TextEmbedder(Protocol):
    def embed(self, texts: list[str]) -> Any: ...


class Segmenter(Protocol):
    name: str

    def segment(self, text: str) -> "SegmentationResult": ...


class BoundaryProposer(Protocol):
    name: str

    def propose(self, text: str) -> Sequence["Boundary"]: ...


@dataclass(frozen=True)
class Boundary:
    position: int
    confidence: float
    source: str
    hard: bool = False
    evidence: tuple[str, ...] = ()


@dataclass(frozen=True)
class Segment:
    start: int
    end: int
    text: str


@dataclass(frozen=True)
class SegmentationResult:
    algorithm: str
    text: str
    boundaries: tuple[Boundary, ...]
    segments: tuple[Segment, ...]
    diagnostics: dict[str, Any] = field(default_factory=dict)

    @property
    def boundary_positions(self) -> tuple[int, ...]:
        return tuple(boundary.position for boundary in self.boundaries)

    def assert_lossless(self) -> None:
        if "".join(segment.text for segment in self.segments) != self.text:
            raise ValueError("segments_do_not_reconstruct_input")
        cursor = 0
        for segment in self.segments:
            if segment.start != cursor or segment.end <= segment.start:
                raise ValueError("segments_are_not_a_contiguous_partition")
            if self.text[segment.start : segment.end] != segment.text:
                raise ValueError("segment_offsets_do_not_match_input")
            cursor = segment.end
        if cursor != len(self.text):
            raise ValueError("segments_do_not_cover_input")


@dataclass(frozen=True)
class SyntacticToken:
    index: int
    text: str
    start: int
    end: int
    pos: str = ""
    head: int = -1
    relation: str = ""


@dataclass(frozen=True)
class PredicateArgument:
    start_token: int
    end_token: int


@dataclass(frozen=True)
class SyntacticAnalysis:
    tokens: tuple[SyntacticToken, ...]
    arguments: tuple[PredicateArgument, ...] = ()


class SyntacticAnalyzer(Protocol):
    def analyze(self, text: str) -> SyntacticAnalysis: ...


def punctuation_boundaries(text: str) -> list[Boundary]:
    boundaries = []
    for index, character in enumerate(text):
        position = index + 1
        if character in SAFE_PUNCTUATION and position < len(text):
            boundaries.append(
                Boundary(
                    position=position,
                    confidence=1.0,
                    source="punctuation",
                    hard=True,
                    evidence=("safe_punctuation",),
                )
            )
    return boundaries


def _normalize_boundaries(
    text: str,
    boundaries: Iterable[Boundary],
) -> tuple[Boundary, ...]:
    merged: dict[int, Boundary] = {}
    for boundary in boundaries:
        if not 0 < boundary.position < len(text):
            continue
        confidence = max(0.0, min(float(boundary.confidence), 1.0))
        normalized = Boundary(
            position=boundary.position,
            confidence=confidence,
            source=boundary.source,
            hard=boundary.hard,
            evidence=tuple(boundary.evidence),
        )
        previous = merged.get(boundary.position)
        if previous is None:
            merged[boundary.position] = normalized
            continue
        sources = sorted(set(previous.source.split("+")) | set(normalized.source.split("+")))
        merged[boundary.position] = Boundary(
            position=boundary.position,
            confidence=max(previous.confidence, normalized.confidence),
            source="+".join(sources),
            hard=previous.hard or normalized.hard,
            evidence=tuple(sorted(set(previous.evidence) | set(normalized.evidence))),
        )
    return tuple(merged[position] for position in sorted(merged))


def build_result(
    algorithm: str,
    text: str,
    boundaries: Iterable[Boundary],
    diagnostics: dict[str, Any] | None = None,
) -> SegmentationResult:
    normalized = _normalize_boundaries(text, boundaries)
    positions = [0, *(boundary.position for boundary in normalized), len(text)]
    segments = tuple(
        Segment(start, end, text[start:end])
        for start, end in zip(positions, positions[1:])
        if start < end
    )
    result = SegmentationResult(
        algorithm=algorithm,
        text=text,
        boundaries=normalized,
        segments=segments,
        diagnostics=diagnostics or {},
    )
    result.assert_lossless()
    return result


class LtpSyntacticAnalyzer:
    """Lazy adapter for the official LTP 4 Pipeline API.

    LTP is optional because its model runtime is substantially heavier than the
    memory engine. Pass an existing ``LTP`` instance in tests or long-lived
    services to avoid repeated model loading.
    """

    def __init__(self, model: str = "LTP/small", pipeline: Any | None = None):
        if pipeline is None:
            try:
                from ltp import LTP
            except ImportError as exc:
                raise RuntimeError(
                    "LTP is optional; install the span-segmentation extra"
                ) from exc
            pipeline = LTP(model)
        self.pipeline = pipeline

    def analyze(self, text: str) -> SyntacticAnalysis:
        output = self.pipeline.pipeline(
            [text],
            tasks=["cws", "pos", "dep", "srl"],
        )
        words = list(output.cws[0])
        positions = _align_tokens(text, words)
        pos_values = list(output.pos[0]) if getattr(output, "pos", None) else []
        dependencies = list(output.dep[0]) if getattr(output, "dep", None) else []
        tokens = []
        for index, (word, (start, end)) in enumerate(zip(words, positions)):
            head, relation = _parse_dependency(
                dependencies[index] if index < len(dependencies) else None
            )
            tokens.append(
                SyntacticToken(
                    index=index,
                    text=word,
                    start=start,
                    end=end,
                    pos=str(pos_values[index]) if index < len(pos_values) else "",
                    head=head,
                    relation=relation,
                )
            )
        arguments = _parse_ltp_srl(
            getattr(output, "srl", None),
            token_count=len(tokens),
        )
        return SyntacticAnalysis(tuple(tokens), tuple(arguments))


def _align_tokens(text: str, words: Sequence[str]) -> list[tuple[int, int]]:
    positions = []
    cursor = 0
    for word in words:
        start = text.find(word, cursor)
        if start < 0:
            raise ValueError(f"cannot_align_token:{word!r}")
        end = start + len(word)
        positions.append((start, end))
        cursor = end
    return positions


def _parse_dependency(value: Any) -> tuple[int, str]:
    if value is None:
        return -1, ""
    if isinstance(value, dict):
        head = value.get("head", value.get("parent", -1))
        relation = value.get("label", value.get("relation", value.get("rel", "")))
    elif isinstance(value, (list, tuple)) and len(value) >= 2:
        head, relation = value[0], value[1]
    else:
        head = getattr(value, "head", getattr(value, "parent", -1))
        relation = getattr(
            value,
            "label",
            getattr(value, "relation", getattr(value, "rel", "")),
        )
    try:
        normalized_head = int(head)
    except (TypeError, ValueError):
        normalized_head = -1
    # LTP uses 0 for ROOT and one-based token heads.
    normalized_head = normalized_head - 1 if normalized_head > 0 else -1
    return normalized_head, str(relation or "")


def _parse_ltp_srl(value: Any, token_count: int) -> list[PredicateArgument]:
    if not value:
        return []
    frames = value[0]
    arguments = []
    for frame in frames:
        raw_arguments = None
        if isinstance(frame, dict):
            raw_arguments = frame.get("arguments", frame.get("args"))
        elif isinstance(frame, (list, tuple)) and len(frame) >= 2:
            raw_arguments = frame[1]
        else:
            raw_arguments = getattr(frame, "arguments", getattr(frame, "args", None))
        for argument in raw_arguments or []:
            if isinstance(argument, dict):
                start = argument.get("start")
                end = argument.get("end")
            elif isinstance(argument, (list, tuple)) and len(argument) >= 3:
                start, end = argument[-2], argument[-1]
            else:
                start = getattr(argument, "start", None)
                end = getattr(argument, "end", None)
            try:
                start_index = int(start)
                end_index = int(end)
            except (TypeError, ValueError):
                continue
            if 0 <= start_index <= end_index < token_count:
                arguments.append(PredicateArgument(start_index, end_index + 1))
    return arguments


class SyntacticBoundaryProposer:
    """Propose boundaries from model-produced SRL and dependency subtrees.

    This class is intentionally not a segmenter. Its output must be decoded by
    an embedding-backed segmenter before it can become a final partition.
    """

    name = "ltp_syntax_srl_candidates"

    def __init__(
        self,
        analyzer: SyntacticAnalyzer | None = None,
        *,
        relations: frozenset[str] = SYNTACTIC_SPLIT_RELATIONS,
        confidence_threshold: float = 0.78,
    ):
        self.analyzer = analyzer or LtpSyntacticAnalyzer()
        self.relations = relations
        self.confidence_threshold = confidence_threshold

    def propose(self, text: str) -> Sequence[Boundary]:
        analysis = self.analyzer.analyze(text)
        candidates = []
        tokens = analysis.tokens

        for argument in analysis.arguments:
            if not 0 <= argument.start_token < argument.end_token <= len(tokens):
                continue
            start = tokens[argument.start_token].start
            end = tokens[argument.end_token - 1].end
            candidates.extend(
                _span_edge_boundaries(
                    text,
                    start,
                    end,
                    confidence=0.96,
                    source="ltp_srl",
                    evidence=("predicate_argument_edge",),
                )
            )

        for token in tokens:
            if token.relation not in self.relations:
                continue
            indices = _dependency_subtree_indices(tokens, token.index)
            if not indices:
                continue
            ordered = sorted(indices)
            if ordered != list(range(ordered[0], ordered[-1] + 1)):
                continue
            start = tokens[ordered[0]].start
            end = tokens[ordered[-1]].end
            candidates.extend(
                _span_edge_boundaries(
                    text,
                    start,
                    end,
                    confidence=0.84,
                    source="ltp_dependency",
                    evidence=("dependency_subtree_edge", token.relation),
                )
            )

        return tuple(
            candidate
            for candidate in _normalize_boundaries(text, candidates)
            if candidate.confidence >= self.confidence_threshold
        )


def _dependency_subtree_indices(
    tokens: Sequence[SyntacticToken],
    root_index: int,
) -> set[int]:
    descendants = {root_index}
    changed = True
    while changed:
        changed = False
        for token in tokens:
            if token.index not in descendants and token.head in descendants:
                descendants.add(token.index)
                changed = True
    return descendants


def _span_edge_boundaries(
    text: str,
    start: int,
    end: int,
    *,
    confidence: float,
    source: str,
    evidence: tuple[str, ...],
) -> list[Boundary]:
    boundaries = []
    if _usable_model_boundary(text, start):
        boundaries.append(Boundary(start, confidence, source, evidence=evidence))
    if _usable_model_boundary(text, end):
        boundaries.append(Boundary(end, confidence, source, evidence=evidence))
    return boundaries


def _usable_model_boundary(text: str, position: int) -> bool:
    if not 0 < position < len(text):
        return False
    return (
        text[position - 1] not in SAFE_PUNCTUATION
        and text[position] not in SAFE_PUNCTUATION
    )


class CrfBoundaryProposer:
    """Candidate adapter for a character-level CRF boundary model.

    The default adapter follows ``sentsplit``'s prediction interface. It must be
    supplied with a domain-trained model; the package's general Chinese model
    detects sentence endings and is intentionally not used as a phrase chunker.
    Predictions are candidates only and still require embedding-backed decoding.
    """

    name = "crf_boundary_candidates"

    def __init__(
        self,
        model_path: str | Path | None = None,
        *,
        predictor: Callable[[str], Sequence[str]] | None = None,
    ):
        if predictor is None:
            if model_path is None:
                raise ValueError("domain_trained_crf_model_required")
            try:
                from sentsplit.segment import SentSplit
            except ImportError as exc:
                raise RuntimeError(
                    "sentsplit is optional; install the span-segmentation extra"
                ) from exc
            splitter = SentSplit(
                "zh",
                model=str(model_path),
                mincut=0,
                maxcut=1_000_000,
                strip_spaces=False,
            )
            predictor = splitter.segment
        self.predictor = predictor

    def propose(self, text: str) -> Sequence[Boundary]:
        pieces = list(self.predictor(text))
        return tuple(_boundaries_from_pieces(text, pieces, self.name))


class CharacterGapProposer:
    """Mechanical high-recall proposer with no lexical or business labels."""

    name = "all_safe_character_gaps"

    def propose(self, text: str) -> Sequence[Boundary]:
        return tuple(
            Boundary(
                position,
                0.50,
                self.name,
                evidence=("mechanical_safe_gap",),
            )
            for position in range(1, len(text))
            if _safe_character_gap(text, position)
        )


def _boundaries_from_pieces(
    text: str,
    pieces: Sequence[str],
    source: str,
) -> list[Boundary]:
    if not pieces:
        return []
    boundaries = []
    cursor = 0
    for piece in pieces:
        if not piece:
            continue
        start = text.find(piece, cursor)
        if start < 0:
            raise ValueError("segmenter_output_cannot_be_aligned_losslessly")
        end = start + len(piece)
        if start > cursor:
            end = start + len(piece)
        cursor = end
        if cursor < len(text):
            boundaries.append(
                Boundary(
                    cursor,
                    0.90,
                    source,
                    evidence=("sequence_boundary",),
                )
            )
    if cursor != len(text):
        raise ValueError("segmenter_output_does_not_cover_input")
    return boundaries


class SemanticTilingSegmenter:
    """TextTiling-style local coherence segmentation over Kylin embeddings.

    This backend deliberately embeds medium-sized left/right windows instead of
    isolated words. It detects local semantic valleys and never compares text to
    memory labels or enumerates arbitrary substrings.
    """

    name = "kylin_semantic_tiling"
    embedding_backed = True

    def __init__(
        self,
        embedder: TextEmbedder,
        *,
        window_chars: int = 8,
        min_segment_chars: int = 3,
        smoothing_radius: int = 2,
        threshold_std: float = 0.35,
        target_segment_chars: int = 7,
        min_depth: float = 0.015,
    ):
        self.embedder = embedder
        self.window_chars = window_chars
        self.min_segment_chars = min_segment_chars
        self.smoothing_radius = smoothing_radius
        self.threshold_std = threshold_std
        self.target_segment_chars = target_segment_chars
        self.min_depth = min_depth

    def segment(self, text: str) -> SegmentationResult:
        hard = punctuation_boundaries(text)
        hard_positions = [0, *(boundary.position for boundary in hard), len(text)]
        selected = list(hard)
        clause_diagnostics = []
        for clause_start, clause_end in zip(hard_positions, hard_positions[1:]):
            clause_boundaries, diagnostics = self._segment_clause(
                text,
                clause_start,
                clause_end,
            )
            selected.extend(clause_boundaries)
            clause_diagnostics.append(diagnostics)
        return build_result(
            self.name,
            text,
            selected,
            diagnostics={"clauses": clause_diagnostics},
        )

    def _segment_clause(
        self,
        text: str,
        clause_start: int,
        clause_end: int,
    ) -> tuple[list[Boundary], dict[str, Any]]:
        candidates = [
            position
            for position in range(
                clause_start + self.min_segment_chars,
                clause_end - self.min_segment_chars + 1,
            )
            if _safe_character_gap(text, position)
        ]
        if len(candidates) < 2:
            return [], {
                "start": clause_start,
                "end": clause_end,
                "candidate_count": len(candidates),
                "selected": [],
            }

        windows = []
        pairs = []
        for position in candidates:
            left = text[max(clause_start, position - self.window_chars) : position]
            right = text[position : min(clause_end, position + self.window_chars)]
            pairs.append((left, right))
            windows.extend((left, right))
        unique_windows = list(dict.fromkeys(windows))
        vectors = self.embedder.embed(unique_windows)
        vector_by_text = {
            value: [float(item) for item in vector]
            for value, vector in zip(unique_windows, vectors)
        }
        similarities = [
            _cosine(vector_by_text[left], vector_by_text[right])
            for left, right in pairs
        ]
        smoothed = _moving_average(similarities, self.smoothing_radius)
        depths = _texttiling_depths(smoothed)
        mean = sum(depths) / len(depths)
        variance = sum((value - mean) ** 2 for value in depths) / len(depths)
        threshold = mean + self.threshold_std * math.sqrt(variance)
        ranked = sorted(
            (
                (depth, position)
                for position, depth in zip(candidates, depths)
                if depth >= threshold and depth >= self.min_depth
            ),
            reverse=True,
        )
        max_internal = max(
            0,
            math.ceil((clause_end - clause_start) / self.target_segment_chars) - 1,
        )
        chosen: list[tuple[float, int]] = []
        for depth, position in ranked:
            anchors = [clause_start, *(item[1] for item in chosen), clause_end]
            if min(abs(position - anchor) for anchor in anchors) < self.min_segment_chars:
                continue
            chosen.append((depth, position))
            if len(chosen) >= max_internal:
                break

        scale = max(max(depths), 1e-9)
        boundaries = [
            Boundary(
                position=position,
                confidence=min(0.89, 0.55 + 0.34 * depth / scale),
                source=self.name,
                evidence=("local_semantic_coherence_valley",),
            )
            for depth, position in sorted(chosen, key=lambda item: item[1])
        ]
        return boundaries, {
            "start": clause_start,
            "end": clause_end,
            "candidate_count": len(candidates),
            "threshold": threshold,
            "selected": [boundary.position for boundary in boundaries],
        }


class EmbeddingCandidateSegmenter:
    """Kylin-backed decoder for boundaries proposed by syntax or a CRF.

    Candidate generators reduce the search space; Kylin embedding evidence has
    the larger weight and can veto every non-punctuation boundary.
    """

    name = "kylin_candidate_decoder"
    embedding_backed = True

    def __init__(
        self,
        embedder: TextEmbedder,
        proposers: Sequence[BoundaryProposer],
        *,
        window_chars: int = 8,
        semantic_weight: float = 0.70,
        threshold: float = 0.56,
        min_segment_chars: int = 2,
        target_segment_chars: int = 6,
        absolute_discontinuity_scale: float = 0.35,
    ):
        if not proposers:
            raise ValueError("at_least_one_boundary_proposer_required")
        if not 0.5 < semantic_weight <= 1.0:
            raise ValueError("semantic_weight_must_give_embedding_the_majority")
        self.embedder = embedder
        self.proposers = tuple(proposers)
        self.window_chars = window_chars
        self.semantic_weight = semantic_weight
        self.threshold = threshold
        self.min_segment_chars = min_segment_chars
        self.target_segment_chars = target_segment_chars
        self.absolute_discontinuity_scale = absolute_discontinuity_scale

    def segment(self, text: str) -> SegmentationResult:
        hard = punctuation_boundaries(text)
        proposed = [
            boundary
            for proposer in self.proposers
            for boundary in proposer.propose(text)
            if not boundary.hard
        ]
        candidates = _normalize_boundaries(text, proposed)
        positions = [boundary.position for boundary in candidates]
        semantic_scores = _embedding_candidate_scores(
            text,
            positions,
            self.embedder,
            window_chars=self.window_chars,
            absolute_discontinuity_scale=self.absolute_discontinuity_scale,
        )
        accepted_candidates = []
        decisions = []
        for candidate in candidates:
            semantic_score = semantic_scores.get(candidate.position, 0.0)
            combined = (
                self.semantic_weight * semantic_score
                + (1.0 - self.semantic_weight) * candidate.confidence
            )
            accepted = combined >= self.threshold
            decisions.append(
                {
                    "position": candidate.position,
                    "candidate_source": candidate.source,
                    "candidate_confidence": candidate.confidence,
                    "embedding_score": semantic_score,
                    "combined_score": combined,
                    "accepted": accepted,
                }
            )
            if accepted:
                accepted_candidates.append(
                    Boundary(
                        position=candidate.position,
                        confidence=combined,
                        source=f"kylin+{candidate.source}",
                        evidence=(
                            "embedding_majority_decision",
                            *candidate.evidence,
                        ),
                    )
                )
        selected = [
            *hard,
            *_select_spaced_boundaries(
                text,
                accepted_candidates,
                hard_positions={boundary.position for boundary in hard},
                min_segment_chars=self.min_segment_chars,
                target_segment_chars=self.target_segment_chars,
            ),
        ]
        return build_result(
            self.name,
            text,
            selected,
            diagnostics={
                "semantic_weight": self.semantic_weight,
                "proposers": [proposer.name for proposer in self.proposers],
                "decisions": decisions,
            },
        )


def _select_spaced_boundaries(
    text: str,
    candidates: Sequence[Boundary],
    *,
    hard_positions: set[int],
    min_segment_chars: int,
    target_segment_chars: int,
) -> list[Boundary]:
    anchors = [0, *sorted(hard_positions), len(text)]
    selected = []
    for clause_start, clause_end in zip(anchors, anchors[1:]):
        clause_candidates = [
            candidate
            for candidate in candidates
            if clause_start < candidate.position < clause_end
        ]
        limit = max(
            0,
            math.ceil((clause_end - clause_start) / target_segment_chars) - 1,
        )
        chosen = []
        for candidate in sorted(
            clause_candidates,
            key=lambda item: (item.confidence, -item.position),
            reverse=True,
        ):
            local_anchors = [clause_start, *(item.position for item in chosen), clause_end]
            if min(
                abs(candidate.position - anchor)
                for anchor in local_anchors
            ) < min_segment_chars:
                continue
            chosen.append(candidate)
            if len(chosen) >= limit:
                break
        selected.extend(sorted(chosen, key=lambda item: item.position))
    return selected


def _embedding_candidate_scores(
    text: str,
    positions: Sequence[int],
    embedder: TextEmbedder,
    *,
    window_chars: int,
    absolute_discontinuity_scale: float,
) -> dict[int, float]:
    if not positions:
        return {}
    ordered = sorted(set(positions))
    windows = []
    pairs = []
    for position in ordered:
        clause_start, clause_end = _containing_clause(text, position)
        left = text[max(clause_start, position - window_chars) : position]
        right = text[position : min(clause_end, position + window_chars)]
        if not left.strip() or not right.strip():
            pairs.append(("", ""))
            continue
        pairs.append((left, right))
        windows.extend((left, right))
    unique_windows = list(dict.fromkeys(windows))
    if not unique_windows:
        return {position: 0.0 for position in ordered}
    vectors = embedder.embed(unique_windows)
    vector_by_text = {
        value: [float(item) for item in vector]
        for value, vector in zip(unique_windows, vectors)
    }
    discontinuities = []
    for left, right in pairs:
        if not left or not right:
            discontinuities.append(0.0)
        else:
            discontinuities.append(
                max(0.0, 1.0 - _cosine(vector_by_text[left], vector_by_text[right]))
            )
    relative = _rank_normalize(discontinuities)
    peak_depths = _local_peak_depths(discontinuities)
    normalized_depths = _minmax_normalize(peak_depths)
    absolute = [
        min(1.0, value / max(absolute_discontinuity_scale, 1e-9))
        for value in discontinuities
    ]
    return {
        position: (
            0.45 * absolute_score
            + 0.35 * rank_score
            + 0.20 * depth_score
        )
        for position, absolute_score, rank_score, depth_score in zip(
            ordered,
            absolute,
            relative,
            normalized_depths,
        )
    }


def _containing_clause(text: str, position: int) -> tuple[int, int]:
    start = position
    while start > 0 and text[start - 1] not in SAFE_PUNCTUATION:
        start -= 1
    end = position
    while end < len(text) and text[end] not in SAFE_PUNCTUATION:
        end += 1
    return start, end


def _rank_normalize(values: Sequence[float]) -> list[float]:
    if not values:
        return []
    if len(values) == 1:
        return [0.5]
    order = sorted(range(len(values)), key=lambda index: values[index])
    ranks = [0.0] * len(values)
    cursor = 0
    while cursor < len(order):
        end = cursor + 1
        rounded = round(values[order[cursor]], 9)
        while end < len(order) and round(values[order[end]], 9) == rounded:
            end += 1
        average_rank = (cursor + end - 1) / 2.0
        normalized = average_rank / (len(values) - 1)
        for index in order[cursor:end]:
            ranks[index] = normalized
        cursor = end
    return ranks


def _local_peak_depths(values: Sequence[float]) -> list[float]:
    depths = []
    for index, value in enumerate(values):
        left = values[index - 1] if index > 0 else value
        right = values[index + 1] if index + 1 < len(values) else value
        depths.append(max(0.0, value - 0.5 * (left + right)))
    return depths


def _minmax_normalize(values: Sequence[float]) -> list[float]:
    if not values:
        return []
    lower = min(values)
    upper = max(values)
    if math.isclose(lower, upper):
        return [0.5] * len(values)
    return [(value - lower) / (upper - lower) for value in values]


def _safe_character_gap(text: str, position: int) -> bool:
    if not 0 < position < len(text):
        return False
    left = text[position - 1]
    right = text[position]
    if left.isspace() or right.isspace():
        return False
    ascii_word = re.compile(r"[A-Za-z0-9_.-]")
    if left.isascii() and right.isascii() and ascii_word.match(left) and ascii_word.match(right):
        return False
    return left not in SAFE_PUNCTUATION and right not in SAFE_PUNCTUATION


def _moving_average(values: Sequence[float], radius: int) -> list[float]:
    if radius <= 0:
        return list(values)
    smoothed = []
    for index in range(len(values)):
        start = max(0, index - radius)
        end = min(len(values), index + radius + 1)
        smoothed.append(sum(values[start:end]) / (end - start))
    return smoothed


def _texttiling_depths(similarities: Sequence[float]) -> list[float]:
    depths = []
    for index, value in enumerate(similarities):
        left_peak = value
        cursor = index - 1
        while cursor >= 0 and similarities[cursor] >= left_peak:
            left_peak = similarities[cursor]
            cursor -= 1
        right_peak = value
        cursor = index + 1
        while cursor < len(similarities) and similarities[cursor] >= right_peak:
            right_peak = similarities[cursor]
            cursor += 1
        depths.append(max(0.0, left_peak + right_peak - 2.0 * value))
    return depths


class PeltEmbeddingSegmenter:
    """PELT change-point detection over sliding Kylin embedding windows."""

    name = "kylin_embedding_pelt"
    embedding_backed = True

    def __init__(
        self,
        embedder: TextEmbedder,
        *,
        window_chars: int = 8,
        step_chars: int = 2,
        min_segment_windows: int = 2,
        penalty: float = 4.0,
    ):
        self.embedder = embedder
        self.window_chars = window_chars
        self.step_chars = step_chars
        self.min_segment_windows = min_segment_windows
        self.penalty = penalty

    def segment(self, text: str) -> SegmentationResult:
        try:
            import numpy as np
            import ruptures as rpt
        except ImportError as exc:
            raise RuntimeError(
                "ruptures is optional; install the span-segmentation extra"
            ) from exc

        hard = punctuation_boundaries(text)
        hard_positions = [0, *(boundary.position for boundary in hard), len(text)]
        selected = list(hard)
        diagnostics = []
        for clause_start, clause_end in zip(hard_positions, hard_positions[1:]):
            starts = list(
                range(
                    clause_start,
                    max(clause_start + 1, clause_end - self.window_chars + 1),
                    self.step_chars,
                )
            )
            windows = [
                text[start : min(clause_end, start + self.window_chars)]
                for start in starts
            ]
            if len(windows) < self.min_segment_windows * 2:
                continue
            signal = np.asarray(self.embedder.embed(windows), dtype=np.float32)
            change_points = rpt.Pelt(
                model="l2",
                min_size=self.min_segment_windows,
                jump=1,
            ).fit(signal).predict(pen=self.penalty)
            positions = []
            for change_point in change_points[:-1]:
                raw_position = _window_change_point_position(
                    starts,
                    change_point,
                    self.window_chars,
                )
                position = _nearest_safe_gap(text, raw_position, clause_start, clause_end)
                if position is not None:
                    positions.append(position)
                    selected.append(
                        Boundary(
                            position,
                            0.75,
                            self.name,
                            evidence=("pelt_change_point",),
                        )
                    )
            diagnostics.append(
                {
                    "start": clause_start,
                    "end": clause_end,
                    "window_count": len(windows),
                    "selected": positions,
                }
            )
        return build_result(
            self.name,
            text,
            selected,
            diagnostics={"clauses": diagnostics},
        )


class GlobalEmbeddingPartitionSegmenter:
    """Exact global change-point decoding over sliding Kylin vectors.

    The objective is the same piecewise-stationary L2 cost used by mature
    change-point packages, while the small in-repo decoder avoids making the
    experiment depend on SciPy or scikit-learn.
    """

    name = "kylin_embedding_global_partition"
    embedding_backed = True

    def __init__(
        self,
        embedder: TextEmbedder,
        *,
        window_chars: int = 8,
        step_chars: int = 2,
        min_segment_windows: int = 2,
        penalty: float = 0.10,
    ):
        self.embedder = embedder
        self.window_chars = window_chars
        self.step_chars = step_chars
        self.min_segment_windows = min_segment_windows
        self.penalty = penalty

    def segment(self, text: str) -> SegmentationResult:
        hard = punctuation_boundaries(text)
        anchors = [0, *(boundary.position for boundary in hard), len(text)]
        selected = list(hard)
        diagnostics = []
        for clause_start, clause_end in zip(anchors, anchors[1:]):
            starts = _sliding_window_starts(
                clause_start,
                clause_end,
                window_chars=self.window_chars,
                step_chars=self.step_chars,
            )
            windows = [
                text[start : min(clause_end, start + self.window_chars)]
                for start in starts
            ]
            if len(windows) < self.min_segment_windows * 2:
                diagnostics.append(
                    {
                        "start": clause_start,
                        "end": clause_end,
                        "window_count": len(windows),
                        "selected": [],
                    }
                )
                continue
            vectors = [
                [float(value) for value in vector]
                for vector in self.embedder.embed(windows)
            ]
            change_points = _optimal_l2_change_points(
                vectors,
                min_size=self.min_segment_windows,
                penalty=self.penalty,
            )
            partition_diagnostics = _embedding_partition_diagnostics(
                vectors,
                change_points,
            )
            positions = []
            for change_point in change_points:
                raw_position = _window_change_point_position(
                    starts,
                    change_point,
                    self.window_chars,
                )
                position = _nearest_safe_gap(
                    text,
                    raw_position,
                    clause_start,
                    clause_end,
                )
                if position is None:
                    continue
                positions.append(position)
                selected.append(
                    Boundary(
                        position,
                        0.78,
                        self.name,
                        evidence=("global_embedding_change_point",),
                    )
                )
            diagnostics.append(
                {
                    "start": clause_start,
                    "end": clause_end,
                    "window_count": len(windows),
                    "change_points": change_points,
                    "selected": positions,
                    "partition": partition_diagnostics,
                }
            )
        return build_result(
            self.name,
            text,
            selected,
            diagnostics={"clauses": diagnostics, "penalty": self.penalty},
        )


class AdaptiveGlobalEmbeddingPartitionSegmenter:
    """Kernel model selection plus local refinement for short utterances.

    The global stage follows kernel change-point detection: it computes the
    optimal partition for each feasible segment count and then applies a
    nonlinear complexity penalty. The local stage only refines those globally
    selected changes; it does not enumerate independent boundary decisions.
    """

    name = "kylin_embedding_global_adaptive"
    embedding_backed = True

    def __init__(
        self,
        embedder: TextEmbedder,
        *,
        min_window_chars: int = 4,
        max_window_chars: int = 8,
        step_chars: int = 1,
        min_segment_windows: int = 2,
        slope_multiplier: float = 2.0,
    ):
        self.embedder = embedder
        self.min_window_chars = min_window_chars
        self.max_window_chars = max_window_chars
        self.step_chars = step_chars
        self.min_segment_windows = min_segment_windows
        self.slope_multiplier = slope_multiplier

    def segment(self, text: str) -> SegmentationResult:
        hard = punctuation_boundaries(text)
        anchors = [0, *(boundary.position for boundary in hard), len(text)]
        selected = list(hard)
        diagnostics = []
        for clause_start, clause_end in zip(anchors, anchors[1:]):
            clause_length = clause_end - clause_start
            window_chars = min(
                self.max_window_chars,
                max(self.min_window_chars, clause_length // 3),
                clause_length,
            )
            starts = _sliding_window_starts(
                clause_start,
                clause_end,
                window_chars=window_chars,
                step_chars=self.step_chars,
            )
            windows = [
                text[start : min(clause_end, start + window_chars)]
                for start in starts
            ]
            if len(windows) < self.min_segment_windows * 2:
                diagnostics.append(
                    {
                        "start": clause_start,
                        "end": clause_end,
                        "window_chars": window_chars,
                        "window_count": len(windows),
                        "selected": [],
                        "reason": "insufficient_windows",
                    }
                )
                continue
            vectors = [
                _unit_vector([float(value) for value in vector])
                for vector in self.embedder.embed(windows)
            ]
            change_points, model_selection = (
                _kernel_model_selected_change_points(
                    vectors,
                    min_size=self.min_segment_windows,
                    slope_multiplier=self.slope_multiplier,
                )
            )
            coarse_positions = [
                _window_change_point_position(
                    starts,
                    change_point,
                    window_chars,
                )
                for change_point in change_points
            ]
            refined_positions, refinement = _refine_global_boundaries(
                text,
                clause_start,
                clause_end,
                coarse_positions,
                self.embedder,
                window_chars=window_chars,
            )
            for position in refined_positions:
                selected.append(
                    Boundary(
                        position,
                        0.80,
                        self.name,
                        evidence=(
                            "kernel_model_selected_change_point",
                            "multiscale_embedding_refinement",
                        ),
                    )
                )
            diagnostics.append(
                {
                    "start": clause_start,
                    "end": clause_end,
                    "window_chars": window_chars,
                    "window_count": len(windows),
                    "change_points": change_points,
                    "coarse_positions": coarse_positions,
                    "selected": refined_positions,
                    "model_selection": model_selection,
                    "refinement": refinement,
                }
            )
        return build_result(
            self.name,
            text,
            selected,
            diagnostics={
                "clauses": diagnostics,
                "slope_multiplier": self.slope_multiplier,
            },
        )


def _sliding_window_starts(
    start: int,
    end: int,
    *,
    window_chars: int,
    step_chars: int,
) -> list[int]:
    if start >= end:
        return []
    last = max(start, end - window_chars)
    starts = list(range(start, last + 1, step_chars))
    if not starts or starts[-1] != last:
        starts.append(last)
    return starts


def _window_change_point_position(
    starts: Sequence[int],
    change_point: int,
    window_chars: int,
) -> int:
    """Map a change in the window sequence to the window's semantic center."""
    return (
        starts[min(max(change_point, 0), len(starts) - 1)]
        + window_chars // 2
    )


def _optimal_l2_change_points(
    vectors: Sequence[Sequence[float]],
    *,
    min_size: int,
    penalty: float,
) -> list[int]:
    sample_count = len(vectors)
    if sample_count < min_size * 2:
        return []
    dimension = len(vectors[0])
    prefix = [[0.0] * dimension]
    prefix_norm = [0.0]
    for vector in vectors:
        prefix.append(
            [
                previous + float(value)
                for previous, value in zip(prefix[-1], vector)
            ]
        )
        prefix_norm.append(
            prefix_norm[-1] + sum(float(value) ** 2 for value in vector)
        )

    def segment_cost(start: int, end: int) -> float:
        length = end - start
        summed = [
            prefix[end][index] - prefix[start][index]
            for index in range(dimension)
        ]
        squared_sum = prefix_norm[end] - prefix_norm[start]
        centroid_term = sum(value * value for value in summed) / length
        return max(0.0, squared_sum - centroid_term)

    best = [math.inf] * (sample_count + 1)
    previous = [-1] * (sample_count + 1)
    best[0] = -penalty
    for end in range(min_size, sample_count + 1):
        for start in range(0, end - min_size + 1):
            if start != 0 and start < min_size:
                continue
            if not math.isfinite(best[start]):
                continue
            score = best[start] + segment_cost(start, end) + penalty
            if score < best[end]:
                best[end] = score
                previous[end] = start
    if previous[sample_count] < 0:
        return []
    change_points = []
    cursor = sample_count
    while previous[cursor] > 0:
        change_points.append(previous[cursor])
        cursor = previous[cursor]
    return sorted(change_points)


def _kernel_model_selected_change_points(
    vectors: Sequence[Sequence[float]],
    *,
    min_size: int,
    slope_multiplier: float,
) -> tuple[list[int], dict[str, Any]]:
    partitions = _optimal_l2_partitions_by_count(
        vectors,
        min_size=min_size,
    )
    if not partitions:
        return [], {
            "residual_scale": 0.0,
            "selected_segments": 1,
            "curve": [],
        }

    adjacent_distances = [
        max(0.0, 1.0 - _cosine(left, right))
        for left, right in zip(vectors, vectors[1:])
    ]
    residual_scale = _median(adjacent_distances)
    leading_constant = slope_multiplier * residual_scale
    sample_count = len(vectors)
    curve = []
    for partition in partitions:
        segment_count = int(partition["segments"])
        log_model_count = (
            0.0
            if segment_count == 1
            else (
                math.lgamma(sample_count)
                - math.lgamma(segment_count)
                - math.lgamma(sample_count - segment_count + 1)
            )
        )
        empirical_risk = float(partition["cost"]) / sample_count
        complexity = (log_model_count + segment_count) / sample_count
        penalty = leading_constant * complexity
        curve.append(
            {
                **partition,
                "empirical_risk": empirical_risk,
                "complexity": complexity,
                "penalty": penalty,
                "criterion": empirical_risk + penalty,
            }
        )
    selected = min(
        curve,
        key=lambda item: (float(item["criterion"]), int(item["segments"])),
    )
    return list(selected["change_points"]), {
        "residual_scale": residual_scale,
        "leading_constant": leading_constant,
        "selected_segments": selected["segments"],
        "curve": curve,
    }


def _optimal_l2_partitions_by_count(
    vectors: Sequence[Sequence[float]],
    *,
    min_size: int,
) -> list[dict[str, Any]]:
    sample_count = len(vectors)
    if sample_count < min_size:
        return []
    dimension = len(vectors[0])
    prefix = [[0.0] * dimension]
    prefix_norm = [0.0]
    for vector in vectors:
        prefix.append(
            [
                previous + float(value)
                for previous, value in zip(prefix[-1], vector)
            ]
        )
        prefix_norm.append(
            prefix_norm[-1] + sum(float(value) ** 2 for value in vector)
        )

    def segment_cost(start: int, end: int) -> float:
        length = end - start
        summed = [
            prefix[end][index] - prefix[start][index]
            for index in range(dimension)
        ]
        squared_sum = prefix_norm[end] - prefix_norm[start]
        centroid_term = sum(value * value for value in summed) / length
        return max(0.0, squared_sum - centroid_term)

    max_segments = sample_count // min_size
    best = [
        [math.inf] * (sample_count + 1)
        for _ in range(max_segments + 1)
    ]
    previous = [
        [-1] * (sample_count + 1)
        for _ in range(max_segments + 1)
    ]
    best[0][0] = 0.0
    for segment_count in range(1, max_segments + 1):
        minimum_end = segment_count * min_size
        for end in range(minimum_end, sample_count + 1):
            minimum_start = (segment_count - 1) * min_size
            maximum_start = end - min_size
            for start in range(minimum_start, maximum_start + 1):
                prior = best[segment_count - 1][start]
                if not math.isfinite(prior):
                    continue
                score = prior + segment_cost(start, end)
                if score < best[segment_count][end]:
                    best[segment_count][end] = score
                    previous[segment_count][end] = start

    partitions = []
    for segment_count in range(1, max_segments + 1):
        if not math.isfinite(best[segment_count][sample_count]):
            continue
        change_points = []
        cursor = sample_count
        remaining = segment_count
        while remaining > 0:
            start = previous[remaining][cursor]
            if start < 0:
                change_points = []
                break
            if start > 0:
                change_points.append(start)
            cursor = start
            remaining -= 1
        partitions.append(
            {
                "segments": segment_count,
                "change_points": sorted(change_points),
                "cost": best[segment_count][sample_count],
            }
        )
    return partitions


def _refine_global_boundaries(
    text: str,
    clause_start: int,
    clause_end: int,
    coarse_positions: Sequence[int],
    embedder: TextEmbedder,
    *,
    window_chars: int,
) -> tuple[list[int], list[dict[str, Any]]]:
    if not coarse_positions:
        return [], []

    ordered = sorted(coarse_positions)
    scales = sorted({max(2, window_chars // 2), window_chars})
    candidate_groups = []
    snippets = []
    for index, coarse in enumerate(ordered):
        previous = ordered[index - 1] if index > 0 else None
        following = ordered[index + 1] if index + 1 < len(ordered) else None
        lower = max(
            clause_start + 2,
            coarse - window_chars,
            (previous + coarse) // 2 + 1 if previous is not None else clause_start + 2,
        )
        upper = min(
            clause_end - 2,
            coarse + window_chars,
            (coarse + following) // 2 if following is not None else clause_end - 2,
        )
        candidates = [
            position
            for position in range(lower, upper + 1)
            if _safe_character_gap(text, position)
        ]
        records = []
        for position in candidates:
            contexts = []
            for scale in scales:
                left = text[max(clause_start, position - scale) : position]
                right = text[position : min(clause_end, position + scale)]
                if left.strip() and right.strip():
                    contexts.append((left, right))
                    snippets.extend((left, right))
            records.append((position, contexts))
        candidate_groups.append((coarse, records))

    unique_snippets = list(dict.fromkeys(snippets))
    if not unique_snippets:
        return [], []
    vectors = embedder.embed(unique_snippets)
    vector_by_text = {
        value: _unit_vector([float(item) for item in vector])
        for value, vector in zip(unique_snippets, vectors)
    }

    selected = []
    diagnostics = []
    for coarse, records in candidate_groups:
        scored = []
        for position, contexts in records:
            distances = [
                max(
                    0.0,
                    1.0
                    - _cosine(
                        vector_by_text[left],
                        vector_by_text[right],
                    ),
                )
                for left, right in contexts
            ]
            if distances:
                scored.append(
                    {
                        "position": position,
                        "score": sum(distances) / len(distances),
                        "distance_from_coarse": abs(position - coarse),
                    }
                )
        if not scored:
            diagnostics.append(
                {
                    "coarse": coarse,
                    "selected": None,
                    "top_candidates": [],
                }
            )
            continue
        ranked = sorted(
            scored,
            key=lambda item: (
                -float(item["score"]),
                int(item["distance_from_coarse"]),
                int(item["position"]),
            ),
        )
        chosen = int(ranked[0]["position"])
        selected.append(chosen)
        diagnostics.append(
            {
                "coarse": coarse,
                "selected": chosen,
                "top_candidates": ranked[:3],
            }
        )
    return sorted(set(selected)), diagnostics


def _unit_vector(vector: Sequence[float]) -> list[float]:
    norm = math.sqrt(sum(float(value) ** 2 for value in vector))
    if norm <= 1e-12:
        return [0.0 for _ in vector]
    return [float(value) / norm for value in vector]


def _median(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(float(value) for value in values)
    midpoint = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[midpoint]
    return 0.5 * (ordered[midpoint - 1] + ordered[midpoint])


def _embedding_partition_diagnostics(
    vectors: Sequence[Sequence[float]],
    change_points: Sequence[int],
) -> dict[str, Any]:
    if not vectors:
        return {
            "vector_norm_min": 0.0,
            "vector_norm_max": 0.0,
            "no_split_cost": 0.0,
            "partition_cost": 0.0,
            "relative_gain": 0.0,
            "adjacent_discontinuities": [],
        }

    def interval_cost(start: int, end: int) -> float:
        length = end - start
        dimension = len(vectors[0])
        centroid = [
            sum(float(vectors[row][column]) for row in range(start, end))
            / length
            for column in range(dimension)
        ]
        return sum(
            sum(
                (float(vectors[row][column]) - centroid[column]) ** 2
                for column in range(dimension)
            )
            for row in range(start, end)
        )

    norms = [
        math.sqrt(sum(float(value) ** 2 for value in vector))
        for vector in vectors
    ]
    no_split_cost = interval_cost(0, len(vectors))
    anchors = [0, *change_points, len(vectors)]
    partition_cost = sum(
        interval_cost(start, end)
        for start, end in zip(anchors, anchors[1:])
    )
    relative_gain = (
        (no_split_cost - partition_cost) / no_split_cost
        if no_split_cost > 1e-12
        else 0.0
    )
    adjacent_discontinuities = [
        {
            "change_point": change_point,
            "cosine_distance": 1.0
            - _cosine(vectors[change_point - 1], vectors[change_point]),
        }
        for change_point in change_points
        if 0 < change_point < len(vectors)
    ]
    return {
        "vector_norm_min": min(norms),
        "vector_norm_max": max(norms),
        "no_split_cost": no_split_cost,
        "partition_cost": partition_cost,
        "relative_gain": relative_gain,
        "adjacent_discontinuities": adjacent_discontinuities,
    }


def _nearest_safe_gap(
    text: str,
    position: int,
    lower: int,
    upper: int,
) -> int | None:
    for distance in range(0, 4):
        for candidate in (position - distance, position + distance):
            if lower < candidate < upper and _safe_character_gap(text, candidate):
                return candidate
    return None


def _cosine(left: Sequence[float], right: Sequence[float]) -> float:
    numerator = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return max(-1.0, min(1.0, numerator / (left_norm * right_norm)))
