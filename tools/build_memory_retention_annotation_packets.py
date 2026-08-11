from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from tools.evaluate_memory_lifecycle import (
    DEFAULT_MEMORIES,
    DEFAULT_OBSERVATIONS,
    _day,
    _key,
    _polarity,
    _query_time,
    build_fixture,
)


DEFAULT_OUTPUT = Path(
    "outputs/memory_lifecycle/"
    "ai_retention_annotation_packets_v1.json"
)
DECISION_DAY = 420.0


def _demand_family(case_id: str) -> str:
    normalized = case_id.removeprefix("query:")
    return re.sub(r"_(?:HQ|Q)\d+$", "", normalized)


def _gold_key(item: dict[str, Any]) -> tuple[str, str, str]:
    return _key(
        str(item.get("condition_tag_id") or ""),
        str(item.get("object_tag_id") or ""),
        _polarity(str(item.get("attitude_direction") or "")),
    )


def _matching_gold_evidence(
    case: dict[str, Any],
    semantic_key: tuple[str, str, str],
) -> list[dict[str, object]]:
    evidence = []
    for item in case.get("gold_observations") or ():
        if _gold_key(item) != semantic_key:
            continue
        raw_evidence = item.get("evidence") or {}
        evidence.append(
            {
                "condition_text": raw_evidence.get("condition"),
                "object_text": raw_evidence.get("object"),
                "attitude_text": raw_evidence.get("attitude"),
                "temporal_expressions": dict(
                    raw_evidence.get("temporal") or {}
                ),
                "support": dict(item.get("support") or {}),
            }
        )
    return evidence


