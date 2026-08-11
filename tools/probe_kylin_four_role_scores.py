from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from src.memory_engine.span_matching import (
    CandidateSpan,
    PrototypeEmbeddingScorer,
    label_group,
)
from tools.evaluate_kylin_span_matching import (
    CachedEmbedder,
    _gold_spans,
)


DEFAULT_SOURCE_CASES = Path("tests/data/span_segmentation_cases_v2.json")
DEFAULT_MATCHING_CASES = Path(
    "tests/data/span_matching_cases_v2_four_roles.json"
)
DEFAULT_OUTPUT = Path(
    "runtime/results/kylin_span_matching_v2_four_roles_raw/"
    "gold_span_probes.json"
)


def _confidence_score(assessment: Any) -> float:
    length_penalty = 0.004 * max(
        0,
        len(assessment.candidate.text) - 6,
    )
    return (
        assessment.similarity
        + 1.5 * assessment.margin
        - length_penalty
    )


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
    probes = []
    for specification in specifications:
        case = source[specification["id"]]
        for gold in _gold_spans(case["text"], specification["expected"]):
            probes.append(
                {
                    "case_id": case["id"],
                    "gold": gold,
                    "candidate": CandidateSpan(
                        start=gold["start"],
                        end=gold["end"],
                        text=gold["text"],
                        token_count=0,
                    ),
                }
            )

    embedder = CachedEmbedder(KylinTextEmbedding())
    scorer = PrototypeEmbeddingScorer(embedder)
    assessments = scorer.assess(
        [probe["candidate"] for probe in probes]
    )
    rows = []
    for probe, assessment in zip(probes, assessments):
        ranked = sorted(
            assessment.label_scores.items(),
            key=lambda item: (-item[1], item[0]),
        )
        rows.append(
            {
                "case_id": probe["case_id"],
                "gold": probe["gold"],
                "candidate": asdict(probe["candidate"]),
                "predicted_label": assessment.label,
                "predicted_group": label_group(assessment.label),
                "similarity": assessment.similarity,
                "margin": assessment.margin,
                "confidence_score": _confidence_score(assessment),
                "accepted": assessment.accepted,
                "ranked_labels": [
                    {"label": label, "similarity": similarity}
                    for label, similarity in ranked
                ],
            }
        )

    output = {
        "matching_cases": str(args.matching_cases),
        "prototype_min_similarity": scorer.min_similarity,
        "prototype_min_margin": scorer.min_margin,
        "embedding_cache": {
            "requested": embedder.requested,
            "computed": embedder.computed,
            "cache_hits": embedder.requested - embedder.computed,
        },
        "probes": rows,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(output, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            [
                {
                    "case_id": row["case_id"],
                    "text": row["gold"]["text"],
                    "gold": row["gold"]["label"],
                    "predicted": row["predicted_label"],
                    "score": row["confidence_score"],
                }
                for row in rows
                if row["gold"]["group"] == "condition"
            ],
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
