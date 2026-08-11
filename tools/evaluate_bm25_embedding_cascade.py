from __future__ import annotations

import argparse
import json
import re
import statistics
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from tools.evaluate_bm25_only_retrieval import (
    DEFAULT_SOURCE_ROOT,
    JiebaIdentifierTokenizer,
    PrebuiltBM25Index,
    _memory_document,
    _read_csv,
    _split_ids,
)
from tools.evaluate_online_retrieval_v1 import _tags
from src.memory_engine.preference_matching import CanonicalTagRegistry


DEFAULT_BASELINE = Path(
    "outputs/online_retrieval_v1/recall85_full_530_final.json"
)
DEFAULT_OBSERVATIONS = Path(
    "tests/data/os_agent_observation_benchmark_v31.json"
)
DEFAULT_OUTPUT = Path(
    "runtime/results/bm25_embedding_cascade/cascade_v1.json"
)

FILE_IDENTIFIER = re.compile(
    r"[A-Za-z0-9_#-]+\.(?:xlsx?|csv|tsv|docx?|pptx?|pdf|json|log)",
    re.IGNORECASE,
)
MULTI_TASK_MARKER = re.compile(
    r"(?:第\s*[2-9二三四五六七八九]\s*件|分别处理|各自(?:原来|之前|的)|"
    r"不同文件|同时处理|一起处理这批)",
    re.IGNORECASE,
)


def _percentile(values: Sequence[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    position = (len(ordered) - 1) * percentile
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction


def _cosine(left: Sequence[float], right: Sequence[float]) -> float:
    # The Kylin backend returns normalized vectors. Keeping the norms here
    # makes the evaluator usable with deterministic test doubles as well.
    numerator = sum(float(a) * float(b) for a, b in zip(left, right))
    left_norm = sum(float(value) ** 2 for value in left) ** 0.5
    right_norm = sum(float(value) ** 2 for value in right) ** 0.5
    if not left_norm or not right_norm:
        return 0.0
    return max(-1.0, min(1.0, numerator / (left_norm * right_norm)))


def _memory_fragments(row: Mapping[str, str]) -> tuple[str, ...]:
    action = (row.get("expected_action") or "").replace("_", " ")
    constraint = row.get("constraints") or ""
    summary = row.get("memory_summary") or ""
    values = [summary]
    if action or constraint:
        values.append(" ".join(value for value in (action, constraint) if value))
    return tuple(dict.fromkeys(value for value in values if value.strip()))


def _context_documents(
    query: Mapping[str, str],
    contexts: Mapping[str, Mapping[str, str]],
) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            contexts[context_id]["active_document"]
            for context_id in _split_ids(query["current_context_ids"])
            if context_id in contexts
            and contexts[context_id].get("active_document")
        )
    )


def _context_text(
    query: Mapping[str, str],
    contexts: Mapping[str, Mapping[str, str]],
) -> str:
    documents = _context_documents(query, contexts)
    return " ".join((query["query_text"], *documents)).strip()


@dataclass(frozen=True)
class CascadeThresholds:
    min_semantic: float
    min_combined: float
    min_margin: float


BALANCED_THRESHOLD_FLOOR = CascadeThresholds(0.75, 0.82, 0.10)


@dataclass(frozen=True)
class RankedCandidate:
    memory_id: str
    condition_tag_id: str | None
    bm25_score: float
    bm25_ratio: float
    semantic_score: float
    identifier_coverage: float
    combined_score: float
    matched_terms: tuple[str, ...]


