from __future__ import annotations

import argparse
import json
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, Sequence

from src.memory_engine.span_matching import (
    CONSERVATIVE_GROUP_SCORE_THRESHOLDS_V1,
    FOUR_ROLE_GROUP_SCORE_THRESHOLDS_V1,
    JiebaSpanTokenizer,
    MultiPrototypeContrastiveMatcher,
    PrototypeEmbeddingScorer,
    SemiMarkovSpanLatticeMatcher,
    SpanMatch,
    label_group,
)
from src.memory_engine.span_segmentation import (
    AdaptiveGlobalEmbeddingPartitionSegmenter,
    Segment,
    build_result,
    punctuation_boundaries,
)
from tools.evaluate_kylin_span_segmentation import CachedEmbedder


DEFAULT_SOURCE_CASES = Path("tests/data/span_segmentation_cases_v2.json")
DEFAULT_MATCHING_CASES = Path("tests/data/span_matching_cases_v1.json")
DEFAULT_OUTPUT = Path(
    "runtime/results/kylin_span_matching_v1/kylin_span_matching.json"
)
PRIMARY_GROUPS = frozenset(
    {"condition", "attitude", "object", "temporal"}
)


def _occurrences(text: str, needle: str) -> list[int]:
    starts = []
    cursor = 0
    while True:
        start = text.find(needle, cursor)
        if start < 0:
            return starts
        starts.append(start)
        cursor = start + 1


def _gold_spans(
    text: str,
    definitions: Sequence[dict[str, Any]],
) -> list[dict[str, Any]]:
    spans = []
    for definition in definitions:
        value = str(definition["text"])
        occurrence = int(definition.get("occurrence", 0))
        starts = _occurrences(text, value)
        if occurrence >= len(starts):
            raise ValueError(
                f"matching_gold_not_found:{value!r}:occurrence={occurrence}"
            )
        start = starts[occurrence]
        spans.append(
            {
                **definition,
                "start": start,
                "end": start + len(value),
                "group": label_group(str(definition["label"])),
            }
        )
    return sorted(spans, key=lambda span: (span["start"], span["end"]))


def _pair_quality(predicted: SpanMatch, gold: dict[str, Any]) -> float | None:
    if label_group(predicted.label) != gold["group"]:
        return None
    overlap = max(
        0,
        min(predicted.end, gold["end"]) - max(predicted.start, gold["start"]),
    )
    if overlap <= 0:
        return None
    coverage = overlap / (gold["end"] - gold["start"])
    foreign = (predicted.end - predicted.start) - overlap
    if coverage < 0.50 or foreign > 4:
        return None
    return coverage - 0.04 * foreign


