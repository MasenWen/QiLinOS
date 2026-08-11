from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any


DEFAULT_PACKETS = Path(
    "outputs/memory_lifecycle/"
    "ai_retention_annotation_packets_v1.json"
)
DEFAULT_OUTPUT = Path(
    "outputs/memory_lifecycle/"
    "ai_retention_annotations_v1.json"
)


# These sets are an explicit blind AI adjudication over every semantic
# group. No packet field or lifecycle output is used to derive membership.
GLOBAL_CONTEXT_LOSS_GROUPS = {
    *(f"retgrp_{index:03d}" for index in range(1, 27)),
    *(f"retgrp_{index:03d}" for index in range(28, 34)),
    *(f"retgrp_{index:03d}" for index in range(36, 39)),
}
OLD_TASK_GROUPS = {
    "retgrp_040",
    "retgrp_042",
    "retgrp_046",
    "retgrp_047",
    "retgrp_049",
    "retgrp_050",
    "retgrp_052",
    "retgrp_053",
    "retgrp_054",
    "retgrp_057",
    "retgrp_058",
    "retgrp_059",
    "retgrp_060",
    "retgrp_064",
    "retgrp_066",
    "retgrp_067",
    "retgrp_072",
    "retgrp_075",
    "retgrp_077",
    "retgrp_078",
    "retgrp_079",
    "retgrp_080",
    "retgrp_081",
    "retgrp_082",
    "retgrp_085",
    "retgrp_086",
    "retgrp_088",
    "retgrp_094",
    "retgrp_098",
}
CONTRADICTED_GROUPS = {
    "retgrp_045",
    "retgrp_056",
    "retgrp_061",
    "retgrp_065",
    "retgrp_073",
    "retgrp_089",
    "retgrp_097",
}
AMBIGUOUS_GLOBAL_GROUPS = {"retgrp_039"}
DURABLE_BUT_CONFLICTED_GROUPS = {
    "retgrp_027",
    "retgrp_034",
    "retgrp_035",
}
AMBIGUOUS_RECENT_GROUPS = {
    "retgrp_043",
    "retgrp_071",
    "retgrp_084",
    "retgrp_096",
}
KEEP_REPRESENTATIVE_BY_GROUP = {
    "retgrp_041": "epmem_0da4ae69d12e50868a009c25",
    "retgrp_044": "epmem_ca7ada2d3271874793315ef4",
    "retgrp_048": "epmem_6908333b7808f932446121a8",
    "retgrp_051": "epmem_083d6f6b062174ca069371a3",
    "retgrp_055": "epmem_65237a743e182609af3cfcc1",
    "retgrp_062": "epmem_afeb7a4989826e4f5839538a",
    "retgrp_063": "epmem_16c0bbdec2663f0b294faa54",
    "retgrp_068": "epmem_fa41bcf95383954eed236f08",
    "retgrp_069": "epmem_86b226d3c81adfa87c990e11",
    "retgrp_070": "epmem_a98a884eed61f1698628f1f7",
    "retgrp_074": "epmem_a99021c3e98edcfe0ce884c6",
    "retgrp_076": "epmem_ca6b48e70aa188059c893180",
    "retgrp_083": "epmem_f2e9b4f4cd5aa04606677323",
    "retgrp_087": "epmem_831c62f6ab2966419b2851b5",
    "retgrp_090": "epmem_13e71ae384051bf0a24efffa",
    "retgrp_091": "epmem_f9fc367282d3a1d2474392dc",
    "retgrp_092": "epmem_34aaf72b709ccdc64714b148",
    "retgrp_093": "epmem_9cfa540b47d73f7e453fe945",
    "retgrp_095": "epmem_fa09184ea5527872d89a0065",
}


