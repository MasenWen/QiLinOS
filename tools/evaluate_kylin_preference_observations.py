from __future__ import annotations

import argparse
import json
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, Mapping

from src.memory_engine.preference_matching import (
    PreferenceFrameMatcher,
    PreferenceObservationMemory,
    PreferenceObservationMemoryExtractor,
    PreferenceObservationOptions,
    PreferenceSourceObservation,
)
from src.memory_engine.span_matching import JiebaSpanTokenizer
from tools.evaluate_kylin_span_segmentation import CachedEmbedder


DEFAULT_CASES = Path(
    "tests/data/preference_observation_choices_v1.json"
)
DEFAULT_OUTPUT = Path(
    "runtime/results/kylin_preference_observations_v1/"
    "kylin_preference_observations.json"
)


def _options(value: Mapping[str, Any]) -> PreferenceObservationOptions:
    return PreferenceObservationOptions(
        condition_tag_ids=tuple(value.get("condition_tag_ids") or ()),
        object_tag_ids=tuple(value.get("object_tag_ids") or ()),
        temporal_labels=tuple(value.get("temporal_labels") or ()),
    )


def _attitude_direction(value: float) -> str:
    if value > 0.10:
        return "positive"
    if value < -0.10:
        return "negative"
    return "uncertain"


def _grade(
    memory: PreferenceObservationMemory | None,
    expected: Mapping[str, Any],
) -> dict[str, bool]:
    if memory is None:
        return {
            "memory_formed": False,
            "condition": False,
            "object": False,
            "attitude": False,
            "temporal": False,
            "promotion_seed": False,
            "explicit_long_term": False,
            "evidence_ready": False,
            "all_correct": False,
        }
    values = {
        "memory_formed": True,
        "condition": (
            memory.condition_tag_id == expected["condition_tag_id"]
        ),
        "object": memory.object_tag_id == expected["object_tag_id"],
        "attitude": (
            _attitude_direction(memory.attitude_value)
            == expected["attitude_direction"]
        ),
        "temporal": memory.temporal_label == expected["temporal_label"],
        "promotion_seed": math_isclose(
            memory.promotion_seed,
            float(expected["promotion_seed"]),
        ),
        "explicit_long_term": (
            memory.explicit_long_term
            is bool(expected["explicit_long_term"])
        ),
        "evidence_ready": bool(
            memory.memory_id
            and memory.observation_id
            and memory.object_tag_id
        ),
    }
    values["all_correct"] = all(values.values())
    return values


def math_isclose(left: float, right: float) -> bool:
    return abs(float(left) - float(right)) <= 1e-9


def main() -> None:
    try:
        from src.rag.kylin_embedding_sdk import KylinTextEmbedding
    except ImportError:
        from tools.evaluate_kylin_embedding_preference_object_blind import (
            KylinTextEmbedding,
        )

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--cases",
        type=Path,
        default=DEFAULT_CASES,
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    cases = json.loads(args.cases.read_text(encoding="utf-8"))
    embedder = CachedEmbedder(KylinTextEmbedding())
    extractor = PreferenceObservationMemoryExtractor(
        PreferenceFrameMatcher(
            embedder,
            tokenizer=JiebaSpanTokenizer(),
        )
    )
    rows = []
    started = time.perf_counter()
    for index, case in enumerate(cases):
        observation = PreferenceSourceObservation(
            observation_id=f"obs-choice-{case['id']}",
            source_event_id=f"choice-event-{case['id']}",
            user_id="choice-eval-user",
            session_id=f"choice-eval-{case['id']}",
            event_time=f"2026-07-27T00:{index:02d}:00+00:00",
            content=case["text"],
            source_reliability=1.0,
            privacy={
                "sensitivity": "normal",
                "deletion_scope": "user",
            },
        )
        case_started = time.perf_counter()
        extraction = extractor.extract(
            observation,
            options=_options(case["options"]),
        )
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
        grade = _grade(selected, case["expected"])
        rows.append(
            {
                "id": case["id"],
                "text": case["text"],
                "options": case["options"],
                "expected": case["expected"],
                "selected_memory": (
                    asdict(selected) if selected is not None else None
                ),
                "all_memories": [
                    asdict(memory)
                    for memory in extraction.memories
                ],
                "evidence": [
                    item.to_dict()
                    for item in extraction.evidence
                ],
                "grade": grade,
                "latency_ms": (
                    time.perf_counter() - case_started
                )
                * 1000.0,
            }
        )

    fields = (
        "memory_formed",
        "condition",
        "object",
        "attitude",
        "temporal",
        "promotion_seed",
        "explicit_long_term",
        "evidence_ready",
        "all_correct",
    )
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
            "Closed-choice Kylin Embedding evaluation from dialogue "
            "Observation to auditable preference memory and Evidence."
        ),
        "case_file": str(args.cases),
        "selection_rule": (
            "Highest extraction_confidence; expected labels are never used "
            "for candidate selection."
        ),
        "uses_llm": False,
        "elapsed_ms": (time.perf_counter() - started) * 1000.0,
        "embedding_cache": {
            "requested": embedder.requested,
            "computed": embedder.computed,
            "cache_hits": embedder.requested - embedder.computed,
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
                "summary": summary,
                "embedding_cache": output["embedding_cache"],
                "elapsed_ms": output["elapsed_ms"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
