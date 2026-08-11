from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


WORKSPACE = Path(__file__).resolve().parents[2]
DEFAULT_V31 = WORKSPACE / (
    "os_agent_memory_query_benchmark_v3.1/"
    "os_agent_memory_query_benchmark_v3.1_20260725"
)
DEFAULT_V53 = WORKSPACE / (
    "os_agent_memory_query_benchmark_v5.3_20260729/"
    "os_agent_memory_query_benchmark_v5.3_20260729"
)
DEFAULT_OUTPUT = WORKSPACE / (
    "os_agent_memory_query_benchmark_official_1000_v1_20260806"
)
QUERY_TYPES = (
    "human_context_explicit",
    "human_goal_oriented",
    "contextual_ellipsis",
    "low_overlap_paraphrase",
    "human_constraint_emphasis",
)
QUERY_FIELDS = (
    "sequence_no",
    "dataset_origin",
    "precedent_case_id",
    "query_id",
    "answer_group_id",
    "composite_case_id",
    "scenario_id",
    "scenario_label",
    "ability_id",
    "ability_label",
    "competition_requirement_group",
    "memory_capability_under_test",
    "failure_mode_under_test",
    "evaluation_track",
    "evidence_mode",
    "cross_source_relation",
    "query_type",
    "dataset_partition",
    "difficulty_level",
    "alignment_method",
    "alignment_claim",
    "source_dataset_ids",
    "dialogue_episode_ids",
    "operation_episode_ids",
    "required_dialogue_event_ids",
    "required_operation_event_ids",
    "candidate_dialogue_event_ids",
    "candidate_operation_event_ids",
    "forbidden_dialogue_event_ids",
    "forbidden_operation_event_ids",
    "required_evidence_ids",
    "candidate_evidence_ids",
    "forbidden_evidence_ids",
    "target_content_types",
    "target_memory_types",
    "apps_involved",
    "workflow_steps_json",
    "handoff_artifacts_json",
    "expected_action_keys",
    "forbidden_action_keys",
    "target_objects",
    "operation_state_labels",
    "decision_class",
    "max_score",
    "query_text",
    "current_context_text",
)
ANSWER_FIELDS = (
    "dataset_origin",
    "precedent_case_id",
    "answer_group_id",
    "canonical_user_intent",
    "dialogue_memory_texts",
    "operation_log_texts",
    "required_memory_texts",
    "candidate_memory_texts",
    "forbidden_memory_texts",
    "operation_state_reasoning",
    "memory_dependency_reason",
    "expected_conclusion",
    "expected_operation_text",
    "reference_agent_response",
    "answer_reasoning_core",
    "scoring_points_json",
    "scoring_rubric_text",
)


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _json_list(value: str | Sequence[str] | None) -> list[str]:
    if not value:
        return []
    if not isinstance(value, str):
        return [str(item) for item in value if str(item)]
    stripped = value.strip()
    if not stripped:
        return []
    if stripped.startswith("["):
        return [str(item) for item in json.loads(stripped)]
    return [item for item in stripped.split("|") if item]


def _json_text(values: Iterable[str]) -> str:
    return json.dumps(list(dict.fromkeys(values)), ensure_ascii=False)


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _largest_remainder(counter: Counter[str], total: int) -> dict[str, int]:
    source_total = sum(counter.values())
    raw = {key: total * value / source_total for key, value in counter.items()}
    result = {key: int(value) for key, value in raw.items()}
    remaining = total - sum(result.values())
    order = sorted(
        counter,
        key=lambda key: (-(raw[key] - result[key]), key),
    )
    for key in order[:remaining]:
        result[key] += 1
    return result


def _choose_variants(
    rows: Sequence[Mapping[str, str]],
    text_counts: Counter[str],
    omitted_counts: Counter[str],
) -> tuple[list[Mapping[str, str]], str] | None:
    by_type = {row["query_type"]: row for row in rows}
    if set(by_type) != set(QUERY_TYPES):
        return None
    choices = []
    for omitted in QUERY_TYPES:
        retained = [by_type[kind] for kind in QUERY_TYPES if kind != omitted]
        additions = Counter(row["query_text"] for row in retained)
        if any(
            text_counts[text] + increment > 2
            for text, increment in additions.items()
        ):
            continue
        choices.append(
            (
                sum(
                    text_counts[text] * increment
                    for text, increment in additions.items()
                ),
                omitted_counts[omitted],
                _digest(rows[0]["answer_group_id"] + omitted),
                omitted,
                retained,
            )
        )
    if not choices:
        return None
    _, _, _, omitted, retained = min(choices)
    omitted_counts[omitted] += 1
    text_counts.update(row["query_text"] for row in retained)
    return retained, omitted


