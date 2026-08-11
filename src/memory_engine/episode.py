from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from .models import Episode, Observation, parse_time
from .store import MemoryEngineStore


STRONG_END_ACTIONS = frozenset(
    {"complete", "submit", "send", "save_final", "task_complete", "file_submitted", "email_sent"}
)

EPISODE_START_ROLES = frozenset(
    {
        "preference_statement",
        "habit_statement",
        "safety_constraint",
        "previous_preference_reference",
        "workflow_definition",
        "historical_case_reference",
        "template_definition",
        "association_rule",
        "standing_preference",
    }
)

EPISODE_CONTINUATION_ROLES = frozenset(
    {
        "clarification",
        "scope_extension",
        "preference_update",
        "cross_scene_extension",
        "workflow_constraint",
        "reuse_boundary",
        "template_constraint",
        "retrieval_constraint",
        "one_time_exception",
        "conflict_resolution",
    }
)


def _stable_id(prefix: str, value: str) -> str:
    return f"{prefix}_{hashlib.sha256(value.encode('utf-8')).hexdigest()[:24]}"


def _seconds_between(first: str, second: str) -> float:
    left = parse_time(first)
    right = parse_time(second)
    if left is None or right is None:
        return 0.0
    if left.tzinfo is None:
        left = left.replace(tzinfo=timezone.utc)
    if right.tzinfo is None:
        right = right.replace(tzinfo=timezone.utc)
    return (right - left).total_seconds()


def _tokens(value: str) -> set[str]:
    normalized = value.strip().lower()
    words = set(re.findall(r"[\w]+", normalized))
    if len(words) == 1 and len(normalized) > 3:
        words |= {normalized[index : index + 2] for index in range(len(normalized) - 1)}
    return words


def _similarity(left: str, right: str) -> float:
    if not left or not right:
        return 0.0
    left_tokens = _tokens(left)
    right_tokens = _tokens(right)
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def _task_instance_ids(observation: Observation) -> set[str]:
    values = observation.context.get("task_instance_ids")
    if values is None:
        values = observation.context.get("task_instance_id")
    if values is None:
        return set()
    if isinstance(values, str):
        return {values} if values else set()
    if isinstance(values, (list, tuple, set)):
        return {str(value) for value in values if str(value)}
    return {str(values)}


def _is_complete(observation: Observation) -> bool:
    if observation.action in STRONG_END_ACTIONS:
        return True
    return bool(observation.result.get("task_complete") or observation.state.get("task_complete"))


def _context_text(observation: Observation, name: str) -> str:
    return str(observation.context.get(name) or "").strip()


def _context_values(observation: Observation, name: str) -> set[str]:
    value = observation.context.get(name)
    if isinstance(value, str):
        return {value} if value else set()
    if isinstance(value, (list, tuple, set)):
        return {str(item) for item in value if str(item)}
    return {str(value)} if value not in (None, "") else set()


def _application_ids(observation: Observation) -> set[str]:
    values = _context_values(observation, "referenced_app_ids")
    if observation.app:
        values.add(observation.app)
    return values


def _valid_relation_marker(value: str) -> bool:
    return bool(value and not value.isdecimal() and value.casefold() != "none")


def _explicitly_related(
    previous: Observation,
    current: Observation,
) -> bool:
    supersedes = _context_text(current, "supersedes_event_id")
    if supersedes and supersedes == previous.source_event_id:
        return True
    previous_group = _context_text(previous, "conflict_group_id")
    current_group = _context_text(current, "conflict_group_id")
    return bool(
        previous_group == current_group
        and _valid_relation_marker(current_group)
    )


def _same_structured_context(
    previous: Observation,
    current: Observation,
) -> bool:
    compared = 0
    for name in (
        "scenario_id",
        "competition_ability_id",
        "memory_signal_type",
    ):
        left = _context_text(previous, name)
        right = _context_text(current, name)
        if not left or not right:
            continue
        compared += 1
        if left != right:
            return False
    return compared > 0


