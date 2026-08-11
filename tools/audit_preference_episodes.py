from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from src.memory_engine.preference_episode import (
    PreferenceEpisode,
    PreferenceEpisodeEngine,
)
from src.memory_engine.preference_matching import PreferenceObservationMemory


DEFAULT_INPUT = Path(
    "outputs/remote_preference_frame_audit/"
    "kylin_os_agent_observations_v31_original_punctuation_"
    "temporal_scope_anchors_v2.json"
)
DEFAULT_OUTPUT = Path(
    "outputs/remote_preference_frame_audit/"
    "kylin_os_agent_preference_episodes_v1.json"
)
QUERY_SUFFIX = re.compile(r"_(?:HQ|Q)\d+$", re.IGNORECASE)


def _session_id(case_id: str) -> str:
    kind, value = case_id.split(":", 1)
    if kind == "event":
        return value
    session = QUERY_SUFFIX.sub("", value)
    if session != value:
        return session
    raise ValueError(f"cannot derive session from case id: {case_id}")


def _polarity(value: float) -> str:
    if value >= 0.12:
        return "support"
    if value <= -0.12:
        return "oppose"
    return "uncertain"


def _noisy_or(values: Iterable[float]) -> float:
    remaining = 1.0
    for value in values:
        remaining *= 1.0 - max(0.0, min(1.0, value))
    return 1.0 - remaining


def _time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _observations(
    cases: list[dict[str, Any]],
) -> tuple[
    list[PreferenceObservationMemory],
    dict[str, dict[str, Any]],
]:
    rows: list[PreferenceObservationMemory] = []
    source: dict[str, dict[str, Any]] = {}
    session_positions: Counter[str] = Counter()
    base = datetime(2026, 7, 27, tzinfo=timezone.utc)

    for case in cases:
        session_id = _session_id(case["id"])
        position = session_positions[session_id]
        session_positions[session_id] += 1
        observed_time = (
            base + timedelta(minutes=position)
        ).isoformat()
        for frame_index, prediction in enumerate(
            case.get("predicted_observations") or ()
        ):
            memory_id = f"audit:{case['id']}:{frame_index}"
            temporal = prediction.get("temporal_label") or ""
            confidence = float(prediction.get("confidence") or 0.0)
            observation = PreferenceObservationMemory(
                memory_id=memory_id,
                observation_id=f"observation:{case['id']}:{frame_index}",
                source_event_id=case["id"],
                user_id="os-agent-v31-user",
                session_id=session_id,
                observed_time=observed_time,
                source_text=case.get("original_text") or case.get("text") or "",
                condition_tag_id=prediction.get("condition_tag_id") or "",
                condition_name=prediction.get("condition_text") or "",
                condition_text=prediction.get("condition_text") or "",
                object_tag_id=prediction.get("object_tag_id") or "",
                object_name=prediction.get("object_text") or "",
                object_text=prediction.get("object_text") or "",
                attitude_value=float(
                    prediction.get("attitude_value") or 0.0
                ),
                attitude_anchor=(
                    prediction.get("attitude_direction") or "uncertain"
                ),
                # The historical export omitted this field. Frame confidence
                # is the least assumptive reconstruction available.
                attitude_confidence=confidence,
                temporal_label=temporal,
                promotion_seed=(
                    1.0
                    if temporal
                    in {"temporal_medium", "temporal_long"}
                    else 0.0
                ),
                explicit_long_term=temporal == "temporal_long",
                extraction_confidence=confidence,
                source_start=int(prediction.get("source_start") or 0),
                source_end=int(prediction.get("source_end") or 0),
            )
            rows.append(observation)
            source[memory_id] = {
                "case_id": case["id"],
                "source_kind": case["source_kind"],
                "evaluation_track": case["evaluation_track"],
                "query_type": case["query_type"],
                "text": observation.source_text,
                "gold_observations": case.get("gold_observations") or [],
                "prediction": prediction,
            }
    return rows, source


def _continuity(
    episode: PreferenceEpisode,
    engine: PreferenceEpisodeEngine,
) -> list[dict[str, Any]]:
    rows = []
    for index in range(1, len(episode.observations)):
        left = episode.observations[index - 1]
        right = episode.observations[index]
        gap = (_time(right.observed_time) - _time(left.observed_time)).total_seconds()
        intervening = max(
            0,
            (
                episode.sequence_positions[index]
                - episode.sequence_positions[index - 1]
                - 1
            ),
        )
        time_closeness = max(
            0.0,
            1.0 - gap / max(engine.config.max_gap_seconds, 1),
        )
        order_closeness = min(
            1.0,
            max(
                0.0,
                1.0
                - intervening
                / max(engine.config.max_intervening_observations + 1, 1),
            ),
        )
        score = 0.60 + 0.25 * time_closeness + 0.15 * order_closeness
        rows.append(
            {
                "left_memory_id": left.memory_id,
                "right_memory_id": right.memory_id,
                "condition_exact": True,
                "time_gap_seconds": gap,
                "intervening_observations": intervening,
                "diagnostic_continuity_score": round(score, 6),
            }
        )
    return rows


