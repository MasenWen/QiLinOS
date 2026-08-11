from __future__ import annotations

import argparse
import json
import statistics
import time
from pathlib import Path
from typing import Any, Mapping, Sequence

from src.memory_engine.observation import ObservationMatcher
from src.memory_engine.preference_matching import (
    DEFAULT_CANONICAL_TAGS_V1,
    CanonicalTag,
    PreferenceObservationOptions,
)
from src.memory_engine.span_matching import JiebaSpanTokenizer


DEFAULT_CASES = Path("tests/data/observation_formation_small_v1.json")
DEFAULT_OUTPUT = Path(
    "runtime/results/observation_formation_small_v1/development.json"
)


def _direction(value: float) -> str:
    if value > 0.10:
        return "positive"
    if value < -0.10:
        return "negative"
    return "uncertain"


def _prediction(frame: Any) -> dict[str, Any]:
    return {
        "condition_tag_id": (
            frame.condition.tag_id if frame.condition is not None else None
        ),
        "condition_text": (
            frame.condition.text if frame.condition is not None else None
        ),
        "object_tag_id": frame.object.tag_id,
        "object_text": frame.object.text,
        "attitude_direction": _direction(frame.attitude.value),
        "attitude_value": frame.attitude.value,
        "attitude_text": frame.attitude.text,
        "temporal_label": (
            frame.temporal.label if frame.temporal is not None else None
        ),
        "temporal_text": (
            frame.temporal.text if frame.temporal is not None else None
        ),
        "confidence": frame.confidence,
        "source_start": frame.source_start,
        "source_end": frame.source_end,
    }


def frame_is_correct(
    predicted: Mapping[str, Any],
    expected: Mapping[str, Any],
) -> bool:
    return bool(
        predicted["condition_tag_id"] in expected["condition_tag_ids"]
        and predicted["object_tag_id"] == expected["object_tag_id"]
        and predicted["attitude_direction"]
        in expected["attitude_directions"]
        and predicted["temporal_label"] in expected["temporal_labels"]
    )


def maximum_frame_matching(
    predictions: Sequence[Mapping[str, Any]],
    expected_frames: Sequence[Mapping[str, Any]],
) -> tuple[tuple[int, int], ...]:
    compatibility = {
        prediction_index: tuple(
            expected_index
            for expected_index, expected in enumerate(expected_frames)
            if frame_is_correct(prediction, expected)
        )
        for prediction_index, prediction in enumerate(predictions)
    }
    best: tuple[tuple[int, int], ...] = ()

    def visit(
        prediction_index: int,
        used_expected: frozenset[int],
        pairs: tuple[tuple[int, int], ...],
    ) -> None:
        nonlocal best
        if prediction_index >= len(predictions):
            if len(pairs) > len(best):
                best = pairs
            return
        if len(pairs) + len(predictions) - prediction_index <= len(best):
            return
        visit(prediction_index + 1, used_expected, pairs)
        for expected_index in compatibility[prediction_index]:
            if expected_index in used_expected:
                continue
            visit(
                prediction_index + 1,
                used_expected | {expected_index},
                (*pairs, (prediction_index, expected_index)),
            )

    visit(0, frozenset(), ())
    return best


def _role_credit(
    predicted: Mapping[str, Any],
    expected: Mapping[str, Any],
) -> dict[str, bool]:
    return {
        "condition": (
            predicted["condition_tag_id"] in expected["condition_tag_ids"]
        ),
        "object": predicted["object_tag_id"] == expected["object_tag_id"],
        "attitude": (
            predicted["attitude_direction"]
            in expected["attitude_directions"]
        ),
        "temporal": (
            predicted["temporal_label"] in expected["temporal_labels"]
        ),
    }


def _best_near_match(
    predicted: Mapping[str, Any],
    expected_frames: Sequence[Mapping[str, Any]],
) -> dict[str, Any] | None:
    if not expected_frames:
        return None
    values = [
        (_role_credit(predicted, expected), index, expected)
        for index, expected in enumerate(expected_frames)
    ]
    credits, index, expected = max(
        values,
        key=lambda value: (
            sum(value[0].values()),
            value[0]["object"],
            value[0]["attitude"],
            -value[1],
        ),
    )
    return {
        "expected_index": index,
        "credits": credits,
        "expected": expected,
    }


def _custom_tags(values: Sequence[Mapping[str, Any]]) -> tuple[CanonicalTag, ...]:
    return tuple(
        CanonicalTag(
            tag_id=str(value["tag_id"]),
            name=str(value["name"]),
            groups=tuple(value["groups"]),
            aliases=tuple(value["aliases"]),
            prototypes=tuple(value["prototypes"]),
        )
        for value in values
    )