def build_annotation_packets(
    memory_path: Path = DEFAULT_MEMORIES,
    observation_path: Path = DEFAULT_OBSERVATIONS,
) -> dict[str, object]:
    episode_payload = json.loads(
        memory_path.read_text(encoding="utf-8")
    )
    observation_payload = json.loads(
        observation_path.read_text(encoding="utf-8")
    )
    raw_memories = {
        str(memory["memory_id"]): dict(memory)
        for episode in episode_payload["episodes"]
        for memory in episode.get("memories") or ()
    }
    cases_by_id = {
        str(case["id"]): case
        for case in observation_payload["cases"]
    }
    initial, late, _, _ = build_fixture(memory_path)
    seeds = tuple(initial) + tuple(late)
    created_days = {
        seed.memory_id: _day(seed.created_at)
        for seed in seeds
        if seed.memory_id in raw_memories
    }

    query_cases = [
        case
        for case in observation_payload["cases"]
        if case.get("source_kind") == "query"
    ]
    demand_by_key: dict[
        tuple[str, str, str],
        list[dict[str, object]],
    ] = defaultdict(list)
    for index, case in enumerate(query_cases):
        day = _day(_query_time(index, len(query_cases)))
        for item in case.get("gold_observations") or ():
            semantic_key = _gold_key(item)
            raw_evidence = item.get("evidence") or {}
            demand_by_key[semantic_key].append(
                {
                    "case_id": str(case["id"]),
                    "demand_family_id": _demand_family(
                        str(case["id"])
                    ),
                    "day": round(day, 6),
                    "query_type": case.get("query_type"),
                    "text": case.get("original_text") or case.get("text"),
                    "condition_text": raw_evidence.get("condition"),
                    "object_text": raw_evidence.get("object"),
                    "attitude_text": raw_evidence.get("attitude"),
                    "temporal_expressions": dict(
                        raw_evidence.get("temporal") or {}
                    ),
                }
            )

    grouped: dict[
        tuple[str, str, str],
        list[dict[str, Any]],
    ] = defaultdict(list)
    for memory in raw_memories.values():
        grouped[
            _key(
                str(memory.get("condition_tag_id") or ""),
                str(memory.get("object_tag_id") or ""),
                str(memory.get("attitude_polarity") or ""),
            )
        ].append(memory)

    object_conditions: dict[str, set[str]] = defaultdict(set)
    opposite_ids: dict[
        tuple[str, str, str],
        list[str],
    ] = defaultdict(list)
    for semantic_key, memories in grouped.items():
        condition, object_id, polarity = semantic_key
        object_conditions[object_id].add(condition)
        opposite = "oppose" if polarity == "support" else "support"
        opposite_ids[(condition, object_id, opposite)].extend(
            str(memory["memory_id"]) for memory in memories
        )

    packets = []
    for group_index, semantic_key in enumerate(sorted(grouped), 1):
        condition, object_id, polarity = semantic_key
        memories = sorted(
            grouped[semantic_key],
            key=lambda item: (
                created_days[str(item["memory_id"])],
                str(item["memory_id"]),
            ),
        )
        demand = sorted(
            demand_by_key.get(semantic_key, ()),
            key=lambda item: (float(item["day"]), str(item["case_id"])),
        )
        latest_demand_day = (
            float(demand[-1]["day"]) if demand else None
        )
        demand_family_ids = sorted(
            {
                str(item["demand_family_id"])
                for item in demand
            }
        )
        members = []
        for memory in memories:
            source_cases = []
            for case_id in memory.get("source_event_ids") or ():
                case = cases_by_id.get(str(case_id))
                if case is None:
                    continue
                source_cases.append(
                    {
                        "case_id": str(case["id"]),
                        "source_kind": case.get("source_kind"),
                        "query_type": case.get("query_type"),
                        "text": (
                            case.get("original_text")
                            or case.get("text")
                        ),
                        "gold_evidence": _matching_gold_evidence(
                            case,
                            semantic_key,
                        ),
                    }
                )
            members.append(
                    {
                        "memory_id": str(memory["memory_id"]),
                        "session_id": str(
                            memory.get("session_id") or ""
                        ),
                        "created_day": round(
                        created_days[str(memory["memory_id"])],
                        6,
                    ),
                        "condition_name": memory.get("condition_name"),
                        "object_name": memory.get("object_name"),
                        "source_evidence_count": len(source_cases),
                        "source_family_count": len(
                            {
                                _demand_family(
                                    str(item["case_id"])
                                )
                                for item in source_cases
                            }
                        ),
                        "source_evidence": source_cases,
                }
            )
        packets.append(
            {
                "group_id": f"retgrp_{group_index:03d}",
                "semantic_key": {
                    "condition_tag_id": condition,
                    "object_tag_id": object_id,
                    "attitude_polarity": polarity,
                },
                "members": members,
                "same_object_condition_count": len(
                    object_conditions[object_id]
                ),
                "same_object_conditions": sorted(
                    object_conditions[object_id]
                ),
                "opposite_attitude_memory_ids": sorted(
                    opposite_ids.get(semantic_key, ())
                ),
                "future_gold_demand": demand,
                "future_demand_family_ids": demand_family_ids,
                "future_demand_family_count": len(
                    demand_family_ids
                ),
                "latest_demand_day": latest_demand_day,
                "days_since_latest_demand": (
                    round(DECISION_DAY - latest_demand_day, 6)
                    if latest_demand_day is not None
                    else None
                ),
            }
        )

    return {
        "purpose": (
            "Blind evidence packets for AI adjudication of final-day "
            "memory retention."
        ),
        "decision_day": DECISION_DAY,
        "labels": {
            "keep": (
                "The memory should remain retrievable at decision day."
            ),
            "forget": (
                "The memory may be lazily removed by decision day."
            ),
            "uncertain": (
                "Evidence is insufficient for a defensible binary label."
            ),
        },
        "annotation_principles": [
            (
                "Judge semantic durability, later demonstrated need, "
                "scope, contradiction, and redundancy together."
            ),
            (
                "A one-off task instruction is not automatically a "
                "durable preference."
            ),
            (
                "Repeated requests matter, but repetition inside one "
                "task is weaker than recurrence across contexts."
            ),
            (
                "A cross-context preference can remain useful without "
                "a recent identical query."
            ),
            (
                "When evidence cannot support a high-confidence binary "
                "decision, use uncertain rather than inventing intent."
            ),
        ],
        "blindness_contract": {
            "excluded_from_packets": [
                "lifecycle strategy name",
                "stability value",
                "confidence value",
                "activation selected by tested algorithm",
                "tested algorithm memory status",
                "forget threshold",
                "existing lifecycle score",
                "predicted observation output",
            ],
            "advisory_only": [
                (
                    "Raw temporal expressions may be read, but no "
                    "upstream short/medium/long prediction is supplied."
                )
            ],
        },
        "memory_count": len(raw_memories),
        "semantic_group_count": len(packets),
        "packets": packets,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--memories",
        type=Path,
        default=DEFAULT_MEMORIES,
    )
    parser.add_argument(
        "--observations",
        type=Path,
        default=DEFAULT_OBSERVATIONS,
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    payload = build_annotation_packets(
        args.memories,
        args.observations,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "output": str(args.output),
                "memory_count": payload["memory_count"],
                "semantic_group_count": payload[
                    "semantic_group_count"
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
