from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from src.memory_engine.strict.config import StrictMemoryEngineConfig
from src.memory_engine.strict.engine import StrictMemoryEngine
from src.memory_engine.strict.sparse_projection import (
    SparseProjectionIndex,
    SparseProjectionSettings,
    text_features,
)
from src.memory_engine.strict.store import StrictMemoryEngineStore


class ZeroKylinScorer:
    backend_id = "openkylin_text_embedding_sdk_test_double"

    def score(self, query, memories):
        return {memory.memory_id: 0.0 for memory in memories}


class SparseProjectionSmokeTest(unittest.TestCase):
    def test_index_can_upsert_search_and_remove(self):
        index = SparseProjectionIndex(
            SparseProjectionSettings(
                bucket_count=64,
                repeats=3,
                candidate_k=2,
            )
        )
        index.upsert("memory-usd", text_features("quotation default USD"))
        index.upsert("memory-chart", text_features("sales chart"))

        result = index.search(text_features("quotation USD"), top_k=2)

        self.assertTrue(result)
        self.assertIn("memory-usd", {item[0] for item in result})
        index.remove("memory-usd")
        self.assertNotIn(
            "memory-usd",
            {item[0] for item in index.search(text_features("quotation USD"))},
        )

    def test_same_seed_is_deterministic(self):
        settings = SparseProjectionSettings(bucket_count=32, repeats=3)
        left = SparseProjectionIndex(settings)
        right = SparseProjectionIndex(settings)
        for index in (left, right):
            index.upsert("a", text_features("alpha beta"))
            index.upsert("b", text_features("gamma delta"))

        self.assertEqual(
            left.search(text_features("alpha")),
            right.search(text_features("alpha")),
        )

    def test_enabled_switch_runs_through_retrieval_without_replacing_old_api(self):
        with TemporaryDirectory() as directory:
            base_config = StrictMemoryEngineConfig.load(
                database_path=Path(directory) / "strict.db"
            )
            retrieval = {
                **base_config.retrieval,
                "sparse_projection_enabled": True,
                "sparse_projection_candidate_k": 5,
            }
            config = replace(base_config, retrieval=retrieval)
            store = StrictMemoryEngineStore(config.database_path)
            engine = StrictMemoryEngine(
                config=config,
                store=store,
                semantic_scorer=ZeroKylinScorer(),
            )
            engine.ingest_observation(
                {
                    "source_type": "dialogue",
                    "source_event_id": "sparse-switch-1",
                    "user_id": "U001",
                    "session_id": "S001",
                    "event_time": datetime(
                        2026, 7, 1, 10, tzinfo=timezone.utc
                    ).isoformat(),
                    "actor": "user",
                    "content": "以后默认使用 USD。",
                    "task": "quotation reply",
                },
                stage_limit="lifecycle",
            )

            result = engine.retrieve(
                "以后默认使用 USD",
                {
                    "user_id": "U001",
                    "query_time": "2026-07-02T10:00:00+00:00",
                },
            )

            trace = result["trace"]["sparse_projection"]
            self.assertTrue(trace["enabled"])
            self.assertTrue(trace["used"])
