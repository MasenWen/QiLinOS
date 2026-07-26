from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from src.memory_engine.strict.config import StrictMemoryEngineConfig
from src.memory_engine.strict.engine import StrictMemoryEngine
from src.memory_engine.strict.store import StrictMemoryEngineStore


class GoldKylinScorer:
    backend_id = "openkylin_text_embedding_sdk_gold_double"

    def score(self, query, memories):
        return {memory.memory_id: 1.0 for memory in memories}


class StrictEndToEndGoldTest(unittest.TestCase):
    def test_formal_chain_produces_actionable_grounded_memories(self):
        with TemporaryDirectory() as directory:
            config = StrictMemoryEngineConfig.load(
                database_path=Path(directory) / "strict.db"
            )
            store = StrictMemoryEngineStore(config.database_path)
            engine = StrictMemoryEngine(
                config=config,
                store=store,
                semantic_scorer=GoldKylinScorer(),
            )
            final_run = None
            start = datetime(
                2026,
                6,
                1,
                10,
                tzinfo=timezone(timedelta(hours=8)),
            )
            for index, day in enumerate((0, 4, 8, 15, 22), start=1):
                final_run = engine.ingest_observation(
                    {
                        "source_type": "dialogue",
                        "source_event_id": f"gold-{index}",
                        "user_id": "GOLD_USER",
                        "session_id": f"GOLD_SESSION_{index}",
                        "event_time": (start + timedelta(days=day)).isoformat(),
                        "actor": "user",
                        "content": (
                            "以后默认 USD，回复保持简洁，"
                            "外部邮件发送前必须确认。"
                        ),
                        "task": "quotation reply",
                        "context": {"customer_type": "external"},
                    },
                    stage_limit="lifecycle",
                )

            stages = [
                output.stage
                for output in store.list_stage_outputs(final_run["run_id"])
            ]
            self.assertEqual(
                [
                    "observation",
                    "stm",
                    "episode_repair",
                    "evidence",
                    "tool_preference",
                    "output_style",
                    "safety",
                    "fact",
                    "workflow",
                    "case",
                    "template",
                    "memory_update",
                    "conflict_classifier",
                    "static_resolver",
                    "dynamic_resolver",
                    "conditional_resolver",
                    "confidence",
                    "stability",
                    "lifecycle",
                ],
                stages,
            )
            retrieval = engine.retrieve(
                "为外部客户生成报价并发送邮件",
                {
                    "user_id": "GOLD_USER",
                    "query_time": "2026-07-01T10:00:00+08:00",
                    "task": "quotation reply",
                    "customer_type": "external",
                    "memory_need": "currency output_style safety",
                },
                top_k=5,
            )
            self.assertEqual(3, len(retrieval["planner"]["selected_memory_ids"]))
            self.assertEqual(
                {
                    "preference:currency",
                    "preference:output_style",
                    "safety:send_or_persist",
                },
                {item["slot_key"] for item in retrieval["items"]},
            )
            reflection = engine.reflect("GOLD_USER")
            self.assertEqual(3, len(reflection["artifacts"]))
            self.assertTrue(
                all(
                    artifact["grounding_verified"]
                    for artifact in reflection["artifacts"]
                )
            )
            dry_run = engine.forget(
                {
                    "user_id": "GOLD_USER",
                    "slot_key": "preference:output_style",
                },
                dry_run=True,
            )
            self.assertEqual("planned", dry_run["status"])
            self.assertEqual(1, len(dry_run["candidate_memory_ids"]))


if __name__ == "__main__":
    unittest.main()