class BM25EmbeddingFastPath:
    def __init__(
        self,
        memory_rows: Sequence[Mapping[str, str]],
        *,
        tokenizer: JiebaIdentifierTokenizer,
        embedder: Any,
        condition_by_memory: Mapping[str, str | None],
    ) -> None:
        self.tokenizer = tokenizer
        self.embedder = embedder
        self.documents = {
            row["memory_id"]: _memory_document(row) for row in memory_rows
        }
        self.index = PrebuiltBM25Index(self.documents, tokenizer)
        self.condition_by_memory = dict(condition_by_memory)
        self.condition_frequency: dict[str, int] = {}
        for condition in self.condition_by_memory.values():
            if condition:
                self.condition_frequency[condition] = (
                    self.condition_frequency.get(condition, 0) + 1
                )

        fragments_by_memory = {
            row["memory_id"]: _memory_fragments(row) for row in memory_rows
        }
        unique_fragments = tuple(
            dict.fromkeys(
                fragment
                for fragments in fragments_by_memory.values()
                for fragment in fragments
            )
        )
        vectors = embedder.embed(list(unique_fragments))
        vector_by_fragment = dict(zip(unique_fragments, vectors))
        self.fragment_vectors = {
            memory_id: tuple(vector_by_fragment[value] for value in fragments)
            for memory_id, fragments in fragments_by_memory.items()
        }
        self.fragment_count = len(unique_fragments)

    def rank(
        self,
        text: str,
        *,
        top_k: int = 8,
    ) -> tuple[RankedCandidate, ...]:
        hits = self.index.search(text, top_k=top_k)
        return self.rerank(text, hits)

    def rerank(
        self,
        text: str,
        hits: Sequence[Any],
    ) -> tuple[RankedCandidate, ...]:
        if not hits:
            return ()
        query_vector = self.embedder.embed([text])[0]
        top_bm25 = max(hit.score for hit in hits) or 1.0
        query_identifiers = set(self.tokenizer.identifiers(text))
        ranked = []
        for hit in hits:
            semantic = max(
                _cosine(query_vector, vector)
                for vector in self.fragment_vectors[hit.document_id]
            )
            covered = sum(
                identifier in self.documents[hit.document_id].casefold()
                for identifier in query_identifiers
            )
            identifier_coverage = (
                covered / len(query_identifiers) if query_identifiers else 0.0
            )
            bm25_ratio = hit.score / top_bm25
            combined = (
                0.72 * semantic
                + 0.18 * bm25_ratio
                + 0.10 * identifier_coverage
            )
            ranked.append(
                RankedCandidate(
                    memory_id=hit.document_id,
                    condition_tag_id=self.condition_by_memory.get(
                        hit.document_id
                    ),
                    bm25_score=hit.score,
                    bm25_ratio=bm25_ratio,
                    semantic_score=semantic,
                    identifier_coverage=identifier_coverage,
                    combined_score=combined,
                    matched_terms=hit.matched_terms,
                )
            )
        return tuple(
            sorted(
                ranked,
                key=lambda value: (
                    -value.combined_score,
                    -value.semantic_score,
                    value.memory_id,
                ),
            )
        )

    def condition_is_conflicted(self, condition: str | None) -> bool:
        return bool(condition and self.condition_frequency.get(condition, 0) > 1)


def _has_ambiguous_reference(
    registry: CanonicalTagRegistry,
    text: str,
) -> bool:
    mentions = registry.find_mentions(text)
    return any(
        mention.tag_id == "object:ambiguous_prior_workflow"
        for mention in mentions
    ) and not any(
        mention.tag_id.startswith("object:")
        and mention.tag_id != "object:ambiguous_prior_workflow"
        for mention in mentions
    )


def _is_multi_task(text: str) -> bool:
    files = {value.casefold() for value in FILE_IDENTIFIER.findall(text)}
    return len(files) >= 2 or bool(MULTI_TASK_MARKER.search(text))


def _passes_threshold(
    candidate: RankedCandidate,
    *,
    margin: float,
    thresholds: CascadeThresholds,
) -> bool:
    return (
        candidate.semantic_score >= thresholds.min_semantic
        and candidate.combined_score >= thresholds.min_combined
        and margin >= thresholds.min_margin
    )


def _early_decision(
    ranked: Sequence[RankedCandidate],
    *,
    text: str,
    ambiguous: bool,
    fast_path: BM25EmbeddingFastPath,
    thresholds: CascadeThresholds,
) -> tuple[str, ...]:
    if not ranked or ambiguous or _is_multi_task(text):
        return ()
    first = ranked[0]
    if fast_path.condition_is_conflicted(first.condition_tag_id):
        return ()
    margin = (
        first.combined_score - ranked[1].combined_score
        if len(ranked) > 1
        else first.combined_score
    )
    return (
        (first.memory_id,)
        if _passes_threshold(first, margin=margin, thresholds=thresholds)
        else ()
    )


