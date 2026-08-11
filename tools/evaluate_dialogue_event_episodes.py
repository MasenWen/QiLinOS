from __future__ import annotations

import argparse
import json
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Iterable, Mapping

from src.memory_engine.episode import EpisodeManager
from src.memory_engine.normalizers import observation_from_event
from src.memory_engine.store import MemoryEngineStore


DEFAULT_OUTPUT = Path(
    "outputs/dialogue_event_episode_audit/"
    "dialogue_event_episode_audit.json"
)
EXCEL_EPOCH = datetime(1899, 12, 30, tzinfo=timezone.utc)


@dataclass(frozen=True)
class DialogueRecord:
    message_text: str
    scenario_id: str
    ability_id: str
    utterance_role: str
    memory_signal_type: str
    preference_scope: str
    referenced_app_ids: tuple[str, ...]
    event_time: datetime
    user_id: str
    event_id: str
    gold_episode_id: str
    split: str
    supersedes_event_id: str
    conflict_group_id: str


@dataclass(frozen=True)
class GoldEpisodeRecord:
    episode_id: str
    user_message_count: int
    apps_referenced: tuple[str, ...]
    start_time: datetime
    end_time: datetime
    user_id: str
    primary_ability_id: str
    context: Mapping[str, Any]


def _matrix_records(path: Path) -> list[dict[str, Any]]:
    matrix = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(matrix, list) or not matrix:
        raise ValueError(f"matrix_is_empty:{path}")
    header = matrix[0]
    if not isinstance(header, list):
        raise ValueError(f"matrix_header_is_invalid:{path}")
    return [
        dict(zip(header, row, strict=False))
        for row in matrix[1:]
        if isinstance(row, list) and any(value is not None for value in row)
    ]


def _string_list(value: Any) -> tuple[str, ...]:
    if isinstance(value, list):
        return tuple(str(item) for item in value if str(item))
    if not value:
        return ()
    try:
        parsed = json.loads(str(value))
    except json.JSONDecodeError:
        parsed = None
    if isinstance(parsed, list):
        return tuple(str(item) for item in parsed if str(item))
    return tuple(
        item.strip()
        for item in str(value).replace(";", ",").split(",")
        if item.strip()
    )


def _event_time(value: Any) -> datetime:
    if isinstance(value, (int, float)):
        return EXCEL_EPOCH + timedelta(days=float(value))
    text = str(value or "").strip()
    if not text:
        raise ValueError("event_time_is_empty")
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def read_dialogue_records(path: Path) -> list[DialogueRecord]:
    records = []
    for row in _matrix_records(path):
        records.append(
            DialogueRecord(
                message_text=str(row.get("message_text") or ""),
                scenario_id=str(row.get("scenario_id") or ""),
                ability_id=str(
                    row.get("competition_ability_id") or ""
                ),
                utterance_role=str(row.get("utterance_role") or ""),
                memory_signal_type=str(
                    row.get("memory_signal_type") or ""
                ),
                preference_scope=str(
                    row.get("preference_scope") or ""
                ),
                referenced_app_ids=_string_list(
                    row.get("referenced_app_ids")
                ),
                event_time=_event_time(row.get("event_time")),
                user_id=str(row.get("user_id") or ""),
                event_id=str(row.get("event_id") or ""),
                gold_episode_id=str(row.get("episode_id") or ""),
                split=str(row.get("split") or ""),
                supersedes_event_id=str(
                    row.get("supersedes_event_id") or ""
                ),
                conflict_group_id=str(
                    row.get("conflict_group_id") or ""
                ),
            )
        )
    return records


def read_gold_episodes(path: Path) -> dict[str, GoldEpisodeRecord]:
    episodes = {}
    for row in _matrix_records(path):
        episode_id = str(row.get("episode_id") or "")
        raw_context = row.get("context_json")
        try:
            context = json.loads(str(raw_context or "{}"))
        except json.JSONDecodeError:
            context = {}
        episodes[episode_id] = GoldEpisodeRecord(
            episode_id=episode_id,
            user_message_count=int(
                float(row.get("user_message_count") or 0)
            ),
            apps_referenced=_string_list(row.get("apps_referenced")),
            start_time=_event_time(row.get("start_time")),
            end_time=_event_time(row.get("end_time")),
            user_id=str(row.get("user_id") or ""),
            primary_ability_id=str(
                row.get("primary_ability_id") or ""
            ),
            context=context if isinstance(context, Mapping) else {},
        )
    return episodes


