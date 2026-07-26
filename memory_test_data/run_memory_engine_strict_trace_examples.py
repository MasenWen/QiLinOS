from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from memory_test_data.run_memory_engine_strict_dataset_eval import (  # noqa: E402
    expected_event_ids,
    query_context,
    rank_query,
    read_csv,
    source_event_ids_for_item,
)
from src.memory_engine.strict.config import StrictMemoryEngineConfig  # noqa: E402
from src.memory_engine.strict.engine import StrictMemoryEngine  # noqa: E402
from src.memory_engine.strict.kylin import KylinSDKSemanticScorer  # noqa: E402
from src.memory_engine.strict.store import StrictMemoryEngineStore  # noqa: E402


DEFAULT_QUERY_IDS = (
    "Q0001",  # short current context, expected hit
    "Q0003",  # short temporary preference, expected hit
    "Q0005",  # short task state, expected hit
    "Q0023",  # mid conflict update, known hard case
    "Q0025",  # mid scenario preference, known hard case
    "Q0029",  # routine pattern, known hard case
    "Q0041",  # frequency preference, representative mid-term case
)


def write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def memory_label(memory: Any | None) -> str:
    if memory is None:
        return ""
    return f"{memory.memory_id} | {memory.status.value} | {memory.slot_key} | {memory.semantic_value}"


def obs_summary(observation: Any | None) -> dict[str, Any]:
    if observation is None:
        return {}
    return {
        "observation_id": observation.observation_id,
        "source_event_id": observation.source_event_id,
        "time": observation.event_time,
        "source_type": observation.source_type.value,
        "action": observation.action,
        "app": observation.app,
        "content": observation.content,
        "context": dict(observation.context),
    }


def evidence_summary(evidence: Any) -> dict[str, Any]:
    return {
        "evidence_id": evidence.evidence_id,
        "type": evidence.evidence_type,
        "slot": evidence.claim_slot,
        "value": evidence.claim_value,
        "admission": evidence.admission.value,
        "status": evidence.status,
        "condition": dict(evidence.condition),
        "source_observation_ids": list(evidence.source_observation_ids),
        "independent_unit_id": evidence.independent_unit_id,
    }


def candidate_summary(candidate: Any) -> dict[str, Any]:
    return {
        "candidate_id": candidate.candidate_id,
        "evidence_id": candidate.evidence_id,
        "slot": candidate.slot_key,
        "value": candidate.semantic_value,
        "cardinality": candidate.cardinality,
        "condition": dict(candidate.condition),
        "source_module_id": candidate.source_module_id,
        "status": candidate.status,
    }


def impact_summary(impact: Any) -> dict[str, Any]:
    return {
        "impact_id": impact.impact_id,
        "candidate_id": impact.candidate_id,
        "evidence_id": impact.evidence_id,
        "target_memory_id": impact.target_memory_id,
        "action": impact.action.value,
        "reason_code": impact.reason_code,
    }


def strict_memory_summary(memory: Any) -> dict[str, Any]:
    return {
        "memory_id": memory.memory_id,
        "status": memory.status.value,
        "slot": memory.slot_key,
        "value": memory.semantic_value,
        "condition": dict(memory.condition),
        "scope": dict(memory.scope),
        "evidence_ids": list(memory.evidence_ids),
        "support_unit_ids": list(memory.support_unit_ids),
        "confidence": dict(memory.confidence),
        "stability": dict(memory.stability),
        "valid_from": memory.valid_from,
        "valid_to": memory.valid_to,
    }


def conflict_summary(group: Any) -> dict[str, Any]:
    return {
        "conflict_group_id": group.conflict_group_id,
        "slot": group.slot_key,
        "type": group.conflict_type.value,
        "status": group.status,
        "memory_ids": list(group.memory_ids),
        "winner_memory_id": group.winner_memory_id,
        "unresolved_reason": group.unresolved_reason,
        "condition_partition": dict(group.condition_partition),
    }


def source_events_for_evidence(
    evidence: Any,
    observation_by_id: dict[str, Any],
) -> set[str]:
    result: set[str] = set()
    for observation_id in evidence.source_observation_ids:
        observation = observation_by_id.get(observation_id)
        if observation:
            result.add(observation.source_event_id)
    return result


def index_by_id(items: Iterable[dict[str, str]], key: str) -> dict[str, dict[str, str]]:
    return {item[key]: item for item in items}


