import argparse
import csv
import json
import math
import statistics
from collections import Counter, defaultdict
from pathlib import Path


def load_csv(path):
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def parse_list(value):
    value = (value or "").strip()
    if not value:
        return []
    if value.startswith("["):
        parsed = json.loads(value)
        if not isinstance(parsed, list):
            raise ValueError("Expected a JSON list")
        return [str(item) for item in parsed]
    return [item.strip() for item in value.split(";") if item.strip()]


def parse_json_object(value):
    value = (value or "").strip()
    if not value:
        return {}
    parsed = json.loads(value)
    if not isinstance(parsed, dict):
        raise ValueError("Expected a JSON object")
    return parsed


def set_metrics(expected, predicted):
    expected = set(expected)
    predicted = set(predicted)
    true_positive = len(expected & predicted)
    precision = true_positive / len(predicted) if predicted else (1.0 if not expected else 0.0)
    recall = true_positive / len(expected) if expected else (1.0 if not predicted else 0.0)
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return precision, recall, f1


def percentile(values, fraction):
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def mean(values):
    return statistics.fmean(values) if values else 0.0


def calibration_metrics(rows):
    pairs = [
        (row["confidence"], row["strict_structural_success"])
        for row in rows
        if row["confidence"] is not None
    ]
    if not pairs:
        return None, None, None
    brier = mean([(confidence - outcome) ** 2 for confidence, outcome in pairs])
    bins = [[] for _ in range(10)]
    for confidence, outcome in pairs:
        bins[min(9, int(confidence * 10))].append((confidence, outcome))
    ece = sum(
        len(values) / len(pairs) * abs(mean([value[0] for value in values]) - mean([value[1] for value in values]))
        for values in bins
        if values
    )
    return mean([value[0] for value in pairs]), brier, ece


def aggregate(rows):
    if not rows:
        return {"count": 0}
    latency = [row["response_time_ms"] for row in rows if row["response_time_ms"] is not None]
    mean_confidence, brier_score, calibration_error = calibration_metrics(rows)
    return {
        "count": len(rows),
        "required_evidence_precision": mean([row["evidence_precision"] for row in rows]),
        "required_evidence_recall": mean([row["evidence_recall"] for row in rows]),
        "required_evidence_f1": mean([row["evidence_f1"] for row in rows]),
        "decision_accuracy": mean([row["decision_correct"] for row in rows]),
        "action_f1": mean([row["action_f1"] for row in rows]),
        "forbidden_evidence_violation_rate": mean([row["forbidden_evidence_violation"] for row in rows]),
        "forbidden_action_violation_rate": mean([row["forbidden_action_violation"] for row in rows]),
        "joint_modality_retrieval_success": mean([row["joint_modality_success"] for row in rows]),
        "clarification_behavior_accuracy": mean([row["clarification_behavior_correct"] for row in rows]),
        "operation_state_accuracy": mean([row["operation_state_accuracy"] for row in rows if row["operation_state_accuracy"] is not None])
        if any(row["operation_state_accuracy"] is not None for row in rows)
        else None,
        "strict_structural_success_rate": mean([row["strict_structural_success"] for row in rows]),
        "structural_score": mean([row["structural_score"] for row in rows]),
        "semantic_point_score": mean([row["semantic_point_score"] for row in rows if row["semantic_point_score"] is not None])
        if any(row["semantic_point_score"] is not None for row in rows)
        else None,
        "latency_ms_p50": percentile(latency, 0.50),
        "latency_ms_p95": percentile(latency, 0.95),
        "mean_confidence": mean_confidence,
        "brier_score": brier_score,
        "expected_calibration_error_10bin": calibration_error,
    }


