from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


DEFAULT_OUTPUT = Path(
    "runtime/generalization/mainline_observation_holdout_v1.json"
)
TEMPORAL_LABELS = (
    "temporal_short",
    "temporal_medium",
    "temporal_long",
)


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _split_ids(value: str) -> tuple[str, ...]:
    return tuple(item for item in value.split("|") if item)


def _slug(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", value.casefold()).strip("_")
    if normalized:
        return normalized[:72]
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def _normalized_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().casefold()


def _take(values: Iterable[str], limit: int) -> tuple[str, ...]:
    return tuple(dict.fromkeys(value for value in values if value))[:limit]


def _distractors(
    correct: Sequence[str],
    pool: Sequence[str],
    *,
    key: str,
    count: int,
) -> list[str]:
    correct_set = set(correct)
    candidates = [value for value in pool if value not in correct_set]
    candidates.sort(
        key=lambda value: hashlib.sha256(
            f"{key}|{value}".encode("utf-8")
        ).hexdigest()
    )
    return [*correct, *candidates[:count]]


def _tag(
    *,
    tag_id: str,
    name: str,
    group: str,
    aliases: Iterable[str],
    prototypes: Iterable[str],
) -> dict[str, Any]:
    return {
        "tag_id": tag_id,
        "name": name,
        "groups": [group],
        "aliases": list(_take((name, *aliases), 8)),
        "prototypes": list(_take(prototypes, 4))
        or [f"{group} label for {name}"],
    }


def _v1_cases(
    root: Path,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    base = (
        root
        / "os_agent_memory_benchmark_v1"
        / "os_agent_memory_benchmark_v1"
    )
    events = _rows(base / "data" / "raw_events.csv")
    evidence = _rows(base / "data" / "evidence_ground_truth.csv")
    memories = _rows(base / "data" / "memory_ground_truth.csv")
    privacy = _rows(base / "data" / "privacy_decisions.csv")
    event_by_id = {row["event_id"]: row for row in events}
    privacy_by_event = {
        row["event_id"]: row for row in privacy
    }

    train_events = [row for row in events if row["split"] == "train"]
    condition_examples: dict[str, list[str]] = defaultdict(list)
    condition_aliases: dict[str, list[str]] = defaultdict(list)
    for row in train_events:
        task = row["task_type"]
        condition_examples[task].append(row["raw_content"])
        condition_aliases[task].extend((row["app"], task.replace("_", " ")))

    evidence_by_id = {row["evidence_id"]: row for row in evidence}
    object_examples: dict[str, list[str]] = defaultdict(list)
    object_aliases: dict[str, list[str]] = defaultdict(list)
    for memory in memories:
        if memory["split"] != "train":
            continue
        slot = memory["slot"]
        object_aliases[slot].extend(
            (slot.replace("_", " "), memory["memory_type"])
        )
        for evidence_id in _split_ids(memory["support_evidence_ids"]):
            source = evidence_by_id.get(evidence_id)
            if source is None:
                continue
            for event_id in _split_ids(source["source_event_ids"]):
                event = event_by_id.get(event_id)
                if event is not None:
                    object_examples[slot].append(event["raw_content"])

    condition_ids = {
        value: f"holdout:v1:condition:{_slug(value)}"
        for value in sorted(condition_examples)
    }
    object_ids = {
        value: f"holdout:v1:object:{_slug(value)}"
        for value in sorted(object_examples)
    }
    tags = [
        *(
            _tag(
                tag_id=condition_ids[name],
                name=name,
                group="condition",
                aliases=condition_aliases[name],
                prototypes=condition_examples[name],
            )
            for name in sorted(condition_ids)
        ),
        *(
            _tag(
                tag_id=object_ids[name],
                name=name,
                group="object",
                aliases=object_aliases[name],
                prototypes=object_examples[name],
            )
            for name in sorted(object_ids)
        ),
    ]

    test_evidence = {
        row["evidence_id"]: row
        for row in evidence
        if row["split"] == "test"
        and row["source_mode"] in {"EXPLICIT_USER", "MANUAL_CONFIG"}
        and row["eligible_for_preference_learning"].casefold() == "true"
    }
    memory_by_evidence: dict[str, list[dict[str, str]]] = defaultdict(list)
    for memory in memories:
        if memory["split"] != "test":
            continue
        for evidence_id in _split_ids(memory["support_evidence_ids"]):
            if evidence_id in test_evidence:
                memory_by_evidence[evidence_id].append(memory)

    by_event: dict[str, list[dict[str, str]]] = defaultdict(list)
    for evidence_id, row in test_evidence.items():
        for event_id in _split_ids(row["source_event_ids"]):
            for memory in memory_by_evidence.get(evidence_id, ()):
                by_event[event_id].append(memory)

    cases = []
    condition_pool = sorted(condition_ids.values())
    object_pool = sorted(object_ids.values())
    for event_id, linked in sorted(by_event.items()):
        event = event_by_id.get(event_id)
        if event is None or event["task_type"] not in condition_ids:
            continue
        privacy_row = privacy_by_event.get(event_id, {})
        if (
            privacy_row.get("decision", "ALLOW") != "ALLOW"
            or privacy_row.get(
                "raw_value_allowed_in_memory",
                "true",
            ).casefold()
            != "true"
        ):
            continue
        linked = list(
            {
                memory["memory_id"]: memory for memory in linked
                if memory["slot"] in object_ids
            }.values()
        )
        if not linked:
            continue
        gold = [
            {
                "condition_tag_id": condition_ids[event["task_type"]],
                "object_tag_id": object_ids[memory["slot"]],
                "attitude_direction": "positive",
                "temporal_labels": [],
                "support": {
                    "condition": "explicit",
                    "object": "explicit",
                    "attitude": "implicit",
                    "temporal": "implicit",
                },
                "evidence": {
                    "event_id": event_id,
                    "memory_id": memory["memory_id"],
                    "source_mode": (
                        test_evidence[
                            next(
                                evidence_id
                                for evidence_id, values
                                in memory_by_evidence.items()
                                if memory in values
                                and event_id
                                in _split_ids(
                                    test_evidence[evidence_id][
                                        "source_event_ids"
                                    ]
                                )
                            )
                        ]["source_mode"]
                    ),
                },
            }
            for memory in linked
        ]
        correct_conditions = list(
            dict.fromkeys(item["condition_tag_id"] for item in gold)
        )
        correct_objects = list(
            dict.fromkeys(item["object_tag_id"] for item in gold)
        )
        cases.append(
            {
                "id": f"holdout:v1:event:{event_id}",
                "source_kind": event["source_type"],
                "evaluation_track": "frozen_user_test",
                "query_type": event["event_type"],
                "text": event["raw_content"],
                "gold_observations": gold,
                "options": {
                    "condition_tag_ids": _distractors(
                        correct_conditions,
                        condition_pool,
                        key=event_id,
                        count=2,
                    ),
                    "object_tag_ids": _distractors(
                        correct_objects,
                        object_pool,
                        key=event_id,
                        count=3,
                    ),
                    "temporal_labels": list(TEMPORAL_LABELS),
                },
                "annotation_notes": [
                    "Condition and object come from frozen benchmark fields.",
                    "Attitude and temporal are diagnostic weak labels only.",
                ],
            }
        )
    return cases, tags


def _event_holdout_cases(
    *,
    dataset_name: str,
    events_path: Path,
    memories_path: Path,
    train_users: set[str],
    test_users: set[str],
    included_event_types: set[str],
    object_field: str = "object",
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    events = _rows(events_path)
    memories = _rows(memories_path)
    memory_by_event: dict[str, list[dict[str, str]]] = defaultdict(list)
    for memory in memories:
        for event_id in _split_ids(memory["evidence_event_ids"]):
            memory_by_event[event_id].append(memory)

    train = [
        row for row in events
        if row["user_id"] in train_users
        and row["event_type"] in included_event_types
    ]
    test = [
        row for row in events
        if row["user_id"] in test_users
        and row["event_type"] in included_event_types
    ]
    condition_examples: dict[str, list[str]] = defaultdict(list)
    object_examples: dict[str, list[str]] = defaultdict(list)
    for row in train:
        condition_examples[row["scene"]].append(row["detail"])
        object_examples[row[object_field]].append(row["detail"])

    condition_ids = {
        value: f"holdout:{dataset_name}:condition:{_slug(value)}"
        for value in sorted(condition_examples)
    }
    object_ids = {
        value: f"holdout:{dataset_name}:object:{_slug(value)}"
        for value in sorted(object_examples)
    }
    tags = [
        *(
            _tag(
                tag_id=condition_ids[name],
                name=name,
                group="condition",
                aliases=(name.replace("_", " "),),
                prototypes=condition_examples[name],
            )
            for name in sorted(condition_ids)
        ),
        *(
            _tag(
                tag_id=object_ids[name],
                name=name,
                group="object",
                aliases=(name.replace("_", " "),),
                prototypes=object_examples[name],
            )
            for name in sorted(object_ids)
        ),
    ]
    condition_pool = sorted(condition_ids.values())
    object_pool = sorted(object_ids.values())
    cases = []
    for row in test:
        if (
            row["scene"] not in condition_ids
            or row[object_field] not in object_ids
        ):
            continue
        linked = memory_by_event.get(row["event_id"], ())
        temporal = []
        if linked:
            memory_type = Counter(
                memory["memory_type"] for memory in linked
            ).most_common(1)[0][0]
            temporal = {
                "short_term": ["temporal_short"],
                "mid_term": ["temporal_medium"],
                "long_term": ["temporal_long"],
            }.get(memory_type, [])
        condition_id = condition_ids[row["scene"]]
        object_id = object_ids[row[object_field]]
        cases.append(
            {
                "id": (
                    f"holdout:{dataset_name}:event:{row['event_id']}"
                ),
                "source_kind": "event_text",
                "evaluation_track": "held_out_users",
                "query_type": row["event_type"],
                "text": row["detail"],
                "gold_observations": [
                    {
                        "condition_tag_id": condition_id,
                        "object_tag_id": object_id,
                        "attitude_direction": (
                            "negative"
                            if row["event_type"] == "cancellation"
                            else "positive"
                        ),
                        "temporal_labels": temporal,
                        "support": {
                            "condition": "explicit",
                            "object": "explicit",
                            "attitude": "implicit",
                            "temporal": "implicit",
                        },
                        "evidence": {
                            "event_id": row["event_id"],
                            "source_fields": [
                                "scene",
                                object_field,
                                "detail",
                            ],
                        },
                    }
                ],
                "options": {
                    "condition_tag_ids": _distractors(
                        [condition_id],
                        condition_pool,
                        key=row["event_id"],
                        count=2,
                    ),
                    "object_tag_ids": _distractors(
                        [object_id],
                        object_pool,
                        key=row["event_id"],
                        count=3,
                    ),
                    "temporal_labels": list(TEMPORAL_LABELS),
                },
                "annotation_notes": [
                    "Held-out user text; catalog prototypes use train users only.",
                    "Attitude and temporal are diagnostic weak labels only.",
                ],
            }
        )
    return cases, tags


def build_dataset(root: Path) -> dict[str, Any]:
    v1_cases, v1_tags = _v1_cases(root)
    memory_cases, memory_tags = _event_holdout_cases(
        dataset_name="memory_test",
        events_path=(
            root / "memory_test_data" / "memory_test_data"
            / "user_event_log.csv"
        ),
        memories_path=(
            root / "memory_test_data" / "memory_test_data"
            / "memory_ground_truth.csv"
        ),
        train_users={"U001", "U002", "U003"},
        test_users={"U004", "U005"},
        included_event_types={"preference_statement"},
    )
    challenge_cases, _ = _event_holdout_cases(
        dataset_name="challenge_v2",
        events_path=(
            root / "agent_memory_challenge_v2" / "challenge_v2"
            / "user_event_log_challenge_v2.csv"
        ),
        memories_path=(
            root / "agent_memory_challenge_v2" / "challenge_v2"
            / "memory_ground_truth_challenge_v2.csv"
        ),
        train_users={"U101", "U102", "U103", "U104"},
        test_users={"U105", "U106", "U107", "U108"},
        included_event_types={
            "preference_statement",
            "preference_update",
            "plan",
            "cancellation",
        },
        object_field="app",
    )

    cases = []
    duplicate_texts = []
    seen_texts: dict[str, str] = {}
    for case in (*v1_cases, *memory_cases):
        normalized = _normalized_text(case["text"])
        if normalized in seen_texts:
            duplicate_texts.append(
                {
                    "kept": seen_texts[normalized],
                    "dropped": case["id"],
                }
            )
            continue
        seen_texts[normalized] = case["id"]
        cases.append(case)

    tags_by_id = {
        tag["tag_id"]: tag
        for tag in (*v1_tags, *memory_tags)
    }
    conditions = sorted(
        (
            tag for tag in tags_by_id.values()
            if "condition" in tag["groups"]
        ),
        key=lambda item: item["tag_id"],
    )
    objects = sorted(
        (
            tag for tag in tags_by_id.values()
            if "object" in tag["groups"]
        ),
        key=lambda item: item["tag_id"],
    )
    return {
        "schema_version": "mainline.observation_holdout.v1",
        "source_dataset": "root_dataset_generalization_holdout",
        "annotation_policy": {
            "catalog": (
                "Canonical tag prototypes are built only from training users. "
                "Held-out user text never enters the tag catalog."
            ),
            "strict_roles": (
                "Only condition and object are strict extractable roles. "
                "Attitude and temporal remain weak diagnostics because the "
                "source datasets do not provide span-level gold."
            ),
            "deduplication": (
                "Exact normalized text duplicates are retained once."
            ),
            "runtime_llm": False,
            "structured_events": (
                "Challenge v2 structured events are excluded from this "
                "text-semantic score. Their scene, app and object keys are "
                "evaluated through the structured Observation adapter."
            ),
        },
        "audit": {
            "case_count": len(cases),
            "condition_tag_count": len(conditions),
            "object_tag_count": len(objects),
            "duplicate_text_count": len(duplicate_texts),
            "duplicate_text_examples": duplicate_texts[:40],
            "source_counts": dict(
                sorted(
                    Counter(
                        case["id"].split(":")[1] for case in cases
                    ).items()
                )
            ),
            "support_counts": {
                role: dict(
                    sorted(
                        Counter(
                            observation["support"][role]
                            for case in cases
                            for observation in case["gold_observations"]
                        ).items()
                    )
                )
                for role in (
                    "condition",
                    "object",
                    "attitude",
                    "temporal",
                )
            },
            "structured_event_holdout": {
                "challenge_v2_case_count": len(challenge_cases),
                "evaluation": "mainline structured adapter track",
            },
        },
        "tag_catalog": {
            "conditions": conditions,
            "objects": objects,
        },
        "cases": cases,
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
    payload = build_dataset(args.workspace_root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "output": str(args.output),
                "audit": payload["audit"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