def _structured_context_changed(
    previous: Observation,
    current: Observation,
) -> bool:
    changes = 0
    compared = 0
    for name in (
        "scenario_id",
        "competition_ability_id",
        "memory_signal_type",
    ):
        left = _context_text(previous, name)
        right = _context_text(current, name)
        if not left or not right:
            continue
        compared += 1
        changes += left != right
    return compared >= 2 and changes >= 1


@dataclass(frozen=True)
class BoundaryDecision:
    split: bool
    confidence: float
    reason: str
    score: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "split": self.split,
            "confidence": self.confidence,
            "reason": self.reason,
            "score": self.score,
        }


class EpisodeManager:
    """Deterministic initial segmentation with reversible split/merge operations."""

    def __init__(
        self,
        store: MemoryEngineStore,
        *,
        idle_gap_minutes: int = 10,
        max_episode_minutes: int = 60,
        task_similarity_threshold: float = 0.7,
    ):
        self.store = store
        self.idle_gap_seconds = idle_gap_minutes * 60
        self.max_episode_seconds = max_episode_minutes * 60
        self.task_similarity_threshold = task_similarity_threshold

    def attach(self, observation: Observation) -> tuple[Episode, BoundaryDecision]:
        current = self.store.latest_open_episode(observation.user_id, observation.session_id)
        if current is None:
            episode = self._new_episode(observation)
            decision = BoundaryDecision(False, 1.0, "initial_episode", 0.0)
        else:
            previous = self.store.get_observation(current.observation_ids[-1])
            decision = self.decide_boundary(current, previous, observation)
            if decision.split:
                current.status = "closed"
                current.end_time = previous.event_time if previous else observation.event_time
                current.boundary_confidence = decision.confidence
                current.boundary_reason = decision.reason
                self.store.put_episode(current)
                episode = self._new_episode(observation)
            else:
                episode = current
                self._append(episode, observation)

        if _is_complete(observation):
            episode.status = "closed"
            episode.end_time = observation.event_time
            episode.boundary_confidence = 1.0
            episode.boundary_reason = "strong_end"
        self.store.put_episode(episode)
        return episode, decision

    def decide_boundary(
        self,
        episode: Episode,
        previous: Observation | None,
        current: Observation,
    ) -> BoundaryDecision:
        if previous is None:
            return BoundaryDecision(False, 0.2, "missing_previous_observation", 0.0)

        shared_artifact = bool(set(episode.artifact_refs) & set(current.artifact_refs))
        shared_entity = bool(set(episode.entity_refs) & set(current.entity_refs))
        current_instances = _task_instance_ids(current)
        shared_instance = bool(set(episode.task_instance_ids) & current_instances)
        task_similarity = _similarity(episode.task_hint, current.task_hint)
        same_task = bool(
            episode.task_hint
            and current.task_hint
            and task_similarity >= self.task_similarity_threshold
        )

        if (
            _explicitly_related(previous, current)
            or shared_instance
            or shared_artifact
            or shared_entity
            or same_task
        ):
            return BoundaryDecision(False, 0.95, "strong_relation", 0.0)

        current_role = _context_text(current, "utterance_role")
        if (
            current_role in EPISODE_CONTINUATION_ROLES
            and _same_structured_context(previous, current)
        ):
            return BoundaryDecision(
                False,
                0.95,
                "structured_continuation",
                0.0,
            )
        if current_role in EPISODE_START_ROLES:
            return BoundaryDecision(
                True,
                0.98,
                "structured_episode_start",
                1.0,
            )
        if _structured_context_changed(previous, current):
            return BoundaryDecision(
                True,
                0.90,
                "structured_context_switch",
                0.85,
            )

        elapsed = _seconds_between(previous.event_time, current.event_time)
        duration = _seconds_between(episode.start_time, current.event_time)
        if duration > self.max_episode_seconds:
            return BoundaryDecision(True, 0.95, "max_episode_duration", 1.0)

        goal_changed = bool(
            episode.goal_hint
            and current.goal_hint
            and episode.goal_hint != current.goal_hint
            and _similarity(episode.goal_hint, current.goal_hint) < self.task_similarity_threshold
        )
        artifact_disjoint = bool(episode.artifact_refs and current.artifact_refs and not shared_artifact)
        entity_disjoint = bool(episode.entity_refs and current.entity_refs and not shared_entity)
        previous_apps = _application_ids(previous)
        current_apps = _application_ids(current)
        app_disjoint = bool(
            previous_apps
            and current_apps
            and not previous_apps & current_apps
        )
        if goal_changed and artifact_disjoint and entity_disjoint:
            return BoundaryDecision(True, 0.95, "strong_goal_artifact_entity_switch", 0.95)

        score = 0.0
        if goal_changed:
            score += 0.30
        if artifact_disjoint:
            score += 0.20
        if entity_disjoint:
            score += 0.15
        if app_disjoint and elapsed > 0.5 * self.idle_gap_seconds:
            score += 0.10
        if _is_complete(previous):
            score += 0.25
        if previous.state and current.state and previous.state != current.state:
            score += 0.10
        if _is_complete(previous) and (goal_changed or artifact_disjoint):
            return BoundaryDecision(True, 0.95, "completed_then_new_task", max(score, 0.8))
        if goal_changed and artifact_disjoint:
            return BoundaryDecision(True, 0.90, "goal_and_artifact_switch", max(score, 0.75))
        if elapsed > self.idle_gap_seconds:
            return BoundaryDecision(True, 0.75, "idle_gap", max(score, 0.6))
        if score >= 0.70:
            return BoundaryDecision(True, 0.70, "split_score", score)

        # An application switch alone is context, not a task boundary.
        reason = "app_switch_only" if previous.app and current.app and previous.app != current.app else "continue"
        return BoundaryDecision(False, 0.65 if reason == "continue" else 0.85, reason, score)

    def split_score(self, left: Observation, right: Observation) -> float:
        goal_change = bool(
            left.goal_hint and right.goal_hint and _similarity(left.goal_hint, right.goal_hint) < 0.7
        )
        artifact_disjoint = bool(
            left.artifact_refs
            and right.artifact_refs
            and not set(left.artifact_refs) & set(right.artifact_refs)
        )
        entity_disjoint = bool(
            left.entity_refs
            and right.entity_refs
            and not set(left.entity_refs) & set(right.entity_refs)
        )
        state_discontinuity = bool(left.state and right.state and left.state != right.state)
        return min(
            1.0,
            0.30 * goal_change
            + 0.20 * artifact_disjoint
            + 0.15 * entity_disjoint
            + 0.25 * _is_complete(left)
            + 0.10 * state_discontinuity,
        )

    def merge_score(self, left: Episode, right: Episode) -> float:
        same_task = bool(left.task_hint and right.task_hint and _similarity(left.task_hint, right.task_hint) >= 0.7)
        artifact_overlap = bool(set(left.artifact_refs) & set(right.artifact_refs))
        entity_overlap = bool(set(left.entity_refs) & set(right.entity_refs))
        time_close = _seconds_between(left.end_time or left.start_time, right.start_time) <= self.idle_gap_seconds
        left_state = dict(left.state)
        right_state = dict(right.state)
        state_continuity = bool(left_state and right_state and left_state == right_state)
        unfinished_then_continue = left.status != "closed" and (same_task or artifact_overlap)
        return min(
            1.0,
            0.25 * same_task
            + 0.25 * artifact_overlap
            + 0.15 * entity_overlap
            + 0.10 * time_close
            + 0.20 * state_continuity
            + 0.05 * unfinished_then_continue,
        )

    def split_episode(self, episode_id: str, at_observation_id: str) -> tuple[Episode, Episode]:
        episode = self.store.get_episode(episode_id)
        if episode is None:
            raise KeyError(f"episode_not_found:{episode_id}")
        index = episode.observation_ids.index(at_observation_id)
        if index <= 0:
            raise ValueError("split_requires_observations_on_both_sides")
        left_ids = episode.observation_ids[:index]
        right_ids = episode.observation_ids[index:]
        left_last = self.store.get_observation(left_ids[-1])
        right_first = self.store.get_observation(right_ids[0])
        if left_last is None or right_first is None:
            raise ValueError("episode_lineage_incomplete")

        episode.observation_ids = left_ids
        episode.end_time = left_last.event_time
        episode.status = "closed"
        episode.boundary_reason = "repair_split"
        episode.boundary_confidence = self.split_score(left_last, right_first)
        right = Episode(
            episode_id=_stable_id("episode", right_first.observation_id),
            user_id=episode.user_id,
            session_id=episode.session_id,
            observation_ids=right_ids,
            start_time=right_first.event_time,
            end_time=None,
            status="open",
            boundary_reason="repair_split",
            boundary_confidence=episode.boundary_confidence,
        )
        self._rebuild_summary(episode)
        self._rebuild_summary(right)
        self.store.put_episode(episode)
        self.store.put_episode(right)
        return episode, right

    def merge_episodes(self, left_id: str, right_id: str, *, threshold: float = 0.60) -> Episode:
        left = self.store.get_episode(left_id)
        right = self.store.get_episode(right_id)
        if left is None or right is None:
            raise KeyError("episode_not_found")
        if left.user_id != right.user_id or left.session_id != right.session_id:
            raise ValueError("merge_scope_mismatch")
        if _seconds_between(left.start_time, right.start_time) < 0:
            raise ValueError("merge_time_direction")
        score = self.merge_score(left, right)
        if score < threshold:
            raise ValueError(f"merge_score_below_threshold:{score:.3f}")
        left.observation_ids.extend(
            observation_id
            for observation_id in right.observation_ids
            if observation_id not in left.observation_ids
        )
        left.end_time = right.end_time
        left.status = right.status
        left.boundary_reason = "repair_merge"
        left.boundary_confidence = score
        self._rebuild_summary(left)
        self.store.put_episode(left)
        right.status = "merged"
        right.state = {**dict(right.state), "merged_into": left.episode_id}
        self.store.put_episode(right)
        return left

    def _new_episode(self, observation: Observation) -> Episode:
        episode = Episode(
            episode_id=_stable_id("episode", observation.observation_id),
            user_id=observation.user_id,
            session_id=observation.session_id,
            observation_ids=[],
            start_time=observation.event_time,
        )
        self._append(episode, observation)
        return episode

    @staticmethod
    def _append(episode: Episode, observation: Observation) -> None:
        if observation.observation_id not in episode.observation_ids:
            episode.observation_ids.append(observation.observation_id)
        episode.task_hint = observation.task_hint or episode.task_hint
        episode.goal_hint = observation.goal_hint or episode.goal_hint
        episode.apps = sorted(set(episode.apps) | ({observation.app} if observation.app else set()))
        episode.artifact_refs = sorted(set(episode.artifact_refs) | set(observation.artifact_refs))
        episode.entity_refs = sorted(set(episode.entity_refs) | set(observation.entity_refs))
        episode.task_instance_ids = sorted(set(episode.task_instance_ids) | _task_instance_ids(observation))
        episode.state = dict(observation.state or episode.state)

    def _rebuild_summary(self, episode: Episode) -> None:
        observations = [
            self.store.get_observation(observation_id)
            for observation_id in episode.observation_ids
        ]
        observations = [observation for observation in observations if observation is not None]
        episode.task_hint = ""
        episode.goal_hint = ""
        episode.apps = []
        episode.artifact_refs = []
        episode.entity_refs = []
        episode.task_instance_ids = []
        episode.state = {}
        for observation in observations:
            self._append(episode, observation)
        if observations:
            episode.start_time = observations[0].event_time
            if episode.status == "closed":
                episode.end_time = observations[-1].event_time