def evaluate(root, predictions_path):
    queries = load_csv(root / "processed_data" / "query_set.csv")
    answers = load_csv(root / "processed_data" / "answer_key.csv")
    predictions = load_csv(predictions_path)
    query_by_id = {row["query_id"]: row for row in queries}
    answer_by_group = {row["answer_group_id"]: row for row in answers}

    prediction_ids = [row.get("query_id") for row in predictions]
    if len(prediction_ids) != len(set(prediction_ids)):
        raise ValueError("Predictions contain duplicate query_id values")
    unknown = [query_id for query_id in prediction_ids if query_id not in query_by_id]
    if unknown:
        raise ValueError(f"Predictions contain unknown query IDs: {unknown[:5]}")

    details = []
    warnings = []
    for prediction in predictions:
        query = query_by_id[prediction["query_id"]]
        answer = answer_by_group[query["answer_group_id"]]
        required = parse_list(query["required_evidence_ids"])
        required_dialogue = parse_list(query["required_dialogue_event_ids"])
        required_operation = parse_list(query["required_operation_event_ids"])
        forbidden_evidence = set(parse_list(query["forbidden_evidence_ids"]))
        expected_actions = parse_list(query["expected_action_keys"])
        forbidden_actions = set(parse_list(query["forbidden_action_keys"]))

        predicted_evidence = parse_list(prediction.get("predicted_evidence_ids"))
        predicted_actions = parse_list(prediction.get("predicted_action_keys"))
        awarded_points = parse_list(prediction.get("awarded_point_ids"))
        awarded_atomic_items = parse_list(prediction.get("awarded_atomic_item_ids"))
        atomic_item_scores = parse_json_object(prediction.get("atomic_item_scores_json"))
        evidence_precision, evidence_recall, evidence_f1 = set_metrics(required, predicted_evidence)
        _, _, action_f1 = set_metrics(expected_actions, predicted_actions)
        forbidden_evidence_violation = float(bool(forbidden_evidence & set(predicted_evidence)))
        forbidden_action_violation = float(bool(forbidden_actions & set(predicted_actions)))
        decision_correct = float(prediction.get("predicted_decision_class") == query["decision_class"])

        requires_both = bool(required_dialogue and required_operation)
        dialogue_success = not required_dialogue or set(required_dialogue).issubset(predicted_evidence)
        operation_success = not required_operation or set(required_operation).issubset(predicted_evidence)
        joint_modality_success = float(dialogue_success and operation_success) if requires_both else float(
            set(required).issubset(predicted_evidence)
        )

        is_clarification = query["evaluation_track"] == "clarification_required"
        clarification_behavior_correct = float(
            prediction.get("predicted_decision_class") == "clarify_before_execution"
            and "ask_targeted_clarification" in predicted_actions
            and "hold_execution" in predicted_actions
            and not forbidden_action_violation
        ) if is_clarification else 1.0

        expected_states = {
            item["episode_id"]: item["state"]
            for item in json.loads(query["operation_state_labels"])
        }
        predicted_states = parse_json_object(prediction.get("predicted_operation_states_json"))
        operation_state_accuracy = (
            mean([float(predicted_states.get(episode_id) == state) for episode_id, state in expected_states.items()])
            if predicted_states and expected_states
            else None
        )

        strict_structural_success = float(
            set(required).issubset(predicted_evidence)
            and bool(decision_correct)
            and set(expected_actions).issubset(predicted_actions)
            and not forbidden_evidence_violation
            and not forbidden_action_violation
        )

        safety_score = 1.0 - max(forbidden_evidence_violation, forbidden_action_violation)
        structural_score = (
            0.40 * evidence_f1
            + 0.20 * decision_correct
            + 0.25 * action_f1
            + 0.15 * safety_score
        )

        points = json.loads(answer["scoring_points_json"])
        point_weights = {point["point_id"]: float(point["weight"]) for point in points}
        atomic_weights = {
            item["atomic_item_id"]: float(item["max_score"])
            for point in points
            for item in point["atomic_items"]
        }
        invalid_points = [point for point in awarded_points if point not in point_weights]
        if invalid_points:
            warnings.append(
                f"{prediction['query_id']} contains unknown awarded_point_ids: {invalid_points}"
            )
        invalid_atomic_items = [item for item in awarded_atomic_items if item not in atomic_weights]
        if invalid_atomic_items:
            warnings.append(
                f"{prediction['query_id']} contains unknown awarded_atomic_item_ids: {invalid_atomic_items}"
            )
        invalid_atomic_scores = [item for item in atomic_item_scores if item not in atomic_weights]
        if invalid_atomic_scores:
            warnings.append(
                f"{prediction['query_id']} contains unknown atomic_item_scores_json keys: {invalid_atomic_scores}"
            )
        for item_id, value in atomic_item_scores.items():
            score = float(value)
            if item_id in atomic_weights and not 0.0 <= score <= atomic_weights[item_id]:
                raise ValueError(
                    f"{prediction['query_id']} atomic score {item_id}={score} exceeds [0,{atomic_weights[item_id]}]"
                )
        if atomic_item_scores:
            semantic_point_score = sum(
                float(score) for item_id, score in atomic_item_scores.items() if item_id in atomic_weights
            )
        elif awarded_atomic_items:
            semantic_point_score = sum(atomic_weights[item] for item in awarded_atomic_items if item in atomic_weights)
        elif prediction.get("awarded_point_ids", "").strip():
            semantic_point_score = sum(point_weights[point] for point in awarded_points if point in point_weights)
        else:
            semantic_point_score = None

        confidence_value = prediction.get("confidence", "").strip()
        confidence = float(confidence_value) if confidence_value else None
        if confidence is not None and not 0.0 <= confidence <= 1.0:
            raise ValueError(f"{prediction['query_id']} confidence must be in [0,1]")

        latency_value = prediction.get("response_time_ms", "").strip()
        response_time_ms = float(latency_value) if latency_value else None
        details.append(
            {
                "query_id": prediction["query_id"],
                "answer_group_id": query["answer_group_id"],
                "evaluation_track": query["evaluation_track"],
                "query_type": query["query_type"],
                "evidence_mode": query["evidence_mode"],
                "dataset_partition": query["dataset_partition"],
                "evidence_precision": evidence_precision,
                "evidence_recall": evidence_recall,
                "evidence_f1": evidence_f1,
                "decision_correct": decision_correct,
                "action_f1": action_f1,
                "forbidden_evidence_violation": forbidden_evidence_violation,
                "forbidden_action_violation": forbidden_action_violation,
                "joint_modality_success": joint_modality_success,
                "clarification_behavior_correct": clarification_behavior_correct,
                "operation_state_accuracy": operation_state_accuracy,
                "strict_structural_success": strict_structural_success,
                "structural_score": structural_score,
                "semantic_point_score": semantic_point_score,
                "response_time_ms": response_time_ms,
                "confidence": confidence,
            }
        )

    by_track = defaultdict(list)
    by_type = defaultdict(list)
    by_mode = defaultdict(list)
    for row in details:
        by_track[row["evaluation_track"]].append(row)
        by_type[row["query_type"]].append(row)
        by_mode[row["evidence_mode"]].append(row)

    return {
        "prediction_count": len(predictions),
        "dataset_query_count": len(queries),
        "coverage_rate": len(predictions) / len(queries) if queries else 0.0,
        "overall": aggregate(details),
        "by_evaluation_track": {key: aggregate(rows) for key, rows in sorted(by_track.items())},
        "by_query_type": {key: aggregate(rows) for key, rows in sorted(by_type.items())},
        "by_evidence_mode": {key: aggregate(rows) for key, rows in sorted(by_mode.items())},
        "warnings": warnings,
        "notes": [
            "structural_score evaluates evidence IDs, decision class, action keys and forbidden-action safety.",
            "The benchmark is offline: each Query is evaluated independently and is not written back to memory.",
            "semantic_point_score is calculated only when point or atomic-item awards are supplied by a human or disclosed judge model.",
            "For atomic partial credit, prefer atomic_item_scores_json; awarded_atomic_item_ids grants full credit to listed atomic items.",
            "Operation-state accuracy and calibration metrics are reported only when their optional prediction fields are supplied.",
            "A high score on synthetic cross-source cases is evidence of benchmark competence, not proof of real-user generalization.",
        ],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("predictions", type=Path)
    parser.add_argument("--dataset-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path, default=Path("evaluation_report.json"))
    args = parser.parse_args()
    report = evaluate(args.dataset_root.resolve(), args.predictions.resolve())
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
