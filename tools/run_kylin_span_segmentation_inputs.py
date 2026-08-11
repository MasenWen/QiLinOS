from __future__ import annotations

import argparse
import json
import time
from dataclasses import asdict
from pathlib import Path

from src.memory_engine.span_segmentation import (
    AdaptiveGlobalEmbeddingPartitionSegmenter,
)
from tools.evaluate_kylin_span_segmentation import CachedEmbedder


def main() -> None:
    try:
        from src.rag.kylin_embedding_sdk import KylinTextEmbedding
    except ImportError:
        from tools.evaluate_kylin_embedding_preference_object_blind import (
            KylinTextEmbedding,
        )

    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    cases = json.loads(args.cases.read_text(encoding="utf-8"))
    backend = KylinTextEmbedding()
    embedder = CachedEmbedder(backend)
    algorithm = AdaptiveGlobalEmbeddingPartitionSegmenter(
        embedder,
        min_window_chars=4,
        max_window_chars=8,
        step_chars=1,
        min_segment_windows=2,
        slope_multiplier=2.0,
    )
    rows = []
    started = time.perf_counter()
    for case in cases:
        case_started = time.perf_counter()
        result = algorithm.segment(case["text"])
        rows.append(
            {
                "id": case["id"],
                "challenge": case["challenge"],
                "text": case["text"],
                "segments": [segment.text for segment in result.segments],
                "boundaries": [
                    asdict(boundary) for boundary in result.boundaries
                ],
                "algorithm_latency_ms": (
                    time.perf_counter() - case_started
                )
                * 1000.0,
                "diagnostics": result.diagnostics,
            }
        )
    output = {
        "elapsed_ms": (time.perf_counter() - started) * 1000.0,
        "algorithms": {
            algorithm.name: {
                "configuration": {
                    "min_window_chars": 4,
                    "max_window_chars": 8,
                    "step_chars": 1,
                    "min_segment_windows": 2,
                    "slope_multiplier": 2.0,
                },
                "embedding_cache": {
                    "requested": embedder.requested,
                    "computed": embedder.computed,
                    "cache_hits": embedder.requested - embedder.computed,
                },
                "cases": rows,
            }
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(output, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "cases": len(rows),
                "elapsed_ms": output["elapsed_ms"],
                "computed_embeddings": embedder.computed,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
