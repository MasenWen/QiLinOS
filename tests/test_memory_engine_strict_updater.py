from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from src.memory_engine.strict.config import StrictMemoryEngineConfig
from src.memory_engine.strict.contracts import ImpactAction, LifecycleStatus
from src.memory_engine.strict.engine import StrictMemoryEngine
from src.memory_engine.strict.store import StrictMemoryEngineStore


class StrictUpdaterTest(unittest.TestCase):
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
            stage_limit="memory_update",
        )

    def test_same_independent_unit_never_inflates_support_count(self):
        event = {
            "source_type": "dialogue",
            "source_event_id": "same-unit",
            "user_id": "U001",
            "session_id": "S001",
            "event_time": "2026-07-23T10:00:00+08:00",
            "actor": "user",
            "content": "以后默认 USD。",
            "task": "quotation reply",
        }
        first = self.engine.ingest_observation(event, stage_limit="memory_update")
        first_impact_ids = {
            item.impact_id for item in self.store.list_impacts()
        }
        second = self.engine.ingest_observation(event, stage_limit="memory_update")
        second_impact_ids = {
            item.impact_id for item in self.store.list_impacts()
        }
        memories = self.store.list_memories("U001")
        self.assertEqual(1, len(memories))
        self.assertEqual(1, len(memories[0].support_unit_ids))
        self.assertEqual(first["memory_ids"], second["memory_ids"])
        self.assertEqual(first_impact_ids, second_impact_ids)
        self.assertEqual([], self.store.list_unapplied_candidates("U001"))

    def test_explicit_temporal_change_creates_multiple_impacts_and_lineage(self):
        self.preference(
            "currency-old",
            "默认使用 USD。",
            session_id="S001",
            event_time="2026-07-01T10:00:00+08:00",
        )
        result = self.preference(
            "currency-new",
            "从今天起以后默认使用人民币。",
            session_id="S002",
            event_time="2026-07-23T10:00:00+08:00",
        )
        memories = self.store.list_memories(
            "U001",
            slot_key="preference:currency",
        )
        old = next(item for item in memories if item.semantic_value == "USD")
        new = next(item for item in memories if item.semantic_value == "CNY")
        self.assertEqual(LifecycleStatus.HISTORICAL, old.status)
        self.assertEqual(LifecycleStatus.CANDIDATE, new.status)
        self.assertIn(new.memory_id, old.successor_memory_ids)
        self.assertIn(old.memory_id, new.predecessor_memory_ids)
        new_candidate_id = next(
            candidate.candidate_id
            for candidate in self.store.list_candidates("U001")
            if candidate.semantic_value == "CNY"
        )
        actions = {
            impact.action
            for impact in self.store.list_impacts()
            if impact.candidate_id == new_candidate_id
        }
        self.assertEqual(
            {ImpactAction.CREATE, ImpactAction.SUPERSEDE},
            actions,
        )
        self.assertGreaterEqual(len(result["impact_ids"]), 2)

    def test_disjoint_conditions_specialize_without_overwriting(self):
        self.preference(
            "external-currency",
            "以后默认使用 USD。",
            session_id="S001",
            event_time="2026-07-01T10:00:00+08:00",
            context={"customer_type": "external"},
        )
        self.preference(
            "internal-currency",
            "以后默认使用人民币。",
            session_id="S002",
            event_time="2026-07-02T10:00:00+08:00",
            context={"customer_type": "internal"},
        )
        memories = self.store.list_memories(
            "U001",
            slot_key="preference:currency",
        )
        self.assertEqual(2, len(memories))
        self.assertTrue(
            all(item.status is LifecycleStatus.CANDIDATE for item in memories)
        )
        self.assertIn(
            ImpactAction.SPECIALIZE,
            {item.action for item in self.store.list_impacts()},
        )

    def test_one_candidate_can_create_and_contradict_multiple_memories(self):
        self.preference(
            "currency-a",
            "默认使用 USD。",
            session_id="S001",
            event_time="2026-07-01T10:00:00+08:00",
        )
        self.preference(
            "currency-b",
            "默认使用人民币。",
            session_id="S002",
            event_time="2026-07-02T10:00:00+08:00",
        )
        self.preference(
            "currency-c",
            "默认使用欧元。",
            session_id="S003",
            event_time="2026-07-03T10:00:00+08:00",
        )
        eur_candidate = next(
            item
            for item in self.store.list_candidates("U001")
            if item.semantic_value == "EUR"
        )
        impacts = [
            item
            for item in self.store.list_impacts()
            if item.candidate_id == eur_candidate.candidate_id
        ]
        self.assertEqual(1, sum(item.action is ImpactAction.CREATE for item in impacts))
        self.assertEqual(
            2,
            sum(item.action is ImpactAction.CONTRADICT for item in impacts),
        )

    def test_recent_behavior_window_supersedes_completed_old_window(self):
        choices = ("line_chart",) * 4 + ("bar_chart",) * 3
        for day, choice in enumerate(choices, start=1):
            self.engine.ingest_observation(
                {
                    "source_type": "gui_action",
                    "source_event_id": f"chart-{day}",
                    "user_id": "U001",
                    "session_id": f"S-CHART-{day}",
                    "event_time": f"2026-07-{day:02d}T10:00:00+08:00",
                    "action": "create_chart",
                    "target": choice,
                    "content": f"Selected {choice} for the sales trend",
                    "task": "sales analysis",
                    "app": "spreadsheet",
                    "context": {"scene": "sales analysis"},
                },
                stage_limit="memory_update",
            )

        memories = self.store.list_memories(
            "U001",
            slot_key="behavior:sales_analysis:create_chart",
        )
        old = next(
            item for item in memories if "line_chart" in item.semantic_value
        )
        current = next(
            item for item in memories if "bar_chart" in item.semantic_value
        )
        self.assertEqual(LifecycleStatus.HISTORICAL, old.status)
        self.assertEqual(LifecycleStatus.CANDIDATE, current.status)
        self.assertIn(current.memory_id, old.successor_memory_ids)
        self.assertIn(old.memory_id, current.predecessor_memory_ids)
        self.assertEqual(
            "recent_window_behavior_drift",
            current.provenance["dynamic_reason"],
        )
        bar_candidate_ids = {
            item.candidate_id
            for item in self.store.list_candidates("U001")
            if "bar_chart" in item.semantic_value
        }
        self.assertIn(
            ImpactAction.SUPERSEDE,
            {
                impact.action
                for impact in self.store.list_impacts()
                if impact.candidate_id in bar_candidate_ids
            },
        )

    def test_nonexclusive_observed_behaviors_coexist_as_multi_cardinality(self):
        for index, target in enumerate(
            ("weekly_template.docx", "customer_notes.docx"),
            start=1,
        ):
            self.engine.ingest_observation(
                {
                    "source_type": "gui_action",
                    "source_event_id": f"routine-{index}",
                    "user_id": "U001",
                    "session_id": f"S-ROUTINE-{index}",
                    "event_time": f"2026-07-0{index}T10:00:00+08:00",
                    "action": "open_file",
                    "target": target,
                    "content": f"Opened {target}",
                    "task": "weekly reporting",
                    "app": "word_processor",
                    "context": {"scene": "weekly reporting"},
                },
                stage_limit="memory_update",
            )

        memories = [
            item
            for item in self.store.list_memories("U001")
            if item.slot_key
            == "behavior:weekly_reporting:open_file"
        ]
        self.assertEqual(2, len(memories))
        self.assertTrue(all(item.cardinality == "multi" for item in memories))
        self.assertNotIn(
            ImpactAction.CONTRADICT,
            {
                impact.action
                for impact in self.store.list_impacts()
                if impact.target_memory_id
                in {item.memory_id for item in memories}
            },
        )


if __name__ == "__main__":
    unittest.main()
