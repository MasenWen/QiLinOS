from __future__ import annotations

import unittest
from os import environ
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from src.memory_engine.engine import MemoryEngine
from src.memory_engine.episode import EpisodeManager
from src.memory_engine.store import MemoryEngineStore


class MemoryEngineObservationTest(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.store = MemoryEngineStore(Path(self.directory.name) / "engine.db")
        self.engine = MemoryEngine(store=self.store)

    def tearDown(self):
        self.directory.cleanup()

    def test_all_source_adapters_preserve_required_semantics(self):
        events = [
            {
                "source_type": "dialogue",
                "source_event_id": "dialogue-1",
                "user_id": "U001",
                "session_id": "S001",
                "actor": "user",
                "content": "Please continue the report.",
            },
            {
                "source_type": "gui_action",
                "source_event_id": "gui-1",
                "user_id": "U001",
                "session_id": "S001",
                "app": "writer",
                "action": "clicked",
                "target": "save",
                "artifact_refs": ["report.odt"],
            },
            {
                "source_type": "tool_result",
                "source_event_id": "tool-1",
                "user_id": "U001",
                "session_id": "S001",
                "tool": "send_email",
                "success": False,
                "error_signature": "SMTP_TIMEOUT",
                "output_schema_valid": False,
                "state_changed": False,
                "latency_ms": 1200,
            },
            {
                "source_type": "manual_config",
                "source_event_id": "config-1",
                "user_id": "U001",
                "session_id": "S001",
                "namespace": "mail",
                "key": "confirm_before_send",
                "old_value": False,
                "new_value": True,
                "version": "2",
                "scope": "user",
                "changed_by": "user",
            },
            {
                "source_type": "system_event",
                "source_event_id": "system-1",
                "user_id": "U001",
                "session_id": "S001",
                "event": "task_started",
                "message": "Report task started.",
            },
        ]

        for event in events:
            with self.subTest(source_type=event["source_type"]):
                result = self.engine.ingest_event(event)
                self.assertEqual("ok", result["status"])
                self.assertTrue(result["schema_valid"])

        observations = self.store.list_observations("U001")
        self.assertEqual(5, len(observations))
        tool = next(item for item in observations if item.source_type == "tool_result")
        self.assertFalse(tool.result["success"])
        self.assertEqual("SMTP_TIMEOUT", tool.result["error_signature"])
        self.assertFalse(tool.result["output_schema_valid"])
        self.assertFalse(tool.result["state_changed"])
        self.assertEqual(1200.0, tool.result["latency_ms"])
        config = next(item for item in observations if item.source_type == "manual_config")
        self.assertEqual("mail", config.result["namespace"])
        self.assertEqual("confirm_before_send", config.result["key"])
        self.assertEqual(True, config.result["new_value"])

    def test_source_event_replay_is_idempotent_for_observation_and_episode(self):
        event = {
            "source_type": "dialogue",
            "source_event_id": "replay-1",
            "user_id": "U001",
            "session_id": "S001",
            "content": "Continue editing the same report.",
        }
        first = self.engine.ingest_event(event)
        second = self.engine.ingest_event(event)

        self.assertTrue(first["observation_created"])
        self.assertFalse(second["observation_created"])
        self.assertEqual(first["episode_id"], second["episode_id"])
        self.assertEqual(1, len(self.store.list_observations("U001")))
        self.assertEqual(1, len(self.store.list_episodes("U001")))

    def test_secret_config_is_rejected_before_storage(self):
        result = self.engine.ingest_event(
            {
                "source_type": "manual_config",
                "source_event_id": "secret-config",
                "user_id": "U001",
                "session_id": "S001",
                "namespace": "llm",
                "key": "api_key",
                "new_value": "sk-abcdefghijklmnopqrstuvwxyz123456",
            }
        )

        self.assertEqual({"status": "skipped", "reason": "unsafe_source_event"}, result)
        self.assertEqual([], self.store.list_observations("U001"))


class MemoryEngineEpisodeTest(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.store = MemoryEngineStore(Path(self.directory.name) / "engine.db")
        self.engine = MemoryEngine(store=self.store)

    def tearDown(self):
        self.directory.cleanup()

    def _ingest(self, event_id, event_time, **values):
        return self.engine.ingest_event(
            {
                "source_type": "gui_action",
                "source_event_id": event_id,
                "user_id": "U001",
                "session_id": "S001",
                "event_time": event_time,
                "app": values.pop("app", "writer"),
                "action": values.pop("action", "click"),
                **values,
            }
        )

    def test_application_switch_alone_does_not_split_episode(self):
        first = self._ingest("app-1", "2026-07-23T10:00:00+08:00", app="writer")
        second = self._ingest("app-2", "2026-07-23T10:01:00+08:00", app="browser")

        self.assertEqual(first["episode_id"], second["episode_id"])
        self.assertEqual("app_switch_only", second["boundary"]["reason"])
        self.assertEqual(1, len(self.store.list_episodes("U001")))

    def test_idle_gap_splits_unrelated_activity(self):
        first = self._ingest(
            "gap-1",
            "2026-07-23T10:00:00+08:00",
            app="writer",
        )
        second = self._ingest(
            "gap-2",
            "2026-07-23T10:20:01+08:00",
            app="mail",
        )

        self.assertNotEqual(first["episode_id"], second["episode_id"])
        self.assertEqual("idle_gap", second["boundary"]["reason"])
        self.assertEqual(2, len(self.store.list_episodes("U001")))

    def test_shared_artifact_keeps_episode_across_app_and_idle_gap(self):
        first = self._ingest(
            "artifact-1",
            "2026-07-23T10:00:00+08:00",
            app="writer",
            artifact_refs=["report.odt"],
        )
        second = self._ingest(
            "artifact-2",
            "2026-07-23T10:30:00+08:00",
            app="browser",
            artifact_refs=["report.odt"],
        )

        self.assertEqual(first["episode_id"], second["episode_id"])
        self.assertEqual("strong_relation", second["boundary"]["reason"])

    def test_explicit_completion_closes_then_new_activity_starts_episode(self):
        first = self._ingest(
            "done-1",
            "2026-07-23T10:00:00+08:00",
            action="submitted",
            goal="submit report",
            artifact_refs=["report.odt"],
        )
        second = self._ingest(
            "done-2",
            "2026-07-23T10:01:00+08:00",
            app="mail",
            goal="reply to customer",
            artifact_refs=["mail-88"],
        )

        self.assertEqual("closed", first["episode_status"])
        self.assertNotEqual(first["episode_id"], second["episode_id"])
        self.assertEqual(2, len(self.store.list_episodes("U001")))

    def test_repair_split_and_merge_are_reversible(self):
        first = self._ingest(
            "repair-1",
            "2026-07-23T10:00:00+08:00",
            task="draft report",
            artifact_refs=["report.odt"],
        )
        second = self._ingest(
            "repair-2",
            "2026-07-23T10:01:00+08:00",
            task="draft report",
            artifact_refs=["report.odt"],
        )
        manager = EpisodeManager(self.store)
        left, right = manager.split_episode(first["episode_id"], second["observation_id"])
        merged = manager.merge_episodes(left.episode_id, right.episode_id)

        self.assertEqual(2, len(merged.observation_ids))
        self.assertEqual("repair_merge", merged.boundary_reason)
        self.assertEqual("merged", self.store.get_episode(right.episode_id).status)


class MemoryEngineEpisodeEvidenceTest(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.store = MemoryEngineStore(Path(self.directory.name) / "engine.db")
        self.engine = MemoryEngine(store=self.store)

    def tearDown(self):
        self.directory.cleanup()

    def test_closed_episode_extracts_atomic_shadow_evidence(self):
        events = [
            {
                "source_type": "dialogue",
                "source_event_id": "ev-dialogue",
                "user_id": "U001",
                "session_id": "S001",
                "event_time": "2026-07-23T10:00:00+08:00",
                "actor": "user",
                "content": "默认 USD、回复简洁、外部邮件发送前必须确认",
                "task": "quotation reply",
                "artifact_refs": ["email-203"],
                "context": {"customer_type": "external"},
            },
            {
                "source_type": "tool_result",
                "source_event_id": "ev-api-fail",
                "user_id": "U001",
                "session_id": "S001",
                "event_time": "2026-07-23T10:01:00+08:00",
                "tool": "company_quote_api",
                "success": False,
                "error_signature": "HTTP_503",
                "output_schema_valid": False,
                "state_changed": False,
                "task": "quotation reply",
                "artifact_refs": ["email-203"],
                "context": {"customer_type": "external"},
            },
            {
                "source_type": "tool_result",
                "source_event_id": "ev-excel-success",
                "user_id": "U001",
                "session_id": "S001",
                "event_time": "2026-07-23T10:02:00+08:00",
                "tool": "quotation_excel",
                "success": True,
                "output_schema_valid": True,
                "state_changed": True,
                "task": "quotation reply",
                "artifact_refs": ["email-203"],
                "context": {"customer_type": "external"},
            },
            {
                "source_type": "system_event",
                "source_event_id": "ev-complete",
                "user_id": "U001",
                "session_id": "S001",
                "event_time": "2026-07-23T10:03:00+08:00",
                "event": "task_complete",
                "message": "Quotation reply completed.",
                "task": "quotation reply",
                "artifact_refs": ["email-203"],
                "context": {"customer_type": "external"},
            },
        ]

        with patch.dict(
            environ,
            {"NEX_MEMORY_EVIDENCE_MODE": "shadow_episode_v1"},
        ):
            results = [self.engine.ingest_event(event) for event in events]
            replay = self.engine.ingest_event(events[-1])

        episode_id = results[-1]["episode_id"]
        evidence = self.store.list_evidence_for_episode(episode_id)
        categories = [item.memory_category for item in evidence]
        recovery = next(
            item for item in evidence if item.memory_category == "recovery_case"
        )

        self.assertEqual("closed", results[-1]["episode_status"])
        self.assertEqual(7, len(evidence))
        self.assertEqual(3, categories.count("explicit_preference") + categories.count("safety_strategy"))
        self.assertEqual(2, categories.count("tool_outcome"))
        self.assertEqual(1, categories.count("task_outcome"))
        self.assertEqual("knowledge", recovery.memory_family)
        self.assertEqual("HTTP_503", recovery.condition["error_signature"])
        self.assertEqual(
            "company_quote_api->quotation_excel",
            recovery.claim_value,
        )
        self.assertTrue(recovery.statistics["is_fallback"])
        self.assertEqual((episode_id,), recovery.source_episode_ids)
        self.assertEqual(episode_id, recovery.independent_unit_id)
        self.assertFalse(replay["observation_created"])
        self.assertEqual(7, self.store.counts()["evidence"])
        self.assertEqual(1, self.store.counts()["engine_runs"])
        self.assertEqual(0, self.store.counts()["impacts"])
        self.assertEqual(0, self.store.counts()["memories"])
        self.assertEqual(0, self.store.counts()["index_refs"])

    def test_manual_close_runs_shadow_extractor(self):
        event = {
            "source_type": "dialogue",
            "source_event_id": "manual-close-dialogue",
            "user_id": "U001",
            "session_id": "S002",
            "event_time": "2026-07-23T11:00:00+08:00",
            "actor": "user",
            "content": "以后默认使用人民币",
            "task": "quotation reply",
        }
        with patch.dict(
            environ,
            {"NEX_MEMORY_EVIDENCE_MODE": "shadow_episode_v1"},
        ):
            self.engine.ingest_event(event)
            result = self.engine.close_episode(
                "S002",
                user_id="U001",
                reason="manual_test",
            )

        self.assertEqual("ok", result["status"])
        self.assertEqual("closed", result["episode_status"])
        self.assertEqual(1, result["extraction"]["evidence_count"])
        evidence = self.store.list_evidence_for_episode(result["episode_id"])
        self.assertEqual("preference:currency", evidence[0].claim_slot)
        self.assertEqual(0, self.store.counts()["memories"])


if __name__ == "__main__":
    unittest.main()
