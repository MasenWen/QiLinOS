from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from src.memory_engine.memory_lifecycle import (
    CONFIDENCE_STRATEGIES,
    STABILITY_STRATEGIES,
    ConfidenceEvidence,
    LifecycleObservation,
    MemoryLifeRelation,
    MemoryLifeSeed,
    MemoryLifecycleEngine,
    SourceBetaMeanConfidence,
    WeibullSurvivalStability,
    temporal_retention_days,
)


BASE = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _at(day: float) -> str:
    return (BASE + timedelta(days=day)).isoformat()


def _seed(
    memory_id: str,
    *,
    source_kind: str = "text",
    temporal_label: str = "temporal_short",
    temporal_confidence: float = 0.2,
    explicit_long_term: bool = False,
    support_count: int = 1,
    polarity: str = "support",
    condition: str = "condition:file:sheet",
    object_id: str = "object:action:chart",
    created_day: float = 0.0,
    conflict: float = 0.0,
) -> MemoryLifeSeed:
    evidence = tuple(
        ConfidenceEvidence(
            evidence_id=f"{memory_id}:evidence:{index}",
            observed_at=_at(created_day - support_count + index + 1),
            source_kind=source_kind,
            quality=0.9,
            independent_unit_id=f"{memory_id}:unit:{index}",
        )
        for index in range(support_count)
    )
    return MemoryLifeSeed(
        memory_id=memory_id,
        user_id="user-1",
        created_at=_at(created_day),
        source_kind=source_kind,
        temporal_label=temporal_label,
        temporal_confidence=temporal_confidence,
        explicit_long_term=explicit_long_term,
        base_strength=0.9,
        condition_tag_ids=(condition,),
        object_tag_ids=(object_id,),
        attitude_polarity=polarity,
        evidence=evidence,
        conflicting_strength=conflict,
    )


def _query(
    observation_id: str,
    day: float,
    *,
    condition: str = "condition:file:sheet",
    object_id: str = "object:action:chart",
    polarity: str = "support",
) -> LifecycleObservation:
    return LifecycleObservation(
        observation_id=observation_id,
        user_id="user-1",
        observed_at=_at(day),
        source_kind="query",
        condition_tag_ids=(condition,),
        object_tag_ids=(object_id,),
        attitude_polarity=polarity,
    )