def validate_gold_tables(
    records: list[DialogueRecord],
    episodes: Mapping[str, GoldEpisodeRecord],
) -> dict[str, Any]:
    grouped = dict(_episode_order(records))
    issues = []
    if set(grouped) != set(episodes):
        issues.append(
            {
                "kind": "episode_id_set_mismatch",
                "event_only": sorted(set(grouped) - set(episodes)),
                "episode_only": sorted(set(episodes) - set(grouped)),
            }
        )
    for episode_id in sorted(set(grouped) & set(episodes)):
        event_rows = grouped[episode_id]
        gold = episodes[episode_id]
        checks = {
            "user_message_count": (
                len(event_rows),
                gold.user_message_count,
            ),
            "user_id": (
                {item.user_id for item in event_rows},
                {gold.user_id},
            ),
            "apps_referenced": (
                set().union(
                    *(set(item.referenced_app_ids) for item in event_rows)
                ),
                set(gold.apps_referenced),
            ),
            "start_time": (
                min(item.event_time for item in event_rows),
                gold.start_time,
            ),
            "end_time": (
                max(item.event_time for item in event_rows),
                gold.end_time,
            ),
            "primary_ability_id": (
                {item.ability_id for item in event_rows},
                {gold.primary_ability_id},
            ),
        }
        for field, (actual, expected) in checks.items():
            if actual != expected:
                issues.append(
                    {
                        "kind": "field_mismatch",
                        "episode_id": episode_id,
                        "field": field,
                        "actual": str(actual),
                        "expected": str(expected),
                    }
                )
    return {
        "valid": not issues,
        "event_episode_count": len(grouped),
        "gold_episode_count": len(episodes),
        "issue_count": len(issues),
        "issues": issues[:20],
    }


def _episode_order(
    records: Iterable[DialogueRecord],
) -> list[tuple[str, list[DialogueRecord]]]:
    grouped: dict[str, list[DialogueRecord]] = {}
    for record in records:
        grouped.setdefault(record.gold_episode_id, []).append(record)
    return [
        (episode_id, sorted(items, key=lambda item: item.event_time))
        for episode_id, items in grouped.items()
    ]


def _source_event(
    record: DialogueRecord,
    *,
    event_id: str,
    user_id: str,
    session_id: str,
    event_time: datetime,
) -> dict[str, Any]:
    return {
        "source_type": "dialogue",
        "source_event_id": event_id,
        "user_id": user_id,
        "session_id": session_id,
        "event_time": event_time.isoformat(),
        "actor": "user",
        "content": record.message_text,
        "app": (
            record.referenced_app_ids[0]
            if record.referenced_app_ids
            else ""
        ),
        "scenario_id": record.scenario_id,
        "competition_ability_id": record.ability_id,
        "utterance_role": record.utterance_role,
        "memory_signal_type": record.memory_signal_type,
        "preference_scope": record.preference_scope,
        "referenced_app_ids": list(record.referenced_app_ids),
        "supersedes_event_id": record.supersedes_event_id,
        "conflict_group_id": record.conflict_group_id,
        "context": {"split": record.split},
    }


def _raw_events(
    records: list[DialogueRecord],
) -> list[tuple[DialogueRecord, dict[str, Any]]]:
    return [
        (
            record,
            _source_event(
                record,
                event_id=f"raw:{record.event_id}",
                user_id=record.user_id,
                session_id="dialogue-review",
                event_time=record.event_time,
            ),
        )
        for record in records
    ]


def _stress_events(
    records: list[DialogueRecord],
    *,
    boundary_gap_seconds: float,
) -> list[tuple[DialogueRecord, dict[str, Any]]]:
    cursor = datetime(2026, 1, 1, tzinfo=timezone.utc)
    output = []
    for _, episode_records in _episode_order(records):
        source_start = episode_records[0].event_time
        episode_end = cursor
        for record in episode_records:
            shifted = cursor + (record.event_time - source_start)
            episode_end = max(episode_end, shifted)
            output.append(
                (
                    record,
                    _source_event(
                        record,
                        event_id=f"stress:{record.event_id}",
                        user_id="stress-user",
                        session_id="compressed-dialogue-stream",
                        event_time=shifted,
                    ),
                )
            )
        cursor = episode_end + timedelta(seconds=boundary_gap_seconds)
    return output


def _pairs(groups: Mapping[str, str]) -> set[tuple[str, str]]:
    by_group: dict[str, list[str]] = defaultdict(list)
    for event_id, group_id in groups.items():
        by_group[group_id].append(event_id)
    return {
        (left, right)
        for items in by_group.values()
        for index, left in enumerate(sorted(items))
        for right in sorted(items)[index + 1 :]
    }


