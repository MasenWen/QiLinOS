from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from src.memory_engine.reflection import (
    DeepSeekReflectionClient,
    LifecycleReflection,
    ReflectionMemoryPacket,
    build_reflection_packets,
)
from tools.evaluate_memory_lifecycle import (
    DEFAULT_MEMORIES,
    DEFAULT_OBSERVATIONS,
    build_fixture,
    run_combination,
)
from tools.evaluate_memory_reflection import (
    EXPECTED_CORRECTION_VERDICTS,
    _annotation_by_id,
    _source_records,
)
from tools.materialize_ai_retention_annotations import (
    DEFAULT_OUTPUT as DEFAULT_ANNOTATIONS,
)


DEFAULT_PRIOR_RESULT = Path(
    "outputs/memory_reflection/"
    "server_deepseek_reflection_lifecycle_v1_round2.json"
)
DEFAULT_OUTPUT = Path(
    "outputs/memory_reflection/"
    "deepseek_reflection_fine_grained_v2.json"
)
MERGE_CHALLENGE_GROUPS = (
    (
        (
            "epmem_235338183f56e8f9e210c6db",
            "epmem_5c6cc61f57a5be34ed19f5db",
        ),
        "ambiguous",
    ),
    (
        (
            "epmem_3642a3c9bc99a8cf40e79a80",
            "epmem_84ca1c1498dbbae35dbbe171",
        ),
        "no_merge",
    ),
    (
        (
            "epmem_5a5cb625e9d94c808d3c7376",
            "epmem_9104926f5d198c42bd778645",
        ),
        "no_merge",
    ),
    (
        (
            "epmem_235338183f56e8f9e210c6db",
            "epmem_bc396ffebfb744c7619bb42c",
        ),
        "ambiguous",
    ),
)


def _rank(memory_id: str) -> str:
    return hashlib.sha256(memory_id.encode("utf-8")).hexdigest()


def _capture_packets(
    observation_path: Path,
    memory_path: Path,
) -> tuple[
    dict[str, ReflectionMemoryPacket],
    dict[str, tuple[ReflectionMemoryPacket, ...]],
]:
    initial, late, relations, _ = build_fixture(memory_path)
    sources = _source_records(observation_path)
    snapshots: dict[str, tuple[ReflectionMemoryPacket, ...]] = {}

    def capture(engine, at: str, phase: str):
        snapshots[phase] = build_reflection_packets(
            engine,
            sources,
            at=at,
        )
        return {"phase": phase, "mode": "capture_only"}

    run_combination(
        "weibull",
        "beta_bound",
        observation_path=observation_path,
        initial_seeds=initial,
        late_seeds=late,
        relations=relations,
        reflection_callback=capture,
    )
    latest: dict[str, ReflectionMemoryPacket] = {}
    for phase in (
        "before_query_replay",
        "between_query_epochs",
        "after_late_memories",
    ):
        for packet in snapshots[phase]:
            latest[packet.memory_id] = packet
    return latest, snapshots


