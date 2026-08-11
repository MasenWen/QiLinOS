from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.memory_engine.reflection import (
    DeepSeekReflectionClient,
    LifecycleReflection,
    ReflectionMemoryPacket,
    ReflectionSource,
)


DEFAULT_OUTPUT = Path(
    "runtime/generalization/root_dataset_reflection_server.json"
)
REVIEWED_AT = "2026-06-20T12:00:00+08:00"


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _split_ids(value: str) -> tuple[str, ...]:
    return tuple(item for item in value.split("|") if item)


def _condition_tags(memory: Mapping[str, str]) -> tuple[str, ...]:
    try:
        values = json.loads(memory["condition_json"] or "{}")
    except json.JSONDecodeError:
        values = {}
    return tuple(
        f"condition:{key}={json.dumps(value, ensure_ascii=False)}"
        for key, value in sorted(values.items())
    )


def _source_kind(value: str) -> str:
    if value in {"EXPLICIT_USER", "MANUAL_CONFIG"}:
        return "text"
    return "log"


def _days_between(start: str, end: str) -> float:
    left = datetime.fromisoformat(start.replace("Z", "+00:00"))
    right = datetime.fromisoformat(end.replace("Z", "+00:00"))
    return max(0.0, (right - left).total_seconds() / 86400.0)


def _version_id(memory_id: str, source_ids: Sequence[str]) -> str:
    material = "|".join((memory_id, *source_ids))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:20]


def _memory_packet(
    memory: Mapping[str, str],
    evidence_by_id: Mapping[str, Mapping[str, str]],
    raw_by_id: Mapping[str, Mapping[str, str]],
    privacy_by_event: Mapping[str, Mapping[str, str]],
) -> ReflectionMemoryPacket:
    evidence_rows = [
        evidence_by_id[evidence_id]
        for evidence_id in _split_ids(memory["support_evidence_ids"])
        if evidence_id in evidence_by_id
    ]
    source_ids = tuple(
        dict.fromkeys(
            source_id
            for evidence in evidence_rows
            for source_id in _split_ids(evidence["source_event_ids"])
        )
    )
    sources = []
    for source_id in source_ids:
        raw = raw_by_id.get(source_id)
        privacy = privacy_by_event.get(source_id, {})
        visible = (
            raw is not None
            and privacy.get("decision", "ALLOW") == "ALLOW"
            and privacy.get("raw_value_allowed_in_memory", "true")
            == "true"
        )
        sources.append(
            ReflectionSource(
                source_id=source_id,
                source_kind=(
                    _source_kind(evidence_rows[0]["source_mode"])
                    if evidence_rows
                    else "unknown"
                ),
                text=(
                    str(raw["raw_content"])
                    if visible and raw is not None
                    else "[SOURCE REDACTED]"
                ),
                privacy_status="available" if visible else "redacted",
            )
        )
    latest_evidence = max(
        (
            evidence["observed_time"]
            for evidence in evidence_rows
        ),
        default=memory["valid_from"],
    )
    tier = memory["lifecycle_tier"]
    return ReflectionMemoryPacket(
        memory_id=memory["memory_id"],
        version_id=_version_id(memory["memory_id"], source_ids),
        user_id=memory["user_id"],
        condition_tag_ids=_condition_tags(memory),
        object_tag_ids=(f"slot:{memory['slot']}",),
        attitude_polarity="support",
        temporal_label={
            "short": "temporal_short",
            "mid": "temporal_medium",
            "long": "temporal_long",
            "erased": "temporal_short",
        }.get(tier, "temporal_medium"),
        created_at=memory["valid_from"],
        reviewed_at=REVIEWED_AT,
        activation_count=0,
        last_activated_at="",
        first_activated_at="",
        activation_span_days=0.0,
        latest_evidence_at=latest_evidence,
        inactivity_days=_days_between(latest_evidence, REVIEWED_AT),
        obsolete_after_days={
            "short": 21.0,
            "mid": 75.0,
            "long": 240.0,
            "erased": 0.0,
        }.get(tier, 75.0),
        independent_evidence_count=len(
            {
                evidence["independent_unit_id"]
                for evidence in evidence_rows
                if evidence["independent_unit_id"]
            }
        ),
        confidence=float(memory["confidence"]),
        stability=float(memory["stability"]),
        source_refs=tuple(sources),
        source_evidence_count=len(source_ids),
    )


