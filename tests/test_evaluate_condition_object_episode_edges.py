from __future__ import annotations

import unittest

from tools.evaluate_condition_object_episode_edges import (
    EventSemanticMatch,
    _semantic_groups,
)


def _row(
    event_id: str,
    *,
    seconds: int,
    condition: str | None,
    obj: str | None,
) -> EventSemanticMatch:
    return EventSemanticMatch(
        event_id=event_id,
        gold_episode_id="unused",
        event_time=f"2026-01-01T00:00:{seconds:02d}+00:00",
        text=event_id,
        condition_tag_id=condition,
        condition_similarity=0.8 if condition else None,
        condition_exact=False,
        object_tag_id=obj,
        object_similarity=0.8 if obj else None,
        object_exact=False,
        gold_condition_tag_id="unused",
        gold_object_tag_id="unused",
        canonical_matches=(),
        latency_ms=1.0,
        embedding_requested=1,
        embedding_computed=1,
    )


class ConditionObjectEpisodeEdgeTests(unittest.TestCase):
    def test_condition_conflict_has_priority_over_object_overlap(
        self,
    ) -> None:
        rows = [
            _row(
                "first",
                seconds=0,
                condition="task:a",
                obj="rule:x",
            ),
            _row(
                "extension",
                seconds=5,
                condition="task:b",
                obj="rule:x",
            ),
        ]

        predicted, decisions = _semantic_groups(
            rows,
            use_condition=True,
            use_object=True,
            time_fallback_seconds=None,
        )

        self.assertNotEqual(
            predicted["first"],
            predicted["extension"],
        )
        self.assertEqual(
            decisions[1]["reason"],
            "condition_conflict",
        )

    def test_object_overlap_fills_an_unknown_condition(
        self,
    ) -> None:
        rows = [
            _row(
                "first",
                seconds=0,
                condition="task:a",
                obj="rule:x",
            ),
            _row(
                "clarification",
                seconds=5,
                condition=None,
                obj="rule:x",
            ),
        ]

        predicted, decisions = _semantic_groups(
            rows,
            use_condition=True,
            use_object=True,
            time_fallback_seconds=None,
        )

        self.assertEqual(
            predicted["first"],
            predicted["clarification"],
        )
        self.assertEqual(decisions[1]["reason"], "object_overlap")

    def test_two_semantic_conflicts_start_a_new_episode(
        self,
    ) -> None:
        rows = [
            _row(
                "first",
                seconds=0,
                condition="task:a",
                obj="rule:x",
            ),
            _row(
                "second",
                seconds=5,
                condition="task:b",
                obj="rule:y",
            ),
        ]

        predicted, decisions = _semantic_groups(
            rows,
            use_condition=True,
            use_object=True,
            time_fallback_seconds=None,
        )

        self.assertNotEqual(
            predicted["first"],
            predicted["second"],
        )
        self.assertEqual(
            decisions[1]["reason"],
            "condition_conflict",
        )

    def test_null_is_unknown_and_time_can_be_a_fallback(
        self,
    ) -> None:
        rows = [
            _row(
                "first",
                seconds=0,
                condition="task:a",
                obj="rule:x",
            ),
            _row(
                "unknown",
                seconds=40,
                condition=None,
                obj=None,
            ),
        ]

        without_time, _ = _semantic_groups(
            rows,
            use_condition=True,
            use_object=True,
            time_fallback_seconds=None,
        )
        with_time, decisions = _semantic_groups(
            rows,
            use_condition=True,
            use_object=True,
            time_fallback_seconds=30.0,
        )

        self.assertEqual(
            without_time["first"],
            without_time["unknown"],
        )
        self.assertNotEqual(
            with_time["first"],
            with_time["unknown"],
        )
        self.assertEqual(
            decisions[1]["reason"],
            "semantic_unknown_time_fallback",
        )

    def test_evaluator_uses_retroactive_condition_boundary(
        self,
    ) -> None:
        rows = [
            _row(
                "old-task",
                seconds=0,
                condition="task:a",
                obj="rule:x",
            ),
            _row(
                "new-task-introduction",
                seconds=5,
                condition=None,
                obj="rule:y",
            ),
            _row(
                "new-task-detail",
                seconds=10,
                condition="task:b",
                obj="rule:y",
            ),
        ]

        predicted, decisions = _semantic_groups(
            rows,
            use_condition=True,
            use_object=True,
            time_fallback_seconds=None,
            retroactive_unknown_condition=True,
            object_conflict_confirmation=2,
        )

        self.assertNotEqual(
            predicted["old-task"],
            predicted["new-task-introduction"],
        )
        self.assertEqual(
            predicted["new-task-introduction"],
            predicted["new-task-detail"],
        )
        self.assertEqual(
            "condition_unknown_reassigned",
            decisions[1]["reason"],
        )
