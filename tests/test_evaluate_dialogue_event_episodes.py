from __future__ import annotations

import unittest
from datetime import datetime, timezone

from tools.evaluate_dialogue_event_episodes import (
    DialogueRecord,
    _evaluate_groups,
    _source_event,
)


def _record() -> DialogueRecord:
    return DialogueRecord(
        message_text="Keep the current task together.",
        scenario_id="office_automation",
        ability_id="operation_habit_capture",
        utterance_role="clarification",
        memory_signal_type="operation_habit",
        preference_scope="cross_session",
        referenced_app_ids=("document_editor", "email_client"),
        event_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
        user_id="U001",
        event_id="event-1",
        gold_episode_id="gold-episode-1",
        split="test",
        supersedes_event_id="",
        conflict_group_id="",
    )


class DialogueEpisodeEvaluationTest(unittest.TestCase):
    def test_source_event_does_not_expose_gold_episode_id(self) -> None:
        record = _record()

        event = _source_event(
            record,
            event_id="blind:event-1",
            user_id="U001",
            session_id="S001",
            event_time=record.event_time,
        )

        self.assertNotIn("episode_id", event)
        self.assertNotIn("gold_episode_id", event)
        self.assertEqual(
            "clarification",
            event["utterance_role"],
        )

    def test_merge_precision_and_recall_are_reported_separately(self) -> None:
        ordered = ["a", "b", "c"]
        gold = {"a": "g1", "b": "g1", "c": "g2"}
        predicted = {"a": "p1", "b": "p1", "c": "p1"}

        metrics = _evaluate_groups(ordered, gold, predicted)

        self.assertEqual(1.0, metrics["merge_recall"])
        self.assertAlmostEqual(1 / 3, metrics["merge_precision"])
        self.assertEqual(0.0, metrics["exact_episode_rate"])
        self.assertEqual(0, metrics["split_gold_episodes"])
        self.assertEqual(1, metrics["overmerged_predicted_episodes"])


if __name__ == "__main__":
    unittest.main()