class MemoryLifecycleTest(unittest.TestCase):
    def test_temporal_label_is_a_weighted_prior_not_hard_expiry(
        self,
    ) -> None:
        weak_short = _seed(
            "weak-short",
            temporal_label="temporal_short",
            temporal_confidence=0.2,
        )
        strong_short = _seed(
            "strong-short",
            temporal_label="temporal_short",
            temporal_confidence=1.0,
        )
        explicit_long = _seed(
            "explicit-long",
            temporal_label="temporal_long",
            temporal_confidence=0.6,
            explicit_long_term=True,
        )

        self.assertGreater(
            temporal_retention_days(weak_short),
            temporal_retention_days(strong_short),
        )
        self.assertGreater(
            temporal_retention_days(explicit_long),
            temporal_retention_days(weak_short) * 4.0,
        )

    def test_all_stability_strategies_decay_and_activate(self) -> None:
        for name, strategy_type in STABILITY_STRATEGIES.items():
            with self.subTest(strategy=name):
                strategy = strategy_type()
                state = strategy.initialize(_seed(f"memory-{name}"))
                initial = strategy.value(state, _at(0))
                decayed = strategy.value(state, _at(90))
                before, after = strategy.activate(state, _at(90), 1.0)

                self.assertLess(decayed, initial)
                self.assertAlmostEqual(decayed, before)
                self.assertGreater(after, before)

    def test_stale_short_is_forgotten_but_long_survives(self) -> None:
        for stability_name, stability_type in (
            STABILITY_STRATEGIES.items()
        ):
            with self.subTest(stability=stability_name):
                engine = MemoryLifecycleEngine(
                    stability_type(),
                    SourceBetaMeanConfidence(),
                )
                engine.add_memory(_seed("short"))
                engine.add_memory(
                    _seed(
                        "long",
                        temporal_label="temporal_long",
                        temporal_confidence=0.8,
                        explicit_long_term=True,
                    )
                )

                forgotten = engine.maintain(_at(365))

                self.assertIn("short", forgotten)
                self.assertEqual(
                    "forgotten",
                    engine.states["short"].status,
                )
                self.assertEqual(
                    "active",
                    engine.states["long"].status,
                )

    def test_selected_query_activates_only_matching_memory(self) -> None:
        engine = MemoryLifecycleEngine(
            WeibullSurvivalStability(),
            SourceBetaMeanConfidence(),
        )
        engine.add_memory(_seed("matching"))
        engine.add_memory(
            _seed(
                "different",
                condition="condition:file:other",
                object_id="object:action:other",
            )
        )

        result = engine.query(_query("query-1", 20), top_k=1)

        self.assertEqual(
            ("matching",),
            tuple(item.memory_id for item in result.selected),
        )
        self.assertEqual(1, engine.states["matching"].activation_count)
        self.assertEqual(0, engine.states["different"].activation_count)

    def test_query_does_not_activate_opposite_attitude(self) -> None:
        engine = MemoryLifecycleEngine(
            WeibullSurvivalStability(),
            SourceBetaMeanConfidence(),
        )
        engine.add_memory(_seed("support"))
        engine.add_memory(_seed("oppose", polarity="oppose"))

        result = engine.query(_query("query-attitude", 5), top_k=2)

        self.assertEqual(
            ("support",),
            tuple(item.memory_id for item in result.selected),
        )
        self.assertEqual(0, engine.states["oppose"].activation_count)

    def test_weak_secondary_candidate_does_not_fill_top_k(self) -> None:
        engine = MemoryLifecycleEngine(
            WeibullSurvivalStability(),
            SourceBetaMeanConfidence(),
            secondary_selection_ratio=0.8,
        )
        engine.add_memory(_seed("exact"))
        broad = replace(
            _seed("broad"),
            condition_tag_ids=(),
        )
        engine.add_memory(broad)

        result = engine.query(_query("quality-gate", 5), top_k=2)

        self.assertEqual(
            ("exact",),
            tuple(item.memory_id for item in result.selected),
        )
        self.assertEqual(0, engine.states["broad"].activation_count)

    def test_exact_query_can_rescue_borderline_memory(self) -> None:
        engine = MemoryLifecycleEngine(
            WeibullSurvivalStability(),
            SourceBetaMeanConfidence(),
        )
        engine.add_memory(_seed("borderline"))
        rescue_day = next(
            day
            for day in range(60, 220)
            if (
                engine.rescue_floor
                <= engine.stability_strategy.value(
                    engine.states["borderline"].stability,
                    _at(day),
                )
                < engine.forget_threshold
            )
        )

        result = engine.query(
            _query("query-rescue", rescue_day),
            top_k=1,
        )

        self.assertEqual(1, len(result.selected))
        self.assertTrue(result.selected[0].rescued)
        self.assertGreater(
            result.selected[0].stability_after,
            result.selected[0].stability_before,
        )
        self.assertEqual(
            "active",
            engine.states["borderline"].status,
        )

    def test_positive_relation_lifts_both_memories(self) -> None:
        engine = MemoryLifecycleEngine(
            WeibullSurvivalStability(),
            SourceBetaMeanConfidence(),
        )
        engine.add_memory(_seed("old", created_day=0))
        engine.add_memory(_seed("new", created_day=20))
        old_stability = engine.stability_strategy.value(
            engine.states["old"].stability,
            _at(20),
        )
        new_stability = engine.stability_strategy.value(
            engine.states["new"].stability,
            _at(20),
        )
        old_confidence = float(engine.states["old"].confidence["value"])
        new_confidence = float(engine.states["new"].confidence["value"])

        engine.add_relation(
            MemoryLifeRelation(
                relation_id="supports-old-new",
                source_memory_id="old",
                target_memory_id="new",
                relation_type="supports",
                weight=0.9,
                observed_at=_at(20),
            )
        )

        self.assertGreater(
            float(engine.states["old"].stability["value"]),
            old_stability,
        )
        self.assertGreater(
            float(engine.states["new"].stability["value"]),
            new_stability,
        )
        self.assertGreater(
            float(engine.states["old"].confidence["value"]),
            old_confidence,
        )
        self.assertGreater(
            float(engine.states["new"].confidence["value"]),
            new_confidence,
        )

    def test_non_supporting_relation_does_not_lift_life_variables(
        self,
    ) -> None:
        engine = MemoryLifecycleEngine(
            WeibullSurvivalStability(),
            SourceBetaMeanConfidence(),
        )
        engine.add_memory(_seed("old"))
        engine.add_memory(_seed("new"))
        before = (
            float(engine.states["old"].stability["value"]),
            float(engine.states["old"].confidence["value"]),
        )

        engine.add_relation(
            MemoryLifeRelation(
                relation_id="related-old-new",
                source_memory_id="old",
                target_memory_id="new",
                relation_type="related",
                weight=0.95,
                observed_at=_at(0),
            )
        )

        after = (
            float(engine.states["old"].stability["value"]),
            float(engine.states["old"].confidence["value"]),
        )
        self.assertEqual(before, after)

    def test_conflict_reduces_confidence(self) -> None:
        engine = MemoryLifecycleEngine(
            WeibullSurvivalStability(),
            SourceBetaMeanConfidence(),
        )
        engine.add_memory(_seed("left"))
        engine.add_memory(_seed("right", polarity="oppose"))
        before = float(engine.states["left"].confidence["value"])

        engine.add_relation(
            MemoryLifeRelation(
                relation_id="conflict",
                source_memory_id="left",
                target_memory_id="right",
                relation_type="conflicts",
                weight=0.9,
                observed_at=_at(0),
            )
        )

        self.assertLess(
            float(engine.states["left"].confidence["value"]),
            before,
        )

    def test_text_source_confidence_is_higher_than_log_source(
        self,
    ) -> None:
        for name, confidence_type in CONFIDENCE_STRATEGIES.items():
            with self.subTest(confidence=name):
                engine = MemoryLifecycleEngine(
                    WeibullSurvivalStability(),
                    confidence_type(),
                )
                engine.add_memory(_seed("text", source_kind="text"))
                engine.add_memory(_seed("log", source_kind="log"))
                text = float(engine.states["text"].confidence["value"])
                log = float(engine.states["log"].confidence["value"])

                self.assertGreater(text - log, 0.20)

    def test_confidence_changes_final_selection(self) -> None:
        engine = MemoryLifecycleEngine(
            WeibullSurvivalStability(),
            SourceBetaMeanConfidence(),
        )
        engine.add_memory(_seed("text", source_kind="text"))
        engine.add_memory(_seed("log", source_kind="log"))

        result = engine.query(_query("source-choice", 5), top_k=1)

        self.assertEqual("text", result.selected[0].memory_id)
        self.assertEqual(1, engine.states["text"].activation_count)
        self.assertEqual(0, engine.states["log"].activation_count)

    def test_all_nine_combinations_complete_basic_flow(self) -> None:
        for stability_name, stability_type in (
            STABILITY_STRATEGIES.items()
        ):
            for confidence_name, confidence_type in (
                CONFIDENCE_STRATEGIES.items()
            ):
                with self.subTest(
                    stability=stability_name,
                    confidence=confidence_name,
                ):
                    engine = MemoryLifecycleEngine(
                        stability_type(),
                        confidence_type(),
                    )
                    engine.add_memory(_seed("memory"))
                    result = engine.query(
                        _query("query", 10),
                        top_k=1,
                    )
                    snapshot = engine.snapshot(_at(20))

                    self.assertEqual(1, len(result.selected))
                    self.assertEqual(1, len(snapshot))
                    self.assertGreater(
                        float(snapshot[0]["stability"]["value"]),
                        0.0,
                    )
                    self.assertGreater(
                        float(snapshot[0]["confidence"]["value"]),
                        0.0,
                    )


if __name__ == "__main__":
    unittest.main()
