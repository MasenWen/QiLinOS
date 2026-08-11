from __future__ import annotations

import argparse
import json
from pathlib import Path

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
from tools.evaluate_memory_reflection import (
    EXPECTED_CORRECTION_VERDICTS,
    _annotation_by_id,
    _source_records,
)
from tools.materialize_ai_retention_annotations import (
    DEFAULT_OUTPUT as DEFAULT_ANNOTATIONS,
)


DEFAULT_OUTPUT = Path(
    "outputs/memory_reflection/deepseek_skill_smoke_v1.json"
)


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
        default=Path("runtime/reflection_tmp"),
    )
    args = parser.parse_args()

    annotation_payload = json.loads(
        args.annotations.read_text(encoding="utf-8")
    )
    annotations = _annotation_by_id(annotation_payload)
    initial, late, relations, _ = build_fixture(args.memories)
    sources = _source_records(args.observations)
    snapshots = {}

    def capture_packets(engine, at: str, phase: str):
        snapshots[phase] = build_reflection_packets(
            engine,
            sources,
            at=at,
        )
        return {"phase": phase, "mode": "capture_only"}

    run_combination(
        "weibull",
        "beta_bound",
        observation_path=args.observations,
        initial_seeds=initial,
        late_seeds=late,
        relations=relations,
        reflection_callback=capture_packets,
    )
    packet_by_id = {}
    for phase in (
        "before_query_replay",
        "between_query_epochs",
        "after_late_memories",
    ):
        for packet in snapshots[phase]:
            packet_by_id[packet.memory_id] = packet
    packets = tuple(packet_by_id.values())

    selected_ids = []
    seen_categories = set()
    for annotation in annotation_payload["annotations"]:
        category = str(annotation["category"])
        if category in seen_categories:
            continue
        memory_id = str(annotation["memory_id"])
        if memory_id not in packet_by_id:
            continue
        selected_ids.append(memory_id)
        seen_categories.add(category)
    selected = tuple(packet_by_id[memory_id] for memory_id in selected_ids)

    client = DeepSeekReflectionClient()
    reflection = LifecycleReflection(
        client,
        temporary_directory=args.temporary_directory,
        correction_batch_size=12,
        merge_batch_size=4,
    )
    corrections = reflection.review_corrections(
        selected,
        round_id="skill_smoke",
    )
    correction_rows = []
    for proposal in corrections:
        annotation = annotations[proposal.memory_id]
        expected = EXPECTED_CORRECTION_VERDICTS[
            str(annotation["category"])
        ]
        correction_rows.append(
            {
                **proposal.to_dict(),
                "category": annotation["category"],
                "gold_label": annotation["label"],
                "expected_verdicts": sorted(expected),
                "correct": proposal.verdict in expected,
            }
        )
    certain_correction_rows = [
        row
        for row in correction_rows
        if row["gold_label"] != "uncertain"
    ]

    grouped = {}
    for packet in snapshots["after_late_memories"]:
        grouped.setdefault(packet.semantic_key, []).append(packet)
    merge_groups = []
    for values in grouped.values():
        if len(values) <= 1:
            continue
        categories = {
            str(annotations[packet.memory_id]["category"])
            for packet in values
        }
        if "recent_clear_task_with_redundant_memories" in categories:
            merge_groups.append(
                tuple(sorted(values, key=lambda item: item.memory_id))
            )
        if len(merge_groups) == 4:
            break
    merges = reflection.review_merges(
        tuple(merge_groups),
        round_id="skill_smoke",
    )
    merge_rows = [
        {
            **proposal.to_dict(),
            "expected": "merge",
            "correct": proposal.decision == "merge",
        }
        for proposal in merges
    ]
    remaining = (
        list(args.temporary_directory.iterdir())
        if args.temporary_directory.exists()
        else []
    )
    output = {
        "model": client.model,
        "correction": {
            "count": len(correction_rows),
            "correct": sum(row["correct"] for row in correction_rows),
            "accuracy": round(
                sum(row["correct"] for row in correction_rows)
                / max(1, len(correction_rows)),
                6,
            ),
            "certain_count": len(certain_correction_rows),
            "certain_correct": sum(
                row["correct"] for row in certain_correction_rows
            ),
            "certain_accuracy": round(
                sum(row["correct"] for row in certain_correction_rows)
                / max(1, len(certain_correction_rows)),
                6,
            ),
            "rows": correction_rows,
        },
        "merge": {
            "count": len(merge_rows),
            "correct": sum(row["correct"] for row in merge_rows),
            "accuracy": round(
                sum(row["correct"] for row in merge_rows)
                / max(1, len(merge_rows)),
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
                "correction_accuracy": output["correction"]["accuracy"],
                "correction_certain_accuracy": (
                    output["correction"]["certain_accuracy"]
                ),
                "merge_accuracy": output["merge"]["accuracy"],
                "api_call_count": len(client.calls),
                "temporary_files_remaining": len(remaining),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