def _feature_groups(
    episode: PreferenceEpisode,
    engine: PreferenceEpisodeEngine,
) -> list[dict[str, Any]]:
    grouped: dict[
        tuple[str, str],
        list[PreferenceObservationMemory],
    ] = {}
    for observation in episode.observations:
        polarity = _polarity(observation.attitude_value)
        if not observation.object_tag_id or polarity == "uncertain":
            continue
        grouped.setdefault(
            (observation.object_tag_id, polarity),
            [],
        ).append(observation)

    rows = []
    for (object_tag_id, polarity), observations in grouped.items():
        by_source: dict[str, PreferenceObservationMemory] = {}
        for observation in observations:
            current = by_source.get(observation.source_event_id)
            if (
                current is None
                or engine.observation_strength(observation)
                > engine.observation_strength(current)
            ):
                by_source[observation.source_event_id] = observation
        independent = list(by_source.values())
        strengths = [
            engine.observation_strength(item)
            for item in independent
        ]
        aggregate = _noisy_or(strengths)
        strongest = max(strengths, default=0.0)
        rows.append(
            {
                "object_tag_id": object_tag_id,
                "attitude_polarity": polarity,
                "memory_relation": 1.0,
                "support_count": len(independent),
                "source_memory_ids": [
                    item.memory_id for item in independent
                ],
                "individual_strengths": [
                    round(value, 6) for value in strengths
                ],
                "strongest_strength": round(strongest, 6),
                "aggregate_strength": round(aggregate, 6),
                "passes_single_threshold": (
                    strongest
                    >= engine.config.single_strength_threshold
                ),
                "passes_aggregate_threshold": (
                    len(independent)
                    >= engine.config.minimum_aggregate_support
                    and aggregate
                    >= engine.config.aggregate_strength_threshold
                ),
            }
        )
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    dataset = json.loads(args.input.read_text(encoding="utf-8"))
    observations, source = _observations(dataset["cases"])
    engine = PreferenceEpisodeEngine()
    result = engine.process(observations)
    memory_by_episode: dict[str, list[dict[str, Any]]] = {}
    for memory in result.memories:
        memory_by_episode.setdefault(memory.episode_id, []).append(
            asdict(memory)
        )

    episodes = []
    for episode in result.episodes:
        feature_groups = _feature_groups(episode, engine)
        memories = memory_by_episode.get(episode.episode_id, [])
        episodes.append(
            {
                "episode_id": episode.episode_id,
                "session_id": episode.session_id,
                "condition_tag_id": episode.condition_tag_id,
                "observation_count": len(episode.observations),
                "independent_source_count": len(
                    {
                        item.source_event_id
                        for item in episode.observations
                    }
                ),
                "source_memory_ids": [
                    item.memory_id for item in episode.observations
                ],
                "observations": [
                    {
                        **source[item.memory_id],
                        "memory_id": item.memory_id,
                        "condition_tag_id": item.condition_tag_id,
                        "object_tag_id": item.object_tag_id,
                        "attitude_value": item.attitude_value,
                        "attitude_polarity": _polarity(
                            item.attitude_value
                        ),
                        "temporal_label": item.temporal_label,
                        "reconstructed_strength": round(
                            engine.observation_strength(item),
                            6,
                        ),
                    }
                    for item in episode.observations
                ],
                "continuity": _continuity(episode, engine),
                "feature_groups": feature_groups,
                "suitable_for_memory": bool(memories),
                "memories": memories,
            }
        )

    output = {
        "purpose": (
            "Episode audit over the previously generated OS Agent v3.1 "
            "Observation predictions. No embeddings or LLMs are rerun."
        ),
        "input": str(args.input),
        "weight_reconstruction": {
            "attitude_confidence": (
                "Historical export omitted attitude_confidence; frame "
                "confidence is reused for audit reconstruction."
            ),
            "strength": (
                "0.45 * extraction_confidence + "
                "0.30 * attitude_confidence + "
                "0.25 * abs(attitude_value)"
            ),
        },
        "continuity_diagnostic": {
            "note": (
                "This score explains accepted boundaries; the engine uses "
                "the underlying hard gates, not this combined score."
            ),
            "formula": (
                "0.60 * exact_condition + 0.25 * time_closeness + "
                "0.15 * order_closeness"
            ),
        },
        "config": asdict(engine.config),
        "summary": {
            "input_case_count": len(dataset["cases"]),
            "input_observation_count": len(observations),
            "episode_count": len(result.episodes),
            "multi_observation_episode_count": sum(
                len(item.observations) > 1
                for item in result.episodes
            ),
            "multi_source_episode_count": sum(
                len({value.source_event_id for value in item.observations})
                > 1
                for item in result.episodes
            ),
            "suitable_episode_count": sum(
                bool(memory_by_episode.get(item.episode_id))
                for item in result.episodes
            ),
            "unsuitable_episode_count": sum(
                not memory_by_episode.get(item.episode_id)
                for item in result.episodes
            ),
            "memory_count": len(result.memories),
            "strong_single_memory_count": sum(
                item.promotion_reason == "strong_single"
                for item in result.memories
            ),
            "aggregate_memory_count": sum(
                item.promotion_reason == "coherent_aggregate"
                for item in result.memories
            ),
        },
        "episodes": episodes,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(output, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(output["summary"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
