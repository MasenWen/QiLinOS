from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from src.memory_engine.conflict import ConflictMemory, ConflictResolver
from src.memory_engine.memory_lifecycle import (
    CONFIDENCE_STRATEGIES,
    STABILITY_STRATEGIES,
    ConfidenceEvidence,
    MemoryLifeSeed,
    MemoryLifecycleEngine,
)
from tools.evaluate_online_retrieval_v1 import (
    RetrievalRuntime,
    _deadline_expansion_conditions,
    _latency_summary,
    _recall_expansion_conditions,
    _sdk_fingerprint,
    retrieve_once,
)


class _FakeEmbedder:
    requested = 0
    computed = 0


class _FakeMatcher:
    def __init__(self) -> None:
        self.embedder = _FakeEmbedder()
        self.registry = SimpleNamespace(
            find_mentions=lambda text: ()
        )
        self.last_budget = None

    def match(self, text, *, options, budget=None):
        self.last_budget = budget
        self.embedder.requested += 2
        self.embedder.computed += 1
        condition = SimpleNamespace(
            tag_id="condition:file:sheet",
            text="sheet",
        )
        obj = SimpleNamespace(
            tag_id="object:action:chart",
            text="chart",
        )
        attitude = SimpleNamespace(value=0.5, text="use")
        frame = SimpleNamespace(
            condition=condition,
            object=obj,
            attitude=attitude,
            confidence=0.9,
            temporal=None,
            source_start=0,
            source_end=len(text),
        )
        return SimpleNamespace(
            frames=(frame,),
            diagnostics={
                "observation_budget": (
                    budget.diagnostics()
                    if budget is not None
                    else {"enabled": False}
                )
            },
        )


def _runtime() -> RetrievalRuntime:
    engine = MemoryLifecycleEngine(
        STABILITY_STRATEGIES["weibull"](),
        CONFIDENCE_STRATEGIES["beta_bound"](),
    )
    memory_id = "memory-1"
    created_at = "2026-07-25T09:00:00+08:00"
    engine.add_memory(
        MemoryLifeSeed(
            memory_id=memory_id,
            user_id="benchmark_user_01",
            created_at=created_at,
            source_kind="text",
            temporal_label="temporal_short",
            temporal_confidence=0.8,
            explicit_long_term=False,
            base_strength=0.9,
            condition_tag_ids=("condition:file:sheet",),
            object_tag_ids=("object:action:chart",),
            attitude_polarity="positive",
            evidence=(
                ConfidenceEvidence(
                    evidence_id="evidence-1",
                    observed_at=created_at,
                    source_kind="text",
                    quality=0.9,
                ),
            ),
        )
    )
    conflicts = ConflictResolver()
    conflicts.add(
        ConflictMemory(
            memory_id=memory_id,
            user_id="benchmark_user_01",
            slot_key="condition:file:sheet",
            value="object:action:chart",
            confidence=0.9,
            source_kind="text",
            observed_at=created_at,
        )
    )
    return RetrievalRuntime(
        engine=engine,
        conflicts=conflicts,
        memory_payloads={
            memory_id: {
                "memory_id": memory_id,
                "summary": "Use a chart.",
                "expected_action": "chart",
                "condition_tag_id": "condition:file:sheet",
                "object_tag_id": "object:action:chart",
            }
        },
        condition_tag_ids=("condition:file:sheet",),
        object_tag_ids=("object:action:chart",),
        detected_conflict_count=0,
    )


def _query(text: str) -> dict[str, str]:
    return {
        "query_id": "query-1",
        "query_text": text,
        "current_context_ids": "",
        "evaluation_track": "single_memory",
        "query_type": "unit",
        "dataset_partition": "test",
        "required_memory_ids": "memory-1",
        "forbidden_memory_ids": "",
    }


