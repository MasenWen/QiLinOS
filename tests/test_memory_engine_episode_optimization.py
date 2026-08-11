from __future__ import annotations

import unittest

from src.memory_engine.episode_optimization import (
    EpisodeBoundaryRepairConfig,
    EpisodeOptimizationEvent,
    GlobalEpisodeDecoderConfig,
    decode_episode_boundaries,
    repair_episode_boundaries,
)


def _event(
    event_id: str,
    condition: str | None = None,
    *,
    scores: dict[str, float] | None = None,
    objects: tuple[str, ...] = (),
) -> EpisodeOptimizationEvent:
    return EpisodeOptimizationEvent(
        event_id=event_id,
        condition_tag_id=condition,
        condition_scores=scores or {},
        object_tag_ids=objects,
    )


class BidirectionalEpisodeBoundaryRepairTest(unittest.TestCase):
    def test_moves_delayed_boundary_when_unknown_event_supports_right(self) -> None:
        events = (
            _event("a1", "condition:a"),
            _event(
                "b1",
                scores={"condition:a": 0.51, "condition:b": 0.83},
            ),
            _event("b2", "condition:b"),
        )

        result = repair_episode_boundaries(events, (2,))

        self.assertEqual(result.boundaries, (1,))
        self.assertTrue(result.decisions[0].changed)
        self.assertEqual(
            result.decisions[0].reason,
            "decisive_bidirectional_evidence",
        )

    def test_keeps_baseline_when_unknown_event_has_no_scores(self) -> None:
        events = (
            _event("a1", "condition:a"),
            _event("unknown"),
            _event("b1", "condition:b"),
        )

        result = repair_episode_boundaries(events, (2,))

        self.assertEqual(result.boundaries, (2,))
        self.assertFalse(result.decisions[0].changed)
        self.assertEqual(
            result.decisions[0].reason,
            "abstain_no_discriminative_evidence",
        )

    def test_keeps_baseline_when_scores_are_ambiguous(self) -> None:
        events = (
            _event("a1", "condition:a"),
            _event(
                "unknown",
                scores={"condition:a": 0.78, "condition:b": 0.79},
            ),
            _event("b1", "condition:b"),
        )

        result = repair_episode_boundaries(events, (2,))

        self.assertEqual(result.boundaries, (2,))
        self.assertFalse(result.decisions[0].changed)

    def test_relation_object_does_not_move_boundary(self) -> None:
        relation = "object:preference_versioning"
        events = (
            _event("a1", "condition:a", objects=(relation,)),
            _event("unknown", objects=(relation,)),
            _event("b1", "condition:b", objects=(relation,)),
        )

        result = repair_episode_boundaries(events, (2,))

        self.assertEqual(result.boundaries, (2,))
        self.assertFalse(result.decisions[0].changed)

    def test_substantive_object_can_support_right_anchor(self) -> None:
        events = (
            _event("a1", "condition:a", objects=("object:a",)),
            _event("b1", objects=("object:b",)),
            _event("b2", "condition:b", objects=("object:b",)),
        )
        config = EpisodeBoundaryRepairConfig(
            condition_weight=0.0,
            object_weight=0.2,
            min_total_gain=0.08,
        )

        result = repair_episode_boundaries(
            events,
            (2,),
            config=config,
        )

        self.assertEqual(result.boundaries, (1,))
        self.assertTrue(result.decisions[0].changed)

    def test_collapses_spurious_singleton_between_primary_anchors(
        self,
    ) -> None:
        events = (
            _event("a1", "condition:a"),
            _event(
                "b1",
                scores={"condition:a": 0.53, "condition:b": 0.84},
            ),
            _event("b2", "condition:b"),
        )

        result = repair_episode_boundaries(events, (1, 2))

        self.assertEqual(result.boundaries, (1,))
        self.assertTrue(result.decisions[0].changed)
        self.assertEqual(
            result.decisions[0].reason,
            "decisive_bidirectional_evidence_collapse",
        )


class GlobalEpisodeDecoderTest(unittest.TestCase):
    def test_moves_boundary_using_unknown_event_condition_scores(self) -> None:
        events = (
            _event("a1", "condition:a"),
            _event(
                "b1",
                scores={"condition:a": 0.45, "condition:b": 0.86},
            ),
            _event("b2", "condition:b"),
        )
        config = GlobalEpisodeDecoderConfig(
            boundary_cost=0.12,
            baseline_boundary_reward=0.04,
        )

        result = decode_episode_boundaries(
            events,
            (2,),
            config=config,
        )

        self.assertEqual(result.boundaries, (1,))

    def test_preserves_baseline_without_new_evidence(self) -> None:
        events = (
            _event("a1", "condition:a"),
            _event("unknown"),
            _event("b1", "condition:b"),
        )
        config = GlobalEpisodeDecoderConfig(
            boundary_cost=0.12,
            baseline_boundary_reward=0.12,
        )

        result = decode_episode_boundaries(
            events,
            (2,),
            config=config,
        )

        self.assertEqual(result.boundaries, (2,))

    def test_relation_object_does_not_create_extra_segment(self) -> None:
        relation = "object:preference_versioning"
        events = (
            _event("a1", "condition:a", objects=(relation,)),
            _event("a2", objects=(relation,)),
        )

        result = decode_episode_boundaries(events, ())

        self.assertEqual(result.boundaries, ())

    def test_object_evidence_alone_cannot_rewrite_baseline(self) -> None:
        events = (
            _event("a1", "condition:a", objects=("object:a",)),
            _event("a2", objects=("object:a",)),
            _event("b1", objects=("object:b",)),
            _event("b2", "condition:b", objects=("object:b",)),
        )

        result = decode_episode_boundaries(events, (3,))

        self.assertEqual(result.boundaries, (3,))

    def test_different_explicit_conditions_are_split(self) -> None:
        events = (
            _event("a1", "condition:a"),
            _event("b1", "condition:b"),
        )

        result = decode_episode_boundaries(events, ())

        self.assertEqual(result.boundaries, (1,))


if __name__ == "__main__":
    unittest.main()
