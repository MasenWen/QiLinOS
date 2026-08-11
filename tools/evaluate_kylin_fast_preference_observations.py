from __future__ import annotations

import argparse
import json
import statistics
import time
from dataclasses import asdict
from pathlib import Path

from src.memory_engine.observation import ObservationMatcher
from src.memory_engine.preference_matching import (
    PreferenceObservationMemoryExtractor,
    PreferenceSourceObservation,
)
from src.memory_engine.span_matching import JiebaSpanTokenizer
from tools.evaluate_kylin_preference_observations import (
    DEFAULT_CASES,
    _grade,
    _options,
)


DEFAULT_OUTPUT = Path(
    "runtime/results/kylin_fast_preference_observations_v1/"
    "kylin_fast_preference_observations.json"
)


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    position = (len(ordered) - 1) * percentile
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return (
        ordered[lower] * (1.0 - fraction)
        + ordered[upper] * fraction
    )


def main() -> None:
    try:
        from src.rag.kylin_embedding_sdk import KylinTextEmbedding
    except ImportError:
        from tools.evaluate_kylin_embedding_preference_object_blind import (
            KylinTextEmbedding,
        )

    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    cases = json.loads(args.cases.read_text(encoding="utf-8"))

    initialization_started = time.perf_counter()
    matcher = ObservationMatcher(
        KylinTextEmbedding(),
        tokenizer=JiebaSpanTokenizer(),
    )
    extractor = PreferenceObservationMemoryExtractor(matcher)
    initialization_ms = (
        time.perf_counter() - initialization_started
    ) * 1000.0

    rows = []
    for index, case in enumerate(cases):
        observation = PreferenceSourceObservation(
            observation_id=f"obs-fast-{case['id']}",
            source_event_id=f"fast-event-{case['id']}",
            user_id="fast-choice-eval-user",
            session_id=f"fast-choice-eval-{case['id']}",
            event_time=f"2026-07-27T01:{index:02d}:00+00:00",
            content=case["text"],
            source_reliability=1.0,
            privacy={
                "sensitivity": "normal",
                "deletion_scope": "user",
            },
        )
        started = time.perf_counter()
        extraction = extractor.extract(
            observation,
            options=_options(case["options"]),
        )
        latency_ms = (time.perf_counter() - started) * 1000.0
        selected = (
            max(
                extraction.memories,
                key=lambda value: (
                    value.extraction_confidence,
                    -value.source_start,
                    value.object_tag_id,
                ),
            )
            if extraction.memories
            else None
        )
        rows.append(
            {
                "id": case["id"],
                "text": case["text"],
                "selected_memory": (
                    asdict(selected) if selected is not None else None
                ),
                "grade": _grade(selected, case["expected"]),
                "latency_ms": latency_ms,
                "greedy_candidates": (
                    extraction.frame_result.diagnostics[
                        "greedy_candidates"
                    ]
                ),
                "embedding_requested_delta": (
                    extraction.frame_result.diagnostics[
                        "embedding_requested_delta"
                    ]
                ),
                "embedding_computed_delta": (
                    extraction.frame_result.diagnostics[
                        "embedding_computed_delta"
                    ]
                ),
                "frame_count": len(extraction.memories),
            }
        )

    latencies = [float(row["latency_ms"]) for row in rows]
    fields = tuple(rows[0]["grade"]) if rows else ()
    summary = {
        field: {
            "correct": sum(row["grade"][field] for row in rows),
            "total": len(rows),
            "accuracy": (
                sum(row["grade"][field] for row in rows) / len(rows)
                if rows
                else 1.0
            ),
        }
        for field in fields
    }
    output = {
        "purpose": (
            "Closed-choice latency and quality evaluation for the greedy "
            "Fast Observation module. The baseline module is unchanged."
        ),
        "uses_llm": False,
        "case_file": str(args.cases),
        "initialization_ms": initialization_ms,
        "latency": {
            "mean_ms": statistics.fmean(latencies) if latencies else 0.0,
            "median_ms": statistics.median(latencies) if latencies else 0.0,
            "p95_ms": _percentile(latencies, 0.95),
            "max_ms": max(latencies) if latencies else 0.0,
            "under_300ms": sum(value <= 300.0 for value in latencies),
            "total": len(latencies),
        },
        "embedding": {
            "requested_runtime": sum(
                row["embedding_requested_delta"] for row in rows
            ),
            "computed_runtime": sum(
                row["embedding_computed_delta"] for row in rows
            ),
            "cache_hits_runtime": sum(
                row["embedding_requested_delta"]
                - row["embedding_computed_delta"]
                for row in rows
            ),
        },
        "summary": summary,
        "cases": rows,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(output, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "initialization_ms": initialization_ms,
                "latency": output["latency"],
                "embedding": output["embedding"],
                "summary": summary,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
