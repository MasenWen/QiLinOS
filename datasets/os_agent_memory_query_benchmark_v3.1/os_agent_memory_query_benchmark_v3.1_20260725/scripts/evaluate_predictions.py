from __future__ import annotations

import argparse
import csv
import json
import math
from collections import defaultdict
from pathlib import Path
from statistics import mean


def load_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def parse_list(value: str) -> list[str]:
    value = (value or "").strip()
    if not value:
        return []
    if value.startswith("["):
        try:
            parsed = json.loads(value)
            return [str(item) for item in parsed] if isinstance(parsed, list) else []
        except json.JSONDecodeError:
            pass
    return [item.strip() for item in value.split("|") if item.strip()]


def safe_float(value: str) -> float | None:
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def ratio(numerator: float, denominator: int) -> float | None:
    return round(numerator / denominator, 6) if denominator else None


def summarize(rows: list[dict[str, object]]) -> dict[str, object]:
    retrieval_rows = [row for row in rows if row["has_required"]]
    conflict_rows = [row for row in rows if row["has_forbidden"]]
    action_rows = [row for row in rows if row["has_action"]]
    scored_rows = [row for row in rows if row["point_score"] is not None]
    latencies = sorted(float(row["latency_ms"]) for row in rows if row["latency_ms"] is not None)
    return {
        "queries": len(rows),
        "required_memory_exact_set_accuracy": ratio(sum(bool(row["required_exact"]) for row in retrieval_rows), len(retrieval_rows)),
        "required_memory_recall_at_1": ratio(sum(float(row["recall_at_1"]) for row in retrieval_rows), len(retrieval_rows)),
        "required_memory_recall_at_3": ratio(sum(float(row["recall_at_3"]) for row in retrieval_rows), len(retrieval_rows)),
        "required_memory_recall_at_5": ratio(sum(float(row["recall_at_5"]) for row in retrieval_rows), len(retrieval_rows)),
        "all_required_hit_at_5": ratio(sum(bool(row["all_required_at_5"]) for row in retrieval_rows), len(retrieval_rows)),
        "mrr_first_required": ratio(sum(float(row["reciprocal_rank"]) for row in retrieval_rows), len(retrieval_rows)),
        "forbidden_exposure_at_5": ratio(sum(bool(row["forbidden_at_5"]) for row in conflict_rows), len(conflict_rows)),
        "decision_accuracy": ratio(sum(bool(row["decision_correct"]) for row in rows), len(rows)),
        "action_set_exact_match": ratio(sum(bool(row["action_correct"]) for row in action_rows), len(action_rows)),
        "point_based_conclusion_score": ratio(sum(float(row["point_score"]) for row in scored_rows), len(scored_rows)),
        "point_scored_queries": len(scored_rows),
        "mean_response_time_ms": round(mean(latencies), 3) if latencies else None,
        "p95_response_time_ms": latencies[max(0, math.ceil(0.95 * len(latencies)) - 1)] if latencies else None,
    }


parser = argparse.ArgumentParser(description="Evaluate v3.1 OS Agent memory predictions.")
parser.add_argument("predictions", type=Path)
parser.add_argument(
    "--gold",
    type=Path,
    default=Path(__file__).resolve().parents[1] / "processed_data" / "query_set.csv",
)
parser.add_argument("--output", type=Path)
args = parser.parse_args()

gold_rows = load_csv(args.gold)
prediction_rows = load_csv(args.predictions)
gold = {row["query_id"]: row for row in gold_rows}
predictions = {row["query_id"]: row for row in prediction_rows}

missing = sorted(set(gold) - set(predictions))
extra = sorted(set(predictions) - set(gold))
evaluated: list[dict[str, object]] = []

for query_id, answer in gold.items():
    prediction = predictions.get(query_id)
    if prediction is None:
        continue
    required = set(parse_list(answer["required_memory_ids"]))
    forbidden = set(parse_list(answer["forbidden_memory_ids"]))
    ranked = parse_list(prediction.get("predicted_memory_ids", ""))
    ranked_set = set(ranked)

    def recall_at(k: int) -> float:
        return len(required.intersection(ranked[:k])) / len(required) if required else 0.0

    first_required_rank = next((index + 1 for index, memory_id in enumerate(ranked) if memory_id in required), None)
    expected_actions = set(parse_list(answer.get("expected_action_keys", "")))
    predicted_actions = set(parse_list(prediction.get("predicted_action_keys", "")))

    point_score: float | None = None
    awarded_points = set(parse_list(prediction.get("awarded_point_ids", "")))
    if "awarded_point_ids" in prediction and prediction.get("awarded_point_ids", "").strip():
        points = json.loads(answer["scoring_points_json"])
        known_point_ids = {str(point["point_id"]) for point in points}
        unknown = awarded_points - known_point_ids
        if unknown:
            raise ValueError(f"{query_id} has unknown awarded_point_ids: {sorted(unknown)}")
        point_score = sum(float(point["weight"]) for point in points if str(point["point_id"]) in awarded_points)

    evaluated.append(
        {
            "query_id": query_id,
            "track": answer["evaluation_track"],
            "partition": answer["dataset_partition"],
            "has_required": bool(required),
            "has_forbidden": bool(forbidden),
            "has_action": bool(expected_actions),
            "required_exact": ranked_set == required,
            "recall_at_1": recall_at(1),
            "recall_at_3": recall_at(3),
            "recall_at_5": recall_at(5),
            "all_required_at_5": bool(required) and required.issubset(set(ranked[:5])),
            "reciprocal_rank": 1 / first_required_rank if first_required_rank else 0.0,
            "forbidden_at_5": bool(forbidden.intersection(ranked[:5])),
            "decision_correct": prediction.get("predicted_decision_class", "") == answer["decision_class"],
            "action_correct": predicted_actions == expected_actions,
            "point_score": point_score,
            "latency_ms": safe_float(prediction.get("response_time_ms", "")),
        }
    )

by_track: dict[str, list[dict[str, object]]] = defaultdict(list)
by_partition: dict[str, list[dict[str, object]]] = defaultdict(list)
for row in evaluated:
    by_track[str(row["track"])].append(row)
    by_partition[str(row["partition"])].append(row)

result = {
    "gold_queries": len(gold),
    "evaluated_queries": len(evaluated),
    "coverage": ratio(len(evaluated), len(gold)),
    "missing_prediction_count": len(missing),
    "extra_prediction_count": len(extra),
    "overall": summarize(evaluated),
    "by_evaluation_track": {key: summarize(value) for key, value in sorted(by_track.items())},
    "by_dataset_partition": {key: summarize(value) for key, value in sorted(by_partition.items())},
    "missing_query_ids_sample": missing[:20],
    "extra_query_ids_sample": extra[:20],
    "notes": [
        "Point-based conclusion score is reported only when predictions provide awarded_point_ids.",
        "awarded_point_ids should come from a separate human or disclosed LLM judge; it is not inferred by this script.",
        "For clarification_required rows, required-memory retrieval metrics are not applicable; decision accuracy remains applicable.",
    ],
}
text = json.dumps(result, ensure_ascii=False, indent=2)
print(text)
if args.output:
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(text, encoding="utf-8")
