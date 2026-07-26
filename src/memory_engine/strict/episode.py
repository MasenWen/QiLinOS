from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import datetime
from typing import Any, Iterable, Mapping
from uuid import NAMESPACE_URL, uuid5

from .config import EpisodeConfig
from .contracts import (
    BoundaryDecision,
    Completion,
    ExecutionFragment,
    RepairedExecution,
    StrictObservation,
)


NOISE_ACTIONS = {
    "click",
    "clicked",
    "double_click",
    "mouse_move",
    "mousemove",
    "window_focus",
    "window_blur",
    "scroll",
}


class TimeTaskArtifactSTM:
    module_id = "stm.time_task_artifact_rule.v1"

    def provisional_episode_id(
        self,
        observation: StrictObservation,
    ) -> str:
        return "pep-" + uuid5(
            NAMESPACE_URL,
            f"strict-stm:{observation.user_id}:{observation.session_id}",
        ).hex


class SplitMergeEpisodeRepair:
    module_id = "episode_repair.split_merge_rule.v1"

    def __init__(self, config: EpisodeConfig):
        self.config = config

    def repair(
        self,
        observations: Iterable[StrictObservation],
        provisional_episode_ids: Mapping[str, str],
    ) -> tuple[RepairedExecution, list[ExecutionFragment], str]:
        ordered = sorted(
            observations,
            key=lambda item: (
                datetime.fromisoformat(item.event_time),
                item.sequence_no is None,
                item.sequence_no if item.sequence_no is not None else 0,
                item.observation_id,
            ),
        )
        if not ordered:
            raise ValueError("cannot repair an empty observation sequence")
        user_ids = {item.user_id for item in ordered}
        session_ids = {item.session_id for item in ordered}
        if len(user_ids) != 1 or len(session_ids) != 1:
            raise ValueError("one repaired execution must belong to one user/session")

        trace: list[dict[str, Any]] = []
        groups: list[tuple[list[StrictObservation], BoundaryDecision | None]] = [
            ([ordered[0]], None)
        ]
        for left, right in zip(ordered, ordered[1:]):
            decision = self.split_decision(left, right)
            trace.append(
                {
                    "operation": "split_decision",
                    "left_observation_id": left.observation_id,
                    "right_observation_id": right.observation_id,
                    "decision": decision.to_dict(),
                }
            )
            if decision.should_split:
                groups.append(([right], decision))
            else:
                groups[-1][0].append(right)

        fragments = [
            self._fragment(items, boundary, provisional_episode_ids)
            for items, boundary in groups
        ]
        fragments = self._merge_pass(fragments, trace)
        observation_ids = tuple(
            observation_id
            for fragment in fragments
            for observation_id in fragment.observation_ids
        )
        input_fingerprint = hashlib.sha256(
            "|".join(item.content_hash for item in ordered).encode("utf-8")
        ).hexdigest()
        execution_id = "rex-" + uuid5(
            NAMESPACE_URL,
            (
                f"strict-execution:{ordered[0].user_id}:{ordered[0].session_id}:"
                f"{input_fingerprint}"
            ),
        ).hex
        path_valid, path_reasons = _validate_path(ordered, fragments)
        trace.append(
            {
                "operation": "fragment_graph_validation",
                "valid": path_valid,
                "reason_codes": path_reasons,
            }
        )
        execution = RepairedExecution(
            execution_id=execution_id,
            user_id=ordered[0].user_id,
            session_id=ordered[0].session_id,
            fragment_ids=tuple(item.fragment_id for item in fragments),
            observation_ids=observation_ids,
            start_time=ordered[0].event_time,
            end_time=ordered[-1].event_time,
            path_valid=path_valid,
            repair_trace=tuple(trace),
        )
        return execution, fragments, input_fingerprint

    def split_decision(
        self,
        left: StrictObservation,
        right: StrictObservation,
    ) -> BoundaryDecision:
        features = {
            "goal_change": _different_nonempty(left.goal_hint, right.goal_hint),
            "artifact_disjoint": _disjoint_nonempty(
                left.artifact_refs,
                right.artifact_refs,
            ),
            "entity_disjoint": _disjoint_nonempty(
                left.entity_refs,
                right.entity_refs,
            ),
            "task_complete_then_new_start": float(
                left.completion is Completion.COMPLETED
                and _new_task_started(left, right)
            ),
            "state_discontinuity": _state_discontinuity(left, right),
        }
        weighted_score = sum(
            features[name] * float(weight)
            for name, weight in self.config.split_weights.items()
        )
        elapsed = _seconds(left.event_time, right.event_time)
        idle_split = (
            elapsed > self.config.idle_gap_seconds
            and not _related_by_artifact_or_entity(left, right)
        )
        complete_new = bool(features["task_complete_then_new_start"])
        goal_artifact = bool(
            features["goal_change"] and features["artifact_disjoint"]
        )
        forced = complete_new or goal_artifact
        should_split = (
            forced
            or idle_split
            or weighted_score >= self.config.split_threshold
        )
        reasons = [
            name for name, value in features.items() if value > 0.0
        ]
        if idle_split:
            reasons.append("idle_gap")
        if not reasons:
            reasons.append("continuous_execution")
        return BoundaryDecision(
            should_split=should_split,
            score=round(weighted_score, 6),
            reason_codes=tuple(reasons),
            features=features,
            forced=forced,
        )

    def merge_decision(
        self,
        left: ExecutionFragment,
        right: ExecutionFragment,
    ) -> tuple[bool, dict[str, Any]]:
        gap = _seconds(left.end_time, right.start_time)
        hard_reasons: list[str] = []
        if left.user_id != right.user_id or left.session_id != right.session_id:
            hard_reasons.append("different_scope")
        if left.completion is Completion.COMPLETED:
            hard_reasons.append("unrelated_after_completion")
        if _incompatible_nonempty(left.goal, right.goal):
            hard_reasons.append("incompatible_goal")
        if _mutually_exclusive_instances(left, right):
            hard_reasons.append("mutually_exclusive_task_instance")
        if gap < 0:
            hard_reasons.append("time_direction")

        features = {
            "same_task_goal": float(
                _same_nonempty(left.task, right.task)
                or _same_nonempty(left.goal, right.goal)
            ),
            "artifact_overlap": _overlap(left.artifact_refs, right.artifact_refs),
            "entity_overlap": _overlap(left.entity_refs, right.entity_refs),
            "time_close": float(0 <= gap <= self.config.merge_gap_seconds),
            "state_continuity": _mapping_continuity(
                left.post_state,
                right.pre_state,
            ),
            "unfinished_then_continue": float(
                left.completion is not Completion.COMPLETED
                and (
                    _same_nonempty(left.task, right.task)
                    or _overlap(left.artifact_refs, right.artifact_refs) > 0
                    or _overlap(left.entity_refs, right.entity_refs) > 0
                )
            ),
        }
        score = sum(
            features[name] * float(weight)
            for name, weight in self.config.merge_weights.items()
        )
        should_merge = not hard_reasons and score >= self.config.merge_threshold
        return should_merge, {
            "score": round(score, 6),
            "threshold": self.config.merge_threshold,
            "features": features,
            "hard_gate_reasons": hard_reasons,
        }

    def _fragment(
        self,
        observations: list[StrictObservation],
        boundary: BoundaryDecision | None,
        provisional_episode_ids: Mapping[str, str],
    ) -> ExecutionFragment:
        observation_ids = tuple(item.observation_id for item in observations)
        fragment_id = "frag-" + uuid5(
            NAMESPACE_URL,
            (
                f"strict-fragment-start:{observations[0].user_id}:"
                f"{observations[0].session_id}:"
                f"{observations[0].observation_id}"
            ),
        ).hex
        return ExecutionFragment(
            fragment_id=fragment_id,
            user_id=observations[0].user_id,
            session_id=observations[0].session_id,
            observation_ids=observation_ids,
            start_time=observations[0].event_time,
            end_time=observations[-1].event_time,
            task=_representative(item.task_hint for item in observations),
            goal=_representative(item.goal_hint for item in observations),
            pre_state=dict(observations[0].pre_state),
            post_state=dict(observations[-1].post_state),
            actions=_semantic_actions(observations),
            artifact_refs=_union(item.artifact_refs for item in observations),
            entity_refs=_union(item.entity_refs for item in observations),
            apps=_union((item.app,) for item in observations if item.app),
            completion=_fragment_completion(observations),
            source_episode_ids=_union(
                (provisional_episode_ids[item.observation_id],)
                for item in observations
            ),
            boundary_before=boundary,
        )

    def _merge_pass(
        self,
        fragments: list[ExecutionFragment],
        trace: list[dict[str, Any]],
    ) -> list[ExecutionFragment]:
        merged: list[ExecutionFragment] = []
        for fragment in fragments:
            if not merged:
                merged.append(fragment)
                continue
            left = merged[-1]
            should_merge, decision = self.merge_decision(left, fragment)
            trace.append(
                {
                    "operation": "merge_decision",
                    "left_fragment_id": left.fragment_id,
                    "right_fragment_id": fragment.fragment_id,
                    "should_merge": should_merge,
                    **decision,
                }
            )
            if should_merge:
                merged[-1] = _merge_fragments(left, fragment)
            else:
                merged.append(fragment)
        return merged


