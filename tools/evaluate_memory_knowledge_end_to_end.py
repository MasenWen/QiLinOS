from __future__ import annotations

import argparse
import copy
import json
import statistics
import time
from pathlib import Path
from typing import Any, Mapping, Sequence

from src.memory_engine.knowledge_tags import WorkplaceTagKnowledgeBase
from src.memory_engine.observation import ObservationMatcher
from src.memory_engine.preference_matching import PreferenceObservationOptions
from src.memory_engine.reflection import DeepSeekReflectionClient
from src.memory_engine.span_matching import JiebaSpanTokenizer
from tools.evaluate_kylin_os_agent_observations_v31 import (
    _grade_case,
    _prediction,
    _summarize,
)
from tools.evaluate_online_retrieval_v1 import (
    DEFAULT_OBSERVATIONS,
    DEFAULT_SOURCE_ROOT,
    _quality_summary,
    _read_csv,
    _tag_maps,
    _tags,
    build_runtime,
    run_pass,
)


DEFAULT_DATABASE = Path("runtime/knowledge/workplace_tags_v1.sqlite")
DEFAULT_BASELINE = Path(
    "runtime/results/online_retrieval_v1/recall85_full_530_final.json"
)
DEFAULT_OUTPUT = Path(
    "runtime/results/memory_knowledge_end_to_end/end_to_end_v1.json"
)
DEFAULT_MARKDOWN = Path(
    "runtime/results/memory_knowledge_end_to_end/in-out.md"
)
ANSWER_SYSTEM = """# Memory-aware desktop agent

Answer the user in concise Chinese. Use current context first, then retrieved
memories. A memory is user-specific evidence. A knowledge reference is only a
general entity or task label and may help interpret wording; it is not evidence
that the user has a preference and must not override a memory. Conflict
companions are alternatives that require explicit disambiguation. If the
provided evidence is insufficient or the decision is ambiguous, ask one clear
question instead of guessing. Do not mention internal IDs or scores.

Return one JSON object with the single field `answer`.
"""
JUDGE_SYSTEM = """# Independent answer reviewer

Evaluate the answer only after it has been generated. Compare it with the gold
decision and rubric. Do not reward an answer merely for sounding plausible.
Return JSON with: `decision_correct` (boolean), `content_score_10` (number),
`groundedness_score_10` (number), `knowledge_helpful` (boolean), and `reason`
(short Chinese text).
"""


