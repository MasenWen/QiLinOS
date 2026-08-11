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
from tools.evaluate_memory_reflection import _source_records


DEFAULT_OUTPUT = Path(
    "outputs/memory_reflection/"
    "deepseek_reflection_pipeline_smoke_v2.json"
)
TARGET_GROUPS = (
    (
        "epmem_1742521b12a20a2ba3cebdfd",
        "epmem_75783558876488be79ff0804",
        "epmem_2def1d08f1098c1e019f3bb6",
        "epmem_65237a743e182609af3cfcc1",
    ),
    (
        "epmem_28dfd7f5a1a1d5f9a65b12ea",
        "epmem_55f4f42d6c51d8ace0a8d85a",
        "epmem_65a40464cc3e27b1b2a9a03f",
        "epmem_34aaf72b709ccdc64714b148",
    ),
    (
        "epmem_a83ab8dcbf01037bde24bc6d",
        "epmem_6d559f35725a56711956237f",
        "epmem_16c0bbdec2663f0b294faa54",
    ),
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--observations", type=Path, default=DEFAULT_OBSERVATIONS)
    parser.add_argument("--memories", type=Path, default=DEFAULT_MEMORIES)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--temporary-directory",
        type=Path,
        default=Path("runtime/reflection_tmp"),
    )
    args = parser.parse_args()

    initial, late, relations, _ = build_fixture(args.memories)
    sources = _source_records(args.observations)
    client = DeepSeekReflectionClient()
    reflection = LifecycleReflection(
        client,
        temporary_directory=args.temporary_directory,
        correction_batch_size=12,
        merge_batch_size=4,
    )
    selected_ids = {
        memory_id
        for group in TARGET_GROUPS
        for memory_id in group
    }

    def reflect_selected(engine, at: str, phase: str):
        if phase != "after_late_memories":
            return {"phase": phase, "mode": "skipped"}
        packets = tuple(
            packet
            for packet in build_reflection_packets(
                engine,
                sources,
                at=at,
            )
            if packet.memory_id in selected_ids
        )
        return reflection.run(
            engine,
            packets,
            at=at,
            round_id="pipeline_smoke_v2",
        )

    result, engine = run_combination(
        "weibull",
        "beta_bound",
        observation_path=args.observations,
        initial_seeds=initial,
        late_seeds=late,
        relations=relations,
        reflection_callback=reflect_selected,
    )
    trace = result["reflection"][-1]
    canonical_ids = {
        str(proposal["canonical_memory_id"])
        for proposal in trace["merge_proposals"]
        if proposal["decision"] == "merge"
    }
    canonical_states = []
    for memory_id in sorted(canonical_ids):
        state = engine.states[memory_id]
        canonical_states.append(
            {
                "memory_id": memory_id,
                "status": state.status,
                "activation_count": state.activation_count,
                "last_activated_at": state.last_activated_at,
                "source_event_count": len(
                    state.seed.metadata.get("source_event_ids") or ()
                ),
                "evidence_count": len(state.seed.evidence),
                "reflection_penalty": state.reflection_penalty,
            }
        )
    corrections = {
        str(proposal["memory_id"]): proposal
        for proposal in trace["correction_proposals"]
    }
    output = {
        "purpose": (
            "Actual merge-first Reflection pipeline smoke using three "
            "fixed duplicate groups from the lifecycle dataset."
        ),
        "target_group_count": len(TARGET_GROUPS),
        "merge_decisions": trace["merge_proposals"],
        "merged_memory_count": len(trace["merged_memory_ids"]),
        "reviewed_after_merge_count": trace["reviewed_memory_count"],
        "canonical_corrections": [
            corrections[memory_id]
            for memory_id in sorted(canonical_ids)
            if memory_id in corrections
        ],
        "canonical_states": canonical_states,
        "api_calls": client.calls,
        "temporary_markdown_deleted": (
            reflection.deleted_temporary_files
        ),
        "temporary_files_remaining": (
            [
                str(path)
                for path in args.temporary_directory.iterdir()
            ]
            if args.temporary_directory.exists()
            else []
        ),
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
                "merge_count": sum(
                    proposal["decision"] == "merge"
                    for proposal in trace["merge_proposals"]
                ),
                "canonical_supported_count": sum(
                    proposal["verdict"] == "supported"
                    for proposal in output["canonical_corrections"]
                ),
                "canonical_penalties": [
                    state["reflection_penalty"]
                    for state in canonical_states
                ],
                "api_call_count": len(client.calls),
                "temporary_files_remaining": len(
                    output["temporary_files_remaining"]
                ),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