def _group_sets(groups: Mapping[str, str]) -> set[frozenset[str]]:
    by_group: dict[str, set[str]] = defaultdict(set)
    for event_id, group_id in groups.items():
        by_group[group_id].add(event_id)
    return {frozenset(items) for items in by_group.values()}


def _evaluate_groups(
    ordered_event_ids: list[str],
    gold: Mapping[str, str],
    predicted: Mapping[str, str],
) -> dict[str, Any]:
    gold_pairs = _pairs(gold)
    predicted_pairs = _pairs(predicted)
    true_pairs = gold_pairs & predicted_pairs
    gold_sets = _group_sets(gold)
    predicted_sets = _group_sets(predicted)

    gold_to_predicted: dict[str, set[str]] = defaultdict(set)
    predicted_to_gold: dict[str, set[str]] = defaultdict(set)
    for event_id in ordered_event_ids:
        gold_to_predicted[gold[event_id]].add(predicted[event_id])
        predicted_to_gold[predicted[event_id]].add(gold[event_id])

    gold_boundaries = {
        index
        for index in range(1, len(ordered_event_ids))
        if gold[ordered_event_ids[index - 1]]
        != gold[ordered_event_ids[index]]
    }
    predicted_boundaries = {
        index
        for index in range(1, len(ordered_event_ids))
        if predicted[ordered_event_ids[index - 1]]
        != predicted[ordered_event_ids[index]]
    }
    true_boundaries = gold_boundaries & predicted_boundaries

    return {
        "event_count": len(ordered_event_ids),
        "gold_episode_count": len(gold_sets),
        "predicted_episode_count": len(predicted_sets),
        "merge_precision": (
            len(true_pairs) / len(predicted_pairs)
            if predicted_pairs
            else 1.0
        ),
        "merge_recall": (
            len(true_pairs) / len(gold_pairs) if gold_pairs else 1.0
        ),
        "exact_episode_rate": (
            len(gold_sets & predicted_sets) / len(gold_sets)
            if gold_sets
            else 1.0
        ),
        "intact_gold_episode_rate": (
            sum(len(values) == 1 for values in gold_to_predicted.values())
            / len(gold_to_predicted)
            if gold_to_predicted
            else 1.0
        ),
        "pure_predicted_episode_rate": (
            sum(len(values) == 1 for values in predicted_to_gold.values())
            / len(predicted_to_gold)
            if predicted_to_gold
            else 1.0
        ),
        "boundary_precision": (
            len(true_boundaries) / len(predicted_boundaries)
            if predicted_boundaries
            else (1.0 if not gold_boundaries else 0.0)
        ),
        "boundary_recall": (
            len(true_boundaries) / len(gold_boundaries)
            if gold_boundaries
            else 1.0
        ),
        "overmerged_predicted_episodes": sum(
            len(values) > 1 for values in predicted_to_gold.values()
        ),
        "split_gold_episodes": sum(
            len(values) > 1 for values in gold_to_predicted.values()
        ),
    }


def _audit_examples(
    pairs: list[tuple[DialogueRecord, dict[str, Any]]],
    predicted: Mapping[str, str],
    *,
    limit: int = 8,
) -> dict[str, Any]:
    by_predicted: dict[str, list[tuple[DialogueRecord, str]]] = defaultdict(
        list
    )
    by_gold: dict[str, list[tuple[DialogueRecord, str]]] = defaultdict(list)
    for record, event in pairs:
        event_id = str(event["source_event_id"])
        by_predicted[predicted[event_id]].append((record, event_id))
        by_gold[record.gold_episode_id].append((record, event_id))

    def item(
        group_id: str,
        values: list[tuple[DialogueRecord, str]],
    ) -> dict[str, Any]:
        return {
            "group_id": group_id,
            "event_count": len(values),
            "gold_episode_ids": sorted(
                {record.gold_episode_id for record, _ in values}
            ),
            "predicted_episode_ids": sorted(
                {predicted[event_id] for _, event_id in values}
            ),
            "events": [
                {
                    "event_id": event_id,
                    "gold_episode_id": record.gold_episode_id,
                    "role": record.utterance_role,
                    "ability": record.ability_id,
                    "apps": list(record.referenced_app_ids),
                    "text": record.message_text,
                }
                for record, event_id in values[:12]
            ],
        }

    overmerged = [
        item(group_id, values)
        for group_id, values in by_predicted.items()
        if len({record.gold_episode_id for record, _ in values}) > 1
    ][:limit]
    split = [
        item(group_id, values)
        for group_id, values in by_gold.items()
        if len({predicted[event_id] for _, event_id in values}) > 1
    ][:limit]
    return {"overmerged": overmerged, "split": split}


