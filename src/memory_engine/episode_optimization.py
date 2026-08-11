from __future__ import annotations

from dataclasses import asdict, dataclass, field
from types import MappingProxyType
from typing import Iterable, Mapping, Sequence


def _clean_tags(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(value for value in values if value))


def _clean_scores(values: Mapping[str, float]) -> Mapping[str, float]:
    return MappingProxyType(
        {
            tag_id: max(-1.0, min(1.0, float(score)))
            for tag_id, score in values.items()
            if tag_id
        }
    )


@dataclass(frozen=True)
class EpisodeOptimizationEvent:
    """Evidence used after the stable streaming Episode grouper."""

    event_id: str
    condition_tag_id: str | None = None
    condition_scores: Mapping[str, float] = field(default_factory=dict)
    object_tag_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.event_id:
            raise ValueError("event_id must not be empty")
        object.__setattr__(
            self,
            "condition_scores",
            _clean_scores(self.condition_scores),
        )
        object.__setattr__(
            self,
            "object_tag_ids",
            _clean_tags(self.object_tag_ids),
        )


@dataclass(frozen=True)
class EpisodeBoundaryRepairConfig:
    relation_object_tag_ids: tuple[str, ...] = (
        "object:preference_versioning",
    )
    max_unknown_events: int = 4
    condition_weight: float = 1.0
    object_weight: float = 0.12
    baseline_stickiness: float = 0.04
    min_evidence_margin: float = 0.035
    min_total_gain: float = 0.08
    min_runner_up_margin: float = 0.03
    min_collapse_margin: float = 0.06

    def __post_init__(self) -> None:
        if self.max_unknown_events < 1:
            raise ValueError("max_unknown_events must be positive")
        if min(
            self.condition_weight,
            self.object_weight,
            self.baseline_stickiness,
            self.min_evidence_margin,
            self.min_total_gain,
            self.min_runner_up_margin,
            self.min_collapse_margin,
        ) < 0.0:
            raise ValueError("weights and margins must be non-negative")
        object.__setattr__(
            self,
            "relation_object_tag_ids",
            _clean_tags(self.relation_object_tag_ids),
        )