def markdown_report(payload: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# strict_v1 代表性测试中间状态 Trace")
    lines.append("")
    lines.append(f"数据库：`{payload['database']}`")
    lines.append(f"语义后端：`{payload['semantic_backend']}`")
    lines.append("")
    for case in payload["cases"]:
        lines.append(f"## {case['query_id']}：{case['target_category']}")
        lines.append("")
        lines.append(f"查询：{case['query_text']}")
        lines.append("")
        lines.append(f"标准答案：{case['expected_answer']}")
        lines.append(f"期望事件：`{' | '.join(case['expected_event_ids'])}`")
        lines.append(f"命中排名：`{case['hit_rank']}`")
        lines.append("")
        lines.append("### 1. 标准来源事件")
        for observation in case["expected_observations"]:
            lines.append(
                "- `{source_event_id}` `{source_type}` `{action}` `{app}`：{content}".format(
                    **{
                        "source_event_id": observation.get("source_event_id", ""),
                        "source_type": observation.get("source_type", ""),
                        "action": observation.get("action", ""),
                        "app": observation.get("app", ""),
                        "content": observation.get("content", ""),
                    }
                )
            )
        lines.append("")
        lines.append("### 2. 这些事件形成的 Evidence")
        if case["lineage_evidence"]:
            for evidence in case["lineage_evidence"][:10]:
                lines.append(
                    "- `{evidence_id}` type=`{type}` slot=`{slot}` admission=`{admission}` value={value}".format(
                        **evidence
                    )
                )
        else:
            lines.append("- 未找到直接相交 Evidence。")
        lines.append("")
        lines.append("### 3. Candidate / Impact / Memory")
        for candidate in case["lineage_candidates"][:8]:
            lines.append(
                "- Candidate `{candidate_id}` slot=`{slot}` value={value} status=`{status}`".format(
                    **candidate
                )
            )
        for impact in case["lineage_impacts"][:8]:
            lines.append(
                "- Impact `{impact_id}` action=`{action}` target=`{target_memory_id}` reason=`{reason_code}`".format(
                    **impact
                )
            )
        for memory in case["lineage_memories"][:8]:
            lines.append(
                "- Memory `{memory_id}` status=`{status}` slot=`{slot}` value={value}".format(
                    **memory
                )
            )
        lines.append("")
        lines.append("### 4. Retrieval Top-K")
        for item in case["retrieved_items"]:
            lines.append(
                "- rank `{rank}` `{memory_id}` decision=`{decision}` activation=`{activation}` "
                "kylin=`{kylin_semantic}` compatible=`{category_compatible}` lineage=`{lineage_match}` "
                "value={semantic_value}".format(**item)
            )
        lines.append("")
        lines.append("### 5. 检索 trace 摘要")
        trace = case["retrieval_trace"]
        lines.append(
            "- hard filter included: `{}`".format(
                len(trace.get("hard_filter", {}).get("included_ids", []))
            )
        )
        excluded = trace.get("hard_filter", {}).get("excluded", {})
        if excluded:
            reason_counts: dict[str, int] = defaultdict(int)
            for reasons in excluded.values():
                for reason in reasons:
                    reason_counts[reason] += 1
            lines.append(
                "- hard filter excluded reasons: `{} `".format(
                    ", ".join(f"{key}={value}" for key, value in sorted(reason_counts.items()))
                )
            )
        conflict = trace.get("conflict_decisions", {})
        lines.append(
            "- clarifications: `{}` advisory: `{}`".format(
                len(conflict.get("clarifications", [])),
                len(conflict.get("advisory_ids", [])),
            )
        )
        lines.append("")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset-dir", type=Path, required=True)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--query-id", action="append", dest="query_ids")
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    query_ids = tuple(args.query_ids or DEFAULT_QUERY_IDS)

    queries = index_by_id(read_csv(args.dataset_dir / "memory_query_set.csv"), "query_id")
    expected = index_by_id(read_csv(args.dataset_dir / "memory_expected_results.csv"), "query_id")
    ground_truth = index_by_id(read_csv(args.dataset_dir / "memory_ground_truth.csv"), "memory_id")

    config = StrictMemoryEngineConfig.load(database_path=args.database)
    store = StrictMemoryEngineStore(args.database)
    scorer = KylinSDKSemanticScorer()
    engine = StrictMemoryEngine(config=config, store=store, semantic_scorer=scorer)

    users = sorted({queries[query_id]["user_id"] for query_id in query_ids if query_id in queries})
    evidence_by_id: dict[str, Any] = {}
    observation_by_id: dict[str, Any] = {}
    candidates_by_evidence: dict[str, list[Any]] = defaultdict(list)
    impacts_by_evidence: dict[str, list[Any]] = defaultdict(list)

    for user_id in users:
        for evidence in store.list_evidence(user_id):
            evidence_by_id[evidence.evidence_id] = evidence
            for observation in store.get_observations(evidence.source_observation_ids):
                observation_by_id[observation.observation_id] = observation
        for candidate in store.list_candidates(user_id):
            candidates_by_evidence[candidate.evidence_id].append(candidate)
    for impact in store.list_impacts():
        impacts_by_evidence[impact.evidence_id].append(impact)

    cases: list[dict[str, Any]] = []
    for query_id in query_ids:
        query = queries[query_id]
        exp = expected[query_id]
        acceptable = [item for item in exp["acceptable_memory_ids"].split("|") if item]
        if not acceptable:
            acceptable = [exp["expected_memory_id"]]
        expected_events = sorted(expected_event_ids(acceptable, ground_truth))

        result = engine.retrieve(query["query_text"], query_context(query), top_k=args.top_k)
        hit_rank, item_audit = rank_query(
            query,
            exp,
            result,
            ground_truth=ground_truth,
            evidence_by_id=evidence_by_id,
            observation_by_id=observation_by_id,
        )

        expected_observations = [
            store.get_observation_by_source_event(event_id)
            for event_id in expected_events
        ]
        expected_observation_ids = {
            observation.observation_id
            for observation in expected_observations
            if observation is not None
        }
        lineage_evidence = [
            evidence
            for evidence in evidence_by_id.values()
            if expected_observation_ids & set(evidence.source_observation_ids)
        ]
        lineage_evidence.sort(key=lambda item: (item.observed_time, item.evidence_id))
        lineage_candidates = [
            candidate
            for evidence in lineage_evidence
            for candidate in candidates_by_evidence.get(evidence.evidence_id, [])
        ]
        lineage_impacts = [
            impact
            for evidence in lineage_evidence
            for impact in impacts_by_evidence.get(evidence.evidence_id, [])
        ]
        lineage_memory_ids = {
            impact.target_memory_id
            for impact in lineage_impacts
            if impact.target_memory_id
        }
        lineage_memory_ids.update(item["memory_id"] for item in result["items"])
        lineage_memories = [
            store.get_memory(memory_id)
            for memory_id in sorted(lineage_memory_ids)
            if not memory_id.startswith("scoped-")
        ]
        lineage_memories = [memory for memory in lineage_memories if memory is not None]
        slot_keys = {memory.slot_key for memory in lineage_memories}
        conflicts = []
        for user_id in users:
            try:
                user_groups = store.list_conflict_groups(user_id, include_obsolete=True)
            except TypeError:
                user_groups = store.list_conflict_groups(user_id)
            for group in user_groups:
                if group.slot_key in slot_keys or set(group.memory_ids) & set(lineage_memory_ids):
                    conflicts.append(group)

        audit_by_memory_id = {
            item["memory_id"]: item
            for item in item_audit
        }
        retrieved_items = []
        for index, item in enumerate(result["items"], start=1):
            audit = audit_by_memory_id.get(item["memory_id"], {})
            retrieved_items.append(
                {
                    "rank": index,
                    "memory_id": item["memory_id"],
                    "decision": item["decision"],
                    "semantic_value": item["semantic_value"],
                    "activation": item["scores"]["activation"]["total"],
                    "kylin_semantic": item["scores"]["kylin_semantic"],
                    "bm25": item["scores"]["bm25"],
                    "condition": item["condition"],
                    "evidence_types": audit.get("evidence_types", []),
                    "source_event_ids": audit.get("source_event_ids", []),
                    "category_compatible": audit.get("category_compatible", False),
                    "lineage_match": audit.get("lineage_match", False),
                }
            )

        cases.append(
            {
                "query_id": query_id,
                "query_text": query["query_text"],
                "target_type": query["target_memory_type"],
                "target_category": query["target_memory_category"],
                "expected_memory_id": exp["expected_memory_id"],
                "expected_answer": exp["expected_answer"],
                "expected_event_ids": expected_events,
                "hit_rank": hit_rank,
                "result_run_id": result["run_id"],
                "expected_observations": [
                    obs_summary(observation)
                    for observation in expected_observations
                    if observation is not None
                ],
                "lineage_evidence": [
                    {
                        **evidence_summary(evidence),
                        "source_event_ids": sorted(
                            source_events_for_evidence(evidence, observation_by_id)
                        ),
                    }
                    for evidence in lineage_evidence
                ],
                "lineage_candidates": [
                    candidate_summary(candidate)
                    for candidate in lineage_candidates
                ],
                "lineage_impacts": [
                    impact_summary(impact)
                    for impact in lineage_impacts
                ],
                "lineage_memories": [
                    strict_memory_summary(memory)
                    for memory in lineage_memories
                ],
                "conflicts": [
                    conflict_summary(group)
                    for group in conflicts
                ],
                "retrieved_items": retrieved_items,
                "retrieval_trace": result["trace"],
                "stage_outputs": [
                    output.to_dict()
                    for output in store.list_stage_outputs(result["run_id"])
                ],
            }
        )

    payload = {
        "database": str(args.database),
        "dataset_dir": str(args.dataset_dir),
        "semantic_backend": scorer.backend_id,
        "query_ids": list(query_ids),
        "cases": cases,
    }
    write_json(args.output_dir / "strict_trace_examples.json", payload)
    (args.output_dir / "strict_trace_examples.md").write_text(
        markdown_report(payload),
        encoding="utf-8",
    )
    print(json.dumps({"status": "ok", "output_dir": str(args.output_dir), "cases": len(cases)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
