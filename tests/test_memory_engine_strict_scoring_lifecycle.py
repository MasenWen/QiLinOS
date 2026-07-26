from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from src.memory_engine.strict.config import StrictMemoryEngineConfig
from src.memory_engine.strict.contracts import LifecycleStatus
from src.memory_engine.strict.engine import StrictMemoryEngine
from src.memory_engine.strict.store import StrictMemoryEngineStore


class StrictScoringLifecycleTest(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.config = StrictMemoryEngineConfig.load(
            database_path=Path(self.directory.name) / "strict.db"
        )
        self.store = StrictMemoryEngineStore(self.config.database_path)
        self.engine = StrictMemoryEngine(config=self.config, store=self.store)

    def tearDown(self):
        self.directory.cleanup()

    def preference(
        self,
        index: int,
        content: str = "以后默认使用 USD。",
        *,
        day: int,
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
                "source_event_id": f"score-{index}",
                "user_id": "U001",
                "session_id": f"S{index:03d}",
                "event_time": event_time.isoformat(),
                "actor": "user",
                "content": content,
                "task": "quotation reply",
            },
            stage_limit="lifecycle",
        )

    def test_confidence_uses_epsilon_and_abstains_on_one_support(self):
        self.preference(1, day=0)
        memory = self.store.list_memories("U001")[0]
        self.assertEqual(0.75, memory.confidence["absolute"])
        self.assertEqual(1.0, memory.confidence["choice"])
        self.assertEqual(1.0, memory.confidence["margin"])
        self.assertTrue(memory.confidence["abstain"])
        self.assertIn(
            "insufficient_independent_support",
            memory.confidence["abstain_reasons"],
        )

    def test_five_independent_windows_promote_candidate_to_stable(self):
        for index, day in enumerate((0, 4, 8, 15, 22), start=1):
            self.preference(index, day=day)
        memory = self.store.list_memories("U001")[0]
        self.assertEqual(5, len(memory.support_unit_ids))
        self.assertEqual(5, memory.stability["n_observed"])
        self.assertEqual(1.0, memory.stability["support_consistency"])
        self.assertEqual(1.0, memory.stability["value"])
        self.assertEqual(LifecycleStatus.STABLE, memory.status)
        events = self.store.list_lifecycle_events(memory.memory_id)
        self.assertEqual(1, len(events))
        self.assertEqual(LifecycleStatus.CANDIDATE, events[0].from_status)
        self.assertEqual(LifecycleStatus.STABLE, events[0].to_status)

    def test_opportunity_scope_counts_competing_choice_without_false_support(self):
        self.preference(1, "默认使用 USD。", day=0)
        self.preference(2, "默认使用 USD。", day=5)
        self.preference(3, "默认使用 USD。", day=10)
        self.preference(4, "默认使用人民币。", day=15)
        usd = next(
            item
            for item in self.store.list_memories("U001")
            if item.semantic_value == "USD"
        )
        self.assertEqual(4, usd.stability["n_observed"])
        self.assertEqual(3, usd.stability["n_supported"])
        self.assertEqual(0.75, usd.stability["support_consistency"])
        self.assertEqual(1, usd.stability["switches"])
        self.assertEqual(3, usd.confidence["support_independent_units"])
        self.assertFalse(usd.confidence["abstain"])

    def test_dynamic_historical_status_is_lifecycle_hard_exception(self):
        self.preference(1, "默认使用 USD。", day=0)
        self.preference(2, "从今天起以后默认使用人民币。", day=20)
        old = next(
            item
            for item in self.store.list_memories("U001")
            if item.semantic_value == "USD"
        )
        self.assertEqual(LifecycleStatus.HISTORICAL, old.status)
        self.assertEqual([], self.store.list_lifecycle_events(old.memory_id))


if __name__ == "__main__":
    unittest.main()
