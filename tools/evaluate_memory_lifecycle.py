from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from time import perf_counter
from typing import Any, Callable, Iterable, Mapping

from src.memory_engine.memory_lifecycle import (
    CONFIDENCE_STRATEGIES,
    STABILITY_STRATEGIES,
    ConfidenceEvidence,
    LifecycleObservation,
    MemoryLifeRelation,
    MemoryLifeSeed,
    MemoryLifecycleEngine,
)


DEFAULT_OBSERVATIONS = Path(
    "outputs/remote_preference_frame_audit/"
    "kylin_os_agent_observations_v31_original_punctuation_"
    "temporal_scope_anchors_v2.json"
)
DEFAULT_MEMORIES = Path(
    "outputs/remote_preference_frame_audit/"
    "kylin_os_agent_preference_episodes_v1.json"
)
DEFAULT_OUTPUT = Path(
    "outputs/memory_lifecycle/comparison_v1.json"
)
BASE = datetime(2026, 1, 1, tzinfo=timezone.utc)
REPLAY_TOP_K = 2


def _at(day: float) -> str:
    return (BASE + timedelta(days=day)).isoformat()


def _day(value: str) -> float:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return (parsed.astimezone(timezone.utc) - BASE).total_seconds() / 86400


def _polarity(value: str) -> str:
    normalized = value.strip().casefold()
    if normalized in {"positive", "support", "like"}:
        return "support"
    if normalized in {"negative", "oppose", "avoid"}:
        return "oppose"
    return ""


def _key(
    condition: str,
    object_id: str,
    polarity: str,
) -> tuple[str, str, str]:
    return condition, object_id, polarity


def _memory_key(seed: MemoryLifeSeed) -> tuple[str, str, str]:
    return _key(
        seed.condition_tag_ids[0] if seed.condition_tag_ids else "",
        seed.object_tag_ids[0] if seed.object_tag_ids else "",
        seed.attitude_polarity,
    )


def _temporal_confidence(memory: dict[str, Any]) -> float:
    if memory.get("explicit_long_term"):
        return 0.95
    label = str(memory.get("temporal_label") or "")
    if label == "temporal_long":
        return 0.65
    if label == "temporal_medium":
        return 0.55
    if label == "temporal_short":
        return 0.20
    return 0.0


