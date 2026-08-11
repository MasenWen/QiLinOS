from __future__ import annotations

import unittest

from src.memory_engine.memory_lifecycle import LifecycleObservation
from tools.evaluate_memory_lifecycle import (
    DEFAULT_MEMORIES,
    DEFAULT_OBSERVATIONS,
    REPLAY_TOP_K,
    _observation_supports_key,
    build_fixture,
    run_combination,
)


class MemoryLifecycleEvaluationTest(unittest.TestCase):
    def test_replay_top_k_is_fixed_before_answers_are_scored(self) -> None:
        self.assertEqual(2, REPLAY_TOP_K)

    def test_partial_observation_compatibility_is_explicit(self) -> None:
        key = (
            "condition:file:sheet",
            "object:action:chart",
            "support",
        )
        partial = LifecycleObservation(
            observation_id="partial",
            user_id="user",
            observed_at="2026-01-01T00:00:00+00:00",
            source_kind="query",
            object_tag_ids=("object:action:chart",),
            attitude_polarity="support",
        )
        opposite = LifecycleObservation(
            observation_id="opposite",
            user_id="user",
            observed_at="2026-01-01T00:00:00+00:00",
            source_kind="query",
            object_tag_ids=("object:action:chart",),
            attitude_polarity="oppose",
        )

        self.assertTrue(_observation_supports_key(partial, key))
        self.assertFalse(_observation_supports_key(opposite, key))

    @unittest.skipUnless(
        DEFAULT_MEMORIES.exists() and DEFAULT_OBSERVATIONS.exists(),
        "lifecycle replay fixtures are not present",
    )
    def test_fixed_replay_flow_is_internally_consistent(self) -> None:
        initial, late, relations, fixture = build_fixture(
            DEFAULT_MEMORIES
        )

        result, _ = run_combination(
            "fsrs",
            "beta_temporal",
            observation_path=DEFAULT_OBSERVATIONS,
            initial_seeds=initial,
            late_seeds=late,
            relations=relations,
        )

        retrieval = result["retrieval"]
        lifecycle = result["lifecycle"]
        self.assertEqual(191, fixture["raw_memory_count"])
        self.assertEqual(
            retrieval["eligible_case_count"],
            sum(retrieval["failure_stage_counts"].values()),
        )
        self.assertEqual(1.0, lifecycle["active_refresh_survival"])
        self.assertEqual(1.0, lifecycle["stale_short_forget_rate"])
        self.assertEqual(1.0, lifecycle["positive_relation_lift_rate"])
        self.assertEqual(
            1.0,
            lifecycle["conflict_confidence_drop_rate"],
        )
        self.assertEqual(
            1.0,
            lifecycle["late_positive_relation_lift_rate"],
        )


if __name__ == "__main__":
    unittest.main()
