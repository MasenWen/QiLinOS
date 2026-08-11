from __future__ import annotations

import argparse
import json
import math
import statistics
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, Sequence

from src.memory_engine.span_segmentation import (
    AdaptiveGlobalEmbeddingPartitionSegmenter,
    CharacterGapProposer,
    EmbeddingCandidateSegmenter,
    GlobalEmbeddingPartitionSegmenter,
    SemanticTilingSegmenter,
)


DEFAULT_CASES = (
    Path(__file__).parents[1]
    / "tests"
    / "data"
    / "span_segmentation_cases_v2.json"
)

SEMANTIC_TILING_PROFILES = {
    "baseline": {
        "window_chars": 8,
        "min_segment_chars": 2,
        "smoothing_radius": 1,
        "threshold_std": 0.25,
        "target_segment_chars": 6,
    },
    "moderate": {
        "window_chars": 8,
        "min_segment_chars": 3,
        "smoothing_radius": 2,
        "threshold_std": 0.35,
        "target_segment_chars": 8,
    },
    "conservative": {
        "window_chars": 8,
        "min_segment_chars": 4,
        "smoothing_radius": 2,
        "threshold_std": 0.50,
        "target_segment_chars": 10,
    },
}

CANDIDATE_DECODER_PROFILES = {
    "baseline": {
        "window_chars": 8,
        "semantic_weight": 0.75,
        "threshold": 0.59,
        "min_segment_chars": 2,
        "target_segment_chars": 6,
    },
    "moderate": {
        "window_chars": 8,
        "semantic_weight": 0.75,
        "threshold": 0.64,
        "min_segment_chars": 3,
        "target_segment_chars": 8,
    },
    "conservative": {
        "window_chars": 8,
        "semantic_weight": 0.75,
        "threshold": 0.68,
        "min_segment_chars": 4,
        "target_segment_chars": 10,
    },
}


class CachedEmbedder:
    def __init__(self, backend: Any):
        self.backend = backend
        self.cache: dict[str, Any] = {}
        self.requested = 0
        self.computed = 0

    def embed(self, texts: list[str]) -> list[Any]:
        self.requested += len(texts)
        missing = list(dict.fromkeys(text for text in texts if text not in self.cache))
        if missing:
            vectors = self.backend.embed(missing)
            self.computed += len(missing)
            for text, vector in zip(missing, vectors):
                self.cache[text] = vector.copy()
        return [self.cache[text] for text in texts]


def _boundary_positions(segments: Sequence[str]) -> set[int]:
    positions = set()
    cursor = 0
    for segment in segments[:-1]:
        cursor += len(segment)
        positions.add(cursor)
    return positions


def _score_case(
    predicted: set[int],
    text_length: int,
    acceptable_segmentations: Sequence[Sequence[str]],
) -> dict[str, Any]:
    alternatives = [
        _boundary_positions(segments)
        for segments in acceptable_segmentations
    ]
    required = set.intersection(*alternatives)
    allowed = set.union(*alternatives)
    optional = allowed - required
    forbidden = set(range(1, text_length)) - allowed
    true_positive = len(predicted & required)
    false_positive = len(predicted & forbidden)
    false_negative = len(required - predicted)
    precision = (
        true_positive / (true_positive + false_positive)
        if true_positive + false_positive
        else 1.0 if not required else 0.0
    )
    recall = (
        true_positive / (true_positive + false_negative)
        if true_positive + false_negative
        else 1.0
    )
    f1 = (
        2.0 * precision * recall / (precision + recall)
        if precision + recall
        else 0.0
    )
    return {
        "required": sorted(required),
        "optional": sorted(optional),
        "forbidden_prediction_count": false_positive,
        "optional_prediction_count": len(predicted & optional),
        "tp": true_positive,
        "fp": false_positive,
        "fn": false_negative,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "score_10": f1 * 10.0,
        "exact": false_positive == 0 and false_negative == 0,
        "fragmentation_free": false_positive == 0,
        "all_required_boundaries_found": false_negative == 0,
    }


