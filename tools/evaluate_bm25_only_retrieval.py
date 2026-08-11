from __future__ import annotations

import argparse
import csv
import json
import math
import re
import statistics
import time
import tracemalloc
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


DEFAULT_SOURCE_ROOT = (
    Path(__file__).resolve().parents[2]
    / "os_agent_memory_query_benchmark_v3.1"
    / "os_agent_memory_query_benchmark_v3.1_20260725"
)
DEFAULT_CURRENT_RETRIEVAL = Path(
    "outputs/online_retrieval_v1/recall85_full_530_final.json"
)
DEFAULT_OUTPUT = Path(
    "runtime/results/bm25_only_retrieval/bm25_only_v1.json"
)
IDENTIFIER_PATTERN = re.compile(
    r"(?:[A-Za-z][A-Za-z0-9_#-]*(?:\.[A-Za-z0-9_#-]+)+)"
    r"|(?:\b[A-Z]{1,4}\d{1,7}(?::[A-Z]{1,4}\d{1,7})?\b)"
    r"|(?:\b(?:0x)?[A-Fa-f0-9]{4,}\b)"
    r"|(?:\b[A-Za-z][A-Za-z0-9]*(?:_[A-Za-z0-9#]+)+\b)"
    r"|(?:\b\d+(?:\.\d+){1,4}\b)"
)
LATIN_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_#:+./-]+")


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _split_ids(value: str) -> tuple[str, ...]:
    return tuple(item for item in value.split("|") if item)