@dataclass(frozen=True)
class EpisodeBoundaryRepairDecision:
    left_anchor_event_id: str
    right_anchor_event_id: str
    old_boundary: int
    new_boundary: int
    changed: bool
    reason: str
    old_score: float
    new_score: float
    runner_up_score: float
    evidence_event_ids: tuple[str, ...]
    old_boundaries: tuple[int, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class EpisodeBoundaryRepairResult:
    boundaries: tuple[int, ...]
    assignments: Mapping[str, str]
    decisions: tuple[EpisodeBoundaryRepairDecision, ...]


@dataclass(frozen=True)
class GlobalEpisodeDecoderConfig:
    relation_object_tag_ids: tuple[str, ...] = (
        "object:preference_versioning",
    )
    condition_weight: float = 1.0
    explicit_condition_reward: float = 1.0
    explicit_condition_conflict_penalty: float = 3.0
    repeated_object_reward: float = 0.04
    conflicting_object_penalty: float = 0.03
    boundary_cost: float = 0.24
    baseline_boundary_reward: float = 0.10
    require_condition_score_for_boundary_change: bool = True
    max_segment_events: int | None = None
    episode_id_prefix: str = "optimized-episode"

    def __post_init__(self) -> None:
        if self.max_segment_events is not None and self.max_segment_events < 1:
            raise ValueError("max_segment_events must be positive")
        if min(
            self.condition_weight,
            self.explicit_condition_reward,
            self.explicit_condition_conflict_penalty,
            self.repeated_object_reward,
            self.conflicting_object_penalty,
            self.boundary_cost,
            self.baseline_boundary_reward,
        ) < 0.0:
            raise ValueError("weights and penalties must be non-negative")
        if not self.episode_id_prefix:
            raise ValueError("episode_id_prefix must not be empty")
        object.__setattr__(
            self,
            "relation_object_tag_ids",
            _clean_tags(self.relation_object_tag_ids),
        )


@dataclass(frozen=True)
class GlobalEpisodeSegment:
    start: int
    end: int
    condition_tag_id: str | None
    score: float


@dataclass(frozen=True)
class GlobalEpisodeDecodeResult:
    boundaries: tuple[int, ...]
    assignments: Mapping[str, str]
    score: float
    segments: tuple[GlobalEpisodeSegment, ...]


def boundaries_from_assignments(
    events: Sequence[EpisodeOptimizationEvent],
    assignments: Mapping[str, str],
) -> tuple[int, ...]:
    boundaries = []
    for index in range(1, len(events)):
        previous = assignments[events[index - 1].event_id]
        current = assignments[events[index].event_id]
        if previous != current:
            boundaries.append(index)
    return tuple(boundaries)


def assignments_from_boundaries(
    events: Sequence[EpisodeOptimizationEvent],
    boundaries: Iterable[int],
    *,
    episode_id_prefix: str = "optimized-episode",
) -> Mapping[str, str]:
    boundary_set = set(boundaries)
    if any(value <= 0 or value >= len(events) for value in boundary_set):
        raise ValueError("boundaries must fall between events")
    assignments: dict[str, str] = {}
    group_number = 1
    for index, event in enumerate(events):
        if index in boundary_set:
            group_number += 1
        assignments[event.event_id] = (
            f"{episode_id_prefix}-{group_number:04d}"
        )
    return MappingProxyType(assignments)


def _subject_tags(
    event: EpisodeOptimizationEvent,
    relation_object_tag_ids: set[str],
) -> set[str]:
    return set(event.object_tag_ids) - relation_object_tag_ids


def _relative_condition_support(
    event: EpisodeOptimizationEvent,
    tag_id: str,
) -> float:
    score = event.condition_scores.get(tag_id)
    if score is None:
        return 0.0
    alternatives = [
        value
        for candidate, value in event.condition_scores.items()
        if candidate != tag_id
    ]
    return score - (max(alternatives) if alternatives else 0.0)


def _anchor_subjects(
    events: Sequence[EpisodeOptimizationEvent],
    anchor_index: int,
    *,
    direction: int,
    condition_tag_id: str,
    relation_object_tag_ids: set[str],
    limit: int = 3,
) -> set[str]:
    subjects: set[str] = set()
    cursor = anchor_index
    inspected = 0
    while 0 <= cursor < len(events) and inspected < limit:
        event = events[cursor]
        if (
            event.condition_tag_id
            and event.condition_tag_id != condition_tag_id
        ):
            break
        subjects.update(_subject_tags(event, relation_object_tag_ids))
        cursor += direction
        inspected += 1
    return subjects


def _candidate_boundary_score(
    events: Sequence[EpisodeOptimizationEvent],
    *,
    left_anchor: int,
    right_anchor: int,
    boundary: int,
    old_boundary: int,
    left_tag: str,
    right_tag: str,
    left_subjects: set[str],
    right_subjects: set[str],
    settings: EpisodeBoundaryRepairConfig,
    relation_object_tag_ids: set[str],
) -> tuple[float, tuple[str, ...]]:
    score = (
        settings.baseline_stickiness
        if boundary == old_boundary
        else 0.0
    )
    evidence_event_ids = []
    for index in range(left_anchor + 1, right_anchor):
        event = events[index]
        left_condition = _relative_condition_support(event, left_tag)
        right_condition = _relative_condition_support(event, right_tag)
        left_object = 0.0
        right_object = 0.0
        subjects = _subject_tags(event, relation_object_tag_ids)
        if subjects:
            if subjects & left_subjects:
                left_object = settings.object_weight
            if subjects & right_subjects:
                right_object = settings.object_weight
        left_support = (
            settings.condition_weight * left_condition + left_object
        )
        right_support = (
            settings.condition_weight * right_condition + right_object
        )
        if (
            abs(left_support - right_support)
            >= settings.min_evidence_margin
        ):
            evidence_event_ids.append(event.event_id)
        selected = left_support if index < boundary else right_support
        score += selected
    return score, tuple(evidence_event_ids)


def repair_episode_boundaries(
    events: Sequence[EpisodeOptimizationEvent],
    baseline_boundaries: Iterable[int],
    *,
    config: EpisodeBoundaryRepairConfig | None = None,
) -> EpisodeBoundaryRepairResult:
    """Move a delayed boundary only when both-side evidence is decisive."""

    settings = config or EpisodeBoundaryRepairConfig()
    if len({event.event_id for event in events}) != len(events):
        raise ValueError("event_id must be unique")
    boundaries = set(baseline_boundaries)
    if any(value <= 0 or value >= len(events) for value in boundaries):
        raise ValueError("boundaries must fall between events")
    relation_tags = set(settings.relation_object_tag_ids)
    anchors = [
        index
        for index, event in enumerate(events)
        if event.condition_tag_id
    ]
    decisions = []

    for left_anchor, right_anchor in zip(
        anchors,
        anchors[1:],
        strict=False,
    ):
        left_tag = events[left_anchor].condition_tag_id
        right_tag = events[right_anchor].condition_tag_id
        unknown_count = right_anchor - left_anchor - 1
        if (
            left_tag is None
            or right_tag is None
            or left_tag == right_tag
            or unknown_count < 1
            or unknown_count > settings.max_unknown_events
        ):
            continue
        local_boundaries = sorted(
            value
            for value in boundaries
            if left_anchor < value <= right_anchor
        )
        if not local_boundaries:
            continue
        multiple_boundaries = len(local_boundaries) > 1
        old_boundary = local_boundaries[-1]
        scoring_old_boundary = (
            -1 if multiple_boundaries else old_boundary
        )
        left_subjects = _anchor_subjects(
            events,
            left_anchor,
            direction=-1,
            condition_tag_id=left_tag,
            relation_object_tag_ids=relation_tags,
        )
        right_subjects = _anchor_subjects(
            events,
            right_anchor,
            direction=1,
            condition_tag_id=right_tag,
            relation_object_tag_ids=relation_tags,
        )
        scored = []
        for candidate in range(left_anchor + 1, right_anchor + 1):
            candidate_score, evidence_ids = _candidate_boundary_score(
                events,
                left_anchor=left_anchor,
                right_anchor=right_anchor,
                boundary=candidate,
                old_boundary=scoring_old_boundary,
                left_tag=left_tag,
                right_tag=right_tag,
                left_subjects=left_subjects,
                right_subjects=right_subjects,
                settings=settings,
                relation_object_tag_ids=relation_tags,
            )
            scored.append((candidate_score, candidate, evidence_ids))
        scored.sort(key=lambda value: (value[0], value[1]), reverse=True)
        best_score, best_boundary, evidence_ids = scored[0]
        runner_up_score = scored[1][0] if len(scored) > 1 else best_score
        old_score = max(
            value[0]
            for value in scored
            if value[1] in local_boundaries
        )
        has_evidence = bool(evidence_ids)
        enough_gain = (
            multiple_boundaries
            or best_score - old_score >= settings.min_total_gain
        )
        enough_margin = (
            best_score - runner_up_score
            >= (
                settings.min_collapse_margin
                if multiple_boundaries
                else settings.min_runner_up_margin
            )
        )
        changed = bool(
            (
                multiple_boundaries
                or best_boundary != old_boundary
            )
            and has_evidence
            and enough_gain
            and enough_margin
        )
        if changed:
            boundaries.difference_update(local_boundaries)
            boundaries.add(best_boundary)
            reason = (
                "decisive_bidirectional_evidence_collapse"
                if multiple_boundaries
                else "decisive_bidirectional_evidence"
            )
        elif not has_evidence:
            reason = "abstain_no_discriminative_evidence"
        elif not enough_gain:
            reason = "abstain_insufficient_gain"
        elif not enough_margin:
            reason = "abstain_ambiguous_boundary"
        else:
            reason = "keep_baseline_best"
        decisions.append(
            EpisodeBoundaryRepairDecision(
                left_anchor_event_id=events[left_anchor].event_id,
                right_anchor_event_id=events[right_anchor].event_id,
                old_boundary=old_boundary,
                new_boundary=best_boundary if changed else old_boundary,
                changed=changed,
                reason=reason,
                old_score=old_score,
                new_score=best_score,
                runner_up_score=runner_up_score,
                evidence_event_ids=evidence_ids,
                old_boundaries=tuple(local_boundaries),
            )
        )

    ordered_boundaries = tuple(sorted(boundaries))
    return EpisodeBoundaryRepairResult(
        boundaries=ordered_boundaries,
        assignments=assignments_from_boundaries(
            events,
            ordered_boundaries,
        ),
        decisions=tuple(decisions),
    )


def _condition_prefixes(
    events: Sequence[EpisodeOptimizationEvent],
    settings: GlobalEpisodeDecoderConfig,
) -> tuple[tuple[str, ...], Mapping[str, tuple[float, ...]]]:
    tags = tuple(
        sorted(
            {
                tag_id
                for event in events
                for tag_id in (
                    *((event.condition_tag_id,) if event.condition_tag_id else ()),
                    *event.condition_scores.keys(),
                )
            }
        )
    )
    prefixes = {}
    for tag_id in tags:
        values = [0.0]
        total = 0.0
        for event in events:
            if event.condition_tag_id:
                contribution = (
                    settings.explicit_condition_reward
                    if event.condition_tag_id == tag_id
                    else -settings.explicit_condition_conflict_penalty
                )
            else:
                contribution = (
                    settings.condition_weight
                    * _relative_condition_support(event, tag_id)
                )
            total += contribution
            values.append(total)
        prefixes[tag_id] = tuple(values)
    return tags, MappingProxyType(prefixes)


def _object_prefixes(
    events: Sequence[EpisodeOptimizationEvent],
    relation_object_tag_ids: set[str],
) -> Mapping[str, tuple[int, ...]]:
    tags = sorted(
        {
            tag_id
            for event in events
            for tag_id in _subject_tags(event, relation_object_tag_ids)
        }
    )
    prefixes = {}
    for tag_id in tags:
        values = [0]
        total = 0
        for event in events:
            total += int(
                tag_id
                in _subject_tags(event, relation_object_tag_ids)
            )
            values.append(total)
        prefixes[tag_id] = tuple(values)
    return MappingProxyType(prefixes)


def _segment_score(
    start: int,
    end: int,
    *,
    condition_tags: Sequence[str],
    condition_prefixes: Mapping[str, tuple[float, ...]],
    object_prefixes: Mapping[str, tuple[int, ...]],
    settings: GlobalEpisodeDecoderConfig,
) -> tuple[float, str | None]:
    condition_tag_id = None
    condition_score = 0.0
    for tag_id in condition_tags:
        prefix = condition_prefixes[tag_id]
        score = prefix[end] - prefix[start]
        if condition_tag_id is None or score > condition_score:
            condition_tag_id = tag_id
            condition_score = score
    if condition_score <= 0.0:
        condition_score = 0.0
        condition_tag_id = None

    object_counts = [
        prefix[end] - prefix[start]
        for prefix in object_prefixes.values()
    ]
    same_pairs = sum(
        count * (count - 1) / 2.0 for count in object_counts
    )
    total_mentions = sum(object_counts)
    all_pairs = total_mentions * (total_mentions - 1) / 2.0
    conflicting_pairs = max(0.0, all_pairs - same_pairs)
    object_score = (
        settings.repeated_object_reward * same_pairs
        - settings.conflicting_object_penalty * conflicting_pairs
    )
    return condition_score + object_score, condition_tag_id


def _evidence_boundary_positions(
    events: Sequence[EpisodeOptimizationEvent],
) -> set[int]:
    anchors = [
        index
        for index, event in enumerate(events)
        if event.condition_tag_id
    ]
    allowed = set()
    for index in range(1, len(events)):
        left_tag = events[index - 1].condition_tag_id
        right_tag = events[index].condition_tag_id
        if left_tag and right_tag and left_tag != right_tag:
            allowed.add(index)
    for index, event in enumerate(events):
        if event.condition_tag_id or not event.condition_scores:
            continue
        left_candidates = [value for value in anchors if value < index]
        right_candidates = [value for value in anchors if value > index]
        if not left_candidates or not right_candidates:
            continue
        left = left_candidates[-1]
        right = right_candidates[0]
        if (
            events[left].condition_tag_id
            == events[right].condition_tag_id
        ):
            continue
        allowed.update(range(left + 1, right + 1))
    return allowed


def _segments_from_boundaries(
    events: Sequence[EpisodeOptimizationEvent],
    boundaries: Iterable[int],
    *,
    baseline_boundaries: set[int],
    condition_tags: Sequence[str],
    condition_prefixes: Mapping[str, tuple[float, ...]],
    object_prefixes: Mapping[str, tuple[int, ...]],
    settings: GlobalEpisodeDecoderConfig,
) -> tuple[tuple[GlobalEpisodeSegment, ...], float]:
    starts = (0, *tuple(sorted(boundaries)))
    ends = (*starts[1:], len(events))
    segments = []
    total_score = 0.0
    for start, end in zip(starts, ends, strict=True):
        content_score, condition_tag_id = _segment_score(
            start,
            end,
            condition_tags=condition_tags,
            condition_prefixes=condition_prefixes,
            object_prefixes=object_prefixes,
            settings=settings,
        )
        transition_score = 0.0
        if start > 0:
            transition_score -= settings.boundary_cost
            if start in baseline_boundaries:
                transition_score += settings.baseline_boundary_reward
        score = content_score + transition_score
        total_score += score
        segments.append(
            GlobalEpisodeSegment(
                start=start,
                end=end,
                condition_tag_id=condition_tag_id,
                score=score,
            )
        )
    return tuple(segments), total_score


def decode_episode_boundaries(
    events: Sequence[EpisodeOptimizationEvent],
    baseline_boundaries: Iterable[int],
    *,
    config: GlobalEpisodeDecoderConfig | None = None,
) -> GlobalEpisodeDecodeResult:
    """Decode all contiguous Episode boundaries with a semi-Markov DP."""

    settings = config or GlobalEpisodeDecoderConfig()
    if len({event.event_id for event in events}) != len(events):
        raise ValueError("event_id must be unique")
    if not events:
        return GlobalEpisodeDecodeResult(
            boundaries=(),
            assignments=MappingProxyType({}),
            score=0.0,
            segments=(),
        )
    baseline = set(baseline_boundaries)
    if any(value <= 0 or value >= len(events) for value in baseline):
        raise ValueError("boundaries must fall between events")

    condition_tags, condition_prefixes = _condition_prefixes(
        events,
        settings,
    )
    object_prefixes = _object_prefixes(
        events,
        set(settings.relation_object_tag_ids),
    )
    size = len(events)
    best_scores = [float("-inf")] * (size + 1)
    best_scores[0] = 0.0
    previous_starts = [-1] * (size + 1)
    segment_labels: list[str | None] = [None] * (size + 1)
    segment_scores = [0.0] * (size + 1)

    for end in range(1, size + 1):
        earliest = (
            max(0, end - settings.max_segment_events)
            if settings.max_segment_events is not None
            else 0
        )
        for start in range(earliest, end):
            content_score, condition_tag_id = _segment_score(
                start,
                end,
                condition_tags=condition_tags,
                condition_prefixes=condition_prefixes,
                object_prefixes=object_prefixes,
                settings=settings,
            )
            transition_score = 0.0
            if start > 0:
                transition_score -= settings.boundary_cost
                if start in baseline:
                    transition_score += settings.baseline_boundary_reward
            candidate = (
                best_scores[start]
                + content_score
                + transition_score
            )
            if candidate > best_scores[end] + 1e-12:
                best_scores[end] = candidate
                previous_starts[end] = start
                segment_labels[end] = condition_tag_id
                segment_scores[end] = (
                    content_score + transition_score
                )
            elif abs(candidate - best_scores[end]) <= 1e-12:
                current_start = previous_starts[end]
                candidate_uses_baseline = start in baseline
                current_uses_baseline = current_start in baseline
                if (
                    candidate_uses_baseline
                    and not current_uses_baseline
                ) or (
                    candidate_uses_baseline == current_uses_baseline
                    and start < current_start
                ):
                    previous_starts[end] = start
                    segment_labels[end] = condition_tag_id
                    segment_scores[end] = (
                        content_score + transition_score
                    )

    segments = []
    cursor = size
    while cursor > 0:
        start = previous_starts[cursor]
        if start < 0:
            raise RuntimeError("global Episode decoder has no valid path")
        segments.append(
            GlobalEpisodeSegment(
                start=start,
                end=cursor,
                condition_tag_id=segment_labels[cursor],
                score=segment_scores[cursor],
            )
        )
        cursor = start
    segments.reverse()
    decoded_boundaries = {
        segment.start for segment in segments[1:]
    }
    if settings.require_condition_score_for_boundary_change:
        allowed_changes = _evidence_boundary_positions(events)
        boundaries_set = {
            value
            for value in decoded_boundaries
            if value in baseline or value in allowed_changes
        }
        boundaries_set.update(
            value
            for value in baseline
            if value in decoded_boundaries
            or value not in allowed_changes
        )
    else:
        boundaries_set = decoded_boundaries
    boundaries = tuple(sorted(boundaries_set))
    final_segments, final_score = _segments_from_boundaries(
        events,
        boundaries,
        baseline_boundaries=baseline,
        condition_tags=condition_tags,
        condition_prefixes=condition_prefixes,
        object_prefixes=object_prefixes,
        settings=settings,
    )
    return GlobalEpisodeDecodeResult(
        boundaries=boundaries,
        assignments=assignments_from_boundaries(
            events,
            boundaries,
            episode_id_prefix=settings.episode_id_prefix,
        ),
        score=final_score,
        segments=final_segments,
    )


__all__ = [
    "EpisodeBoundaryRepairConfig",
    "EpisodeBoundaryRepairDecision",
    "EpisodeBoundaryRepairResult",
    "EpisodeOptimizationEvent",
    "GlobalEpisodeDecodeResult",
    "GlobalEpisodeDecoderConfig",
    "GlobalEpisodeSegment",
    "assignments_from_boundaries",
    "boundaries_from_assignments",
    "decode_episode_boundaries",
    "repair_episode_boundaries",
]
