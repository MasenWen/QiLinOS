from __future__ import annotations

import argparse
import json
import statistics
import time
from pathlib import Path

from src.memory_engine.knowledge_tags import WorkplaceTagKnowledgeBase
from src.memory_engine.observation import ObservationMatcher
from src.memory_engine.span_matching import JiebaSpanTokenizer
from src.rag.kylin_embedding_sdk import KylinTextEmbedding


CASES = (
    {
        "text": "以后在Excel里整理预算表时优先使用折线图",
        "condition": {"app:spreadsheet"},
        "object": {"chart:line"},
    },
    {
        "text": "网络不稳定时优先用OpenVPN连接服务器",
        "condition": {"condition:network_unstable"},
        "object": {"app:openvpn", "system:vpn"},
    },
    {
        "text": "发送报价邮件前先让我确认",
        "condition": {"task:email"},
        "object": {"action:confirm_before_send"},
    },
    {
        "text": "做代码解释时优先使用ChatGPT Codex",
        "condition": {
            "task:code_explanation",
            "action:code_explanation",
            "condition:coding_work",
        },
        "object": {"app:chatgpt_codex"},
    },
    {
        "text": "研究论文时尽量用Zotero管理参考文献",
        "condition": {"condition:research_work", "task:paper_search"},
        "object": {"app:zotero", "artifact:citation"},
    },
    {
        "text": "在GitHub做代码审查时优先检查测试结果",
        "condition": {"app:github", "artifact:pull_request"},
        "object": {"action:testing", "action:code_review"},
    },
)


def _frame_rows(result) -> list[dict]:
    return [
        {
            "condition": frame.condition.tag_id if frame.condition else None,
            "object": frame.object.tag_id,
            "attitude": frame.attitude.value,
            "temporal": frame.temporal.label if frame.temporal else None,
            "confidence": frame.confidence,
        }
        for frame in result.frames
    ]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--database",
        default="runtime/knowledge/workplace_tags_v1.sqlite",
    )
    parser.add_argument(
        "--output",
        default="runtime/results/knowledge_augmented_observation_v1.json",
    )
    args = parser.parse_args()

    knowledge_started = time.perf_counter()
    knowledge = WorkplaceTagKnowledgeBase(args.database)
    knowledge_open_ms = (time.perf_counter() - knowledge_started) * 1000.0
    matcher_started = time.perf_counter()
    matcher = ObservationMatcher(
        KylinTextEmbedding(),
        tokenizer=JiebaSpanTokenizer(),
        knowledge_base=knowledge,
        knowledge_top_k_per_group=12,
    )
    matcher_initialization_ms = (time.perf_counter() - matcher_started) * 1000.0

    passes = []
    for pass_name in ("first", "warm"):
        rows = []
        for case in CASES:
            knowledge_query_started = time.perf_counter()
            candidates = knowledge.query(case["text"])
            knowledge_query_ms = (
                time.perf_counter() - knowledge_query_started
            ) * 1000.0
            observation_started = time.perf_counter()
            result = matcher.match(case["text"])
            observation_ms = (
                time.perf_counter() - observation_started
            ) * 1000.0
            frames = _frame_rows(result)
            correct = any(
                frame["condition"] in case["condition"]
                and frame["object"] in case["object"]
                for frame in frames
            )
            rows.append(
                {
                    "text": case["text"],
                    "expected_condition": sorted(case["condition"]),
                    "expected_object": sorted(case["object"]),
                    "knowledge_query_ms": knowledge_query_ms,
                    "observation_ms": observation_ms,
                    "candidate_tag_ids": [value.tag_id for value in candidates],
                    "frames": frames,
                    "correct": correct,
                }
            )
        passes.append(
            {
                "name": pass_name,
                "correct": sum(row["correct"] for row in rows),
                "total": len(rows),
                "knowledge_mean_ms": statistics.fmean(
                    row["knowledge_query_ms"] for row in rows
                ),
                "observation_mean_ms": statistics.fmean(
                    row["observation_ms"] for row in rows
                ),
                "rows": rows,
            }
        )

    report = {
        "knowledge": knowledge.statistics(),
        "knowledge_open_ms": knowledge_open_ms,
        "matcher_initialization_ms": matcher_initialization_ms,
        "passes": passes,
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
