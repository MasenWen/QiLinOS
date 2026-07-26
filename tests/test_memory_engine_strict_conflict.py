from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from src.memory_engine.strict.config import StrictMemoryEngineConfig
from src.memory_engine.strict.contracts import ConflictType, LifecycleStatus
from src.memory_engine.strict.engine import StrictMemoryEngine
from src.memory_engine.strict.store import StrictMemoryEngineStore


class StrictConflictTest(unittest.TestCase):
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
        event_id: str,
        content: str,
        *,
        session_id: str,
        event_time: str,
        context=None,
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
                "context": context or {},
            },
            stage_limit="conditional_resolver",
        )

    def test_static_conflict_abstains_when_source_and_support_are_tied(self):
        self.preference(
            "static-usd",
            "默认使用 USD。",
            session_id="S001",
            event_time="2026-07-01T10:00:00+08:00",
        )
        self.preference(
            "static-cny",
            "默认使用人民币。",
            session_id="S002",
            event_time="2026-07-02T10:00:00+08:00",
        )
        groups = self.store.list_conflict_groups(
            "U001",
            slot_key="preference:currency",
        )
        self.assertEqual(1, len(groups))
        group = groups[0]
        self.assertEqual(ConflictType.STATIC, group.conflict_type)
        self.assertEqual("unresolved", group.status)
        self.assertEqual("", group.winner_memory_id)
        self.assertEqual("static_priority_tie", group.unresolved_reason)

    def test_dynamic_conflict_has_historical_predecessor_and_one_winner(self):
        self.preference(
            "dynamic-usd",
            "默认使用 USD。",
            session_id="S001",
            event_time="2026-07-01T10:00:00+08:00",
        )
        self.preference(
            "dynamic-cny",
            "从今天起以后默认使用人民币。",
            session_id="S002",
            event_time="2026-07-23T10:00:00+08:00",
        )
        groups = self.store.list_conflict_groups(
            "U001",
            slot_key="preference:currency",
        )
        self.assertEqual(1, len(groups))
        group = groups[0]
        self.assertEqual(ConflictType.DYNAMIC, group.conflict_type)
        self.assertEqual("resolved", group.status)
        winner = self.store.get_memory(group.winner_memory_id)
        self.assertEqual("CNY", winner.semantic_value)
        old = next(
            item
            for item in self.store.list_memories("U001")
            if item.semantic_value == "USD"
        )
        self.assertEqual(LifecycleStatus.HISTORICAL, old.status)
        self.assertEqual(winner.valid_from, old.valid_to)

    def test_condition_partition_precedes_time_and_requires_query_condition(self):
        self.preference(
            "conditional-external",
            "以后默认使用 USD。",
            session_id="S001",
            event_time="2026-07-01T10:00:00+08:00",
            context={"customer_type": "external"},
        )
        self.preference(
            "conditional-internal",
            "从今天起以后默认使用人民币。",
            session_id="S002",
            event_time="2026-07-23T10:00:00+08:00",
            context={"customer_type": "internal"},
        )
        group = self.store.list_conflict_groups(
            "U001",
            slot_key="preference:currency",
        )[0]
        self.assertEqual(ConflictType.CONDITIONAL, group.conflict_type)
        self.assertEqual("partitioned", group.status)
        self.assertEqual("", group.winner_memory_id)
        self.assertEqual("query_condition_required", group.unresolved_reason)
        self.assertEqual(2, len(group.condition_partition))
        self.assertTrue(
            all(
                condition["customer_type"] in {"external", "internal"}
                for condition in group.condition_partition.values()
            )
        )

    def test_disjoint_activity_is_partitioned_before_internal_dynamic_conflict(self):
        self.preference(
            "sales-old",
            "默认使用 USD。",
            session_id="S001",
            event_time="2026-07-01T10:00:00+08:00",
            context={"activity": "sales_trend"},
        )
        self.preference(
            "finance-current",
            "默认使用欧元。",
            session_id="S002",
            event_time="2026-07-02T10:00:00+08:00",
            context={"activity": "finance_summary"},
        )
        initial = self.store.list_conflict_groups(
            "U001",
            slot_key="preference:currency",
        )
        self.assertEqual(1, len(initial))
        self.assertEqual(ConflictType.CONDITIONAL, initial[0].conflict_type)

        self.preference(
            "sales-new",
            "从今天起以后默认使用人民币。",
            session_id="S003",
            event_time="2026-07-23T10:00:00+08:00",
            context={"activity": "sales_trend"},
        )
        active = self.store.list_conflict_groups(
            "U001",
            slot_key="preference:currency",
        )
        self.assertEqual(1, len(active))
        self.assertEqual(ConflictType.DYNAMIC, active[0].conflict_type)
        self.assertEqual(2, len(active[0].memory_ids))
        active_values = {
            self.store.get_memory(memory_id).semantic_value
            for memory_id in active[0].memory_ids
        }
        self.assertEqual({"USD", "CNY"}, active_values)

        audit_groups = self.store.list_conflict_groups(
            "U001",
            slot_key="preference:currency",
            include_obsolete=True,
        )
        self.assertEqual(2, len(audit_groups))
        self.assertEqual(
            1,
            sum(group.status == "obsolete" for group in audit_groups),
        )


if __name__ == "__main__":
    unittest.main()
