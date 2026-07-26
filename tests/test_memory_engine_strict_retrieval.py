from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from src.memory_engine.strict.config import StrictMemoryEngineConfig
from src.memory_engine.strict.engine import StrictMemoryEngine
from src.memory_engine.strict.errors import StrictConfigurationError
from src.memory_engine.strict.kylin import KylinSDKSemanticScorer
from src.memory_engine.strict.store import StrictMemoryEngineStore


class ZeroKylinScorer:
    backend_id = "openkylin_text_embedding_sdk_test_double"

    def score(self, query, memories):
        return {memory.memory_id: 0.0 for memory in memories}


class StrictRetrievalTest(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.config = StrictMemoryEngineConfig.load(
            database_path=Path(self.directory.name) / "strict.db"
        )
        self.store = StrictMemoryEngineStore(self.config.database_path)
        self.engine = StrictMemoryEngine(
            config=self.config,
            store=self.store,
            semantic_scorer=ZeroKylinScorer(),
        )

    def tearDown(self):
        self.directory.cleanup()

    def ingest(
        self,
        index: int,
        content: str,
        *,
        day: int,
        context=None,
    ):
        event_time = datetime(
            2026,
            7,
            1,
            10,
            tzinfo=timezone(timedelta(hours=8)),
        ) + timedelta(days=day)
        return self.engine.ingest_observation(
            {
                "source_type": "dialogue",
                "source_event_id": f"retrieval-{index}",
                "user_id": "U001",
                "session_id": f"S{index:03d}",
                "event_time": event_time.isoformat(),
                "actor": "user",
                "content": content,
                "task": "quotation reply",
                "context": context or {},
            },
            stage_limit="lifecycle",
        )

    def test_low_confidence_memory_is_advisory_not_actionable(self):
        self.ingest(1, "以后默认使用 USD。", day=0)
        result = self.engine.retrieve(
            "报价应该使用什么货币？",
            {
                "user_id": "U001",
                "query_time": "2026-07-02T10:00:00+08:00",
                "task": "quotation reply",
                "memory_need": "currency",
            },
        )
        self.assertEqual([], result["planner"]["selected_memory_ids"])
        self.assertEqual(1, len(result["planner"]["advisory_memory_ids"]))
        self.assertTrue(result["planner"]["abstained"])
        self.assertEqual("advisory", result["items"][0]["decision"])

    def test_repeated_support_becomes_actionable_and_has_lineage(self):
        for index, day in enumerate((0, 4, 8, 15, 22), start=1):
            self.ingest(index, "以后默认使用 USD。", day=day)
        result = self.engine.retrieve(
            "生成报价时使用默认货币",
            {
                "user_id": "U001",
                "query_time": "2026-08-01T10:00:00+08:00",
                "task": "quotation reply",
                "memory_need": "currency",
            },
        )
        self.assertEqual(1, len(result["planner"]["selected_memory_ids"]))
        self.assertEqual("USD", result["items"][0]["semantic_value"])
        self.assertEqual("actionable", result["items"][0]["decision"])
        self.assertEqual(5, len(result["items"][0]["lineage"]["support_unit_ids"]))

    def test_conditional_conflict_selects_known_branch_or_requests_context(self):
        self.ingest(
            1,
            "以后默认使用 USD。",
            day=0,
            context={"customer_type": "external"},
        )
        self.ingest(
            2,
            "以后默认使用人民币。",
            day=1,
            context={"customer_type": "internal"},
        )
        known = self.engine.retrieve(
            "生成报价",
            {
                "user_id": "U001",
                "query_time": "2026-07-03T10:00:00+08:00",
                "task": "quotation reply",
                "customer_type": "external",
                "memory_need": "currency",
            },
        )
        self.assertEqual([], known["planner"]["clarifications"])
        self.assertEqual(["USD"], [item["semantic_value"] for item in known["items"]])

        missing = self.engine.retrieve(
            "生成报价",
            {
                "user_id": "U001",
                "query_time": "2026-07-03T10:00:00+08:00",
                "task": "quotation reply",
                "memory_need": "currency",
            },
        )
        self.assertEqual(1, len(missing["planner"]["clarifications"]))
        self.assertIn(
            "customer_type",
            missing["planner"]["clarifications"][0]["required_condition_keys"],
        )
        self.assertEqual(2, len(missing["items"]))

    def test_kylin_semantic_scores_are_injected_without_baseline_fallback(self):
        self.ingest(1, "以后默认使用 USD。", day=0)
        self.ingest(2, "以后回复保持简洁。", day=1)
        memories = self.store.list_memories("U001")
        style_id = next(
            item.memory_id
            for item in memories
            if item.slot_key == "preference:output_style"
        )
        scores = {
            item.memory_id: (1.0 if item.memory_id == style_id else 0.0)
            for item in memories
        }
        result = self.engine.retrieve(
            "回忆用户习惯",
            {
                "user_id": "U001",
                "query_time": "2026-07-03T10:00:00+08:00",
            },
            kylin_semantic_scores=scores,
        )
        self.assertEqual(style_id, result["items"][0]["memory_id"])
        self.assertEqual("provided_scores", result["trace"]["semantic_backend"])
        self.assertFalse(result["trace"]["fallback_used"])

    def test_future_memory_is_removed_by_hard_filter(self):
        self.ingest(1, "以后默认使用 USD。", day=20)
        result = self.engine.retrieve(
            "报价默认货币",
            {
                "user_id": "U001",
                "query_time": "2026-07-05T10:00:00+08:00",
                "task": "quotation reply",
                "memory_need": "currency",
            },
        )
        self.assertEqual([], result["items"])
        excluded = result["trace"]["hard_filter"]["excluded"]
        self.assertIn(
            "future_validity",
            next(iter(excluded.values())),
        )

    def test_historical_query_keeps_predecessor_while_current_query_uses_winner(self):
        self.ingest(
            1,
            "默认使用 USD。",
            day=0,
            context={"activity": "sales_trend"},
        )
        self.ingest(
            2,
            "从今天起以后默认使用人民币。",
            day=4,
            context={"activity": "sales_trend"},
        )

        historical = self.engine.retrieve(
            "调取变更前的旧偏好历史记忆",
            {
                "user_id": "U001",
                "query_time": "2026-07-10T10:00:00+08:00",
                "task": "quotation reply",
                "activity": "sales_trend",
                "memory_need": "偏好变化前的历史记忆",
            },
        )
        self.assertIn(
            "USD",
            {item["semantic_value"] for item in historical["items"]},
        )

        current = self.engine.retrieve(
            "调取最近几次更新后的有效偏好",
            {
                "user_id": "U001",
                "query_time": "2026-07-10T10:00:00+08:00",
                "task": "quotation reply",
                "activity": "sales_trend",
                "memory_need": "更新后的有效偏好",
            },
        )
        self.assertEqual(
            ["CNY"],
            [item["semantic_value"] for item in current["items"]],
        )

    def test_retrieval_fails_closed_when_kylin_scores_are_missing(self):
        self.ingest(1, "以后默认使用 USD。", day=0)
        engine_without_sdk = StrictMemoryEngine(
            config=self.config,
            store=self.store,
        )
        with self.assertRaises(StrictConfigurationError):
            engine_without_sdk.retrieve(
                "报价默认货币",
                {
                    "user_id": "U001",
                    "query_time": "2026-07-02T10:00:00+08:00",
                },
            )

    def test_gui_context_is_retrievable_without_becoming_long_term_memory(self):
        self.engine.ingest_observation(
            {
                "source_type": "gui_action",
                "source_event_id": "gui-open-quote",
                "user_id": "U001",
                "session_id": "S-GUI",
                "event_time": "2026-07-10T10:00:00+08:00",
                "action": "open_file",
                "target": "Q3-enterprise-quote.xlsx",
                "content": "Opened Q3-enterprise-quote.xlsx in spreadsheet",
                "task": "quotation reply",
                "app": "spreadsheet",
                "context": {"scene": "enterprise quotation"},
            },
            stage_limit="evidence",
        )

        self.assertEqual([], self.store.list_memories("U001"))
        evidence = self.store.list_evidence("U001")
        self.assertEqual(2, len(evidence))
        scoped = next(
            item for item in evidence if item.admission.value == "scoped_only"
        )
        behavioral = next(
            item
            for item in evidence
            if item.admission.value == "long_term_candidate"
        )
        self.assertTrue(
            behavioral.statistics["preference_inference_forbidden"]
        )

        result = self.engine.retrieve(
            "Which quotation file did I just open?",
            {
                "user_id": "U001",
                "query_time": "2026-07-10T10:05:00+08:00",
                "task": "quotation reply",
                "scene": "enterprise quotation",
            },
        )
        self.assertEqual(1, len(result["items"]))
        self.assertEqual("actionable", result["items"][0]["decision"])
        self.assertIn("Q3-enterprise-quote.xlsx", result["items"][0]["semantic_value"])
        self.assertEqual(
            [scoped.evidence_id],
            result["items"][0]["lineage"]["evidence_ids"],
        )
        self.assertEqual([], self.store.list_memories("U001"))

    def test_temporary_preference_is_scoped_retrievable_and_not_promoted(self):
        self.engine.ingest_observation(
            {
                "source_type": "dialogue",
                "source_event_id": "temporary-currency",
                "user_id": "U001",
                "session_id": "S-TEMP",
                "event_time": "2026-07-10T11:00:00+08:00",
                "actor": "user",
                "content": "For this task, use USD.",
                "task": "one-off quotation",
            },
            stage_limit="lifecycle",
        )

        self.assertEqual([], self.store.list_memories("U001"))
        evidence = self.store.list_evidence("U001")
        self.assertEqual(1, len(evidence))
        self.assertFalse(evidence[0].eligible_for_candidate)

        result = self.engine.retrieve(
            "What currency should this task use?",
            {
                "user_id": "U001",
                "query_time": "2026-07-10T11:05:00+08:00",
                "task": "one-off quotation",
                "memory_need": "currency",
            },
        )
        self.assertEqual("USD", result["items"][0]["semantic_value"])
        self.assertEqual("actionable", result["items"][0]["decision"])
        self.assertTrue(result["items"][0]["stability"]["promotion_forbidden"])
        self.assertEqual([], self.store.list_memories("U001"))

    def test_scoped_projection_selects_latest_evidence_as_of_query_time(self):
        for source_event_id, event_time, target in (
            ("open-before", "2026-07-01T10:00:00+08:00", "before.xlsx"),
            ("open-after", "2026-07-03T10:00:00+08:00", "after.xlsx"),
        ):
            self.engine.ingest_observation(
                {
                    "source_type": "gui_action",
                    "source_event_id": source_event_id,
                    "user_id": "U001",
                    "session_id": source_event_id,
                    "event_time": event_time,
                    "action": "open_file",
                    "target": target,
                    "content": f"Opened {target}",
                    "task": "spreadsheet review",
                    "app": "spreadsheet",
                    "context": {"scene": "spreadsheet review"},
                },
                stage_limit="evidence",
            )

        result = self.engine.retrieve(
            "Which file was open?",
            {
                "user_id": "U001",
                "query_time": "2026-07-02T10:00:00+08:00",
                "task": "spreadsheet review",
                "scene": "spreadsheet review",
                "app": "spreadsheet",
            },
        )
        self.assertEqual(1, len(result["items"]))
        self.assertIn("before.xlsx", result["items"][0]["semantic_value"])

    def test_repeated_gui_behavior_forms_knowledge_not_preference(self):
        for index, day in enumerate((0, 4, 8, 15, 22), start=1):
            self.engine.ingest_observation(
                {
                    "source_type": "gui_action",
                    "source_event_id": f"gui-export-{index}",
                    "user_id": "U001",
                    "session_id": f"S-EXPORT-{index}",
                    "event_time": (
                        datetime(
                            2026,
                            7,
                            1,
                            10,
                            tzinfo=timezone(timedelta(hours=8)),
                        )
                        + timedelta(days=day)
                    ).isoformat(),
                    "action": "export_file",
                    "target": "monthly_report.pdf",
                    "content": "Exported the monthly report as PDF",
                    "task": "monthly reporting",
                    "app": "office",
                    "context": {"scene": "monthly reporting"},
                },
                stage_limit="lifecycle",
            )

        memories = self.store.list_memories("U001")
        behavior = next(
            item
            for item in memories
            if item.slot_key == "behavior:monthly_reporting:export_file"
        )
        self.assertEqual("knowledge", behavior.memory_family)
        self.assertEqual("stable", behavior.status.value)
        self.assertEqual(5, len(behavior.support_unit_ids))
        self.assertTrue(
            behavior.provenance["preference_inference_forbidden"]
        )
        result = self.engine.retrieve(
            "How is the monthly report usually exported?",
            {
                "user_id": "U001",
                "query_time": "2026-08-01T10:00:00+08:00",
                "task": "monthly reporting",
                "scene": "monthly reporting",
                "app": "office",
                "memory_need": "repeated export behavior",
            },
            top_k=10,
        )
        self.assertEqual(1, len(result["trace"]["hard_filter"]["included_ids"]))
        self.assertEqual(behavior.memory_id, result["items"][0]["memory_id"])

    def test_kylin_sdk_scorer_uses_embedding_vectors_directly(self):
        self.ingest(1, "以后默认使用 USD。", day=0)
        self.ingest(2, "以后回复保持简洁。", day=1)
        memories = self.store.list_memories("U001")

        class FakeEmbedder:
            def embed_batch(self, texts, memory_action):
                self.texts = texts
                self.memory_action = memory_action
                return [[1.0, 0.0], [1.0, 0.0], [0.0, 1.0]]

        embedder = FakeEmbedder()
        scores = KylinSDKSemanticScorer(embedder=embedder).score(
            "currency",
            memories,
        )
        self.assertEqual("search", embedder.memory_action)
        self.assertEqual(3, len(embedder.texts))
        self.assertTrue(
            all("中期记忆" in text for text in embedder.texts[1:])
        )
        self.assertTrue(
            all("当前有效记忆" in text for text in embedder.texts[1:])
        )
        self.assertEqual([0.0, 1.0], sorted(scores.values()))


if __name__ == "__main__":
    unittest.main()
