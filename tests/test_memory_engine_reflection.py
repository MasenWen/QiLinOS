from __future__ import annotations

import re
import unittest
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from src.memory_engine.memory_lifecycle import (
    ConfidenceEvidence,
    LifecycleObservation,
    MemoryLifeRelation,
    MemoryLifeSeed,
    MemoryLifecycleEngine,
    SourceBetaMeanConfidence,
    WeibullSurvivalStability,
)
from src.memory_engine.reflection import (
    LifecycleReflection,
    ReflectionMemoryPacket,
    ReflectionScheduleInput,
    ReflectionSource,
    build_reflection_packets,
    calculate_reflection_schedule,
)


BASE = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _at(day: float) -> str:
    return (BASE + timedelta(days=day)).isoformat()


def _seed(
    memory_id: str,
    *,
    condition: str = "condition:file:sheet",
    object_id: str = "object:action:chart",
    evidence_id: str | None = None,
) -> MemoryLifeSeed:
    return MemoryLifeSeed(
        memory_id=memory_id,
        user_id="user-1",
        created_at=_at(0),
        source_kind="text",
        temporal_label="temporal_short",
        temporal_confidence=0.2,
        explicit_long_term=False,
        base_strength=0.9,
        condition_tag_ids=(condition,),
        object_tag_ids=(object_id,),
        attitude_polarity="support",
        evidence=(
            ConfidenceEvidence(
                evidence_id=evidence_id or f"evidence-{memory_id}",
                observed_at=_at(0),
                source_kind="text",
                quality=0.9,
                independent_unit_id=f"unit-{memory_id}",
            ),
        ),
        metadata={
            "dataset_source": (
                "os_agent_memory_query_benchmark_v3.1"
            ),
            "source_event_ids": (f"source-{memory_id}",),
        },
    )


def _packet(
    memory_id: str,
    *,
    source_evidence_count: int = 1,
) -> ReflectionMemoryPacket:
    return ReflectionMemoryPacket(
        memory_id=memory_id,
        version_id=f"version-{memory_id}",
        user_id="user-1",
        condition_tag_ids=("condition:file:sheet",),
        object_tag_ids=("object:action:chart",),
        attitude_polarity="support",
        temporal_label="temporal_short",
        created_at=_at(0),
        reviewed_at=_at(10),
        activation_count=0,
        last_activated_at="",
        first_activated_at="",
        activation_span_days=0.0,
        latest_evidence_at=_at(0),
        inactivity_days=10.0,
        obsolete_after_days=60.0,
        independent_evidence_count=1,
        confidence=0.8,
        stability=0.7,
        source_refs=(
            ReflectionSource(
                source_id=f"source-{memory_id}",
                source_kind="query",
                text=f"Use the chart for {memory_id}.",
            ),
        ),
        source_evidence_count=source_evidence_count,
    )


class ConsensusFakeClient:
    def __init__(self, *, invalid_citations: bool = False):
        self.calls = []
        self.invalid_citations = invalid_citations

    def complete_json(
        self,
        *,
        system_markdown: str,
        user_markdown: str,
        task_name: str,
    ):
        self.calls.append({"task_name": task_name})
        memory_ids = re.findall(
            r"^## MEMORY ([^\s]+)",
            user_markdown,
            flags=re.MULTILINE,
        )
        if task_name.startswith("correction:"):
            return {
                "reviews": [
                    {
                        "memory_id": memory_id,
                        "verdict": "supported",
                        "source_refs": [
                            (
                                "not-a-source"
                                if self.invalid_citations
                                else f"source-{memory_id}"
                            )
                        ],
                        "rationale": "The source supports this memory.",
                    }
                    for memory_id in dict.fromkeys(memory_ids)
                ]
            }
        group_ids = re.findall(
            r"^# CANDIDATE_GROUP ([^\s]+)",
            user_markdown,
            flags=re.MULTILINE,
        )
        return {
            "groups": [
                {
                    "group_id": group_id,
                    "decision": "merge",
                    "canonical_memory_id": memory_ids[0],
                    "duplicate_memory_ids": memory_ids[1:],
                    "source_refs": [
                        f"source-{memory_id}"
                        for memory_id in memory_ids
                    ],
                    "rationale": "The sources express the same scoped intent.",
                }
                for group_id in group_ids
            ]
        }