def _merge_fragments(
    left: ExecutionFragment,
    right: ExecutionFragment,
) -> ExecutionFragment:
    observation_ids = left.observation_ids + right.observation_ids
    return ExecutionFragment(
        fragment_id=left.fragment_id,
        user_id=left.user_id,
        session_id=left.session_id,
        observation_ids=observation_ids,
        start_time=left.start_time,
        end_time=right.end_time,
        task=left.task or right.task,
        goal=left.goal or right.goal,
        pre_state=left.pre_state,
        post_state=right.post_state,
        actions=_union((left.actions, right.actions)),
        artifact_refs=_union((left.artifact_refs, right.artifact_refs)),
        entity_refs=_union((left.entity_refs, right.entity_refs)),
        apps=_union((left.apps, right.apps)),
        completion=right.completion,
        source_episode_ids=_union(
            (left.source_episode_ids, right.source_episode_ids)
        ),
        boundary_before=left.boundary_before,
    )


def _validate_path(
    observations: list[StrictObservation],
    fragments: list[ExecutionFragment],
) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    expected = [item.observation_id for item in observations]
    actual = [
        observation_id
        for fragment in fragments
        for observation_id in fragment.observation_ids
    ]
    if actual != expected:
        reasons.append("observation_order_or_coverage")
    if len(actual) != len(set(actual)):
        reasons.append("observation_reused")
    times = [datetime.fromisoformat(item.event_time) for item in observations]
    if times != sorted(times):
        reasons.append("time_not_monotonic")
    for left, right in zip(observations, observations[1:]):
        continuity = _mapping_continuity(left.post_state, right.pre_state)
        same_fragment = any(
            left.observation_id in fragment.observation_ids
            and right.observation_id in fragment.observation_ids
            for fragment in fragments
        )
        if same_fragment and continuity == 0.0 and left.post_state and right.pre_state:
            reasons.append("state_discontinuity_inside_fragment")
    return not reasons, reasons or ["valid"]


