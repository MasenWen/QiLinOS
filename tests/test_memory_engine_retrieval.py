from __future__ import annotations

import unittest
from tempfile import TemporaryDirectory
from pathlib import Path

from src.memory_engine.engine import MemoryEngine
from src.memory_engine.store import MemoryEngineStore


class MemoryEngineRetrievalTest(unittest.TestCase):
    def test_structured_activation_promotes_matching_memory_class(self):
        items = [
            {
                "id": "routine",
                "memory": "User often saves research links.",
                "score": 0.95,
                "metadata": {
                    "memory_category": "frequency_preference",
                    "memory_type": "mid_term",
                    "scene": "browser_research",
                    "app": "browser",
                    "status": "active",
                },
            },
            {
                "id": "page",
                "memory": "User just opened the Kylin SDK documentation.",
                "score": 0.70,
                "metadata": {
                    "memory_category": "current_context",
                    "memory_type": "short_term",
                    "scene": "browser_research",
                    "app": "browser",
                    "status": "active",
                },
            },
        ]

        engine = MemoryEngine(lambda _q, _u, _k: items)
        response = engine.retrieve(
            "需要恢复最后查看的参考页面和最近上下文",
            context={
                "user_id": "U001",
                "scene": "browser_research",
                "app": "browser",
                "memory_need": "最近工作对象的短期上下文",
            },
            top_k=2,
        )

        self.assertEqual("page", response.items[0]["id"])
        self.assertEqual("current_context", response.trace["inferred"]["memory_category"])

    def test_future_memory_is_filtered(self):
        items = [
            {
                "id": "future",
                "memory": "A future task state.",
                "score": 0.99,
                "metadata": {"status": "active", "start_time": "2026-07-08 10:00:00"},
            },
            {
                "id": "current",
                "memory": "The current task state.",
                "score": 0.80,
                "metadata": {"status": "active", "start_time": "2026-07-07 10:00:00"},
            },
        ]
        engine = MemoryEngine(lambda _q, _u, _k: items)

        response = engine.retrieve(
            "continue task",
            context={"user_id": "U001", "query_time": "2026-07-07 10:05:00"},
        )

        self.assertEqual(["current"], [item["id"] for item in response.items])
        self.assertEqual("future_memory", response.trace["rejected"][0]["reason"])

    def test_task_type_keeps_os_agent_task_on_top(self):
        items = [
            {
                "id": "chart",
                "memory": "Use Calc to create a chart.",
                "score": 0.92,
                "metadata": {
                    "scene": "office_automation_spreadsheet",
                    "app": "libreoffice_calc",
                    "task_type": "chart_creation",
                },
            },
            {
                "id": "fill",
                "memory": "Fill blank spreadsheet cells with the value above.",
                "score": 0.88,
                "metadata": {
                    "scene": "office_automation_spreadsheet",
                    "app": "libreoffice_calc",
                    "task_type": "spreadsheet_data_fill",
                },
            },
        ]
        engine = MemoryEngine(lambda _q, _u, _k: items)

        response = engine.retrieve(
            "Fill all blank cells with the value above",
            context={
                "user_id": "os_agent_tasks",
                "scene": "office_automation_spreadsheet",
                "app": "libreoffice_calc",
                "task_type": "spreadsheet_data_fill",
            },
        )

        self.assertEqual("fill", response.items[0]["id"])


class _FakeMemory:
    def __init__(self):
        self.calls = []
        self.deleted = []

    def add(self, content, **kwargs):
        self.calls.append((content, kwargs))
        return {"results": [{"id": f"idx-{len(self.calls)}"}]}

    def delete(self, memory_id):
        self.deleted.append(memory_id)


class _FakeMem0Store:
    def __init__(self):
        self._memory = _FakeMemory()


