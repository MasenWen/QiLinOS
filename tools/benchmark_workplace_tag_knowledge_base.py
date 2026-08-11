from __future__ import annotations

import argparse
import json
import statistics
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from src.memory_engine.knowledge_tags import WorkplaceTagKnowledgeBase


def _percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    index = min(len(ordered) - 1, round((len(ordered) - 1) * percentile))
    return ordered[index]


def _texts() -> list[str]:
    values = []
    for path in (
        Path("tests/data/observation_formation_small_v1.json"),
        Path("tests/data/os_agent_observation_benchmark_v31.json"),
    ):
        payload = json.loads(path.read_text(encoding="utf-8"))
        rows = list(payload.get("cases", ()))
        for split_rows in payload.get("splits", {}).values():
            rows.extend(split_rows)
        for row in rows:
            text = row.get("text") or row.get("query") or row.get("content")
            if text:
                values.append(text)
    if not values:
        values = [
            "在Excel里整理预算表并导出PDF",
            "使用Codex解释这段Python代码",
            "网络不稳定时改用OpenVPN连接服务器",
            "发送报价邮件前先让我确认",
        ]
    return values


def _measure_query(
    knowledge: WorkplaceTagKnowledgeBase,
    text: str,
) -> tuple[float, int]:
    started = time.perf_counter()
    result = knowledge.query(text)
    return (time.perf_counter() - started) * 1000.0, len(result)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--database",
        default="runtime/knowledge/workplace_tags_v1.sqlite",
    )
    parser.add_argument("--repeats", type=int, default=10)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--output")
    args = parser.parse_args()

    opened = time.perf_counter()
    knowledge = WorkplaceTagKnowledgeBase(args.database)
    open_ms = (time.perf_counter() - opened) * 1000.0
    source_texts = _texts()
    texts = (source_texts * args.repeats)[: max(len(source_texts), 1000)]

    warmup = [_measure_query(knowledge, text) for text in source_texts[:20]]
    sequential = [_measure_query(knowledge, text) for text in texts]
    parallel_started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        parallel = list(executor.map(lambda text: _measure_query(knowledge, text), texts))
    parallel_wall_ms = (time.perf_counter() - parallel_started) * 1000.0

    sequential_ms = [value[0] for value in sequential]
    parallel_ms = [value[0] for value in parallel]
    report = {
        "knowledge": knowledge.statistics(),
        "cold_open_ms": open_ms,
        "query_count": len(texts),
        "warmup_mean_ms": statistics.fmean(value[0] for value in warmup),
        "sequential": {
            "mean_ms": statistics.fmean(sequential_ms),
            "p50_ms": _percentile(sequential_ms, 0.50),
            "p95_ms": _percentile(sequential_ms, 0.95),
            "p99_ms": _percentile(sequential_ms, 0.99),
            "mean_candidate_count": statistics.fmean(value[1] for value in sequential),
        },
        "parallel": {
            "workers": args.workers,
            "wall_ms": parallel_wall_ms,
            "throughput_qps": len(texts) / max(1e-9, parallel_wall_ms / 1000.0),
            "mean_ms": statistics.fmean(parallel_ms),
            "p50_ms": _percentile(parallel_ms, 0.50),
            "p95_ms": _percentile(parallel_ms, 0.95),
            "p99_ms": _percentile(parallel_ms, 0.99),
        },
    }
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    print(rendered)
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