def _semantic_actions(
    observations: Iterable[StrictObservation],
) -> tuple[str, ...]:
    actions: list[str] = []
    for item in observations:
        action = item.action.strip().lower()
        if action and action not in NOISE_ACTIONS:
            actions.append(action)
        if item.tool:
            outcome = "success" if item.result.get("success") else "failure"
            actions.append(f"tool:{item.tool}:{outcome}")
    return _deduplicate(actions)


def _fragment_completion(
    observations: list[StrictObservation],
) -> Completion:
    for item in reversed(observations):
        if item.completion is not Completion.UNKNOWN:
            return item.completion
    return Completion.UNKNOWN


def _state_discontinuity(
    left: StrictObservation,
    right: StrictObservation,
) -> float:
    continuity = _mapping_continuity(left.post_state, right.pre_state)
    if not left.post_state or not right.pre_state:
        return 0.0
    return 1.0 - continuity


def _mapping_continuity(
    left: Mapping[str, Any],
    right: Mapping[str, Any],
) -> float:
    shared = set(left) & set(right)
    if not shared:
        return 0.0
    matches = sum(left[key] == right[key] for key in shared)
    return matches / len(shared)


def _new_task_started(
    left: StrictObservation,
    right: StrictObservation,
) -> bool:
    if right.action.lower() in {"task_started", "task_resumed", "started"}:
        return True
    return bool(
        (right.task_hint and right.task_hint != left.task_hint)
        or (right.goal_hint and right.goal_hint != left.goal_hint)
    )


def _mutually_exclusive_instances(
    left: ExecutionFragment,
    right: ExecutionFragment,
) -> bool:
    if not left.task or not right.task or left.task == right.task:
        return False
    related = (
        _overlap(left.artifact_refs, right.artifact_refs) > 0
        or _overlap(left.entity_refs, right.entity_refs) > 0
    )
    return not related


def _related_by_artifact_or_entity(
    left: StrictObservation,
    right: StrictObservation,
) -> bool:
    return bool(
        set(left.artifact_refs) & set(right.artifact_refs)
        or set(left.entity_refs) & set(right.entity_refs)
    )


def _representative(values: Iterable[str]) -> str:
    cleaned = [value.strip() for value in values if value.strip()]
    if not cleaned:
        return ""
    counts = Counter(cleaned)
    return max(counts, key=lambda value: (counts[value], -cleaned.index(value)))


def _union(groups: Iterable[Iterable[str]]) -> tuple[str, ...]:
    return _deduplicate(item for group in groups for item in group if item)


def _deduplicate(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(values))


def _same_nonempty(left: str, right: str) -> bool:
    return bool(left and right and left.casefold() == right.casefold())


def _different_nonempty(left: str, right: str) -> float:
    return float(bool(left and right and left.casefold() != right.casefold()))


def _incompatible_nonempty(left: str, right: str) -> bool:
    return bool(_different_nonempty(left, right))


def _disjoint_nonempty(
    left: Iterable[str],
    right: Iterable[str],
) -> float:
    left_set = set(left)
    right_set = set(right)
    return float(bool(left_set and right_set and left_set.isdisjoint(right_set)))


def _overlap(
    left: Iterable[str],
    right: Iterable[str],
) -> float:
    left_set = set(left)
    right_set = set(right)
    if not left_set or not right_set:
        return 0.0
    return len(left_set & right_set) / len(left_set | right_set)


def _seconds(left: str, right: str) -> float:
    return (
        datetime.fromisoformat(right) - datetime.fromisoformat(left)
    ).total_seconds()
