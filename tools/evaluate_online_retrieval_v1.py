from __future__ import annotations

import argparse
import csv
import hashlib
import json
import statistics
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from src.memory_engine.conflict import (
    ConflictMemory,
    ConflictResolver,
    apply_conflict_assessment,
)
from src.memory_engine.memory_lifecycle import (
    CONFIDENCE_STRATEGIES,
    STABILITY_STRATEGIES,
    ConfidenceEvidence,
    LifecycleObservation,
    MemoryLifeSeed,
    MemoryLifecycleEngine,
)
from src.memory_engine.normalizers import dialogue_adapter
from src.memory_engine.observation import ObservationBudget, ObservationMatcher
from src.memory_engine.preference_matching import (
    CanonicalTag,
    PreferenceObservationOptions,
)
from src.memory_engine.security import is_engine_safe
from src.memory_engine.span_matching import JiebaSpanTokenizer
from tools.evaluate_kylin_os_agent_observations_v31 import (
    _grade_case,
    _prediction,
    _summarize,
)


DEFAULT_OBSERVATIONS = Path(
    "tests/data/os_agent_observation_benchmark_v31.json"
)
DEFAULT_SOURCE_ROOT = (
    Path(__file__).resolve().parents[2]
    / "os_agent_memory_query_benchmark_v3.1"
    / "os_agent_memory_query_benchmark_v3.1_20260725"
)
DEFAULT_OUTPUT = Path(
    "runtime/results/online_retrieval_v1/"
    "online_retrieval_v1.json"
)
DEFAULT_KYLIN_SDK_LIBRARY = Path(
    "/usr/lib/x86_64-linux-gnu/libkysdk-coreai-embedding.so.1"
)
TEMPORAL_LABELS = (
    "temporal_short",
    "temporal_medium",
    "temporal_long",
)
ONLINE_BUDGET_MS = {
    "input_safety": 5.0,
    "normalization_and_context": 5.0,
    "observation": 480.0,
    "memory_query": 5.0,
    "output_safety_and_packaging": 5.0,
    "scheduler_reserve": 0.0,
    "total": 500.0,
}
RETRIEVAL_HARD_STOP_MS = 800.0
RECALL_EXPANSION_MIN_FORMATION_SIMILARITY = 0.50
RECALL_EXPANSION_MAX_RESIDUAL_MARGIN = 0.16
RECALL_EXPANSION_SCORE_FACTOR = 0.72
RECALL_EXPANSION_TOP_K_PER_CONDITION = 5


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _sdk_fingerprint(backend: Any, library: Path) -> dict[str, Any]:
    try:
        resolved = library.resolve(strict=True)
    except OSError:
        raise RuntimeError(
            f"required Kylin embedding SDK library is unavailable: {library}"
        ) from None
    return {
        "backend": "kylin_coreai_embedding",
        "fallback_used": False,
        "library_path": str(resolved),
        "library_sha256": _sha256_file(resolved),
        "model_name": str(getattr(backend, "_model_name", "unknown")),
        "dimension": int(getattr(backend, "dim", 0)),
    }


def _split_ids(value: str) -> tuple[str, ...]:
    return tuple(item for item in value.split("|") if item)


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


def _latency_summary(
    values: Sequence[float],
    *,
    budget_ms: float,
) -> dict[str, float | int]:
    return {
        "mean_ms": statistics.mean(values) if values else 0.0,
        "median_ms": statistics.median(values) if values else 0.0,
        "p95_ms": _percentile(values, 0.95),
        "p99_ms": _percentile(values, 0.99),
        "max_ms": max(values, default=0.0),
        "within_budget_count": sum(
            value <= budget_ms for value in values
        ),
        "within_budget_rate": (
            sum(value <= budget_ms for value in values) / len(values)
            if values
            else 1.0
        ),
        "total": len(values),
        "budget_ms": budget_ms,
    }


def _tags(dataset: Mapping[str, Any]) -> tuple[CanonicalTag, ...]:
    values = [
        *dataset["tag_catalog"]["conditions"],
        *dataset["tag_catalog"]["objects"],
    ]
    return tuple(
        CanonicalTag(
            tag_id=value["tag_id"],
            name=value["name"],
            groups=tuple(value["groups"]),
            aliases=tuple(value["aliases"]),
            prototypes=tuple(value["prototypes"]),
        )
        for value in values
    )


