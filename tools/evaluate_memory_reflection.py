from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from src.memory_engine.reflection import (
    DeepSeekReflectionClient,
    LifecycleReflection,
    build_reflection_packets,
)
from tools.evaluate_memory_lifecycle import (
    DEFAULT_MEMORIES,
    DEFAULT_OBSERVATIONS,
    build_fixture,
    run_combination,
)
from tools.evaluate_memory_lifecycle_ai_gold import evaluate_ai_gold
from tools.materialize_ai_retention_annotations import (
    DEFAULT_OUTPUT as DEFAULT_ANNOTATIONS,
)


DEFAULT_OUTPUT = Path(
    "outputs/memory_reflection/deepseek_reflection_lifecycle_v1.json"
)
DEFAULT_TEMPORARY_DIRECTORY = Path("runtime/reflection_tmp")

EXPECTED_CORRECTION_VERDICTS = {
    "completed_task_without_late_recurrence": {
        "obsolete_task_state",
        "supported",
    },
    "context_loss_from_one_off_task": {"scope_error"},
    "contradicted_or_inverted_attitude": {"contradicted"},
    "possible_durable_display_preference": {
        "supported",
        "scope_error",
        "unverifiable",
    },
    "recent_but_unsafe_global_ambiguity": {
        "scope_error",
        "unverifiable",
    },
    "recent_clear_task_with_redundant_memories": {"supported"},
    "recent_conditioned_but_semantically_ambiguous": {
        "obsolete_task_state",
        "supported",
        "unverifiable",
    },
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _source_records(path: Path) -> dict[str, dict[str, object]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {
        str(case["id"]): {
            "source_kind": case.get("source_kind"),
            "original_text": (
                case.get("original_text") or case.get("text") or ""
            ),
            "privacy_status": "available",
        }
        for case in payload["cases"]
    }


def _annotation_by_id(
    payload: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    return {
        str(item["memory_id"]): dict(item)
        for item in payload["annotations"]
    }


def _review_quality(
    traces: list[dict[str, object]],
    annotations: dict[str, dict[str, Any]],
) -> dict[str, object]:
    latest = {}
    guarded = set()
    for trace in traces:
        round_guarded = {
            str(memory_id)
            for memory_id in trace.get(
                "guarded_obsolete_memory_ids",
                (),
            )
        }
        for proposal in trace["correction_proposals"]:
            memory_id = str(proposal["memory_id"])
            latest[memory_id] = proposal
            if memory_id in round_guarded:
                guarded.add(memory_id)
            else:
                guarded.discard(memory_id)
    scored = []
    for memory_id, proposal in latest.items():
        annotation = annotations.get(memory_id)
        if annotation is None:
            continue
        expected = EXPECTED_CORRECTION_VERDICTS.get(
            str(annotation["category"]),
            {"unverifiable"},
        )
        verdict = str(proposal["verdict"])
        effective_verdict = (
            "supported"
            if (
                verdict == "obsolete_task_state"
                and memory_id in guarded
            )
            else verdict
        )
        scored.append(
            {
                "memory_id": memory_id,
                "category": annotation["category"],
                "gold_label": annotation["label"],
                "verdict": verdict,
                "effective_verdict": effective_verdict,
                "expected_verdicts": sorted(expected),
                "correct": verdict in expected,
                "effective_correct": effective_verdict in expected,
                "penalty_factor": proposal["penalty_factor"],
                "guarded_obsolete": memory_id in guarded,
            }
        )
    certain = [
        item
        for item in scored
        if annotations[item["memory_id"]]["label"] != "uncertain"
    ]
    keep = [
        item
        for item in certain
        if annotations[item["memory_id"]]["label"] == "keep"
    ]
    forget = [
        item
        for item in certain
        if annotations[item["memory_id"]]["label"] == "forget"
    ]
    return {
        "reviewed_unique_memory_count": len(scored),
        "certain_scored_count": len(certain),
        "semantic_verdict_accuracy": round(
            sum(item["correct"] for item in certain)
            / max(1, len(certain)),
            6,
        ),
        "effective_semantic_accuracy": round(
            sum(item["effective_correct"] for item in certain)
            / max(1, len(certain)),
            6,
        ),
        "guarded_obsolete_count": sum(
            item["guarded_obsolete"] for item in certain
        ),
        "keep_false_penalty_rate": round(
            sum(float(item["penalty_factor"]) < 1.0 for item in keep)
            / max(1, len(keep)),
            6,
        ),
        "forget_flag_rate": round(
            sum(float(item["penalty_factor"]) < 1.0 for item in forget)
            / max(1, len(forget)),
            6,
        ),
        "by_category": _category_quality(certain),
        "errors": [item for item in certain if not item["correct"]],
        "effective_errors": [
            item for item in certain if not item["effective_correct"]
        ],
    }


def _category_quality(
    rows: list[dict[str, object]],
) -> dict[str, dict[str, object]]:
    grouped: dict[str, list[dict[str, object]]] = {}
    for row in rows:
        grouped.setdefault(str(row["category"]), []).append(row)
    return {
        category: {
            "count": len(values),
            "correct": sum(bool(item["correct"]) for item in values),
            "accuracy": round(
                sum(bool(item["correct"]) for item in values)
                / len(values),
                6,
            ),
            "verdict_counts": {
                verdict: sum(item["verdict"] == verdict for item in values)
                for verdict in sorted(
                    {str(item["verdict"]) for item in values}
                )
            },
        }
        for category, values in sorted(grouped.items())
    }


def _compact_lifecycle(
    result: dict[str, object],
    ai_gold: dict[str, object],
) -> dict[str, object]:
    retrieval = result["retrieval"]
    lifecycle = result["lifecycle"]
    return {
        "ai_gold": {
            key: ai_gold[key]
            for key in (
                "score",
                "keep_recall",
                "forget_recall",
                "balanced_accuracy",
                "binary_accuracy",
                "confidence_weighted_accuracy",
                "confusion",
            )
        },
        "retrieval": {
            key: retrieval[key]
            for key in (
                "query_case_count",
                "eligible_case_count",
                "prediction_covered_eligible_count",
                "hit_count",
                "hit_rate",
                "selected_count",
                "correct_selected_count",
                "selection_precision",
                "semantic_selected_count",
                "semantic_correct_selected_count",
                "semantic_selection_precision",
                "rescued_activation_count",
                "failure_stage_counts",
                "incorrect_selection_counts",
            )
        },
        "lifecycle": {
            key: lifecycle[key]
            for key in (
                "active_refresh_survival",
                "explicit_long_survival",
                "stale_short_forget_rate",
                "real_stale_risk_forget_rate",
                "forgotten_total",
                "active_total",
                "positive_relation_lift_rate",
                "conflict_confidence_drop_rate",
            )
        },
        "performance_ms": result["performance_ms"],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--observations", type=Path, default=DEFAULT_OBSERVATIONS)
    parser.add_argument("--memories", type=Path, default=DEFAULT_MEMORIES)
    parser.add_argument(
        "--annotations",
        type=Path,
        default=DEFAULT_ANNOTATIONS,
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--temporary-directory",
        type=Path,
        default=DEFAULT_TEMPORARY_DIRECTORY,
    )
    parser.add_argument("--correction-batch-size", type=int, default=24)
    parser.add_argument("--merge-batch-size", type=int, default=10)
    args = parser.parse_args()

    annotation_payload = json.loads(
        args.annotations.read_text(encoding="utf-8")
    )
    annotations = _annotation_by_id(annotation_payload)
    sources = _source_records(args.observations)
    initial, late, relations, fixture = build_fixture(args.memories)

    baseline_result, baseline_engine = run_combination(
        "weibull",
        "beta_bound",
        observation_path=args.observations,
        initial_seeds=initial,
        late_seeds=late,
        relations=relations,
    )
    baseline_gold = evaluate_ai_gold(
        baseline_engine,
        annotation_payload,
        baseline_result,
    )

    client = DeepSeekReflectionClient()
    reflection = LifecycleReflection(
        client,
        temporary_directory=args.temporary_directory,
        correction_batch_size=args.correction_batch_size,
        merge_batch_size=args.merge_batch_size,
    )

    def explicit_reflection(engine, at: str, phase: str):
        packets = build_reflection_packets(
            engine,
            sources,
            at=at,
        )
        return reflection.run(
            engine,
            packets,
            at=at,
            round_id=phase,
        )

    reflected_result, reflected_engine = run_combination(
        "weibull",
        "beta_bound",
        observation_path=args.observations,
        initial_seeds=initial,
        late_seeds=late,
        relations=relations,
        reflection_callback=explicit_reflection,
    )
    reflected_gold = evaluate_ai_gold(
        reflected_engine,
        annotation_payload,
        reflected_result,
    )
    traces = list(reflected_result["reflection"])
    merged_states = [
        state
        for state in reflected_engine.states.values()
        if state.status == "merged"
    ]
    penalized_states = [
        state
        for state in reflected_engine.states.values()
        if state.reflection_penalty < 1.0
    ]
    remaining_temp_files = (
        list(args.temporary_directory.iterdir())
        if args.temporary_directory.exists()
        else []
    )
    skill_dir = Path(__file__).parents[1] / (
        "src/memory_engine/reflection_skills"
    )
    output = {
        "purpose": (
            "DeepSeek-backed Reflection inserted explicitly at three "
            "points in the fixed memory lifecycle replay."
        ),
        "runtime_model": client.model,
        "scheduler_used_for_quality_test": False,
        "explicit_reflection_phases": [
            "before_query_replay",
            "between_query_epochs",
            "after_late_memories",
        ],
        "fixture": fixture,
        "input_hashes": {
            "observations_sha256": _sha256(args.observations),
            "memories_sha256": _sha256(args.memories),
            "annotations_sha256": _sha256(args.annotations),
            "correctness_skill_sha256": _sha256(
                skill_dir / "correctness_review.md"
            ),
            "merge_skill_sha256": _sha256(
                skill_dir / "duplicate_merge.md"
            ),
        },
        "baseline": _compact_lifecycle(
            baseline_result,
            baseline_gold,
        ),
        "with_reflection": _compact_lifecycle(
            reflected_result,
            reflected_gold,
        ),
        "delta": {
            "ai_gold_score": round(
                float(reflected_gold["score"])
                - float(baseline_gold["score"]),
                6,
            ),
            "keep_recall": round(
                float(reflected_gold["keep_recall"])
                - float(baseline_gold["keep_recall"]),
                6,
            ),
            "forget_recall": round(
                float(reflected_gold["forget_recall"])
                - float(baseline_gold["forget_recall"]),
                6,
            ),
            "balanced_accuracy": round(
                float(reflected_gold["balanced_accuracy"])
                - float(baseline_gold["balanced_accuracy"]),
                6,
            ),
            "hit_rate": round(
                float(reflected_result["retrieval"]["hit_rate"])
                - float(baseline_result["retrieval"]["hit_rate"]),
                6,
            ),
            "selection_precision": round(
                float(
                    reflected_result["retrieval"][
                        "selection_precision"
                    ]
                )
                - float(
                    baseline_result["retrieval"]["selection_precision"]
                ),
                6,
            ),
            "semantic_selection_precision": round(
                float(
                    reflected_result["retrieval"][
                        "semantic_selection_precision"
                    ]
                )
                - float(
                    baseline_result["retrieval"][
                        "semantic_selection_precision"
                    ]
                ),
                6,
            ),
        },
        "review_quality": _review_quality(traces, annotations),
        "reflection_rounds": traces,
        "state_changes": {
            "penalized_memory_count": len(penalized_states),
            "merged_memory_count": len(merged_states),
            "active_memory_count": sum(
                state.status == "active"
                for state in reflected_engine.states.values()
            ),
            "forgotten_memory_count": sum(
                state.status == "forgotten"
                for state in reflected_engine.states.values()
            ),
            "merged_alias_count": len(merged_states),
        },
        "api": {
            "call_count": len(client.calls),
            "calls": client.calls,
            "temporary_markdown_created": (
                reflection.deleted_temporary_files
            ),
            "temporary_markdown_deleted": (
                reflection.deleted_temporary_files
            ),
            "temporary_files_remaining": [
                str(path) for path in remaining_temp_files
            ],
        },
        "final_reflection_states": [
            {
                "memory_id": state.seed.memory_id,
                "status": state.status,
                "merged_into": state.merged_into,
                "reflection_penalty": state.reflection_penalty,
                "confidence": state.confidence["value"],
            }
            for state in sorted(
                reflected_engine.states.values(),
                key=lambda item: item.seed.memory_id,
            )
            if (
                state.reflection_penalty < 1.0
                or state.status == "merged"
            )
        ],
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
                "model": client.model,
                "api_calls": len(client.calls),
                "baseline": output["baseline"]["ai_gold"],
                "with_reflection": output["with_reflection"]["ai_gold"],
                "delta": output["delta"],
                "review_quality": {
                    key: output["review_quality"][key]
                    for key in (
                        "semantic_verdict_accuracy",
                        "keep_false_penalty_rate",
                        "forget_flag_rate",
                    )
                },
                "state_changes": output["state_changes"],
                "temporary_files_remaining": len(
                    remaining_temp_files
                ),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