def _aggregate(case_scores: Sequence[dict[str, Any]]) -> dict[str, Any]:
    true_positive = sum(score["tp"] for score in case_scores)
    false_positive = sum(score["fp"] for score in case_scores)
    false_negative = sum(score["fn"] for score in case_scores)
    precision = (
        true_positive / (true_positive + false_positive)
        if true_positive + false_positive
        else 0.0
    )
    recall = (
        true_positive / (true_positive + false_negative)
        if true_positive + false_negative
        else 0.0
    )
    f1 = (
        2.0 * precision * recall / (precision + recall)
        if precision + recall
        else 0.0
    )
    return {
        "cases": len(case_scores),
        "boundary_precision": precision,
        "boundary_recall": recall,
        "boundary_f1": f1,
        "score_10": f1 * 10.0,
        "exact_case_accuracy": (
            sum(bool(score["exact"]) for score in case_scores) / len(case_scores)
            if case_scores
            else 0.0
        ),
        "overcuts": false_positive,
        "undercuts": false_negative,
        "true_positive_boundaries": true_positive,
        "fragmentation_free_case_rate": (
            sum(bool(score["fragmentation_free"]) for score in case_scores)
            / len(case_scores)
            if case_scores
            else 0.0
        ),
        "complete_required_boundary_case_rate": (
            sum(
                bool(score["all_required_boundaries_found"])
                for score in case_scores
            )
            / len(case_scores)
            if case_scores
            else 0.0
        ),
    }


