#!/usr/bin/env python3
"""Audit scoped static retrieval results without changing the evaluator."""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


def percent(part: int, whole: int) -> float:
    return round(100.0 * part / whole, 4) if whole else 0.0


def summarize_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    exact_slot_complete = 0
    top1_any_required = 0
    raw_overlap_count = 0
    effective_forbidden_top1 = 0
    effective_forbidden_top2 = 0
    top1_misses: list[dict[str, Any]] = []
    by_required_count: dict[int, dict[str, int]] = defaultdict(
        lambda: {"queries": 0, "exact_slot_complete": 0, "top1_any_required": 0}
    )
    by_track: dict[str, dict[str, int]] = defaultdict(
        lambda: {"queries": 0, "exact_slot_complete": 0, "top1_any_required": 0}
    )
    namespace_sizes: Counter[int] = Counter()

    for row in rows:
        required = set(row.get("required_memory_ids", []))
        candidates = set(row.get("candidate_memory_ids", []))
        forbidden = set(row.get("forbidden_memory_ids", []))
        ranked = row.get("ranked_memory_ids", [])
        required_count = len(required)
        track = str(row.get("evaluation_track", "unknown"))
        top1_hit = bool(required.intersection(ranked[:1]))
        exact_complete = required <= set(ranked[:required_count]) if required else True
        effective_forbidden = forbidden - required - candidates

        by_required_count[required_count]["queries"] += 1
        by_track[track]["queries"] += 1
        if exact_complete:
            exact_slot_complete += 1
            by_required_count[required_count]["exact_slot_complete"] += 1
            by_track[track]["exact_slot_complete"] += 1
        if top1_hit:
            top1_any_required += 1
            by_required_count[required_count]["top1_any_required"] += 1
            by_track[track]["top1_any_required"] += 1
        elif required:
            top1_misses.append(
                {
                    "sequence_no": row.get("sequence_no"),
                    "query_id": row.get("query_id"),
                    "precedent_case_id": row.get("precedent_case_id"),
                    "dataset_origin": row.get("dataset_origin"),
                    "evaluation_track": track,
                    "required_count": required_count,
                    "required_memory_ids": sorted(required),
                    "top_memory_ids": ranked[:required_count],
                }
            )

        if required.intersection(forbidden):
            raw_overlap_count += 1
        if effective_forbidden.intersection(ranked[:1]):
            effective_forbidden_top1 += 1
        if effective_forbidden.intersection(ranked[:2]):
            effective_forbidden_top2 += 1

        namespace_size = row.get("retrieval_diagnostics", {}).get(
            "namespace_memory_count"
        )
        if isinstance(namespace_size, int):
            namespace_sizes[namespace_size] += 1

    def add_rates(groups: dict[Any, dict[str, int]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, values in sorted(groups.items(), key=lambda item: str(item[0])):
            total = values["queries"]
            result[str(key)] = {
                **values,
                "exact_slot_complete_rate": percent(
                    values["exact_slot_complete"], total
                ),
                "top1_any_required_rate": percent(
                    values["top1_any_required"], total
                ),
            }
        return result

    total = len(rows)
    return {
        "queries": total,
        "exact_slot_complete": exact_slot_complete,
        "exact_slot_complete_rate": percent(exact_slot_complete, total),
        "top1_any_required": top1_any_required,
        "top1_any_required_rate": percent(top1_any_required, total),
        "required_forbidden_parent_overlap_queries": raw_overlap_count,
        "required_forbidden_parent_overlap_rate": percent(raw_overlap_count, total),
        "effective_forbidden_only_top1_queries": effective_forbidden_top1,
        "effective_forbidden_only_top1_rate": percent(
            effective_forbidden_top1, total
        ),
        "effective_forbidden_only_top2_queries": effective_forbidden_top2,
        "effective_forbidden_only_top2_rate": percent(
            effective_forbidden_top2, total
        ),
        "by_required_memory_count": add_rates(by_required_count),
        "by_evaluation_track": add_rates(by_track),
        "namespace_memory_count_distribution": {
            str(key): value for key, value in sorted(namespace_sizes.items())
        },
        "top1_misses": top1_misses,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("result", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    with args.result.open("r", encoding="utf-8") as handle:
        report = json.load(handle)
    audit = summarize_rows(report["rows"])
    rendered = json.dumps(audit, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)


if __name__ == "__main__":
    main()
