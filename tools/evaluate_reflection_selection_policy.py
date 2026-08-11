from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

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


DEFAULT_REFLECTION = Path(
    "outputs/memory_reflection/"
    "server_deepseek_reflection_lifecycle_v1_round1.json"
)
DEFAULT_OUTPUT = Path(
    "outputs/memory_reflection/"
    "selection_policy_replay_v1.json"
)


def _replay_callback(
    traces: dict[str, dict[str, Any]],
    *,
    merge_first: bool = False,
):
    def apply(engine, at: str, phase: str):
        trace = traces[phase]
        penalized = []
        recovered = []
        merged = []
        operations = (
            ("merge", "correction")
            if merge_first
            else ("correction", "merge")
        )
        for operation in operations:
            if operation == "correction":
                for proposal in trace["correction_proposals"]:
                    changed = engine.apply_reflection_penalty(
                        str(proposal["memory_id"]),
                        penalty_factor=float(proposal["penalty_factor"]),
                        at=at,
                        review_id=str(proposal["review_id"]),
                        verdict=str(proposal["verdict"]),
                        rationale=str(proposal["rationale"]),
                        source_refs=tuple(proposal["source_refs"]),
                    )
                    if changed:
                        if proposal["verdict"] == "supported":
                            recovered.append(str(proposal["memory_id"]))
                        elif float(proposal["penalty_factor"]) < 1.0:
                            penalized.append(str(proposal["memory_id"]))
                continue
            for proposal in trace["merge_proposals"]:
                if proposal["decision"] != "merge":
                    continue
                changed = engine.merge_memories(
                    str(proposal["canonical_memory_id"]),
                    tuple(proposal["duplicate_memory_ids"]),
                    at=at,
                    review_id=str(proposal["review_id"]),
                    rationale=str(proposal["rationale"]),
                    source_refs=tuple(proposal["source_refs"]),
                )
                merged.extend(changed)
        return {
            "round_id": phase,
            "mode": (
                "fixed_deepseek_merge_first_replay"
                if merge_first
                else "fixed_deepseek_replay"
            ),
            "penalized_memory_ids": penalized,
            "recovered_memory_ids": recovered,
            "merged_memory_ids": merged,
        }

    return apply


def _compact(
    result: dict[str, Any],
    gold: dict[str, Any],
) -> dict[str, object]:
    retrieval = result["retrieval"]
    lifecycle = result["lifecycle"]
    return {
        "ai_gold_score": gold["score"],
        "keep_recall": gold["keep_recall"],
        "forget_recall": gold["forget_recall"],
        "balanced_accuracy": gold["balanced_accuracy"],
        "hit_rate": retrieval["hit_rate"],
        "selection_precision": retrieval["selection_precision"],
        "semantic_selection_precision": retrieval[
            "semantic_selection_precision"
        ],
        "selected_count": retrieval["selected_count"],
        "semantic_selected_count": retrieval[
            "semantic_selected_count"
        ],
        "incorrect_selection_counts": retrieval[
            "incorrect_selection_counts"
        ],
        "explicit_long_survival": lifecycle[
            "explicit_long_survival"
        ],
        "real_stale_risk_forget_rate": lifecycle[
            "real_stale_risk_forget_rate"
        ],
        "active_total": lifecycle["active_total"],
        "forgotten_total": lifecycle["forgotten_total"],
        "performance_ms": result["performance_ms"],
        "lifecycle_miss_samples": [
            item
            for item in result["query_trace_sample"]
            if item.get("failure_stage") == "lifecycle_retrieval_miss"
        ],
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
    parser.add_argument(
        "--reflection-result",
        type=Path,
        default=DEFAULT_REFLECTION,
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--ratios",
        type=float,
        nargs="+",
        default=(0.0, 0.70, 0.78, 0.84, 0.90, 0.95),
    )
    parser.add_argument("--merge-first", action="store_true")
    args = parser.parse_args()

    annotations = json.loads(
        args.annotations.read_text(encoding="utf-8")
    )
    reflection_result = json.loads(
        args.reflection_result.read_text(encoding="utf-8")
    )
    traces = {
        str(trace["round_id"]): trace
        for trace in reflection_result["reflection_rounds"]
    }
    initial, late, relations, fixture = build_fixture(args.memories)
    rows = []
    for ratio in args.ratios:
        options = {"secondary_selection_ratio": ratio}
        baseline, baseline_engine = run_combination(
            "weibull",
            "beta_bound",
            observation_path=args.observations,
            initial_seeds=initial,
            late_seeds=late,
            relations=relations,
            engine_options=options,
        )
        reflected, reflected_engine = run_combination(
            "weibull",
            "beta_bound",
            observation_path=args.observations,
            initial_seeds=initial,
            late_seeds=late,
            relations=relations,
            reflection_callback=_replay_callback(
                traces,
                merge_first=args.merge_first,
            ),
            engine_options=options,
        )
        baseline_gold = evaluate_ai_gold(
            baseline_engine,
            annotations,
            baseline,
        )
        reflected_gold = evaluate_ai_gold(
            reflected_engine,
            annotations,
            reflected,
        )
        rows.append(
            {
                "secondary_selection_ratio": ratio,
                "baseline": _compact(baseline, baseline_gold),
                "reflection": _compact(reflected, reflected_gold),
            }
        )
    output = {
        "purpose": (
            "Deterministic replay of fixed DeepSeek Reflection decisions "
            "while varying only the secondary retrieval quality gate."
        ),
        "fixture": fixture,
        "reflection_source": str(args.reflection_result),
        "merge_first": args.merge_first,
        "ratios": rows,
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
                "ratios": [
                    {
                        "ratio": row["secondary_selection_ratio"],
                        "baseline_precision": row["baseline"][
                            "selection_precision"
                        ],
                        "reflection_precision": row["reflection"][
                            "selection_precision"
                        ],
                        "baseline_semantic_precision": row["baseline"][
                            "semantic_selection_precision"
                        ],
                        "reflection_semantic_precision": row[
                            "reflection"
                        ]["semantic_selection_precision"],
                        "reflection_hit_rate": row["reflection"][
                            "hit_rate"
                        ],
                        "reflection_gold_score": row["reflection"][
                            "ai_gold_score"
                        ],
                    }
                    for row in rows
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