def _legacy_cases(
    root: Path,
    *,
    count: int,
    text_counts: Counter[str],
    omitted_counts: Counter[str],
) -> list[dict[str, Any]]:
    queries = _rows(root / "processed_data/query_set.csv")
    memories = {
        row["memory_id"]: row
        for row in _rows(root / "processed_data/memory_records.csv")
    }
    by_group: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in queries:
        by_group[row["answer_group_id"]].append(row)
    candidates = []
    for group_id, values in by_group.items():
        source_ids = _json_list(values[0]["source_task_ids"])
        if len(source_ids) != 1 or values[0]["evaluation_track"] != "single_memory":
            continue
        required = _json_list(values[0]["required_memory_ids"])
        memory_type = required[0].split("_", 1)[0] if required else "UNKNOWN"
        candidates.append((memory_type, group_id, values, source_ids[0]))

    selected = []
    type_counts: Counter[str] = Counter()
    while len(selected) < count:
        available = [value for value in candidates if value[1] not in {x["answer_group_id"] for x in selected}]
        if not available:
            raise RuntimeError("not enough legacy cases")
        available.sort(
            key=lambda value: (
                type_counts[value[0]],
                _digest(value[1]),
            )
        )
        accepted = None
        for memory_type, group_id, values, source_id in available:
            variants = _choose_variants(values, text_counts, omitted_counts)
            if variants is None:
                continue
            retained, omitted = variants
            accepted = {
                "dataset_origin": "v3.1",
                "precedent_case_id": f"OFFICIAL1000_LEGACY_{source_id}",
                "answer_group_id": group_id,
                "source_task_ids": [source_id],
                "memory_type": memory_type,
                "queries": retained,
                "omitted_query_type": omitted,
            }
            break
        if accepted is None:
            raise RuntimeError("legacy exact-text duplicate cap is unsatisfiable")
        selected.append(accepted)
        type_counts[accepted["memory_type"]] += 1
    return selected


def _feature_score(row: Mapping[str, str], counts: Counter[str]) -> float:
    features = [
        f"scenario:{row['scenario_id']}",
        f"partition:{row['dataset_partition']}",
        f"difficulty:{row['difficulty_level']}",
        f"ability:{row['ability_id']}",
        f"relation:{row['cross_source_relation']}",
    ]
    features.extend(f"app:{value}" for value in _json_list(row["apps_involved"]))
    return sum(1.0 / (1.0 + counts[value]) for value in features)


def _register_features(row: Mapping[str, str], counts: Counter[str]) -> None:
    for value in (
        f"scenario:{row['scenario_id']}",
        f"partition:{row['dataset_partition']}",
        f"difficulty:{row['difficulty_level']}",
        f"ability:{row['ability_id']}",
        f"relation:{row['cross_source_relation']}",
    ):
        counts[value] += 1
    for value in _json_list(row["apps_involved"]):
        counts[f"app:{value}"] += 1