def _group_review(group_id: str) -> dict[str, object]:
    if group_id in GLOBAL_CONTEXT_LOSS_GROUPS:
        return {
            "category": "context_loss_from_one_off_task",
            "semantic_vote": "forget",
            "chronology_vote": "forget",
            "safety_vote": "forget",
            "group_rationale": (
                "The conditionless record reads as a specific task whose "
                "scene was lost, not a demonstrated cross-context "
                "preference. Retaining it globally risks false transfer."
            ),
        }
    if group_id in OLD_TASK_GROUPS:
        return {
            "category": "completed_task_without_late_recurrence",
            "semantic_vote": "forget",
            "chronology_vote": "forget",
            "safety_vote": "forget",
            "group_rationale": (
                "The content is tied to a concrete file operation. Any "
                "same-family demand is too remote from decision day to "
                "justify indefinite retention."
            ),
        }
    if group_id in CONTRADICTED_GROUPS:
        return {
            "category": "contradicted_or_inverted_attitude",
            "semantic_vote": "forget",
            "chronology_vote": "forget",
            "safety_vote": "forget",
            "group_rationale": (
                "The stored attitude is unsupported or contradicted by "
                "the source instruction and later demand. Keeping it "
                "would preserve a misleading preference."
            ),
        }
    if group_id in AMBIGUOUS_GLOBAL_GROUPS:
        return {
            "category": "recent_but_unsafe_global_ambiguity",
            "semantic_vote": "forget",
            "chronology_vote": "keep",
            "safety_vote": "forget",
            "group_rationale": (
                "Later requests refer to prior workflows, but this "
                "conditionless label cannot identify which workflow. "
                "Specific condition memories are safer evidence."
            ),
        }
    if group_id in DURABLE_BUT_CONFLICTED_GROUPS:
        return {
            "category": "possible_durable_display_preference",
            "semantic_vote": "uncertain",
            "chronology_vote": "forget",
            "safety_vote": "uncertain",
            "group_rationale": (
                "The wording could express a reusable display habit, "
                "but scope is missing and the evidence is stale or "
                "internally conflicting."
            ),
        }
    if group_id in AMBIGUOUS_RECENT_GROUPS:
        return {
            "category": "recent_conditioned_but_semantically_ambiguous",
            "semantic_vote": "uncertain",
            "chronology_vote": "keep",
            "safety_vote": "uncertain",
            "group_rationale": (
                "The condition is known and later demand exists, but "
                "the object only says to reuse an unspecified prior "
                "workflow. A confident binary label would invent detail."
            ),
        }
    if group_id in KEEP_REPRESENTATIVE_BY_GROUP:
        return {
            "category": "recent_clear_task_with_redundant_memories",
            "semantic_vote": "forget",
            "chronology_vote": "keep",
            "safety_vote": "keep",
            "group_rationale": (
                "The task is not a universal preference, but clear "
                "same-semantic demand reappears late enough that one "
                "well-supported representative should remain."
            ),
        }
    raise ValueError(f"unadjudicated_group:{group_id}")


