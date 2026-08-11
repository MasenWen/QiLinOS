from __future__ import annotations

import argparse
import json
import statistics
import time
from collections import defaultdict
from dataclasses import asdict
from pathlib import Path
from typing import Any, Mapping, Sequence

from src.memory_engine.observation import ObservationMatcher
from src.memory_engine.preference_matching import (
    CanonicalTag,
    PreferenceObservationOptions,
)
from src.memory_engine.span_matching import JiebaSpanTokenizer


DEFAULT_CASES = Path(
    "tests/data/os_agent_observation_benchmark_v31.json"
)
DEFAULT_OUTPUT = Path(
    "runtime/results/kylin_os_agent_observations_v31/"
    "kylin_os_agent_observations.json"
)
ROLES = ("condition", "object", "attitude", "temporal")
ROLE_WEIGHTS = {
    "condition": 0.25,
    "object": 0.30,
    "attitude": 0.20,
    "temporal": 0.15,
}
TEMPORAL_SCALE = {
    "temporal_short": 0.0,
    "temporal_medium": 0.5,
    "temporal_long": 1.0,
}
CHINESE_PUNCTUATION = frozenset(
    "，。；：！？、…—～·（）【】〔〕［］｛｝《》〈〉「」『』“”‘’"
)


def _chinese_punctuation_as_spaces(text: str) -> str:
    if not any("\u3400" <= character <= "\u9fff" for character in text):
        return text
    transformed = "".join(
        " " if character in CHINESE_PUNCTUATION else character
        for character in text
    )
    return " ".join(transformed.split())


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


def _direction(value: float) -> str:
    if value >= 0.10:
        return "positive"
    if value <= -0.10:
        return "negative"
    return "uncertain"


def _prediction(frame: Any) -> dict[str, Any]:
    return {
        "condition_tag_id": (
            frame.condition.tag_id if frame.condition else None
        ),
        "condition_text": (
            frame.condition.text if frame.condition else None
        ),
        "object_tag_id": frame.object.tag_id,
        "object_text": frame.object.text,
        "attitude_direction": _direction(frame.attitude.value),
        "attitude_value": frame.attitude.value,
        "attitude_text": frame.attitude.text,
        "temporal_label": (
            frame.temporal.label if frame.temporal else None
        ),
        "temporal_text": (
            frame.temporal.text if frame.temporal else None
        ),
        "confidence": frame.confidence,
        "source_start": frame.source_start,
        "source_end": frame.source_end,
    }


def _temporal_credit(
    acceptable: Sequence[str],
    predicted: str | None,
) -> float:
    if not acceptable:
        return 1.0 if predicted is None else 0.0
    if predicted is None or predicted not in TEMPORAL_SCALE:
        return 0.0
    distances = [
        abs(TEMPORAL_SCALE[predicted] - TEMPORAL_SCALE[label])
        for label in acceptable
        if label in TEMPORAL_SCALE
    ]
    if not distances:
        return 0.0
    distance = min(distances)
    if distance == 0.0:
        return 1.0
    if distance <= 0.5:
        return 0.70
    return 0.15


def _role_credit(
    role: str,
    gold: Mapping[str, Any],
    predicted: Mapping[str, Any],
) -> float:
    if role == "condition":
        return float(
            predicted["condition_tag_id"]
            == gold["condition_tag_id"]
        )
    if role == "object":
        return float(
            predicted["object_tag_id"] == gold["object_tag_id"]
        )
    if role == "attitude":
        return float(
            predicted["attitude_direction"]
            == gold["attitude_direction"]
        )
    return _temporal_credit(
        tuple(gold["temporal_labels"]),
        predicted["temporal_label"],
    )


def _role_correct(
    role: str,
    gold: Mapping[str, Any],
    predicted: Mapping[str, Any],
) -> bool:
    return _role_credit(role, gold, predicted) == 1.0


def _pair_value(
    gold: Mapping[str, Any],
    predicted: Mapping[str, Any],
) -> tuple[int, int, float, float]:
    credits = {
        role: _role_credit(role, gold, predicted)
        for role in ROLES
    }
    return (
        int(credits["object"] == 1.0),
        int(credits["condition"] == 1.0),
        sum(credits.values()),
        float(predicted["confidence"]),
    )