def _attitude_direction(value: float) -> str:
    if value >= 0.10:
        return "positive"
    if value <= -0.10:
        return "negative"
    return "uncertain"


def _memory_temporal(memory_id: str) -> tuple[str, float, bool]:
    prefix = memory_id.split("_", 1)[0].upper()
    if prefix == "LTM":
        return "temporal_long", 0.95, True
    if prefix == "MTM":
        return "temporal_medium", 0.80, False
    return "temporal_short", 0.75, False


def _event_gold_by_task(
    dataset: Mapping[str, Any],
) -> dict[str, Mapping[str, Any]]:
    return {
        case["id"].removeprefix("event:"): case["gold_observations"][0]
        for case in dataset["cases"]
        if case["source_kind"] == "event"
    }


def _tag_maps(
    dataset: Mapping[str, Any],
) -> tuple[dict[str, str], tuple[str, ...]]:
    conditions = {
        value["name"]: value["tag_id"]
        for value in dataset["tag_catalog"]["conditions"]
    }
    objects = tuple(
        value["tag_id"]
        for value in dataset["tag_catalog"]["objects"]
    )
    return conditions, objects


@dataclass(frozen=True)
class RetrievalRuntime:
    engine: MemoryLifecycleEngine
    conflicts: ConflictResolver
    memory_payloads: Mapping[str, Mapping[str, Any]]
    condition_tag_ids: tuple[str, ...]
    object_tag_ids: tuple[str, ...]
    detected_conflict_count: int


def build_runtime(
    memory_rows: Sequence[Mapping[str, str]],
    dataset: Mapping[str, Any],
) -> RetrievalRuntime:
    by_task = _event_gold_by_task(dataset)
    engine = MemoryLifecycleEngine(
        STABILITY_STRATEGIES["weibull"](),
        CONFIDENCE_STRATEGIES["beta_bound"](),
        minimum_match=0.35,
        minimum_selection_score=0.20,
        secondary_selection_ratio=0.0,
    )
    conflicts = ConflictResolver()
    payloads: dict[str, Mapping[str, Any]] = {}
    condition_ids = set()
    object_ids = set()
    detected_conflicts = 0

    for memory in sorted(
        memory_rows,
        key=lambda value: (
            value["first_supported_at"],
            value["memory_id"],
        ),
    ):
        gold = by_task[memory["source_task_id"]]
        condition_id = str(gold["condition_tag_id"] or "")
        object_id = str(gold["object_tag_id"])
        temporal, temporal_confidence, explicit_long = _memory_temporal(
            memory["memory_id"]
        )
        quality = max(
            0.50,
            min(
                1.0,
                float(memory.get("support_consistency") or 0.90),
            ),
        )
        evidence = ConfidenceEvidence(
            evidence_id=f"{memory['memory_id']}:source",
            observed_at=memory["first_supported_at"],
            source_kind="text",
            quality=quality,
            independent_unit_id=memory["source_task_id"],
        )
        seed = MemoryLifeSeed(
            memory_id=memory["memory_id"],
            user_id=memory["user_id"],
            created_at=memory["first_supported_at"],
            source_kind="text",
            temporal_label=temporal,
            temporal_confidence=temporal_confidence,
            explicit_long_term=explicit_long,
            base_strength=quality,
            condition_tag_ids=(condition_id,) if condition_id else (),
            object_tag_ids=(object_id,),
            attitude_polarity="positive",
            evidence=(evidence,),
            metadata={
                "summary": memory["memory_summary"],
                "expected_action": memory["expected_action"],
                "source_task_id": memory["source_task_id"],
            },
        )
        engine.add_memory(seed)
        resolution = conflicts.add(
            ConflictMemory(
                memory_id=memory["memory_id"],
                user_id=memory["user_id"],
                slot_key=condition_id or object_id,
                value=object_id,
                confidence=quality,
                source_kind="text",
                observed_at=memory["first_supported_at"],
                conditions=(
                    {"condition_tag_id": condition_id}
                    if condition_id
                    else {}
                ),
                condition_tag_ids=(
                    (condition_id,) if condition_id else ()
                ),
                valid_from=memory["first_supported_at"],
                evidence_strength=quality,
                metadata={
                    "summary": memory["memory_summary"],
                    "expected_action": memory["expected_action"],
                },
            )
        )
        for assessment in resolution.conflicts:
            detected_conflicts += 1
            apply_conflict_assessment(
                engine,
                assessment,
                observed_at=memory["first_supported_at"],
            )
        payloads[memory["memory_id"]] = {
            "memory_id": memory["memory_id"],
            "summary": memory["memory_summary"],
            "expected_action": memory["expected_action"],
            "condition_tag_id": condition_id or None,
            "object_tag_id": object_id,
        }
        if condition_id:
            condition_ids.add(condition_id)
        object_ids.add(object_id)

    object_ids.add("object:ambiguous_prior_workflow")
    return RetrievalRuntime(
        engine=engine,
        conflicts=conflicts,
        memory_payloads=payloads,
        condition_tag_ids=tuple(sorted(condition_ids)),
        object_tag_ids=tuple(sorted(object_ids)),
        detected_conflict_count=detected_conflicts,
    )