class MemoryReflectionTest(unittest.TestCase):
    def _engine(self) -> MemoryLifecycleEngine:
        return MemoryLifecycleEngine(
            WeibullSurvivalStability(),
            SourceBetaMeanConfidence(),
        )

    def test_reflection_penalty_survives_confidence_rescore(self) -> None:
        engine = self._engine()
        engine.add_memory(_seed("memory-a"))
        engine.add_memory(
            _seed(
                "memory-b",
                condition="condition:file:other",
                object_id="object:action:other",
            )
        )

        changed = engine.apply_reflection_penalty(
            "memory-a",
            penalty_factor=0.55,
            at=_at(1),
            review_id="review-a",
            verdict="scope_error",
            rationale="The source scope was lost.",
            source_refs=("source-memory-a",),
        )
        engine.add_relation(
            MemoryLifeRelation(
                relation_id="support-a-b",
                source_memory_id="memory-a",
                target_memory_id="memory-b",
                relation_type="supports",
                weight=0.9,
                observed_at=_at(2),
            )
        )

        confidence = engine.states["memory-a"].confidence
        self.assertTrue(changed)
        self.assertEqual(0.55, confidence["reflection_penalty"])
        self.assertAlmostEqual(
            confidence["value"],
            confidence["evidence_value"] * 0.55,
            places=7,
        )
        self.assertFalse(
            engine.apply_reflection_penalty(
                "memory-a",
                penalty_factor=0.35,
                at=_at(3),
                review_id="review-a",
                verdict="contradicted",
                rationale="Repeated review.",
            )
        )

    def test_later_supported_consensus_recovers_old_penalty(self) -> None:
        engine = self._engine()
        engine.add_memory(_seed("memory-a"))
        engine.apply_reflection_penalty(
            "memory-a",
            penalty_factor=0.6,
            at=_at(90),
            review_id="review-negative",
            verdict="obsolete_task_state",
            rationale="No reuse was visible yet.",
        )

        changed = engine.apply_reflection_penalty(
            "memory-a",
            penalty_factor=1.0,
            at=_at(120),
            review_id="review-supported",
            verdict="supported",
            rationale="Later activations show valid reuse.",
        )

        self.assertTrue(changed)
        self.assertEqual(
            1.0,
            engine.states["memory-a"].reflection_penalty,
        )
        self.assertEqual(
            engine.states["memory-a"].confidence["evidence_value"],
            engine.states["memory-a"].confidence["value"],
        )

    def test_recent_task_cannot_be_marked_obsolete(self) -> None:
        engine = self._engine()
        engine.add_memory(_seed("memory-a"))

        changed = engine.apply_reflection_penalty(
            "memory-a",
            penalty_factor=0.6,
            at=_at(30),
            review_id="review-too-early",
            verdict="obsolete_task_state",
            rationale="The task appears one-off.",
        )

        self.assertFalse(changed)
        self.assertEqual(
            1.0,
            engine.states["memory-a"].reflection_penalty,
        )
        review_event = engine.states["memory-a"].events[-1]
        self.assertTrue(review_event["guarded_obsolete"])

    def test_unverifiable_review_does_not_clear_old_penalty(self) -> None:
        engine = self._engine()
        engine.add_memory(_seed("memory-a"))
        engine.apply_reflection_penalty(
            "memory-a",
            penalty_factor=0.35,
            at=_at(1),
            review_id="review-negative",
            verdict="contradicted",
            rationale="The source contradicts the memory.",
        )

        changed = engine.apply_reflection_penalty(
            "memory-a",
            penalty_factor=1.0,
            at=_at(2),
            review_id="review-missing",
            verdict="unverifiable",
            rationale="The later source is unavailable.",
        )

        self.assertFalse(changed)
        self.assertEqual(
            0.35,
            engine.states["memory-a"].reflection_penalty,
        )

    def test_merge_preserves_lineage_and_rewires_relations(self) -> None:
        engine = self._engine()
        engine.add_memory(_seed("duplicate", evidence_id="evidence-b"))
        engine.query(
            LifecycleObservation(
                observation_id="query-before-merge",
                user_id="user-1",
                observed_at=_at(1),
                source_kind="query",
                condition_tag_ids=("condition:file:sheet",),
                object_tag_ids=("object:action:chart",),
                attitude_polarity="support",
            ),
            top_k=1,
        )
        engine.add_memory(_seed("canonical", evidence_id="evidence-a"))
        engine.add_memory(
            _seed(
                "neighbor",
                condition="condition:file:other",
                object_id="object:action:other",
            )
        )
        engine.add_relation(
            MemoryLifeRelation(
                relation_id="duplicate-neighbor",
                source_memory_id="duplicate",
                target_memory_id="neighbor",
                relation_type="supports",
                weight=0.8,
                observed_at=_at(1),
            )
        )

        merged = engine.merge_memories(
            "canonical",
            ("duplicate",),
            at=_at(2),
            review_id="merge-review",
            rationale="Same source-grounded intent.",
            source_refs=("source-canonical", "source-duplicate"),
        )

        self.assertEqual(("duplicate",), merged)
        self.assertEqual("merged", engine.states["duplicate"].status)
        self.assertEqual(
            "canonical",
            engine.states["duplicate"].merged_into,
        )
        self.assertEqual(
            {"evidence-a", "evidence-b"},
            {
                item.evidence_id
                for item in engine.states["canonical"].seed.evidence
            },
        )
        self.assertEqual(
            {
                "source-canonical",
                "source-duplicate",
            },
            set(
                engine.states["canonical"].seed.metadata[
                    "source_event_ids"
                ]
            ),
        )
        self.assertEqual(1, engine.states["canonical"].activation_count)
        self.assertEqual(
            _at(1),
            engine.states["canonical"].last_activated_at,
        )
        endpoints = {
            (
                relation.source_memory_id,
                relation.target_memory_id,
            )
            for relation in engine.relations.values()
        }
        self.assertIn(("canonical", "neighbor"), endpoints)

    def test_two_skills_reach_consensus_and_delete_temporary_md(
        self,
    ) -> None:
        engine = self._engine()
        engine.add_memory(_seed("memory-a"))
        engine.add_memory(_seed("memory-b"))
        client = ConsensusFakeClient()
        with TemporaryDirectory() as directory:
            reflection = LifecycleReflection(
                client,
                temporary_directory=Path(directory),
            )
            result = reflection.run(
                engine,
                (_packet("memory-a"), _packet("memory-b")),
                at=_at(10),
                round_id="round-1",
            )

            self.assertEqual(4, len(client.calls))
            self.assertEqual(
                ["merge", "merge", "correction", "correction"],
                [
                    str(call["task_name"]).split(":", 1)[0]
                    for call in client.calls
                ],
            )
            self.assertEqual(4, result["temporary_files_deleted"])
            self.assertEqual([], list(Path(directory).iterdir()))
            self.assertEqual(1, result["reviewed_memory_count"])
        self.assertEqual(["memory-b"], result["merged_memory_ids"])
        self.assertEqual("active", engine.states["memory-a"].status)
        self.assertEqual("merged", engine.states["memory-b"].status)

    def test_coalesced_packet_combines_activity_and_sources(self) -> None:
        first = _packet("memory-a")
        second = replace(
            _packet("memory-b"),
            activation_count=3,
            first_activated_at=_at(5),
            last_activated_at=_at(35),
            activation_span_days=30.0,
            latest_evidence_at=_at(20),
            inactivity_days=5.0,
            obsolete_after_days=95.0,
        )

        merged = LifecycleReflection._coalesced_packet(
            (first, second),
            "memory-a",
            at=_at(40),
        )

        self.assertEqual(3, merged.activation_count)
        self.assertEqual(_at(5), merged.first_activated_at)
        self.assertEqual(_at(35), merged.last_activated_at)
        self.assertEqual(5.0, merged.inactivity_days)
        self.assertGreaterEqual(merged.obsolete_after_days, 95.0)
        self.assertEqual(
            {
                "source-memory-a",
                "source-memory-b",
            },
            merged.visible_source_ids,
        )

    def test_invalid_source_citations_cannot_lower_confidence(self) -> None:
        engine = self._engine()
        engine.add_memory(_seed("memory-a"))
        client = ConsensusFakeClient(invalid_citations=True)
        with TemporaryDirectory() as directory:
            reflection = LifecycleReflection(
                client,
                temporary_directory=Path(directory),
            )
            proposals = reflection.review_corrections(
                (_packet("memory-a"),),
                round_id="round-invalid",
            )

        self.assertEqual("unverifiable", proposals[0].verdict)
        self.assertEqual(1.0, proposals[0].penalty_factor)
        self.assertEqual(3, len(client.calls))

    def test_incomplete_source_coverage_cannot_penalize_or_merge(
        self,
    ) -> None:
        engine = self._engine()
        engine.add_memory(_seed("memory-a"))
        engine.add_memory(_seed("memory-b"))
        client = ConsensusFakeClient()
        packets = (
            _packet("memory-a", source_evidence_count=2),
            _packet("memory-b"),
        )
        with TemporaryDirectory() as directory:
            reflection = LifecycleReflection(
                client,
                temporary_directory=Path(directory),
            )
            result = reflection.run(
                engine,
                packets,
                at=_at(10),
                round_id="privacy-incomplete",
            )

        proposals = result["correction_proposals"]
        self.assertEqual("unverifiable", proposals[0]["verdict"])
        self.assertEqual([], result["penalized_memory_ids"])
        self.assertEqual([], result["merged_memory_ids"])
        self.assertEqual("active", engine.states["memory-b"].status)

    def test_structured_checks_override_inconsistent_verdict(self) -> None:
        verdict = LifecycleReflection._normalized_correction_verdict(
            {
                "verdict": "supported",
                "evidence_status": "complete",
                "attitude_alignment": "contradicted",
                "scope_alignment": "aligned",
                "memory_role": "reusable_rule",
            },
            _packet("memory-a"),
        )
        obsolete = LifecycleReflection._normalized_correction_verdict(
            {
                "verdict": "supported",
                "evidence_status": "complete",
                "attitude_alignment": "aligned",
                "scope_alignment": "aligned",
                "memory_role": "obsolete_one_off",
            },
            replace(
                _packet("memory-a"),
                inactivity_days=100.0,
            ),
        )

        self.assertEqual("contradicted", verdict)
        self.assertEqual("obsolete_task_state", obsolete)

    def test_specific_source_cannot_be_global_when_condition_missing(
        self,
    ) -> None:
        packet = replace(
            _packet("memory-a"),
            condition_tag_ids=(),
        )

        verdict = LifecycleReflection._normalized_correction_verdict(
            {
                "verdict": "supported",
                "evidence_status": "complete",
                "attitude_alignment": "aligned",
                "source_scope": "specific",
                "scope_alignment": "aligned",
                "memory_role": "reusable_rule",
            },
            packet,
        )

        self.assertEqual("scope_error", verdict)

    def test_blank_condition_value_is_missing_scope(self) -> None:
        packet = replace(
            _packet("memory-a"),
            condition_tag_ids=("",),
        )

        verdict = LifecycleReflection._normalized_correction_verdict(
            {
                "verdict": "supported",
                "evidence_status": "complete",
                "attitude_alignment": "aligned",
                "source_scope": "specific",
                "scope_alignment": "aligned",
                "memory_role": "reusable_rule",
            },
            packet,
        )

        self.assertFalse(packet.has_condition)
        self.assertEqual("scope_error", verdict)

    def test_scope_loss_precedes_attitude_diagnosis(self) -> None:
        packet = replace(
            _packet("memory-a"),
            condition_tag_ids=("",),
        )

        verdict = LifecycleReflection._normalized_correction_verdict(
            {
                "verdict": "contradicted",
                "evidence_status": "complete",
                "attitude_alignment": "contradicted",
                "source_scope": "specific",
                "scope_alignment": "overgeneralized",
                "memory_role": "reusable_rule",
            },
            packet,
        )

        self.assertEqual("scope_error", verdict)

    def test_blank_available_source_is_not_complete_coverage(self) -> None:
        packet = replace(
            _packet("memory-a"),
            source_refs=(
                ReflectionSource(
                    source_id="source-memory-a",
                    source_kind="query",
                    text="   ",
                ),
            ),
        )

        self.assertFalse(packet.source_coverage_complete)

    def test_recent_supporting_evidence_guards_obsolete_review(self) -> None:
        engine = self._engine()
        seed = _seed("memory-a")
        engine.add_memory(
            replace(
                seed,
                evidence=(
                    replace(seed.evidence[0], observed_at=_at(100)),
                ),
            )
        )

        changed = engine.apply_reflection_penalty(
            "memory-a",
            penalty_factor=0.6,
            at=_at(120),
            review_id="review-recent-evidence",
            verdict="obsolete_task_state",
            rationale="The task appears old.",
        )

        self.assertFalse(changed)
        event = engine.states["memory-a"].events[-1]
        self.assertTrue(event["guarded_obsolete"])
        self.assertEqual(20.0, event["inactivity_days"])

    def test_recurrence_extends_obsolete_horizon(self) -> None:
        engine = self._engine()
        engine.add_memory(_seed("memory-a"))
        for day in (10, 40, 80):
            engine.query(
                LifecycleObservation(
                    observation_id=f"query-{day}",
                    user_id="user-1",
                    observed_at=_at(day),
                    source_kind="query",
                    condition_tag_ids=("condition:file:sheet",),
                    object_tag_ids=("object:action:chart",),
                    attitude_polarity="support",
                ),
                top_k=1,
            )

        changed = engine.apply_reflection_penalty(
            "memory-a",
            penalty_factor=0.6,
            at=_at(150),
            review_id="review-recurring",
            verdict="obsolete_task_state",
            rationale="The task has not appeared recently.",
        )

        self.assertFalse(changed)
        event = engine.states["memory-a"].events[-1]
        self.assertGreater(event["obsolete_after_days"], 70.0)
        self.assertTrue(event["guarded_obsolete"])

    def test_multiple_observations_can_share_one_complete_source(
        self,
    ) -> None:
        engine = self._engine()
        seed = _seed("memory-a")
        seed = replace(
            seed,
            evidence=(
                *seed.evidence,
                ConfidenceEvidence(
                    evidence_id="second-observation",
                    observed_at=_at(0),
                    source_kind="text",
                    quality=0.9,
                    independent_unit_id="second-observation",
                ),
            ),
        )
        engine.add_memory(seed)

        packets = build_reflection_packets(
            engine,
            {
                "source-memory-a": {
                    "source_kind": "query",
                    "original_text": "Use this chart.",
                }
            },
            at=_at(10),
        )

        self.assertEqual(1, packets[0].source_evidence_count)
        self.assertTrue(packets[0].source_coverage_complete)

    def test_scheduler_requires_idle_window_and_prevents_repeats(
        self,
    ) -> None:
        ready = ReflectionScheduleInput(
            now=_at(30),
            last_reflection_at=_at(0),
            active_memory_count=500,
            unreviewed_memory_count=300,
            changed_memory_count=80,
            high_risk_memory_count=30,
            idle_seconds=3600,
            predicted_idle_seconds=2400,
            predicted_idle_probability=0.95,
            active_task_count=0,
        )
        active_task = ReflectionScheduleInput(
            **{**asdict(ready), "active_task_count": 1}
        )
        just_ran = ReflectionScheduleInput(
            **{
                **asdict(ready),
                "last_reflection_at": _at(29.9),
                "unreviewed_memory_count": 0,
                "changed_memory_count": 0,
            }
        )

        self.assertTrue(
            calculate_reflection_schedule(ready).should_reflect
        )
        self.assertFalse(
            calculate_reflection_schedule(active_task).should_reflect
        )
        repeated = calculate_reflection_schedule(just_ran)
        self.assertFalse(repeated.should_reflect)
        self.assertIn("cooldown", repeated.reason)


if __name__ == "__main__":
    unittest.main()