def materialize_annotations(
    packet_path: Path = DEFAULT_PACKETS,
) -> dict[str, object]:
    payload = json.loads(packet_path.read_text(encoding="utf-8"))
    packet_groups = {
        str(packet["group_id"]) for packet in payload["packets"]
    }
    adjudicated_groups = (
        GLOBAL_CONTEXT_LOSS_GROUPS
        | OLD_TASK_GROUPS
        | CONTRADICTED_GROUPS
        | AMBIGUOUS_GLOBAL_GROUPS
        | DURABLE_BUT_CONFLICTED_GROUPS
        | AMBIGUOUS_RECENT_GROUPS
        | set(KEEP_REPRESENTATIVE_BY_GROUP)
    )
    if packet_groups != adjudicated_groups:
        missing = sorted(packet_groups - adjudicated_groups)
        extra = sorted(adjudicated_groups - packet_groups)
        raise ValueError(
            f"adjudication_coverage_error:missing={missing}:extra={extra}"
        )

    annotations = []
    group_adjudications = []
    for packet in payload["packets"]:
        group_id = str(packet["group_id"])
        review = _group_review(group_id)
        member_labels = []
        for member in packet["members"]:
            memory_id = str(member["memory_id"])
            if group_id in DURABLE_BUT_CONFLICTED_GROUPS:
                label = "uncertain"
                confidence = 0.58
                rationale = (
                    "Potentially durable preference, but current evidence "
                    "cannot resolve scope and contradiction."
                )
            elif group_id in AMBIGUOUS_RECENT_GROUPS:
                label = "uncertain"
                confidence = 0.62
                rationale = (
                    "Recent need is real, but the remembered workflow is "
                    "not semantically specified enough for binary review."
                )
            elif group_id in KEEP_REPRESENTATIVE_BY_GROUP:
                representative = KEEP_REPRESENTATIVE_BY_GROUP[group_id]
                if memory_id == representative:
                    label = "keep"
                    confidence = 0.88
                    rationale = (
                        "Chosen as the single recent, semantically clear "
                        "representative with the strongest complete "
                        "evidence in its duplicate group."
                    )
                else:
                    label = "forget"
                    confidence = 0.91
                    rationale = (
                        "Semantically duplicated by the retained "
                        "representative; keeping both would multiply "
                        "activation without adding user intent."
                    )
            else:
                label = "forget"
                confidence = (
                    0.97
                    if group_id in CONTRADICTED_GROUPS
                    else 0.93
                )
                rationale = str(review["group_rationale"])
            member_labels.append(
                {
                    "memory_id": memory_id,
                    "label": label,
                    "confidence": confidence,
                    "rationale": rationale,
                }
            )
            annotations.append(
                {
                    "memory_id": memory_id,
                    "group_id": group_id,
                    "label": label,
                    "confidence": confidence,
                    "semantic_vote": review["semantic_vote"],
                    "chronology_vote": review["chronology_vote"],
                    "safety_vote": review["safety_vote"],
                    "category": review["category"],
                    "rationale": rationale,
                    "evidence_summary": {
                        "created_day": member["created_day"],
                        "source_evidence_count": member[
                            "source_evidence_count"
                        ],
                        "future_demand_family_count": packet[
                            "future_demand_family_count"
                        ],
                        "latest_demand_day": packet[
                            "latest_demand_day"
                        ],
                        "days_since_latest_demand": packet[
                            "days_since_latest_demand"
                        ],
                        "same_object_condition_count": packet[
                            "same_object_condition_count"
                        ],
                        "opposite_attitude_memory_count": len(
                            packet["opposite_attitude_memory_ids"]
                        ),
                    },
                }
            )
        group_adjudications.append(
            {
                "group_id": group_id,
                "semantic_key": packet["semantic_key"],
                **review,
                "member_labels": member_labels,
            }
        )

    counts = Counter(item["label"] for item in annotations)
    return {
        "purpose": (
            "Blind AI-adjudicated final-day retention labels for the "
            "memory lifecycle benchmark."
        ),
        "schema_version": "memory.retention.ai_annotation.v1",
        "decision_day": payload["decision_day"],
        "decision_source": (
            "Explicit AI semantic adjudication over blind evidence "
            "packets; labels are not inferred by a scoring rule."
        ),
        "review_protocol": {
            "semantic_pass": (
                "Distinguish durable preference from one-off task state."
            ),
            "chronology_pass": (
                "Examine independent demand families and elapsed time."
            ),
            "safety_pass": (
                "Compare harm from stale retention, contradiction, "
                "context transfer, redundancy, and premature forgetting."
            ),
            "adjudication": (
                "Resolve perspectives item by item; preserve uncertain "
                "when a defensible binary answer is unavailable."
            ),
            "independence_note": (
                "The three passes are independent reasoning perspectives "
                "from one Codex AI reviewer, not three separately hosted "
                "models."
            ),
        },
        "blindness_contract": payload["blindness_contract"],
        "memory_count": len(annotations),
        "group_count": len(group_adjudications),
        "label_counts": dict(sorted(counts.items())),
        "binary_scored_count": counts["keep"] + counts["forget"],
        "uncertain_count": counts["uncertain"],
        "group_adjudications": group_adjudications,
        "annotations": annotations,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--packets",
        type=Path,
        default=DEFAULT_PACKETS,
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    payload = materialize_annotations(args.packets)
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
                "group_count": payload["group_count"],
                "label_counts": payload["label_counts"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
