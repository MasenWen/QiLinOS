from __future__ import annotations

import csv
import json
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "processed_data"
REPORT = ROOT / "validation_report.json"

EXPECTED_TRACKS = {
    "single_memory": 235,
    "complementary_multi_memory": 150,
    "conflict_resolution": 75,
    "clarification_required": 70,
}
EXPECTED_PARTITIONS = {"train": 150, "dev": 45, "test": 40, "challenge": 295}
CANONICAL_TYPES = {
    "human_context_explicit",
    "human_goal_oriented",
    "contextual_ellipsis",
    "low_overlap_paraphrase",
    "human_constraint_emphasis",
}
HUMAN_FIELDS = [
    "query_text",
    "required_memory_texts",
    "candidate_memory_texts",
    "forbidden_memory_texts",
    "expected_conclusion",
    "expected_operation_text",
    "answer_reasoning",
    "scoring_rubric_text",
    "status",
    "rank",
]
REMOVED_FIELDS = {
    "schema_version",
    "query_variant_id",
    "interaction_mode",
    "domain",
    "scene",
    "app_scope",
    "workflow_scope",
    "dependency_order",
    "source_dataset",
    "source_fidelity",
    "synthetic_dimensions",
    "memory_count",
    "evidence_relation",
    "constraints",
    "scoring_reason",
    "answerability",
    "top_k",
    "automatic_evaluation_available",
}


def load_csv(name: str) -> list[dict[str, str]]:
    with (DATA / name).open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def split_ids(value: str) -> list[str]:
    return [item.strip() for item in (value or "").split("|") if item.strip()]


def normalize(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).lower()
    return re.sub(r"[\s，。！？、；：,.!?;:'\"“”‘’（）()【】\[\]<>《》/\\_-]+", "", value)


errors: list[str] = []
warnings: list[str] = []

required_files = {
    "task_index.csv": {"task_id", "memory_id", "context_id"},
    "memory_records.csv": {"memory_id", "source_task_id", "memory_summary", "constraints"},
    "context_set.csv": {"context_id", "source_task_id", "visible_hint"},
    "query_set.csv": {
        "query_id",
        "answer_group_id",
        "evaluation_track",
        "query_type",
        "dataset_partition",
        "source_task_ids",
        "current_context_ids",
        "required_memory_ids",
        "candidate_memory_ids",
        "forbidden_memory_ids",
        "workflow_steps_json",
        "handoff_artifacts_json",
        "expected_action_keys",
        "decision_class",
        "scoring_points_json",
        "max_score",
        *HUMAN_FIELDS,
    },
    "dataset_stats.csv": {"category", "metric", "value", "notes"},
}

loaded: dict[str, list[dict[str, str]]] = {}
for file_name, required_fields in required_files.items():
    path = DATA / file_name
    if not path.exists():
        errors.append(f"missing file: {file_name}")
        continue
    rows = load_csv(file_name)
    loaded[file_name] = rows
    actual = set(rows[0]) if rows else set()
    missing = sorted(required_fields - actual)
    if missing:
        errors.append(f"{file_name} missing fields: {missing}")