def _raw_memories(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return [
        dict(memory)
        for episode in payload["episodes"]
        for memory in episode.get("memories") or ()
    ]


def _late_memory_ids(
    memories: Iterable[dict[str, Any]],
) -> set[str]:
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = (
        defaultdict(list)
    )
    for memory in memories:
        grouped[
            _key(
                str(memory["condition_tag_id"]),
                str(memory["object_tag_id"]),
                str(memory["attitude_polarity"]),
            )
        ].append(memory)
    selected = []
    for key in sorted(grouped):
        values = sorted(
            grouped[key],
            key=lambda item: str(item["memory_id"]),
        )
        if len(values) > 1:
            selected.append(str(values[-1]["memory_id"]))
        if len(selected) == 12:
            break
    return set(selected)


def _text_seed(
    memory: dict[str, Any],
    *,
    created_day: float,
) -> MemoryLifeSeed:
    support_count = max(1, int(memory.get("support_count") or 1))
    source_ids = tuple(memory.get("source_event_ids") or ())
    quality = float(
        memory.get("strongest_observation_strength")
        or memory.get("strength")
        or 0.8
    )
    evidence = []
    for index in range(support_count):
        source_id = (
            str(source_ids[index])
            if index < len(source_ids)
            else f"{memory['memory_id']}:source:{index}"
        )
        observed_day = created_day - 7.0 * (
            support_count - index - 1
        )
        evidence.append(
            ConfidenceEvidence(
                evidence_id=(
                    f"{memory['memory_id']}:confidence:{index}"
                ),
                observed_at=_at(observed_day),
                source_kind="text",
                quality=quality,
                independent_unit_id=source_id,
            )
        )
    return MemoryLifeSeed(
        memory_id=str(memory["memory_id"]),
        user_id=str(memory["user_id"]),
        created_at=_at(created_day),
        source_kind="text",
        temporal_label=str(memory.get("temporal_label") or ""),
        temporal_confidence=_temporal_confidence(memory),
        explicit_long_term=bool(memory.get("explicit_long_term")),
        base_strength=float(memory["strength"]),
        condition_tag_ids=(str(memory["condition_tag_id"]),),
        object_tag_ids=(str(memory["object_tag_id"]),),
        attitude_polarity=str(memory["attitude_polarity"]),
        evidence=tuple(evidence),
        conflicting_strength=float(
            memory.get("conflicting_strength") or 0.0
        ),
        metadata={
            "session_id": memory.get("session_id"),
            "support_count": support_count,
            "promotion_reason": memory.get("promotion_reason"),
            "episode_id": memory.get("episode_id"),
            "condition_name": memory.get("condition_name"),
            "object_name": memory.get("object_name"),
            "source_observation_ids": tuple(
                memory.get("source_observation_ids") or ()
            ),
            "source_event_ids": tuple(
                memory.get("source_event_ids") or ()
            ),
            "source_memory_ids": tuple(
                memory.get("source_memory_ids") or ()
            ),
            "dataset_source": "os_agent_memory_query_benchmark_v3.1",
        },
    )


def _control_seed(
    memory_id: str,
    *,
    source_kind: str,
    condition: str,
    object_id: str,
    created_day: float,
    temporal_label: str = "temporal_short",
    temporal_confidence: float = 0.2,
    explicit_long_term: bool = False,
    base_strength: float = 0.9,
) -> MemoryLifeSeed:
    return MemoryLifeSeed(
        memory_id=memory_id,
        user_id="os-agent-v31-user",
        created_at=_at(created_day),
        source_kind=source_kind,
        temporal_label=temporal_label,
        temporal_confidence=temporal_confidence,
        explicit_long_term=explicit_long_term,
        base_strength=base_strength,
        condition_tag_ids=(condition,),
        object_tag_ids=(object_id,),
        attitude_polarity="support",
        evidence=(
            ConfidenceEvidence(
                evidence_id=f"{memory_id}:evidence",
                observed_at=_at(created_day),
                source_kind=source_kind,
                quality=0.88,
                independent_unit_id=f"{memory_id}:unit",
            ),
        ),
        metadata={"dataset_source": "controlled_lifecycle_probe"},
    )


def _probe_seed(
    memory: dict[str, Any],
    *,
    role: str,
    index: int,
) -> MemoryLifeSeed:
    memory_id = f"control-{role}:{memory['memory_id']}"
    seed = _text_seed(memory, created_day=0.0)
    evidence = tuple(
        replace(
            item,
            evidence_id=f"{memory_id}:evidence:{position}",
            independent_unit_id=f"{memory_id}:unit:{position}",
        )
        for position, item in enumerate(seed.evidence)
    )
    return replace(
        seed,
        memory_id=memory_id,
        user_id=f"lifecycle-{role}-probe-{index}",
        evidence=evidence,
        metadata={
            "dataset_source": "controlled_lifecycle_probe",
            "probe_role": role,
            "source_memory_id": memory["memory_id"],
            "probe_index": index,
            "support_count": memory.get("support_count"),
        },
    )


def build_fixture(
    memory_path: Path,
) -> tuple[
    tuple[MemoryLifeSeed, ...],
    tuple[MemoryLifeSeed, ...],
    tuple[MemoryLifeRelation, ...],
    dict[str, object],
]:
    raw = sorted(
        _raw_memories(memory_path),
        key=lambda item: (
            str(item.get("session_id") or ""),
            str(item["memory_id"]),
        ),
    )
    late_ids = _late_memory_ids(raw)
    seeds = []
    initial_index = 0
    late_index = 0
    for memory in raw:
        memory_id = str(memory["memory_id"])
        if memory_id in late_ids:
            created_day = 305.0 + late_index * 0.20
            late_index += 1
        else:
            created_day = 30.0 * initial_index / max(
                1,
                len(raw) - len(late_ids) - 1,
            )
            initial_index += 1
        seeds.append(
            _text_seed(memory, created_day=created_day)
        )

    probe_raw = [
        memory
        for memory in raw
        if (
            memory.get("temporal_label") == "temporal_short"
            and int(memory.get("support_count") or 1) <= 2
            and not memory.get("explicit_long_term")
        )
    ]
    stale_probes = tuple(
        _probe_seed(memory, role="stale", index=index)
        for index, memory in enumerate(probe_raw[:12])
    )
    active_probes = tuple(
        _probe_seed(memory, role="active", index=index)
        for index, memory in enumerate(probe_raw[12:24])
    )
    controls = (
        _control_seed(
            "control-source-text",
            source_kind="text",
            condition="condition:control:source_prior",
            object_id="object:control:source_prior",
            created_day=10.0,
            temporal_label="temporal_long",
            temporal_confidence=0.95,
            explicit_long_term=True,
        ),
        _control_seed(
            "control-source-log",
            source_kind="log",
            condition="condition:control:source_prior",
            object_id="object:control:source_prior",
            created_day=10.0,
            temporal_label="temporal_long",
            temporal_confidence=0.95,
            explicit_long_term=True,
        ),
        _control_seed(
            "log-w32time-request",
            source_kind="log",
            condition="condition:service:w32time",
            object_id="object:time_resync_request",
            created_day=12.0,
            base_strength=0.88,
        ),
        _control_seed(
            "log-w32time-sync",
            source_kind="log",
            condition="condition:service:w32time",
            object_id="object:time_source_sync",
            created_day=12.1,
            base_strength=0.93,
        ),
        _control_seed(
            "log-w32time-updated",
            source_kind="log",
            condition="condition:service:w32time",
            object_id="object:system_time_update",
            created_day=12.2,
            base_strength=0.96,
        ),
        _control_seed(
            "log-codex-process",
            source_kind="log",
            condition="condition:app:chatgpt_codex",
            object_id="object:process_creation",
            created_day=13.0,
            base_strength=0.86,
        ),
        _control_seed(
            "log-dell-process",
            source_kind="log",
            condition="condition:app:dell_power_manager",
            object_id="object:process_creation",
            created_day=13.2,
            base_strength=0.83,
        ),
        *stale_probes,
        *active_probes,
    )
    seeds.extend(controls)
    by_id = {seed.memory_id: seed for seed in seeds}

    grouped: dict[tuple[str, str, str], list[MemoryLifeSeed]] = (
        defaultdict(list)
    )
    for seed in seeds:
        if seed.metadata.get("dataset_source") == (
            "os_agent_memory_query_benchmark_v3.1"
        ):
            grouped[_memory_key(seed)].append(seed)

    relations = []
    for key in sorted(grouped):
        values = sorted(
            grouped[key],
            key=lambda seed: (
                _day(seed.created_at),
                seed.memory_id,
            ),
        )
        for left, right in zip(values, values[1:]):
            observed_day = max(
                _day(left.created_at),
                _day(right.created_at),
            )
            relations.append(
                MemoryLifeRelation(
                    relation_id=(
                        f"supports:{left.memory_id}:{right.memory_id}"
                    ),
                    source_memory_id=left.memory_id,
                    target_memory_id=right.memory_id,
                    relation_type="supports",
                    weight=round(
                        0.72
                        + 0.22
                        * min(
                            left.base_strength,
                            right.base_strength,
                        ),
                        6,
                    ),
                    observed_at=_at(observed_day),
                )
            )

    by_scope: dict[tuple[str, str], dict[str, list[MemoryLifeSeed]]] = (
        defaultdict(lambda: defaultdict(list))
    )
    for seed in seeds:
        condition, object_id, polarity = _memory_key(seed)
        by_scope[(condition, object_id)][polarity].append(seed)
    for scope in sorted(by_scope):
        supports = by_scope[scope].get("support") or ()
        opposes = by_scope[scope].get("oppose") or ()
        if not supports or not opposes:
            continue
        left = max(supports, key=lambda seed: seed.base_strength)
        right = max(opposes, key=lambda seed: seed.base_strength)
        observed_day = max(
            _day(left.created_at),
            _day(right.created_at),
        )
        relations.append(
            MemoryLifeRelation(
                relation_id=f"conflicts:{left.memory_id}:{right.memory_id}",
                source_memory_id=left.memory_id,
                target_memory_id=right.memory_id,
                relation_type="conflicts",
                weight=round(
                    0.70
                    + 0.20
                    * min(left.base_strength, right.base_strength),
                    6,
                ),
                observed_at=_at(observed_day),
            )
        )

    relations.extend(
        (
            MemoryLifeRelation(
                relation_id="precedes:w32time-request:sync",
                source_memory_id="log-w32time-request",
                target_memory_id="log-w32time-sync",
                relation_type="precedes",
                weight=0.91,
                observed_at=_at(12.1),
                directed=True,
            ),
            MemoryLifeRelation(
                relation_id="precedes:w32time-sync:updated",
                source_memory_id="log-w32time-sync",
                target_memory_id="log-w32time-updated",
                relation_type="precedes",
                weight=0.94,
                observed_at=_at(12.2),
                directed=True,
            ),
            MemoryLifeRelation(
                relation_id="related:source-prior-control",
                source_memory_id="control-source-text",
                target_memory_id="control-source-log",
                relation_type="related",
                weight=0.95,
                observed_at=_at(10.0),
            ),
        )
    )
    relations.sort(
        key=lambda relation: (
            _day(relation.observed_at),
            relation.relation_id,
        )
    )
    initial = tuple(
        seed for seed in seeds if seed.memory_id not in late_ids
    )
    late = tuple(
        seed for seed in seeds if seed.memory_id in late_ids
    )
    return (
        initial,
        late,
        tuple(relations),
        {
            "raw_memory_count": len(raw),
            "initial_memory_count": len(initial),
            "late_memory_count": len(late),
            "log_control_count": sum(
                seed.source_kind == "log" for seed in controls
            ),
            "stale_probe_count": len(stale_probes),
            "active_probe_count": len(active_probes),
            "late_memory_ids": sorted(late_ids),
            "temporal_labels": {
                label: sum(
                    seed.temporal_label == label
                    for seed in seeds
                    if seed.metadata.get("dataset_source")
                    == "os_agent_memory_query_benchmark_v3.1"
                )
                for label in (
                    "temporal_short",
                    "temporal_medium",
                    "temporal_long",
                )
            },
            "relation_count": len(relations),
            "positive_relation_count": sum(
                relation.relation_type == "supports"
                for relation in relations
            ),
            "conflict_relation_count": sum(
                relation.relation_type == "conflicts"
                for relation in relations
            ),
            "memory_ids": sorted(by_id),
        },
    )


def _query_time(index: int, total: int) -> str:
    split = int(total * 0.70)
    if index < split:
        fraction = index / max(1, split - 1)
        return _at(35.0 + 65.0 * fraction)
    fraction = (index - split) / max(1, total - split - 1)
    return _at(240.0 + 60.0 * fraction)


def _case_gold_keys(
    case: dict[str, Any],
) -> set[tuple[str, str, str]]:
    return {
        _key(
            str(item.get("condition_tag_id") or ""),
            str(item.get("object_tag_id") or ""),
            _polarity(str(item.get("attitude_direction") or "")),
        )
        for item in case.get("gold_observations") or ()
    }


def _case_observations(
    case: dict[str, Any],
    at: str,
) -> tuple[LifecycleObservation, ...]:
    return tuple(
        LifecycleObservation(
            observation_id=f"{case['id']}:{index}",
            user_id="os-agent-v31-user",
            observed_at=at,
            source_kind="query",
            condition_tag_ids=(
                (str(item["condition_tag_id"]),)
                if item.get("condition_tag_id")
                else ()
            ),
            object_tag_ids=(
                (str(item["object_tag_id"]),)
                if item.get("object_tag_id")
                else ()
            ),
            attitude_polarity=_polarity(
                str(item.get("attitude_direction") or "")
            ),
            metadata={
                "case_id": case["id"],
                "query_type": case.get("query_type"),
                "evaluation_track": case.get("evaluation_track"),
            },
        )
        for index, item in enumerate(
            case.get("predicted_observations") or ()
        )
    )


def _observation_supports_key(
    observation: LifecycleObservation,
    key: tuple[str, str, str],
) -> bool:
    condition, object_id, polarity = key
    if (
        observation.condition_tag_ids
        and condition not in observation.condition_tag_ids
    ):
        return False
    if (
        observation.object_tag_ids
        and object_id not in observation.object_tag_ids
    ):
        return False
    if (
        observation.attitude_polarity
        and polarity
        and observation.attitude_polarity != polarity
    ):
        return False
    return bool(
        observation.condition_tag_ids
        or observation.object_tag_ids
        or observation.attitude_polarity
    )


def _partially_matches_gold(
    candidate: tuple[str, str, str],
    gold_keys: set[tuple[str, str, str]],
) -> bool:
    _, object_id, polarity = candidate
    return any(
        object_id
        and object_id == gold_object
        and polarity
        and polarity == gold_polarity
        for _, gold_object, gold_polarity in gold_keys
    )


def _apply_available_relations(
    engine: MemoryLifecycleEngine,
    relations: Iterable[MemoryLifeRelation],
) -> list[dict[str, object]]:
    applied = []
    for relation in relations:
        if relation.relation_id in engine.relations:
            continue
        if (
            relation.source_memory_id not in engine.states
            or relation.target_memory_id not in engine.states
        ):
            continue
        before = {
            memory_id: {
                "stability": float(
                    engine.stability_strategy.value(
                        engine.states[memory_id].stability,
                        relation.observed_at,
                    )
                ),
                "confidence": float(
                    engine.states[memory_id].confidence["value"]
                ),
            }
            for memory_id in (
                relation.source_memory_id,
                relation.target_memory_id,
            )
        }
        engine.add_relation(relation)
        after = {
            memory_id: {
                "stability": float(
                    engine.states[memory_id].stability["value"]
                ),
                "confidence": float(
                    engine.states[memory_id].confidence["value"]
                ),
            }
            for memory_id in before
        }
        applied.append(
            {
                "relation_id": relation.relation_id,
                "relation_type": relation.relation_type,
                "weight": relation.weight,
                "at": relation.observed_at,
                "before": before,
                "after": after,
            }
        )
    return applied


def _mean(values: Iterable[float]) -> float:
    selected = tuple(values)
    return sum(selected) / len(selected) if selected else 0.0


def _state_key(engine: MemoryLifecycleEngine, memory_id: str):
    return _memory_key(engine.states[memory_id].seed)


def _is_retained(
    engine: MemoryLifecycleEngine,
    memory_id: str,
) -> bool:
    seen = set()
    while memory_id and memory_id not in seen:
        seen.add(memory_id)
        state = engine.states.get(memory_id)
        if state is None:
            return False
        if state.status == "active":
            return True
        if state.status != "merged":
            return False
        memory_id = state.merged_into
    return False


def run_combination(
    stability_name: str,
    confidence_name: str,
    *,
    observation_path: Path,
    initial_seeds: tuple[MemoryLifeSeed, ...],
    late_seeds: tuple[MemoryLifeSeed, ...],
    relations: tuple[MemoryLifeRelation, ...],
    reflection_callback: (
        Callable[
            [MemoryLifecycleEngine, str, str],
            Mapping[str, object],
        ]
        | None
    ) = None,
    engine_options: Mapping[str, object] | None = None,
) -> tuple[dict[str, object], MemoryLifecycleEngine]:
    engine = MemoryLifecycleEngine(
        STABILITY_STRATEGIES[stability_name](),
        CONFIDENCE_STRATEGIES[confidence_name](),
        **dict(engine_options or {}),
    )
    started = perf_counter()
    for seed in sorted(
        initial_seeds,
        key=lambda item: (_day(item.created_at), item.memory_id),
    ):
        engine.add_memory(seed)
    relation_trace = _apply_available_relations(engine, relations)
    reflection_trace: list[Mapping[str, object]] = []

    active_probe_ids = [
        memory_id
        for memory_id, state in engine.states.items()
        if state.seed.metadata.get("probe_role") == "active"
    ]
    refresh_trace = []
    for day in (30.0, 90.0, 180.0):
        for memory_id in active_probe_ids:
            state = engine.states[memory_id]
            result = engine.query(
                LifecycleObservation(
                    observation_id=(
                        f"control-refresh:{memory_id}:{int(day)}"
                    ),
                    user_id=state.seed.user_id,
                    observed_at=_at(day),
                    source_kind="query",
                    condition_tag_ids=state.seed.condition_tag_ids,
                    object_tag_ids=state.seed.object_tag_ids,
                    attitude_polarity=state.seed.attitude_polarity,
                ),
                top_k=1,
            )
            refresh_trace.append(result.to_dict())

    if reflection_callback is not None:
        reflection_trace.append(
            reflection_callback(
                engine,
                _at(34.0),
                "before_query_replay",
            )
        )

    payload = json.loads(observation_path.read_text(encoding="utf-8"))
    query_cases = [
        case
        for case in payload["cases"]
        if case.get("source_kind") == "query"
    ]
    query_case_count = 0
    eligible_case_count = 0
    hit_count = 0
    selected_count = 0
    correct_selected_count = 0
    semantic_selected_count = 0
    semantic_correct_selected_count = 0
    rescued_count = 0
    no_observation_count = 0
    prediction_covered_count = 0
    failure_stage_counts: dict[str, int] = defaultdict(int)
    incorrect_selection_counts: dict[str, int] = defaultdict(int)
    query_trace = []
    by_query_type: dict[str, dict[str, int]] = defaultdict(
        lambda: {
            "eligible": 0,
            "hit": 0,
            "selected": 0,
            "correct_selected": 0,
        }
    )
    for index, case in enumerate(query_cases):
        if (
            reflection_callback is not None
            and index == int(len(query_cases) * 0.70)
        ):
            reflection_trace.append(
                reflection_callback(
                    engine,
                    _at(220.0),
                    "between_query_epochs",
                )
            )
        at = _query_time(index, len(query_cases))
        observations = _case_observations(case, at)
        gold_keys = _case_gold_keys(case)
        prediction_covers_gold = any(
            _observation_supports_key(observation, gold_key)
            for observation in observations
            for gold_key in gold_keys
        )
        available_keys = {
            _memory_key(state.seed)
            for state in engine.states.values()
        }
        eligible = bool(gold_keys & available_keys)
        query_case_count += 1
        if eligible:
            eligible_case_count += 1
            prediction_covered_count += int(prediction_covers_gold)
        if not observations:
            no_observation_count += 1

        case_selected = []
        for observation in observations:
            result = engine.query(
                observation,
                top_k=REPLAY_TOP_K,
            )
            case_selected.extend(
                selection.memory_id
                for selection in result.selected
            )
            rescued_count += sum(
                selection.rescued for selection in result.selected
            )
        correct = [
            memory_id
            for memory_id in case_selected
            if _state_key(engine, memory_id) in gold_keys
        ]
        incorrect = [
            memory_id
            for memory_id in case_selected
            if _state_key(engine, memory_id) not in gold_keys
        ]
        semantic_selected = {
            _state_key(engine, memory_id)
            for memory_id in case_selected
        }
        semantic_correct = semantic_selected & gold_keys
        hit = bool(correct)
        if eligible:
            if hit:
                failure_stage = "hit"
            elif not observations:
                failure_stage = "upstream_abstention"
            elif not prediction_covers_gold:
                failure_stage = "upstream_label_miss"
            else:
                failure_stage = "lifecycle_retrieval_miss"
            failure_stage_counts[failure_stage] += 1
        for memory_id in incorrect:
            candidate_key = _state_key(engine, memory_id)
            if not any(
                _observation_supports_key(observation, candidate_key)
                for observation in observations
            ):
                category = "lifecycle_broad_match"
            elif prediction_covers_gold:
                category = "compatible_competitor"
            else:
                category = "upstream_prediction"
            incorrect_selection_counts[category] += 1
            if _partially_matches_gold(candidate_key, gold_keys):
                incorrect_selection_counts[
                    "object_attitude_partial"
                ] += 1
        if eligible and hit:
            hit_count += 1
        selected_count += len(case_selected)
        correct_selected_count += len(correct)
        semantic_selected_count += len(semantic_selected)
        semantic_correct_selected_count += len(semantic_correct)
        query_type = str(case.get("query_type") or "unknown")
        bucket = by_query_type[query_type]
        bucket["eligible"] += int(eligible)
        bucket["hit"] += int(eligible and hit)
        bucket["selected"] += len(case_selected)
        bucket["correct_selected"] += len(correct)
        lifecycle_miss = (
            eligible
            and failure_stage == "lifecycle_retrieval_miss"
        )
        if (
            lifecycle_miss
            or (
                len(query_trace) < 30
                and (
                    not hit
                    or len(correct) != len(case_selected)
                    or index % 31 == 0
                )
            )
        ):
            query_trace.append(
                {
                    "case_id": case["id"],
                    "at": at,
                    "query_type": query_type,
                    "gold_keys": [list(value) for value in gold_keys],
                    "predicted_keys": [
                        [
                            (
                                observation.condition_tag_ids[0]
                                if observation.condition_tag_ids
                                else ""
                            ),
                            (
                                observation.object_tag_ids[0]
                                if observation.object_tag_ids
                                else ""
                            ),
                            observation.attitude_polarity,
                        ]
                        for observation in observations
                    ],
                    "predicted_observation_count": len(observations),
                    "selected_memory_ids": case_selected,
                    "correct_memory_ids": correct,
                    "eligible": eligible,
                    "hit": hit,
                    "failure_stage": (
                        failure_stage if eligible else "not_eligible"
                    ),
                }
            )

    for seed in sorted(
        late_seeds,
        key=lambda item: (_day(item.created_at), item.memory_id),
    ):
        engine.add_memory(seed)
    late_relation_trace = _apply_available_relations(engine, relations)
    relation_trace.extend(late_relation_trace)
    if reflection_callback is not None:
        reflection_trace.append(
            reflection_callback(
                engine,
                _at(310.0),
                "after_late_memories",
            )
        )

    source_control = engine.query(
        LifecycleObservation(
            observation_id="control-query:source-prior",
            user_id="os-agent-v31-user",
            observed_at=_at(310),
            source_kind="query",
            condition_tag_ids=("condition:control:source_prior",),
            object_tag_ids=("object:control:source_prior",),
            attitude_polarity="support",
        ),
        top_k=1,
    )

    refresh_ids = active_probe_ids
    for day in (315.0, 350.0, 390.0):
        for memory_id in refresh_ids:
            state = engine.states[memory_id]
            if state.status != "active":
                continue
            result = engine.query(
                LifecycleObservation(
                    observation_id=(
                        f"control-refresh:{memory_id}:{int(day)}"
                    ),
                    user_id=state.seed.user_id,
                    observed_at=_at(day),
                    source_kind="query",
                    condition_tag_ids=state.seed.condition_tag_ids,
                    object_tag_ids=state.seed.object_tag_ids,
                    attitude_polarity=state.seed.attitude_polarity,
                ),
                top_k=1,
            )
            refresh_trace.append(result.to_dict())

    stale_candidates = [
        memory_id
        for memory_id, state in engine.states.items()
        if state.seed.metadata.get("probe_role") == "stale"
    ]
    real_stale_risk_ids = [
        memory_id
        for memory_id, state in engine.states.items()
        if (
            state.seed.temporal_label == "temporal_short"
            and not state.seed.explicit_long_term
            and _day(state.seed.created_at) <= 100.0
            and (
                not state.last_activated_at
                or _day(state.last_activated_at) <= 100.0
            )
            and int(state.seed.metadata.get("support_count") or 1) <= 2
            and len(state.relation_support) <= 1
            and state.seed.metadata.get("dataset_source")
            == "os_agent_memory_query_benchmark_v3.1"
        )
    ]
    long_ids = [
        seed.memory_id
        for seed in (*initial_seeds, *late_seeds)
        if (
            seed.explicit_long_term
            and seed.metadata.get("dataset_source")
            == "os_agent_memory_query_benchmark_v3.1"
        )
    ]

    engine.maintain(_at(420))
    elapsed_ms = (perf_counter() - started) * 1000.0

    active_survival = _mean(
        _is_retained(engine, memory_id)
        for memory_id in refresh_ids
    )
    long_survival = _mean(
        _is_retained(engine, memory_id)
        for memory_id in long_ids
    )
    stale_forget = _mean(
        engine.states[memory_id].status == "forgotten"
        for memory_id in stale_candidates
    )
    real_stale_forget = _mean(
        engine.states[memory_id].status == "forgotten"
        for memory_id in real_stale_risk_ids
    )
    positive_relation_events = [
        event
        for event in relation_trace
        if event["relation_type"] == "supports"
    ]
    conflict_relation_events = [
        event
        for event in relation_trace
        if event["relation_type"] == "conflicts"
    ]
    late_memory_ids = {seed.memory_id for seed in late_seeds}
    late_positive_relation_events = [
        event
        for event in positive_relation_events
        if late_memory_ids & set(event["before"])
    ]
    relation_lift = _mean(
        all(
            float(event["after"][memory_id]["stability"])
            > float(event["before"][memory_id]["stability"])
            and float(event["after"][memory_id]["confidence"])
            > float(event["before"][memory_id]["confidence"])
            for memory_id in event["before"]
        )
        for event in positive_relation_events
    )
    conflict_confidence_drop = _mean(
        all(
            float(event["after"][memory_id]["confidence"])
            < float(event["before"][memory_id]["confidence"])
            for memory_id in event["before"]
        )
        for event in conflict_relation_events
    )
    late_relation_lift = _mean(
        all(
            float(event["after"][memory_id]["stability"])
            > float(event["before"][memory_id]["stability"])
            and float(event["after"][memory_id]["confidence"])
            > float(event["before"][memory_id]["confidence"])
            for memory_id in event["before"]
        )
        for event in late_positive_relation_events
    )
    text_confidence = _mean(
        float(state.confidence["value"])
        for state in engine.states.values()
        if state.seed.source_kind == "text"
    )
    log_confidence = _mean(
        float(state.confidence["value"])
        for state in engine.states.values()
        if state.seed.source_kind == "log"
    )
    source_gap = text_confidence - log_confidence
    precision = (
        correct_selected_count / selected_count
        if selected_count
        else 0.0
    )
    semantic_precision = (
        semantic_correct_selected_count / semantic_selected_count
        if semantic_selected_count
        else 0.0
    )
    hit_rate = (
        hit_count / eligible_case_count
        if eligible_case_count
        else 0.0
    )
    source_control_selected = (
        source_control.selected[0].memory_id
        if source_control.selected
        else ""
    )
    source_choice = source_control_selected == "control-source-text"

    temporal_outcomes = {}
    for label in (
        "temporal_short",
        "temporal_medium",
        "temporal_long",
    ):
        states = [
            state
            for state in engine.states.values()
            if (
                state.seed.temporal_label == label
                and state.seed.metadata.get("dataset_source")
                == "os_agent_memory_query_benchmark_v3.1"
            )
        ]
        temporal_outcomes[label] = {
            "count": len(states),
            "active": sum(state.status == "active" for state in states),
            "retained": sum(
                _is_retained(engine, state.seed.memory_id)
                for state in states
            ),
            "merged": sum(state.status == "merged" for state in states),
            "forgotten": sum(
                state.status == "forgotten" for state in states
            ),
            "mean_stability": _mean(
                float(state.stability["value"]) for state in states
            ),
            "mean_confidence": _mean(
                float(state.confidence["value"]) for state in states
            ),
        }

    score = 10.0 * (
        0.20 * precision
        + 0.17 * hit_rate
        + 0.14 * active_survival
        + 0.14 * long_survival
        + 0.10 * stale_forget
        + 0.08 * real_stale_forget
        + 0.07 * min(1.0, max(0.0, source_gap) / 0.25)
        + 0.06 * relation_lift
        + 0.04 * float(source_choice)
    )
    summary = {
        "stability_strategy": stability_name,
        "confidence_strategy": confidence_name,
        "score": round(score, 6),
        "performance_ms": round(elapsed_ms, 6),
        "reflection": list(reflection_trace),
        "retrieval": {
            "query_case_count": query_case_count,
            "eligible_case_count": eligible_case_count,
            "no_observation_count": no_observation_count,
            "prediction_covered_eligible_count": (
                prediction_covered_count
            ),
            "hit_count": hit_count,
            "hit_rate": round(hit_rate, 6),
            "selected_count": selected_count,
            "correct_selected_count": correct_selected_count,
            "selection_precision": round(precision, 6),
            "semantic_selected_count": semantic_selected_count,
            "semantic_correct_selected_count": (
                semantic_correct_selected_count
            ),
            "semantic_selection_precision": round(
                semantic_precision,
                6,
            ),
            "rescued_activation_count": rescued_count,
            "failure_stage_counts": dict(
                sorted(failure_stage_counts.items())
            ),
            "incorrect_selection_counts": dict(
                sorted(incorrect_selection_counts.items())
            ),
            "by_query_type": {
                name: {
                    **values,
                    "hit_rate": round(
                        values["hit"] / values["eligible"],
                        6,
                    )
                    if values["eligible"]
                    else 0.0,
                    "selection_precision": round(
                        values["correct_selected"]
                        / values["selected"],
                        6,
                    )
                    if values["selected"]
                    else 0.0,
                }
                for name, values in sorted(by_query_type.items())
            },
        },
        "lifecycle": {
            "active_refresh_memory_count": len(refresh_ids),
            "active_refresh_survival": round(active_survival, 6),
            "explicit_long_memory_count": len(long_ids),
            "explicit_long_survival": round(long_survival, 6),
            "stale_short_memory_count": len(stale_candidates),
            "stale_short_forget_rate": round(stale_forget, 6),
            "real_stale_risk_memory_count": len(
                real_stale_risk_ids
            ),
            "real_stale_risk_forgotten": sum(
                engine.states[memory_id].status == "forgotten"
                for memory_id in real_stale_risk_ids
            ),
            "real_stale_risk_forget_rate": round(
                real_stale_forget,
                6,
            ),
            "forgotten_total": sum(
                state.status == "forgotten"
                for state in engine.states.values()
            ),
            "active_total": sum(
                state.status == "active"
                for state in engine.states.values()
            ),
            "positive_relation_count": len(
                positive_relation_events
            ),
            "positive_relation_lift_rate": round(
                relation_lift,
                6,
            ),
            "conflict_relation_count": len(
                conflict_relation_events
            ),
            "conflict_confidence_drop_rate": round(
                conflict_confidence_drop,
                6,
            ),
            "late_memory_count": len(late_memory_ids),
            "late_memory_active": sum(
                engine.states[memory_id].status == "active"
                for memory_id in late_memory_ids
            ),
            "late_positive_relation_count": len(
                late_positive_relation_events
            ),
            "late_positive_relation_lift_rate": round(
                late_relation_lift,
                6,
            ),
        },
        "confidence": {
            "text_mean": round(text_confidence, 6),
            "log_mean": round(log_confidence, 6),
            "text_log_gap": round(source_gap, 6),
            "source_control_selected": source_control_selected,
            "source_control_correct": source_choice,
        },
        "temporal_outcomes": temporal_outcomes,
        "query_trace_sample": query_trace,
        "refresh_trace": refresh_trace,
        "relation_trace_sample": (
            positive_relation_events[:20]
            + [
                event
                for event in relation_trace
                if event["relation_type"] == "conflicts"
            ][:10]
        ),
        "risk_memory_ids": {
            "recently_refreshed": refresh_ids,
            "explicit_long": long_ids,
            "stale_short": stale_candidates[:30],
            "real_stale_risk": real_stale_risk_ids[:30],
        },
    }
    return summary, engine


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--observations",
        type=Path,
        default=DEFAULT_OBSERVATIONS,
    )
    parser.add_argument(
        "--memories",
        type=Path,
        default=DEFAULT_MEMORIES,
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    initial, late, relations, fixture = build_fixture(args.memories)
    results = []
    engines = {}
    for stability_name in STABILITY_STRATEGIES:
        for confidence_name in CONFIDENCE_STRATEGIES:
            result, engine = run_combination(
                stability_name,
                confidence_name,
                observation_path=args.observations,
                initial_seeds=initial,
                late_seeds=late,
                relations=relations,
            )
            key = f"{stability_name}+{confidence_name}"
            results.append(result)
            engines[key] = engine
    results.sort(
        key=lambda item: (
            -float(item["score"]),
            str(item["stability_strategy"]),
            str(item["confidence_strategy"]),
        )
    )
    best = results[0]
    best_key = (
        f"{best['stability_strategy']}+"
        f"{best['confidence_strategy']}"
    )
    best_engine = engines[best_key]
    hard_initial = tuple(
        replace(
            seed,
            temporal_confidence=(
                1.0 if seed.temporal_label else 0.0
            ),
        )
        for seed in initial
    )
    hard_late = tuple(
        replace(
            seed,
            temporal_confidence=(
                1.0 if seed.temporal_label else 0.0
            ),
        )
        for seed in late
    )
    hard_temporal, _ = run_combination(
        str(best["stability_strategy"]),
        str(best["confidence_strategy"]),
        observation_path=args.observations,
        initial_seeds=hard_initial,
        late_seeds=hard_late,
        relations=relations,
    )
    output = {
        "purpose": (
            "Fixed lifecycle replay over prior Observation and Episode "
            "memory outputs with an adjusted time axis."
        ),
        "runtime_llm_or_embedding": False,
        "retrieval_policy": {
            "top_k_per_observation": REPLAY_TOP_K,
            "answer_independent": True,
        },
        "score_weights": {
            "selection_precision": 0.20,
            "eligible_query_hit_rate": 0.17,
            "active_refresh_survival": 0.14,
            "explicit_long_survival": 0.14,
            "controlled_stale_forgetting": 0.10,
            "real_stale_risk_forgetting": 0.08,
            "text_log_confidence_gap": 0.07,
            "positive_relation_lift": 0.06,
            "source_control_choice": 0.04,
        },
        "time_adjustment": {
            "initial_memory_window_days": [0, 30],
            "first_query_window_days": [35, 100],
            "inserted_inactivity_gap_days": [100, 240],
            "second_query_window_days": [240, 300],
            "late_memory_window_days": [305, 307.4],
            "controlled_refresh_days": [315, 350, 390],
            "final_lazy_maintenance_day": 420,
            "policy": (
                "Semantic labels are unchanged. Only event times are "
                "assigned to expose activation and forgetting behavior."
            ),
        },
        "temporal_policy": {
            "short_label_confidence": 0.20,
            "medium_label_confidence": 0.55,
            "long_label_confidence": 0.65,
            "explicit_long_term_minimum_confidence": 0.95,
            "reason": (
                "The prior temporal audit was weak and 173 of 191 "
                "memories default to short. Labels are blended with a "
                "neutral retention prior instead of acting as expiry."
            ),
        },
        "fixture": fixture,
        "comparison": results,
        "selected_combinations": [
            {
                "rank": index + 1,
                "stability_strategy": result["stability_strategy"],
                "confidence_strategy": result["confidence_strategy"],
                "score": result["score"],
            }
            for index, result in enumerate(results[:3])
        ],
        "best_combination": best_key,
        "hard_temporal_ablation": {
            "policy": (
                "Treat every temporal label as fully reliable while "
                "keeping all other inputs and algorithms unchanged."
            ),
            "blended_temporal": {
                "score": best["score"],
                "retrieval": best["retrieval"],
                "lifecycle": best["lifecycle"],
                "temporal_outcomes": best["temporal_outcomes"],
            },
            "hard_temporal": {
                "score": hard_temporal["score"],
                "retrieval": hard_temporal["retrieval"],
                "lifecycle": hard_temporal["lifecycle"],
                "temporal_outcomes": hard_temporal[
                    "temporal_outcomes"
                ],
            },
            "score_delta_hard_minus_blended": round(
                float(hard_temporal["score"])
                - float(best["score"]),
                6,
            ),
            "forgotten_delta_hard_minus_blended": (
                int(hard_temporal["lifecycle"]["forgotten_total"])
                - int(best["lifecycle"]["forgotten_total"])
            ),
        },
        "best_intermediate_states": best_engine.snapshot(_at(420)),
        "best_transitions": best_engine.transitions,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(output, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "fixture": fixture,
                "selected_combinations": output[
                    "selected_combinations"
                ],
                "comparison": [
                    {
                        "combination": (
                            f"{result['stability_strategy']}+"
                            f"{result['confidence_strategy']}"
                        ),
                        "score": result["score"],
                        "performance_ms": result["performance_ms"],
                        "retrieval": result["retrieval"],
                        "lifecycle": result["lifecycle"],
                        "confidence": result["confidence"],
                        "temporal_outcomes": result[
                            "temporal_outcomes"
                        ],
                    }
                    for result in results
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
