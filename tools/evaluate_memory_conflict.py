from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path
from typing import Any, Mapping

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.memory_engine.conflict import (
    CONFLICT_DETECTORS,
    ConflictDetectorConfig,
    ConflictIndex,
    ConflictMemory,
    apply_conflict_assessment,
)
from src.memory_engine.memory_lifecycle import (
    ConfidenceEvidence,
    MemoryLifeSeed,
    MemoryLifecycleEngine,
    SourceBetaMeanConfidence,
    WeibullSurvivalStability,
)


DEFAULT_CASES = Path("tests/data/memory_conflict_benchmark_v1.json")
DEFAULT_OUTPUT = Path("runtime/results/memory_conflict_v1.json")


def _memory(
    defaults: Mapping[str, Any],
    value: Mapping[str, Any],
) -> ConflictMemory:
    merged = {**defaults, **value}
    for name in ("condition_tag_ids", "supersedes_memory_ids"):
        merged[name] = tuple(merged.get(name) or ())
    return ConflictMemory(**merged)


def _penalty_correct(
    expected: Mapping[str, Any],
    assessment: Any,
) -> bool:
    factors = {
        key: float(value)
        for key, value in assessment.confidence_factors.items()
    }
    penalty = expected["penalty"]
    if penalty == "none":
        return all(value == 1.0 for value in factors.values())
    if penalty == "both":
        if not factors or not all(value < 1.0 for value in factors.values()):
            return False
        weaker = expected.get("weaker_memory_id")
        if weaker:
            other = next(key for key in factors if key != weaker)
            return factors[weaker] < factors[other]
        return True
    predecessor = expected["predecessor_memory_id"]
    successor = expected["successor_memory_id"]
    return (
        factors.get(predecessor, 1.0)
        < factors.get(successor, 1.0)
        and factors.get(predecessor, 1.0) < 1.0
    )


def _explanation_complete(assessment: Any) -> bool:
    if not assessment.detected:
        return bool(assessment.explanation)
    codes = {reason.code for reason in assessment.reasons}
    required = {
        "same_slot",
        "incompatible_values",
        "condition_relation",
        "time_relation",
    }
    if not required <= codes or len(assessment.explanation) < 45:
        return False
    if assessment.conflict_type == "dynamic":
        return (
            assessment.predecessor_memory_id in assessment.explanation
            and assessment.successor_memory_id in assessment.explanation
        )
    return True


def _runtime_confidence_correct(
    assessment: Any,
    left: ConflictMemory,
    right: ConflictMemory,
) -> bool:
    engine = MemoryLifecycleEngine(
        WeibullSurvivalStability(),
        SourceBetaMeanConfidence(),
    )
    for memory in (left, right):
        condition_tags = tuple(memory.condition_tag_ids) or tuple(
            f"condition:{key}:{value}"
            for key, value in sorted(memory.conditions.items())
        )
        engine.add_memory(
            MemoryLifeSeed(
                memory_id=memory.memory_id,
                user_id=memory.user_id,
                created_at=memory.observed_at,
                source_kind=memory.source_kind,
                temporal_label="temporal_medium",
                temporal_confidence=0.5,
                explicit_long_term=False,
                base_strength=float(memory.confidence),
                condition_tag_ids=condition_tags,
                object_tag_ids=(f"object:slot:{memory.slot_key}",),
                attitude_polarity="",
                evidence=(
                    ConfidenceEvidence(
                        evidence_id=f"{memory.memory_id}:evidence",
                        observed_at=memory.observed_at,
                        source_kind=memory.source_kind,
                        quality=float(memory.evidence_strength),
                        independent_unit_id=(
                            f"{memory.memory_id}:independent"
                        ),
                    ),
                ),
            )
        )
    before = {
        memory_id: float(state.confidence["value"])
        for memory_id, state in engine.states.items()
    }
    observed_at = max(left.observed_at, right.observed_at)
    apply_conflict_assessment(
        engine,
        assessment,
        observed_at=observed_at,
    )
    for memory_id, expected_factor in (
        assessment.confidence_factors.items()
    ):
        actual_factor = (
            float(engine.states[memory_id].confidence["value"])
            / before[memory_id]
        )
        if abs(actual_factor - float(expected_factor)) > 1e-6:
            return False
    return True


def _grade_case(
    expected: Mapping[str, Any],
    assessment: Any,
    left: ConflictMemory,
    right: ConflictMemory,
) -> dict[str, bool]:
    expected_type = expected["conflict_type"]
    expected_detected = expected_type != "none"
    predicted_detected = assessment.detected
    links = assessment.links
    link_correct = bool(links) == bool(expected.get("linked", False))
    if links and expected.get("relation_type"):
        link_correct = (
            link_correct
            and links[0].relation_type == expected["relation_type"]
            and links[0].directed == expected["directed"]
        )
    direction_correct = True
    if expected_type == "dynamic":
        direction_correct = (
            assessment.predecessor_memory_id
            == expected["predecessor_memory_id"]
            and assessment.successor_memory_id
            == expected["successor_memory_id"]
        )
    retrieval_correct = not expected_detected
    if expected_detected:
        left_id, right_id = assessment.memory_ids
        groups = ConflictIndex((assessment,)).expand((left_id,))
        retrieval_correct = bool(
            groups
            and groups[0].companions
            and groups[0].companions[0].memory_id == right_id
        )
    graph_correct = not expected_detected
    if expected_detected:
        signals = assessment.graph_signals()
        graph_correct = bool(
            signals
            and signals[0].relation_type == links[0].relation_type
            and signals[0].directed == links[0].directed
        )
    return {
        "type_correct": assessment.conflict_type == expected_type,
        "true_positive": predicted_detected and expected_detected,
        "false_positive": predicted_detected and not expected_detected,
        "false_negative": not predicted_detected and expected_detected,
        "link_correct": link_correct,
        "direction_correct": direction_correct,
        "assessment_factor_correct": _penalty_correct(
            expected,
            assessment,
        ),
        "runtime_confidence_correct": _runtime_confidence_correct(
            assessment,
            left,
            right,
        ),
        "explanation_complete": _explanation_complete(assessment),
        "retrieval_correct": retrieval_correct,
        "graph_correct": graph_correct,
    }