class MemoryEngineLineageTest(unittest.TestCase):
    def test_engine_boundary_rejects_secret_before_lineage_or_index(self):
        with TemporaryDirectory() as directory:
            store = MemoryEngineStore(Path(directory) / "engine.db")
            backend = _FakeMem0Store()
            result = MemoryEngine(store=store).remember_fact(
                "API key: sk-abcdefghijklmnopqrstuvwxyz123456",
                context={"user_id": "U001", "session_id": "S001", "source_event_id": "secret"},
                mem0_store_obj=backend,
            )

            self.assertEqual(result["status"], "skipped")
            self.assertIn("unsafe_content", result["reason"])
            self.assertEqual(0, store.counts()["observations"])
            self.assertEqual([], backend._memory.calls)

    def test_lineage_forgetting_deletes_only_matching_memory(self):
        with TemporaryDirectory() as directory:
            store = MemoryEngineStore(Path(directory) / "engine.db")
            backend = _FakeMem0Store()
            engine = MemoryEngine(store=store)
            engine.remember_fact(
                "用户的项目代号是蓝鲸",
                context={"user_id": "U001", "session_id": "S001", "source_event_id": "project-code"},
                mem0_store_obj=backend,
            )
            engine.remember_fact(
                "用户默认使用 USD 报价",
                context={"user_id": "U001", "session_id": "S001", "source_event_id": "currency"},
                mem0_store_obj=backend,
            )

            preview = engine.forget("蓝鲸", user_id="U001", dry_run=True, mem0_store_obj=backend)
            result = engine.forget("蓝鲸", user_id="U001", dry_run=False, mem0_store_obj=backend)

            self.assertEqual(1, len(preview["candidates"]))
            self.assertEqual(1, result["deleted"])
            self.assertEqual(["idx-1"], backend._memory.deleted)
            remaining = store.list_memories("U001")
            self.assertEqual(["用户默认使用 USD 报价"], [memory.semantic_value for memory in remaining])

    def test_external_send_confirmation_is_safety_strategy(self):
        with TemporaryDirectory() as directory:
            store = MemoryEngineStore(Path(directory) / "engine.db")
            engine = MemoryEngine(store=store)
            engine.remember_fact(
                "发送外部邮件前必须经用户确认",
                context={"user_id": "U001", "session_id": "S001", "source_event_id": "event-safety"},
                index=False,
            )

            memory = store.list_memories("U001")[0]
            self.assertEqual("preference", memory.memory_family)
            self.assertEqual("safety_strategy", memory.memory_category)
            self.assertEqual("safety:external_send_confirmation", memory.slot_key)

    def test_reviewed_fact_writes_complete_idempotent_lineage(self):
        with TemporaryDirectory() as directory:
            store = MemoryEngineStore(Path(directory) / "engine.db")
            backend = _FakeMem0Store()
            engine = MemoryEngine(store=store)
            context = {
                "user_id": "U001",
                "session_id": "S001",
                "source_event_id": "event-001",
                "event_time": "2026-07-23T10:00:00+08:00",
            }

            first = engine.remember_fact(
                "用户偏好简洁回复",
                source_text="以后请简洁回复",
                context=context,
                mem0_store_obj=backend,
            )
            second = engine.remember_fact(
                "用户偏好简洁回复",
                source_text="以后请简洁回复",
                context=context,
                mem0_store_obj=backend,
            )

            self.assertEqual("CREATE", first["impact_action"])
            self.assertEqual("NOOP", second["impact_action"])
            self.assertEqual(
                {
                    "observations": 1,
                    "evidence": 1,
                    "impacts": 1,
                    "memories": 1,
                    "conflict_groups": 0,
                    "lifecycle_events": 0,
                    "index_refs": 1,
                    "engine_runs": 0,
                },
                store.counts(),
            )
            self.assertEqual(1, len(backend._memory.calls))

    def test_new_value_creates_dynamic_conflict_and_historical_predecessor(self):
        with TemporaryDirectory() as directory:
            store = MemoryEngineStore(Path(directory) / "engine.db")
            engine = MemoryEngine(store=store)
            engine.remember_fact(
                "用户默认使用折线图",
                context={"user_id": "U001", "session_id": "S001", "source_event_id": "chart-1"},
                index=False,
            )
            second = engine.remember_fact(
                "用户默认使用柱状图",
                context={"user_id": "U001", "session_id": "S002", "source_event_id": "chart-2"},
                index=False,
            )

            memories = store.list_slot_memories("U001", "preference:chart_type")
            by_value = {memory.semantic_value: memory for memory in memories}
            self.assertEqual("historical", by_value["用户默认使用折线图"].status)
            self.assertEqual("candidate", by_value["用户默认使用柱状图"].status)
            self.assertEqual(1, store.counts()["conflict_groups"])
            self.assertEqual(1, store.counts()["lifecycle_events"])
            self.assertEqual("CREATE", second["impact_action"])

    def test_independent_support_promotes_candidate_to_stable(self):
        with TemporaryDirectory() as directory:
            store = MemoryEngineStore(Path(directory) / "engine.db")
            backend = _FakeMem0Store()
            engine = MemoryEngine(store=store)
            for index in (1, 2):
                engine.remember_fact(
                    "用户默认使用 USD 报价",
                    source_text="报价默认 USD",
                    context={
                        "user_id": "U001",
                        "session_id": f"S00{index}",
                        "source_event_id": f"event-00{index}",
                        "event_time": f"2026-07-2{index}T10:00:00+08:00",
                    },
                    mem0_store_obj=backend,
                )

            memories = store.list_memories("U001")
            self.assertEqual(1, len(memories))
            self.assertEqual("stable", memories[0].status)
            self.assertEqual(2, memories[0].statistics["support_count"])
            self.assertEqual(2, store.counts()["evidence"])
            self.assertEqual(2, store.counts()["impacts"])
            self.assertEqual(1, len(backend._memory.calls))


if __name__ == "__main__":
    unittest.main()
