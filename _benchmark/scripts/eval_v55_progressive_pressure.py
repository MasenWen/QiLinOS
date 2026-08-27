#!/usr/bin/env python3
"""Progressive v5.5 retrieval stress test with strictly nested memory pools.

The existing v5.5 rows describe the same base query at four pool sizes. This
runner rebuilds those pools so every higher pressure is a strict superset of
the previous one, then reports both query-level Hit@k and evidence-level
quality metrics. It evaluates the lexical retrieval core only; empty-query
results therefore describe ranker behavior, not the end-to-end abstention
policy.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import math
import random
import statistics
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.memory_engine.strict.retrieval import _bm25  # noqa: E402


DEFAULT_LEVELS = (100, 500, 2_000, 10_000)
DEFAULT_K_VALUES = (1, 3, 5)


def parse_int_list(value: str) -> tuple[int, ...]:
    values = tuple(int(item.strip()) for item in value.split(",") if item.strip())
    if not values or any(item <= 0 for item in values):
        raise argparse.ArgumentTypeError("expected positive comma-separated integers")
    if tuple(sorted(set(values))) != values:
        raise argparse.ArgumentTypeError("values must be unique and increasing")
    return values


def stable_number(*parts: object) -> int:
    payload = "\x1f".join(str(part) for part in parts).encode("utf-8")
    return int.from_bytes(hashlib.sha256(payload).digest()[:8], "big")


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def mean(values: list[float]) -> float:
    return statistics.fmean(values) if values else 0.0


def load_items(pool_path: Path) -> dict[str, str]:
    items: dict[str, str] = {}
    with gzip.open(pool_path, "rt", encoding="utf-8") as handle:
        for line in handle:
            record = json.loads(line)
            for item in record.get("items", []):
                memory_id = str(item.get("memory_id") or "").strip()
                if memory_id:
                    items[memory_id] = str(item.get("raw_text") or "")
    return items


def load_groups(answer_path: Path, items: dict[str, str]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    with answer_path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            grouped[row["stress_group_id"]].append(row)

    groups: list[dict[str, Any]] = []
    for group_id, rows in sorted(grouped.items()):
        queries = {row["current_query"] for row in rows}
        required_variants = {
            tuple(json.loads(row["required_memory_ids_json"])) for row in rows
        }
        if len(rows) != 4 or len(queries) != 1 or len(required_variants) != 1:
            raise ValueError(f"inconsistent stress group: {group_id}")
        required_raw = next(iter(required_variants))
        required = tuple(dict.fromkeys(mid for mid in required_raw if mid in items))
        missing = tuple(mid for mid in required_raw if mid not in items)
        groups.append(
            {
                "group_id": group_id,
                "base_query_id": rows[0]["base_query_id"],
                "query": next(iter(queries)),
                "required_ids": required,
                "missing_required_ids": missing,
            }
        )
    return groups


def nested_pool_ids(
    *,
    all_ids: tuple[str, ...],
    required_ids: tuple[str, ...],
    levels: tuple[int, ...],
    seed: int,
    group_id: str,
) -> list[tuple[str, ...]]:
    required_set = set(required_ids)
    if len(required_set) > levels[0]:
        raise ValueError(
            f"{group_id}: {len(required_set)} required memories exceed pressure 1 "
            f"pool size {levels[0]}"
        )
    distractors = [memory_id for memory_id in all_ids if memory_id not in required_set]
    random.Random(stable_number(seed, group_id, "distractors")).shuffle(distractors)
    pools: list[tuple[str, ...]] = []
    for size in levels:
        need = max(0, size - len(required_ids))
        members = tuple(required_ids) + tuple(distractors[:need])
        if len(members) != size:
            raise ValueError(f"{group_id}: cannot construct pool of size {size}")
        if pools and not set(pools[-1]).issubset(members):
            raise AssertionError(f"{group_id}: pressure pools are not nested")
        pools.append(members)
    return pools


def rank_pool(
    *,
    query: str,
    pool_ids: tuple[str, ...],
    items: dict[str, str],
    seed: int,
    group_id: str,
) -> tuple[list[str], float]:
    documents = {memory_id: items[memory_id] for memory_id in pool_ids}
    started = time.perf_counter()
    scores = _bm25(query, documents, k1=1.5, b=0.75)
    ranked = sorted(
        scores,
        key=lambda memory_id: (
            -scores[memory_id],
            stable_number(seed, group_id, "tie", memory_id),
        ),
    )
    latency_ms = (time.perf_counter() - started) * 1_000
    return ranked, latency_ms


def metrics_at_k(
    ranked: list[str], required_ids: tuple[str, ...], k: int
) -> dict[str, Any]:
    required = set(required_ids)
    returned = ranked[:k]
    true_positive = len(required.intersection(returned))
    if not required:
        return {
            "returned": len(returned),
            "true_positive": 0,
            "hit": None,
            "precision": None,
            "recall": None,
            "useful_slot_coverage": None,
            "perfect_selection": None,
            "abstained": not returned,
        }
    precision = true_positive / len(returned) if returned else 0.0
    recall = true_positive / len(required)
    useful_slots = true_positive / min(k, len(required))
    return {
        "returned": len(returned),
        "true_positive": true_positive,
        "hit": float(true_positive > 0),
        "precision": precision,
        "recall": recall,
        "useful_slot_coverage": useful_slots,
        "perfect_selection": float(
            precision == 1.0 and true_positive == min(k, len(required))
        ),
        "abstained": False,
    }


def aggregate_level(
    rows: list[dict[str, Any]],
    *,
    k_values: tuple[int, ...],
    baseline_by_group: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    answer_rows = [row for row in rows if row["required_count"] > 0]
    empty_rows = [row for row in rows if row["required_count"] == 0]
    result: dict[str, Any] = {
        "query_count": len(rows),
        "answer_query_count": len(answer_rows),
        "empty_query_count": len(empty_rows),
        "latency_ms": {
            "mean": mean([row["latency_ms"] for row in rows]),
            "p50": percentile([row["latency_ms"] for row in rows], 0.50),
            "p95": percentile([row["latency_ms"] for row in rows], 0.95),
            "p99": percentile([row["latency_ms"] for row in rows], 0.99),
        },
        "ranker_empty_query_abstention": mean(
            [float(row["by_k"][str(k_values[-1])]["abstained"]) for row in empty_rows]
        ),
        "by_k": {},
    }
    for k in k_values:
        key = str(k)
        values = [row["by_k"][key] for row in answer_rows]
        result["by_k"][key] = {
            "hit": mean([value["hit"] for value in values]),
            "selected_precision": mean([value["precision"] for value in values]),
            "evidence_recall": mean([value["recall"] for value in values]),
            "useful_slot_coverage": mean(
                [value["useful_slot_coverage"] for value in values]
            ),
            "perfect_selection": mean(
                [value["perfect_selection"] for value in values]
            ),
        }

    primary_k = str(k_values[-1])
    paired = []
    for row in answer_rows:
        baseline = baseline_by_group.get(row["group_id"])
        if baseline is None:
            continue
        current_metric = row["by_k"][primary_k]
        baseline_metric = baseline["by_k"][primary_k]
        current_top = set(row["top_ids"])
        baseline_top = set(baseline["top_ids"])
        paired.append(
            {
                "hit_lost": float(
                    baseline_metric["hit"] == 1.0 and current_metric["hit"] == 0.0
                ),
                "hit_gained": float(
                    baseline_metric["hit"] == 0.0 and current_metric["hit"] == 1.0
                ),
                "precision_delta": current_metric["precision"]
                - baseline_metric["precision"],
                "recall_delta": current_metric["recall"] - baseline_metric["recall"],
                "slot_delta": current_metric["useful_slot_coverage"]
                - baseline_metric["useful_slot_coverage"],
                "top_k_retention": len(current_top.intersection(baseline_top))
                / max(1, len(baseline_top)),
            }
        )
    result["deformation_vs_pressure_1"] = {
        "hit_lost_queries": int(sum(item["hit_lost"] for item in paired)),
        "hit_gained_queries": int(sum(item["hit_gained"] for item in paired)),
        "selected_precision_delta": mean(
            [item["precision_delta"] for item in paired]
        ),
        "evidence_recall_delta": mean([item["recall_delta"] for item in paired]),
        "useful_slot_coverage_delta": mean(
            [item["slot_delta"] for item in paired]
        ),
        "top_k_retention": mean([item["top_k_retention"] for item in paired]),
    }
    return result


def render_markdown(report: dict[str, Any]) -> str:
    metadata = report["metadata"]
    k = str(metadata["primary_k"])
    lines = [
        "# v5.5 BM25 递增压力检索测试",
        "",
        "同一查询在各级使用严格嵌套的记忆池。压力 N+1 完整包含压力 N，",
        "因此变化反映新增干扰记忆造成的退化，而不是不同随机样本造成的波动。",
        "",
        f"- 基础查询组：{metadata['group_count']}",
        f"- 有正确记忆的查询：{metadata['answer_group_count']}",
        f"- 无正确记忆的查询：{metadata['empty_group_count']}",
        f"- 全局记忆条目：{metadata['global_item_count']}",
        f"- 主返回上限：k={metadata['primary_k']}",
        "- 测试对象：BM25 词面检索核心（不是线上 Mem0 向量检索）",
        "",
        "## 分级结果",
        "",
        f"| 压力 | 记忆池 | 新增记忆 | Hit@{k} | Precision@{k} | Recall@{k} | Slot Coverage@{k} | Perfect@{k} | Hit 丢失 | Top-{k} 保留 | 平均延迟 | P95 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    previous_size = 0
    for level in report["levels"]:
        aggregate = level["aggregate"]
        metric = aggregate["by_k"][k]
        deformation = aggregate["deformation_vs_pressure_1"]
        size = level["pool_size"]
        lines.append(
            "| {label} | {size} | +{added} | {hit:.2%} | {precision:.2%} | "
            "{recall:.2%} | {slot:.2%} | {perfect:.2%} | {lost} | "
            "{retention:.2%} | {mean:.1f}ms | {p95:.1f}ms |".format(
                label=level["label"],
                size=size,
                added=size - previous_size,
                hit=metric["hit"],
                precision=metric["selected_precision"],
                recall=metric["evidence_recall"],
                slot=metric["useful_slot_coverage"],
                perfect=metric["perfect_selection"],
                lost=deformation["hit_lost_queries"],
                retention=deformation["top_k_retention"],
                mean=aggregate["latency_ms"]["mean"],
                p95=aggregate["latency_ms"]["p95"],
            )
        )
        previous_size = size

    lines.extend(
        [
            "",
            "## Hit 曲线",
            "",
            "| 压力 | "
            + " | ".join(f"Hit@{value}" for value in metadata["k_values"])
            + " |",
            "|---|" + "---:|" * len(metadata["k_values"]),
        ]
    )
    for level in report["levels"]:
        aggregate = level["aggregate"]
        values = " | ".join(
            f"{aggregate['by_k'][str(value)]['hit']:.2%}"
            for value in metadata["k_values"]
        )
        lines.append(f"| {level['label']} | {values} |")

    lines.extend(
        [
            "",
            "## 无答案查询",
            "",
            "| 压力 | 查询数 | 纯排序器空返回率 |",
            "|---|---:|---:|",
        ]
    )
    for level in report["levels"]:
        aggregate = level["aggregate"]
        lines.append(
            f"| {level['label']} | {aggregate['empty_query_count']} | "
            f"{aggregate['ranker_empty_query_abstention']:.2%} |"
        )

    lines.extend(
        [
            "",
            "## 口径说明",
            "",
            "- Hit@k：返回的 k 条拼接记忆中至少有一条 required memory。",
            "- Precision@k：返回记忆中 required memory 的比例。",
            "- Recall@k：找回的 required memory 占全部 required memory 的比例；保留其受 k 限制的真实低值。",
            "- Slot Coverage@k：命中数 / min(k, required 数)，衡量有限返回槽位是否得到有效利用。",
            "- Top-k 保留：相对压力 1，当前 Top-k 中仍保留的原结果比例。",
            "- 无 required 的查询单独统计。纯排序器没有拒答门槛，其结果不能替代完整系统的 abstention 测试。",
            "",
        ]
    )
    return "\n".join(lines)


def run(args: argparse.Namespace) -> dict[str, Any]:
    dataset_root = args.dataset_root.resolve()
    items = load_items(dataset_root / "pools" / "initial_memory_pools.ndjson.gz")
    groups = load_groups(dataset_root / "answer_key.csv", items)
    if args.max_groups:
        groups = groups[: args.max_groups]
    all_ids = tuple(items)
    details_by_level: list[list[dict[str, Any]]] = [list() for _ in args.levels]

    print(
        f"Loaded {len(items)} memories and {len(groups)} stress groups; "
        f"levels={args.levels}, k={args.k_values}",
        flush=True,
    )
    for index, group in enumerate(groups, start=1):
        pools = nested_pool_ids(
            all_ids=all_ids,
            required_ids=group["required_ids"],
            levels=args.levels,
            seed=args.seed,
            group_id=group["group_id"],
        )
        for level_index, pool_ids in enumerate(pools):
            ranked, latency_ms = rank_pool(
                query=group["query"],
                pool_ids=pool_ids,
                items=items,
                seed=args.seed,
                group_id=group["group_id"],
            )
            by_k = {
                str(k): metrics_at_k(ranked, group["required_ids"], k)
                for k in args.k_values
            }
            primary_k = args.k_values[-1]
            details_by_level[level_index].append(
                {
                    "group_id": group["group_id"],
                    "base_query_id": group["base_query_id"],
                    "required_count": len(group["required_ids"]),
                    "missing_required_count": len(group["missing_required_ids"]),
                    "latency_ms": latency_ms,
                    "top_ids": ranked[:primary_k],
                    "by_k": by_k,
                }
            )
        if index % 10 == 0 or index == len(groups):
            print(f"Processed {index}/{len(groups)} groups", flush=True)

    baseline_by_group = {
        row["group_id"]: row for row in details_by_level[0]
    }
    levels = []
    for index, (pool_size, rows) in enumerate(zip(args.levels, details_by_level)):
        levels.append(
            {
                "label": f"Pressure {index + 1}",
                "pool_size": pool_size,
                "aggregate": aggregate_level(
                    rows,
                    k_values=args.k_values,
                    baseline_by_group=baseline_by_group,
                ),
                "details": rows,
            }
        )

    answer_groups = [group for group in groups if group["required_ids"]]
    empty_groups = [group for group in groups if not group["required_ids"]]
    return {
        "metadata": {
            "dataset": "OS_Agent_v5.5 progressive memory-pool stress",
            "retriever": "src.memory_engine.strict.retrieval._bm25",
            "seed": args.seed,
            "levels": list(args.levels),
            "k_values": list(args.k_values),
            "primary_k": args.k_values[-1],
            "global_item_count": len(items),
            "group_count": len(groups),
            "answer_group_count": len(answer_groups),
            "empty_group_count": len(empty_groups),
            "required_count": {
                "mean": mean([len(group["required_ids"]) for group in answer_groups]),
                "median": statistics.median(
                    [len(group["required_ids"]) for group in answer_groups]
                )
                if answer_groups
                else 0.0,
                "max": max(
                    (len(group["required_ids"]) for group in answer_groups),
                    default=0,
                ),
            },
            "nested_pool_invariant": True,
            "tie_break": "sha256(seed, stress_group_id, memory_id)",
        },
        "levels": levels,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dataset-root",
        type=Path,
        default=REPO_ROOT / "_benchmark" / "test_subset_v55",
    )
    parser.add_argument("--levels", type=parse_int_list, default=DEFAULT_LEVELS)
    parser.add_argument("--k-values", type=parse_int_list, default=DEFAULT_K_VALUES)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--max-groups", type=int, default=0)
    parser.add_argument(
        "--output-json",
        type=Path,
        default=REPO_ROOT / "_benchmark" / "results" / "v55_progressive_pressure.json",
    )
    parser.add_argument(
        "--output-md",
        type=Path,
        default=REPO_ROOT / "_benchmark" / "results" / "v55_progressive_pressure.md",
    )
    args = parser.parse_args()
    report = run(args)
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_md.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    args.output_md.write_text(render_markdown(report), encoding="utf-8")
    print(f"JSON: {args.output_json}", flush=True)
    print(f"Markdown: {args.output_md}", flush=True)


if __name__ == "__main__":
    main()