def _v53_cases(
    root: Path,
    *,
    count: int,
    text_counts: Counter[str],
    omitted_counts: Counter[str],
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    queries = _rows(root / "processed_data/query_set.csv")
    by_id = {row["query_id"]: row for row in queries}
    by_group: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in queries:
        by_group[row["answer_group_id"]].append(row)
    review = _rows(root / "review/query_review_sample_1000.csv")
    representatives = {
        row["answer_group_id"]: by_id[row["query_id"]]
        for row in review
    }
    quotas = _largest_remainder(
        Counter(row["evaluation_track"] for row in representatives.values()),
        count,
    )
    selected = []
    selected_groups = set()
    feature_counts: Counter[str] = Counter()
    for track in sorted(quotas):
        for _ in range(quotas[track]):
            candidates = [
                row
                for group_id, row in representatives.items()
                if group_id not in selected_groups
                and row["evaluation_track"] == track
            ]
            candidates.sort(
                key=lambda row: (
                    -_feature_score(row, feature_counts),
                    _digest(row["answer_group_id"]),
                )
            )
            accepted = None
            for representative in candidates:
                group_id = representative["answer_group_id"]
                variants = _choose_variants(
                    by_group[group_id], text_counts, omitted_counts
                )
                if variants is None:
                    continue
                retained, omitted = variants
                accepted = {
                    "dataset_origin": "v5.3",
                    "precedent_case_id": (
                        f"OFFICIAL1000_{representative['composite_case_id']}"
                    ),
                    "answer_group_id": group_id,
                    "representative": representative,
                    "queries": retained,
                    "omitted_query_type": omitted,
                }
                break
            if accepted is None:
                raise RuntimeError(f"not enough v5.3 cases for track {track}")
            selected.append(accepted)
            selected_groups.add(accepted["answer_group_id"])
            _register_features(accepted["representative"], feature_counts)
    return selected, quotas


def _ordered_queries(cases: Sequence[Mapping[str, Any]]) -> list[dict[str, str]]:
    by_case = {
        case["precedent_case_id"]: sorted(
            case["queries"], key=lambda row: QUERY_TYPES.index(row["query_type"])
        )
        for case in cases
    }
    output = []
    previous_case = None
    previous_text = None
    for round_index in range(4):
        order = sorted(
            by_case,
            key=lambda case_id: _digest(f"round:{round_index}:{case_id}"),
        )
        if order and order[0] == previous_case:
            order = order[1:] + order[:1]
        for position, case_id in enumerate(order):
            row = dict(by_case[case_id][round_index])
            if row["query_text"] == previous_text:
                swap = next(
                    (
                        index
                        for index in range(position + 1, len(order))
                        if by_case[order[index]][round_index]["query_text"]
                        != previous_text
                    ),
                    None,
                )
                if swap is not None:
                    other = order[swap]
                    order[position], order[swap] = other, case_id
                    case_id = other
                    row = dict(by_case[case_id][round_index])
            row["precedent_case_id"] = case_id
            output.append(row)
            previous_case = case_id
            previous_text = row["query_text"]
    for index, row in enumerate(output, 1):
        row["sequence_no"] = str(index)
    return output


def _legacy_contexts(root: Path) -> dict[str, dict[str, str]]:
    return {
        row["context_id"]: row
        for row in _rows(root / "processed_data/context_set.csv")
    }


def _normalize_query(
    row: Mapping[str, str],
    *,
    origin: str,
    precedent_case_id: str,
    legacy_contexts: Mapping[str, Mapping[str, str]],
) -> dict[str, str]:
    if origin == "v5.3":
        value = {field: str(row.get(field, "")) for field in QUERY_FIELDS}
        value["dataset_origin"] = origin
        value["precedent_case_id"] = precedent_case_id
        return value
    context_text = " ".join(
        legacy_contexts[context_id]["visible_hint"]
        for context_id in _json_list(row.get("current_context_ids"))
        if context_id in legacy_contexts
    )
    legacy_difficulty = {
        "简单": "easy",
        "中等": "medium",
        "困难": "hard",
    }.get(row["difficulty_level"], row["difficulty_level"])
    return {
        "sequence_no": str(row.get("sequence_no", "")),
        "dataset_origin": origin,
        "precedent_case_id": precedent_case_id,
        "query_id": row["query_id"],
        "answer_group_id": row["answer_group_id"],
        "composite_case_id": precedent_case_id,
        "scenario_id": "legacy_calc_task",
        "scenario_label": row.get("scenario_label", "LibreOffice Calc"),
        "ability_id": "legacy_workflow_memory",
        "ability_label": row.get("target_content_types", ""),
        "competition_requirement_group": "legacy_retrieval_regression",
        "memory_capability_under_test": "retrieve the matching legacy workflow memory and preserve its constraints",
        "failure_mode_under_test": "wrong_memory_or_missing_constraint",
        "evaluation_track": row["evaluation_track"],
        "evidence_mode": "legacy_memory_record",
        "cross_source_relation": "single_task_memory",
        "query_type": row["query_type"],
        "dataset_partition": row["dataset_partition"],
        "difficulty_level": legacy_difficulty,
        "alignment_method": "v3.1_original_alignment",
        "alignment_claim": "Original v3.1 task-memory-query alignment.",
        "source_dataset_ids": _json_text(["os_agent_memory_query_benchmark_v3.1"]),
        "dialogue_episode_ids": "[]",
        "operation_episode_ids": "[]",
        "required_dialogue_event_ids": "[]",
        "required_operation_event_ids": "[]",
        "candidate_dialogue_event_ids": "[]",
        "candidate_operation_event_ids": "[]",
        "forbidden_dialogue_event_ids": "[]",
        "forbidden_operation_event_ids": "[]",
        "required_evidence_ids": _json_text(_json_list(row["required_memory_ids"])),
        "candidate_evidence_ids": _json_text(_json_list(row["candidate_memory_ids"])),
        "forbidden_evidence_ids": _json_text(_json_list(row["forbidden_memory_ids"])),
        "target_content_types": _json_text(_json_list(row["target_content_types"])),
        "target_memory_types": _json_text(_json_list(row["target_memory_types"])),
        "apps_involved": row["apps_involved"],
        "workflow_steps_json": row["workflow_steps_json"],
        "handoff_artifacts_json": row["handoff_artifacts_json"],
        "expected_action_keys": _json_text(_json_list(row["expected_action_keys"])),
        "forbidden_action_keys": "[]",
        "target_objects": _json_text(_json_list(row["target_objects"])),
        "operation_state_labels": "[]",
        "decision_class": row["decision_class"],
        "max_score": row["max_score"],
        "query_text": row["query_text"],
        "current_context_text": context_text,
    }


def _legacy_answer(row: Mapping[str, str], precedent_case_id: str) -> dict[str, str]:
    return {
        "dataset_origin": "v3.1",
        "precedent_case_id": precedent_case_id,
        "answer_group_id": row["answer_group_id"],
        "canonical_user_intent": row["query_text"],
        "dialogue_memory_texts": "",
        "operation_log_texts": "",
        "required_memory_texts": row["required_memory_texts"],
        "candidate_memory_texts": row["candidate_memory_texts"],
        "forbidden_memory_texts": row["forbidden_memory_texts"],
        "operation_state_reasoning": "",
        "memory_dependency_reason": row["answer_reasoning"],
        "expected_conclusion": row["expected_conclusion"],
        "expected_operation_text": row["expected_operation_text"],
        "reference_agent_response": row["expected_conclusion"],
        "answer_reasoning_core": row["answer_reasoning"],
        "scoring_points_json": row["scoring_points_json"],
        "scoring_rubric_text": row["scoring_rubric_text"],
    }


def _write_csv(path: Path, fields: Sequence[str], rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _write_ndjson_gz(path: Path, values: Iterable[Mapping[str, Any]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("wb") as raw:
        with gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as compressed:
            with io.TextIOWrapper(compressed, encoding="utf-8") as handle:
                for value in values:
                    handle.write(json.dumps(value, ensure_ascii=False) + "\n")
                    count += 1
    return count


def _filtered_ndjson(
    source: Path,
    ids: set[str],
) -> tuple[list[dict[str, Any]], set[str]]:
    values = []
    found = set()
    with gzip.open(source, "rt", encoding="utf-8") as handle:
        for line in handle:
            value = json.loads(line)
            event_id = str(value["event_id"])
            if event_id in ids:
                values.append(value)
                found.add(event_id)
    return values, found


def _distribution(rows: Sequence[Mapping[str, str]], key: str) -> dict[str, int]:
    return dict(sorted(Counter(row[key] for row in rows).items()))


def _manifest(root: Path) -> None:
    lines = []
    for path in sorted(value for value in root.rglob("*") if value.is_file()):
        if path.name == "FILE_MANIFEST_SHA256.txt":
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        lines.append(f"{digest}  {path.relative_to(root).as_posix()}")
    (root / "FILE_MANIFEST_SHA256.txt").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--v31", type=Path, default=DEFAULT_V31)
    parser.add_argument("--v53", type=Path, default=DEFAULT_V53)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    output = args.output
    if output.exists() and any(output.iterdir()) and not args.overwrite:
        raise SystemExit(f"output directory is not empty: {output}")
    output.mkdir(parents=True, exist_ok=True)

    text_counts: Counter[str] = Counter()
    omitted_counts: Counter[str] = Counter()
    legacy = _legacy_cases(
        args.v31,
        count=40,
        text_counts=text_counts,
        omitted_counts=omitted_counts,
    )
    modern, track_quotas = _v53_cases(
        args.v53,
        count=160,
        text_counts=text_counts,
        omitted_counts=omitted_counts,
    )
    cases = [*legacy, *modern]
    ordered = _ordered_queries(cases)
    case_by_group = {case["answer_group_id"]: case for case in cases}
    legacy_contexts = _legacy_contexts(args.v31)
    normalized_queries = [
        _normalize_query(
            row,
            origin=case_by_group[row["answer_group_id"]]["dataset_origin"],
            precedent_case_id=row["precedent_case_id"],
            legacy_contexts=legacy_contexts,
        )
        for row in ordered
    ]
    for index, row in enumerate(normalized_queries, 1):
        row["sequence_no"] = str(index)

    v53_answers = {
        row["answer_group_id"]: row
        for row in _rows(args.v53 / "processed_data/answer_key.csv")
    }
    answers = []
    for case in cases:
        if case["dataset_origin"] == "v5.3":
            answer = {
                field: v53_answers[case["answer_group_id"]].get(field, "")
                for field in ANSWER_FIELDS
            }
            answer["dataset_origin"] = "v5.3"
            answer["precedent_case_id"] = case["precedent_case_id"]
        else:
            answer = _legacy_answer(case["queries"][0], case["precedent_case_id"])
        answers.append(answer)

    legacy_memory_rows = _rows(args.v31 / "processed_data/memory_records.csv")
    legacy_memory_by_id = {row["memory_id"]: row for row in legacy_memory_rows}
    legacy_memory_ids = {
        memory_id
        for row in normalized_queries
        if row["dataset_origin"] == "v3.1"
        for field in (
            "required_evidence_ids",
            "candidate_evidence_ids",
            "forbidden_evidence_ids",
        )
        for memory_id in _json_list(row[field])
    }
    legacy_selected_memories = [
        legacy_memory_by_id[memory_id]
        for memory_id in sorted(legacy_memory_ids)
    ]
    legacy_task_ids = {
        row["source_task_id"] for row in legacy_selected_memories
    }
    legacy_events = []
    for task_id in sorted(legacy_task_ids):
        raw = json.loads((args.v31 / "raw_json" / f"{task_id}.json").read_text(encoding="utf-8"))
        legacy_events.append(
            {
                "event_id": f"V31_EVENT_{task_id}",
                "source_task_id": task_id,
                "instruction": raw.get("instruction"),
                "snapshot": raw.get("snapshot"),
                "related_apps": raw.get("related_apps", []),
                "config": raw.get("config", []),
            }
        )

    modern_rows = [row for row in normalized_queries if row["dataset_origin"] == "v5.3"]
    dialogue_ids = {
        event_id
        for row in modern_rows
        for field in (
            "required_dialogue_event_ids",
            "candidate_dialogue_event_ids",
            "forbidden_dialogue_event_ids",
        )
        for event_id in _json_list(row[field])
    }
    operation_ids = {
        event_id
        for row in modern_rows
        for field in (
            "required_operation_event_ids",
            "candidate_operation_event_ids",
            "forbidden_operation_event_ids",
        )
        for event_id in _json_list(row[field])
    }
    dialogue_events, found_dialogue = _filtered_ndjson(
        args.v53 / "evidence/dialogue_events_selected.ndjson.gz",
        dialogue_ids,
    )
    operation_events, found_operation = _filtered_ndjson(
        args.v53 / "evidence/operation_events_representative.ndjson.gz",
        operation_ids,
    )
    operation_episode_ids = {
        episode_id
        for row in modern_rows
        for episode_id in _json_list(row["operation_episode_ids"])
    }
    operation_episodes = [
        row
        for row in _rows(args.v53 / "evidence/operation_episodes_selected.csv")
        if row["episode_id"] in operation_episode_ids
    ]
    composite_ids = {
        row["composite_case_id"] for row in modern_rows
    }
    composite_rows = [
        row
        for row in _rows(args.v53 / "evidence/composite_case_map.csv")
        if row["composite_case_id"] in composite_ids
    ]

    precedent_rows = []
    for case in cases:
        if case["dataset_origin"] == "v3.1":
            representative = case["queries"][0]
            evidence_ids = list(
                dict.fromkeys(
                    (
                        *_json_list(representative["required_memory_ids"]),
                        *_json_list(representative["candidate_memory_ids"]),
                        *_json_list(representative["forbidden_memory_ids"]),
                    )
                )
            )
            source_ids = list(
                dict.fromkeys(
                    legacy_memory_by_id[value]["source_task_id"]
                    for value in evidence_ids
                )
            )
            precedent_rows.append(
                {
                    "precedent_case_id": case["precedent_case_id"],
                    "dataset_origin": "v3.1",
                    "answer_group_id": case["answer_group_id"],
                    "dialogue_episode_ids": [],
                    "operation_episode_ids": [],
                    "evidence_ids": evidence_ids,
                    "source_event_ids": [f"V31_EVENT_{value}" for value in source_ids],
                }
            )
        else:
            row = case["representative"]
            precedent_rows.append(
                {
                    "precedent_case_id": case["precedent_case_id"],
                    "dataset_origin": "v5.3",
                    "answer_group_id": case["answer_group_id"],
                    "dialogue_episode_ids": _json_list(row["dialogue_episode_ids"]),
                    "operation_episode_ids": _json_list(row["operation_episode_ids"]),
                    "evidence_ids": list(
                        dict.fromkeys(
                            (
                                *_json_list(row["required_evidence_ids"]),
                                *_json_list(row["candidate_evidence_ids"]),
                                *_json_list(row["forbidden_evidence_ids"]),
                            )
                        )
                    ),
                    "source_event_ids": [],
                }
            )

    dialogue_by_id = {
        str(value["event_id"]): value for value in dialogue_events
    }
    operation_by_id = {
        str(value["event_id"]): value for value in operation_events
    }
    legacy_event_by_id = {
        str(value["event_id"]): value for value in legacy_events
    }
    precedent_inputs = []
    for precedent in precedent_rows:
        if precedent["dataset_origin"] == "v3.1":
            evidence = [
                legacy_memory_by_id[event_id]
                for event_id in precedent["evidence_ids"]
            ]
            source_events = [
                legacy_event_by_id[event_id]
                for event_id in precedent["source_event_ids"]
            ]
            dialogue = []
            operations = []
        else:
            evidence = []
            source_events = []
            dialogue = [
                dialogue_by_id[event_id]
                for event_id in precedent["evidence_ids"]
                if event_id in dialogue_by_id
            ]
            operations = [
                operation_by_id[event_id]
                for event_id in precedent["evidence_ids"]
                if event_id in operation_by_id
            ]
        precedent_inputs.append(
            {
                **precedent,
                "legacy_memory_records": evidence,
                "legacy_source_events": source_events,
                "dialogue_events": dialogue,
                "operation_events": operations,
            }
        )

    _write_csv(output / "processed_data/query_set.csv", QUERY_FIELDS, normalized_queries)
    _write_csv(output / "processed_data/answer_key.csv", ANSWER_FIELDS, answers)
    _write_ndjson_gz(output / "processed_data/precedent_set.ndjson.gz", precedent_rows)
    _write_ndjson_gz(
        output / "processed_data/precedent_inputs.ndjson.gz",
        precedent_inputs,
    )
    _write_csv(
        output / "evidence/legacy_memory_records.csv",
        list(legacy_memory_rows[0]),
        legacy_selected_memories,
    )
    _write_ndjson_gz(output / "evidence/legacy_source_events.ndjson.gz", legacy_events)
    _write_ndjson_gz(output / "evidence/dialogue_events_selected.ndjson.gz", dialogue_events)
    _write_ndjson_gz(output / "evidence/operation_events_representative.ndjson.gz", operation_events)
    _write_csv(
        output / "evidence/operation_episodes_selected.csv",
        list(operation_episodes[0]),
        operation_episodes,
    )
    _write_csv(
        output / "evidence/composite_case_map.csv",
        list(composite_rows[0]),
        composite_rows,
    )

    consecutive_case_repeats = sum(
        left["precedent_case_id"] == right["precedent_case_id"]
        for left, right in zip(normalized_queries, normalized_queries[1:])
    )
    consecutive_text_repeats = sum(
        left["query_text"] == right["query_text"]
        for left, right in zip(normalized_queries, normalized_queries[1:])
    )
    query_text_counts = Counter(row["query_text"] for row in normalized_queries)
    report = {
        "schema_version": "official.memory_query_1000.v1",
        "selection_policy": {
            "precedent_case_count": 200,
            "query_count": 800,
            "legacy_case_count": 40,
            "v53_case_count": 160,
            "queries_per_case": 4,
            "v53_candidate_pool": "human_review_sample_1000",
            "v53_track_quotas": track_quotas,
            "answer_fields_used_for_selection": False,
            "exact_query_text_max_occurrences": 2,
            "ordering": "four deterministic interleaved rounds",
        },
        "counts": {
            "precedent_cases": len(precedent_rows),
            "precedent_input_records": len(precedent_inputs),
            "queries": len(normalized_queries),
            "answer_groups": len(answers),
            "legacy_memory_records": len(legacy_selected_memories),
            "legacy_source_events": len(legacy_events),
            "dialogue_events": len(dialogue_events),
            "operation_events": len(operation_events),
            "operation_episodes": len(operation_episodes),
        },
        "query_distribution": {
            "origin": _distribution(normalized_queries, "dataset_origin"),
            "track": _distribution(normalized_queries, "evaluation_track"),
            "query_type": _distribution(normalized_queries, "query_type"),
            "partition": _distribution(normalized_queries, "dataset_partition"),
            "difficulty": _distribution(normalized_queries, "difficulty_level"),
        },
        "duplication": {
            "unique_query_texts": len(query_text_counts),
            "max_exact_query_text_occurrences": max(query_text_counts.values()),
            "exact_query_texts_repeated_twice": sum(value == 2 for value in query_text_counts.values()),
            "consecutive_same_case": consecutive_case_repeats,
            "consecutive_same_text": consecutive_text_repeats,
            "omitted_query_types": dict(sorted(omitted_counts.items())),
        },
    }
    missing = {
        "dialogue_event_ids": sorted(dialogue_ids - found_dialogue),
        "operation_event_ids": sorted(operation_ids - found_operation),
        "operation_episode_ids": sorted(
            operation_episode_ids - {row["episode_id"] for row in operation_episodes}
        ),
        "legacy_memory_ids": sorted(
            legacy_memory_ids - set(legacy_memory_by_id)
        ),
    }
    validation = {
        "valid": (
            len(precedent_rows) == 200
            and len(normalized_queries) == 800
            and len(precedent_inputs) == 200
            and len(answers) == 200
            and max(query_text_counts.values()) <= 2
            and consecutive_case_repeats == 0
            and consecutive_text_repeats == 0
            and not any(missing.values())
        ),
        "checks": {
            "precedent_case_count_200": len(precedent_rows) == 200,
            "precedent_input_count_200": len(precedent_inputs) == 200,
            "query_count_800": len(normalized_queries) == 800,
            "four_queries_per_case": all(
                value == 4
                for value in Counter(
                    row["precedent_case_id"] for row in normalized_queries
                ).values()
            ),
            "answer_group_count_200": len(answers) == 200,
            "exact_text_cap_two": max(query_text_counts.values()) <= 2,
            "no_consecutive_case_repeat": consecutive_case_repeats == 0,
            "no_consecutive_text_repeat": consecutive_text_repeats == 0,
            "all_evidence_resolved": not any(missing.values()),
        },
        "missing": missing,
    }
    _write_json(output / "selection_report.json", report)
    _write_json(output / "validation_report.json", validation)
    (output / "README.md").write_text(
        """# OS Agent Memory Query Official 1000

固定正式集包含200个前置案例和800条离线Query。40个案例来自v3.1，用于保持旧回归连续性；160个案例从v5.3的1000条人工复核池中分层选取。

每个前置案例保留4种不同问法，Query按四轮交错排列，同一案例不会连续出现；完全相同的Query文本最多出现2次。Query只形成临时Observation，不写回记忆库。

- `processed_data/query_set.csv`：800条无答案Query。
- `processed_data/answer_key.csv`：200组独立答案，仅用于事后评分。
- `processed_data/precedent_set.ndjson.gz`：200个前置证据包索引。
- `processed_data/precedent_inputs.ndjson.gz`：200行可直接顺序导入的完整前置输入。
- `evidence/`：筛选后的旧版记忆、对话事件和操作日志。
- `selection_report.json`：抽样及分布报告。
- `validation_report.json`：结构、重复和证据完整性检查。

选择过程不读取答案字段，也不修改MemoryEngine算法。后续调参应另建开发子集；本目录应固定版本使用。
""",
        encoding="utf-8",
    )
    _manifest(output)
    print(json.dumps({"selection": report, "validation": validation}, ensure_ascii=False, indent=2))
    if not validation["valid"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
