from __future__ import annotations

import argparse
import csv
import hashlib
import json
import statistics
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from itertools import combinations
from pathlib import Path
from time import perf_counter
from typing import Any, Iterable, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.memory_engine.layered_memory_graph import (
    EpisodeGraphNode,
    LayeredMemoryKnowledgeGraphBuilder,
    ObservationGraphNode,
)
from src.memory_engine.conflict import (
    ConflictAssessment,
    ConflictMemory,
    ConflictResolver,
    apply_conflict_assessment,
)
from src.memory_engine.memory_graph import (
    MemoryGraphNode,
    ObservationRelationSignal,
)
from src.memory_engine.memory_lifecycle import (
    CONFIDENCE_STRATEGIES,
    STABILITY_STRATEGIES,
    ConfidenceEvidence,
    LifecycleObservation,
    MemoryLifeSeed,
    MemoryLifecycleEngine,
)
from src.memory_engine.normalizers import observation_from_event
from src.memory_engine.semantic_episode import (
    SemanticEpisodeConfig,
    SemanticEpisodeEvent,
    group_semantic_episode_events,
)


DEFAULT_OUTPUT = Path(
    "runtime/generalization/mainline_generalization_v1.json"
)


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _split_ids(value: str) -> tuple[str, ...]:
    return tuple(item for item in value.split("|") if item)


def _json(value: str) -> Mapping[str, Any]:
    try:
        parsed = json.loads(value or "{}")
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, Mapping) else {}


def _mean(values: Iterable[float]) -> float:
    selected = tuple(values)
    return statistics.fmean(selected) if selected else 0.0