def _calibrate_thresholds(
    rows: Sequence[Mapping[str, Any]],
    *,
    minimum_precision: float = 0.99,
) -> CascadeThresholds:
    best: tuple[tuple[int, float, float], CascadeThresholds] | None = None
    for semantic in (0.75, 0.78, 0.80, 0.82):
        for combined in (0.82, 0.84, 0.86, 0.88):
            for margin in (0.10, 0.12, 0.15, 0.18):
                thresholds = CascadeThresholds(semantic, combined, margin)
                accepted = [
                    row
                    for row in rows
                    if row["structurally_eligible"]
                    and _passes_threshold(
                        row["ranked"][0],
                        margin=row["rank_margin"],
                        thresholds=thresholds,
                    )
                ]
                if not accepted:
                    continue
                precision = sum(
                    row["ranked"][0].memory_id in row["required_ids"]
                    for row in accepted
                ) / len(accepted)
                if precision < minimum_precision:
                    continue
                score = (
                    len(accepted),
                    precision,
                    -(
                        thresholds.min_semantic
                        + thresholds.min_combined
                        + thresholds.min_margin
                    ),
                )
                if best is None or score > best[0]:
                    best = (score, thresholds)
    return best[1] if best else BALANCED_THRESHOLD_FLOOR


def _quality(rows: Sequence[Mapping[str, Any]], key: str) -> dict[str, Any]:
    required_total = sum(len(row["required_ids"]) for row in rows)
    required_hits = sum(
        memory_id in row[key]
        for row in rows
        for memory_id in row["required_ids"]
    )
    selected_total = sum(len(row[key]) for row in rows)
    selected_correct = sum(
        memory_id in row["required_ids"]
        for row in rows
        for memory_id in row[key]
    )
    answerable = [row for row in rows if row["required_ids"]]
    clarification = [row for row in rows if not row["required_ids"]]
    return {
        "query_count": len(rows),
        "required_memory_count": required_total,
        "required_memory_hit_count": required_hits,
        "required_memory_hit_recall": (
            required_hits / required_total if required_total else 1.0
        ),
        "selected_memory_count": selected_total,
        "selected_memory_precision": (
            selected_correct / selected_total if selected_total else 1.0
        ),
        "all_required_query_success_rate": (
            sum(set(row["required_ids"]) <= set(row[key]) for row in answerable)
            / len(answerable)
            if answerable
            else 1.0
        ),
        "clarification_abstention_rate": (
            sum(not row[key] for row in clarification) / len(clarification)
            if clarification
            else 1.0
        ),
        "forbidden_primary_selection_count": sum(
            memory_id in row[key]
            for row in rows
            for memory_id in row["forbidden_ids"]
        ),
    }


def _latency(values: Sequence[float]) -> dict[str, float]:
    return {
        "mean_ms": statistics.mean(values) if values else 0.0,
        "p50_ms": statistics.median(values) if values else 0.0,
        "p95_ms": _percentile(values, 0.95),
        "p99_ms": _percentile(values, 0.99),
        "max_ms": max(values, default=0.0),
        "within_500ms_rate": (
            sum(value <= 500.0 for value in values) / len(values)
            if values
            else 1.0
        ),
        "within_800ms_rate": (
            sum(value <= 800.0 for value in values) / len(values)
            if values
            else 1.0
        ),
    }


