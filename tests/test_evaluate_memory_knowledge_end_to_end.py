from __future__ import annotations

from tools.evaluate_memory_knowledge_end_to_end import (
    _scenario_description,
    build_api_input,
    render_markdown,
    select_examples,
)


def _query(query_id: str, track: str, kind: str, group: str) -> dict[str, str]:
    return {
        "query_id": query_id,
        "answer_group_id": group,
        "evaluation_track": track,
        "query_type": kind,
        "query_text": f"query {query_id}",
        "current_context_ids": "ctx",
    }


def _row(query_id: str, track: str, kind: str, success: bool = True) -> dict:
    return {
        "query_id": query_id,
        "evaluation_track": track,
        "query_type": kind,
        "required_memory_ids": ["m1"] if track != "clarification_required" else [],
        "selected_memory_ids": ["m1"] if success else [],
        "response": {"memories": [], "conflict_companions": []},
    }


def test_api_input_separates_memories_and_knowledge() -> None:
    query = _query("q1", "single_memory", "low_overlap_paraphrase", "g1")
    row = _row("q1", "single_memory", "low_overlap_paraphrase")
    contexts = {
        "ctx": {
            "active_app": "calc",
            "active_document": "budget.xlsx",
            "visible_hint": "budget.xlsx is open",
        }
    }
    packet = build_api_input(
        query,
        row,
        contexts,
        [{"tag_id": "app:spreadsheet", "name": "Spreadsheet"}],
    )
    assert '"retrieved_memories"' in packet
    assert '"knowledge_references"' in packet
    assert '"user_input": "query q1"' in packet


def test_selector_keeps_tracks_distinct() -> None:
    rows = [
        _row("q1", "single_memory", "low_overlap_paraphrase"),
        _row("q2", "complementary_multi_memory", "human_goal_oriented"),
        _row("q3", "conflict_resolution", "human_constraint_emphasis"),
        _row("q4", "clarification_required", "contextual_ellipsis", False),
        _row("q5", "single_memory", "contextual_ellipsis"),
    ]
    queries = {
        row["query_id"]: _query(
            row["query_id"],
            row["evaluation_track"],
            row["query_type"],
            f"group-{row['query_id']}",
        )
        for row in rows
    }
    selected = select_examples(rows, queries, 5)
    assert len(selected) == 5
    assert {row["evaluation_track"] for row in selected} >= {
        "single_memory",
        "complementary_multi_memory",
        "conflict_resolution",
        "clarification_required",
    }


def test_markdown_records_posthoc_scene_and_exact_api_input() -> None:
    query = _query("q1", "single_memory", "low_overlap_paraphrase", "g1")
    row = _row("q1", "single_memory", "low_overlap_paraphrase")
    contexts = {
        "ctx": {
            "active_app": "calc",
            "active_document": "budget.xlsx",
            "visible_hint": "budget.xlsx is open",
        }
    }
    description = _scenario_description(query, contexts, row)
    markdown = render_markdown(
        [
            {
                "evaluation_track": "single_memory",
                "query_type": "low_overlap_paraphrase",
                "scenario_description": description,
                "user_input": query["query_text"],
                "api_input": "EXACT PACKET",
                "api_answer": "ANSWER",
                "judge": {"decision_correct": True},
            }
        ],
        {"ok": True},
    )
    assert "场景描述（运行后补充）" in markdown
    assert "EXACT PACKET" in markdown
    assert "ANSWER" in markdown