def _match(
    gold: Sequence[Mapping[str, Any]],
    predicted: Sequence[Mapping[str, Any]],
) -> tuple[
    list[tuple[int, int]],
    list[int],
    list[int],
]:
    candidates = [
        (_pair_value(gold_value, predicted_value), gold_index, pred_index)
        for gold_index, gold_value in enumerate(gold)
        for pred_index, predicted_value in enumerate(predicted)
    ]
    used_gold = set()
    used_predicted = set()
    matched = []
    for value, gold_index, pred_index in sorted(
        candidates,
        key=lambda item: (
            -item[0][0],
            -item[0][1],
            -item[0][2],
            -item[0][3],
            item[1],
            item[2],
        ),
    ):
        if gold_index in used_gold or pred_index in used_predicted:
            continue
        if value[:3] == (0, 0, 0):
            continue
        matched.append((gold_index, pred_index))
        used_gold.add(gold_index)
        used_predicted.add(pred_index)
    return (
        matched,
        [
            index for index in range(len(gold))
            if index not in used_gold
        ],
        [
            index for index in range(len(predicted))
            if index not in used_predicted
        ],
    )


def _blank_role_counts() -> dict[str, dict[str, float | int]]:
    return {
        role: {"correct": 0, "credit": 0.0, "total": 0}
        for role in ROLES
    }


