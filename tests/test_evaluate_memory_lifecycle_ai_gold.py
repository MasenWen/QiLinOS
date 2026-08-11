from __future__ import annotations

import unittest

from tools.evaluate_memory_lifecycle import (
    DEFAULT_MEMORIES,
    DEFAULT_OBSERVATIONS,
    build_fixture,
    run_combination,
)
from tools.evaluate_memory_lifecycle_ai_gold import evaluate_ai_gold
from tools.materialize_ai_retention_annotations import (
    materialize_annotations,
)


class MemoryLifecycleAIGoldEvaluationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        initial, late, relations, _ = build_fixture(DEFAULT_MEMORIES)
        cls.lifecycle, cls.engine = run_combination(
            "actr",
            "beta_temporal",
            observation_path=DEFAULT_OBSERVATIONS,
            initial_seeds=initial,
            late_seeds=late,
            relations=relations,
        )
        cls.annotations = materialize_annotations()
        cls.result = evaluate_ai_gold(
            cls.engine,
            cls.annotations,
            cls.lifecycle,
        )

    def test_uncertain_annotations_are_excluded_from_binary_score(
        self,
    ) -> None:
        self.assertEqual(183, self.result["binary_scored_count"])
        self.assertEqual(8, self.result["uncertain_count"])

    def test_confusion_matrix_accounts_for_all_annotations(self) -> None:
        confusion = self.result["confusion"]

        self.assertEqual(19, confusion["keep"])
        self.assertEqual(164, confusion["forget"])
        self.assertEqual(8, confusion["uncertain"])
        self.assertEqual(
            19,
            confusion["keep_active"] + confusion["keep_forgotten"],
        )
        self.assertEqual(
            164,
            confusion["forget_active"]
            + confusion["forget_forgotten"],
        )

    def test_ai_metrics_are_bounded(self) -> None:
        for key in (
            "keep_recall",
            "forget_recall",
            "balanced_accuracy",
            "binary_accuracy",
            "confidence_weighted_accuracy",
        ):
            with self.subTest(metric=key):
                self.assertGreaterEqual(self.result[key], 0.0)
                self.assertLessEqual(self.result[key], 1.0)


if __name__ == "__main__":
    unittest.main()
