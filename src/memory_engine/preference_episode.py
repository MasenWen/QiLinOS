from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Iterable

from .models import parse_time
from .preference_matching import PreferenceObservationMemory


def _stable_id(prefix: str, value: str) -> str:
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:24]
    return f"{prefix}_{digest}"


def _clip(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _instant(value: str) -> datetime | None:
    parsed = parse_time(value)
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _seconds_between(left: str, right: str) -> float | None:
    left_time = _instant(left)
    right_time = _instant(right)
    if left_time is None or right_time is None:
        return None
    return (right_time - left_time).total_seconds()


def _noisy_or(values: Iterable[float]) -> float:
    remaining = 1.0
    for value in values:
        remaining *= 1.0 - _clip(value)
    return _clip(1.0 - remaining)


def _polarity(value: float, minimum: float) -> str | None:
    if value >= minimum:
        return "support"
    if value <= -minimum:
        return "oppose"
    return None


def _source_unit(observation: PreferenceObservationMemory) -> str:
    return (
        observation.source_event_id
        or observation.observation_id
        or observation.memory_id
    )


@dataclass(frozen=True)
class PreferenceEpisodeConfig:
    max_gap_seconds: int = 15 * 60
    max_episode_seconds: int = 60 * 60
    max_intervening_observations: int = 2
    minimum_attitude_magnitude: float = 0.12
    single_strength_threshold: float = 0.82
    aggregate_strength_threshold: float = 0.82
    minimum_aggregate_support: int = 2

    def __post_init__(self) -> None:
        if self.max_gap_seconds < 0 or self.max_episode_seconds < 0:
            raise ValueError("episode time limits must be non-negative")
        if self.max_intervening_observations < 0:
            raise ValueError("max_intervening_observations must be non-negative")
        for name in (
            "minimum_attitude_magnitude",
            "single_strength_threshold",
            "aggregate_strength_threshold",
        ):
            value = float(getattr(self, name))
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be in [0, 1]")
        if self.minimum_aggregate_support < 2:
            raise ValueError("minimum_aggregate_support must be at least two")


@dataclass(frozen=True)
class PreferenceEpisode:
    episode_id: str
    user_id: str
    session_id: str
    condition_tag_id: str
    condition_name: str
    observations: tuple[PreferenceObservationMemory, ...]
    sequence_positions: tuple[int, ...]
    start_time: str
    end_time: str
    schema_version: str = "preference.episode.v1"

    @property
    def observation_ids(self) -> tuple[str, ...]:
        return tuple(item.observation_id for item in self.observations)

    def to_dict(self) -> dict[str, object]:
        return {
            "episode_id": self.episode_id,
            "user_id": self.user_id,
            "session_id": self.session_id,
            "condition_tag_id": self.condition_tag_id,
            "condition_name": self.condition_name,
            "observations": [asdict(item) for item in self.observations],
            "sequence_positions": list(self.sequence_positions),
            "start_time": self.start_time,
            "end_time": self.end_time,
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True)
class PreferenceEpisodeMemory:
    memory_id: str
    episode_id: str
    user_id: str
    session_id: str
    condition_tag_id: str
    condition_name: str
    object_tag_id: str
    object_name: str
    attitude_polarity: str
    attitude_value: float
    temporal_label: str
    memory_type: str
    promotion_seed: float
    explicit_long_term: bool
    strength: float
    strongest_observation_strength: float
    conflicting_strength: float
    support_count: int
    source_observation_ids: tuple[str, ...]
    source_event_ids: tuple[str, ...]
    source_memory_ids: tuple[str, ...]
    representative_observation_id: str
    promotion_reason: str
    schema_version: str = "preference.episode_memory.v1"

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class PreferenceEpisodeResult:
    episodes: tuple[PreferenceEpisode, ...]
    memories: tuple[PreferenceEpisodeMemory, ...]


@dataclass
class _EpisodeDraft:
    user_id: str
    session_id: str
    condition_tag_id: str
    observations: list[PreferenceObservationMemory]
    positions: list[int]


class PreferenceEpisodeEngine:
    """Group preference observations and promote coherent evidence clusters."""

    def __init__(
        self,
        config: PreferenceEpisodeConfig | None = None,
    ):
        self.config = config or PreferenceEpisodeConfig()

    def process(
        self,
        observations: Iterable[PreferenceObservationMemory],
    ) -> PreferenceEpisodeResult:
        episodes = self.group(observations)
        memories = tuple(
            memory
            for episode in episodes
            for memory in self.extract(episode)
        )
        return PreferenceEpisodeResult(
            episodes=episodes,
            memories=memories,
        )

    def group(
        self,
        observations: Iterable[PreferenceObservationMemory],
    ) -> tuple[PreferenceEpisode, ...]:
        drafts: list[_EpisodeDraft] = []
        active: dict[tuple[str, str, str], _EpisodeDraft] = {}
        scope_positions: dict[tuple[str, str], int] = {}
        scope_sources: dict[tuple[str, str], str] = {}
        seen_memory_ids: set[str] = set()

        for observation in observations:
            if observation.memory_id in seen_memory_ids:
                continue
            seen_memory_ids.add(observation.memory_id)

            scope = (observation.user_id, observation.session_id)
            source = _source_unit(observation)
            if scope_sources.get(scope) != source:
                scope_positions[scope] = scope_positions.get(scope, -1) + 1
                scope_sources[scope] = source
            position = scope_positions[scope]

            if not observation.condition_tag_id:
                drafts.append(
                    _EpisodeDraft(
                        user_id=observation.user_id,
                        session_id=observation.session_id,
                        condition_tag_id="",
                        observations=[observation],
                        positions=[position],
                    )
                )
                continue

            key = (*scope, observation.condition_tag_id)
            draft = active.get(key)
            if draft is None or not self._can_attach(
                draft,
                observation,
                position,
            ):
                draft = _EpisodeDraft(
                    user_id=observation.user_id,
                    session_id=observation.session_id,
                    condition_tag_id=observation.condition_tag_id,
                    observations=[],
                    positions=[],
                )
                drafts.append(draft)
                active[key] = draft
            draft.observations.append(observation)
            draft.positions.append(position)

        return tuple(self._finish(draft) for draft in drafts)

    def extract(
        self,
        episode: PreferenceEpisode,
    ) -> tuple[PreferenceEpisodeMemory, ...]:
        grouped: dict[
            tuple[str, str],
            list[tuple[PreferenceObservationMemory, float]],
        ] = {}
        for observation in episode.observations:
            polarity = _polarity(
                observation.attitude_value,
                self.config.minimum_attitude_magnitude,
            )
            if not observation.object_tag_id or polarity is None:
                continue
            key = (observation.object_tag_id, polarity)
            grouped.setdefault(key, []).append(
                (observation, self.observation_strength(observation))
            )

        supports = {
            key: self._independent_support(items)
            for key, items in grouped.items()
        }
        aggregate_scores = {
            key: _noisy_or(score for _, score in items)
            for key, items in supports.items()
        }

        memories: list[PreferenceEpisodeMemory] = []
        for (object_tag_id, polarity), items in supports.items():
            if not items:
                continue
            aggregate_strength = aggregate_scores[(object_tag_id, polarity)]
            strongest = max(score for _, score in items)
            strong_single = strongest >= self.config.single_strength_threshold
            strong_group = (
                len(items) >= self.config.minimum_aggregate_support
                and aggregate_strength
                >= self.config.aggregate_strength_threshold
            )
            if not strong_single and not strong_group:
                continue

            representative, _ = max(
                items,
                key=lambda item: (
                    item[1],
                    item[0].extraction_confidence,
                    item[0].memory_id,
                ),
            )
            temporal_label, memory_type = self._temporal_choice(items)
            total_weight = sum(score for _, score in items)
            attitude_value = sum(
                observation.attitude_value * score
                for observation, score in items
            ) / max(total_weight, 1e-9)
            opposite = "oppose" if polarity == "support" else "support"
            conflicting_strength = aggregate_scores.get(
                (object_tag_id, opposite),
                0.0,
            )
            source_observation_ids = tuple(
                dict.fromkeys(item.observation_id for item, _ in items)
            )
            source_event_ids = tuple(
                dict.fromkeys(
                    item.source_event_id
                    for item, _ in items
                    if item.source_event_id
                )
            )
            source_memory_ids = tuple(item.memory_id for item, _ in items)
            memory_id = _stable_id(
                "epmem",
                f"{episode.episode_id}|{object_tag_id}|{polarity}",
            )
            memories.append(
                PreferenceEpisodeMemory(
                    memory_id=memory_id,
                    episode_id=episode.episode_id,
                    user_id=episode.user_id,
                    session_id=episode.session_id,
                    condition_tag_id=episode.condition_tag_id,
                    condition_name=episode.condition_name,
                    object_tag_id=object_tag_id,
                    object_name=representative.object_name,
                    attitude_polarity=polarity,
                    attitude_value=round(attitude_value, 6),
                    temporal_label=temporal_label,
                    memory_type=memory_type,
                    promotion_seed=(
                        0.0 if memory_type == "short_term" else 1.0
                    ),
                    explicit_long_term=memory_type == "long_term",
                    strength=round(aggregate_strength, 6),
                    strongest_observation_strength=round(strongest, 6),
                    conflicting_strength=round(conflicting_strength, 6),
                    support_count=len(items),
                    source_observation_ids=source_observation_ids,
                    source_event_ids=source_event_ids,
                    source_memory_ids=source_memory_ids,
                    representative_observation_id=(
                        representative.observation_id
                    ),
                    promotion_reason=(
                        "strong_single"
                        if strong_single
                        else "coherent_aggregate"
                    ),
                )
            )
        return tuple(memories)

    @staticmethod
    def observation_strength(
        observation: PreferenceObservationMemory,
    ) -> float:
        return _clip(
            0.45 * _clip(observation.extraction_confidence)
            + 0.30 * _clip(observation.attitude_confidence)
            + 0.25 * _clip(abs(observation.attitude_value))
        )

    def _can_attach(
        self,
        draft: _EpisodeDraft,
        observation: PreferenceObservationMemory,
        position: int,
    ) -> bool:
        last = draft.observations[-1]
        if (
            _source_unit(last) == _source_unit(observation)
            and position == draft.positions[-1]
        ):
            return True

        intervening = position - draft.positions[-1] - 1
        if intervening > self.config.max_intervening_observations:
            return False

        gap = _seconds_between(last.observed_time, observation.observed_time)
        duration = _seconds_between(
            draft.observations[0].observed_time,
            observation.observed_time,
        )
        if gap is None or duration is None:
            return False
        return (
            0.0 <= gap <= self.config.max_gap_seconds
            and 0.0 <= duration <= self.config.max_episode_seconds
        )

    @staticmethod
    def _finish(draft: _EpisodeDraft) -> PreferenceEpisode:
        first = draft.observations[0]
        last = draft.observations[-1]
        condition_name = next(
            (
                item.condition_name
                for item in draft.observations
                if item.condition_name
            ),
            "",
        )
        return PreferenceEpisode(
            episode_id=_stable_id(
                "prefep",
                (
                    f"{draft.user_id}|{draft.session_id}|"
                    f"{draft.condition_tag_id}|{first.memory_id}"
                ),
            ),
            user_id=draft.user_id,
            session_id=draft.session_id,
            condition_tag_id=draft.condition_tag_id,
            condition_name=condition_name,
            observations=tuple(draft.observations),
            sequence_positions=tuple(draft.positions),
            start_time=first.observed_time,
            end_time=last.observed_time,
        )

    @staticmethod
    def _independent_support(
        items: list[tuple[PreferenceObservationMemory, float]],
    ) -> list[tuple[PreferenceObservationMemory, float]]:
        strongest_by_source: dict[
            str,
            tuple[PreferenceObservationMemory, float],
        ] = {}
        source_order: list[str] = []
        for item in items:
            source = _source_unit(item[0])
            if source not in strongest_by_source:
                source_order.append(source)
                strongest_by_source[source] = item
                continue
            if item[1] > strongest_by_source[source][1]:
                strongest_by_source[source] = item
        return [strongest_by_source[source] for source in source_order]

    @staticmethod
    def _temporal_choice(
        items: list[tuple[PreferenceObservationMemory, float]],
    ) -> tuple[str, str]:
        by_label: dict[str, list[float]] = {
            "temporal_short": [],
            "temporal_medium": [],
            "temporal_long": [],
        }
        for observation, score in items:
            label = observation.temporal_label.casefold()
            if observation.explicit_long_term or "long" in label:
                bucket = "temporal_long"
            elif "medium" in label or "mid" in label:
                bucket = "temporal_medium"
            elif "short" in label:
                bucket = "temporal_short"
            elif observation.promotion_seed >= 1.0:
                bucket = "temporal_medium"
            else:
                bucket = "temporal_short"
            by_label[bucket].append(score)

        support = {
            label: _noisy_or(values)
            for label, values in by_label.items()
        }
        rank = {
            "temporal_short": 0,
            "temporal_medium": 1,
            "temporal_long": 2,
        }
        selected = max(
            support,
            key=lambda label: (support[label], -rank[label]),
        )
        memory_type = {
            "temporal_short": "short_term",
            "temporal_medium": "mid_term",
            "temporal_long": "long_term",
        }[selected]
        return selected, memory_type
