from __future__ import annotations

import unittest

from src.memory_engine.conflict import (
    ConflictIndex,
    ConflictMemory,
    ConflictResolver,
    HierarchicalRuleConflictDetector,
    HybridConflictDetector,
    WeightedEvidenceConflictDetector,
    apply_conflict_assessment,
    condition_relation,
)
from src.memory_engine.memory_graph import (
    MemoryGraphNode,
    MemoryKnowledgeGraphBuilder,
)
from src.memory_engine.memory_lifecycle import (
    ConfidenceEvidence,
    LifecycleObservation,
    MemoryLifeSeed,
    MemoryLifecycleEngine,
    SourceBetaMeanConfidence,
    WeibullSurvivalStability,
)


NOW = "2026-07-29T09:00:00+00:00"


def _memory(
    memory_id: str,
    value: str,
    *,
    source_kind: str = "text",
    observed_at: str = NOW,
    conditions: dict[str, str] | None = None,
    condition_tag_ids: tuple[str, ...] = (),
    valid_from: str = "",
    valid_to: str = "",
    supersedes: tuple[str, ...] = (),
) -> ConflictMemory:
    return ConflictMemory(
        memory_id=memory_id,
        user_id="user-1",
        slot_key="default_chart",
        value=value,
        confidence=0.86,
        source_kind=source_kind,
        observed_at=observed_at,
        conditions=conditions or {},
        condition_tag_ids=condition_tag_ids,
        valid_from=valid_from,
        valid_to=valid_to,
        supersedes_memory_ids=supersedes,
        evidence_strength=0.9,
    )


def _seed(memory_id: str, *, source_kind: str = "text") -> MemoryLifeSeed:
    return MemoryLifeSeed(
        memory_id=memory_id,
        user_id="user-1",
        created_at=NOW,
        source_kind=source_kind,
        temporal_label="temporal_medium",
        temporal_confidence=0.7,
        explicit_long_term=False,
        base_strength=0.86,
        condition_tag_ids=("condition:spreadsheet",),
        object_tag_ids=("object:chart",),
        attitude_polarity="support",
        evidence=(
            ConfidenceEvidence(
                evidence_id=f"{memory_id}:evidence",
                observed_at=NOW,
                source_kind=source_kind,
                quality=0.9,
                independent_unit_id=f"{memory_id}:unit",
            ),
        ),
    )


def _engine(*memory_ids: str) -> MemoryLifecycleEngine:
    engine = MemoryLifecycleEngine(
        WeibullSurvivalStability(),
        SourceBetaMeanConfidence(),
    )
    for memory_id in memory_ids:
        engine.add_memory(_seed(memory_id))
    return engine


def _node(memory_id: str) -> MemoryGraphNode:
    return MemoryGraphNode(
        memory_id=memory_id,
        episode_id=f"episode:{memory_id}",
        user_id="user-1",
        source_kind="observation",
        strength=0.86,
        condition_tag_ids=("condition:spreadsheet",),
        object_tag_ids=("object:chart",),
        attitude_polarity="support",
    )