def _event_packet(
    row: Mapping[str, str],
) -> ReflectionMemoryPacket:
    memory_id = f"event-memory:{row['event_id']}"
    return ReflectionMemoryPacket(
        memory_id=memory_id,
        version_id=_version_id(memory_id, (row["event_id"],)),
        user_id=row["user_id"],
        condition_tag_ids=(f"task:{row['task_type']}",),
        object_tag_ids=("slot:diary_save_execution",),
        attitude_polarity="support",
        temporal_label="temporal_short",
        created_at=row["timestamp"],
        reviewed_at=REVIEWED_AT,
        activation_count=0,
        last_activated_at="",
        first_activated_at="",
        activation_span_days=0.0,
        latest_evidence_at=row["timestamp"],
        inactivity_days=_days_between(row["timestamp"], REVIEWED_AT),
        obsolete_after_days=21.0,
        independent_evidence_count=1,
        confidence=float(row["quality_score"]),
        stability=0.55,
        source_refs=(
            ReflectionSource(
                source_id=row["event_id"],
                source_kind=row["source_type"],
                text=row["raw_content"],
            ),
        ),
        source_evidence_count=1,
    )


def _accuracy(
    proposals: Mapping[str, str],
    expected: Mapping[str, set[str]],
) -> dict[str, Any]:
    rows = [
        {
            "memory_id": memory_id,
            "predicted": proposals.get(memory_id, "missing"),
            "acceptable": sorted(acceptable),
            "correct": proposals.get(memory_id) in acceptable,
        }
        for memory_id, acceptable in expected.items()
    ]
    return {
        "count": len(rows),
        "correct": sum(row["correct"] for row in rows),
        "accuracy": (
            sum(row["correct"] for row in rows) / len(rows)
            if rows
            else 1.0
        ),
        "rows": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--workspace-root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    base = (
        args.workspace_root
        / "os_agent_memory_benchmark_v1"
        / "os_agent_memory_benchmark_v1"
    )
    memories = [
        row
        for row in _rows(base / "data" / "memory_ground_truth.csv")
        if row["split"] == "test"
    ]
    evidence = [
        row
        for row in _rows(base / "data" / "evidence_ground_truth.csv")
        if row["split"] == "test"
    ]
    raw = [
        row
        for row in _rows(base / "data" / "raw_events.csv")
        if row["split"] == "test"
    ]
    privacy = [
        row
        for row in _rows(base / "data" / "privacy_decisions.csv")
        if row["user_id"] in {"U025", "U026"}
    ]
    memory_by_id = {row["memory_id"]: row for row in memories}
    evidence_by_id = {row["evidence_id"]: row for row in evidence}
    raw_by_id = {row["event_id"]: row for row in raw}
    privacy_by_event = {row["event_id"]: row for row in privacy}

    correction_ids = (
        "MEM-U025-DIARY-DIR-V2",
        "MEM-U026-DIARY-DIR-V2",
        "MEM-U025-MAIL-CONFIRM",
        "MEM-U026-MAIL-CONFIRM",
        "MEM-U025-PAUSED-DIARY",
        "MEM-U026-PAUSED-DIARY",
        "MEM-U025-DIARY-DIR-V1",
        "MEM-U026-DIARY-DIR-V1",
        "MEM-U025-PRIVATE-EMAIL",
        "MEM-U026-PRIVATE-EMAIL",
    )
    packets_by_id = {
        memory_id: _memory_packet(
            memory_by_id[memory_id],
            evidence_by_id,
            raw_by_id,
            privacy_by_event,
        )
        for memory_id in correction_ids
    }
    for memory in memories:
        if memory["user_id"] not in {"U025", "U026"}:
            continue
        packets_by_id.setdefault(
            memory["memory_id"],
            _memory_packet(
                memory,
                evidence_by_id,
                raw_by_id,
                privacy_by_event,
            ),
        )

    strict_expected = {
        memory_id: {"supported"}
        for memory_id in correction_ids[:6]
    }
    strict_expected.update(
        {
            "MEM-U025-PRIVATE-EMAIL": {"unverifiable"},
            "MEM-U026-PRIVATE-EMAIL": {"unverifiable"},
        }
    )
    supersession_expected = {
        "MEM-U025-DIARY-DIR-V1": {
            "contradicted",
            "obsolete_task_state",
        },
        "MEM-U026-DIARY-DIR-V1": {
            "contradicted",
            "obsolete_task_state",
        },
    }

    negative_group_ids = (
        (
            "MEM-U025-DIARY-DIR-V1",
            "MEM-U025-DIARY-DIR-V2",
        ),
        (
            "MEM-U026-DIARY-DIR-V1",
            "MEM-U026-DIARY-DIR-V2",
        ),
        (
            "MEM-U025-REPORT-INTERNAL-PDF",
            "MEM-U025-REPORT-DRAFT-DOCX",
        ),
        (
            "MEM-U026-REPORT-INTERNAL-PDF",
            "MEM-U026-REPORT-DRAFT-DOCX",
        ),
        (
            "MEM-U025-REPORT-EXTERNAL-PDF",
            "MEM-U025-REPORT-EXTERNAL-DOCX",
        ),
        (
            "MEM-U026-REPORT-EXTERNAL-PDF",
            "MEM-U026-REPORT-EXTERNAL-DOCX",
        ),
    )
    merge_groups = [
        tuple(packets_by_id[memory_id] for memory_id in group)
        for group in negative_group_ids
    ]
    positive_group_ids = []
    for user_id in ("U025", "U026"):
        ids = (
            f"EV-{user_id}-008",
            f"EV-{user_id}-009",
        )
        group = tuple(_event_packet(raw_by_id[event_id]) for event_id in ids)
        merge_groups.append(group)
        positive_group_ids.append(
            frozenset(packet.memory_id for packet in group)
        )

    client = DeepSeekReflectionClient()
    reflection = LifecycleReflection(
        client,
        temporary_directory=Path("runtime/reflection_tmp"),
        correction_batch_size=16,
        merge_batch_size=8,
    )
    corrections = reflection.review_corrections(
        tuple(packets_by_id[memory_id] for memory_id in correction_ids),
        round_id="root-generalization-correction-v1",
    )
    merges = reflection.review_merges(
        tuple(merge_groups),
        round_id="root-generalization-merge-v1",
    )
    verdicts = {
        proposal.memory_id: proposal.verdict
        for proposal in corrections
    }
    merge_by_members = {
        frozenset(
            (
                proposal.canonical_memory_id,
                *proposal.duplicate_memory_ids,
            )
        ): proposal
        for proposal in merges
    }
    merge_rows = []
    for group in merge_groups:
        members = frozenset(packet.memory_id for packet in group)
        proposal = merge_by_members.get(members)
        expected = (
            "merge" if members in positive_group_ids else "no_merge"
        )
        predicted = proposal.decision if proposal else "missing"
        merge_rows.append(
            {
                "memory_ids": sorted(members),
                "expected": expected,
                "predicted": predicted,
                "correct": predicted == expected,
                "rationale": proposal.rationale if proposal else "",
            }
        )

    output = {
        "schema_version": "root_dataset.reflection_audit.v1",
        "dataset": "os_agent_memory_benchmark_v1/test",
        "reviewed_at": REVIEWED_AT,
        "correction": {
            "strict_source_grounded": _accuracy(
                verdicts,
                strict_expected,
            ),
            "supersession_context_challenge": _accuracy(
                verdicts,
                supersession_expected,
            ),
            "proposals": [
                proposal.to_dict() for proposal in corrections
            ],
            "scope_note": (
                "The strict score covers current source-supported memories "
                "and privacy-redacted memories. Historical memories are "
                "reported separately because their own source remains "
                "locally true while the successor context is absent from "
                "the current ReflectionMemoryPacket."
            ),
        },
        "merge": {
            "group_count": len(merge_rows),
            "positive_count": len(positive_group_ids),
            "negative_count": len(negative_group_ids),
            "correct": sum(row["correct"] for row in merge_rows),
            "accuracy": (
                sum(row["correct"] for row in merge_rows)
                / len(merge_rows)
            ),
            "rows": merge_rows,
            "scope_note": (
                "Positive groups come from benchmark SAME_EXECUTION event "
                "pairs. Negative groups cover supersession, conditional "
                "coexistence and unresolved contradiction."
            ),
        },
        "api": {
            "call_count": len(client.calls),
            "calls": client.calls,
            "temporary_files_deleted": reflection.deleted_temporary_files,
        },
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
                "strict_correction": output["correction"][
                    "strict_source_grounded"
                ],
                "supersession": output["correction"][
                    "supersession_context_challenge"
                ],
                "merge": {
                    key: output["merge"][key]
                    for key in (
                        "group_count",
                        "positive_count",
                        "negative_count",
                        "correct",
                        "accuracy",
                    )
                },
                "api_call_count": len(client.calls),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