def _percentile(values: Sequence[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    low = int(position)
    high = min(low + 1, len(ordered) - 1)
    ratio = position - low
    return ordered[low] * (1.0 - ratio) + ordered[high] * ratio


def _latency(values: Sequence[float]) -> dict[str, float | int]:
    return {
        "count": len(values),
        "mean_ms": statistics.fmean(values) if values else 0.0,
        "p50_ms": _percentile(values, 0.50),
        "p95_ms": _percentile(values, 0.95),
        "p99_ms": _percentile(values, 0.99),
        "max_ms": max(values, default=0.0),
    }


def _options(case: Mapping[str, Any]) -> PreferenceObservationOptions:
    values = case["options"]
    return PreferenceObservationOptions(
        condition_tag_ids=tuple(values["condition_tag_ids"]),
        object_tag_ids=tuple(values["object_tag_ids"]),
        temporal_labels=tuple(values["temporal_labels"]),
    )


def form_memories(
    matcher: ObservationMatcher,
    dataset: Mapping[str, Any],
    memory_rows: Sequence[Mapping[str, str]],
) -> tuple[list[dict[str, Any]], list[Mapping[str, str]], dict[str, Any]]:
    """Form one lifecycle memory seed per source event without gold selection."""

    event_cases = {
        case["id"].removeprefix("event:"): case
        for case in dataset["cases"]
        if case["source_kind"] == "event"
    }
    predicted_dataset = copy.deepcopy(dataset)
    predicted_events = {
        case["id"].removeprefix("event:"): case
        for case in predicted_dataset["cases"]
        if case["source_kind"] == "event"
    }
    retained_rows: list[Mapping[str, str]] = []
    rows: list[dict[str, Any]] = []
    latencies = []

    for memory in memory_rows:
        task_id = memory["source_task_id"]
        case = event_cases[task_id]
        started = time.perf_counter()
        result = matcher.match(case["text"], options=_options(case))
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        latencies.append(elapsed_ms)
        predictions = [_prediction(frame) for frame in result.frames]
        grade = _grade_case(case["gold_observations"], predictions)
        selected = max(
            predictions,
            key=lambda value: (
                float(value["confidence"]),
                -int(value["source_start"]),
            ),
            default=None,
        )
        if selected is not None:
            predicted_events[task_id]["gold_observations"] = [
                {
                    "condition_tag_id": selected["condition_tag_id"],
                    "object_tag_id": selected["object_tag_id"],
                    "attitude_direction": selected["attitude_direction"],
                    "temporal_labels": (
                        [selected["temporal_label"]]
                        if selected["temporal_label"]
                        else []
                    ),
                }
            ]
            retained_rows.append(memory)
        rows.append(
            {
                "task_id": task_id,
                "source_text": case["text"],
                "memory_id": memory["memory_id"],
                "elapsed_ms": elapsed_ms,
                "predictions": predictions,
                "selected_for_memory": selected,
                "grade": grade,
            }
        )

    report = {
        "source_event_count": len(memory_rows),
        "formed_memory_count": len(retained_rows),
        "formed_memory_rate": (
            len(retained_rows) / len(memory_rows) if memory_rows else 1.0
        ),
        "quality": _summarize(rows),
        "latency": _latency(latencies),
        "selection_policy": (
            "highest-confidence extracted frame; no gold label used to select"
        ),
        "rows": rows,
    }
    return retained_rows, predicted_dataset, report


def _knowledge_refs(
    knowledge: WorkplaceTagKnowledgeBase,
    text: str,
    *,
    limit: int = 6,
) -> tuple[list[dict[str, Any]], float]:
    started = time.perf_counter()
    candidates = knowledge.query(text, top_k_per_group=4)
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    values = []
    for candidate in candidates[:limit]:
        tag = knowledge.by_id[candidate.tag_id]
        values.append(
            {
                "tag_id": candidate.tag_id,
                "name": candidate.name,
                "groups": list(candidate.groups),
                "pack_id": candidate.pack_id,
                "score": round(candidate.score, 6),
                "exact_alias": candidate.exact_alias,
                "matched_alias": candidate.matched_alias,
                "prototypes": list(tag.prototypes[:2]),
            }
        )
    return values, elapsed_ms


def _visible_context(
    query: Mapping[str, str],
    contexts: Mapping[str, Mapping[str, str]],
) -> list[dict[str, str]]:
    values = []
    for context_id in query["current_context_ids"].split("|"):
        if not context_id or context_id not in contexts:
            continue
        context = contexts[context_id]
        values.append(
            {
                "active_app": context["active_app"],
                "active_document": context["active_document"],
                "visible_hint": context["visible_hint"],
            }
        )
    return values


def build_api_input(
    query: Mapping[str, str],
    retrieval: Mapping[str, Any],
    contexts: Mapping[str, Mapping[str, str]],
    knowledge_refs: Sequence[Mapping[str, Any]],
) -> str:
    payload = {
        "current_context": _visible_context(query, contexts),
        "user_input": query["query_text"],
        "retrieved_memories": retrieval["response"]["memories"],
        "conflict_companions": retrieval["response"][
            "conflict_companions"
        ],
        "knowledge_references": list(knowledge_refs),
    }
    return (
        "Use the following retrieval packet to answer the user.\n\n"
        + json.dumps(payload, ensure_ascii=False, indent=2)
    )


def _successful(row: Mapping[str, Any]) -> bool:
    required = set(row["required_memory_ids"])
    return required <= set(row["selected_memory_ids"])


def select_examples(
    rows: Sequence[Mapping[str, Any]],
    queries: Mapping[str, Mapping[str, str]],
    count: int,
) -> list[Mapping[str, Any]]:
    specifications = (
        ("single_memory", "low_overlap_paraphrase", "success"),
        ("complementary_multi_memory", "human_goal_oriented", "success"),
        ("conflict_resolution", "human_constraint_emphasis", "success"),
        ("clarification_required", None, "abstain"),
        ("single_memory", "contextual_ellipsis", "success"),
        ("complementary_multi_memory", "low_overlap_paraphrase", "success"),
        ("single_memory", "human_context_explicit", "success"),
        ("complementary_multi_memory", None, "failure"),
    )
    selected = []
    answer_groups = set()
    for track, query_type, outcome in specifications:
        for row in rows:
            query = queries[row["query_id"]]
            if row.get("evaluation_track") != track:
                continue
            if query_type and row.get("query_type") != query_type:
                continue
            success = _successful(row)
            if outcome == "success" and not success:
                continue
            if outcome == "failure" and success:
                continue
            if outcome == "abstain" and row["selected_memory_ids"]:
                continue
            group = query["answer_group_id"]
            if group in answer_groups:
                continue
            selected.append(row)
            answer_groups.add(group)
            break
        if len(selected) >= count:
            break
    return selected[:count]


def _scenario_description(
    query: Mapping[str, str],
    contexts: Mapping[str, Mapping[str, str]],
    row: Mapping[str, Any],
) -> str:
    visible = _visible_context(query, contexts)
    target = "、".join(
        value["active_document"] for value in visible
    ) or "当前办公任务"
    labels = {
        "single_memory": "单条记忆恢复",
        "complementary_multi_memory": "多条互补记忆组合",
        "conflict_resolution": "冲突记忆辨析",
        "clarification_required": "信息不足时澄清",
    }
    outcome = "命中全部必需记忆" if _successful(row) else "未完整命中"
    return f"{labels.get(query['evaluation_track'], query['evaluation_track'])}；对象为{target}；{outcome}。"


def _judge_input(
    query: Mapping[str, str],
    answer: str,
    knowledge_refs: Sequence[Mapping[str, Any]],
) -> str:
    return json.dumps(
        {
            "query": query["query_text"],
            "decision_class": query["decision_class"],
            "expected_conclusion": query["expected_conclusion"],
            "scoring_rubric": query["scoring_rubric_text"],
            "answer": answer,
            "knowledge_references": list(knowledge_refs),
        },
        ensure_ascii=False,
        indent=2,
    )


def run_api_examples(
    rows: Sequence[Mapping[str, Any]],
    queries: Mapping[str, Mapping[str, str]],
    contexts: Mapping[str, Mapping[str, str]],
    knowledge: WorkplaceTagKnowledgeBase,
    *,
    client: DeepSeekReflectionClient,
) -> list[dict[str, Any]]:
    output = []
    for row in rows:
        query = queries[row["query_id"]]
        refs, knowledge_ms = _knowledge_refs(knowledge, query["query_text"])
        api_input = build_api_input(query, row, contexts, refs)
        response = client.complete_json(
            system_markdown=ANSWER_SYSTEM,
            user_markdown=api_input,
            task_name=f"end_to_end_answer:{row['query_id']}",
        )
        answer = str(response.get("answer") or "").strip()
        judge = client.complete_json(
            system_markdown=JUDGE_SYSTEM,
            user_markdown=_judge_input(query, answer, refs),
            task_name=f"end_to_end_judge:{row['query_id']}",
        )
        output.append(
            {
                "query_id": row["query_id"],
                "evaluation_track": query["evaluation_track"],
                "query_type": query["query_type"],
                "scenario_description": _scenario_description(
                    query, contexts, row
                ),
                "user_input": query["query_text"],
                "selected_memory_ids": row["selected_memory_ids"],
                "knowledge_references": refs,
                "knowledge_lookup_ms": knowledge_ms,
                "api_system": ANSWER_SYSTEM,
                "api_input": api_input,
                "api_answer": answer,
                "judge": judge,
            }
        )
    return output


def render_markdown(
    examples: Sequence[Mapping[str, Any]],
    summary: Mapping[str, Any],
) -> str:
    lines = [
        "# Memory + Knowledge End-to-End Examples",
        "",
        "本文件来自实际服务器运行。场景描述在API回答完成后补写，不属于模型输入。知识引用为当前标签知识库中的实体/任务提示，不等同于用户记忆。",
        "",
        "## Summary",
        "",
        "```json",
        json.dumps(summary, ensure_ascii=False, indent=2),
        "```",
    ]
    for index, example in enumerate(examples, 1):
        lines.extend(
            [
                "",
                f"## Example {index}: {example['evaluation_track']} / {example['query_type']}",
                "",
                "### 场景描述（运行后补充）",
                "",
                example["scenario_description"],
                "",
                "### 用户输入",
                "",
                example["user_input"],
                "",
                "### 最终发送给API的文本",
                "",
                "```text",
                example["api_input"],
                "```",
                "",
                "### API回答",
                "",
                example["api_answer"],
                "",
                "### 独立评审",
                "",
                "```json",
                json.dumps(example["judge"], ensure_ascii=False, indent=2),
                "```",
            ]
        )
    return "\n".join(lines) + "\n"


def _api_summary(examples: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    scores = [float(value["judge"]["content_score_10"]) for value in examples]
    grounded = [
        float(value["judge"]["groundedness_score_10"])
        for value in examples
    ]
    return {
        "example_count": len(examples),
        "decision_correct_count": sum(
            bool(value["judge"]["decision_correct"]) for value in examples
        ),
        "mean_content_score_10": statistics.fmean(scores) if scores else 0.0,
        "mean_groundedness_score_10": (
            statistics.fmean(grounded) if grounded else 0.0
        ),
        "knowledge_helpful_count": sum(
            bool(value["judge"]["knowledge_helpful"]) for value in examples
        ),
        "knowledge_lookup_latency": _latency(
            [float(value["knowledge_lookup_ms"]) for value in examples]
        ),
    }


def _retrieval_latency(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    return {
        "total": _latency(
            [float(value["stages_ms"]["total"]) for value in rows]
        ),
        "observation": _latency(
            [float(value["stages_ms"]["observation"]) for value in rows]
        ),
        "memory_query": _latency(
            [float(value["stages_ms"]["memory_query"]) for value in rows]
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--observations", type=Path, default=DEFAULT_OBSERVATIONS)
    parser.add_argument("--source-root", type=Path, default=DEFAULT_SOURCE_ROOT)
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--markdown", type=Path, default=DEFAULT_MARKDOWN)
    parser.add_argument("--sample-count", type=int, default=8)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--skip-api", action="store_true")
    args = parser.parse_args()

    from src.rag.kylin_embedding_sdk import KylinTextEmbedding

    dataset = json.loads(args.observations.read_text(encoding="utf-8"))
    data_root = args.source_root / "processed_data"
    query_rows = _read_csv(data_root / "query_set.csv")
    if args.limit is not None:
        query_rows = query_rows[: args.limit]
    queries = {value["query_id"]: value for value in query_rows}
    memories = _read_csv(data_root / "memory_records.csv")
    contexts = {
        value["context_id"]: value
        for value in _read_csv(data_root / "context_set.csv")
    }
    observation_cases = {
        case["id"].removeprefix("query:"): case
        for case in dataset["cases"]
        if case["source_kind"] == "query"
    }
    condition_by_document, _ = _tag_maps(dataset)
    knowledge = WorkplaceTagKnowledgeBase(args.database)

    initialized = time.perf_counter()
    matcher = ObservationMatcher(
        KylinTextEmbedding(),
        tokenizer=JiebaSpanTokenizer(),
        tags=_tags(dataset),
        knowledge_base=knowledge,
        knowledge_top_k_per_group=12,
        min_frame_confidence=0.82,
    )
    initialization_ms = (time.perf_counter() - initialized) * 1000.0

    formed_rows, predicted_dataset, formation = form_memories(
        matcher, dataset, memories
    )
    fixed_rows, _ = run_pass(
        pass_name="knowledge_augmented_fixed_memories",
        matcher=matcher,
        runtime_factory=lambda: build_runtime(memories, dataset),
        queries=query_rows,
        contexts=contexts,
        condition_by_document=condition_by_document,
        observation_cases=observation_cases,
    )
    linked_rows, linked_runtime = run_pass(
        pass_name="formed_memory_full_chain",
        matcher=matcher,
        runtime_factory=lambda: build_runtime(
            formed_rows, predicted_dataset
        ),
        queries=query_rows,
        contexts=contexts,
        condition_by_document=condition_by_document,
        observation_cases=observation_cases,
    )

    baseline = (
        json.loads(args.baseline.read_text(encoding="utf-8"))
        if args.baseline.is_file()
        else None
    )
    selected = select_examples(
        linked_rows, queries, min(10, max(5, args.sample_count))
    )
    client = None
    examples: list[dict[str, Any]] = []
    if not args.skip_api:
        client = DeepSeekReflectionClient(max_tokens=2500)
        examples = run_api_examples(
            selected,
            queries,
            contexts,
            knowledge,
            client=client,
        )

    fixed_quality = _quality_summary(fixed_rows)
    linked_quality = _quality_summary(linked_rows)
    summary = {
        "knowledge": knowledge.statistics(),
        "initialization_ms": initialization_ms,
        "memory_formation": {
            key: value for key, value in formation.items() if key != "rows"
        },
        "fixed_memory_knowledge_retrieval": fixed_quality,
        "fixed_memory_knowledge_latency": _retrieval_latency(fixed_rows),
        "formed_memory_full_chain_retrieval": linked_quality,
        "formed_memory_full_chain_latency": _retrieval_latency(linked_rows),
        "formed_runtime_memory_count": len(linked_runtime.memory_payloads),
        "baseline_without_knowledge": (
            baseline["cold"]["quality"] if baseline else None
        ),
        "api_examples": _api_summary(examples),
        "api_call_latency": _latency(
            [
                float(value["elapsed_ms"])
                for value in (client.calls if client else [])
                if value.get("status") == "ok"
            ]
        ),
    }
    output = {
        "purpose": (
            "Memory formation, Retrieval, memory plus local knowledge packet, "
            "and real API answer evaluation."
        ),
        "contract": {
            "answer_labels_used_for_retrieval_or_generation": False,
            "answer_labels_used_for_post_generation_judging": True,
            "knowledge_is_user_memory": False,
            "external_knowledge_api_used": False,
            "scene_description_added_after_api": True,
        },
        "summary": summary,
        "formation": formation,
        "fixed_memory_rows": fixed_rows,
        "linked_rows": linked_rows,
        "examples": examples,
        "api_calls": client.calls if client else [],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(output, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    args.markdown.parent.mkdir(parents=True, exist_ok=True)
    args.markdown.write_text(
        render_markdown(examples, summary), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