def _percentile(values: Sequence[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    position = (len(ordered) - 1) * percentile
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction


def evaluate(
    dataset: Mapping[str, Any],
    *,
    split: str,
    matcher: ObservationMatcher,
) -> dict[str, Any]:
    cases = dataset["splits"][split]
    options = PreferenceObservationOptions(
        condition_tag_ids=tuple(dataset["options"]["condition_tag_ids"]),
        object_tag_ids=tuple(dataset["options"]["object_tag_ids"]),
        temporal_labels=tuple(dataset["options"]["temporal_labels"]),
    )
    rows = []
    for case in cases:
        started = time.perf_counter()
        result = matcher.match(case["text"], options=options)
        latency_ms = (time.perf_counter() - started) * 1000.0
        predictions = [_prediction(frame) for frame in result.frames]
        expected_frames = case["expected_frames"]
        matched = maximum_frame_matching(predictions, expected_frames)
        matched_predictions = {left for left, _ in matched}
        matched_expected = {right for _, right in matched}
        rows.append(
            {
                "id": case["id"],
                "text": case["text"],
                "should_form": bool(expected_frames),
                "expected_frames": expected_frames,
                "predictions": predictions,
                "matched_pairs": [
                    {
                        "prediction_index": left,
                        "expected_index": right,
                    }
                    for left, right in matched
                ],
                "unmatched_prediction_diagnostics": [
                    {
                        "prediction_index": index,
                        "prediction": prediction,
                        "best_near_match": _best_near_match(
                            prediction,
                            expected_frames,
                        ),
                    }
                    for index, prediction in enumerate(predictions)
                    if index not in matched_predictions
                ],
                "unmatched_expected_indices": [
                    index
                    for index in range(len(expected_frames))
                    if index not in matched_expected
                ],
                "latency_ms": latency_ms,
                "diagnostics": {
                    **dict(result.diagnostics),
                    "hypotheses": [
                        {
                            "text": value.text,
                            "group": value.group,
                            "label": value.label,
                            "score": value.score,
                            "similarity": value.similarity,
                            "null_margin": value.null_margin,
                            "competition_margin": value.competition_margin,
                            "sources": list(value.sources),
                        }
                        for value in result.hypotheses
                    ],
                    "canonical_matches": [
                        {
                            "text": value.text,
                            "group": value.group,
                            "tag_id": value.tag_id,
                            "similarity": value.similarity,
                            "competition_margin": value.competition_margin,
                            "exact_alias": value.exact_alias,
                            "hypothesis_score": value.hypothesis_score,
                        }
                        for value in result.canonical_matches
                    ],
                    "attitudes": [
                        {
                            "text": value.text,
                            "direction": _direction(value.value),
                            "value": value.value,
                            "anchor": value.anchor,
                            "similarity": value.similarity,
                            "hypothesis_score": value.hypothesis_score,
                        }
                        for value in result.attitudes
                    ],
                    "temporals": [
                        {
                            "text": value.text,
                            "label": value.label,
                            "confidence": value.confidence,
                            "hypothesis_score": value.hypothesis_score,
                        }
                        for value in result.temporals
                    ],
                },
            }
        )

    expected_total = sum(len(row["expected_frames"]) for row in rows)
    predicted_total = sum(len(row["predictions"]) for row in rows)
    matched_total = sum(len(row["matched_pairs"]) for row in rows)
    should_form_rows = [row for row in rows if row["should_form"]]
    should_not_form_rows = [row for row in rows if not row["should_form"]]
    correctly_formed_cases = sum(
        bool(row["matched_pairs"]) for row in should_form_rows
    )
    empty_negative_cases = sum(
        not row["predictions"] for row in should_not_form_rows
    )
    latencies = [float(row["latency_ms"]) for row in rows]
    return {
        "schema_version": "observation.formation.evaluation.v1",
        "split": split,
        "uses_llm": False,
        "formation_policy": dataset["formation_policy"],
        "summary": {
            "case_count": len(rows),
            "should_form_case_count": len(should_form_rows),
            "should_not_form_case_count": len(should_not_form_rows),
            "expected_frame_count": expected_total,
            "predicted_frame_count": predicted_total,
            "correct_frame_count": matched_total,
            "formation_recall": (
                matched_total / expected_total if expected_total else 1.0
            ),
            "formed_frame_precision": (
                matched_total / predicted_total if predicted_total else 1.0
            ),
            "should_form_case_recall": (
                correctly_formed_cases / len(should_form_rows)
                if should_form_rows
                else 1.0
            ),
            "negative_case_specificity": (
                empty_negative_cases / len(should_not_form_rows)
                if should_not_form_rows
                else 1.0
            ),
            "negative_false_formation_count": (
                len(should_not_form_rows) - empty_negative_cases
            ),
        },
        "latency": {
            "mean_ms": statistics.fmean(latencies) if latencies else 0.0,
            "median_ms": statistics.median(latencies) if latencies else 0.0,
            "p95_ms": _percentile(latencies, 0.95),
            "max_ms": max(latencies) if latencies else 0.0,
        },
        "rows": rows,
    }


def main() -> None:
    try:
        from src.rag.kylin_embedding_sdk import KylinTextEmbedding
    except ImportError:
        from tools.evaluate_kylin_embedding_preference_object_blind import (
            KylinTextEmbedding,
        )

    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument(
        "--split",
        choices=("development", "validation"),
        default="development",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--min-frame-confidence", type=float, default=0.78)
    args = parser.parse_args()

    dataset = json.loads(args.cases.read_text(encoding="utf-8"))
    tags = (
        *DEFAULT_CANONICAL_TAGS_V1,
        *_custom_tags(dataset.get("custom_tags") or ()),
    )
    initialization_started = time.perf_counter()
    matcher = ObservationMatcher(
        KylinTextEmbedding(),
        tokenizer=JiebaSpanTokenizer(),
        tags=tags,
        min_frame_confidence=args.min_frame_confidence,
    )
    initialization_ms = (
        time.perf_counter() - initialization_started
    ) * 1000.0
    output = evaluate(dataset, split=args.split, matcher=matcher)
    output["initialization_ms"] = initialization_ms
    output["min_frame_confidence"] = args.min_frame_confidence
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(output, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "split": args.split,
                "summary": output["summary"],
                "latency": output["latency"],
                "initialization_ms": initialization_ms,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
