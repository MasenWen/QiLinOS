from __future__ import annotations

import json
import unittest
from pathlib import Path

from tools.evaluate_kylin_os_agent_observations_v31 import (
    _chinese_punctuation_as_spaces,
    _grade_case,
    _summarize,
)
from tools.os_agent_observation_annotations import (
    ACTION_ANNOTATIONS,
    build_annotation_dataset,
)


ROOT = Path(__file__).resolve().parents[1]
DATASET_ROOT = (
    ROOT.parent
    / "os_agent_memory_query_benchmark_v3.1"
    / "os_agent_memory_query_benchmark_v3.1_20260725"
)
GOLD = ROOT / "tests" / "data" / (
    "os_agent_observation_benchmark_v31.json"
)


class OsAgentObservationAnnotationTest(unittest.TestCase):
    def test_chinese_punctuation_can_be_replaced_without_damaging_ids(
        self,
    ) -> None:
        text = (
            "请处理 SalesRep.xlsx：B1:E30 先补齐，"
            "再沿用“之前”的顺序。"
        )
        self.assertEqual(
            "请处理 SalesRep.xlsx B1:E30 先补齐 再沿用 之前 的顺序",
            _chinese_punctuation_as_spaces(text),
        )
        english = "Use SalesRep.xlsx: keep B1:E30 unchanged."
        self.assertEqual(
            english,
            _chinese_punctuation_as_spaces(english),
        )

    def test_catalog_covers_every_source_action(self) -> None:
        dataset = build_annotation_dataset(DATASET_ROOT)
        self.assertEqual(47, dataset["audit"]["task_count"])
        self.assertEqual(47, len(ACTION_ANNOTATIONS))
        self.assertEqual(48, dataset["audit"]["object_tag_count"])

    def test_export_contains_events_and_all_queries(self) -> None:
        dataset = json.loads(GOLD.read_text(encoding="utf-8"))
        events = [
            case for case in dataset["cases"]
            if case["source_kind"] == "event"
        ]
        queries = [
            case for case in dataset["cases"]
            if case["source_kind"] == "query"
        ]
        self.assertEqual(47, len(events))
        self.assertEqual(530, len(queries))
        self.assertEqual(577, len(dataset["cases"]))
        self.assertEqual(
            {"explicit": 747},
            dataset["audit"]["support_counts"]["object"],
        )

    def test_lifecycle_metadata_is_not_temporal_gold(self) -> None:
        dataset = json.loads(GOLD.read_text(encoding="utf-8"))
        event = next(
            case for case in dataset["cases"]
            if case["id"].startswith("event:")
        )
        self.assertEqual(
            [],
            event["gold_observations"][0]["temporal_labels"],
        )

    def test_clarification_does_not_commit_candidate_action(self) -> None:
        dataset = json.loads(GOLD.read_text(encoding="utf-8"))
        case = next(
            value for value in dataset["cases"]
            if value["id"] == "query:V3_AQ01_Q01"
        )
        self.assertEqual(
            "object:ambiguous_prior_workflow",
            case["gold_observations"][0]["object_tag_id"],
        )

    def test_scoring_accepts_one_of_multiple_temporal_labels(self) -> None:
        gold = [
            {
                "condition_tag_id": "condition:a",
                "object_tag_id": "object:a",
                "attitude_direction": "positive",
                "temporal_labels": [
                    "temporal_short",
                    "temporal_long",
                ],
                "support": {
                    "condition": "explicit",
                    "object": "explicit",
                    "attitude": "explicit",
                    "temporal": "explicit",
                },
            }
        ]
        prediction = [
            {
                "condition_tag_id": "condition:a",
                "object_tag_id": "object:a",
                "attitude_direction": "positive",
                "temporal_label": "temporal_long",
                "confidence": 0.9,
            }
        ]
        grade = _grade_case(gold, prediction)
        self.assertEqual(1, grade["exact_observations"])

    def test_implicit_role_is_excluded_only_from_fair_score(self) -> None:
        gold = [
            {
                "condition_tag_id": "condition:a",
                "object_tag_id": "object:a",
                "attitude_direction": "positive",
                "temporal_labels": [],
                "support": {
                    "condition": "implicit",
                    "object": "explicit",
                    "attitude": "explicit",
                    "temporal": "null",
                },
            }
        ]
        prediction = [
            {
                "condition_tag_id": None,
                "object_tag_id": "object:a",
                "attitude_direction": "positive",
                "temporal_label": None,
                "confidence": 0.9,
            }
        ]
        grade = _grade_case(gold, prediction)
        summary = _summarize([{"grade": grade}])
        self.assertEqual(
            0,
            summary["role_accuracy_all"]["condition"]["correct"],
        )
        self.assertEqual(
            0,
            summary["role_accuracy_extractable"]["condition"]["total"],
        )

    def test_temporal_adjacent_error_receives_partial_credit(self) -> None:
        gold = [
            {
                "condition_tag_id": "condition:a",
                "object_tag_id": "object:a",
                "attitude_direction": "positive",
                "temporal_labels": ["temporal_short"],
                "support": {
                    "condition": "explicit",
                    "object": "explicit",
                    "attitude": "explicit",
                    "temporal": "explicit",
                },
            }
        ]
        prediction = [
            {
                "condition_tag_id": "condition:a",
                "object_tag_id": "object:a",
                "attitude_direction": "positive",
                "temporal_label": "temporal_medium",
                "confidence": 0.9,
            }
        ]
        grade = _grade_case(gold, prediction)
        summary = _summarize([{"grade": grade}])
        self.assertEqual(
            0.70,
            grade["pairs"][0]["role_credit"]["temporal"],
        )
        self.assertEqual(0, grade["exact_observations"])
        self.assertEqual(
            0.70,
            summary["role_accuracy_all"]["temporal"]["accuracy"],
        )

    def test_temporal_opposite_error_is_still_severely_penalized(self) -> None:
        gold = [
            {
                "condition_tag_id": "condition:a",
                "object_tag_id": "object:a",
                "attitude_direction": "positive",
                "temporal_labels": ["temporal_short"],
                "support": {
                    "condition": "explicit",
                    "object": "explicit",
                    "attitude": "explicit",
                    "temporal": "explicit",
                },
            }
        ]
        prediction = [
            {
                "condition_tag_id": "condition:a",
                "object_tag_id": "object:a",
                "attitude_direction": "positive",
                "temporal_label": "temporal_long",
                "confidence": 0.9,
            }
        ]
        grade = _grade_case(gold, prediction)
        self.assertEqual(
            0.15,
            grade["pairs"][0]["role_credit"]["temporal"],
        )


if __name__ == "__main__":
    unittest.main()