def _grade_case(
    gold: Sequence[Mapping[str, Any]],
    predicted: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    matched, unmatched_gold, unmatched_predicted = _match(
        gold,
        predicted,
    )
    all_counts = _blank_role_counts()
    extractable_counts = _blank_role_counts()
    prediction_counts = _blank_role_counts()
    exact = 0
    rows = []
    by_gold = {gold_index: pred_index for gold_index, pred_index in matched}
    for gold_index, gold_value in enumerate(gold):
        pred_index = by_gold.get(gold_index)
        predicted_value = (
            predicted[pred_index] if pred_index is not None else None
        )
        role_values = {}
        role_credits = {}
        for role in ROLES:
            credit = (
                _role_credit(role, gold_value, predicted_value)
                if predicted_value is not None
                else 0.0
            )
            correct = (
                credit == 1.0
            )
            role_values[role] = correct
            role_credits[role] = credit
            all_counts[role]["total"] += 1
            all_counts[role]["correct"] += int(correct)
            all_counts[role]["credit"] += credit
            support = gold_value["support"][role]
            if support != "implicit":
                extractable_counts[role]["total"] += 1
                extractable_counts[role]["correct"] += int(correct)
                extractable_counts[role]["credit"] += credit
        is_exact = all(role_values.values())
        exact += int(is_exact)
        rows.append(
            {
                "gold_index": gold_index,
                "predicted_index": pred_index,
                "roles": role_values,
                "role_credit": role_credits,
                "exact": is_exact,
            }
        )
    for role in ROLES:
        prediction_counts[role]["total"] = len(predicted)
    for gold_index, pred_index in matched:
        for role in ROLES:
            credit = _role_credit(
                role,
                gold[gold_index],
                predicted[pred_index],
            )
            prediction_counts[role]["credit"] += credit
            prediction_counts[role]["correct"] += int(credit == 1.0)
    return {
        "all_role_counts": all_counts,
        "extractable_role_counts": extractable_counts,
        "prediction_role_counts": prediction_counts,
        "exact_observations": exact,
        "gold_observations": len(gold),
        "predicted_observations": len(predicted),
        "matched_observations": len(matched),
        "unmatched_gold": unmatched_gold,
        "extra_predictions": unmatched_predicted,
        "pairs": rows,
        "null_false_fill": sum(
            1
            for gold_index, pred_index in matched
            for role, field in (
                ("condition", "condition_tag_id"),
                ("temporal", "temporal_label"),
            )
            if gold[gold_index]["support"][role] == "null"
            and predicted[pred_index][field] is not None
        ),
    }


def _merge_counts(
    target: dict[str, dict[str, float | int]],
    source: Mapping[str, Mapping[str, float | int]],
) -> None:
    for role in ROLES:
        target[role]["correct"] += source[role]["correct"]
        target[role]["credit"] += source[role]["credit"]
        target[role]["total"] += source[role]["total"]


def _accuracy(count: Mapping[str, float | int]) -> float:
    return (
        count["credit"] / count["total"]
        if count["total"]
        else 1.0
    )


def _exact_accuracy(count: Mapping[str, float | int]) -> float:
    return (
        count["correct"] / count["total"]
        if count["total"]
        else 1.0
    )


def _summarize(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    all_counts = _blank_role_counts()
    extractable_counts = _blank_role_counts()
    prediction_counts = _blank_role_counts()
    exact = 0
    gold_count = 0
    predicted_count = 0
    matched_count = 0
    null_false_fill = 0
    case_exact = 0
    for row in rows:
        grade = row["grade"]
        _merge_counts(all_counts, grade["all_role_counts"])
        _merge_counts(
            extractable_counts,
            grade["extractable_role_counts"],
        )
        _merge_counts(
            prediction_counts,
            grade["prediction_role_counts"],
        )
        exact += grade["exact_observations"]
        gold_count += grade["gold_observations"]
        predicted_count += grade["predicted_observations"]
        matched_count += grade["matched_observations"]
        null_false_fill += grade["null_false_fill"]
        case_exact += int(
            grade["exact_observations"]
            == grade["gold_observations"]
            and not grade["extra_predictions"]
        )
    explicit_accuracies = {
        role: _accuracy(extractable_counts[role])
        for role in ROLES
    }
    all_accuracies = {
        role: _accuracy(all_counts[role])
        for role in ROLES
    }
    prediction_accuracies = {
        role: _accuracy(prediction_counts[role])
        for role in ROLES
    }
    exact_recall = exact / gold_count if gold_count else 1.0
    prediction_precision = (
        matched_count / predicted_count if predicted_count else 1.0
    )
    observation_formation_recall = (
        matched_count / gold_count if gold_count else 1.0
    )
    formed_weighted_quality = (
        10.0
        * sum(
            ROLE_WEIGHTS[role] * prediction_accuracies[role]
            for role in ROLES
        )
        / sum(ROLE_WEIGHTS.values())
        if predicted_count
        else 0.0
    )
    cases_with_frames = sum(
        row["grade"]["predicted_observations"] > 0 for row in rows
    )
    explicit_score = 10.0 * (
        sum(
            ROLE_WEIGHTS[role] * explicit_accuracies[role]
            for role in ROLES
        )
        + 0.05 * exact_recall
        + 0.05 * prediction_precision
    )
    all_score = 10.0 * (
        sum(
            ROLE_WEIGHTS[role] * all_accuracies[role]
            for role in ROLES
        )
        + 0.05 * exact_recall
        + 0.05 * prediction_precision
    )
    return {
        "case_count": len(rows),
        "gold_observation_count": gold_count,
        "predicted_observation_count": predicted_count,
        "matched_observation_count": matched_count,
        "role_accuracy_extractable": {
            role: {
                **extractable_counts[role],
                "accuracy": explicit_accuracies[role],
                "exact_accuracy": _exact_accuracy(
                    extractable_counts[role]
                ),
            }
            for role in ROLES
        },
        "role_accuracy_all": {
            role: {
                **all_counts[role],
                "accuracy": all_accuracies[role],
                "exact_accuracy": _exact_accuracy(all_counts[role]),
            }
            for role in ROLES
        },
        "prediction_role_precision": {
            role: {
                **prediction_counts[role],
                "accuracy": prediction_accuracies[role],
                "exact_accuracy": _exact_accuracy(
                    prediction_counts[role]
                ),
            }
            for role in ROLES
        },
        "case_formation_rate": (
            cases_with_frames / len(rows) if rows else 1.0
        ),
        "observation_formation_recall": observation_formation_recall,
        "abstention_rate": (
            1.0 - cases_with_frames / len(rows) if rows else 0.0
        ),
        "formed_weighted_quality_10": formed_weighted_quality,
        "exact_observation_recall": exact_recall,
        "exact_observation_precision": (
            exact / predicted_count if predicted_count else 1.0
        ),
        "prediction_precision": prediction_precision,
        "case_exact_rate": case_exact / len(rows) if rows else 1.0,
        "null_false_fill": null_false_fill,
        "score_extractable_10": explicit_score,
        "score_all_10": all_score,
    }


def _breakdowns(
    rows: Sequence[Mapping[str, Any]],
    key: str,
) -> dict[str, Any]:
    groups: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[str(row[key])].append(row)
    return {
        name: _summarize(values)
        for name, values in sorted(groups.items())
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


def main() -> None:
    try:
        from src.rag.kylin_embedding_sdk import KylinTextEmbedding
    except ImportError:
        from tools.evaluate_kylin_embedding_preference_object_blind import (
            KylinTextEmbedding,
        )

    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--limit", type=int)
    parser.add_argument(
        "--chinese-punctuation-as-space",
        action="store_true",
        help=(
            "Replace Chinese punctuation with spaces in Chinese-containing "
            "inputs while preserving ASCII identifier punctuation."
        ),
    )
    parser.add_argument(
        "--min-frame-confidence",
        type=float,
        default=0.82,
    )
    parser.add_argument(
        "--condition-context-fallback",
        action="store_true",
        help=(
            "Use ObservationMatcher's stable multiview condition-context "
            "fallback when a formed frame has no condition."
        ),
    )
    parser.add_argument(
        "--condition-fallback-min-similarity",
        type=float,
        default=0.72,
    )
    parser.add_argument(
        "--condition-fallback-min-margin",
        type=float,
        default=0.04,
    )
    args = parser.parse_args()
    dataset = json.loads(args.cases.read_text(encoding="utf-8"))
    end = (
        args.offset + args.limit
        if args.limit is not None
        else None
    )
    source_cases = dataset["cases"][args.offset:end]
    cases = []
    for source_case in source_cases:
        source_text = source_case["text"]
        text = (
            _chinese_punctuation_as_spaces(source_text)
            if args.chinese_punctuation_as_space
            else source_text
        )
        cases.append(
            {
                **source_case,
                "text": text,
                "_original_text": source_text,
            }
        )

    initialization_started = time.perf_counter()
    matcher = ObservationMatcher(
        KylinTextEmbedding(),
        tokenizer=JiebaSpanTokenizer(),
        tags=_tags(dataset),
        min_frame_confidence=args.min_frame_confidence,
    )
    initialization_ms = (
        time.perf_counter() - initialization_started
    ) * 1000.0

    rows = []
    for index, case in enumerate(cases, 1):
        options = case["options"]
        started = time.perf_counter()
        result = matcher.match(
            case["text"],
            options=PreferenceObservationOptions(
                condition_tag_ids=tuple(
                    options["condition_tag_ids"]
                ),
                object_tag_ids=tuple(options["object_tag_ids"]),
                temporal_labels=tuple(options["temporal_labels"]),
            ),
        )
        condition_fallback = None
        if (
            args.condition_context_fallback
            and result.frames
            and any(frame.condition is None for frame in result.frames)
        ):
            fallback_results = matcher.match_condition_contexts(
                case["text"],
                options=PreferenceObservationOptions(
                    condition_tag_ids=tuple(
                        options["condition_tag_ids"]
                    ),
                    object_tag_ids=tuple(
                        options["object_tag_ids"]
                    ),
                    temporal_labels=tuple(
                        options["temporal_labels"]
                    ),
                ),
                multiview=True,
                top_k_per_context=5,
                include_below_threshold=True,
            )
            candidates = [
                (match, fallback.context)
                for fallback in fallback_results
                for match in fallback.result.canonical_matches
                if (
                    match.group == "condition"
                    and match.similarity
                    >= args.condition_fallback_min_similarity
                    and match.competition_margin
                    >= args.condition_fallback_min_margin
                )
            ]
            if candidates:
                condition_fallback = max(
                    candidates,
                    key=lambda item: (
                        item[0].exact_alias,
                        item[0].similarity,
                        item[0].competition_margin,
                        item[0].score,
                    ),
                )
        latency_ms = (time.perf_counter() - started) * 1000.0
        predicted = [_prediction(frame) for frame in result.frames]
        if condition_fallback is not None:
            condition_match, condition_context = condition_fallback
            for value in predicted:
                if value["condition_tag_id"] is None:
                    value["condition_tag_id"] = condition_match.tag_id
                    value["condition_text"] = condition_context.text
        grade = _grade_case(case["gold_observations"], predicted)
        rows.append(
            {
                "id": case["id"],
                "source_kind": case["source_kind"],
                "evaluation_track": case["evaluation_track"],
                "query_type": case["query_type"],
                "original_text": case["_original_text"],
                "text": case["text"],
                "gold_observations": case["gold_observations"],
                "predicted_observations": predicted,
                "grade": grade,
                "latency_ms": latency_ms,
                "embedding_requested_delta": result.diagnostics[
                    "embedding_requested_delta"
                ],
                "embedding_computed_delta": result.diagnostics[
                    "embedding_computed_delta"
                ],
                "proposed_candidate_count": result.diagnostics[
                    "proposed_candidate_count"
                ],
                "temporal_structural_pruned_count": (
                    result.diagnostics[
                        "temporal_structural_pruned_count"
                    ]
                ),
                "embedding_candidate_count": result.diagnostics[
                    "embedding_candidate_count"
                ],
                "greedy_candidates": result.diagnostics[
                    "greedy_candidates"
                ],
                "dominant_language": result.diagnostics[
                    "dominant_language"
                ],
                "language_atoms": result.diagnostics[
                    "language_atoms"
                ],
                "soft_ranges": result.diagnostics["soft_ranges"],
                "command_attitude_fallbacks": result.diagnostics[
                    "command_attitude_fallbacks"
                ],
                "canonical_matches": [
                    asdict(value)
                    for value in result.canonical_matches
                ],
                "condition_fallback": (
                    {
                        "tag_id": condition_fallback[0].tag_id,
                        "tag_name": condition_fallback[0].tag_name,
                        "text": condition_fallback[1].text,
                        "similarity": condition_fallback[0].similarity,
                        "competition_margin": (
                            condition_fallback[0].competition_margin
                        ),
                    }
                    if condition_fallback is not None
                    else None
                ),
            }
        )
        if index % 100 == 0:
            print(f"processed={index}/{len(cases)}")

    latencies = [float(row["latency_ms"]) for row in rows]
    output = {
        "purpose": (
            "Observation-only evaluation over OS Agent benchmark v3.1. "
            "No retrieval answer or dataset decision label is evaluated."
        ),
        "uses_llm_at_runtime": False,
        "input_transform": {
            "name": (
                "chinese_punctuation_as_space"
                if args.chinese_punctuation_as_space
                else "none"
            ),
            "transformed_case_count": sum(
                case["text"] != case["_original_text"]
                for case in cases
            ),
            "preserves_ascii_identifier_punctuation": True,
        },
        "annotation_policy": dataset["annotation_policy"],
        "annotation_audit": dataset["audit"],
        "temporal_scoring": {
            "scale": TEMPORAL_SCALE,
            "exact_credit": 1.0,
            "adjacent_credit": 0.70,
            "short_long_credit": 0.15,
            "null_mismatch_credit": 0.0,
        },
        "min_frame_confidence": args.min_frame_confidence,
        "condition_context_fallback": {
            "enabled": args.condition_context_fallback,
            "minimum_similarity": (
                args.condition_fallback_min_similarity
            ),
            "minimum_competition_margin": (
                args.condition_fallback_min_margin
            ),
            "used_case_count": sum(
                row["condition_fallback"] is not None for row in rows
            ),
        },
        "initialization_ms": initialization_ms,
        "latency": {
            "mean_ms": statistics.fmean(latencies) if latencies else 0.0,
            "median_ms": (
                statistics.median(latencies) if latencies else 0.0
            ),
            "p95_ms": _percentile(latencies, 0.95),
            "max_ms": max(latencies) if latencies else 0.0,
            "under_300ms": sum(
                value <= 300.0 for value in latencies
            ),
            "total": len(latencies),
        },
        "embedding": {
            "requested_runtime": sum(
                row["embedding_requested_delta"] for row in rows
            ),
            "computed_runtime": sum(
                row["embedding_computed_delta"] for row in rows
            ),
        },
        "overall": _summarize(rows),
        "by_source_kind": _breakdowns(rows, "source_kind"),
        "by_evaluation_track": _breakdowns(
            rows,
            "evaluation_track",
        ),
        "by_query_type": _breakdowns(rows, "query_type"),
        "cases": rows,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(output, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "initialization_ms": initialization_ms,
                "latency": output["latency"],
                "embedding": output["embedding"],
                "overall": output["overall"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