def _context_conditions(
    query: Mapping[str, str],
    contexts: Mapping[str, Mapping[str, str]],
    condition_by_document: Mapping[str, str],
) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            condition_by_document[document]
            for context_id in _split_ids(query["current_context_ids"])
            if context_id in contexts
            for document in (contexts[context_id]["active_document"],)
            if document in condition_by_document
        )
    )


def _query_time(
    query: Mapping[str, str],
    contexts: Mapping[str, Mapping[str, str]],
) -> str:
    values = [
        contexts[context_id]["query_time"]
        for context_id in _split_ids(query["current_context_ids"])
        if context_id in contexts
    ]
    return max(values) if values else "2026-07-25T10:00:00+08:00"


def _deduplicated_frames(
    result: Any,
    context_conditions: Sequence[str],
) -> tuple[dict[str, Any], ...]:
    fallback = (
        context_conditions[0]
        if len(context_conditions) == 1
        else None
    )
    values = {}
    for frame in result.frames:
        condition_id = (
            frame.condition.tag_id
            if frame.condition is not None
            else fallback
        )
        value = {
            "condition_tag_id": condition_id,
            "object_tag_id": frame.object.tag_id,
            "attitude_direction": _attitude_direction(
                frame.attitude.value
            ),
            "confidence": frame.confidence,
        }
        key = (
            value["condition_tag_id"],
            value["object_tag_id"],
            value["attitude_direction"],
        )
        previous = values.get(key)
        if (
            previous is None
            or value["confidence"] > previous["confidence"]
        ):
            values[key] = value
    return tuple(
        sorted(
            values.values(),
            key=lambda value: (
                -value["confidence"],
                value["condition_tag_id"] or "",
                value["object_tag_id"],
            ),
        )
    )


def _recall_expansion_conditions(
    frame_result: Any,
    context_conditions: Sequence[str],
    mentioned_context_conditions: Sequence[str] = (),
) -> tuple[str, ...]:
    """Admit a condition-only retrieval path after semantic intent checks."""

    conditions = tuple(dict.fromkeys(context_conditions))
    if not conditions:
        return ()
    if (
        len(conditions) > 1
        and not frame_result.frames
        and not mentioned_context_conditions
    ):
        return ()
    diagnostics = frame_result.diagnostics
    ambiguity = diagnostics.get("ambiguity_guard") or {}
    if ambiguity.get("activated"):
        return ()
    accepted_concrete_frame = any(
        frame.object.tag_id != "object:ambiguous_prior_workflow"
        for frame in getattr(frame_result, "frames", ())
    )
    full = diagnostics.get("full_text_formation_gate")
    if not full and not accepted_concrete_frame:
        return ()
    if not accepted_concrete_frame:
        if (
            float(full["formation_similarity"])
            < RECALL_EXPANSION_MIN_FORMATION_SIMILARITY
        ):
            return ()
        if (
            float(full["residual_margin"])
            > RECALL_EXPANSION_MAX_RESIDUAL_MARGIN
        ):
            return ()
    assembled = diagnostics.get("assembled_frames") or ()
    assembled_objects = {
        value.get("object_tag_id")
        for value in assembled
        if value.get("object_tag_id")
    }
    if assembled_objects == {"object:ambiguous_prior_workflow"}:
        return ()
    return conditions


