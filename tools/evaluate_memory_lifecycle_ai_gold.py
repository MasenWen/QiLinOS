from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from dataclasses import replace
from pathlib import Path
from typing import Any

from src.memory_engine.memory_lifecycle import (
    CONFIDENCE_STRATEGIES,
    STABILITY_STRATEGIES,
    MemoryLifecycleEngine,
)
from tools.evaluate_memory_lifecycle import (
    DEFAULT_MEMORIES,
    DEFAULT_OBSERVATIONS,
    _at,
    build_fixture,
    run_combination,
)
from tools.materialize_ai_retention_annotations import (
    DEFAULT_OUTPUT as DEFAULT_ANNOTATIONS,
)


DEFAULT_OUTPUT = Path(
    "outputs/memory_lifecycle/comparison_ai_gold_v1.json"
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def evaluate_ai_gold(
    engine: MemoryLifecycleEngine,
    annotation_payload: dict[str, Any],
    lifecycle_summary: dict[str, Any],
) -> dict[str, object]:
    annotations = {
        str(item["memory_id"]): item
        for item in annotation_payload["annotations"]
    }
    missing = sorted(set(annotations) - set(engine.states))
    if missing:
        raise ValueError(f"annotated_memories_missing:{missing}")

    counts = {
        "keep": 0,
        "forget": 0,
        "uncertain": 0,
        "keep_active": 0,
        "keep_forgotten": 0,
        "forget_active": 0,
        "forget_forgotten": 0,
        "uncertain_active": 0,
        "uncertain_forgotten": 0,
    }
    category_counts: dict[str, dict[str, int]] = defaultdict(
        lambda: {
            "count": 0,
            "correct": 0,
            "active": 0,
            "forgotten": 0,
        }
    )
    weighted_correct = 0.0
    weighted_total = 0.0
    mistakes = []
    uncertain_outcomes = []
    for memory_id, annotation in annotations.items():
        state = engine.states[memory_id]
        label = str(annotation["label"])
        merged_target_active = bool(
            state.merged_into
            and state.merged_into in engine.states
            and engine.states[state.merged_into].status == "active"
        )
        if label == "keep":
            status = (
                "active"
                if state.status == "active" or merged_target_active
                else "forgotten"
            )
        elif label == "forget":
            status = (
                "forgotten"
                if state.status in {"forgotten", "merged"}
                else "active"
            )
        else:
            status = (
                "active"
                if state.status == "active" or merged_target_active
                else "forgotten"
            )
        counts[label] += 1
        counts[f"{label}_{status}"] += 1
        category = str(annotation["category"])
        bucket = category_counts[category]
        bucket["count"] += 1
        bucket[status] += 1

        if label == "uncertain":
            uncertain_outcomes.append(
                {
                    "memory_id": memory_id,
                    "status": status,
                    "category": category,
                    "annotation_confidence": annotation["confidence"],
                }
            )
            continue
        correct = (
            (label == "keep" and status == "active")
            or (label == "forget" and status == "forgotten")
        )
        bucket["correct"] += int(correct)
        weight = float(annotation["confidence"])
        weighted_total += weight
        weighted_correct += weight * int(correct)
        if not correct:
            mistakes.append(
                {
                    "memory_id": memory_id,
                    "gold_label": label,
                    "predicted_status": status,
                    "category": category,
                    "annotation_confidence": annotation["confidence"],
                    "annotation_rationale": annotation["rationale"],
                    "activation_count": state.activation_count,
                    "last_activated_at": state.last_activated_at,
                    "relation_support_count": len(
                        state.relation_support
                    ),
                    "stability": state.stability["value"],
                    "confidence": state.confidence["value"],
                }
            )

    keep_recall = (
        counts["keep_active"] / counts["keep"]
        if counts["keep"]
        else 0.0
    )
    forget_recall = (
        counts["forget_forgotten"] / counts["forget"]
        if counts["forget"]
        else 0.0
    )
    binary_count = counts["keep"] + counts["forget"]
    binary_correct = (
        counts["keep_active"] + counts["forget_forgotten"]
    )
    binary_accuracy = (
        binary_correct / binary_count if binary_count else 0.0
    )
    balanced_accuracy = 0.5 * (keep_recall + forget_recall)
    weighted_accuracy = (
        weighted_correct / weighted_total
        if weighted_total
        else 0.0
    )
    lifecycle = lifecycle_summary["lifecycle"]
    ai_score = 10.0 * (
        0.40 * keep_recall
        + 0.35 * forget_recall
        + 0.10 * weighted_accuracy
        + 0.05 * float(lifecycle["active_refresh_survival"])
        + 0.05 * float(lifecycle["explicit_long_survival"])
        + 0.05 * float(lifecycle["stale_short_forget_rate"])
    )
    return {
        "score": round(ai_score, 6),
        "binary_scored_count": binary_count,
        "uncertain_count": counts["uncertain"],
        "confusion": counts,
        "keep_recall": round(keep_recall, 6),
        "forget_recall": round(forget_recall, 6),
        "balanced_accuracy": round(balanced_accuracy, 6),
        "binary_accuracy": round(binary_accuracy, 6),
        "confidence_weighted_accuracy": round(
            weighted_accuracy,
            6,
        ),
        "category_breakdown": {
            name: values
            for name, values in sorted(category_counts.items())
        },
        "high_confidence_mistake_count": sum(
            float(item["annotation_confidence"]) >= 0.85
            for item in mistakes
        ),
        "mistakes": sorted(
            mistakes,
            key=lambda item: (
                item["gold_label"],
                -float(item["annotation_confidence"]),
                item["memory_id"],
            ),
        ),
        "uncertain_outcomes": sorted(
            uncertain_outcomes,
            key=lambda item: item["memory_id"],
        ),
    }


def _run(
    stability_name: str,
    confidence_name: str,
    *,
    annotation_payload: dict[str, Any],
    observation_path: Path,
    initial_seeds: tuple,
    late_seeds: tuple,
    relations: tuple,
) -> tuple[dict[str, object], MemoryLifecycleEngine]:
    lifecycle, engine = run_combination(
        stability_name,
        confidence_name,
        observation_path=observation_path,
        initial_seeds=initial_seeds,
        late_seeds=late_seeds,
        relations=relations,
    )
    ai_gold = evaluate_ai_gold(
        engine,
        annotation_payload,
        lifecycle,
    )
    return (
        {
            "stability_strategy": stability_name,
            "confidence_strategy": confidence_name,
            "ai_gold": ai_gold,
            "performance_ms": lifecycle["performance_ms"],
            "retrieval": lifecycle["retrieval"],
            "lifecycle_controls": lifecycle["lifecycle"],
            "source_confidence": lifecycle["confidence"],
            "temporal_outcomes": lifecycle["temporal_outcomes"],
        },
        engine,
    )


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
    parser.add_argument(
        "--annotations",
        type=Path,
        default=DEFAULT_ANNOTATIONS,
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    annotation_payload = json.loads(
        args.annotations.read_text(encoding="utf-8")
    )
    initial, late, relations, fixture = build_fixture(args.memories)
    results = []
    engines = {}
    for stability_name in STABILITY_STRATEGIES:
        for confidence_name in CONFIDENCE_STRATEGIES:
            result, engine = _run(
                stability_name,
                confidence_name,
                annotation_payload=annotation_payload,
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
            -float(item["ai_gold"]["score"]),
            -float(item["ai_gold"]["balanced_accuracy"]),
            str(item["stability_strategy"]),
            str(item["confidence_strategy"]),
        )
    )
    best = results[0]
    best_key = (
        f"{best['stability_strategy']}+"
        f"{best['confidence_strategy']}"
    )

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
    hard_result, _ = _run(
        str(best["stability_strategy"]),
        str(best["confidence_strategy"]),
        annotation_payload=annotation_payload,
        observation_path=args.observations,
        initial_seeds=hard_initial,
        late_seeds=hard_late,
        relations=relations,
    )

    output = {
        "purpose": (
            "Memory lifecycle comparison against blind AI-adjudicated "
            "long-term retention labels."
        ),
        "runtime_llm_or_embedding": False,
        "annotation_method": annotation_payload["review_protocol"],
        "annotation_label_counts": annotation_payload["label_counts"],
        "uncertain_policy": (
            "Uncertain annotations are reported but excluded from "
            "binary metrics and algorithm ranking."
        ),
        "score_weights": {
            "keep_recall": 0.40,
            "forget_recall": 0.35,
            "confidence_weighted_accuracy": 0.10,
            "active_probe_survival": 0.05,
            "explicit_long_survival": 0.05,
            "stale_probe_forgetting": 0.05,
        },
        "input_hashes": {
            "observations_sha256": _sha256(args.observations),
            "memories_sha256": _sha256(args.memories),
            "annotations_sha256": _sha256(args.annotations),
        },
        "fixture": fixture,
        "comparison": results,
        "best_combination": best_key,
        "hard_temporal_ablation": {
            "blended": best,
            "hard": hard_result,
            "score_delta_hard_minus_blended": round(
                float(hard_result["ai_gold"]["score"])
                - float(best["ai_gold"]["score"]),
                6,
            ),
        },
        "best_final_states": engines[best_key].snapshot(_at(420)),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(output, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "output": str(args.output),
                "best_combination": best_key,
                "comparison": [
                    {
                        "combination": (
                            f"{result['stability_strategy']}+"
                            f"{result['confidence_strategy']}"
                        ),
                        "score": result["ai_gold"]["score"],
                        "keep_recall": result["ai_gold"][
                            "keep_recall"
                        ],
                        "forget_recall": result["ai_gold"][
                            "forget_recall"
                        ],
                        "balanced_accuracy": result["ai_gold"][
                            "balanced_accuracy"
                        ],
                        "binary_accuracy": result["ai_gold"][
                            "binary_accuracy"
                        ],
                        "performance_ms": result["performance_ms"],
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
