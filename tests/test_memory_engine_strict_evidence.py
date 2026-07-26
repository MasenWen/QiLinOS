from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from src.memory_engine.strict.config import StrictMemoryEngineConfig
from src.memory_engine.strict.contracts import EvidenceAdmission
from src.memory_engine.strict.engine import StrictMemoryEngine
from src.memory_engine.strict.store import StrictMemoryEngineStore


class StrictEvidenceTest(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.config = StrictMemoryEngineConfig.load(
            database_path=Path(self.directory.name) / "strict.db"
        )
        self.store = StrictMemoryEngineStore(self.config.database_path)
        self.engine = StrictMemoryEngine(config=self.config, store=self.store)

    def tearDown(self):
        self.directory.cleanup()

    def ingest(
        self,
        source_event_id: str,
        event_time: str,
        *,
        source_type: str = "dialogue",
        **values,
    ):
        return self.engine.ingest_observation(
            {
                "source_type": source_type,
                "source_event_id": source_event_id,
                "user_id": "U001",
                "session_id": "S001",
                "event_time": event_time,
                **values,
            },
            stage_limit="evidence",
        )

    def test_multi_claim_instruction_becomes_three_atomic_long_term_evidence(self):
        result = self.ingest(
            "multi-claim",
            "2026-07-23T10:00:00+08:00",
            actor="user",
            content="以后默认 USD，回复保持简洁，外部邮件发送前必须确认。",
            task="quotation reply",
            context={"customer_type": "external"},
        )
        evidence = self.store.list_evidence("U001")
        self.assertEqual(3, len(evidence))
        self.assertEqual(
            {
                "preference:currency",
                "preference:output_style",
                "safety:send_or_persist",
            },
            {item.claim_slot for item in evidence},
        )
        self.assertTrue(all(item.eligible_for_candidate for item in evidence))
        self.assertTrue(
            all(
                item.admission is EvidenceAdmission.LONG_TERM_CANDIDATE
                for item in evidence
            )
        )
        self.assertTrue(
            all(len(item.source_observation_ids) == 1 for item in evidence)
        )
        self.assertEqual(3, result["candidate_eligible_count"])

    def test_one_off_instruction_is_scoped_and_not_candidate_eligible(self):
        self.ingest(
            "one-off",
            "2026-07-23T10:00:00+08:00",
            actor="user",
            content="这次报价使用 USD，回复简洁。",
            task="quotation reply",
        )
        evidence = self.store.list_evidence("U001")
        self.assertEqual(2, len(evidence))
        self.assertTrue(
            all(item.admission is EvidenceAdmission.SCOPED_ONLY for item in evidence)
        )
        self.assertTrue(all(not item.eligible_for_candidate for item in evidence))

    def test_unadopted_agent_recommendation_does_not_form_preference(self):
        self.ingest(
            "agent-recommendation",
            "2026-07-23T10:00:00+08:00",
            actor="agent",
            content="I recommend that USD should always be the default.",
            task="quotation reply",
        )
        self.assertEqual([], self.store.list_evidence("U001"))

    def test_single_tool_failure_is_case_evidence_not_stable_rule(self):
        self.ingest(
            "tool-failure",
            "2026-07-23T10:00:00+08:00",
            source_type="tool_result",
            tool="company_quote_api",
            success=False,
            error_signature="HTTP_503",
            output_schema_valid=False,
            state_changed=False,
            task="quotation reply",
        )
        evidence = self.store.list_evidence("U001")
        self.assertEqual(1, len(evidence))
        item = evidence[0]
        self.assertEqual("knowledge", item.memory_family)
        self.assertEqual("case", item.candidate_kind)
        self.assertEqual(EvidenceAdmission.CASE_CANDIDATE, item.admission)
        self.assertTrue(item.statistics["single_failure"])
        self.assertNotEqual("preference", item.memory_family)

    def test_complete_fallback_workflow_keeps_knowledge_and_case_separate(self):
        self.ingest(
            "workflow-failure",
            "2026-07-23T10:00:00+08:00",
            source_type="tool_result",
            tool="company_quote_api",
            success=False,
            error_signature="HTTP_503",
            output_schema_valid=False,
            state_changed=False,
            task="quotation reply",
            artifact_refs=["quote-88"],
        )
        self.ingest(
            "workflow-recovery",
            "2026-07-23T10:01:00+08:00",
            source_type="tool_result",
            tool="quotation_excel",
            success=True,
            output_schema_valid=True,
            state_changed=True,
            task="quotation reply",
            artifact_refs=["quote-88"],
        )
        self.ingest(
            "workflow-complete",
            "2026-07-23T10:02:00+08:00",
            source_type="system_event",
            event="task_complete",
            message="Quotation reply completed.",
            task="quotation reply",
            artifact_refs=["quote-88"],
        )
        evidence = self.store.list_evidence("U001")
        workflow = next(item for item in evidence if item.evidence_type == "complete_workflow")
        recovery = next(item for item in evidence if item.evidence_type == "recovery_case")
        self.assertEqual("knowledge", workflow.memory_family)
        self.assertEqual("workflow", workflow.candidate_kind)
        self.assertTrue(workflow.statistics["preference_inference_forbidden"])
        self.assertEqual("knowledge", recovery.memory_family)
        self.assertEqual("case", recovery.candidate_kind)
        self.assertTrue(recovery.statistics["is_fallback"])
        self.assertEqual(
            "company_quote_api->quotation_excel",
            recovery.claim_value,
        )
        self.assertEqual(
            workflow.independent_unit_id,
            recovery.independent_unit_id,
        )

    def test_versioned_manual_config_is_direct_atomic_evidence(self):
        self.ingest(
            "manual-config",
            "2026-07-23T10:00:00+08:00",
            source_type="manual_config",
            namespace="mail",
            key="confirm_before_send",
            old_value=False,
            new_value=True,
            version=3,
            changed_by="user",
        )
        evidence = self.store.list_evidence("U001")
        self.assertEqual(1, len(evidence))
        item = evidence[0]
        self.assertEqual("config:mail:confirm_before_send", item.claim_slot)
        self.assertEqual("true", item.claim_value)
        self.assertEqual("versioned_config", item.directness)
        self.assertEqual(3, item.statistics["version"])

    def test_candidate_modules_only_accept_their_evidence_kind(self):
        result = self.engine.ingest_observation(
            {
                "source_type": "dialogue",
                "source_event_id": "candidate-routing",
                "user_id": "U001",
                "session_id": "S001",
                "event_time": "2026-07-23T10:00:00+08:00",
                "actor": "user",
                "content": "以后默认 USD，回复保持简洁。",
                "task": "quotation reply",
            },
            stage_limit="template",
        )
        candidates = self.store.list_candidates("U001")
        self.assertEqual(2, len(candidates))
        self.assertEqual(
            {"fact", "output_style"},
            {item.candidate_kind for item in candidates},
        )
        self.assertEqual(
            {"candidate.fact_rule.v1", "candidate.output_style_rule.v1"},
            {item.source_module_id for item in candidates},
        )
        self.assertEqual(
            {item.candidate_id for item in candidates},
            set(result["candidate_ids"]),
        )


    def test_behavior_abstraction_drops_object_suffix_but_scoped_context_keeps_it(self):
        self.ingest(
            "rename-dated-file",
            "2026-07-23T10:00:00+08:00",
            source_type="gui_action",
            action="rename_file",
            target="2026-07-23_meeting_notes.md",
            content=(
                "按日期命名整理会议纪要。 "
                "对象：2026-07-23_meeting_notes.md"
            ),
            task="file management",
            app="file_manager",
            context={"scene": "file_management"},
        )
        evidence = self.store.list_evidence("U001")
        scoped = next(
            item for item in evidence if item.admission.value == "scoped_only"
        )
        behavior = next(
            item
            for item in evidence
            if item.evidence_type == "observed_behavior"
        )
        self.assertIn(
            "2026-07-23_meeting_notes.md",
            scoped.claim_value,
        )
        self.assertEqual(
            "按日期命名整理会议纪要。",
            behavior.claim_value,
        )


if __name__ == "__main__":
    unittest.main()