def _deadline_expansion_conditions(
    matcher: ObservationMatcher,
    text: str,
    context_conditions: Sequence[str],
    budget: ObservationBudget,
) -> tuple[str, ...]:
    """Recover explicit multi-condition tasks cut short by the hard stop."""

    if not budget.hard_stop_reached:
        return ()
    allowed = set(context_conditions)
    mentioned = tuple(
        dict.fromkeys(
            mention.tag_id
            for mention in matcher.registry.find_mentions(text)
            if mention.tag_id in allowed
        )
    )
    return mentioned if len(mentioned) >= 2 else ()


def retrieve_once(
    *,
    matcher: ObservationMatcher,
    runtime: RetrievalRuntime,
    query: Mapping[str, str],
    contexts: Mapping[str, Mapping[str, str]],
    condition_by_document: Mapping[str, str],
    observation_case: Mapping[str, Any],
    pass_name: str,
) -> dict[str, Any]:
    total_started = time.perf_counter()
    stages: dict[str, float] = {}
    text = query["query_text"]

    started = time.perf_counter()
    input_safe = is_engine_safe(text)
    stages["input_safety"] = (time.perf_counter() - started) * 1000.0
    if not input_safe:
        stages.update(
            {
                "normalization_and_context": 0.0,
                "observation": 0.0,
                "memory_query": 0.0,
                "output_safety_and_packaging": 0.0,
            }
        )
        stages["total"] = (time.perf_counter() - total_started) * 1000.0
        return {
            "query_id": query["query_id"],
            "pass": pass_name,
            "status": "blocked_input",
            "stages_ms": stages,
            "predicted_observations": [],
            "selected_memory_ids": [],
            "conflict_companion_ids": [],
            "response": None,
            "embedding_requested_delta": 0,
            "embedding_computed_delta": 0,
        }

    started = time.perf_counter()
    context_conditions = _context_conditions(
        query,
        contexts,
        condition_by_document,
    )
    observation = dialogue_adapter(
        {
            "source_event_id": f"retrieval:{query['query_id']}",
            "user_id": "benchmark_user_01",
            "session_id": "online-retrieval-v1",
            "event_time": _query_time(query, contexts),
            "content": text,
            "context": {
                "current_context_ids": list(
                    _split_ids(query["current_context_ids"])
                ),
                "condition_tag_ids": list(context_conditions),
            },
        }
    )
    options = PreferenceObservationOptions(
        condition_tag_ids=(
            context_conditions or runtime.condition_tag_ids
        ),
        object_tag_ids=runtime.object_tag_ids,
        temporal_labels=TEMPORAL_LABELS,
    )
    stages["normalization_and_context"] = (
        time.perf_counter() - started
    ) * 1000.0

    requested_before = matcher.embedder.requested
    computed_before = matcher.embedder.computed
    started = time.perf_counter()
    observation_budget = ObservationBudget(
        started_at=total_started,
        soft_limit_ms=ONLINE_BUDGET_MS["total"],
        hard_limit_ms=RETRIEVAL_HARD_STOP_MS,
    )
    frame_result = matcher.match(
        observation.content,
        options=options,
        budget=observation_budget,
    )
    frames = _deduplicated_frames(
        frame_result,
        context_conditions,
    )
    canonical_mentions = matcher.registry.find_mentions(
        observation.content
    )
    mentioned_context_conditions = tuple(
        dict.fromkeys(
            mention.tag_id
            for mention in canonical_mentions
            if mention.tag_id in set(context_conditions)
        )
    )
    explicit_ambiguous_object = any(
        mention.tag_id == "object:ambiguous_prior_workflow"
        for mention in canonical_mentions
    ) and not any(
        mention.tag_id.startswith("object:")
        and mention.tag_id != "object:ambiguous_prior_workflow"
        for mention in canonical_mentions
    )
    if explicit_ambiguous_object:
        frames = ()
    semantic_expansion_conditions = _recall_expansion_conditions(
        frame_result,
        context_conditions,
        mentioned_context_conditions,
    )
    if explicit_ambiguous_object:
        semantic_expansion_conditions = ()
    deadline_expansion_conditions = _deadline_expansion_conditions(
        matcher,
        observation.content,
        context_conditions,
        observation_budget,
    )
    if explicit_ambiguous_object:
        deadline_expansion_conditions = ()
    recall_expansion_conditions = tuple(
        dict.fromkeys(
            (
                *semantic_expansion_conditions,
                *deadline_expansion_conditions,
            )
        )
    )
    stages["observation"] = (time.perf_counter() - started) * 1000.0

    started = time.perf_counter()
    selected: dict[str, Mapping[str, Any]] = {}
    companions: dict[str, Mapping[str, Any]] = {}
    for index, frame in enumerate(frames):
        lifecycle_observation = LifecycleObservation(
            observation_id=(
                f"retrieval:{query['query_id']}:frame:{index}"
            ),
            user_id="benchmark_user_01",
            observed_at=observation.event_time,
            source_kind="query",
            condition_tag_ids=(
                (frame["condition_tag_id"],)
                if frame["condition_tag_id"]
                else ()
            ),
            object_tag_ids=(frame["object_tag_id"],),
            attitude_polarity=frame["attitude_direction"],
        )
        conflict_aware = runtime.conflicts.query_with_conflicts(
            runtime.engine,
            lifecycle_observation,
            top_k=1,
        )
        for item in conflict_aware.query_result.selected:
            previous = selected.get(item.memory_id)
            payload = {
                **item.to_dict(),
                **runtime.memory_payloads[item.memory_id],
                "retrieval_path": "exact_frame",
            }
            if (
                previous is None
                or payload["retrieval_score"]
                > previous["retrieval_score"]
            ):
                selected[item.memory_id] = payload
        for group in conflict_aware.conflict_groups:
            for companion in group.companions:
                companions.setdefault(
                    companion.memory_id,
                    {
                        **companion.to_dict(),
                        **runtime.memory_payloads[
                            companion.memory_id
                        ],
                        "root_memory_id": group.root_memory_id,
                    },
                )
    for index, condition_id in enumerate(
        recall_expansion_conditions
    ):
        partial_observation = LifecycleObservation(
            observation_id=(
                f"retrieval:{query['query_id']}:condition:{index}"
            ),
            user_id="benchmark_user_01",
            observed_at=observation.event_time,
            source_kind="query",
            condition_tag_ids=(condition_id,),
            object_tag_ids=(),
            attitude_polarity=None,
        )
        conflict_aware = runtime.conflicts.query_with_conflicts(
            runtime.engine,
            partial_observation,
            top_k=RECALL_EXPANSION_TOP_K_PER_CONDITION,
        )
        for item in conflict_aware.query_result.selected:
            if item.memory_id in companions:
                continue
            raw_score = float(item.retrieval_score)
            payload = {
                **item.to_dict(),
                **runtime.memory_payloads[item.memory_id],
                "candidate_retrieval_score": raw_score,
                "retrieval_score": (
                    raw_score * RECALL_EXPANSION_SCORE_FACTOR
                ),
                "retrieval_path": (
                    "condition_deadline_partial"
                    if condition_id in deadline_expansion_conditions
                    and condition_id
                    not in semantic_expansion_conditions
                    else "condition_partial"
                ),
            }
            previous = selected.get(item.memory_id)
            if (
                previous is None
                or payload["retrieval_score"]
                > previous["retrieval_score"]
            ):
                selected[item.memory_id] = payload
        for group in conflict_aware.conflict_groups:
            for companion in group.companions:
                companions.setdefault(
                    companion.memory_id,
                    {
                        **companion.to_dict(),
                        **runtime.memory_payloads[
                            companion.memory_id
                        ],
                        "root_memory_id": group.root_memory_id,
                    },
                )
    selected_values = sorted(
        selected.values(),
        key=lambda value: (
            -float(value["retrieval_score"]),
            value["memory_id"],
        ),
    )[:5]
    companion_values = sorted(
        (
            value
            for memory_id, value in companions.items()
            if memory_id not in selected
        ),
        key=lambda value: (
            -float(value["probability"]),
            value["memory_id"],
        ),
    )
    stages["memory_query"] = (time.perf_counter() - started) * 1000.0

    started = time.perf_counter()
    response = {
        "query_id": query["query_id"],
        "memories": selected_values,
        "conflict_companions": companion_values,
    }
    serialized = json.dumps(
        response,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    output_safe = is_engine_safe(serialized)
    if not output_safe:
        response = {
            "query_id": query["query_id"],
            "memories": [],
            "conflict_companions": [],
            "blocked": "unsafe_retrieval_output",
        }
    stages["output_safety_and_packaging"] = (
        time.perf_counter() - started
    ) * 1000.0
    stages["total"] = (time.perf_counter() - total_started) * 1000.0

    predictions = [_prediction(frame) for frame in frame_result.frames]
    return {
        "query_id": query["query_id"],
        "pass": pass_name,
        "status": "ok" if output_safe else "blocked_output",
        "evaluation_track": query["evaluation_track"],
        "query_type": query["query_type"],
        "dataset_partition": query["dataset_partition"],
        "stages_ms": stages,
        "embedding_requested_delta": (
            matcher.embedder.requested - requested_before
        ),
        "embedding_computed_delta": (
            matcher.embedder.computed - computed_before
        ),
        "context_condition_tag_ids": list(context_conditions),
        "mentioned_context_condition_tag_ids": list(
            mentioned_context_conditions
        ),
        "frame_count": len(frames),
        "recall_expansion_condition_tag_ids": list(
            recall_expansion_conditions
        ),
        "deadline_expansion_condition_tag_ids": list(
            deadline_expansion_conditions
        ),
        "observation_budget": frame_result.diagnostics.get(
            "observation_budget",
            {"enabled": False},
        ),
        "predicted_observations": predictions,
        "observation_grade": _grade_case(
            observation_case["gold_observations"],
            predictions,
        ),
        "required_memory_ids": list(
            _split_ids(query["required_memory_ids"])
        ),
        "forbidden_memory_ids": list(
            _split_ids(query["forbidden_memory_ids"])
        ),
        "selected_memory_ids": [
            value["memory_id"] for value in selected_values
        ],
        "conflict_companion_ids": [
            value["memory_id"] for value in companion_values
        ],
        "response": response,
    }


def _quality_summary(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    required_total = sum(
        len(row["required_memory_ids"]) for row in rows
    )
    required_hits = sum(
        memory_id in row["selected_memory_ids"]
        for row in rows
        for memory_id in row["required_memory_ids"]
    )
    selected_total = sum(
        len(row["selected_memory_ids"]) for row in rows
    )
    selected_correct = sum(
        memory_id in row["required_memory_ids"]
        for row in rows
        for memory_id in row["selected_memory_ids"]
    )
    answerable = [
        row for row in rows if row["required_memory_ids"]
    ]
    clarification = [
        row for row in rows if not row["required_memory_ids"]
    ]
    forbidden_total = sum(
        len(row["forbidden_memory_ids"]) for row in rows
    )
    forbidden_primary = sum(
        memory_id in row["selected_memory_ids"]
        for row in rows
        for memory_id in row["forbidden_memory_ids"]
    )
    forbidden_companions = sum(
        memory_id in row["conflict_companion_ids"]
        for row in rows
        for memory_id in row["forbidden_memory_ids"]
    )
    return {
        "query_count": len(rows),
        "required_memory_count": required_total,
        "required_memory_hit_count": required_hits,
        "required_memory_hit_recall": (
            required_hits / required_total
            if required_total
            else 1.0
        ),
        "selected_memory_count": selected_total,
        "selected_memory_precision": (
            selected_correct / selected_total
            if selected_total
            else 1.0
        ),
        "answerable_query_count": len(answerable),
        "all_required_query_success_rate": (
            sum(
                set(row["required_memory_ids"])
                <= set(row["selected_memory_ids"])
                for row in answerable
            )
            / len(answerable)
            if answerable
            else 1.0
        ),
        "clarification_query_count": len(clarification),
        "clarification_abstention_rate": (
            sum(not row["selected_memory_ids"] for row in clarification)
            / len(clarification)
            if clarification
            else 1.0
        ),
        "forbidden_memory_count": forbidden_total,
        "forbidden_primary_selection_count": forbidden_primary,
        "forbidden_primary_selection_rate": (
            forbidden_primary / forbidden_total
            if forbidden_total
            else 0.0
        ),
        "forbidden_conflict_companion_count": forbidden_companions,
        "observation": _summarize(
            [{"grade": row["observation_grade"]} for row in rows]
        ),
    }


def _pass_summary(
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    stage_summaries = {
        stage: _latency_summary(
            [float(row["stages_ms"][stage]) for row in rows],
            budget_ms=ONLINE_BUDGET_MS[stage],
        )
        for stage in (
            "input_safety",
            "normalization_and_context",
            "observation",
            "memory_query",
            "output_safety_and_packaging",
            "total",
        )
    }
    return {
        "latency": stage_summaries,
        "embedding": {
            "requested": sum(
                int(row["embedding_requested_delta"]) for row in rows
            ),
            "computed": sum(
                int(row["embedding_computed_delta"]) for row in rows
            ),
        },
        "quality": _quality_summary(rows),
        "by_evaluation_track": {
            value: _quality_summary(
                [
                    row for row in rows
                    if row["evaluation_track"] == value
                ]
            )
            for value in sorted(
                {row["evaluation_track"] for row in rows}
            )
        },
        "by_query_type": {
            value: _quality_summary(
                [
                    row for row in rows
                    if row["query_type"] == value
                ]
            )
            for value in sorted({row["query_type"] for row in rows})
        },
        "by_dataset_partition": {
            value: _quality_summary(
                [
                    row for row in rows
                    if row["dataset_partition"] == value
                ]
            )
            for value in sorted(
                {row["dataset_partition"] for row in rows}
            )
        },
    }


def run_pass(
    *,
    pass_name: str,
    matcher: ObservationMatcher,
    runtime_factory: Callable[[], RetrievalRuntime],
    queries: Sequence[Mapping[str, str]],
    contexts: Mapping[str, Mapping[str, str]],
    condition_by_document: Mapping[str, str],
    observation_cases: Mapping[str, Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], RetrievalRuntime]:
    runtime = runtime_factory()
    rows = [
        retrieve_once(
            matcher=matcher,
            runtime=runtime,
            query=query,
            contexts=contexts,
            condition_by_document=condition_by_document,
            observation_case=observation_cases[query["query_id"]],
            pass_name=pass_name,
        )
        for query in queries
    ]
    return rows, runtime


def _unsafe_probes(
    *,
    matcher: ObservationMatcher,
    runtime_factory: Callable[[], RetrievalRuntime],
    observation_case: Mapping[str, Any],
) -> dict[str, Any]:
    runtime = runtime_factory()
    contexts: dict[str, Mapping[str, str]] = {}
    values = (
        "api_key=sk-123456789012345678901234567890",
        "token=abcdefghijklmnopqrstuvwxyz1234567890",
        "normal request\u202eto hide direction",
    )
    rows = []
    for index, text in enumerate(values):
        query = {
            "query_id": f"unsafe-{index}",
            "query_text": text,
            "current_context_ids": "",
            "evaluation_track": "safety",
            "query_type": "unsafe_probe",
            "dataset_partition": "synthetic",
            "required_memory_ids": "",
            "forbidden_memory_ids": "",
        }
        rows.append(
            retrieve_once(
                matcher=matcher,
                runtime=runtime,
                query=query,
                contexts=contexts,
                condition_by_document={},
                observation_case=observation_case,
                pass_name="safety",
            )
        )
    return {
        "probe_count": len(rows),
        "blocked_count": sum(
            row["status"] == "blocked_input" for row in rows
        ),
        "all_blocked": all(
            row["status"] == "blocked_input" for row in rows
        ),
        "latency": _latency_summary(
            [float(row["stages_ms"]["total"]) for row in rows],
            budget_ms=ONLINE_BUDGET_MS["input_safety"],
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--observations",
        type=Path,
        default=DEFAULT_OBSERVATIONS,
    )
    parser.add_argument(
        "--source-root",
        type=Path,
        default=DEFAULT_SOURCE_ROOT,
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--limit", type=int)
    parser.add_argument(
        "--sdk-library",
        type=Path,
        default=DEFAULT_KYLIN_SDK_LIBRARY,
        help="real libkysdk-coreai-embedding shared library to fingerprint",
    )
    parser.add_argument(
        "--skip-warm",
        action="store_true",
    )
    args = parser.parse_args()

    try:
        from src.rag.kylin_embedding_sdk import KylinTextEmbedding
    except (ImportError, OSError) as exc:
        raise SystemExit(
            "formal online retrieval requires the real Kylin embedding SDK; "
            f"no fallback is permitted ({type(exc).__name__})"
        ) from exc

    dataset = json.loads(args.observations.read_text(encoding="utf-8"))
    data_root = args.source_root / "processed_data"
    queries = _read_csv(data_root / "query_set.csv")
    if args.limit is not None:
        queries = queries[: args.limit]
    memories = _read_csv(data_root / "memory_records.csv")
    contexts = {
        value["context_id"]: value
        for value in _read_csv(data_root / "context_set.csv")
    }
    observation_cases = {
        case["id"].removeprefix("query:"): case
        for case in dataset["cases"]
        if case["source_kind"] == "query"
    }
    condition_by_document, _ = _tag_maps(dataset)
    runtime_factory = lambda: build_runtime(memories, dataset)

    initialized = time.perf_counter()
    embedding_backend = KylinTextEmbedding()
    sdk_fingerprint = _sdk_fingerprint(
        embedding_backend,
        args.sdk_library,
    )
    matcher = ObservationMatcher(
        embedding_backend,
        tokenizer=JiebaSpanTokenizer(),
        tags=_tags(dataset),
        min_frame_confidence=0.82,
    )
    initialization_ms = (time.perf_counter() - initialized) * 1000.0

    cold_rows, cold_runtime = run_pass(
        pass_name="cold_novel_input",
        matcher=matcher,
        runtime_factory=runtime_factory,
        queries=queries,
        contexts=contexts,
        condition_by_document=condition_by_document,
        observation_cases=observation_cases,
    )
    warm_rows = []
    if not args.skip_warm:
        warm_rows, _ = run_pass(
            pass_name="warm_identical_replay",
            matcher=matcher,
            runtime_factory=runtime_factory,
            queries=queries,
            contexts=contexts,
            condition_by_document=condition_by_document,
            observation_cases=observation_cases,
        )
    safety = _unsafe_probes(
        matcher=matcher,
        runtime_factory=runtime_factory,
        observation_case=next(iter(observation_cases.values())),
    )

    output = {
        "purpose": (
            "End-to-end online Retrieval: safety, normalization/context, "
            "Observation, lifecycle/conflict query, output safety/package."
        ),
        "runtime_contract": {
            "online_budget_ms": ONLINE_BUDGET_MS,
            "retrieval_hard_stop_ms": RETRIEVAL_HARD_STOP_MS,
            "adaptive_observation_policy": (
                "full before 500 ms; selective from 500-605 ms; strict "
                "from 605-710 ms; finalize-only until the 800 ms hard stop"
            ),
            "initialization_excluded": True,
            "initialization_ms": initialization_ms,
            "embedding_sdk": sdk_fingerprint,
            "memory_count": len(memories),
            "query_count": len(queries),
            "options_policy": (
                "condition tags from visible active documents; all object "
                "tags from active memory, without required-memory leakage"
            ),
            "top_k_per_frame": 1,
            "recall_expansion": {
                "mode": "condition_only_after_intent_gate",
                "min_formation_similarity": (
                    RECALL_EXPANSION_MIN_FORMATION_SIMILARITY
                ),
                "max_residual_margin": (
                    RECALL_EXPANSION_MAX_RESIDUAL_MARGIN
                ),
                "score_factor": RECALL_EXPANSION_SCORE_FACTOR,
                "top_k_per_condition": (
                    RECALL_EXPANSION_TOP_K_PER_CONDITION
                ),
            },
            "max_primary_memories": 5,
            "detected_conflict_count": (
                cold_runtime.detected_conflict_count
            ),
        },
        "cold": _pass_summary(cold_rows),
        "warm": _pass_summary(warm_rows) if warm_rows else None,
        "safety_probes": safety,
        "cases": {
            "cold": cold_rows,
            "warm": warm_rows,
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(output, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "output": str(args.output),
                "contract": output["runtime_contract"],
                "cold": {
                    "latency": output["cold"]["latency"],
                    "embedding": output["cold"]["embedding"],
                    "quality": {
                        key: value
                        for key, value
                        in output["cold"]["quality"].items()
                        if key != "observation"
                    },
                },
                "warm": (
                    {
                        "latency": output["warm"]["latency"],
                        "embedding": output["warm"]["embedding"],
                        "quality": {
                            key: value
                            for key, value
                            in output["warm"]["quality"].items()
                            if key != "observation"
                        },
                    }
                    if output["warm"]
                    else None
                ),
                "safety": safety,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
