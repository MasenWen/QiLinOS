from __future__ import annotations

import unittest

from src.memory_engine.preference_episode import (
    PreferenceEpisodeConfig,
    PreferenceEpisodeEngine,
)
from src.memory_engine.preference_matching import PreferenceObservationMemory


def _observation(
    index: int,
    *,
    minute: int | None = None,
    condition: str = "app:spreadsheet",
    object_id: str = "chart:bar",
    attitude: float = 0.5,
    attitude_confidence: float = 0.55,
    extraction_confidence: float = 0.55,
    temporal: str = "temporal_short",
    source_event_id: str | None = None,
    memory_id: str | None = None,
) -> PreferenceObservationMemory:
    minute = index if minute is None else minute
    source_event_id = source_event_id or f"event-{index}"
    return PreferenceObservationMemory(
        memory_id=memory_id or f"obs-pref-{index}",
        observation_id=f"observation-{index}",
        source_event_id=source_event_id,
        user_id="user-1",
        session_id="session-1",
        observed_time=f"2026-07-27T10:{minute:02d}:00+00:00",
        source_text=f"source text {index}",
        condition_tag_id=condition,
        condition_name=condition,
        condition_text=condition,
        object_tag_id=object_id,
        object_name=object_id,
        object_text=object_id,
        attitude_value=attitude,
        attitude_anchor="test",
        attitude_confidence=attitude_confidence,
        temporal_label=temporal,
        promotion_seed=0.0 if temporal == "temporal_short" else 1.0,
        explicit_long_term=temporal == "temporal_long",
        extraction_confidence=extraction_confidence,
        source_start=0,
        source_end=10,
    )


class PreferenceEpisodeGroupingTest(unittest.TestCase):
    def test_condition_time_and_order_define_episode(self) -> None:
        engine = PreferenceEpisodeEngine()
        observations = [
            _observation(0),
            _observation(1, condition="app:browser"),
            _observation(2),
        ]

        episodes = engine.group(observations)

        spreadsheet = next(
            item
            for item in episodes
            if item.condition_tag_id == "app:spreadsheet"
        )
        self.assertEqual(2, len(spreadsheet.observations))
        self.assertEqual((0, 2), spreadsheet.sequence_positions)
        self.assertEqual(2, len(episodes))

    def test_large_time_gap_splits_same_condition(self) -> None:
        engine = PreferenceEpisodeEngine()

        episodes = engine.group(
            [
                _observation(0, minute=0),
                _observation(1, minute=16),
            ]
        )

        self.assertEqual(2, len(episodes))

    def test_too_many_intervening_tasks_split_same_condition(self) -> None:
        engine = PreferenceEpisodeEngine(
            PreferenceEpisodeConfig(max_intervening_observations=2)
        )
        observations = [
            _observation(0),
            _observation(1, condition="condition:one"),
            _observation(2, condition="condition:two"),
            _observation(3, condition="condition:three"),
            _observation(4),
        ]

        episodes = engine.group(observations)

        spreadsheet = [
            item
            for item in episodes
            if item.condition_tag_id == "app:spreadsheet"
        ]
        self.assertEqual(2, len(spreadsheet))

    def test_missing_condition_remains_singleton(self) -> None:
        engine = PreferenceEpisodeEngine()

        episodes = engine.group(
            [
                _observation(0, condition=""),
                _observation(1, condition=""),
            ]
        )

        self.assertEqual(2, len(episodes))
        self.assertTrue(all(len(item.observations) == 1 for item in episodes))

    def test_replayed_memory_is_idempotent(self) -> None:
        engine = PreferenceEpisodeEngine()
        observation = _observation(0)

        episodes = engine.group([observation, observation])

        self.assertEqual(1, len(episodes))
        self.assertEqual(1, len(episodes[0].observations))

    def test_reused_source_id_after_other_work_does_not_bypass_limits(
        self,
    ) -> None:
        engine = PreferenceEpisodeEngine()
        observations = [
            _observation(0, minute=0, source_event_id="reused-event"),
            _observation(1, minute=1, condition="condition:other"),
            _observation(2, minute=30, source_event_id="reused-event"),
        ]

        episodes = engine.group(observations)

        spreadsheet = [
            item
            for item in episodes
            if item.condition_tag_id == "app:spreadsheet"
        ]
        self.assertEqual(2, len(spreadsheet))