def _matched_episode_examples(
    records: list[DialogueRecord],
    episodes: Mapping[str, GoldEpisodeRecord],
) -> list[dict[str, Any]]:
    grouped = dict(_episode_order(records))
    selected = []
    used_abilities = set()
    for target_size in (1, 2, 3):
        for episode_id, event_rows in grouped.items():
            gold = episodes.get(episode_id)
            if (
                len(event_rows) != target_size
                or gold is None
                or gold.primary_ability_id in used_abilities
            ):
                continue
            used_abilities.add(gold.primary_ability_id)
            selected.append(
                {
                    "episode_id": episode_id,
                    "event_count": len(event_rows),
                    "ability": gold.primary_ability_id,
                    "apps": list(gold.apps_referenced),
                    "task": str(gold.context.get("task") or ""),
                    "artifact": str(
                        gold.context.get("artifact") or ""
                    ),
                    "topic": str(gold.context.get("topic") or ""),
                    "messages": [
                        {
                            "event_id": item.event_id,
                            "role": item.utterance_role,
                            "text": item.message_text,
                        }
                        for item in event_rows
                    ],
                    "prediction": "exact_match",
                }
            )
            break
    return selected


def evaluate_view(
    pairs: list[tuple[DialogueRecord, dict[str, Any]]],
) -> dict[str, Any]:
    with TemporaryDirectory() as directory:
        store = MemoryEngineStore(Path(directory) / "episodes.db")
        manager = EpisodeManager(store)
        predicted: dict[str, str] = {}
        started = time.perf_counter()
        for _, event in pairs:
            observation = observation_from_event(event)
            store.put_observation(observation)
            episode, _ = manager.attach(observation)
            predicted[observation.source_event_id] = episode.episode_id
        elapsed_ms = (time.perf_counter() - started) * 1000.0

    ordered_event_ids = [
        str(event["source_event_id"]) for _, event in pairs
    ]
    gold = {
        str(event["source_event_id"]): record.gold_episode_id
        for record, event in pairs
    }
    return {
        "metrics": _evaluate_groups(
            ordered_event_ids,
            gold,
            predicted,
        ),
        "performance": {
            "total_ms": elapsed_ms,
            "mean_ms_per_event": (
                elapsed_ms / len(pairs) if pairs else 0.0
            ),
        },
        "examples": _audit_examples(pairs, predicted),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--events-matrix", type=Path, required=True)
    parser.add_argument("--episodes-matrix", type=Path)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--stress-gap-seconds", type=float, default=45.0)
    args = parser.parse_args()

    records = read_dialogue_records(args.events_matrix)
    gold_episodes = (
        read_gold_episodes(args.episodes_matrix)
        if args.episodes_matrix
        else {}
    )
    stress_pairs = _stress_events(
        records,
        boundary_gap_seconds=args.stress_gap_seconds,
    )
    role_hidden_pairs = []
    for record, event in _stress_events(
        records,
        boundary_gap_seconds=args.stress_gap_seconds,
    ):
        event.pop("utterance_role", None)
        role_hidden_pairs.append((record, event))
    result = {
        "purpose": (
            "Blind Event-to-Episode grouping audit. Gold episode_id is used "
            "only after grouping for scoring."
        ),
        "input": {
            "events_matrix": str(args.events_matrix),
            "episodes_matrix": (
                str(args.episodes_matrix)
                if args.episodes_matrix
                else None
            ),
            "records": len(records),
            "gold_episodes": len(
                {record.gold_episode_id for record in records}
            ),
            "users": len({record.user_id for record in records}),
        },
        "gold_table_validation": (
            validate_gold_tables(records, gold_episodes)
            if gold_episodes
            else None
        ),
        "views": {
            "original": evaluate_view(_raw_events(records)),
            "compressed_single_session": evaluate_view(stress_pairs),
            "compressed_role_hidden_ablation": evaluate_view(
                role_hidden_pairs
            ),
        },
        "matched_episode_examples": (
            _matched_episode_examples(records, gold_episodes)
            if gold_episodes
            else []
        ),
        "limitations": [
            (
                "The review workbook contains one gold episode per user, "
                "so the original view cannot expose cross-episode overmerge."
            ),
            (
                "The compressed view changes user/session/time metadata but "
                "does not change or synthesize message text."
            ),
            (
                "The role-hidden ablation is diagnostic only; the workbook "
                "does provide utterance_role as an Event field."
            ),
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                name: value["metrics"] | value["performance"]
                for name, value in result["views"].items()
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