def _percentile(values: Sequence[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    position = (len(ordered) - 1) * percentile
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction


def _flatten_json(value: Any) -> Iterable[str]:
    if isinstance(value, Mapping):
        for key, child in value.items():
            yield str(key)
            yield from _flatten_json(child)
    elif isinstance(value, Sequence) and not isinstance(value, str):
        for child in value:
            yield from _flatten_json(child)
    elif value not in (None, ""):
        yield str(value)


class JiebaIdentifierTokenizer:
    """Preserve identifiers and use jieba only for surrounding prose."""

    def __init__(self) -> None:
        try:
            import jieba
        except ImportError as exc:
            raise RuntimeError("jieba_is_required_for_bm25_evaluation") from exc
        if not callable(getattr(jieba, "cut", None)):
            raise RuntimeError("jieba_installation_is_incomplete")
        self._jieba = jieba

    def tokenize(self, text: str) -> tuple[str, ...]:
        values: list[str] = []
        cursor = 0
        for match in IDENTIFIER_PATTERN.finditer(text):
            values.extend(self._prose_tokens(text[cursor : match.start()]))
            identifier = match.group(0).casefold()
            values.append(identifier)
            values.extend(
                token.casefold()
                for token in re.findall(r"[A-Za-z0-9#]+", identifier)
                if len(token) > 1
            )
            cursor = match.end()
        values.extend(self._prose_tokens(text[cursor:]))
        return tuple(token for token in values if token)

    def identifiers(self, text: str) -> tuple[str, ...]:
        return tuple(
            dict.fromkeys(
                match.group(0).casefold()
                for match in IDENTIFIER_PATTERN.finditer(text)
            )
        )

    def _prose_tokens(self, text: str) -> list[str]:
        values = []
        for segment in self._jieba.cut(text, cut_all=False):
            values.extend(
                token.casefold()
                for token in LATIN_TOKEN_PATTERN.findall(segment)
                if token.strip("_#:+./-")
            )
            values.extend(
                token
                for token in re.findall(r"[\u3400-\u9fff]+", segment)
                if token.strip()
            )
        return values


@dataclass(frozen=True)
class BM25Hit:
    document_id: str
    score: float
    matched_terms: tuple[str, ...]


class PrebuiltBM25Index:
    """Small immutable BM25 index built once for the measured query pass."""

    def __init__(
        self,
        documents: Mapping[str, str],
        tokenizer: JiebaIdentifierTokenizer,
        *,
        k1: float = 1.5,
        b: float = 0.75,
    ) -> None:
        self.tokenizer = tokenizer
        self.k1 = float(k1)
        self.b = float(b)
        self.document_terms = {
            document_id: tokenizer.tokenize(text)
            for document_id, text in documents.items()
        }
        self.term_counts = {
            document_id: Counter(terms)
            for document_id, terms in self.document_terms.items()
        }
        self.document_lengths = {
            document_id: len(terms)
            for document_id, terms in self.document_terms.items()
        }
        self.document_count = len(self.document_terms)
        self.average_length = (
            sum(self.document_lengths.values()) / self.document_count
            if self.document_count
            else 1.0
        ) or 1.0
        document_frequency: Counter[str] = Counter()
        for terms in self.document_terms.values():
            document_frequency.update(set(terms))
        self.idf = {
            term: math.log(
                1.0
                + (
                    self.document_count
                    - frequency
                    + 0.5
                )
                / (frequency + 0.5)
            )
            for term, frequency in document_frequency.items()
        }

    def search(self, query: str, *, top_k: int = 5) -> tuple[BM25Hit, ...]:
        query_terms = tuple(dict.fromkeys(self.tokenizer.tokenize(query)))
        scores = []
        for document_id, counts in self.term_counts.items():
            length = self.document_lengths[document_id]
            score = 0.0
            matched = []
            for term in query_terms:
                frequency = counts.get(term, 0)
                if frequency == 0:
                    continue
                matched.append(term)
                denominator = frequency + self.k1 * (
                    1.0
                    - self.b
                    + self.b * length / self.average_length
                )
                score += self.idf[term] * (
                    frequency * (self.k1 + 1.0) / denominator
                )
            if score > 0.0:
                scores.append(
                    BM25Hit(
                        document_id=document_id,
                        score=score,
                        matched_terms=tuple(matched),
                    )
                )
        return tuple(
            sorted(
                scores,
                key=lambda value: (-value.score, value.document_id),
            )[: max(0, top_k)]
        )


def _memory_document(row: Mapping[str, str]) -> str:
    semantic = json.loads(row["semantic_value"] or "{}")
    condition = json.loads(row["condition"] or "{}")
    semantic_without_content = {
        key: value
        for key, value in semantic.items()
        if key != "content"
    }
    return " ".join(
        value
        for value in (
            row["memory_summary"],
            row["expected_action"],
            row["constraints"],
            " ".join(_flatten_json(condition)),
            " ".join(_flatten_json(semantic_without_content)),
        )
        if value
    )


def _quality(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    required_total = sum(len(row["required_ids"]) for row in rows)
    required_hits = sum(
        memory_id in row["selected_ids"]
        for row in rows
        for memory_id in row["required_ids"]
    )
    selected_total = sum(len(row["selected_ids"]) for row in rows)
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
            required_hits / selected_total if selected_total else 1.0
        ),
        "answerable_query_count": len(answerable),
        "any_required_query_hit_rate": (
            sum(
                bool(set(row["required_ids"]) & set(row["selected_ids"]))
                for row in answerable
            )
            / len(answerable)
            if answerable
            else 1.0
        ),
        "all_required_query_success_rate": (
            sum(
                set(row["required_ids"]) <= set(row["selected_ids"])
                for row in answerable
            )
            / len(answerable)
            if answerable
            else 1.0
        ),
        "clarification_query_count": len(clarification),
        "clarification_abstention_rate": (
            sum(not row["selected_ids"] for row in clarification)
            / len(clarification)
            if clarification
            else 1.0
        ),
    }


def _current_selected(path: Path | None) -> dict[str, set[str]]:
    if path is None or not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {
        row["query_id"]: set(row["selected_memory_ids"])
        for row in payload["cases"]["cold"]
    }


def evaluate(
    *,
    memory_rows: Sequence[Mapping[str, str]],
    query_rows: Sequence[Mapping[str, str]],
    current_selected: Mapping[str, set[str]] | None = None,
) -> dict[str, Any]:
    tokenizer_started = time.perf_counter()
    tokenizer = JiebaIdentifierTokenizer()
    tokenizer.tokenize("BM25 中文分词预热 W32time B1:E30")
    tokenizer_cold_start_ms = (
        time.perf_counter() - tokenizer_started
    ) * 1000.0
    documents = {
        row["memory_id"]: _memory_document(row)
        for row in memory_rows
    }
    build_started = time.perf_counter()
    index = PrebuiltBM25Index(documents, tokenizer)
    build_ms = (time.perf_counter() - build_started) * 1000.0
    tracemalloc.start()
    measured_index = PrebuiltBM25Index(documents, tokenizer)
    index_bytes, peak_bytes = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    index = measured_index

    current = dict(current_selected or {})
    rows = []
    latencies = []
    for query in query_rows:
        started = time.perf_counter()
        hits = index.search(query["query_text"], top_k=5)
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        latencies.append(elapsed_ms)
        required = _split_ids(query["required_memory_ids"])
        selected = tuple(hit.document_id for hit in hits)
        current_ids = current.get(query["query_id"], set())
        identifiers = tokenizer.identifiers(query["query_text"])
        rows.append(
            {
                "query_id": query["query_id"],
                "evaluation_track": query["evaluation_track"],
                "query_type": query["query_type"],
                "dataset_partition": query["dataset_partition"],
                "route_group": (
                    "identifier_rich" if identifiers else "natural_language"
                ),
                "identifiers": list(identifiers),
                "required_ids": list(required),
                "selected_ids": list(selected),
                "scores": [
                    {
                        "memory_id": hit.document_id,
                        "score": round(hit.score, 8),
                        "matched_terms": list(hit.matched_terms),
                    }
                    for hit in hits
                ],
                "latency_ms": elapsed_ms,
                "current_selected_ids": sorted(current_ids),
                "bm25_unique_required_hits": sorted(
                    (set(required) & set(selected)) - current_ids
                ),
                "current_unique_required_hits": sorted(
                    (set(required) & current_ids) - set(selected)
                ),
            }
        )

    current_missed_required = sum(
        memory_id not in set(row["current_selected_ids"])
        for row in rows
        for memory_id in row["required_ids"]
    )
    bm25_rescued_required = sum(
        len(row["bm25_unique_required_hits"]) for row in rows
    )
    source_bytes = sum(len(value.encode("utf-8")) for value in documents.values())
    return {
        "contract": {
            "algorithm": "prebuilt_bm25_k1_1.5_b_0.75",
            "embedding_used": False,
            "observation_used": False,
            "answer_labels_used_for_retrieval": False,
            "document_count": len(documents),
            "top_k": 5,
            "document_fields": [
                "memory_summary",
                "expected_action",
                "constraints",
                "condition",
                "semantic_value_without_content",
            ],
        },
        "cost": {
            "tokenizer_cold_start_ms": tokenizer_cold_start_ms,
            "index_build_ms": build_ms,
            "index_allocated_bytes": index_bytes,
            "index_peak_bytes": peak_bytes,
            "source_document_bytes": source_bytes,
            "query_mean_ms": statistics.mean(latencies) if latencies else 0.0,
            "query_p50_ms": statistics.median(latencies) if latencies else 0.0,
            "query_p95_ms": _percentile(latencies, 0.95),
            "query_p99_ms": _percentile(latencies, 0.99),
            "query_max_ms": max(latencies, default=0.0),
        },
        "quality": _quality(rows),
        "by_evaluation_track": {
            value: _quality(
                [row for row in rows if row["evaluation_track"] == value]
            )
            for value in sorted({row["evaluation_track"] for row in rows})
        },
        "by_query_type": {
            value: _quality(
                [row for row in rows if row["query_type"] == value]
            )
            for value in sorted({row["query_type"] for row in rows})
        },
        "by_route_group": {
            value: _quality(
                [row for row in rows if row["route_group"] == value]
            )
            for value in sorted({row["route_group"] for row in rows})
        },
        "complement": {
            "current_result_available": bool(current),
            "current_missed_required_count": current_missed_required,
            "bm25_rescued_required_count": bm25_rescued_required,
            "bm25_rescue_rate_of_current_misses": (
                bm25_rescued_required / current_missed_required
                if current_missed_required
                else 0.0
            ),
            "query_count_with_bm25_unique_required_hit": sum(
                bool(row["bm25_unique_required_hits"]) for row in rows
            ),
            "query_count_with_current_unique_required_hit": sum(
                bool(row["current_unique_required_hits"]) for row in rows
            ),
        },
        "cases": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, default=DEFAULT_SOURCE_ROOT)
    parser.add_argument("--current-retrieval", type=Path, default=DEFAULT_CURRENT_RETRIEVAL)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    data_root = args.source_root / "processed_data"
    result = evaluate(
        memory_rows=_read_csv(data_root / "memory_records.csv"),
        query_rows=_read_csv(data_root / "query_set.csv"),
        current_selected=_current_selected(args.current_retrieval),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "output": str(args.output),
                "contract": result["contract"],
                "cost": result["cost"],
                "quality": result["quality"],
                "by_evaluation_track": result["by_evaluation_track"],
                "by_route_group": result["by_route_group"],
                "complement": result["complement"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