class PreferenceEpisodePromotionTest(unittest.TestCase):
    def test_multiple_weak_observations_promote_together(self) -> None:
        engine = PreferenceEpisodeEngine()
        observations = [_observation(index) for index in range(3)]

        result = engine.process(observations)

        self.assertEqual(1, len(result.episodes))
        self.assertEqual(1, len(result.memories))
        memory = result.memories[0]
        self.assertEqual("coherent_aggregate", memory.promotion_reason)
        self.assertEqual(3, memory.support_count)
        self.assertGreaterEqual(
            memory.strength,
            engine.config.aggregate_strength_threshold,
        )
        self.assertLess(
            memory.strongest_observation_strength,
            engine.config.single_strength_threshold,
        )

    def test_one_strong_observation_promotes_by_itself(self) -> None:
        engine = PreferenceEpisodeEngine()

        result = engine.process(
            [
                _observation(
                    0,
                    attitude=0.95,
                    attitude_confidence=0.95,
                    extraction_confidence=0.95,
                )
            ]
        )

        self.assertEqual(1, len(result.memories))
        self.assertEqual(
            "strong_single",
            result.memories[0].promotion_reason,
        )

    def test_different_objects_do_not_pool_strength(self) -> None:
        engine = PreferenceEpisodeEngine()

        result = engine.process(
            [
                _observation(0, object_id="chart:bar"),
                _observation(1, object_id="chart:line"),
            ]
        )

        self.assertEqual(1, len(result.episodes))
        self.assertEqual(0, len(result.memories))

    def test_opposite_attitudes_are_kept_as_separate_candidates(self) -> None:
        engine = PreferenceEpisodeEngine()
        observations = [
            _observation(index, attitude=0.5)
            for index in range(3)
        ] + [
            _observation(
                index + 3,
                attitude=-0.5,
            )
            for index in range(3)
        ]

        result = engine.process(observations)

        self.assertEqual(
            {"support", "oppose"},
            {item.attitude_polarity for item in result.memories},
        )
        self.assertTrue(
            all(item.conflicting_strength > 0.0 for item in result.memories)
        )

    def test_duplicate_frames_from_one_source_do_not_inflate_support(self) -> None:
        engine = PreferenceEpisodeEngine()
        observations = [
            _observation(
                index,
                source_event_id="same-event",
                memory_id=f"frame-{index}",
            )
            for index in range(3)
        ]

        result = engine.process(observations)

        self.assertEqual(1, len(result.episodes))
        self.assertEqual(0, len(result.memories))

    def test_temporal_vote_initializes_memory_tier(self) -> None:
        engine = PreferenceEpisodeEngine()
        cases = (
            ("temporal_short", "short_term"),
            ("temporal_medium", "mid_term"),
            ("temporal_long", "long_term"),
        )
        for index, (temporal, expected) in enumerate(cases):
            with self.subTest(temporal=temporal):
                result = engine.process(
                    [
                        _observation(
                            index,
                            temporal=temporal,
                            attitude=0.95,
                            attitude_confidence=0.95,
                            extraction_confidence=0.95,
                        )
                    ]
                )
                self.assertEqual(expected, result.memories[0].memory_type)

    def test_episode_keeps_original_observations_without_text_merge(self) -> None:
        engine = PreferenceEpisodeEngine()

        result = engine.process([_observation(index) for index in range(3)])
        serialized = result.episodes[0].to_dict()

        self.assertEqual(
            ["source text 0", "source text 1", "source text 2"],
            [item["source_text"] for item in serialized["observations"]],
        )
        self.assertFalse(hasattr(result.memories[0], "source_text"))


if __name__ == "__main__":
    unittest.main()