class OnlineRetrievalEvaluationTest(unittest.TestCase):
    def test_deadline_expansion_requires_two_explicit_conditions(self) -> None:
        matcher = SimpleNamespace(
            registry=SimpleNamespace(
                find_mentions=lambda text: (
                    SimpleNamespace(tag_id="condition:file:one"),
                    SimpleNamespace(tag_id="condition:file:two"),
                    SimpleNamespace(tag_id="object:action:chart"),
                )
            )
        )
        budget = SimpleNamespace(hard_stop_reached=True)

        self.assertEqual(
            ("condition:file:one", "condition:file:two"),
            _deadline_expansion_conditions(
                matcher,
                "work on one and two",
                (
                    "condition:file:one",
                    "condition:file:two",
                    "condition:file:three",
                ),
                budget,
            ),
        )

        budget.hard_stop_reached = False
        self.assertEqual(
            (),
            _deadline_expansion_conditions(
                matcher,
                "work on one and two",
                ("condition:file:one", "condition:file:two"),
                budget,
            ),
        )

    def test_recall_expansion_requires_concrete_intent_evidence(self) -> None:
        result = SimpleNamespace(
            frames=(),
            diagnostics={
                "full_text_formation_gate": {
                    "formation_similarity": 0.68,
                    "residual_margin": 0.05,
                },
                "ambiguity_guard": {"activated": False},
                "assembled_frames": [
                    {"object_tag_id": "object:action:chart"}
                ],
            }
        )

        self.assertEqual(
            ("condition:file:sheet", "condition:app:calc"),
            _recall_expansion_conditions(
                result,
                (
                    "condition:file:sheet",
                    "condition:app:calc",
                    "condition:file:sheet",
                ),
                (
                    "condition:file:sheet",
                    "condition:app:calc",
                ),
            ),
        )

    def test_recall_expansion_preserves_ambiguity_abstention(self) -> None:
        result = SimpleNamespace(
            frames=(),
            diagnostics={
                "full_text_formation_gate": {
                    "formation_similarity": 0.72,
                    "residual_margin": 0.01,
                },
                "ambiguity_guard": {"activated": True},
                "assembled_frames": [
                    {"object_tag_id": "object:action:chart"}
                ],
            }
        )

        self.assertEqual(
            (),
            _recall_expansion_conditions(
                result,
                ("condition:file:sheet",),
            ),
        )

    def test_accepted_concrete_frame_can_expand_without_full_gate(self) -> None:
        result = SimpleNamespace(
            frames=(
                SimpleNamespace(
                    object=SimpleNamespace(
                        tag_id="object:action:chart"
                    )
                ),
            ),
            diagnostics={
                "full_text_formation_gate": None,
                "ambiguity_guard": {"activated": False},
                "assembled_frames": [
                    {"object_tag_id": "object:action:chart"}
                ],
            },
        )

        self.assertEqual(
            ("condition:file:sheet",),
            _recall_expansion_conditions(
                result,
                ("condition:file:sheet",),
            ),
        )

    def test_recall_expansion_rejects_ambiguous_object_only(self) -> None:
        result = SimpleNamespace(
            frames=(),
            diagnostics={
                "full_text_formation_gate": {
                    "formation_similarity": 0.72,
                    "residual_margin": 0.01,
                },
                "ambiguity_guard": {"activated": False},
                "assembled_frames": [
                    {
                        "object_tag_id": (
                            "object:ambiguous_prior_workflow"
                        )
                    }
                ],
            }
        )

        self.assertEqual(
            (),
            _recall_expansion_conditions(
                result,
                ("condition:file:sheet",),
            ),
        )

    def test_safe_request_runs_the_complete_pipeline(self) -> None:
        matcher = _FakeMatcher()
        row = retrieve_once(
            matcher=matcher,
            runtime=_runtime(),
            query=_query("Please use the chart."),
            contexts={},
            condition_by_document={},
            observation_case={"gold_observations": []},
            pass_name="unit",
        )

        self.assertEqual("ok", row["status"])
        self.assertEqual(["memory-1"], row["selected_memory_ids"])
        self.assertEqual(1, row["embedding_computed_delta"])
        self.assertIsNotNone(matcher.last_budget)
        self.assertEqual(500.0, matcher.last_budget.soft_limit_ms)
        self.assertEqual(800.0, matcher.last_budget.hard_limit_ms)
        self.assertTrue(row["observation_budget"]["enabled"])
        self.assertEqual(
            {
                "input_safety",
                "normalization_and_context",
                "observation",
                "memory_query",
                "output_safety_and_packaging",
                "total",
            },
            set(row["stages_ms"]),
        )

    def test_unsafe_request_stops_before_observation(self) -> None:
        matcher = _FakeMatcher()
        row = retrieve_once(
            matcher=matcher,
            runtime=_runtime(),
            query=_query(
                "api_key=sk-123456789012345678901234567890"
            ),
            contexts={},
            condition_by_document={},
            observation_case={"gold_observations": []},
            pass_name="unit",
        )

        self.assertEqual("blocked_input", row["status"])
        self.assertEqual(0, matcher.embedder.computed)
        self.assertEqual(0.0, row["stages_ms"]["observation"])
        self.assertEqual([], row["selected_memory_ids"])

    def test_latency_summary_uses_the_explicit_budget(self) -> None:
        summary = _latency_summary(
            (100.0, 500.0, 501.0),
            budget_ms=500.0,
        )

        self.assertEqual(2, summary["within_budget_count"])
        self.assertAlmostEqual(2 / 3, summary["within_budget_rate"])
        self.assertEqual(500.0, summary["budget_ms"])

    def test_sdk_fingerprint_proves_real_file_and_no_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            library = Path(root) / "libkysdk-coreai-embedding.so.1"
            payload = b"synthetic-unit-test-library"
            library.write_bytes(payload)
            result = _sdk_fingerprint(
                SimpleNamespace(_model_name="unit-model", dim=768),
                library,
            )

        self.assertEqual("kylin_coreai_embedding", result["backend"])
        self.assertFalse(result["fallback_used"])
        self.assertEqual("unit-model", result["model_name"])
        self.assertEqual(768, result["dimension"])
        self.assertEqual(
            hashlib.sha256(payload).hexdigest(),
            result["library_sha256"],
        )


if __name__ == "__main__":
    unittest.main()