def _prior_error_ids(path: Path) -> set[str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {
        str(row["memory_id"])
        for row in payload["review_quality"]["errors"]
    }


def _select_corrections(
    annotations: dict[str, dict[str, Any]],
    packets: dict[str, ReflectionMemoryPacket],
    prior_errors: set[str],
    holdout_per_category: int,
) -> tuple[list[str], list[str]]:
    regression = sorted(prior_errors & packets.keys())
    by_category: dict[str, list[str]] = defaultdict(list)
    for memory_id, annotation in annotations.items():
        if memory_id in packets and memory_id not in prior_errors:
            by_category[str(annotation["category"])].append(memory_id)
    holdout = []
    for category in sorted(by_category):
        ranked = sorted(by_category[category], key=_rank)
        holdout.extend(ranked[:holdout_per_category])
    return regression, holdout


def _correction_rows(
    proposals,
    annotations: dict[str, dict[str, Any]],
    regression_ids: set[str],
) -> list[dict[str, object]]:
    rows = []
    for proposal in proposals:
        annotation = annotations[proposal.memory_id]
        category = str(annotation["category"])
        expected = EXPECTED_CORRECTION_VERDICTS[category]
        rows.append(
            {
                **proposal.to_dict(),
                "track": (
                    "known_failure_regression"
                    if proposal.memory_id in regression_ids
                    else "stratified_holdout"
                ),
                "category": category,
                "gold_label": annotation["label"],
                "expected_verdicts": sorted(expected),
                "strict_correct": proposal.verdict in expected,
                "negative_action": proposal.penalty_factor < 1.0,
            }
        )
    return rows


def _track_summary(rows: list[dict[str, object]]) -> dict[str, object]:
    by_track: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        by_track[str(row["track"])].append(row)
    return {
        track: {
            "count": len(values),
            "strict_correct": sum(
                bool(row["strict_correct"]) for row in values
            ),
            "strict_accuracy": round(
                sum(bool(row["strict_correct"]) for row in values)
                / max(1, len(values)),
                6,
            ),
            "scope_error_count": sum(
                row["verdict"] == "scope_error" for row in values
            ),
            "unverifiable_count": sum(
                row["verdict"] == "unverifiable" for row in values
            ),
        }
        for track, values in sorted(by_track.items())
    }


def _merge_groups(
    latest: dict[str, ReflectionMemoryPacket],
    snapshots: dict[str, tuple[ReflectionMemoryPacket, ...]],
    annotations: dict[str, dict[str, Any]],
) -> tuple[
    tuple[tuple[ReflectionMemoryPacket, ...], ...],
    dict[frozenset[str], str],
]:
    grouped: dict[tuple[object, ...], list[ReflectionMemoryPacket]] = (
        defaultdict(list)
    )
    for packet in snapshots["after_late_memories"]:
        grouped[packet.semantic_key].append(packet)
    positives = []
    for values in grouped.values():
        if len(values) < 2:
            continue
        categories = {
            str(annotations[packet.memory_id]["category"])
            for packet in values
        }
        if "recent_clear_task_with_redundant_memories" in categories:
            positives.append(
                tuple(sorted(values, key=lambda item: item.memory_id))
            )
    positives.sort(
        key=lambda group: _rank(",".join(item.memory_id for item in group))
    )
    groups = list(positives[:6])
    expected = {
        frozenset(packet.memory_id for packet in group): "merge"
        for group in groups
    }
    for ids, label in MERGE_CHALLENGE_GROUPS:
        if not all(memory_id in latest for memory_id in ids):
            continue
        group = tuple(latest[memory_id] for memory_id in ids)
        key = frozenset(ids)
        if key in expected:
            continue
        groups.append(group)
        expected[key] = label
    return tuple(groups), expected


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
        "--prior-result",
        type=Path,
        default=DEFAULT_PRIOR_RESULT,
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--temporary-directory",
        type=Path,
        default=Path("runtime/reflection_tmp"),
    )
    parser.add_argument("--holdout-per-category", type=int, default=5)
    args = parser.parse_args()

    annotation_payload = json.loads(
        args.annotations.read_text(encoding="utf-8")
    )
    annotations = _annotation_by_id(annotation_payload)
    latest, snapshots = _capture_packets(
        args.observations,
        args.memories,
    )
    prior_errors = _prior_error_ids(args.prior_result)
    regression, holdout = _select_corrections(
        annotations,
        latest,
        prior_errors,
        args.holdout_per_category,
    )
    selected_ids = list(dict.fromkeys((*regression, *holdout)))
    selected = tuple(latest[memory_id] for memory_id in selected_ids)

    client = DeepSeekReflectionClient()
    reflection = LifecycleReflection(
        client,
        temporary_directory=args.temporary_directory,
        correction_batch_size=16,
        merge_batch_size=6,
    )
    corrections = reflection.review_corrections(
        selected,
        round_id="fine_grained_v2",
    )
    correction_rows = _correction_rows(
        corrections,
        annotations,
        set(regression),
    )
    merge_groups, merge_expected = _merge_groups(
        latest,
        snapshots,
        annotations,
    )
    merges = reflection.review_merges(
        merge_groups,
        round_id="fine_grained_v2",
    )
    merge_rows = []
    for proposal in merges:
        key = frozenset(
            (
                proposal.canonical_memory_id,
                *proposal.duplicate_memory_ids,
            )
        )
        expected = merge_expected[key]
        allowed = (
            {"merge", "no_merge"}
            if expected == "ambiguous"
            else {expected}
        )
        strict_scored = expected != "ambiguous"
        merge_rows.append(
            {
                **proposal.to_dict(),
                "expected": expected,
                "allowed_decisions": sorted(allowed),
                "strict_scored": strict_scored,
                "strict_correct": (
                    proposal.decision == expected if strict_scored else None
                ),
                "safe": (
                    proposal.decision in allowed
                    or (
                        expected == "merge"
                        and proposal.decision in {"no_merge", "uncertain"}
                    )
                ),
            }
        )
    remaining = (
        list(args.temporary_directory.iterdir())
        if args.temporary_directory.exists()
        else []
    )
    output = {
        "purpose": (
            "Fine-grained Reflection regression and stratified holdout "
            "using only the fixed lifecycle dataset."
        ),
        "selection": {
            "known_failure_count": len(regression),
            "stratified_holdout_count": len(holdout),
            "holdout_per_category": args.holdout_per_category,
        },
        "correction": {
            "summary": _track_summary(correction_rows),
            "rows": correction_rows,
        },
        "merge": {
            "count": len(merge_rows),
            "strict_scored_count": sum(
                bool(row["strict_scored"]) for row in merge_rows
            ),
            "strict_correct": sum(
                row["strict_correct"] is True for row in merge_rows
            ),
            "strict_accuracy": round(
                sum(row["strict_correct"] is True for row in merge_rows)
                / max(
                    1,
                    sum(
                        bool(row["strict_scored"])
                        for row in merge_rows
                    ),
                ),
                6,
            ),
            "safe_count": sum(bool(row["safe"]) for row in merge_rows),
            "safety_rate": round(
                sum(bool(row["safe"]) for row in merge_rows)
                / max(1, len(merge_rows)),
                6,
            ),
            "positive_merge_recall": round(
                sum(
                    row["expected"] == "merge"
                    and row["decision"] == "merge"
                    for row in merge_rows
                )
                / max(
                    1,
                    sum(
                        row["expected"] == "merge"
                        for row in merge_rows
                    ),
                ),
                6,
            ),
            "rows": merge_rows,
        },
        "api_calls": client.calls,
        "temporary_markdown_deleted": (
            reflection.deleted_temporary_files
        ),
        "temporary_files_remaining": [str(path) for path in remaining],
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
                "correction": output["correction"]["summary"],
                "merge_strict_accuracy": output["merge"][
                    "strict_accuracy"
                ],
                "merge_safety_rate": output["merge"]["safety_rate"],
                "positive_merge_recall": output["merge"][
                    "positive_merge_recall"
                ],
                "api_call_count": len(client.calls),
                "temporary_files_remaining": len(remaining),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