def _category_metrics(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    categories = sorted({row["challenge"] for row in rows})
    return {
        category: _aggregate(
            [row["score"] for row in rows if row["challenge"] == category]
        )
        for category in categories
    }


def _semantic_boundary_metrics(
    rows: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    scores = []
    cases_with_required = 0
    exact_required_cases = 0
    for row in rows:
        hard = {
            int(boundary["position"])
            for boundary in row["boundaries"]
            if boundary["hard"]
        }
        predicted = {
            int(boundary["position"])
            for boundary in row["boundaries"]
            if not boundary["hard"]
        }
        required = set(row["score"]["required"]) - hard
        optional = set(row["score"]["optional"])
        true_positive = len(predicted & required)
        false_positive = len(predicted - required - optional)
        false_negative = len(required - predicted)
        score = {
            "tp": true_positive,
            "fp": false_positive,
            "fn": false_negative,
            "exact": false_positive == 0 and false_negative == 0,
            "fragmentation_free": false_positive == 0,
            "all_required_boundaries_found": false_negative == 0,
        }
        scores.append(score)
        if required:
            cases_with_required += 1
            exact_required_cases += int(score["exact"])
    aggregate = _aggregate(scores)
    aggregate["required_semantic_boundaries"] = sum(
        score["tp"] + score["fn"] for score in scores
    )
    aggregate["cases_with_required_semantic_boundaries"] = cases_with_required
    aggregate["exact_required_semantic_case_rate"] = (
        exact_required_cases / cases_with_required
        if cases_with_required
        else 1.0
    )
    return aggregate


def _percentile(values: Sequence[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, math.ceil(percentile * len(ordered)) - 1)
    return ordered[index]


def main() -> None:
    try:
        from src.rag.kylin_embedding_sdk import KylinTextEmbedding
    except ImportError:
        # The server-side evaluation checkout intentionally contains only the
        # memory-engine package. Reuse the already validated SDK binding from
        # the earlier object-blind embedding experiment in that environment.
        from tools.evaluate_kylin_embedding_preference_object_blind import (
            KylinTextEmbedding,
        )

    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path("runtime/results/kylin_span_segmentation"),
    )
    parser.add_argument(
        "--algorithm",
        choices=[
            "all",
            "kylin_semantic_tiling",
            "kylin_embedding_global_partition",
            "kylin_embedding_global_adaptive",
            "kylin_candidate_decoder",
        ],
        default="all",
    )
    parser.add_argument(
        "--profile",
        choices=["baseline", "moderate", "conservative"],
        default="baseline",
        help=(
            "Predeclared small parameter adjustment. The global partition "
            "algorithm only supports the baseline profile."
        ),
    )
    args = parser.parse_args()
    if (
        args.profile != "baseline"
        and args.algorithm
        in {
            "all",
            "kylin_embedding_global_partition",
            "kylin_embedding_global_adaptive",
        }
    ):
        parser.error(
            "non-baseline profiles only apply to semantic tiling "
            "or candidate decoder"
        )

    cases = json.loads(args.cases.read_text(encoding="utf-8"))
    args.out_dir.mkdir(parents=True, exist_ok=True)

    started = time.perf_counter()
    backend = KylinTextEmbedding()
    semantic_config = SEMANTIC_TILING_PROFILES[args.profile]
    candidate_config = CANDIDATE_DECODER_PROFILES[args.profile]
    algorithm_configs = {
        "kylin_semantic_tiling": semantic_config,
        "kylin_embedding_global_partition": {
            "window_chars": 8,
            "step_chars": 2,
            "min_segment_windows": 2,
            "penalty": 0.10,
        },
        "kylin_embedding_global_adaptive": {
            "min_window_chars": 4,
            "max_window_chars": 8,
            "step_chars": 1,
            "min_segment_windows": 2,
            "slope_multiplier": 2.0,
        },
        "kylin_candidate_decoder": candidate_config,
    }
    algorithm_factories = [
        (
            "kylin_semantic_tiling",
            lambda embedder: SemanticTilingSegmenter(
                embedder,
                **semantic_config,
            ),
        ),
        (
            "kylin_embedding_global_partition",
            lambda embedder: GlobalEmbeddingPartitionSegmenter(
                embedder,
                window_chars=8,
                step_chars=2,
                min_segment_windows=2,
                penalty=0.10,
            ),
        ),
        (
            "kylin_embedding_global_adaptive",
            lambda embedder: AdaptiveGlobalEmbeddingPartitionSegmenter(
                embedder,
                min_window_chars=4,
                max_window_chars=8,
                step_chars=1,
                min_segment_windows=2,
                slope_multiplier=2.0,
            ),
        ),
        (
            "kylin_candidate_decoder",
            lambda embedder: EmbeddingCandidateSegmenter(
                embedder,
                [CharacterGapProposer()],
                **candidate_config,
            ),
        ),
    ]
    if args.algorithm != "all":
        algorithm_factories = [
            item for item in algorithm_factories if item[0] == args.algorithm
        ]

    raw_model_info = getattr(backend, "model_info", None)
    if isinstance(raw_model_info, dict):
        model_info = dict(raw_model_info)
    else:
        model_info = {
            "name": getattr(backend, "_model_name", "unknown"),
            "dim": getattr(backend, "dim", None),
        }
    model_dimension = int(model_info.get("dim") or 0)

    outputs: dict[str, Any] = {}
    for expected_name, factory in algorithm_factories:
        embedder = CachedEmbedder(backend)
        algorithm = factory(embedder)
        if algorithm.name != expected_name:
            raise ValueError("algorithm_factory_name_mismatch")
        rows = []
        scores = []
        latencies_ms = []
        for case in cases:
            algorithm_started = time.perf_counter()
            result = algorithm.segment(case["text"])
            latency_ms = (time.perf_counter() - algorithm_started) * 1000.0
            latencies_ms.append(latency_ms)
            predicted = set(result.boundary_positions)
            score = _score_case(
                predicted,
                len(case["text"]),
                case["acceptable_segmentations"],
            )
            scores.append(score)
            rows.append(
                {
                    "id": case["id"],
                    "challenge": case["challenge"],
                    "text": case["text"],
                    "segments": [segment.text for segment in result.segments],
                    "boundaries": [asdict(boundary) for boundary in result.boundaries],
                    "score": score,
                    "algorithm_latency_ms": latency_ms,
                    "diagnostics": result.diagnostics,
                }
            )
        outputs[algorithm.name] = {
            "configuration": algorithm_configs[algorithm.name],
            "metrics": _aggregate(scores),
            "semantic_boundary_metrics": _semantic_boundary_metrics(rows),
            "metrics_by_challenge": _category_metrics(rows),
            "performance": {
                "algorithm_time_only": True,
                "total_ms": sum(latencies_ms),
                "mean_ms": statistics.mean(latencies_ms),
                "median_ms": statistics.median(latencies_ms),
                "p95_ms": _percentile(latencies_ms, 0.95),
            },
            "space": {
                "cached_embedding_count": embedder.computed,
                "estimated_embedding_cache_bytes": (
                    embedder.computed * model_dimension * 4
                ),
                "complexity_note": (
                    "Estimate covers float32 vectors only; shared SDK model "
                    "memory is excluded because it is identical for all algorithms."
                ),
            },
            "embedding_cache": {
                "requested": embedder.requested,
                "computed": embedder.computed,
                "cache_hits": embedder.requested - embedder.computed,
            },
            "cases": rows,
        }

    backend.close()
    payload = {
        "purpose": "Evaluate label-free sentence-internal boundary segmentation.",
        "model_info": model_info,
        "case_file": str(args.cases),
        "profile": args.profile,
        "elapsed_ms": (time.perf_counter() - started) * 1000.0,
        "algorithms": outputs,
    }
    output_path = args.out_dir / "kylin_span_segmentation.json"
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "output": str(output_path),
                "model_info": model_info,
                "elapsed_ms": payload["elapsed_ms"],
                "metrics": {
                    name: value["metrics"]
                    for name, value in outputs.items()
                },
                "performance": {
                    name: value["performance"]
                    for name, value in outputs.items()
                },
                "space": {
                    name: value["space"]
                    for name, value in outputs.items()
                },
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
