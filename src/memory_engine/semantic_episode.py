from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Iterable, Mapping


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _clean_tags(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(value for value in values if value))


@dataclass(frozen=True)
class SemanticEpisodeEvent:
    """Source-neutral condition/object evidence for one ordered event."""

    event_id: str
    observed_time: str
    condition_tag_ids: tuple[str, ...] = ()
    object_tag_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "condition_tag_ids",
            _clean_tags(self.condition_tag_ids),
        )
        object.__setattr__(
            self,
            "object_tag_ids",
            _clean_tags(self.object_tag_ids),
        )


@dataclass(frozen=True)
class SemanticEpisodeConfig:
    time_fallback_seconds: float | None = None
    retroactive_unknown_condition: bool = False
    object_conflict_confirmation: int = 1
    object_bridge_tag_ids: tuple[str, ...] = ()
    episode_id_prefix: str = "semantic-episode"

    def __post_init__(self) -> None:
        if (
            self.time_fallback_seconds is not None
            and self.time_fallback_seconds < 0.0
        ):
            raise ValueError("time_fallback_seconds must be non-negative")
        if self.object_conflict_confirmation not in (1, 2):
            raise ValueError(
                "object_conflict_confirmation must be one or two"
            )
        if not self.episode_id_prefix:
            raise ValueError("episode_id_prefix must not be empty")
        object.__setattr__(
            self,
            "object_bridge_tag_ids",
            _clean_tags(self.object_bridge_tag_ids),
        )


@dataclass(frozen=True)
class SemanticEpisodeDecision:
    event_id: str
    predicted_episode_id: str
    split: bool
    reason: str
    elapsed_seconds: float
    current_conditions: tuple[str, ...]
    current_objects: tuple[str, ...]
    active_conditions: tuple[str, ...]
    active_objects: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class SemanticEpisodeGrouping:
    assignments: Mapping[str, str]
    decisions: tuple[SemanticEpisodeDecision, ...]


@dataclass
class _Draft:
    events: list[SemanticEpisodeEvent]

    @property
    def conditions(self) -> set[str]:
        return {
            tag
            for event in self.events
            for tag in event.condition_tag_ids
        }

    @property
    def objects(self) -> set[str]:
        return {
            tag
            for event in self.events
            for tag in event.object_tag_ids
        }


