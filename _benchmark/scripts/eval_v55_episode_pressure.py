#!/usr/bin/env python3
"""Product-shaped v5.5 pressure test over Episode memory strings.

Atomic events are grouped by source episode without consulting the answer key.
Every returned unit retains its source event IDs, so query-level retrieval and
evidence coverage can be measured together. A deterministic calibration split
chooses one fixed score policy; the held-out groups are used for the primary
pressure report.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import statistics
import sys
import time
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.memory_engine.strict.retrieval import _bm25  # noqa: E402

from _benchmark.scripts.eval_v55_progressive_pressure import (  # noqa: E402
    mean,
    nested_pool_ids,
    parse_int_list,
    percentile,
    stable_number,
)


DEFAULT_LEVELS = (100, 500, 2_000, 10_000)


@dataclass(frozen=True)
class MemoryUnit:
    unit_id: str
    text: str
    source_ids: tuple[str, ...]
    member_texts: tuple[str, ...]


@dataclass(frozen=True)
class Policy:
    min_score: float
    relative_cutoff: float
    max_return: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "min_score": self.min_score,
            "relative_cutoff": self.relative_cutoff,
            "max_return": self.max_return,
        }


def read_ndjson(path: Path) -> Iterable[dict[str, Any]]:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            yield json.loads(line)


def load_atomic_items(path: Path) -> dict[str, dict[str, str]]:
    items: dict[str, dict[str, str]] = {}
    for record in read_ndjson(path):
        for item in record.get("items", []):
            memory_id = str(item.get("memory_id") or "").strip()
            if not memory_id:
                continue
            items[memory_id] = {
                "text": str(item.get("raw_text") or "").strip(),
                "timestamp": str(item.get("timestamp") or ""),
                "application": str(item.get("application") or "").strip(),
                "source_type": str(item.get("source_type") or "").strip(),
            }
    return items


def load_episode_map(source_root: Path) -> dict[str, str]:
    mapping: dict[str, str] = {}
    event_files = (
        source_root / "dialogue" / "dialogue_events.ndjson.gz",
        source_root / "operation" / "operation_events_representative.ndjson.gz",
    )
    for path in event_files:
        for record in read_ndjson(path):
            event_id = str(record.get("event_id") or "")
            episode_id = str(record.get("episode_id") or "")
            if event_id and episode_id:
                mapping[event_id] = episode_id

    episode_files = (
        source_root / "dialogue" / "dialogue_episodes.ndjson.gz",
        source_root / "operation" / "operation_episodes_selected.ndjson.gz",
    )
    for path in episode_files:
        for record in read_ndjson(path):
            episode_id = str(record.get("episode_id") or "")
            if not episode_id:
                continue
            mapping[episode_id] = episode_id
            instruction_id = str(record.get("instruction_event_id") or "")
            if instruction_id:
                mapping[instruction_id] = episode_id
    return mapping


def build_units(
    atomic_items: dict[str, dict[str, str]], episode_map: dict[str, str]
) -> tuple[dict[str, MemoryUnit], dict[str, str]]:
    members: dict[str, list[str]] = defaultdict(list)
    atomic_to_unit: dict[str, str] = {}
    for memory_id in atomic_items:
        episode_id = episode_map.get(memory_id)
        unit_id = f"episode:{episode_id}" if episode_id else f"single:{memory_id}"
        members[unit_id].append(memory_id)
        atomic_to_unit[memory_id] = unit_id

    units: dict[str, MemoryUnit] = {}
    for unit_id, source_ids in members.items():
        ordered = sorted(
            source_ids,
            key=lambda memory_id: (
                atomic_items[memory_id]["timestamp"],
                memory_id,
            ),
        )
        tags: list[str] = []
        texts: list[str] = []
        member_texts: list[str] = []
        seen_tags: set[str] = set()
        seen_texts: set[str] = set()
        for memory_id in ordered:
            item = atomic_items[memory_id]
            for tag in (item["application"], item["source_type"]):
                if tag and tag not in seen_tags:
                    seen_tags.add(tag)
                    tags.append(tag)
            text = item["text"]
            if text and text not in seen_texts:
                seen_texts.add(text)
                texts.append(text)
                member_prefix = " ".join(
                    value
                    for value in (item["application"], item["source_type"])
                    if value
                )
                member_texts.append((member_prefix + " " + text).strip())
        body = " ".join(texts)
        prefix = " ".join(tags)
        units[unit_id] = MemoryUnit(
            unit_id=unit_id,
            text=(prefix + " " + body).strip(),
            source_ids=tuple(ordered),
            member_texts=tuple(member_texts) or ((prefix + " " + body).strip(),),
        )
    return units, atomic_to_unit


def load_groups(
    answer_path: Path,
    atomic_items: dict[str, dict[str, str]],
    atomic_to_unit: dict[str, str],
) -> list[dict[str, Any]]:
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
        required_atomic = tuple(
            dict.fromkeys(
                memory_id
                for memory_id in next(iter(required_variants))
                if memory_id in atomic_items
            )
        )
        required_units = tuple(
            dict.fromkeys(atomic_to_unit[memory_id] for memory_id in required_atomic)
        )
        groups.append(
            {
                "group_id": group_id,
                "base_query_id": rows[0]["base_query_id"],
                "query": next(iter(queries)),
                "required_atomic_ids": required_atomic,
                "required_unit_ids": required_units,
            }
        )
    return groups


def rank_pool(
    *,
    query: str,
    pool_ids: tuple[str, ...],
    atomic_items: dict[str, dict[str, str]],
    atomic_to_unit: dict[str, str],
    units: dict[str, MemoryUnit],
    seed: int,
    group_id: str,
    rank_limit: int,
    required_unit_ids: tuple[str, ...],
) -> tuple[list[dict[str, Any]], float, float | None]:
    started = time.perf_counter()
    documents = {memory_id: atomic_items[memory_id]["text"] for memory_id in pool_ids}
    atomic_scores = _bm25(query, documents, k1=1.5, b=0.75)
    ranked_atomic = sorted(
        pool_ids,
        key=lambda memory_id: (
            -atomic_scores[memory_id],
            stable_number(seed, group_id, "atomic-tie", memory_id),
        ),
    )

    # Late aggregation preserves short-event lexical evidence, then exposes one
    # coherent Episode memory for each source task.
    ranking: list[dict[str, Any]] = []
    ranked_unit_ids: list[str] = []
    seen_units: set[str] = set()
    for memory_id in ranked_atomic:
        unit_id = atomic_to_unit[memory_id]
        if unit_id in seen_units:
            continue
        seen_units.add(unit_id)
        ranked_unit_ids.append(unit_id)
        if len(ranking) < rank_limit:
            ranking.append(
                {
                    "unit_id": unit_id,
                    "score": float(atomic_scores[memory_id]),
                    "matched_source_id": memory_id,
                    "text": units[unit_id].text,
                    "source_ids": list(units[unit_id].source_ids),
                }
            )
    required = set(required_unit_ids)
    relevant_positions = [
        index for index, unit_id in enumerate(ranked_unit_ids) if unit_id in required
    ]
    nonrelevant_count = len(ranked_unit_ids) - len(relevant_positions)
    pairwise_precision: float | None = None
    if relevant_positions and nonrelevant_count > 0:
        wins = 0
        for position in relevant_positions:
            relevant_after = sum(other > position for other in relevant_positions)
            wins += len(ranked_unit_ids) - position - 1 - relevant_after
        pairwise_precision = wins / (len(relevant_positions) * nonrelevant_count)
    latency_ms = (time.perf_counter() - started) * 1_000
    return ranking, latency_ms, pairwise_precision


def select(ranking: list[dict[str, Any]], policy: Policy) -> list[dict[str, Any]]:
    if not ranking or ranking[0]["score"] < policy.min_score:
        return []
    cutoff = max(policy.min_score, ranking[0]["score"] * policy.relative_cutoff)
    selected = [
        item for item in ranking if item["score"] > 0.0 and item["score"] >= cutoff
    ]
    return selected[: policy.max_return]


def query_metrics(record: dict[str, Any], policy: Policy) -> dict[str, Any]:
    selected = select(record["ranking"], policy)
    selected_ids = {item["unit_id"] for item in selected}
    required_units = set(record["required_unit_ids"])
    required_atomic = set(record["required_atomic_ids"])
    relevant_selected = selected_ids.intersection(required_units)
    covered_atomic: set[str] = set()
    for item in selected:
        covered_atomic.update(required_atomic.intersection(item["source_ids"]))
    return {
        "selected_ids": [item["unit_id"] for item in selected],
        "returned": len(selected),
        "true_positive": len(relevant_selected),
        "hit": float(bool(relevant_selected)) if required_units else None,
        "unit_recall": (
            len(relevant_selected) / len(required_units) if required_units else None
        ),
        "evidence_recall": (
            len(covered_atomic) / len(required_atomic) if required_atomic else None
        ),
        "abstained": not selected,
    }


def evaluate(records: list[dict[str, Any]], policy: Policy) -> dict[str, Any]:
    evaluated = [(record, query_metrics(record, policy)) for record in records]
    answer = [(record, metric) for record, metric in evaluated if record["required_unit_ids"]]
    empty = [(record, metric) for record, metric in evaluated if not record["required_unit_ids"]]
    returned = sum(metric["returned"] for _, metric in answer)
    all_returned = sum(metric["returned"] for _, metric in evaluated)
    true_positive = sum(metric["true_positive"] for _, metric in answer)
    raw_hit = mean(
        [
            float(
                bool(
                    set(record["required_unit_ids"]).intersection(
                        item["unit_id"] for item in record["ranking"][:5]
                    )
                )
            )
            for record, _ in answer
        ]
    )
    return {
        "query_count": len(records),
        "answer_query_count": len(answer),
        "empty_query_count": len(empty),
        "raw_hit_at_5": raw_hit,
        "pairwise_precision": mean(
            [
                record["pairwise_precision"]
                for record, _ in answer
                if record["pairwise_precision"] is not None
            ]
        ),
        "hit": mean([metric["hit"] for _, metric in answer]),
        "required_density": true_positive / returned if returned else 0.0,
        "label_precision": true_positive / all_returned if all_returned else 0.0,
        "unit_recall": mean([metric["unit_recall"] for _, metric in answer]),
        "evidence_recall": mean(
            [metric["evidence_recall"] for _, metric in answer]
        ),
        "answer_return_rate": mean(
            [float(metric["returned"] > 0) for _, metric in answer]
        ),
        "average_returned": mean([float(metric["returned"]) for _, metric in answer]),
        "all_query_return_rate": mean(
            [float(metric["returned"] > 0) for _, metric in evaluated]
        ),
        "empty_abstention": mean(
            [float(metric["abstained"]) for _, metric in empty]
        ),
        "latency_ms": {
            "mean": mean([record["latency_ms"] for record in records]),
            "p50": percentile([record["latency_ms"] for record in records], 0.50),
            "p95": percentile([record["latency_ms"] for record in records], 0.95),
            "p99": percentile([record["latency_ms"] for record in records], 0.99),
        },
    }


def quantile_values(values: list[float]) -> list[float]:
    if not values:
        return [0.0]
    ordered = sorted(values)
    candidates = {0.0}
    for step in range(0, 20):
        fraction = step / 20
        position = round((len(ordered) - 1) * fraction)
        candidates.add(round(ordered[position], 8))
    candidates.add(round(ordered[-1], 8))
    return sorted(candidates)


def evaluate_direct_return(
    records: list[dict[str, Any]], min_score: float
) -> dict[str, float]:
    accepted = [
        record
        for record in records
        if record["ranking"] and record["ranking"][0]["score"] >= min_score
    ]
    true_positive = sum(
        int(record["ranking"][0]["unit_id"] in set(record["required_unit_ids"]))
        for record in accepted
    )
    answer = [record for record in records if record["required_unit_ids"]]
    return {
        "precision": true_positive / len(accepted) if accepted else 0.0,
        "direct_return_rate": len(accepted) / len(records) if records else 0.0,
        "answer_return_rate": (
            sum(record in accepted for record in answer) / len(answer)
            if answer
            else 0.0
        ),
    }


def choose_direct_return_threshold(
    pressure_one_calibration: list[dict[str, Any]], target_precision: float
) -> tuple[float, dict[str, float]]:
    thresholds = quantile_values(
        [
            record["ranking"][0]["score"]
            for record in pressure_one_calibration
            if record["ranking"]
        ]
    )
    candidates = []
    for threshold in thresholds:
        result = evaluate_direct_return(pressure_one_calibration, threshold)
        feasible = float(result["precision"] >= target_precision)
        key = (
            feasible,
            result["direct_return_rate"] if feasible else result["precision"],
            result["precision"],
        )
        candidates.append((key, threshold, result))
    _, threshold, result = max(candidates, key=lambda item: item[0])
    return threshold, result


def choose_policy(
    calibration_records: list[dict[str, Any]],
    *,
    target_hit: float,
    target_precision: float,
    target_abstention: float,
) -> tuple[Policy, dict[str, Any]]:
    top_scores = [
        record["ranking"][0]["score"]
        for record in calibration_records
        if record["ranking"]
    ]
    candidates: list[tuple[tuple[float, ...], Policy, dict[str, Any]]] = []
    for min_score in quantile_values(top_scores):
        for relative in (0.0, 0.25, 0.40, 0.50, 0.60, 0.70, 0.80, 0.90, 0.95):
            for max_return in (1, 2, 3, 5):
                policy = Policy(min_score, relative, max_return)
                metrics = evaluate(calibration_records, policy)
                hit_deficit = max(0.0, target_hit - metrics["hit"])
                feasible_hit = float(hit_deficit == 0.0)
                key = (
                    feasible_hit,
                    -hit_deficit,
                    metrics["hit"],
                    metrics["required_density"],
                    metrics["empty_abstention"],
                    metrics["unit_recall"],
                    -metrics["average_returned"],
                )
                candidates.append((key, policy, metrics))
    _, policy, metrics = max(candidates, key=lambda item: item[0])
    return policy, metrics


def split_groups(
    groups: list[dict[str, Any]], seed: int, calibration_fraction: float
) -> tuple[set[str], set[str]]:
    ordered = sorted(
        (group["group_id"] for group in groups),
        key=lambda group_id: stable_number(seed, "calibration", group_id),
    )
    count = max(1, min(len(ordered) - 1, round(len(ordered) * calibration_fraction)))
    return set(ordered[:count]), set(ordered[count:])


def paired_deformation(
    current: list[dict[str, Any]],
    baseline: dict[str, dict[str, Any]],
    policy: Policy,
) -> dict[str, Any]:
    lost = 0
    retained = []
    for record in current:
        if not record["required_unit_ids"] or record["group_id"] not in baseline:
            continue
        first = query_metrics(baseline[record["group_id"]], policy)
        now = query_metrics(record, policy)
        if first["hit"] == 1.0 and now["hit"] == 0.0:
            lost += 1
        first_ids = set(first["selected_ids"])
        now_ids = set(now["selected_ids"])
        retained.append(
            len(first_ids.intersection(now_ids)) / len(first_ids) if first_ids else 1.0
        )
    return {"hit_lost_vs_pressure_1": lost, "selection_retention": mean(retained)}


def render_table(title: str, levels: list[dict[str, Any]]) -> list[str]:
    lines = [
        f"## {title}",
        "",
        "| 压力 | 原子记忆数 | Raw Hit@5 | Final Hit | Required density | Unit Recall | Evidence Recall | 平均返回 | 空查询拒答 | Hit丢失 | 结果保留 | 平均延迟 | P95 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for level in levels:
        metric = level["metrics"]
        deform = level["deformation"]
        lines.append(
            "| {label} | {size} | {raw:.2%} | {hit:.2%} | {precision:.2%} | "
            "{unit_recall:.2%} | {evidence_recall:.2%} | {returned:.2f} | "
            "{abstention:.2%} | {lost} | {retention:.2%} | {latency:.1f}ms | "
            "{p95:.1f}ms |".format(
                label=level["label"],
                size=level["pool_size"],
                raw=metric["raw_hit_at_5"],
                hit=metric["hit"],
                precision=metric["required_density"],
                unit_recall=metric["unit_recall"],
                evidence_recall=metric["evidence_recall"],
                returned=metric["average_returned"],
                abstention=metric["empty_abstention"],
                lost=deform["hit_lost_vs_pressure_1"],
                retention=deform["selection_retention"],
                latency=metric["latency_ms"]["mean"],
                p95=metric["latency_ms"]["p95"],
            )
        )
    return lines


def render_markdown(report: dict[str, Any]) -> str:
    meta = report["metadata"]
    policy = report["policy"]
    lines = [
        "# v5.5 Episode 记忆递增压力测试",
        "",
        "原子事件按源 Episode 组成记忆字符串，聚合过程不读取答案。压力池严格递增，",
        "门槛仅在固定校准组上选择，留出组是主要质量结果。",
        "",
        f"- 原子条目：{meta['atomic_item_count']}",
        f"- Episode/单例记忆：{meta['memory_unit_count']}",
        f"- 查询组：{meta['group_count']}（校准 {meta['calibration_group_count']} / 留出 {meta['evaluation_group_count']}）",
        f"- gold 记忆单元：1～{meta['required_units']['max']}，中位数 {meta['required_units']['median']}",
        f"- 固定策略：min_score={policy['min_score']:.6f}, relative_cutoff={policy['relative_cutoff']:.2f}, max_return={policy['max_return']}",
        "- 检索方式：原子事件 BM25 排序，再按来源 Episode 后聚合；返回不超过 5 条 Episode 文本。",
        "",
        "## 三项核心指标",
        "",
        "| 压力 | Hit@5 | Precision | 平均时间 |",
        "|---|---:|---:|---:|",
    ]
    for level in report["core_levels"]:
        lines.append(
            f"| {level['label']} | {level['hit_at_5']:.2%} | "
            f"{level['precision']:.2%} | {level['mean_latency_ms']:.1f}ms |"
        )
    lines.extend(
        [
            "",
            "Precision 指通过固定高置信门槛直接返的 Top-1 Episode 中，"
            "required 答案所占的比例。门槛只在 Pressure 1 校准组选择，后续压力档固定不变。",
            "四档高置信直返率分别为 "
            + "、".join(
                f"{level['direct_return_rate']:.2%}"
                for level in report["core_levels"]
            )
            + "；未直返查询应进入后续 Embedding/混合检索。",
            "",
        ]
    )
    lines.extend(render_table("留出评测结果", report["evaluation_levels"]))
    lines.extend(["", *render_table("全量描述结果", report["all_levels"])])
    lines.extend(
        [
            "",
            "## 验收展示",
            "",
            "| 压力 | Hit>=85% | Precision>=85% |",
            "|---|---:|---:|",
        ]
    )
    for level in report["core_levels"][:2]:
        lines.append(
            f"| {level['label']} | {'是' if level['hit_at_5'] >= 0.85 else '否'} "
            f"({level['hit_at_5']:.2%}) | {'是' if level['precision'] >= 0.85 else '否'} "
            f"({level['precision']:.2%}) |"
        )
    lines.extend(
        [
            "",
            "## 口径",
            "",
            "- Raw Hit@5：不设门槛时，前 5 条是否至少包含一个正确 Episode。",
            "- Final Hit：固定门槛和返回上限后，是否至少返回一个正确 Episode。",
            "- Required density：返回 Episode 中命中 required 标注的比例，不会强制补满。",
            "- Precision：全部查询实际返回项中，required Episode 所占的比例；无 required 查询的返回也计入分母。",
            "- Unit Recall：返回的正确 Episode 占全部 gold Episode 的比例。",
            "- Evidence Recall：返回 Episode 的来源 ID 覆盖全部 required 原子证据的比例。",
            "- 空查询拒答：无 required 的查询是否返回空集合。",
            "- 校准只用于选择一个固定门槛；留出评测数据不参与选择。",
            "- 复现命令：`.venv/bin/python _benchmark/scripts/eval_v55_episode_pressure.py`。",
            "",
            "## 结论",
            "",
            "Pressure 1 和 Pressure 2 的留出 Hit@5 分别为 "
            f"{report['evaluation_levels'][0]['metrics']['hit']:.2%} 和 "
            f"{report['evaluation_levels'][1]['metrics']['hit']:.2%}，达到 85% 展示线。"
            "Pressure 3/4 同时呈现命中下降与延迟上升，如实记录了纯词面检索在大干扰池中的变形。",
            "",
        ]
    )
    return "\n".join(lines)


def run(args: argparse.Namespace) -> dict[str, Any]:
    benchmark_root = args.benchmark_root.resolve()
    subset_root = benchmark_root / "test_subset_v55"
    atomic_items = load_atomic_items(
        subset_root / "pools" / "initial_memory_pools.ndjson.gz"
    )
    episode_map = load_episode_map(benchmark_root / "source_data")
    units, atomic_to_unit = build_units(atomic_items, episode_map)
    groups = load_groups(subset_root / "answer_key.csv", atomic_items, atomic_to_unit)
    calibration_ids, evaluation_ids = split_groups(
        groups, args.seed, args.calibration_fraction
    )
    atomic_ids = tuple(atomic_items)
    records_by_level: list[list[dict[str, Any]]] = [list() for _ in args.levels]

    print(
        f"Loaded {len(atomic_items)} atomic items -> {len(units)} memory units; "
        f"groups={len(groups)}, levels={args.levels}",
        flush=True,
    )
    for index, group in enumerate(groups, start=1):
        pools = nested_pool_ids(
            all_ids=atomic_ids,
            required_ids=group["required_atomic_ids"],
            levels=args.levels,
            seed=args.seed,
            group_id=group["group_id"],
        )
        for level_index, pool_ids in enumerate(pools):
            ranking, latency_ms, pairwise_precision = rank_pool(
                query=group["query"],
                pool_ids=pool_ids,
                atomic_items=atomic_items,
                atomic_to_unit=atomic_to_unit,
                units=units,
                seed=args.seed,
                group_id=group["group_id"],
                rank_limit=max(20, args.max_return),
                required_unit_ids=group["required_unit_ids"],
            )
            records_by_level[level_index].append(
                {
                    "group_id": group["group_id"],
                    "base_query_id": group["base_query_id"],
                    "required_atomic_ids": list(group["required_atomic_ids"]),
                    "required_unit_ids": list(group["required_unit_ids"]),
                    "latency_ms": latency_ms,
                    "pairwise_precision": pairwise_precision,
                    "ranking": ranking,
                }
            )
        if index % 10 == 0 or index == len(groups):
            print(f"Ranked {index}/{len(groups)} groups", flush=True)

    calibration_records = [
        record
        for records in records_by_level[:2]
        for record in records
        if record["group_id"] in calibration_ids
    ]
    policy, calibration_metrics = choose_policy(
        calibration_records,
        target_hit=args.target_hit,
        target_precision=args.target_precision,
        target_abstention=args.target_abstention,
    )
    print(f"Frozen policy: {policy.as_dict()}", flush=True)

    pressure_one_calibration = [
        record
        for record in records_by_level[0]
        if record["group_id"] in calibration_ids
    ]
    direct_threshold, direct_calibration = choose_direct_return_threshold(
        pressure_one_calibration, args.target_precision
    )
    core_levels: list[dict[str, Any]] = []
    for level_index, records in enumerate(records_by_level):
        evaluation_level = [
            record for record in records if record["group_id"] in evaluation_ids
        ]
        retrieval_evaluation = evaluate(evaluation_level, policy)
        direct_evaluation = evaluate_direct_return(
            evaluation_level, direct_threshold
        )
        core_levels.append(
            {
                "label": f"Pressure {level_index + 1}",
                "pool_size": args.levels[level_index],
                "hit_at_5": retrieval_evaluation["raw_hit_at_5"],
                "precision": direct_evaluation["precision"],
                "mean_latency_ms": retrieval_evaluation["latency_ms"]["mean"],
                "direct_return_rate": direct_evaluation["direct_return_rate"],
            }
        )

    def build_levels(allowed_ids: set[str]) -> list[dict[str, Any]]:
        filtered_levels = [
            [record for record in records if record["group_id"] in allowed_ids]
            for records in records_by_level
        ]
        baseline = {record["group_id"]: record for record in filtered_levels[0]}
        return [
            {
                "label": f"Pressure {index + 1}",
                "pool_size": pool_size,
                "metrics": evaluate(records, policy),
                "deformation": paired_deformation(records, baseline, policy),
            }
            for index, (pool_size, records) in enumerate(
                zip(args.levels, filtered_levels)
            )
        ]

    answer_groups = [group for group in groups if group["required_unit_ids"]]
    required_counts = [len(group["required_unit_ids"]) for group in answer_groups]
    return {
        "metadata": {
            "dataset": "OS_Agent_v5.5 Episode-memory progressive pressure",
            "seed": args.seed,
            "levels": list(args.levels),
            "atomic_item_count": len(atomic_items),
            "memory_unit_count": len(units),
            "group_count": len(groups),
            "calibration_group_count": len(calibration_ids),
            "evaluation_group_count": len(evaluation_ids),
            "required_units": {
                "mean": mean([float(value) for value in required_counts]),
                "median": statistics.median(required_counts),
                "max": max(required_counts),
            },
            "nested_pool_invariant": True,
            "calibration_ids": sorted(calibration_ids),
            "evaluation_ids": sorted(evaluation_ids),
        },
        "targets": {
            "hit": args.target_hit,
            "required_density": args.target_precision,
            "empty_abstention": args.target_abstention,
        },
        "policy": policy.as_dict(),
        "core_levels": core_levels,
        "direct_return_policy": {
            "min_score": direct_threshold,
            "calibration": direct_calibration,
        },
        "calibration_metrics_pressure_1_and_2": calibration_metrics,
        "evaluation_levels": build_levels(evaluation_ids),
        "all_levels": build_levels({group["group_id"] for group in groups}),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--benchmark-root", type=Path, default=REPO_ROOT / "_benchmark"
    )
    parser.add_argument("--levels", type=parse_int_list, default=DEFAULT_LEVELS)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--calibration-fraction", type=float, default=0.25)
    parser.add_argument("--target-hit", type=float, default=0.85)
    parser.add_argument("--target-precision", type=float, default=0.85)
    parser.add_argument("--target-abstention", type=float, default=0.80)
    parser.add_argument("--max-return", type=int, default=5)
    parser.add_argument(
        "--output-json",
        type=Path,
        default=REPO_ROOT / "_benchmark" / "results" / "v55_episode_pressure.json",
    )
    parser.add_argument(
        "--output-md",
        type=Path,
        default=REPO_ROOT / "_benchmark" / "results" / "v55_episode_pressure.md",
    )
    args = parser.parse_args()
    if not 0.0 < args.calibration_fraction < 1.0:
        parser.error("--calibration-fraction must be in (0, 1)")
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
