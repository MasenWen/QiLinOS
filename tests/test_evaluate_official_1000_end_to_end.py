from __future__ import annotations

import json

from tools.evaluate_official_1000_end_to_end import (
    EpisodeHybridRetriever,
    PersistentEvaluationStore,
    _dialogue_memory,
    _operation_memory,
    build_api_input,
    form_memories,
    retrieval_summary,
)


class _WhitespaceTokenizer:
    def tokenize(self, text: str) -> tuple[str, ...]:
        return tuple(text.casefold().split())

    def identifiers(self, text: str) -> tuple[str, ...]:
        return ()


class _FailingEmbedder:
    def embed(self, texts):
        raise AssertionError("cached Observation vector should be reused")


def test_episode_memories_preserve_evidence_and_structured_content() -> None:
    dialogue = _dialogue_memory(
        "D1",
        [
            {
                "event_id": "DE2",
                "episode_id": "D1",
                "event_time": "2026-01-01T10:01:00",
                "source_event_index": 2,
                "message_text": "数字要写清单位",
                "context_task": "准备出差计划",
                "context_artifact": "出差安排.md",
                "context_topic": "航班和酒店",
                "windows_app_id": "assistant_chat",
                "referenced_app_ids": ["calendar_app"],
                "memory_signal_type": "output_style_preference",
            },
            {
                "event_id": "DE1",
                "episode_id": "D1",
                "event_time": "2026-01-01T10:00:00",
                "source_event_index": 1,
                "message_text": "先写一句结论",
                "context_task": "准备出差计划",
                "context_artifact": "出差安排.md",
                "context_topic": "航班和酒店",
                "windows_app_id": "assistant_chat",
                "referenced_app_ids": ["calendar_app"],
                "memory_signal_type": "output_style_preference",
            },
        ],
    )
    operation = _operation_memory(
        "O1",
        [
            {
                "event_id": "OE1",
                "episode_id": "O1",
                "event_time": "2026-01-01T11:00:00",
                "source_event_index": 1,
                "windows_app_id": "web_browser",
                "action_key": "open_url",
                "target_type": "url",
                "target_value": "https://example.test",
                "result_status": "success",
                "context_text": "恢复网页任务",
            }
        ],
    )

    assert dialogue["evidence_ids"] == ["DE1", "DE2"]
    assert dialogue["memory_summary"].startswith("先写一句结论")
    assert "出差安排.md" in dialogue["constraints"]
    assert operation["evidence_ids"] == ["OE1"]
    assert "open_url" in operation["expected_action"]
    assert "https://example.test" in operation["constraints"]


def test_form_memories_maps_each_evidence_to_parent_episode() -> None:
    precedent = [
        {
            "evidence_ids": ["DE1", "OE1"],
            "legacy_memory_records": [],
            "legacy_source_events": [],
            "dialogue_events": [
                {
                    "event_id": "DE1",
                    "episode_id": "D1",
                    "event_time": "2026-01-01T10:00:00",
                    "message_text": "使用简洁格式",
                }
            ],
            "operation_events": [
                {
                    "event_id": "OE1",
                    "episode_id": "O1",
                    "event_time": "2026-01-01T11:00:00",
                    "action_key": "open_file",
                    "target_value": "report.docx",
                }
            ],
        }
    ]
    memories, mapping, report = form_memories(precedent)

    assert len(memories) == 2
    assert mapping == {
        "DE1": "DIALOGUE_MEMORY::D1",
        "OE1": "OPERATION_MEMORY::O1",
    }
    assert report["evidence_coverage"] == 1.0
    assert report["evidence_collision_count"] == 0


def test_retrieval_summary_separates_recall_and_completeness() -> None:
    rows = [
        {
            "dataset_origin": "v5.3",
            "required_memory_ids": ["M1", "M2"],
            "forbidden_memory_ids": ["M9"],
            "ranked_memory_ids": ["M1", "M9", "M3", "M4", "M5", "M2"],
            "query_observation": {"formed": True, "budget_exhausted": False},
            "retrieval_diagnostics": {"fast_path": False},
            "stages_ms": {
                "observation": 1.0,
                "knowledge": 2.0,
                "retrieval": 3.0,
                "total": 6.0,
            },
        }
    ]
    summary = retrieval_summary(rows)

    assert summary["recall_at_5"]["required_memory_recall"] == 0.5
    assert summary["recall_at_5"]["all_required_query_success_rate"] == 0.0
    assert summary["recall_at_8"]["required_memory_recall"] == 1.0
    assert summary["recall_at_5"]["forbidden_memory_query_rate"] == 1.0


def test_api_packet_contains_runtime_evidence_but_not_answer_key() -> None:
    row = {
        "query_text": "继续刚才的任务",
        "current_context_text": "当前打开 report.docx",
        "query_observation": {"formed": True, "frames": []},
        "retrieved_memories": [{"summary": "在文档中继续修改标题"}],
        "knowledge_references": [{"name": "Word Processor"}],
    }
    packet = build_api_input(row)
    payload = packet.split("\n\n", 1)[1]

    assert json.loads(payload)["user_input"] == "继续刚才的任务"
    assert "expected_conclusion" not in packet
    assert "scoring_rubric" not in packet


def test_persistent_store_resumes_queries_and_vectors(tmp_path) -> None:
    path = tmp_path / "state.sqlite"
    store = PersistentEvaluationStore(path, dataset_fingerprint="fixed")
    memory = {
        "memory_id": "M1",
        "memory_kind": "legacy_memory",
        "episode_id": "E1",
        "memory_summary": "summary",
        "expected_action": "action",
        "constraints": "",
        "condition": "{}",
        "semantic_value": "{}",
        "evidence_ids": ["EV1"],
        "source_event_count": 1,
        "source_text": "source",
    }
    store.upsert_seed_memory(memory, [0.25, 0.75])
    store.commit_query(
        sequence_no=1,
        query_id="Q1",
        observation={"formed": False},
        result={"query_id": "Q1", "sequence_no": 1},
        promoted_memory=None,
        promoted_vector=None,
    )
    store.close()

    resumed = PersistentEvaluationStore(path, dataset_fingerprint="fixed")
    memories, vectors = resumed.load_memories()
    assert memories[0]["memory_id"] == "M1"
    assert vectors["M1"] == (0.25, 0.75)
    assert resumed.processed_sequence_numbers() == {1}
    assert resumed.query_results() == [{"query_id": "Q1", "sequence_no": 1}]
    resumed.close()


def test_retriever_reuses_observation_vector_without_embedding() -> None:
    memory = {
        "memory_id": "M1",
        "memory_kind": "dialogue_memory",
        "episode_id": "E1",
        "memory_summary": "edit report",
        "expected_action": "edit",
        "constraints": "report.docx",
        "condition": "{}",
        "semantic_value": "{}",
        "evidence_ids": ["EV1"],
        "source_event_count": 1,
        "source_text": "edit report",
    }
    retriever = EpisodeHybridRetriever(
        [memory],
        tokenizer=_WhitespaceTokenizer(),
        embedder=_FailingEmbedder(),
        vectors_by_memory={"M1": [1.0, 0.0]},
    )

    ranked, diagnostics, query_vector = retriever.rank(
        "edit report",
        "edit report document editor",
        query_vector=[1.0, 0.0],
    )

    assert [candidate.memory_id for candidate in ranked] == ["M1"]
    assert query_vector == [1.0, 0.0]
    assert diagnostics["reused_observation_vector"] is True