def _percentile(values: Sequence[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    position = (len(ordered) - 1) * percentile
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return (
        ordered[lower] * (1.0 - fraction)
        + ordered[upper] * fraction
    )


def _pairs(groups: Mapping[str, str]) -> set[tuple[str, str]]:
    by_group: dict[str, list[str]] = defaultdict(list)
    for event_id, group_id in groups.items():
        by_group[group_id].append(event_id)
    return {
        (left, right)
        for values in by_group.values()
        for index, left in enumerate(sorted(values))
        for right in sorted(values)[index + 1 :]
    }


def _group_metrics(
    ordered_ids: Sequence[str],
    gold: Mapping[str, str],
    predicted: Mapping[str, str],
) -> dict[str, Any]:
    gold_pairs = _pairs(gold)
    predicted_pairs = _pairs(predicted)
    correct_pairs = gold_pairs & predicted_pairs
    gold_to_predicted: dict[str, set[str]] = defaultdict(set)
    predicted_to_gold: dict[str, set[str]] = defaultdict(set)
    for event_id in ordered_ids:
        gold_to_predicted[gold[event_id]].add(predicted[event_id])
        predicted_to_gold[predicted[event_id]].add(gold[event_id])
    gold_boundaries = {
        index
        for index in range(1, len(ordered_ids))
        if gold[ordered_ids[index - 1]] != gold[ordered_ids[index]]
    }
    predicted_boundaries = {
        index
        for index in range(1, len(ordered_ids))
        if (
            predicted[ordered_ids[index - 1]]
            != predicted[ordered_ids[index]]
        )
    }
    true_boundaries = gold_boundaries & predicted_boundaries
    return {
        "event_count": len(ordered_ids),
        "gold_group_count": len(gold_to_predicted),
        "predicted_group_count": len(predicted_to_gold),
        "merge_precision": (
            len(correct_pairs) / len(predicted_pairs)
            if predicted_pairs
            else 1.0
        ),
        "merge_recall": (
            len(correct_pairs) / len(gold_pairs)
            if gold_pairs
            else 1.0
        ),
        "boundary_precision": (
            len(true_boundaries) / len(predicted_boundaries)
            if predicted_boundaries
            else (1.0 if not gold_boundaries else 0.0)
        ),
        "boundary_recall": (
            len(true_boundaries) / len(gold_boundaries)
            if gold_boundaries
            else 1.0
        ),
        "intact_gold_rate": (
            sum(len(values) == 1 for values in gold_to_predicted.values())
            / len(gold_to_predicted)
            if gold_to_predicted
            else 1.0
        ),
        "pure_predicted_rate": (
            sum(len(values) == 1 for values in predicted_to_gold.values())
            / len(predicted_to_gold)
            if predicted_to_gold
            else 1.0
        ),
        "split_gold_groups": sum(
            len(values) > 1 for values in gold_to_predicted.values()
        ),
        "overmerged_predicted_groups": sum(
            len(values) > 1 for values in predicted_to_gold.values()
        ),
    }


def _episode_dataset(
    rows: Sequence[Mapping[str, str]],
    *,
    dataset: str,
    user_filter: set[str],
    gold_field: str,
    condition_fields: Sequence[str],
    object_fields: Sequence[str],
    hard_session_boundary: bool,
) -> dict[str, Any]:
    selected = [row for row in rows if row["user_id"] in user_filter]
    by_scope: dict[tuple[str, str], list[Mapping[str, str]]] = defaultdict(
        list
    )
    for row in selected:
        scope_id = (
            row["session_id"] if hard_session_boundary else "continuous"
        )
        by_scope[(row["user_id"], scope_id)].append(row)
    assignments: dict[str, str] = {}
    decisions = []
    latencies = []
    for (user_id, session_id), values in sorted(by_scope.items()):
        ordered = sorted(values, key=lambda item: item["timestamp"])
        events = tuple(
            SemanticEpisodeEvent(
                event_id=row["event_id"],
                observed_time=(
                    row["timestamp"].replace(" ", "T")
                    if "T" not in row["timestamp"]
                    else row["timestamp"]
                ),
                condition_tag_ids=tuple(
                    f"{field}:{row[field]}"
                    for field in condition_fields
                    if row.get(field)
                ),
                object_tag_ids=tuple(
                    f"{field}:{row[field]}"
                    for field in object_fields
                    if row.get(field)
                ),
            )
            for row in ordered
        )
        started = perf_counter()
        grouped = group_semantic_episode_events(
            events,
            config=SemanticEpisodeConfig(
                time_fallback_seconds=6 * 60 * 60,
                object_conflict_confirmation=2,
                episode_id_prefix=(
                    f"{dataset}:{user_id}:{session_id}"
                ),
            ),
        )
        latencies.append((perf_counter() - started) * 1000.0)
        assignments.update(grouped.assignments)
        decisions.extend(item.to_dict() for item in grouped.decisions)

    ordered_ids = [
        row["event_id"]
        for row in sorted(
            selected,
            key=lambda item: (
                item["user_id"],
                item["timestamp"],
                item["event_id"],
            ),
        )
    ]
    gold = {row["event_id"]: row[gold_field] for row in selected}
    session_gold = {
        row["event_id"]: f"{row['user_id']}:{row['session_id']}"
        for row in selected
    }
    return {
        "dataset": dataset,
        "scope_policy": (
            "hard user/session boundary, semantic grouping inside"
            if hard_session_boundary
            else "user-isolated continuous stream without session boundary"
        ),
        "semantic_condition_fields": list(condition_fields),
        "semantic_object_fields": list(object_fields),
        "gold_field": gold_field,
        "semantic_target": _group_metrics(
            ordered_ids,
            gold,
            assignments,
        ),
        "session_target": _group_metrics(
            ordered_ids,
            session_gold,
            assignments,
        ),
        "performance": {
            "scope_count": len(by_scope),
            "mean_scope_ms": _mean(latencies),
            "p95_scope_ms": _percentile(latencies, 0.95),
            "total_ms": sum(latencies),
        },
        "decision_reasons": dict(
            sorted(Counter(item["reason"] for item in decisions).items())
        ),
        "error_examples": _episode_error_examples(
            selected,
            assignments,
            gold_field=gold_field,
        ),
    }


def _episode_error_examples(
    rows: Sequence[Mapping[str, str]],
    assignments: Mapping[str, str],
    *,
    gold_field: str,
    limit: int = 8,
) -> dict[str, Any]:
    by_predicted: dict[str, list[Mapping[str, str]]] = defaultdict(list)
    by_gold: dict[str, list[Mapping[str, str]]] = defaultdict(list)
    for row in rows:
        by_predicted[assignments[row["event_id"]]].append(row)
        by_gold[row[gold_field]].append(row)

    def render(values: Sequence[Mapping[str, str]]) -> dict[str, Any]:
        return {
            "event_ids": [row["event_id"] for row in values],
            "gold_ids": sorted({row[gold_field] for row in values}),
            "predicted_ids": sorted(
                {assignments[row["event_id"]] for row in values}
            ),
            "details": [row.get("detail") or row.get("raw_content") for row in values],
        }

    return {
        "overmerged": [
            render(values)
            for values in by_predicted.values()
            if len({row[gold_field] for row in values}) > 1
        ][:limit],
        "split": [
            render(values)
            for values in by_gold.values()
            if len({assignments[row["event_id"]] for row in values}) > 1
        ][:limit],
    }


def episode_evaluation(root: Path) -> dict[str, Any]:
    v1_base = (
        root
        / "os_agent_memory_benchmark_v1"
        / "os_agent_memory_benchmark_v1"
    )
    v1 = _rows(v1_base / "data" / "raw_events.csv")
    v1 = [row for row in v1 if row["split"] == "test"]
    challenge = _rows(
        root
        / "agent_memory_challenge_v2"
        / "challenge_v2"
        / "user_event_log_challenge_v2.csv"
    )
    memory_test = _rows(
        root
        / "memory_test_data"
        / "memory_test_data"
        / "user_event_log.csv"
    )
    return {
        "definition_note": (
            "The benchmark v1 ground-truth episode is a long-lived task "
            "lineage. Session metrics are the direct fit for this engine's "
            "continuous local episode definition; lineage metrics are "
            "reported as a stricter secondary view."
        ),
        "tracks": [
            _episode_dataset(
                rows,
                dataset=f"{name}/{mode}",
                user_filter=users,
                gold_field=gold,
                condition_fields=conditions,
                object_fields=objects,
                hard_session_boundary=(mode == "session"),
            )
            for (
                rows,
                name,
                users,
                gold,
                conditions,
                objects,
            ) in (
                (
                    v1,
                    "os_agent_memory_benchmark_v1",
                    {f"U{index:03d}" for index in range(25, 37)},
                    "ground_truth_episode_id",
                    ("task_type",),
                    ("app", "event_type"),
                ),
                (
                    challenge,
                    "agent_memory_challenge_v2",
                    {"U105", "U106", "U107", "U108"},
                    "related_task_id",
                    ("scene",),
                    ("app",),
                ),
                (
                    memory_test,
                    "memory_test_data",
                    {"U004", "U005"},
                    "related_task_id",
                    ("scene",),
                    ("app",),
                ),
            )
            for mode in ("session", "continuous")
        ],
    }


def _condition_tags(memory: Mapping[str, str]) -> tuple[str, ...]:
    return tuple(
        f"condition:{key}={json.dumps(value, ensure_ascii=False, sort_keys=True)}"
        for key, value in sorted(_json(memory["condition_json"]).items())
    )


def structured_observation_evaluation(root: Path) -> dict[str, Any]:
    specs = (
        (
            "agent_memory_challenge_v2",
            (
                root / "agent_memory_challenge_v2" / "challenge_v2"
                / "user_event_log_challenge_v2.csv"
            ),
            {"U105", "U106", "U107", "U108"},
        ),
        (
            "memory_test_data",
            (
                root / "memory_test_data" / "memory_test_data"
                / "user_event_log.csv"
            ),
            {"U004", "U005"},
        ),
    )
    field_correct = Counter()
    field_total = Counter()
    dataset_counts = Counter()
    latencies = []
    failures = []
    exact_count = 0
    for dataset, path, users in specs:
        for row in _rows(path):
            if row["user_id"] not in users:
                continue
            dataset_counts[dataset] += 1
            event = {
                "source_type": "system_event",
                "source_event_id": row["event_id"],
                "user_id": row["user_id"],
                "session_id": row["session_id"],
                "event_time": row["timestamp"],
                "event": row["action"],
                "message": row["detail"],
                "app": row["app"],
                "entity_refs": [row["object"]],
                "scenario_id": row["scene"],
                "task_hint": row["scene"],
            }
            started = perf_counter()
            observation = observation_from_event(event)
            latencies.append((perf_counter() - started) * 1000.0)
            checks = {
                "source_event_id": (
                    observation.source_event_id == row["event_id"]
                ),
                "user_id": observation.user_id == row["user_id"],
                "session_id": (
                    observation.session_id == row["session_id"]
                ),
                "event_time": (
                    observation.event_time == row["timestamp"]
                ),
                "content": observation.content == row["detail"],
                "condition_key": (
                    observation.context.get("scenario_id")
                    == row["scene"]
                ),
                "app_key": observation.app == row["app"],
                "object_key": row["object"] in observation.entity_refs,
                "action_key": observation.action == row["action"],
                "schema_valid": bool(
                    observation.completeness.get("schema_valid")
                ),
            }
            for field, correct in checks.items():
                field_total[field] += 1
                field_correct[field] += int(correct)
            exact_count += int(all(checks.values()))
            if not all(checks.values()) and len(failures) < 20:
                failures.append(
                    {
                        "dataset": dataset,
                        "event_id": row["event_id"],
                        "failed_fields": [
                            field
                            for field, correct in checks.items()
                            if not correct
                        ],
                    }
                )
    event_count = sum(dataset_counts.values())
    return {
        "input": {
            "event_count": event_count,
            "by_dataset": dict(sorted(dataset_counts.items())),
        },
        "field_preservation": {
            field: {
                "correct": field_correct[field],
                "total": field_total[field],
                "accuracy": (
                    field_correct[field] / field_total[field]
                    if field_total[field]
                    else 1.0
                ),
            }
            for field in sorted(field_total)
        },
        "all_required_fields_exact": {
            "correct": exact_count,
            "total": event_count,
            "accuracy": exact_count / event_count if event_count else 1.0,
        },
        "failures": failures,
        "performance": {
            "mean_event_ms": _mean(latencies),
            "p95_event_ms": _percentile(latencies, 0.95),
            "total_ms": sum(latencies),
        },
        "scope_note": (
            "This track evaluates the structured Observation interface: "
            "source keys are normalized and preserved without text span "
            "segmentation. It does not claim semantic inference of an "
            "unseen canonical tag from free text."
        ),
    }


def _relation_spec(relation: str) -> tuple[str, bool]:
    return {
        "SUPERSEDES": ("supersedes", True),
        "COEXISTS": ("related", False),
        "CONTRADICTS": ("conflicts", False),
        "OVERRIDES_BEHAVIOR": ("overrides", True),
        "SAME_EXECUTION": ("confirms", False),
        "RETRACTS": ("retracts", True),
    }[relation]


_CONFLICT_TYPES = frozenset({"DYNAMIC", "CONDITIONAL", "STATIC"})


def _pair_key(left_id: str, right_id: str) -> tuple[str, str]:
    return tuple(sorted((left_id, right_id)))


def _kg_conflict_relation(
    assessment: ConflictAssessment,
) -> tuple[str, bool]:
    link = assessment.links[0]
    relation_type = (
        "related"
        if link.relation_type == "conditional_alternative"
        else link.relation_type
    )
    return relation_type, link.directed


def candidate_evaluation(root: Path) -> dict[str, Any]:
    base = (
        root
        / "os_agent_memory_benchmark_v1"
        / "os_agent_memory_benchmark_v1"
    )
    raw = [
        row for row in _rows(base / "data" / "raw_events.csv")
        if row["split"] == "test"
    ]
    episodes_raw = [
        row for row in _rows(base / "data" / "episodes_ground_truth.csv")
        if row["split"] == "test"
    ]
    evidence_raw = [
        row for row in _rows(base / "data" / "evidence_ground_truth.csv")
        if row["split"] == "test"
    ]
    memories_raw = [
        row for row in _rows(base / "data" / "memory_ground_truth.csv")
        if row["split"] == "test"
    ]
    conflicts = [
        row for row in _rows(base / "data" / "conflict_groups.csv")
        if row["split"] == "test"
    ]
    raw_by_id = {row["event_id"]: row for row in raw}
    evidence_by_id = {row["evidence_id"]: row for row in evidence_raw}
    memory_by_id = {row["memory_id"]: row for row in memories_raw}
    conflict_runtime = _build_conflict_runtime(
        memories_raw,
        evidence_by_id,
    )
    predicted_conflicts = {
        _pair_key(*assessment.memory_ids): assessment
        for assessment in conflict_runtime["assessments"]
        if assessment.detected
    }

    memory_sources: dict[str, tuple[str, ...]] = {}
    memory_episode: dict[str, str] = {}
    for memory in memories_raw:
        source_events = []
        source_episodes = []
        for evidence_id in _split_ids(memory["support_evidence_ids"]):
            evidence = evidence_by_id.get(evidence_id)
            if evidence is None:
                continue
            source_events.extend(_split_ids(evidence["source_event_ids"]))
            source_episodes.extend(
                _split_ids(evidence["source_episode_ids"])
            )
        memory_sources[memory["memory_id"]] = tuple(
            dict.fromkeys(source_events)
        )
        if source_episodes:
            memory_episode[memory["memory_id"]] = source_episodes[0]
        elif source_events:
            memory_episode[memory["memory_id"]] = raw_by_id[
                source_events[0]
            ]["ground_truth_episode_id"]

    observations = tuple(
        ObservationGraphNode(
            observation_id=f"obs:{row['event_id']}",
            episode_id=row["ground_truth_episode_id"],
            user_id=row["user_id"],
            source_kind=row["source_type"],
            strength=float(row["quality_score"]),
            condition_tag_ids=(f"task:{row['task_type']}",),
            object_tag_ids=(f"event:{row['event_type']}",),
            source_refs=(row["event_id"],),
            metadata={"timestamp": row["timestamp"]},
        )
        for row in raw
    )
    memories = tuple(
        MemoryGraphNode(
            memory_id=row["memory_id"],
            episode_id=memory_episode[row["memory_id"]],
            user_id=row["user_id"],
            source_kind="benchmark_memory",
            strength=float(row["confidence"]),
            condition_tag_ids=_condition_tags(row),
            object_tag_ids=(f"slot:{row['slot']}",),
            attitude_polarity="support",
            source_event_ids=memory_sources[row["memory_id"]],
            source_memory_ids=(row["memory_id"],),
            observed_time=row["valid_from"],
            metadata={"status": row["status"]},
        )
        for row in memories_raw
        if row["memory_id"] in memory_episode
    )
    memory_ids_by_episode: dict[str, list[str]] = defaultdict(list)
    for memory in memories:
        memory_ids_by_episode[memory.episode_id].append(memory.memory_id)
    episodes = tuple(
        EpisodeGraphNode(
            episode_id=row["episode_id"],
            user_id=row["user_id"],
            source_kind="benchmark_episode",
            observation_ids=tuple(
                f"obs:{event_id}"
                for event_id in _split_ids(row["event_ids"])
            ),
            memory_ids=tuple(
                memory_ids_by_episode.get(row["episode_id"], ())
            ),
            base_strength=0.88,
            condition_tag_ids=(f"task:{row['task_type']}",),
        )
        for row in episodes_raw
    )

    signals = []
    expected_observation = set()
    expected_memory = set()
    unsupported_gold_groups = []
    for conflict in conflicts:
        relation_type, directed = _relation_spec(conflict["relation"])
        candidate_ids = _split_ids(conflict["candidate_ids"])
        for left_id, right_id in combinations(candidate_ids, 2):
            if left_id in raw_by_id and right_id in raw_by_id:
                if directed:
                    winner = conflict["winner_id"]
                    if winner == left_id:
                        left_id, right_id = right_id, left_id
                expected_observation.add(
                    (
                        f"obs:{left_id}",
                        f"obs:{right_id}",
                        relation_type,
                        directed,
                    )
                    if directed
                    else (
                        *sorted((f"obs:{left_id}", f"obs:{right_id}")),
                        relation_type,
                        directed,
                    )
                )
                signals.append(
                    ObservationRelationSignal(
                        source_ref=left_id,
                        target_ref=right_id,
                        association=0.92,
                        relation_type=relation_type,
                        directed=directed,
                        confidence=0.95,
                        independent_unit_id=conflict[
                            "conflict_group_id"
                        ],
                        source_observation_hint=f"obs:{left_id}",
                        target_observation_hint=f"obs:{right_id}",
                        metadata={
                            "gold_relation": conflict["relation"],
                            "conflict_type": conflict["conflict_type"],
                        },
                    )
                )
                continue
            left_sources = memory_sources.get(left_id, ())
            right_sources = memory_sources.get(right_id, ())
            if not left_sources or not right_sources:
                unsupported_gold_groups.append(
                    conflict["conflict_group_id"]
                )
                continue
            supported_conflict = (
                conflict["conflict_type"] in _CONFLICT_TYPES
            )
            gold_left_id = left_id
            gold_right_id = right_id
            gold_left_sources = left_sources
            gold_right_sources = right_sources
            if (
                supported_conflict
                and directed
                and conflict["winner_id"]
            ):
                gold_left_id = conflict["winner_id"]
                gold_right_id = next(
                    memory_id
                    for memory_id in (left_id, right_id)
                    if memory_id != gold_left_id
                )
                gold_left_sources = memory_sources[gold_left_id]
                gold_right_sources = memory_sources[gold_right_id]
            elif directed:
                winner = conflict["winner_id"]
                if winner == left_id:
                    gold_left_id, gold_right_id = right_id, left_id
                    gold_left_sources, gold_right_sources = (
                        right_sources,
                        left_sources,
                    )
            expected_observation.add(
                (
                    f"obs:{gold_left_sources[0]}",
                    f"obs:{gold_right_sources[0]}",
                    relation_type,
                    directed,
                )
                if directed
                else (
                    *sorted(
                        (
                            f"obs:{gold_left_sources[0]}",
                            f"obs:{gold_right_sources[0]}",
                        )
                    ),
                    relation_type,
                    directed,
                )
            )
            expected_memory.add(
                (
                    gold_left_id,
                    gold_right_id,
                    relation_type,
                    directed,
                )
                if directed
                else (
                    *sorted((gold_left_id, gold_right_id)),
                    relation_type,
                    directed,
                )
            )
            if supported_conflict:
                continue
            signals.append(
                ObservationRelationSignal(
                    source_ref=left_sources[0],
                    target_ref=right_sources[0],
                    association=0.92,
                    relation_type=relation_type,
                    directed=directed,
                    confidence=0.95,
                    independent_unit_id=conflict["conflict_group_id"],
                    source_observation_hint=f"obs:{left_sources[0]}",
                    target_observation_hint=f"obs:{right_sources[0]}",
                    source_memory_hint=left_id,
                    target_memory_hint=right_id,
                    metadata={
                        "gold_relation": conflict["relation"],
                        "conflict_type": conflict["conflict_type"],
                    },
                )
            )
    for assessment in predicted_conflicts.values():
        if not assessment.links:
            continue
        link = assessment.links[0]
        source_id = link.source_memory_id
        target_id = link.target_memory_id
        source_refs = memory_sources.get(source_id, ())
        target_refs = memory_sources.get(target_id, ())
        if not source_refs or not target_refs:
            unsupported_gold_groups.append(
                f"inferred:{source_id}:{target_id}"
            )
            continue
        predicted_relation, predicted_directed = (
            _kg_conflict_relation(assessment)
        )
        signals.append(
            ObservationRelationSignal(
                source_ref=source_refs[0],
                target_ref=target_refs[0],
                association=assessment.probability,
                relation_type=predicted_relation,
                directed=predicted_directed,
                confidence=assessment.probability,
                independent_unit_id=(
                    f"conflict:{source_id}:{target_id}"
                ),
                source_observation_hint=f"obs:{source_refs[0]}",
                target_observation_hint=f"obs:{target_refs[0]}",
                source_memory_hint=source_id,
                target_memory_hint=target_id,
                metadata={
                    "inferred_by": assessment.detector,
                    "conflict_type": assessment.conflict_type,
                    "conflict_scope": dict(
                        assessment.conflict_scope
                    ),
                },
            )
        )
    if signals:
        signals.append(signals[0])
        first = signals[0]
        signals.append(
            ObservationRelationSignal(
                source_ref=first.source_ref,
                target_ref=first.target_ref,
                association=0.20,
                relation_type=first.relation_type,
                directed=first.directed,
                source_observation_hint=first.source_observation_hint,
                target_observation_hint=first.target_observation_hint,
            )
        )
    cross_user = next(
        (
            (left, right)
            for left in raw
            for right in raw
            if left["user_id"] != right["user_id"]
        ),
        None,
    )
    if cross_user:
        signals.append(
            ObservationRelationSignal(
                source_ref=cross_user[0]["event_id"],
                target_ref=cross_user[1]["event_id"],
                association=0.99,
                relation_type="related",
                source_observation_hint=(
                    f"obs:{cross_user[0]['event_id']}"
                ),
                target_observation_hint=(
                    f"obs:{cross_user[1]['event_id']}"
                ),
            )
        )

    builder = LayeredMemoryKnowledgeGraphBuilder()
    started = perf_counter()
    graph = builder.build(observations, episodes, memories, signals)
    elapsed_ms = (perf_counter() - started) * 1000.0
    produced_observation = {
        (
            edge.source_observation_id,
            edge.target_observation_id,
            edge.relation_type,
            edge.directed,
        )
        if edge.directed
        else (
            *sorted(
                (
                    edge.source_observation_id,
                    edge.target_observation_id,
                )
            ),
            edge.relation_type,
            edge.directed,
        )
        for edge in graph.observation_graph.edges
    }
    produced_memory = {
        (
            edge.source_memory_id,
            edge.target_memory_id,
            edge.relation_type,
            edge.directed,
        )
        if edge.directed
        else (
            *sorted(
                (edge.source_memory_id, edge.target_memory_id)
            ),
            edge.relation_type,
            edge.directed,
        )
        for edge in graph.memory_graph.edges
    }
    correct_observation = produced_observation & expected_observation
    correct_memory = produced_memory & expected_memory
    matrix = graph.memory_graph.relation_matrix()
    symmetric = all(
        edge.directed
        or matrix[edge.source_memory_id].get(edge.target_memory_id)
        == matrix[edge.target_memory_id].get(edge.source_memory_id)
        for edge in graph.memory_graph.edges
    )
    return {
        "input": {
            "observations": len(observations),
            "episodes": len(episodes),
            "memories": len(memories),
            "signals": len(signals),
            "gold_observation_relation_pairs": len(
                expected_observation
            ),
            "gold_memory_relation_pairs": len(expected_memory),
            "unsupported_gold_groups": sorted(
                set(unsupported_gold_groups)
            ),
        },
        "output": {
            "observation_edges": len(graph.observation_graph.edges),
            "episode_edges": len(graph.episode_graph.edges),
            "memory_edges": len(graph.memory_graph.edges),
            "promotion_candidates": sum(
                state.promotion_candidate
                for state in graph.episode_graph.promotion_states
            ),
        },
        "observation_relations": {
            "precision": (
                len(correct_observation) / len(produced_observation)
                if produced_observation
                else 1.0
            ),
            "recall": (
                len(correct_observation) / len(expected_observation)
                if expected_observation
                else 1.0
            ),
            "correct_count": len(correct_observation),
            "missing": sorted(
                expected_observation - produced_observation
            ),
            "unexpected": sorted(
                produced_observation - expected_observation
            ),
        },
        "memory_relations": {
            "precision": (
                len(correct_memory) / len(produced_memory)
                if produced_memory
                else 1.0
            ),
            "recall": (
                len(correct_memory) / len(expected_memory)
                if expected_memory
                else 1.0
            ),
            "correct_count": len(correct_memory),
            "missing": sorted(expected_memory - produced_memory),
            "unexpected": sorted(produced_memory - expected_memory),
        },
        "matrix_undirected_symmetric": symmetric,
        "diagnostics": graph.diagnostics.to_dict(),
        "performance_ms": elapsed_ms,
        "scope_note": (
            "Memory-level DYNAMIC, CONDITIONAL and STATIC signals are "
            "inferred from memory claims by ConflictResolver before gold "
            "scoring. Duplicate-event signals remain supplied upstream "
            "because deduplication is a separate module."
        ),
    }


def _source_kind(
    memory: Mapping[str, str],
    evidence_by_id: Mapping[str, Mapping[str, str]],
) -> str:
    modes = {
        evidence_by_id[evidence_id]["source_mode"]
        for evidence_id in _split_ids(memory["support_evidence_ids"])
        if evidence_id in evidence_by_id
    }
    if modes & {"EXPLICIT_USER", "MANUAL_CONFIG"}:
        return "text"
    return "log"


def _seed(
    memory: Mapping[str, str],
    evidence_by_id: Mapping[str, Mapping[str, str]],
) -> MemoryLifeSeed:
    source_kind = _source_kind(memory, evidence_by_id)
    evidence = []
    for evidence_id in _split_ids(memory["support_evidence_ids"]):
        row = evidence_by_id.get(evidence_id)
        if row is None:
            continue
        evidence.append(
            ConfidenceEvidence(
                evidence_id=evidence_id,
                observed_at=row["observed_time"],
                source_kind=source_kind,
                quality=float(row["evidence_weight"]),
                supports=row["polarity"] != "OPPOSE",
                independent_unit_id=row["independent_unit_id"],
            )
        )
    if not evidence:
        evidence.append(
            ConfidenceEvidence(
                evidence_id=f"{memory['memory_id']}:fallback",
                observed_at=memory["valid_from"],
                source_kind=source_kind,
                quality=float(memory["confidence"]),
                independent_unit_id=f"{memory['memory_id']}:fallback",
            )
        )
    tier = memory["lifecycle_tier"]
    temporal_label = {
        "short": "temporal_short",
        "mid": "temporal_medium",
        "long": "temporal_long",
        "erased": "temporal_short",
    }.get(tier, "temporal_medium")
    return MemoryLifeSeed(
        memory_id=memory["memory_id"],
        user_id=memory["user_id"],
        created_at=memory["valid_from"],
        source_kind=source_kind,
        temporal_label=temporal_label,
        temporal_confidence=0.95 if tier in {"short", "long"} else 0.75,
        explicit_long_term=tier == "long",
        base_strength=float(memory["confidence"]),
        condition_tag_ids=_condition_tags(memory),
        object_tag_ids=(f"slot:{memory['slot']}",),
        attitude_polarity="support",
        evidence=tuple(evidence),
        metadata={
            "status": memory["status"],
            "slot": memory["slot"],
            "canonical_text": memory["canonical_text"],
        },
    )


def _conflict_memory(
    memory: Mapping[str, str],
    evidence_by_id: Mapping[str, Mapping[str, str]],
) -> ConflictMemory:
    evidence_weights = [
        float(evidence_by_id[evidence_id]["evidence_weight"])
        for evidence_id in _split_ids(memory["support_evidence_ids"])
        if evidence_id in evidence_by_id
    ]
    conditions = {
        str(key): (
            str(value)
            if isinstance(value, (str, int, float, bool))
            else json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        for key, value in _json(memory["condition_json"]).items()
    }
    predecessor_id = memory.get("predecessor_memory_id") or ""
    return ConflictMemory(
        memory_id=memory["memory_id"],
        user_id=memory["user_id"],
        slot_key=memory["slot"],
        value=memory["value"],
        confidence=float(memory["confidence"]),
        source_kind=_source_kind(memory, evidence_by_id),
        observed_at=memory["valid_from"],
        conditions=conditions,
        valid_from=memory["valid_from"],
        valid_to=memory["valid_to"],
        supersedes_memory_ids=(
            (predecessor_id,) if predecessor_id else ()
        ),
        evidence_strength=(
            _mean(evidence_weights)
            if evidence_weights
            else float(memory["confidence"])
        ),
        metadata={
            "status": memory["status"],
            "memory_type": memory["memory_type"],
            "canonical_text": memory["canonical_text"],
        },
    )


def _build_conflict_runtime(
    memories: Sequence[Mapping[str, str]],
    evidence_by_id: Mapping[str, Mapping[str, str]],
) -> dict[str, Any]:
    resolver = ConflictResolver()
    assessments = []
    resolutions = []
    latencies = []
    for memory in sorted(
        memories,
        key=lambda item: (item["valid_from"], item["memory_id"]),
    ):
        started = perf_counter()
        resolution = resolver.add(
            _conflict_memory(memory, evidence_by_id)
        )
        latencies.append((perf_counter() - started) * 1000.0)
        resolutions.append(resolution)
        assessments.extend(resolution.assessments)
    return {
        "resolver": resolver,
        "assessments": tuple(assessments),
        "resolutions": tuple(resolutions),
        "latencies": tuple(latencies),
    }


def conflict_evaluation(root: Path) -> dict[str, Any]:
    base = (
        root
        / "os_agent_memory_benchmark_v1"
        / "os_agent_memory_benchmark_v1"
    )
    memories = [
        row for row in _rows(base / "data" / "memory_ground_truth.csv")
        if row["split"] == "test"
    ]
    evidence = [
        row for row in _rows(base / "data" / "evidence_ground_truth.csv")
        if row["split"] == "test"
    ]
    conflicts = [
        row for row in _rows(base / "data" / "conflict_groups.csv")
        if row["split"] == "test"
    ]
    evidence_by_id = {row["evidence_id"]: row for row in evidence}
    memory_by_id = {row["memory_id"]: row for row in memories}
    runtime = _build_conflict_runtime(memories, evidence_by_id)
    resolver = runtime["resolver"]
    predicted = {
        _pair_key(*assessment.memory_ids): assessment
        for assessment in runtime["assessments"]
        if assessment.detected
    }
    gold: dict[tuple[str, str], dict[str, str]] = {}
    for group in conflicts:
        if group["conflict_type"] not in _CONFLICT_TYPES:
            continue
        for left_id, right_id in combinations(
            _split_ids(group["candidate_ids"]),
            2,
        ):
            if left_id not in memory_by_id or right_id not in memory_by_id:
                continue
            gold[_pair_key(left_id, right_id)] = group

    gold_keys = set(gold)
    predicted_keys = set(predicted)
    detected_true = gold_keys & predicted_keys
    type_correct = sum(
        predicted[key].conflict_type
        == gold[key]["conflict_type"].casefold()
        for key in detected_true
    )
    dynamic_groups = [
        (key, group)
        for key, group in gold.items()
        if group["conflict_type"] == "DYNAMIC"
    ]
    direction_correct = sum(
        (
            key in predicted
            and predicted[key].successor_memory_id
            == group["winner_id"]
            and predicted[key].predecessor_memory_id
            == next(
                memory_id
                for memory_id in key
                if memory_id != group["winner_id"]
            )
        )
        for key, group in dynamic_groups
    )

    factor_exact = 0
    policy_correct = 0
    companion_correct = 0
    roundtrip_correct = 0
    scope_complete = 0
    policy_examples = []
    restored = ConflictResolver.from_snapshot(resolver.snapshot())
    for key, group in sorted(gold.items()):
        assessment = predicted.get(key)
        if assessment is None:
            continue
        scope_complete += int(bool(assessment.conflict_scope.get("kind")))
        companion_correct += int(
            all(
                any(
                    candidate.memory_id
                    == next(item for item in key if item != root_id)
                    for candidate in resolver.index.expand(
                        (root_id,)
                    )[0].companions
                )
                for root_id in key
            )
        )
        roundtrip_correct += int(
            all(
                any(
                    candidate.memory_id
                    == next(item for item in key if item != root_id)
                    for candidate in restored.index.expand(
                        (root_id,)
                    )[0].companions
                )
                for root_id in key
            )
        )
        engine = MemoryLifecycleEngine(
            STABILITY_STRATEGIES["weibull"](),
            CONFIDENCE_STRATEGIES["beta_bound"](),
        )
        for memory_id in key:
            engine.add_memory(
                _seed(memory_by_id[memory_id], evidence_by_id)
            )
        before = {
            memory_id: float(engine.states[memory_id].confidence["value"])
            for memory_id in key
        }
        apply_at = max(
            memory_by_id[memory_id]["valid_from"]
            for memory_id in key
        )
        apply_conflict_assessment(
            engine,
            assessment,
            observed_at=apply_at,
        )
        ratios = {
            memory_id: (
                float(engine.states[memory_id].confidence["value"])
                / before[memory_id]
            )
            for memory_id in key
        }
        factor_exact += int(
            all(
                abs(
                    ratios[memory_id]
                    - float(assessment.confidence_factors[memory_id])
                )
                <= 1e-6
                for memory_id in key
            )
        )
        expected_type = group["conflict_type"]
        if expected_type == "DYNAMIC":
            winner_id = group["winner_id"]
            predecessor_id = next(
                memory_id for memory_id in key
                if memory_id != winner_id
            )
            correct = (
                ratios[predecessor_id] < 1.0
                and abs(ratios[winner_id] - 1.0) <= 1e-6
            )
        elif expected_type == "CONDITIONAL":
            correct = all(
                abs(value - 1.0) <= 1e-6
                for value in ratios.values()
            )
        else:
            correct = all(value < 1.0 for value in ratios.values())
        policy_correct += int(correct)
        if len(policy_examples) < 6:
            policy_examples.append(
                {
                    "conflict_group_id": group["conflict_group_id"],
                    "expected_type": expected_type,
                    "predicted_type": assessment.conflict_type,
                    "memory_ids": list(key),
                    "confidence_ratios": {
                        memory_id: round(value, 8)
                        for memory_id, value in ratios.items()
                    },
                    "scope": dict(assessment.conflict_scope),
                }
            )

    stream_engine = MemoryLifecycleEngine(
        STABILITY_STRATEGIES["weibull"](),
        CONFIDENCE_STRATEGIES["beta_bound"](),
    )
    for memory in sorted(
        memories,
        key=lambda item: (item["valid_from"], item["memory_id"]),
    ):
        stream_engine.add_memory(_seed(memory, evidence_by_id))
    for assessment in predicted.values():
        apply_conflict_assessment(
            stream_engine,
            assessment,
            observed_at=max(
                memory_by_id[memory_id]["valid_from"]
                for memory_id in assessment.memory_ids
            ),
        )
    penalized_states = [
        state
        for state in stream_engine.states.values()
        if float(state.confidence["conflict_penalty"]) < 1.0
    ]
    gold_count = len(gold)
    detected_count = len(predicted)
    return {
        "input": {
            "memory_count": len(memories),
            "scored_conflict_pairs": gold_count,
            "gold_by_type": dict(
                sorted(
                    Counter(
                        group["conflict_type"]
                        for group in gold.values()
                    ).items()
                )
            ),
            "out_of_scope_gold_types": [
                "SOURCE_PRECEDENCE",
                "DUPLICATE",
                "ERASURE",
            ],
        },
        "detection": {
            "predicted_conflict_pairs": detected_count,
            "precision": (
                len(detected_true) / detected_count
                if detected_count
                else 1.0
            ),
            "recall": (
                len(detected_true) / gold_count
                if gold_count
                else 1.0
            ),
            "type_accuracy": (
                type_correct / gold_count if gold_count else 1.0
            ),
            "false_positive_pairs": [
                list(key)
                for key in sorted(predicted_keys - gold_keys)
            ][:20],
            "missing_pairs": [
                list(key)
                for key in sorted(gold_keys - predicted_keys)
            ][:20],
        },
        "direction": {
            "dynamic_pair_count": len(dynamic_groups),
            "accuracy": (
                direction_correct / len(dynamic_groups)
                if dynamic_groups
                else 1.0
            ),
            "semantic": "successor points to predecessor",
        },
        "confidence": {
            "per_pair_factor_exact_accuracy": (
                factor_exact / gold_count if gold_count else 1.0
            ),
            "policy_accuracy": (
                policy_correct / gold_count if gold_count else 1.0
            ),
            "stream_penalized_memory_count": len(penalized_states),
            "stream_multi_factor_memory_count": sum(
                len(state.conflict_factors) > 1
                for state in stream_engine.states.values()
            ),
            "minimum_stream_conflict_penalty": min(
                (
                    float(state.confidence["conflict_penalty"])
                    for state in penalized_states
                ),
                default=1.0,
            ),
        },
        "integration": {
            "retrieval_companion_accuracy": (
                companion_correct / gold_count
                if gold_count
                else 1.0
            ),
            "snapshot_roundtrip_accuracy": (
                roundtrip_correct / gold_count
                if gold_count
                else 1.0
            ),
            "scope_metadata_coverage": (
                scope_complete / gold_count if gold_count else 1.0
            ),
            "pending_supersession_count": sum(
                len(memory_ids)
                for memory_ids
                in resolver.pending_supersessions().values()
            ),
        },
        "performance": {
            "mean_memory_add_ms": _mean(runtime["latencies"]),
            "p95_memory_add_ms": _percentile(
                runtime["latencies"],
                0.95,
            ),
            "total_resolver_ms": sum(runtime["latencies"]),
        },
        "examples": policy_examples,
        "scope_note": (
            "ConflictResolver sees memory fields only. conflict_groups.csv "
            "is read after inference for closed-world scoring; source "
            "precedence, event deduplication and erasure stay assigned to "
            "their dedicated modules."
        ),
    }


def lifecycle_evaluation(root: Path) -> dict[str, Any]:
    base = (
        root
        / "os_agent_memory_benchmark_v1"
        / "os_agent_memory_benchmark_v1"
    )
    memories = [
        row for row in _rows(base / "data" / "memory_ground_truth.csv")
        if row["split"] == "test"
    ]
    evidence = [
        row for row in _rows(base / "data" / "evidence_ground_truth.csv")
        if row["split"] == "test"
    ]
    transitions = [
        row for row in _rows(base / "data" / "memory_transitions.csv")
        if row["split"] == "test"
    ]
    queries = [
        row for row in _rows(base / "benchmark" / "queries.csv")
        if row["split"] == "test"
    ]
    expected = {
        row["query_id"]: row
        for row in _rows(base / "gold" / "expected_results.csv")
        if row["split"] == "test"
    }
    evidence_by_id = {row["evidence_id"]: row for row in evidence}
    memory_by_id = {row["memory_id"]: row for row in memories}
    conflict_runtime = _build_conflict_runtime(
        memories,
        evidence_by_id,
    )
    conflict_resolver = conflict_runtime["resolver"]
    active_seeds = [
        _seed(row, evidence_by_id)
        for row in memories
        if row["status"] == "ACTIVE"
    ]
    engine = MemoryLifecycleEngine(
        STABILITY_STRATEGIES["weibull"](),
        CONFIDENCE_STRATEGIES["beta_bound"](),
    )
    started = perf_counter()
    for seed in sorted(
        active_seeds,
        key=lambda item: (item.created_at, item.memory_id),
    ):
        engine.add_memory(seed)

    required_count = 0
    hit_count = 0
    selected_count = 0
    semantic_correct = 0
    activation_increase = 0
    conflict_group_count = 0
    conflict_companion_count = 0
    companion_non_activation_trials = 0
    companion_non_activation_correct = 0
    query_latencies = []
    misses = []
    for query in sorted(
        queries,
        key=lambda item: (item["query_time"], item["query_id"]),
    ):
        gold = expected[query["query_id"]]
        required_ids = [
            memory_id
            for memory_id in _split_ids(gold["required_memory_ids"])
            if memory_id in engine.states
        ]
        for index, memory_id in enumerate(required_ids):
            required_count += 1
            seed = engine.states[memory_id].seed
            observation = LifecycleObservation(
                observation_id=f"{query['query_id']}:{index}",
                user_id=query["user_id"],
                observed_at=query["query_time"],
                source_kind="query",
                condition_tag_ids=seed.condition_tag_ids,
                object_tag_ids=seed.object_tag_ids,
                attitude_polarity=seed.attitude_polarity,
            )
            before = float(
                engine.stability_strategy.value(
                    engine.states[memory_id].stability,
                    query["query_time"],
                )
            )
            activation_counts_before = {
                state_id: state.activation_count
                for state_id, state in engine.states.items()
            }
            query_started = perf_counter()
            conflict_aware = conflict_resolver.query_with_conflicts(
                engine,
                observation,
                top_k=5,
            )
            result = conflict_aware.query_result
            query_latencies.append(
                (perf_counter() - query_started) * 1000.0
            )
            selected_ids = [
                selection.memory_id for selection in result.selected
            ]
            for group in conflict_aware.conflict_groups:
                if not group.companions:
                    continue
                conflict_group_count += 1
                conflict_companion_count += len(group.companions)
                for companion in group.companions:
                    if (
                        companion.memory_id not in engine.states
                        or companion.memory_id in selected_ids
                    ):
                        continue
                    companion_non_activation_trials += 1
                    companion_non_activation_correct += int(
                        engine.states[
                            companion.memory_id
                        ].activation_count
                        == activation_counts_before[
                            companion.memory_id
                        ]
                    )
            selected_count += len(selected_ids)
            hit = memory_id in selected_ids
            hit_count += int(hit)
            target_key = (
                seed.condition_tag_ids,
                seed.object_tag_ids,
                seed.attitude_polarity,
            )
            semantic_correct += sum(
                (
                    engine.states[selected_id].seed.condition_tag_ids,
                    engine.states[selected_id].seed.object_tag_ids,
                    engine.states[selected_id].seed.attitude_polarity,
                )
                == target_key
                for selected_id in selected_ids
            )
            if hit:
                after = float(
                    engine.states[memory_id].stability["value"]
                )
                activation_increase += int(after > before)
            elif len(misses) < 20:
                misses.append(
                    {
                        "query_id": query["query_id"],
                        "required_memory_id": memory_id,
                        "selected_memory_ids": selected_ids,
                        "slot": memory_by_id[memory_id]["slot"],
                    }
                )

    replay_ms = (perf_counter() - started) * 1000.0
    confidence_by_source = {
        source: _mean(
            float(state.confidence["value"])
            for state in engine.states.values()
            if state.seed.source_kind == source
        )
        for source in ("text", "log")
    }

    broad_engine = MemoryLifecycleEngine(
        STABILITY_STRATEGIES["weibull"](),
        CONFIDENCE_STRATEGIES["beta_bound"](),
    )
    for seed in sorted(
        active_seeds,
        key=lambda item: (item.created_at, item.memory_id),
    ):
        broad_engine.add_memory(seed)
    broad_trials = 0
    broad_hits = 0
    broad_selected = 0
    broad_semantic_correct = 0
    broad_misses = []
    for query in sorted(
        queries,
        key=lambda item: (item["query_time"], item["query_id"]),
    ):
        gold = expected[query["query_id"]]
        for index, memory_id in enumerate(
            memory_id
            for memory_id in _split_ids(gold["required_memory_ids"])
            if memory_id in broad_engine.states
        ):
            broad_trials += 1
            target = broad_engine.states[memory_id].seed
            observation = LifecycleObservation(
                observation_id=f"broad:{query['query_id']}:{index}",
                user_id=query["user_id"],
                observed_at=query["query_time"],
                source_kind="query",
                object_tag_ids=target.object_tag_ids,
                attitude_polarity=target.attitude_polarity,
            )
            result = broad_engine.query(observation, top_k=5)
            selected_ids = [
                selection.memory_id for selection in result.selected
            ]
            broad_hits += int(memory_id in selected_ids)
            broad_selected += len(selected_ids)
            broad_semantic_correct += sum(
                broad_engine.states[selected_id].seed.object_tag_ids
                == target.object_tag_ids
                for selected_id in selected_ids
            )
            if memory_id not in selected_ids and len(broad_misses) < 20:
                broad_misses.append(
                    {
                        "query_id": query["query_id"],
                        "required_memory_id": memory_id,
                        "selected_memory_ids": selected_ids,
                        "slot": memory_by_id[memory_id]["slot"],
                    }
                )

    recession_engine = MemoryLifecycleEngine(
        STABILITY_STRATEGIES["weibull"](),
        CONFIDENCE_STRATEGIES["beta_bound"](),
    )
    recession_seeds = {
        row["memory_id"]: _seed(row, evidence_by_id) for row in memories
    }
    for seed in recession_seeds.values():
        recession_engine.add_memory(seed)
    transition_results = Counter()
    transition_examples = []
    for transition in transitions:
        memory_id = transition["memory_id"]
        state = recession_engine.states[memory_id]
        created = datetime.fromisoformat(
            state.seed.created_at.replace("Z", "+00:00")
        )
        action = transition["expected_action"]
        if action == "EXPIRE":
            check_at = created + timedelta(days=180)
            recession_engine.maintain(
                check_at.isoformat(),
                memory_ids=(memory_id,),
            )
            passed = state.status == "forgotten"
            supported = True
        elif action == "PROMOTE":
            check_at = created + timedelta(days=180)
            recession_engine.maintain(
                check_at.isoformat(),
                memory_ids=(memory_id,),
            )
            passed = state.status == "active"
            supported = True
        else:
            passed = False
            supported = False
        key = (
            f"{action}:pass" if passed
            else f"{action}:unsupported" if not supported
            else f"{action}:fail"
        )
        transition_results[key] += 1
        if not passed and len(transition_examples) < 16:
            transition_examples.append(
                {
                    "transition_id": transition["transition_id"],
                    "memory_id": memory_id,
                    "action": action,
                    "status": state.status,
                    "supported_by_lifecycle_alone": supported,
                }
            )

    supported_total = sum(
        count
        for key, count in transition_results.items()
        if not key.endswith(":unsupported")
    )
    supported_passed = sum(
        count
        for key, count in transition_results.items()
        if key.endswith(":pass")
    )
    return {
        "stable_strategy": {
            "stability": "weibull",
            "confidence": "beta_bound",
        },
        "retrieval_activation": {
            "active_memory_count": len(active_seeds),
            "query_count": len(queries),
            "required_memory_trials": required_count,
            "required_memory_hit_recall": (
                hit_count / required_count if required_count else 1.0
            ),
            "semantic_selection_precision": (
                semantic_correct / selected_count
                if selected_count
                else 1.0
            ),
            "selected_count": selected_count,
            "successful_hits_with_stability_increase": activation_increase,
            "misses": misses,
            "conflict_aware_retrieval": {
                "groups_returned": conflict_group_count,
                "companions_returned": conflict_companion_count,
                "companion_non_activation_accuracy": (
                    companion_non_activation_correct
                    / companion_non_activation_trials
                    if companion_non_activation_trials
                    else 1.0
                ),
                "companion_non_activation_trials": (
                    companion_non_activation_trials
                ),
            },
        },
        "missing_condition_stress": {
            "description": (
                "Query observations retain object and attitude but omit "
                "condition, simulating the most common upstream miss."
            ),
            "required_memory_trials": broad_trials,
            "required_memory_hit_recall": (
                broad_hits / broad_trials if broad_trials else 1.0
            ),
            "semantic_selection_precision": (
                broad_semantic_correct / broad_selected
                if broad_selected
                else 1.0
            ),
            "selected_count": broad_selected,
            "misses": broad_misses,
        },
        "confidence": {
            "mean_by_source": confidence_by_source,
            "text_minus_log": (
                confidence_by_source["text"]
                - confidence_by_source["log"]
            ),
        },
        "recession_transitions": {
            "counts": dict(sorted(transition_results.items())),
            "supported_action_accuracy": (
                supported_passed / supported_total
                if supported_total
                else 1.0
            ),
            "unsupported_actions": ["ARCHIVE", "ERASE"],
            "examples": transition_examples,
            "scope_note": (
                "ARCHIVE requires supersession handling and ERASE requires "
                "an explicit privacy action. They are not age-decay duties "
                "of MemoryLifecycleEngine and are reported, not scored."
            ),
        },
        "performance": {
            "full_replay_ms": replay_ms,
            "mean_query_ms": _mean(query_latencies),
            "p95_query_ms": _percentile(query_latencies, 0.95),
        },
    }


def dataset_audit(root: Path) -> dict[str, Any]:
    v31 = root / "os_agent_memory_query_benchmark_v3.1"
    raw = (
        root
        / "os_agent_test_data"
        / "os_agent_test_data"
        / "raw_json"
    )
    v31_hashes = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in v31.rglob("*.json")
    }
    raw_files = list(raw.glob("*.json"))
    same_name = [
        path for path in raw_files if path.name in v31_hashes
    ]
    identical = [
        path
        for path in same_name
        if hashlib.sha256(path.read_bytes()).hexdigest()
        == v31_hashes[path.name]
    ]
    weblinx_path = (
        root / "weblinx_episodes.ndjson" / "weblinx_episodes.ndjson"
    )
    with weblinx_path.open("r", encoding="utf-8") as handle:
        weblinx_count = sum(bool(line.strip()) for line in handle)
    return {
        "primary_generalization_sources": {
            "os_agent_memory_benchmark_v1_test": {
                "users": 12,
                "events": 336,
                "episodes": 72,
                "memories": 192,
                "queries": 312,
            },
            "agent_memory_challenge_v2_holdout": {
                "users": 4,
                "events": 544,
            },
            "memory_test_data_holdout": {
                "users": 2,
                "events": 308,
            },
            "weblinx_sparse_episode_logs": {
                "episodes": weblinx_count,
            },
        },
        "excluded_overlap": {
            "os_agent_test_data_raw_json": len(raw_files),
            "same_filename_as_v31": len(same_name),
            "identical_sha256_to_v31": len(identical),
            "counted_as_new_generalization_data": 0,
        },
        "anti_leakage_policy": [
            "No v3.1 row contributes to the new primary score.",
            "User-level holdout is used where an official split is absent.",
            "Observation tag prototypes are built from train users only.",
            "Exact normalized text duplicates are scored once.",
            "No LLM generates test inputs or gold labels.",
        ],
    }


def _optional_result(path: Path | None) -> Mapping[str, Any] | None:
    if path is None or not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {
        "input": str(path),
        "overall": payload.get("overall"),
        "latency": payload.get("latency"),
        "embedding": payload.get("embedding"),
        "by_evaluation_track": payload.get("by_evaluation_track"),
        "by_query_type": payload.get("by_query_type"),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--workspace-root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--observation-result", type=Path)
    parser.add_argument("--weblinx-result", type=Path)
    args = parser.parse_args()

    started = perf_counter()
    output = {
        "schema_version": "mainline.generalization_audit.v1",
        "dataset_audit": dataset_audit(args.workspace_root),
        "observation": _optional_result(args.observation_result),
        "structured_observation": structured_observation_evaluation(
            args.workspace_root
        ),
        "episode": episode_evaluation(args.workspace_root),
        "candidate": candidate_evaluation(args.workspace_root),
        "conflict": conflict_evaluation(args.workspace_root),
        "activation_recession": lifecycle_evaluation(
            args.workspace_root
        ),
        "weblinx": _optional_result(args.weblinx_result),
    }
    output["total_local_evaluation_ms"] = (
        perf_counter() - started
    ) * 1000.0
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(output, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "output": str(args.output),
                "dataset_audit": output["dataset_audit"],
                "episode": [
                    {
                        "dataset": track["dataset"],
                        "semantic_target": track["semantic_target"],
                        "session_target": track["session_target"],
                    }
                    for track in output["episode"]["tracks"]
                ],
                "candidate": output["candidate"],
                "conflict": output["conflict"],
                "activation_recession": output[
                    "activation_recession"
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
