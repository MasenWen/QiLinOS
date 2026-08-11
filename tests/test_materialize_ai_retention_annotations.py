from __future__ import annotations

import unittest

from tools.materialize_ai_retention_annotations import (
    materialize_annotations,
)


class AIRetentionAnnotationsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.payload = materialize_annotations()

    def test_every_memory_receives_exactly_one_label(self) -> None:
        annotations = self.payload["annotations"]
        memory_ids = [item["memory_id"] for item in annotations]

        self.assertEqual(191, len(annotations))
        self.assertEqual(191, len(set(memory_ids)))
        self.assertEqual(
            {"keep", "forget", "uncertain"},
            {item["label"] for item in annotations},
        )

    def test_uncertain_is_not_forced_into_binary_gold(self) -> None:
        counts = self.payload["label_counts"]

        self.assertEqual(19, counts["keep"])
        self.assertEqual(164, counts["forget"])
        self.assertEqual(8, counts["uncertain"])
        self.assertEqual(183, self.payload["binary_scored_count"])

    def test_all_three_reasoning_perspectives_are_recorded(self) -> None:
        for annotation in self.payload["annotations"]:
            self.assertIn("semantic_vote", annotation)
            self.assertIn("chronology_vote", annotation)
            self.assertIn("safety_vote", annotation)
            self.assertTrue(annotation["rationale"])

    def test_each_retained_group_has_only_one_representative(self) -> None:
        kept_by_group = {}
        for annotation in self.payload["annotations"]:
            if annotation["label"] != "keep":
                continue
            kept_by_group.setdefault(
                annotation["group_id"],
                [],
            ).append(annotation["memory_id"])

        self.assertEqual(19, len(kept_by_group))
        self.assertTrue(
            all(len(memory_ids) == 1 for memory_ids in kept_by_group.values())
        )


if __name__ == "__main__":
    unittest.main()
