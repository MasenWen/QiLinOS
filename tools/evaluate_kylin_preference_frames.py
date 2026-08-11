from __future__ import annotations

import argparse
import json
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, Sequence

from src.memory_engine.preference_matching import PreferenceFrameMatcher
from src.memory_engine.span_matching import JiebaSpanTokenizer, SpanMatch
from tools.evaluate_kylin_span_matching import (
    _gold_spans,
    _score_matches,
)
from tools.evaluate_kylin_span_segmentation import CachedEmbedder


DEFAULT_SOURCE_CASES = Path("tests/data/span_segmentation_cases_v2.json")
DEFAULT_MATCHING_CASES = Path(
    "tests/data/span_matching_cases_v2_four_roles.json"
)
DEFAULT_OUTPUT = Path(
    "runtime/results/kylin_preference_frames_v1/"
    "kylin_preference_frames.json"
)


def _hypothesis_matches(result: Any) -> list[SpanMatch]:
    return [
        SpanMatch(
            start=hypothesis.start,
            end=hypothesis.end,
            text=hypothesis.text,
            label=hypothesis.label,
            score=hypothesis.score,
            similarity=hypothesis.similarity,
            margin=hypothesis.null_margin,
            source="+".join(hypothesis.sources),
        )
        for hypothesis in result.hypotheses
    ]


def _group_metrics(
    rows: Sequence[dict[str, Any]],
    group: str,
) -> dict[str, Any]:
    gold_count = 0
    matched_count = 0
    for row in rows:
        gold_count += sum(
            target["group"] == group
            for target in row["candidate_score"]["gold"]
        )
        matched_count += sum(
            alignment["gold"]["group"] == group
            for alignment in row["candidate_score"]["alignments"]
        )
    return {
        "gold": gold_count,
        "matched": matched_count,
        "missed": gold_count - matched_count,
        "recall": matched_count / gold_count if gold_count else 1.0,
    }


def _frame_role_coverage(
    result: Any,
    gold: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    spans = []
    for frame in result.frames:
        spans.append(
            SpanMatch(
                frame.attitude.start,
                frame.attitude.end,
                frame.attitude.text,
                "attitude",
                frame.confidence,
                frame.attitude.similarity,
                frame.attitude.confidence,
                result.algorithm,
            )
        )
        spans.append(
            SpanMatch(
                frame.object.start,
                frame.object.end,
                frame.object.text,
                "object",
                frame.confidence,
                frame.object.similarity,
                frame.object.score,
                result.algorithm,
            )
        )
        if frame.condition is not None:
            spans.append(
                SpanMatch(
                    frame.condition.start,
                    frame.condition.end,
                    frame.condition.text,
                    "condition",
                    frame.confidence,
                    frame.condition.similarity,
                    frame.condition.score,
                    result.algorithm,
                )
            )
        if frame.temporal is not None:
            spans.append(
                SpanMatch(
                    frame.temporal.start,
                    frame.temporal.end,
                    frame.temporal.text,
                    frame.temporal.label,
                    frame.confidence,
                    frame.temporal.confidence,
                    frame.temporal.confidence,
                    result.algorithm,
                )
            )
    return _score_matches(spans, gold)


def main() -> None:
    try:
        from src.rag.kylin_embedding_sdk import KylinTextEmbedding
    except ImportError:
        from tools.evaluate_kylin_embedding_preference_object_blind import (
            KylinTextEmbedding,
        )

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--source-cases",
        type=Path,
        default=DEFAULT_SOURCE_CASES,
    )
    parser.add_argument(
        "--matching-cases",
        type=Path,
        default=DEFAULT_MATCHING_CASES,
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    source = {
        row["id"]: row
        for row in json.loads(args.source_cases.read_text(encoding="utf-8"))
    }
    specifications = json.loads(
        args.matching_cases.read_text(encoding="utf-8")
    )
    embedder = CachedEmbedder(KylinTextEmbedding())
    matcher = PreferenceFrameMatcher(
        embedder,
        tokenizer=JiebaSpanTokenizer(),
    )

    rows = []
    started = time.perf_counter()
    for specification in specifications:
        case = source[specification["id"]]
        gold = _gold_spans(case["text"], specification["expected"])
        case_started = time.perf_counter()
        result = matcher.match(case["text"])
        candidate_score = _score_matches(
            _hypothesis_matches(result),
            gold,
        )
        frame_score = _frame_role_coverage(result, gold)
        rows.append(
            {
                "id": case["id"],
                "text": case["text"],
                "gold": gold,
                "candidate_score": candidate_score,
                "frame_score": frame_score,
                "attitudes": [
                    asdict(attitude)
                    for attitude in result.attitudes
                ],
                "canonical_matches": [
                    asdict(match)
                    for match in result.canonical_matches
                ],
                "frames": [asdict(frame) for frame in result.frames],
                "diagnostics": result.diagnostics,
                "latency_ms": (
                    time.perf_counter() - case_started
                )
                * 1000.0,
            }
        )

    candidate_tp = sum(row["candidate_score"]["tp"] for row in rows)
    candidate_fp = sum(row["candidate_score"]["fp"] for row in rows)
    candidate_fn = sum(row["candidate_score"]["fn"] for row in rows)
    frame_tp = sum(row["frame_score"]["tp"] for row in rows)
    frame_fp = sum(row["frame_score"]["fp"] for row in rows)
    frame_fn = sum(row["frame_score"]["fn"] for row in rows)
    frame_precision = (
        frame_tp / (frame_tp + frame_fp)
        if frame_tp + frame_fp
        else 1.0
    )
    frame_recall = (
        frame_tp / (frame_tp + frame_fn)
        if frame_tp + frame_fn
        else 1.0
    )
    output = {
        "purpose": (
            "Fixed-set black-box evaluation of dual-path high-recall role "
            "candidates and contextual preference frames."
        ),
        "source_cases": str(args.source_cases),
        "matching_cases": str(args.matching_cases),
        "elapsed_ms": (time.perf_counter() - started) * 1000.0,
        "embedding_cache": {
            "requested": embedder.requested,
            "computed": embedder.computed,
            "cache_hits": embedder.requested - embedder.computed,
        },
        "candidate_layer": {
            "tp": candidate_tp,
            "fp": candidate_fp,
            "fn": candidate_fn,
            "recall": (
                candidate_tp / (candidate_tp + candidate_fn)
                if candidate_tp + candidate_fn
                else 1.0
            ),
            "by_group": {
                group: _group_metrics(rows, group)
                for group in (
                    "condition",
                    "temporal",
                    "attitude",
                    "object",
                )
            },
            "note": (
                "Candidate precision is intentionally not a release gate; "
                "overlapping cross-role hypotheses are resolved downstream."
            ),
        },
        "frame_layer": {
            "tp": frame_tp,
            "fp": frame_fp,
            "fn": frame_fn,
            "role_coverage_precision": frame_precision,
            "role_coverage_recall": frame_recall,
            "role_coverage_f1": (
                2.0
                * frame_precision
                * frame_recall
                / (frame_precision + frame_recall)
                if frame_precision + frame_recall
                else 0.0
            ),
            "frame_count": sum(len(row["frames"]) for row in rows),
        },
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
                "candidate_layer": output["candidate_layer"],
                "frame_layer": output["frame_layer"],
                "embedding_cache": output["embedding_cache"],
                "elapsed_ms": output["elapsed_ms"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