if errors:
    REPORT.write_text(json.dumps({"status": "FAIL", "errors": errors}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(REPORT.read_text(encoding="utf-8"))
    sys.exit(1)

tasks = loaded["task_index.csv"]
memories = loaded["memory_records.csv"]
contexts = loaded["context_set.csv"]
queries = loaded["query_set.csv"]
headers = list(queries[0]) if queries else []

if headers[-2:] != ["status", "rank"]:
    errors.append("status and rank must be the two rightmost fields")
if set(headers) & REMOVED_FIELDS:
    errors.append(f"redundant fields were retained: {sorted(set(headers) & REMOVED_FIELDS)}")

task_ids = {row["task_id"] for row in tasks}
memory_by_id = {row["memory_id"]: row for row in memories}
memory_ids = set(memory_by_id)
context_ids = {row["context_id"] for row in contexts}

for label, values in (
    ("task_id", [row["task_id"] for row in tasks]),
    ("memory_id", [row["memory_id"] for row in memories]),
    ("context_id", [row["context_id"] for row in contexts]),
    ("query_id", [row["query_id"] for row in queries]),
):
    duplicates = [value for value, count in Counter(values).items() if count > 1]
    if duplicates:
        errors.append(f"duplicate {label}: {duplicates[:10]}")

groups: dict[str, list[dict[str, str]]] = defaultdict(list)
normalized_queries: dict[str, list[str]] = defaultdict(list)
normalized_conclusions: dict[str, list[str]] = defaultdict(list)

for row in queries:
    query_id = row["query_id"]
    groups[row["answer_group_id"]].append(row)
    normalized_queries[normalize(row["query_text"])].append(query_id)
    normalized_conclusions[normalize(row["expected_conclusion"])].append(query_id)

    for field in HUMAN_FIELDS[:-2]:
        if not row[field].strip():
            errors.append(f"empty human-review field {field}: {query_id}")
    if len(row["answer_reasoning"]) < 400:
        errors.append(f"answer reasoning is not sufficiently detailed: {query_id}")
    if row["query_text"] not in row["answer_reasoning"]:
        errors.append(f"answer reasoning does not include the full query: {query_id}")
    if any(token in row["answer_reasoning"] or token in row["scoring_rubric_text"] for token in ("同上", "略去", "内容略", "见前文")):
        errors.append(f"omitted review explanation detected: {query_id}")

    if row["status"] not in {"not_pass", "pass"}:
        errors.append(f"invalid human status: {query_id}")
    try:
        rank = int(row["rank"])
    except ValueError:
        errors.append(f"rank is not an integer: {query_id}")
        rank = -1
    if not 0 <= rank <= 5:
        errors.append(f"rank is outside 0..5: {query_id}")

    required_ids = split_ids(row["required_memory_ids"])
    candidate_ids = split_ids(row["candidate_memory_ids"])
    forbidden_ids = split_ids(row["forbidden_memory_ids"])
    role_sets = [set(required_ids), set(candidate_ids), set(forbidden_ids)]
    if role_sets[0] & role_sets[1] or role_sets[0] & role_sets[2] or role_sets[1] & role_sets[2]:
        errors.append(f"overlapping memory roles: {query_id}")
    for memory_id in set(required_ids + candidate_ids + forbidden_ids):
        if memory_id not in memory_ids:
            errors.append(f"missing memory reference {memory_id}: {query_id}")
            continue
        summary = memory_by_id[memory_id]["memory_summary"].rstrip("。；")
        corresponding_field = (
            "required_memory_texts"
            if memory_id in required_ids
            else "candidate_memory_texts"
            if memory_id in candidate_ids
            else "forbidden_memory_texts"
        )
        if summary not in row[corresponding_field]:
            errors.append(f"human memory text does not contain full memory {memory_id}: {query_id}")
    for task_id in split_ids(row["source_task_ids"]):
        if task_id not in task_ids:
            errors.append(f"missing task reference {task_id}: {query_id}")
    for context_id in split_ids(row["current_context_ids"]):
        if context_id not in context_ids:
            errors.append(f"missing context reference {context_id}: {query_id}")

    track = row["evaluation_track"]
    if track == "single_memory" and len(required_ids) != 1:
        errors.append(f"single-memory structure mismatch: {query_id}")
    elif track == "complementary_multi_memory" and len(required_ids) < 2:
        errors.append(f"multi-memory structure mismatch: {query_id}")
    elif track == "conflict_resolution" and (not required_ids or not forbidden_ids):
        errors.append(f"conflict structure mismatch: {query_id}")
    elif track == "clarification_required" and (required_ids or len(candidate_ids) < 2 or row["decision_class"] != "ask_clarification"):
        errors.append(f"clarification structure mismatch: {query_id}")

    try:
        apps = json.loads(row["apps_involved"])
        steps = json.loads(row["workflow_steps_json"])
        handoffs = json.loads(row["handoff_artifacts_json"])
        points = json.loads(row["scoring_points_json"])
    except json.JSONDecodeError:
        errors.append(f"invalid JSON field: {query_id}")
        continue
    if apps != ["libreoffice_calc"] or not isinstance(steps, list) or handoffs != []:
        errors.append(f"unsupported app/workflow metadata: {query_id}")
    if not isinstance(points, list) or not points:
        errors.append(f"missing scoring points: {query_id}")
    else:
        score = sum(float(point.get("weight", 0)) for point in points)
        if abs(score - 1.0) > 0.0001 or row["max_score"] != "1.00":
            errors.append(f"scoring points do not total 1.00: {query_id}")
        for point in points:
            for memory_id in point.get("evidence_memory_ids", []):
                if memory_id not in memory_ids:
                    errors.append(f"scoring point references missing memory {memory_id}: {query_id}")

for group_id, group_rows in groups.items():
    if len(group_rows) != 5:
        errors.append(f"answer group has {len(group_rows)} queries instead of 5: {group_id}")
    if {row["query_type"] for row in group_rows} != CANONICAL_TYPES:
        errors.append(f"answer group does not contain the five canonical query types: {group_id}")
    if len({row["expected_conclusion"] for row in group_rows}) != 1:
        errors.append(f"answer group contains inconsistent conclusions: {group_id}")
    if len({row["dataset_partition"] for row in group_rows}) != 1:
        errors.append(f"answer group crosses dataset partitions: {group_id}")

for ids in normalized_queries.values():
    if len(ids) > 1:
        errors.append(f"normalized duplicate queries: {ids[:10]}")
for ids in normalized_conclusions.values():
    if len(ids) > 5:
        errors.append(f"one normalized conclusion has more than five queries: {ids[:10]}")

track_counts = Counter(row["evaluation_track"] for row in queries)
partition_counts = Counter(row["dataset_partition"] for row in queries)
type_counts = Counter(row["query_type"] for row in queries)
status_counts = Counter(row["status"] for row in queries)
rank_counts = Counter(int(row["rank"]) for row in queries if row["rank"].isdigit())

if len(queries) != 530:
    errors.append(f"query count is {len(queries)}, expected 530")
if len(groups) != 106:
    errors.append(f"answer group count is {len(groups)}, expected 106")
if dict(track_counts) != EXPECTED_TRACKS:
    errors.append(f"track distribution mismatch: {dict(track_counts)}")
if dict(partition_counts) != EXPECTED_PARTITIONS:
    errors.append(f"partition distribution mismatch: {dict(partition_counts)}")
if set(type_counts) != CANONICAL_TYPES or any(count != 106 for count in type_counts.values()):
    errors.append(f"query type distribution mismatch: {dict(type_counts)}")

review_workbook = ROOT / "processed_data_backup" / "query_set_human_review.xlsx"
if not review_workbook.exists():
    errors.append("missing human-review workbook")
if (ROOT / "processed_data_backup" / "query_set.xlsx").exists():
    errors.append("obsolete query_set.xlsx should not coexist with the human-review workbook")

warnings.append("status and rank are human-owned fields; this validator checks only their allowed value ranges.")
warnings.append("The benchmark still contains only 47 independent source operations.")

report = {
    "status": "PASS" if not errors else "FAIL",
    "counts": {
        "tasks": len(tasks),
        "memory_records": len(memories),
        "queries": len(queries),
        "answer_groups": len(groups),
        "unique_normalized_conclusions": len(normalized_conclusions),
    },
    "track_distribution": dict(track_counts),
    "partition_distribution": dict(partition_counts),
    "query_type_distribution": dict(type_counts),
    "human_status_distribution": dict(status_counts),
    "human_rank_distribution": {str(key): value for key, value in sorted(rank_counts.items())},
    "errors": errors,
    "warnings": warnings,
}
REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(report, ensure_ascii=False, indent=2))
sys.exit(1 if errors else 0)
