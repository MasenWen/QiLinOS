from __future__ import annotations

import unittest
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory

from src.memory_engine.strict.config import STAGE_ORDER, StrictMemoryEngineConfig
from src.memory_engine.strict.contracts import (
    BoundaryDecision,
    Completion,
    ExecutionFragment,
)
from src.memory_engine.strict.engine import StrictMemoryEngine
from src.memory_engine.strict.errors import (
    IdempotencyConflictError,
    StrictStageUnavailableError,
)
from src.memory_engine.strict.episode import SplitMergeEpisodeRepair
from src.memory_engine.strict.store import StrictMemoryEngineStore
from src.memory_engine.strict.registry import StrictModuleRegistry


class StrictMemoryEngineTestCase(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.config = StrictMemoryEngineConfig.load(
            database_path=Path(self.directory.name) / "strict.db"
        )
        self.store = StrictMemoryEngineStore(self.config.database_path)
        self.engine = StrictMemoryEngine(config=self.config, store=self.store)

    def tearDown(self):
        self.directory.cleanup()

    def ingest(self, source_event_id: str, event_time: str, **values):
        stage_limit = values.pop("stage_limit", "episode_repair")
        return self.engine.ingest_observation(
            {
                "source_type": values.pop("source_type", "gui_action"),
                "source_event_id": source_event_id,
                "user_id": "U001",
                "session_id": "S001",
                "event_time": event_time,
                **values,
            },
            stage_limit=stage_limit,
        )


class StrictConfigurationAndRegistryTest(StrictMemoryEngineTestCase):
    def test_config_names_every_formal_stage_and_missing_registry_fails_closed(self):
        self.assertEqual(set(STAGE_ORDER), set(self.config.modules))
        self.assertTrue(self.config.strict_full_activation)
        self.engine.validate_full_activation()
        empty_registry = StrictModuleRegistry()
        with self.assertRaises(StrictStageUnavailableError):
            empty_registry.validate_full(self.config)

    def test_stage_trace_explicitly_records_no_fallback(self):
        result = self.ingest(
            "trace-1",
            "2026-07-23T10:00:00+08:00",
            action="start",
            task="draft report",
        )
        self.assertFalse(result["fallback_used"])
        self.assertEqual(
            {
                "observation",
                "stm",
                "episode_repair",
            },
            set(result["module_versions"]),
        )


class StrictObservationContractTest(StrictMemoryEngineTestCase):
    def test_supported_sources_are_typed_and_ordered(self):
        events = [
            {
                "source_type": "dialogue",
                "source_event_id": "source-dialogue",
                "actor": "user",
                "content": "Continue the report.",
            },
            {
                "source_type": "gui_action",
                "source_event_id": "source-gui",
                "app": "writer",
                "action": "save",
                "artifact_refs": ["report.odt"],
            },
            {
                "source_type": "tool_result",
                "source_event_id": "source-tool",
                "tool": "save_document",
                "success": True,
                "output_schema_valid": True,
                "state_changed": True,
            },
            {
                "source_type": "manual_config",
                "source_event_id": "source-config",
                "namespace": "writer",
                "key": "currency",
                "new_value": "USD",
                "version": 2,
            },
            {
                "source_type": "system_event",
                "source_event_id": "source-system",
                "event": "task_complete",
                "message": "Report completed.",
            },
        ]
        for sequence_no, event in enumerate(events):
            event.update(
                {
                    "user_id": "U001",
                    "session_id": "S001",
                    "sequence_no": sequence_no,
                    "event_time": f"2026-07-23T10:0{sequence_no}:00+08:00",
                }
            )
            result = self.engine.ingest_observation(event)
            self.assertEqual("ok", result["status"])

        observations = self.store.list_observations("U001", "S001")
        self.assertEqual(
            [
                "dialogue",
                "gui_action",
                "tool_result",
                "manual_config",
                "system_event",
            ],
            [item.source_type.value for item in observations],
        )
        self.assertEqual(Completion.COMPLETED, observations[-1].completion)
        self.assertTrue(observations[2].result["success"])
        self.assertEqual("USD", observations[3].result["new_value"])

    def test_replay_is_idempotent_but_changed_replay_is_rejected(self):
        event = {
            "source_type": "dialogue",
            "source_event_id": "replay",
            "user_id": "U001",
            "session_id": "S001",
            "event_time": "2026-07-23T10:00:00+08:00",
            "content": "Use USD.",
        }
        first = self.engine.ingest_observation(event)
        second = self.engine.ingest_observation(event)
        self.assertTrue(first["observation_created"])
        self.assertFalse(second["observation_created"])
        self.assertEqual(first["observation_id"], second["observation_id"])

        with self.assertRaises(IdempotencyConflictError):
            self.engine.ingest_observation({**event, "content": "Use CNY."})

    def test_secret_is_rejected_before_observation_storage(self):
        result = self.ingest(
            "secret",
            "2026-07-23T10:00:00+08:00",
            source_type="manual_config",
            namespace="llm",
            key="api_key",
            new_value="sk-abcdefghijklmnopqrstuvwxyz123456",
        )
        self.assertEqual("rejected", result["status"])
        self.assertEqual(0, self.store.counts()["strict_observations"])
        self.assertEqual(1, self.store.counts()["strict_engine_runs"])


class StrictEpisodeRepairTest(StrictMemoryEngineTestCase):
    def test_completion_then_new_goal_is_forced_split(self):
        first = self.ingest(
            "finish-report",
            "2026-07-23T10:00:00+08:00",
            action="task_complete",
            completion="completed",
            task="draft report",
            goal="submit report",
            artifact_refs=["report.odt"],
        )
        second = self.ingest(
            "start-mail",
            "2026-07-23T10:01:00+08:00",
            action="task_started",
            task="reply to customer",
            goal="answer customer",
            artifact_refs=["mail-88"],
        )
        execution, fragments = self.store.get_execution("U001", "S001")
        self.assertEqual(2, len(fragments))
        self.assertTrue(execution.path_valid)
        self.assertNotEqual(first["fragment_ids"], second["fragment_ids"])
        boundary = fragments[1].boundary_before
        self.assertIsNotNone(boundary)
        self.assertTrue(boundary.forced)
        self.assertIn(
            "task_complete_then_new_start",
            boundary.reason_codes,
        )

    def test_app_switch_and_gui_noise_do_not_split_or_pollute_workflow(self):
        self.ingest(
            "writer-click",
            "2026-07-23T10:00:00+08:00",
            app="writer",
            action="click",
            task="draft report",
            artifact_refs=["report.odt"],
        )
        result = self.ingest(
            "browser-save",
            "2026-07-23T10:01:00+08:00",
            app="browser",
            action="save",
            task="draft report",
            artifact_refs=["report.odt"],
        )
        execution, fragments = self.store.get_execution("U001", "S001")
        self.assertEqual(1, len(fragments))
        self.assertEqual(("save",), fragments[0].actions)
        self.assertEqual({"writer", "browser"}, set(fragments[0].apps))
        self.assertTrue(result["path_valid"])
        self.assertEqual(execution.observation_ids, fragments[0].observation_ids)

    def test_state_discontinuity_creates_auditable_boundary(self):
        self.ingest(
            "state-left",
            "2026-07-23T10:00:00+08:00",
            action="edit",
            goal="prepare report",
            artifact_refs=["report.odt"],
            post_state={"document": "open", "version": 2},
        )
        self.ingest(
            "state-right",
            "2026-07-23T10:01:00+08:00",
            action="edit",
            goal="prepare report",
            artifact_refs=["report.odt"],
            pre_state={"document": "closed", "version": 1},
        )
        execution, _ = self.store.get_execution("U001", "S001")
        decisions = [
            item
            for item in execution.repair_trace
            if item["operation"] == "split_decision"
        ]
        self.assertEqual(1.0, decisions[0]["decision"]["features"]["state_discontinuity"])
        self.assertIn(
            "state_discontinuity",
            decisions[0]["decision"]["reason_codes"],
        )

    def test_merge_rule_obeys_score_and_completion_hard_gate(self):
        repair = SplitMergeEpisodeRepair(self.config.episode)
        boundary = BoundaryDecision(False, 0.0, ("test",), {})
        left = ExecutionFragment(
            fragment_id="left",
            user_id="U001",
            session_id="S001",
            observation_ids=("left-obs",),
            start_time="2026-07-23T10:00:00+08:00",
            end_time="2026-07-23T10:01:00+08:00",
            task="draft report",
            goal="prepare report",
            pre_state={"document": "open"},
            post_state={"document": "open"},
            actions=("edit",),
            artifact_refs=("report.odt",),
            entity_refs=(),
            apps=("writer",),
            completion=Completion.INCOMPLETE,
            source_episode_ids=("episode-left",),
            boundary_before=boundary,
        )
        right = replace(
            left,
            fragment_id="right",
            observation_ids=("right-obs",),
            start_time="2026-07-23T10:02:00+08:00",
            end_time="2026-07-23T10:03:00+08:00",
            source_episode_ids=("episode-right",),
        )
        should_merge, decision = repair.merge_decision(left, right)
        self.assertTrue(should_merge)
        self.assertGreaterEqual(decision["score"], self.config.episode.merge_threshold)

        completed = replace(left, completion=Completion.COMPLETED)
        should_merge, decision = repair.merge_decision(completed, right)
        self.assertFalse(should_merge)
        self.assertIn(
            "unrelated_after_completion",
            decision["hard_gate_reasons"],
        )

    def test_stage_outputs_are_append_only_across_repair_runs(self):
        self.ingest(
            "history-1",
            "2026-07-23T10:00:00+08:00",
            action="edit",
            task="draft report",
        )
        self.ingest(
            "history-2",
            "2026-07-23T10:01:00+08:00",
            action="save",
            task="draft report",
        )
        counts = self.store.counts()
        self.assertEqual(2, counts["strict_engine_runs"])
        self.assertEqual(6, counts["strict_stage_outputs"])
        self.assertEqual(2, counts["strict_repaired_executions"])


if __name__ == "__main__":
    unittest.main()
