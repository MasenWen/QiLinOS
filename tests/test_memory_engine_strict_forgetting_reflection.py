from __future__ import annotations

import unittest
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory

from src.memory_engine.strict.config import StrictMemoryEngineConfig
from src.memory_engine.strict.contracts import LifecycleStatus
from src.memory_engine.strict.engine import StrictMemoryEngine
from src.memory_engine.strict.store import StrictMemoryEngineStore


class ZeroKylinScorer:
    backend_id = "openkylin_text_embedding_sdk_test_double"

    def score(self, query, memories):
        return {memory.memory_id: 0.0 for memory in memories}


class StrictForgettingReflectionTest(unittest.TestCase):
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

    def preference(
        self,
        event_id: str,
        content: str,
        *,
        session_id: str,
        event_time: str,
        stage_limit: str = "lifecycle",
    ):
        return self.engine.ingest_observation(
            {
                "source_type": "dialogue",
                "source_event_id": event_id,
                "user_id": "U001",
                "session_id": session_id,
                "event_time": event_time,
                "actor": "user",
                "content": content,
                "task": "quotation reply",
            },
            stage_limit=stage_limit,
        )

    def test_dry_run_has_no_lineage_side_effects(self):
        self.preference(
            "dry-usd",
            "以后默认使用 USD。",
            session_id="S001",
            event_time="2026-07-01T10:00:00+08:00",
        )
        before = self.store.counts()
        result = self.engine.forget(
            {
                "user_id": "U001",
                "semantic_value": "USD",
                "reason": "test",
            },
            dry_run=True,
        )
        memory = self.store.list_memories("U001")[0]
        self.assertEqual("planned", result["status"])
        self.assertEqual(LifecycleStatus.CANDIDATE, memory.status)
        self.assertEqual([], self.store.list_suppressions("U001"))
        self.assertEqual(
            before["strict_evidence"],
            self.store.counts()["strict_evidence"],
        )

    def test_forget_dynamic_successor_restores_predecessor_and_suppresses_regrowth(self):
        self.preference(
            "old-usd",
            "默认使用 USD。",
            session_id="S001",
            event_time="2026-07-01T10:00:00+08:00",
        )
        self.preference(
            "new-cny",
            "从今天起以后默认使用人民币。",
            session_id="S002",
            event_time="2026-07-20T10:00:00+08:00",
        )
        result = self.engine.forget(
            {
                "user_id": "U001",
                "slot_key": "preference:currency",
                "semantic_value": "CNY",
                "reason": "user_revoked_cny",
            },
            dry_run=False,
        )
        self.assertEqual("completed", result["status"])
        self.assertTrue(result["report"]["residual_verified"])
        memories = self.store.list_memories("U001")
        cny = next(item for item in memories if item.semantic_value == "CNY")
        usd = next(item for item in memories if item.semantic_value == "USD")
        self.assertEqual(LifecycleStatus.DELETED, cny.status)
        self.assertEqual(LifecycleStatus.CANDIDATE, usd.status)
        self.assertEqual("", usd.valid_to)
        self.assertEqual(1, len(self.store.list_suppressions("U001")))

        retrieval = self.engine.retrieve(
            "报价默认货币",
            {
                "user_id": "U001",
                "query_time": "2026-07-21T10:00:00+08:00",
                "task": "quotation reply",
                "memory_need": "currency",
            },
        )
        self.assertNotIn(
            "CNY",
            [item["semantic_value"] for item in retrieval["items"]],
        )

        replay = self.preference(
            "new-cny-again",
            "以后默认使用人民币。",
            session_id="S003",
            event_time="2026-07-22T10:00:00+08:00",
            stage_limit="evidence",
        )
        self.assertEqual(0, replay["candidate_eligible_count"])
        self.assertEqual([], replay["created_evidence_ids"])
        self.assertEqual(1, len(replay["suppressed_evidence_ids"]))
        self.assertEqual(
            1,
            self.store.counts()["strict_suppressions"],
        )

    def test_reflection_is_grounded_and_deleted_memory_disappears(self):
        self.preference(
            "reflect-usd",
            "以后默认使用 USD。",
            session_id="S001",
            event_time="2026-07-01T10:00:00+08:00",
        )
        reflected = self.engine.reflect("U001")
        self.assertEqual(1, len(reflected["artifacts"]))
        artifact = reflected["artifacts"][0]
        self.assertTrue(artifact["grounding_verified"])
        self.assertEqual(1, len(artifact["evidence_ids"]))
        self.assertIn("preference:currency = USD", artifact["claim"])

        self.engine.forget(
            {
                "user_id": "U001",
                "semantic_value": "USD",
            },
            dry_run=False,
        )
        reflected_after = self.engine.reflect("U001")
        self.assertEqual([], reflected_after["artifacts"])

    def test_reflection_reports_broken_grounding_instead_of_inventing_claim(self):
        self.preference(
            "broken-grounding",
            "以后默认使用 USD。",
            session_id="S001",
            event_time="2026-07-01T10:00:00+08:00",
        )
        memory = self.store.list_memories("U001")[0]
        self.store.put_memory(
            replace(memory, evidence_ids=("missing-evidence",))
        )
        result = self.engine.reflect("U001")
        artifact = result["artifacts"][0]
        self.assertFalse(artifact["grounding_verified"])
        self.assertIn(
            "missing_or_retracted_evidence",
            artifact["grounding_errors"],
        )
        self.assertIn("no_active_evidence", artifact["grounding_errors"])


if __name__ == "__main__":
    unittest.main()