def evaluate(
    *,
    memory_rows: Sequence[Mapping[str, str]],
    query_rows: Sequence[Mapping[str, str]],
    contexts: Mapping[str, Mapping[str, str]],
    baseline_payload: Mapping[str, Any],
    dataset: Mapping[str, Any],
    embedder: Any,
) -> dict[str, Any]:
    baseline_by_query = {
        row["query_id"]: row for row in baseline_payload["cases"]["cold"]
    }
    # Condition ids are benchmark metadata, not query answers. They are read
    # from the fixed Observation tag catalogue through source_task_id.
    event_gold = {
        case["id"].removeprefix("event:"): case["gold_observations"][0]
        for case in dataset["cases"]
        if case["source_kind"] == "event"
    }
    condition_by_memory = {
        row["memory_id"]: event_gold[row["source_task_id"]].get(
            "condition_tag_id"
        )
        for row in memory_rows
    }
    tokenizer = JiebaIdentifierTokenizer()
    tokenizer.tokenize("BM25 级联预热 W32time B1:E30")
    index_started = time.perf_counter()
    fast_path = BM25EmbeddingFastPath(
        memory_rows,
        tokenizer=tokenizer,
        embedder=embedder,
        condition_by_memory=condition_by_memory,
    )
    initialization_ms = (time.perf_counter() - index_started) * 1000.0
    registry = CanonicalTagRegistry(_tags(dataset))

    rows: list[dict[str, Any]] = []
    for query in query_rows:
        baseline = baseline_by_query[query["query_id"]]
        search_text = _context_text(query, contexts)
        context_documents = _context_documents(query, contexts)
        context_ids = tuple(
            dict.fromkeys(_split_ids(query["current_context_ids"]))
        )
        ambiguous = _has_ambiguous_reference(registry, query["query_text"])
        multi_task = _is_multi_task(query["query_text"])
        started = time.perf_counter()
        lexical_hits = fast_path.index.search(search_text, top_k=8)
        lexical_top_condition = (
            condition_by_memory.get(lexical_hits[0].document_id)
            if lexical_hits
            else None
        )
        prefilter_eligible = (
            len(context_ids) == 1
            and not ambiguous
            and not multi_task
            and bool(lexical_hits)
            and not fast_path.condition_is_conflicted(
                lexical_top_condition
            )
        )
        if prefilter_eligible:
            ranked = fast_path.rerank(search_text, lexical_hits)
        else:
            ranked = ()
        fast_ms = (time.perf_counter() - started) * 1000.0
        first = ranked[0] if ranked else None
        rank_margin = (
            first.combined_score - ranked[1].combined_score
            if first is not None and len(ranked) > 1
            else first.combined_score if first is not None else 0.0
        )
        structurally_eligible = bool(
            first
            and prefilter_eligible
            and not fast_path.condition_is_conflicted(
                first.condition_tag_id
            )
        )
        baseline_overhead = sum(
            float(baseline["stages_ms"].get(stage, 0.0))
            for stage in (
                "input_safety",
                "normalization_and_context",
                "output_safety_and_packaging",
            )
        )
        rows.append(
            {
                "query_id": query["query_id"],
                "query_text": query["query_text"],
                "partition": query["dataset_partition"],
                "evaluation_track": query["evaluation_track"],
                "query_type": query["query_type"],
                "required_ids": set(_split_ids(query["required_memory_ids"])),
                "forbidden_ids": set(_split_ids(query["forbidden_memory_ids"])),
                "baseline_ids": tuple(baseline["selected_memory_ids"]),
                "baseline_total_ms": float(baseline["stages_ms"]["total"]),
                "baseline_fast_overhead_ms": baseline_overhead,
                "fast_ms": fast_ms,
                "ambiguous": ambiguous,
                "multi_task": multi_task,
                "context_document_count": len(context_documents),
                "context_id_count": len(context_ids),
                "prefilter_eligible": prefilter_eligible,
                "structurally_eligible": structurally_eligible,
                "rank_margin": rank_margin,
                "ranked": ranked,
            }
        )

    calibration = [row for row in rows if row["partition"] == "train"]
    thresholds = _calibrate_thresholds(calibration)
    for row in rows:
        early = _early_decision(
            row["ranked"],
            text=row["query_text"],
            ambiguous=row["ambiguous"],
            fast_path=fast_path,
            thresholds=thresholds,
        )
        row["early_ids"] = early
        row["cascade_ids"] = early or row["baseline_ids"]

        supplement = []
        if not early and not row["ambiguous"]:
            for candidate in row["ranked"]:
                if fast_path.condition_is_conflicted(
                    candidate.condition_tag_id
                ):
                    continue
                if candidate.memory_id in row["baseline_ids"]:
                    continue
                if (
                    candidate.semantic_score
                    >= thresholds.min_semantic + 0.04
                    and candidate.combined_score
                    >= thresholds.min_combined + 0.04
                    and (
                        candidate.identifier_coverage >= 0.50
                        or candidate.semantic_score
                        >= thresholds.min_semantic + 0.10
                    )
                ):
                    supplement.append(candidate.memory_id)
                if len(row["baseline_ids"]) + len(supplement) >= 5:
                    break
        row["supplement_ids"] = tuple(supplement)
        row["cascade_supplement_ids"] = tuple(
            dict.fromkeys((*row["cascade_ids"], *supplement))
        )[:5]
        row["cascade_total_ms"] = (
            row["fast_ms"] + row["baseline_fast_overhead_ms"]
            if early
            else row["fast_ms"] + row["baseline_total_ms"]
        )

    early_rows = [row for row in rows if row["early_ids"]]
    fast_correct = sum(
        set(row["early_ids"]) <= row["required_ids"]
        for row in early_rows
    )
    serializable_rows = []
    for row in rows:
        serializable_rows.append(
            {
                **{
                    key: value
                    for key, value in row.items()
                    if key not in {"required_ids", "forbidden_ids", "ranked"}
                },
                "required_ids": sorted(row["required_ids"]),
                "forbidden_ids": sorted(row["forbidden_ids"]),
                "ranked": [asdict(value) for value in row["ranked"]],
            }
        )
    return {
        "contract": {
            "algorithm": "BM25 Top-8 -> Kylin Embedding rerank -> conservative early exit",
            "answer_labels_used_for_ranking": False,
            "threshold_calibration_partition": "train",
            "evaluation_partitions": ["dev", "test", "challenge"],
            "memory_count": len(memory_rows),
            "query_count": len(query_rows),
            "fragment_count": fast_path.fragment_count,
            "embedding_prefilter": (
                "exactly one active context id, no explicit ambiguity or "
                "multi-task structure, and no lexical condition conflict"
            ),
            "thresholds": asdict(thresholds),
            "threshold_floor": asdict(BALANCED_THRESHOLD_FLOOR),
            "threshold_policy": (
                "maximize train coverage at >=99% direct-return precision "
                "without going below the shadow-negative safety floor"
            ),
            "fallback_latency_projection": (
                "conservative serial sum; embedding cache reuse is not subtracted"
            ),
        },
        "initialization": {
            "bm25_and_memory_fragment_embedding_ms": initialization_ms,
        },
        "quality": {
            "baseline": _quality(rows, "baseline_ids"),
            "cascade": _quality(rows, "cascade_ids"),
            "cascade_with_supplement": _quality(
                rows, "cascade_supplement_ids"
            ),
        },
        "early_exit": {
            "count": len(early_rows),
            "coverage": len(early_rows) / len(rows) if rows else 0.0,
            "correct_count": fast_correct,
            "precision": fast_correct / len(early_rows) if early_rows else 1.0,
            "by_partition": {
                partition: {
                    "count": sum(
                        row["partition"] == partition for row in early_rows
                    ),
                    "precision": (
                        sum(
                            row["partition"] == partition
                            and set(row["early_ids"]) <= row["required_ids"]
                            for row in early_rows
                        )
                        / sum(
                            row["partition"] == partition for row in early_rows
                        )
                        if any(
                            row["partition"] == partition for row in early_rows
                        )
                        else 1.0
                    ),
                }
                for partition in sorted({row["partition"] for row in rows})
            },
        },
        "latency": {
            "fast_path_only": _latency([row["fast_ms"] for row in rows]),
            "baseline_total": _latency(
                [row["baseline_total_ms"] for row in rows]
            ),
            "projected_cascade_total": _latency(
                [row["cascade_total_ms"] for row in rows]
            ),
            "projected_mean_saved_ms": statistics.mean(
                row["baseline_total_ms"] - row["cascade_total_ms"]
                for row in rows
            ),
        },
        "cases": serializable_rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, default=DEFAULT_SOURCE_ROOT)
    parser.add_argument("--observations", type=Path, default=DEFAULT_OBSERVATIONS)
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()

    try:
        from src.rag.kylin_embedding_sdk import KylinTextEmbedding
    except (ImportError, OSError) as exc:
        raise SystemExit(
            "cascade evaluation requires the real Kylin embedding SDK; "
            f"no fallback is permitted ({type(exc).__name__})"
        ) from exc

    data_root = args.source_root / "processed_data"
    queries = _read_csv(data_root / "query_set.csv")
    if args.limit is not None:
        queries = queries[: args.limit]
    memories = _read_csv(data_root / "memory_records.csv")
    contexts = {
        row["context_id"]: row
        for row in _read_csv(data_root / "context_set.csv")
    }
    dataset = json.loads(args.observations.read_text(encoding="utf-8"))
    baseline = json.loads(args.baseline.read_text(encoding="utf-8"))

    initialized = time.perf_counter()
    embedder = KylinTextEmbedding()
    model_initialization_ms = (time.perf_counter() - initialized) * 1000.0
    result = evaluate(
        memory_rows=memories,
        query_rows=queries,
        contexts=contexts,
        baseline_payload=baseline,
        dataset=dataset,
        embedder=embedder,
    )
    result["initialization"]["embedding_model_ms"] = model_initialization_ms
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "output": str(args.output),
                "contract": result["contract"],
                "quality": result["quality"],
                "early_exit": result["early_exit"],
                "latency": result["latency"],
                "initialization": result["initialization"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
