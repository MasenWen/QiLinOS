from __future__ import annotations

import json
import unittest

from tools.build_memory_retention_annotation_packets import (
    build_annotation_packets,
)


class MemoryRetentionAnnotationPacketsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.payload = build_annotation_packets()

    def test_all_memories_are_present_once(self) -> None:
        memory_ids = [
            member["memory_id"]
            for packet in self.payload["packets"]
            for member in packet["members"]
        ]

        self.assertEqual(191, len(memory_ids))
        self.assertEqual(191, len(set(memory_ids)))

    def test_packets_do_not_contain_lifecycle_predictions(self) -> None:
        serialized = json.dumps(
            self.payload["packets"],
            ensure_ascii=False,
        ).casefold()

        for forbidden in (
            '"stability"',
            '"confidence"',
            '"status"',
            '"activation_count"',
            '"forgotten_at"',
            '"temporal_label"',
            '"predicted_observations"',
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, serialized)

    def test_future_demand_uses_gold_not_predictions(self) -> None:
        demand = [
            item
            for packet in self.payload["packets"]
            for item in packet["future_gold_demand"]
        ]

        self.assertGreater(len(demand), 0)
        self.assertTrue(all("case_id" in item for item in demand))
        self.assertTrue(all("day" in item for item in demand))


if __name__ == "__main__":
    unittest.main()