def _score_matches(
    predicted: Sequence[SpanMatch],
    gold: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    relevant = [
        match for match in predicted if label_group(match.label) in PRIMARY_GROUPS
    ]
    pairs = []
    for predicted_index, match in enumerate(relevant):
        for gold_index, target in enumerate(gold):
            quality = _pair_quality(match, target)
            if quality is not None:
                pairs.append(
                    (
                        quality,
                        predicted_index,
                        gold_index,
                    )
                )
    matched_predicted = set()
    matched_gold = set()
    alignments = []
    for quality, predicted_index, gold_index in sorted(
        pairs,
        key=lambda value: (-value[0], value[1], value[2]),
    ):
        if predicted_index in matched_predicted or gold_index in matched_gold:
            continue
        matched_predicted.add(predicted_index)
        matched_gold.add(gold_index)
        match = relevant[predicted_index]
        target = gold[gold_index]
        alignments.append(
            {
                "predicted": asdict(match),
                "gold": target,
                "quality": quality,
                "subtype_correct": match.label == target["label"],
            }
        )
    true_positive = len(matched_gold)
    false_positive = len(relevant) - true_positive
    false_negative = len(gold) - true_positive
    precision = (
        true_positive / (true_positive + false_positive)
        if true_positive + false_positive
        else 1.0 if not gold else 0.0
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
    subtype_correct = sum(
        bool(alignment["subtype_correct"]) for alignment in alignments
    )
    return {
        "gold": list(gold),
        "predicted": [asdict(match) for match in relevant],
        "alignments": alignments,
        "tp": true_positive,
        "fp": false_positive,
        "fn": false_negative,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "score_10": f1 * 10.0,
        "subtype_correct": subtype_correct,
        "subtype_accuracy_on_hits": (
            subtype_correct / true_positive if true_positive else 0.0
        ),
    }


def _aggregate(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    true_positive = sum(row["score"]["tp"] for row in rows)
    false_positive = sum(row["score"]["fp"] for row in rows)
    false_negative = sum(row["score"]["fn"] for row in rows)
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
    subtype_correct = sum(
        row["score"]["subtype_correct"] for row in rows
    )
    return {
        "cases": len(rows),
        "gold_spans": true_positive + false_negative,
        "predicted_spans": true_positive + false_positive,
        "tp": true_positive,
        "fp": false_positive,
        "fn": false_negative,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "score_10": f1 * 10.0,
        "subtype_correct": subtype_correct,
        "subtype_accuracy_on_hits": (
            subtype_correct / true_positive if true_positive else 0.0
        ),
    }


def _segments(
    name: str,
    text: str,
    adaptive: AdaptiveGlobalEmbeddingPartitionSegmenter,
) -> tuple[Segment, ...]:
    if name == "punctuation_only":
        return build_result(
            name,
            text,
            punctuation_boundaries(text),
        ).segments
    if name == adaptive.name:
        return adaptive.segment(text).segments
    raise ValueError(f"unknown_segmenter:{name}")


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
    parser.add_argument(
        "--group-threshold-profile",
        choices=("none", "conservative_v1", "four_roles_v1"),
        default="none",
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
    cases = [
        {
            **source[specification["id"]],
            "expected": specification["expected"],
        }
        for specification in specifications
    ]

    backend = KylinTextEmbedding()
    embedder = CachedEmbedder(backend)
    tokenizer = JiebaSpanTokenizer()
    scorer = PrototypeEmbeddingScorer(embedder)
    threshold_profiles = {
        "none": {},
        "conservative_v1": CONSERVATIVE_GROUP_SCORE_THRESHOLDS_V1,
        "four_roles_v1": FOUR_ROLE_GROUP_SCORE_THRESHOLDS_V1,
    }
    group_score_thresholds = threshold_profiles[
        args.group_threshold_profile
    ]
    matchers = (
        MultiPrototypeContrastiveMatcher(
            scorer,
            tokenizer,
            group_score_thresholds=group_score_thresholds,
        ),
        SemiMarkovSpanLatticeMatcher(
            scorer,
            tokenizer,
            group_score_thresholds=group_score_thresholds,
        ),
    )
    adaptive = AdaptiveGlobalEmbeddingPartitionSegmenter(
        embedder,
        min_window_chars=4,
        max_window_chars=8,
        step_chars=1,
        min_segment_windows=2,
        slope_multiplier=2.0,
    )
    segmenter_names = ("punctuation_only", adaptive.name)
    segmentations = {
        (segmenter_name, case["id"]): _segments(
            segmenter_name,
            case["text"],
            adaptive,
        )
        for segmenter_name in segmenter_names
        for case in cases
    }

    outputs = {}
    started = time.perf_counter()
    for segmenter_name in segmenter_names:
        for matcher in matchers:
            rows = []
            for case in cases:
                segments = segmentations[(segmenter_name, case["id"])]
                matched = []
                diagnostics = []
                case_started = time.perf_counter()
                for segment in segments:
                    result = matcher.match(
                        segment.text,
                        offset=segment.start,
                    )
                    matched.extend(result.matches)
                    diagnostics.append(
                        {
                            "segment": asdict(segment),
                            "matcher": result.diagnostics,
                        }
                    )
                matched.sort(key=lambda match: (match.start, match.end))
                gold = _gold_spans(case["text"], case["expected"])
                rows.append(
                    {
                        "id": case["id"],
                        "text": case["text"],
                        "segments": [asdict(segment) for segment in segments],
                        "matches": [asdict(match) for match in matched],
                        "score": _score_matches(matched, gold),
                        "diagnostics": diagnostics,
                        "latency_ms": (
                            time.perf_counter() - case_started
                        )
                        * 1000.0,
                    }
                )
            key = f"{segmenter_name}+{matcher.name}"
            outputs[key] = {
                "segmenter": segmenter_name,
                "matcher": matcher.name,
                "metrics": _aggregate(rows),
                "cases": rows,
            }

    output = {
        "purpose": (
            "Black-box comparison of two embedding-backed span matchers over "
            "two interchangeable segmentation routes."
        ),
        "case_file": str(args.matching_cases),
        "elapsed_ms": (time.perf_counter() - started) * 1000.0,
        "embedding_cache": {
            "requested": embedder.requested,
            "computed": embedder.computed,
            "cache_hits": embedder.requested - embedder.computed,
        },
        "config": {
            "prototype_min_similarity": scorer.min_similarity,
            "prototype_min_margin": scorer.min_margin,
            "group_threshold_profile": args.group_threshold_profile,
            "group_score_thresholds": group_score_thresholds,
            "foreign_character_tolerance": 4,
        },
        "combinations": outputs,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(output, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                key: value["metrics"]
                for key, value in outputs.items()
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