def _percentile(values: list[float], quantile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(
        len(ordered) - 1,
        max(0, int(round((len(ordered) - 1) * quantile))),
    )
    return ordered[index]


def _summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    count = len(rows)
    positives = sum(row["expected_type"] != "none" for row in rows)
    predicted = sum(row["assessment"]["detected"] for row in rows)
    true_positive = sum(row["grade"]["true_positive"] for row in rows)
    latencies = [float(row["latency_ms"]) for row in rows]

    def accuracy(name: str) -> float:
        return (
            sum(bool(row["grade"][name]) for row in rows) / count
            if count
            else 1.0
        )

    type_accuracy = accuracy("type_correct")
    detection_precision = (
        true_positive / predicted if predicted else 1.0
    )
    detection_recall = (
        true_positive / positives if positives else 1.0
    )
    link_accuracy = accuracy("link_correct")
    direction_accuracy = accuracy("direction_correct")
    assessment_factor_accuracy = accuracy(
        "assessment_factor_correct"
    )
    runtime_confidence_accuracy = accuracy(
        "runtime_confidence_correct"
    )
    explanation_accuracy = accuracy("explanation_complete")
    retrieval_accuracy = accuracy("retrieval_correct")
    graph_accuracy = accuracy("graph_correct")
    quality = 10.0 * (
        0.25 * type_accuracy
        + 0.13 * detection_precision
        + 0.13 * detection_recall
        + 0.10 * link_accuracy
        + 0.08 * direction_accuracy
        + 0.12 * runtime_confidence_accuracy
        + 0.08 * explanation_accuracy
        + 0.07 * retrieval_accuracy
        + 0.04 * graph_accuracy
    )
    return {
        "case_count": count,
        "positive_case_count": positives,
        "predicted_conflict_count": predicted,
        "type_accuracy": type_accuracy,
        "detection_precision": detection_precision,
        "detection_recall": detection_recall,
        "link_accuracy": link_accuracy,
        "direction_accuracy": direction_accuracy,
        "assessment_factor_accuracy": assessment_factor_accuracy,
        "confidence_adjustment_accuracy": runtime_confidence_accuracy,
        "explanation_completeness": explanation_accuracy,
        "retrieval_companion_accuracy": retrieval_accuracy,
        "graph_signal_accuracy": graph_accuracy,
        "quality_score_10": quality,
        "latency": {
            "mean_ms": statistics.fmean(latencies) if latencies else 0.0,
            "median_ms": statistics.median(latencies) if latencies else 0.0,
            "p95_ms": _percentile(latencies, 0.95),
            "max_ms": max(latencies) if latencies else 0.0,
        },
    }


def evaluate(
    dataset: Mapping[str, Any],
    *,
    split: str,
) -> dict[str, Any]:
    defaults = dataset["memory_defaults"]
    config = ConflictDetectorConfig(
        slot_aliases=dataset.get("slot_aliases") or {},
    )
    cases = [
        item
        for item in dataset["cases"]
        if split == "all" or item["split"] == split
    ]
    methods = {}
    for name, detector_type in CONFLICT_DETECTORS.items():
        detector = detector_type(config)
        rows = []
        for case in cases:
            left = _memory(defaults, case["left"])
            right = _memory(defaults, case["right"])
            started = time.perf_counter()
            assessment = detector.assess(left, right)
            latency_ms = (time.perf_counter() - started) * 1000.0
            grade = _grade_case(
                case["expected"],
                assessment,
                left,
                right,
            )
            rows.append(
                {
                    "id": case["id"],
                    "split": case["split"],
                    "description": case["description"],
                    "expected_type": case["expected"]["conflict_type"],
                    "expected": case["expected"],
                    "assessment": assessment.to_dict(),
                    "grade": grade,
                    "latency_ms": latency_ms,
                }
            )
        methods[name] = {
            "summary": _summary(rows),
            "rows": rows,
        }
    ranked = sorted(
        (
            {
                "method": name,
                "quality_score_10": result["summary"][
                    "quality_score_10"
                ],
                "type_accuracy": result["summary"]["type_accuracy"],
                "detection_precision": result["summary"][
                    "detection_precision"
                ],
                "detection_recall": result["summary"][
                    "detection_recall"
                ],
            }
            for name, result in methods.items()
        ),
        key=lambda item: (
            -item["quality_score_10"],
            -item["detection_precision"],
            item["method"],
        ),
    )
    return {
        "schema_version": "memory_conflict.evaluation.v1",
        "split": split,
        "case_count": len(cases),
        "methods": methods,
        "ranking": ranked,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument(
        "--split",
        choices=("development", "validation", "all"),
        default="all",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    dataset = json.loads(args.cases.read_text(encoding="utf-8"))
    result = evaluate(dataset, split=args.split)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "split": result["split"],
                "case_count": result["case_count"],
                "ranking": result["ranking"],
                "summaries": {
                    name: value["summary"]
                    for name, value in result["methods"].items()
                },
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