class MemoryConflictTest(unittest.TestCase):
    def test_three_methods_cover_static_conflict(self) -> None:
        left = _memory("bar", "bar")
        right = _memory("line", "line")

        for detector_type in (
            HierarchicalRuleConflictDetector,
            WeightedEvidenceConflictDetector,
            HybridConflictDetector,
        ):
            with self.subTest(detector=detector_type.__name__):
                result = detector_type().assess(left, right)

                self.assertEqual("static", result.conflict_type)
                self.assertEqual("conflicts", result.links[0].relation_type)
                self.assertFalse(result.links[0].directed)
                self.assertLess(result.confidence_factors["bar"], 1.0)
                self.assertLess(result.confidence_factors["line"], 1.0)

    def test_disjoint_conditions_are_scoped_not_penalized(self) -> None:
        work = _memory(
            "work",
            "bar",
            conditions={"place": "work"},
        )
        home = _memory(
            "home",
            "line",
            conditions={"place": "home"},
        )
        result = HybridConflictDetector().assess(work, home)

        self.assertEqual("conditional", result.conflict_type)
        self.assertEqual(
            {"work": 1.0, "home": 1.0},
            result.confidence_factors,
        )
        self.assertEqual(
            "conditional_alternative",
            result.links[0].relation_type,
        )

    def test_explicit_change_penalizes_only_predecessor(self) -> None:
        old = _memory("old", "bar")
        new = _memory(
            "new",
            "line",
            observed_at="2026-07-30T09:00:00+00:00",
            supersedes=("old",),
        )
        result = HybridConflictDetector().assess(old, new)
        engine = _engine("old", "new")
        before = {
            key: float(state.confidence["value"])
            for key, state in engine.states.items()
        }

        apply_conflict_assessment(
            engine,
            result,
            observed_at="2026-07-30T09:00:00+00:00",
        )

        self.assertEqual("dynamic", result.conflict_type)
        self.assertEqual("old", result.predecessor_memory_id)
        self.assertEqual("new", result.successor_memory_id)
        self.assertLess(
            engine.states["old"].confidence["value"],
            before["old"],
        )
        self.assertEqual(
            engine.states["new"].confidence["value"],
            before["new"],
        )
        self.assertTrue(engine.states["old"].conflict_factors)
        self.assertFalse(engine.states["old"].relation_conflict)
        self.assertFalse(engine.states["new"].relation_conflict)

    def test_static_conflict_penalizes_both_lifecycle_states(self) -> None:
        result = HybridConflictDetector().assess(
            _memory("bar", "bar"),
            _memory("line", "line"),
        )
        engine = _engine("bar", "line")
        before = {
            key: float(state.confidence["value"])
            for key, state in engine.states.items()
        }

        apply_conflict_assessment(engine, result, observed_at=NOW)

        for memory_id in ("bar", "line"):
            self.assertLess(
                engine.states[memory_id].confidence["value"],
                before[memory_id],
            )
            self.assertTrue(engine.states[memory_id].conflict_factors)
            self.assertFalse(engine.states[memory_id].relation_conflict)

    def test_runtime_confidence_matches_assessment_factors(self) -> None:
        result = HybridConflictDetector().assess(
            _memory("bar", "bar"),
            _memory("line", "line"),
        )
        engine = _engine("bar", "line")
        before = {
            key: float(state.confidence["value"])
            for key, state in engine.states.items()
        }

        apply_conflict_assessment(engine, result, observed_at=NOW)

        for memory_id, factor in result.confidence_factors.items():
            actual_factor = (
                engine.states[memory_id].confidence["value"]
                / before[memory_id]
            )
            self.assertAlmostEqual(factor, actual_factor, places=7)
            self.assertFalse(
                engine.states[memory_id].relation_conflict,
            )

    def test_partial_scope_conflict_does_not_apply_global_penalty(
        self,
    ) -> None:
        broad = _memory(
            "broad",
            "bar",
            conditions={"app": "spreadsheet"},
        )
        narrow = _memory(
            "narrow",
            "line",
            conditions={"app": "spreadsheet", "task": "budget"},
        )

        result = HybridConflictDetector().assess(broad, narrow)

        self.assertEqual("static", result.conflict_type)
        self.assertEqual("overlap", result.condition_relation)
        self.assertEqual(
            {"broad": 1.0, "narrow": 1.0},
            result.confidence_factors,
        )
        self.assertEqual("intersection", result.conflict_scope["kind"])
        self.assertEqual(
            {"app": "spreadsheet", "task": "budget"},
            result.conflict_scope["conditions"],
        )

    def test_reclassified_pair_can_revoke_prior_conflict_penalty(
        self,
    ) -> None:
        detector = HybridConflictDetector()
        static = detector.assess(
            _memory("left", "bar"),
            _memory("right", "line"),
        )
        conditional = detector.assess(
            _memory(
                "left",
                "bar",
                conditions={"place": "work"},
            ),
            _memory(
                "right",
                "line",
                conditions={"place": "home"},
            ),
        )
        engine = _engine("left", "right")
        initial = {
            key: float(state.confidence["value"])
            for key, state in engine.states.items()
        }

        apply_conflict_assessment(engine, static, observed_at=NOW)
        apply_conflict_assessment(
            engine,
            conditional,
            observed_at="2026-07-30T09:00:00+00:00",
        )

        self.assertEqual(
            initial,
            {
                key: float(state.confidence["value"])
                for key, state in engine.states.items()
            },
        )

    def test_retrieval_expansion_returns_the_other_claim_from_either_side(
        self,
    ) -> None:
        result = HybridConflictDetector().assess(
            _memory("bar", "bar"),
            _memory("line", "line"),
        )
        index = ConflictIndex((result,))

        from_bar = index.expand(("bar",))[0].companions
        from_line = index.expand(("line",))[0].companions

        self.assertEqual(("line",), tuple(row.memory_id for row in from_bar))
        self.assertEqual(("bar",), tuple(row.memory_id for row in from_line))
        self.assertIn("incompatible values", from_bar[0].explanation)

    def test_conflict_signal_forms_a_symmetric_graph_edge(self) -> None:
        result = HybridConflictDetector().assess(
            _memory("bar", "bar"),
            _memory("line", "line"),
        )

        graph = MemoryKnowledgeGraphBuilder().build(
            (_node("bar"), _node("line")),
            result.graph_signals(),
        )
        matrix = graph.relation_matrix()

        self.assertEqual(1, len(graph.edges))
        self.assertEqual("conflicts", graph.edges[0].relation_type)
        self.assertFalse(graph.edges[0].directed)
        self.assertEqual(matrix["bar"]["line"], matrix["line"]["bar"])
        self.assertEqual(
            "global",
            result.graph_signals()[0].metadata[
                "conflict_scope"
            ]["kind"],
        )

    def test_swapping_inputs_preserves_type_and_dynamic_direction(self) -> None:
        old = _memory("old", "bar")
        new = _memory(
            "new",
            "line",
            observed_at="2026-07-30T09:00:00+00:00",
            supersedes=("old",),
        )
        detector = HybridConflictDetector()

        forward = detector.assess(old, new)
        reverse = detector.assess(new, old)

        self.assertEqual(forward.conflict_type, reverse.conflict_type)
        self.assertEqual(
            forward.predecessor_memory_id,
            reverse.predecessor_memory_id,
        )
        self.assertEqual(
            forward.successor_memory_id,
            reverse.successor_memory_id,
        )
        self.assertEqual(forward.links, reverse.links)

    def test_meaningful_symbols_are_not_erased_during_value_comparison(
        self,
    ) -> None:
        detector = HybridConflictDetector()

        for left_value, right_value in (
            ("-5", "5"),
            ("C++", "C"),
            ("v1.2", "v12"),
        ):
            with self.subTest(left=left_value, right=right_value):
                result = detector.assess(
                    _memory("left", left_value),
                    _memory("right", right_value),
                )
                self.assertEqual("static", result.conflict_type)

    def test_condition_tags_only_partition_on_the_same_axis(self) -> None:
        work = _memory(
            "work",
            "bar",
            condition_tag_ids=("condition:place:work",),
        )
        mobile = _memory(
            "mobile",
            "line",
            condition_tag_ids=("condition:device:mobile",),
        )
        home = _memory(
            "home",
            "line",
            condition_tag_ids=("condition:place:home",),
        )

        self.assertEqual("overlap", condition_relation(work, mobile))
        self.assertEqual("disjoint", condition_relation(work, home))

    def test_explicit_supersession_wins_over_changed_condition(self) -> None:
        old = _memory(
            "old",
            "bar",
            conditions={"place": "work"},
        )
        new = _memory(
            "new",
            "line",
            conditions={"place": "home"},
            supersedes=("old",),
        )

        result = HybridConflictDetector().assess(old, new)

        self.assertEqual("dynamic", result.conflict_type)
        self.assertEqual("old", result.predecessor_memory_id)

    def test_validity_orders_backfilled_history_not_observation_time(
        self,
    ) -> None:
        historical = _memory(
            "historical",
            "bar",
            observed_at="2027-01-01T00:00:00+00:00",
            valid_from="2025-01-01T00:00:00+00:00",
            valid_to="2026-01-01T00:00:00+00:00",
        )
        current = _memory(
            "current",
            "line",
            observed_at="2026-01-01T00:00:00+00:00",
            valid_from="2026-01-01T00:00:00+00:00",
            valid_to="2027-01-01T00:00:00+00:00",
        )

        result = HybridConflictDetector().assess(historical, current)

        self.assertEqual("dynamic", result.conflict_type)
        self.assertEqual("historical", result.predecessor_memory_id)
        self.assertEqual("current", result.successor_memory_id)

    def test_one_missing_validity_scope_remains_unresolved(self) -> None:
        unscoped = _memory("unscoped", "bar")
        scoped = _memory(
            "scoped",
            "line",
            valid_from="2026-01-01T00:00:00+00:00",
            valid_to="2027-01-01T00:00:00+00:00",
        )

        result = HybridConflictDetector().assess(unscoped, scoped)

        self.assertEqual("unresolved", result.conflict_type)
        self.assertEqual("unknown", result.time_relation)

    def test_invalid_validity_and_self_supersession_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            _memory(
                "invalid",
                "bar",
                valid_from="2027-01-01T00:00:00+00:00",
                valid_to="2026-01-01T00:00:00+00:00",
            )
        with self.assertRaises(ValueError):
            _memory("self", "bar", supersedes=("self",))

    def test_mutual_supersession_is_unresolved(self) -> None:
        left = _memory("left", "bar", supersedes=("right",))
        right = _memory("right", "line", supersedes=("left",))

        result = HybridConflictDetector().assess(left, right)

        self.assertEqual("unresolved", result.conflict_type)
        self.assertIn(
            "mutual_supersession",
            {reason.code for reason in result.reasons},
        )

    def test_repeated_scan_is_idempotent_for_lifecycle_and_index(
        self,
    ) -> None:
        result = HybridConflictDetector().assess(
            _memory("bar", "bar"),
            _memory("line", "line"),
        )
        engine = _engine("bar", "line")
        index = ConflictIndex()

        apply_conflict_assessment(engine, result, observed_at=NOW)
        first = {
            key: float(state.confidence["value"])
            for key, state in engine.states.items()
        }
        apply_conflict_assessment(
            engine,
            result,
            observed_at="2026-07-30T09:00:00+00:00",
        )
        index.add(result)
        index.add(result)

        self.assertEqual(
            first,
            {
                key: float(state.confidence["value"])
                for key, state in engine.states.items()
            },
        )
        self.assertEqual(
            1,
            len(index.expand(("bar",))[0].companions),
        )

    def test_resolver_only_compares_same_user_and_slot_candidates(
        self,
    ) -> None:
        resolver = ConflictResolver()
        resolver.add(_memory("chart-old", "bar"))
        resolver.add(
            ConflictMemory(
                memory_id="format",
                user_id="user-1",
                slot_key="report_format",
                value="PDF",
                confidence=0.86,
                source_kind="text",
                observed_at=NOW,
            )
        )
        resolver.add(
            ConflictMemory(
                memory_id="other-user",
                user_id="user-2",
                slot_key="default_chart",
                value="pie",
                confidence=0.86,
                source_kind="text",
                observed_at=NOW,
            )
        )

        resolution = resolver.add(_memory("chart-new", "line"))

        self.assertEqual(1, resolution.candidate_count)
        self.assertEqual(1, len(resolution.conflicts))
        self.assertEqual(
            "static",
            resolution.conflicts[0].conflict_type,
        )
        companions = resolver.index.expand(("chart-new",))
        self.assertEqual(
            "chart-old",
            companions[0].companions[0].memory_id,
        )

    def test_resolver_honors_explicit_supersession_across_slot_rename(
        self,
    ) -> None:
        resolver = ConflictResolver()
        resolver.add(
            ConflictMemory(
                memory_id="old",
                user_id="user-1",
                slot_key="legacy_assistant",
                value="ChatGPT",
                confidence=0.86,
                source_kind="text",
                observed_at=NOW,
            )
        )

        resolution = resolver.add(
            ConflictMemory(
                memory_id="new",
                user_id="user-1",
                slot_key="preferred_assistant",
                value="Codex",
                confidence=0.86,
                source_kind="text",
                observed_at=NOW,
                supersedes_memory_ids=("old",),
            )
        )

        self.assertEqual(1, resolution.candidate_count)
        self.assertEqual("dynamic", resolution.conflicts[0].conflict_type)
        self.assertEqual(
            "old",
            resolution.conflicts[0].predecessor_memory_id,
        )

    def test_resolver_rechecks_late_supersession_target(self) -> None:
        resolver = ConflictResolver()
        first = resolver.add(
            ConflictMemory(
                memory_id="new",
                user_id="user-1",
                slot_key="preferred_assistant",
                value="Codex",
                confidence=0.86,
                source_kind="text",
                observed_at=NOW,
                supersedes_memory_ids=("old",),
            )
        )

        resolution = resolver.add(
            ConflictMemory(
                memory_id="old",
                user_id="user-1",
                slot_key="legacy_assistant",
                value="ChatGPT",
                confidence=0.86,
                source_kind="text",
                observed_at="2025-07-29T09:00:00+00:00",
            )
        )

        self.assertEqual(0, first.candidate_count)
        self.assertEqual(1, resolution.candidate_count)
        self.assertEqual("dynamic", resolution.conflicts[0].conflict_type)
        self.assertEqual(
            "old",
            resolution.conflicts[0].predecessor_memory_id,
        )

    def test_resolver_snapshot_rebuilds_pending_supersession(self) -> None:
        resolver = ConflictResolver(HybridConflictDetector())
        resolver.add(
            ConflictMemory(
                memory_id="new",
                user_id="user-1",
                slot_key="preferred_assistant",
                value="Codex",
                confidence=0.86,
                source_kind="text",
                observed_at=NOW,
                supersedes_memory_ids=("old",),
            )
        )

        restored = ConflictResolver.from_snapshot(resolver.snapshot())
        resolution = restored.add(
            ConflictMemory(
                memory_id="old",
                user_id="user-1",
                slot_key="legacy_assistant",
                value="ChatGPT",
                confidence=0.86,
                source_kind="text",
                observed_at="2025-07-29T09:00:00+00:00",
            )
        )

        self.assertIsInstance(restored.detector, HybridConflictDetector)
        self.assertEqual(
            {"old": ("new",)},
            resolver.pending_supersessions(),
        )
        self.assertEqual("dynamic", resolution.conflicts[0].conflict_type)
        self.assertFalse(restored.pending_supersessions())

    def test_stale_pending_supersession_can_be_pruned(self) -> None:
        resolver = ConflictResolver()
        resolver.add(
            ConflictMemory(
                memory_id="new",
                user_id="user-1",
                slot_key="preferred_assistant",
                value="Codex",
                confidence=0.86,
                source_kind="text",
                observed_at="2025-07-29T09:00:00+00:00",
                supersedes_memory_ids=("old",),
            )
        )

        expired = resolver.prune_pending_supersessions(
            before="2026-01-01T00:00:00+00:00",
        )
        restored = ConflictResolver.from_snapshot(resolver.snapshot())
        resolution = resolver.add(
            ConflictMemory(
                memory_id="old",
                user_id="user-1",
                slot_key="legacy_assistant",
                value="ChatGPT",
                confidence=0.86,
                source_kind="text",
                observed_at="2024-07-29T09:00:00+00:00",
            )
        )

        self.assertEqual((("old", "new"),), expired)
        self.assertFalse(resolver.pending_supersessions())
        self.assertFalse(restored.pending_supersessions())
        self.assertEqual(0, resolution.candidate_count)

    def test_multiple_conflict_factors_accumulate_with_a_floor(self) -> None:
        engine = _engine("memory")
        baseline = float(engine.states["memory"].confidence["value"])

        engine.apply_conflict_factor(
            "memory",
            factor_id="primary",
            factor=0.70,
            at=NOW,
            rationale="primary conflict",
        )
        primary = engine.states["memory"].confidence[
            "conflict_penalty"
        ]
        engine.apply_conflict_factor(
            "memory",
            factor_id="secondary",
            factor=0.60,
            at=NOW,
            rationale="independent conflict",
        )
        combined = engine.states["memory"].confidence[
            "conflict_penalty"
        ]

        self.assertAlmostEqual(0.70, float(primary), places=7)
        self.assertLess(float(combined), 0.60)
        self.assertGreaterEqual(float(combined), 0.25)
        self.assertLess(
            float(engine.states["memory"].confidence["value"]),
            baseline * 0.60,
        )

        engine.apply_conflict_factor(
            "memory",
            factor_id="secondary",
            factor=1.0,
            at="2026-07-30T09:00:00+00:00",
            rationale="secondary conflict revoked",
        )
        self.assertAlmostEqual(
            0.70,
            float(
                engine.states["memory"].confidence[
                    "conflict_penalty"
                ]
            ),
            places=7,
        )

    def test_lifecycle_query_returns_conflict_companion_without_activation(
        self,
    ) -> None:
        resolver = ConflictResolver()
        resolver.add(_memory("bar", "bar"))
        resolver.add(_memory("line", "line"))
        engine = _engine("bar", "line")
        observation = LifecycleObservation(
            observation_id="query",
            user_id="user-1",
            observed_at=NOW,
            source_kind="query",
            condition_tag_ids=("condition:spreadsheet",),
            object_tag_ids=("object:chart",),
            attitude_polarity="support",
        )

        result = resolver.query_with_conflicts(
            engine,
            observation,
            top_k=1,
        )

        selected_id = result.query_result.selected[0].memory_id
        companion = result.conflict_groups[0].companions[0]
        self.assertNotEqual(selected_id, companion.memory_id)
        self.assertEqual(
            1,
            engine.states[selected_id].activation_count,
        )
        self.assertEqual(
            0,
            engine.states[companion.memory_id].activation_count,
        )
        self.assertTrue(companion.explanation)


if __name__ == "__main__":
    unittest.main()