def group_semantic_episode_events(
    events: Iterable[SemanticEpisodeEvent],
    *,
    config: SemanticEpisodeConfig | None = None,
) -> SemanticEpisodeGrouping:
    """Group ordered events using conservative condition/object boundaries."""

    settings = config or SemanticEpisodeConfig()
    ordered = tuple(events)
    if len({event.event_id for event in ordered}) != len(ordered):
        raise ValueError("event_id must be unique")
    if not ordered:
        return SemanticEpisodeGrouping(assignments={}, decisions=())

    drafts: list[_Draft] = []
    reasons: dict[str, str] = {}
    splits: dict[str, bool] = {}
    elapsed_by_id: dict[str, float] = {}
    pending_object_event_id: str | None = None
    pending_object_tags: set[str] = set()
    previous: SemanticEpisodeEvent | None = None

    for event in ordered:
        elapsed = (
            (
                _parse_time(event.observed_time)
                - _parse_time(previous.observed_time)
            ).total_seconds()
            if previous is not None
            else 0.0
        )
        elapsed_by_id[event.event_id] = elapsed
        current_conditions = set(event.condition_tag_ids)
        current_objects = set(event.object_tag_ids)

        if not drafts:
            drafts.append(_Draft(events=[event]))
            reasons[event.event_id] = "initial"
            splits[event.event_id] = False
            previous = event
            continue

        active = drafts[-1]
        active_conditions = active.conditions
        active_objects = active.objects
        condition_same = bool(active_conditions & current_conditions)
        condition_conflict = bool(
            active_conditions
            and current_conditions
            and not condition_same
        )

        if condition_conflict:
            moved = None
            if (
                settings.retroactive_unknown_condition
                and len(active.events) > 1
                and not active.events[-1].condition_tag_ids
                and active.events[-1].object_tag_ids
                and current_objects
                and (
                    set(active.events[-1].object_tag_ids)
                    & current_objects
                )
            ):
                moved = active.events.pop()
            if moved is None:
                drafts.append(_Draft(events=[event]))
                reasons[event.event_id] = "condition_conflict"
                splits[event.event_id] = True
            else:
                drafts.append(_Draft(events=[moved, event]))
                reasons[moved.event_id] = (
                    "condition_unknown_reassigned"
                )
                splits[moved.event_id] = True
                reasons[event.event_id] = (
                    "condition_conflict_confirmed_pending"
                )
                splits[event.event_id] = False
            pending_object_event_id = None
            pending_object_tags.clear()
            previous = event
            continue

        if condition_same:
            active.events.append(event)
            reasons[event.event_id] = "condition_overlap"
            splits[event.event_id] = False
            pending_object_event_id = None
            pending_object_tags.clear()
            previous = event
            continue

        confirms_pending_object = bool(
            settings.object_conflict_confirmation == 2
            and previous is not None
            and pending_object_event_id == previous.event_id
            and current_objects
            and pending_object_tags & current_objects
        )
        if confirms_pending_object:
            moved = active.events.pop()
            drafts.append(_Draft(events=[moved, event]))
            reasons[moved.event_id] = "object_conflict_confirmed"
            splits[moved.event_id] = True
            reasons[event.event_id] = "object_conflict_overlap"
            splits[event.event_id] = False
            pending_object_event_id = None
            pending_object_tags.clear()
            previous = event
            continue

        if pending_object_event_id is not None:
            stable_events = active.events[:-1]
            stable_objects = {
                tag
                for stable_event in stable_events
                for tag in stable_event.object_tag_ids
            }
            returns_to_stable_object = bool(
                stable_objects & current_objects
            )
            if returns_to_stable_object:
                active.events.append(event)
                reasons[event.event_id] = "object_return_to_active"
                splits[event.event_id] = False
                pending_object_event_id = None
                pending_object_tags.clear()
                previous = event
                continue

            moved = active.events.pop()
            drafts.append(_Draft(events=[moved]))
            reasons[moved.event_id] = (
                "object_conflict_unresolved_split"
            )
            splits[moved.event_id] = True
            active = drafts[-1]

        pending_object_event_id = None
        pending_object_tags.clear()
        active_objects = active.objects
        object_same = bool(active_objects & current_objects)
        object_bridge_compatible = bool(
            active_objects
            and current_objects
            and (
                (active_objects | current_objects)
                & set(settings.object_bridge_tag_ids)
            )
        )
        object_conflict = bool(
            active_objects
            and current_objects
            and not object_same
            and not object_bridge_compatible
        )

        if object_conflict:
            if settings.object_conflict_confirmation == 1:
                drafts.append(_Draft(events=[event]))
                reasons[event.event_id] = "object_conflict"
                splits[event.event_id] = True
            else:
                active.events.append(event)
                reasons[event.event_id] = "object_conflict_pending"
                splits[event.event_id] = False
                pending_object_event_id = event.event_id
                pending_object_tags = set(current_objects)
        elif object_same:
            active.events.append(event)
            reasons[event.event_id] = "object_overlap"
            splits[event.event_id] = False
        elif object_bridge_compatible:
            active.events.append(event)
            reasons[event.event_id] = "object_bridge_compatible"
            splits[event.event_id] = False
        elif (
            settings.time_fallback_seconds is not None
            and elapsed > settings.time_fallback_seconds
        ):
            drafts.append(_Draft(events=[event]))
            reasons[event.event_id] = (
                "semantic_unknown_time_fallback"
            )
            splits[event.event_id] = True
        else:
            active.events.append(event)
            reasons[event.event_id] = "semantic_unknown_keep"
            splits[event.event_id] = False
        previous = event

    if pending_object_event_id is not None:
        active = drafts[-1]
        if (
            len(active.events) > 1
            and active.events[-1].event_id
            == pending_object_event_id
        ):
            moved = active.events.pop()
            drafts.append(_Draft(events=[moved]))
            reasons[moved.event_id] = "object_conflict_end_split"
            splits[moved.event_id] = True

    assignments: dict[str, str] = {}
    decisions_by_id: dict[str, SemanticEpisodeDecision] = {}
    for index, draft in enumerate(drafts, 1):
        episode_id = f"{settings.episode_id_prefix}-{index:04d}"
        conditions = tuple(sorted(draft.conditions))
        objects = tuple(sorted(draft.objects))
        for event in draft.events:
            assignments[event.event_id] = episode_id
            decisions_by_id[event.event_id] = SemanticEpisodeDecision(
                event_id=event.event_id,
                predicted_episode_id=episode_id,
                split=splits[event.event_id],
                reason=reasons[event.event_id],
                elapsed_seconds=elapsed_by_id[event.event_id],
                current_conditions=event.condition_tag_ids,
                current_objects=event.object_tag_ids,
                active_conditions=conditions,
                active_objects=objects,
            )

    decisions = tuple(decisions_by_id[event.event_id] for event in ordered)
    return SemanticEpisodeGrouping(
        assignments=assignments,
        decisions=decisions,
    )


__all__ = [
    "SemanticEpisodeConfig",
    "SemanticEpisodeDecision",
    "SemanticEpisodeEvent",
    "SemanticEpisodeGrouping",
    "group_semantic_episode_events",
]
