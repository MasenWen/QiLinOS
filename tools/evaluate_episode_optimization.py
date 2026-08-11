from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from typing import Any, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.memory_engine.episode_optimization import (
    EpisodeBoundaryRepairConfig,
    EpisodeOptimizationEvent,
    GlobalEpisodeDecoderConfig,
    boundaries_from_assignments,
    decode_episode_boundaries,
    repair_episode_boundaries,
)
from tools.evaluate_condition_object_episode_edges import (
    DEFAULT_OBJECT_BRIDGE_TAG_IDS,
    EventSemanticMatch,
    _error_examples,
    _evaluate_groups,
    _read_matches,
    _semantic_groups,
)


DEFAULT_MATCHES = Path(
    "outputs/dialogue_condition_object_episode/"
    "conservative_bridge.json"
)
DEFAULT_OUTPUT = Path(
    "outputs/dialogue_condition_object_episode/"
    "episode_optimization.json"
)


def _raw_match_rows(path: Path) -> list[Mapping[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    source = payload.get("matches", payload)
    if not isinstance(source, list):
        raise ValueError("matches must be a list")
    return [row for row in source if isinstance(row, Mapping)]


def _condition_score_view(
    row: Mapping[str, Any],
    *,
    min_top_similarity: float,
    min_top_margin: float,
) -> dict[str, float]:
    saved = row.get("condition_view_scores")
    if isinstance(saved, Mapping):
        scores = {
            str(tag_id): float(score)
            for tag_id, score in saved.items()
            if tag_id
        }
    else:
        scores: dict[str, float] = {}
        for match in row.get("canonical_matches", ()):
            if not isinstance(match, Mapping):
                continue
            if match.get("group") != "condition":
                continue
            tag_id = str(match.get("tag_id") or "")
            if not tag_id:
                continue
            similarity = float(match.get("similarity") or 0.0)
            if match.get("exact_alias"):
                similarity = 1.0
            scores[tag_id] = max(scores.get(tag_id, -1.0), similarity)
    if len(scores) < 2:
        return {}
    ranked = sorted(scores.values(), reverse=True)
    if (
        ranked[0] < min_top_similarity
        or ranked[0] - ranked[1] < min_top_margin
    ):
        return {}
    return scores


def _optimization_events(
    rows: Sequence[EventSemanticMatch],
    raw_rows: Sequence[Mapping[str, Any]],
    *,
    min_top_similarity: float,
    min_top_margin: float,
) -> tuple[EpisodeOptimizationEvent, ...]:
    if len(rows) != len(raw_rows):
        raise ValueError("parsed and raw match counts differ")
    events = []
    for row, raw in zip(rows, raw_rows, strict=True):
        if row.event_id != str(raw.get("event_id") or ""):
            raise ValueError("parsed and raw match order differs")
        is_soft_fallback = (
            row.condition_match_source
            == "short_context_fallback"
        )
        saved_scores = raw.get("condition_view_scores", {})
        soft_scores = (
            {
                str(tag_id): float(score)
                for tag_id, score in saved_scores.items()
                if tag_id
            }
            if is_soft_fallback and isinstance(saved_scores, Mapping)
            else {}
        )
        events.append(
            EpisodeOptimizationEvent(
                event_id=row.event_id,
                condition_tag_id=(
                    row.condition_tag_id
                    if row.condition_match_source == "primary"
                    else None
                ),
                condition_scores=(
                    {}
                    if row.condition_match_source == "primary"
                    and row.condition_tag_id
                    else soft_scores
                    or _condition_score_view(
                        raw,
                        min_top_similarity=min_top_similarity,
                        min_top_margin=min_top_margin,
                    )
                ),
                object_tag_ids=(
                    (row.object_tag_id,) if row.object_tag_id else ()
                ),
            )
        )
    return tuple(events)


def _metrics(
    rows: Sequence[EventSemanticMatch],
    assignments: Mapping[str, str],
) -> dict[str, Any]:
    ordered_ids = [row.event_id for row in rows]
    gold = {row.event_id: row.gold_episode_id for row in rows}
    return _evaluate_groups(ordered_ids, gold, assignments)


def evaluate(
    rows: Sequence[EventSemanticMatch],
    raw_rows: Sequence[Mapping[str, Any]],
    *,
    min_top_similarity: float,
    min_top_margin: float,
) -> dict[str, Any]:
    events = _optimization_events(
        rows,
        raw_rows,
        min_top_similarity=min_top_similarity,
        min_top_margin=min_top_margin,
    )
    baseline_assignments, baseline_decisions = _semantic_groups(
        rows,
        use_condition=True,
        use_object=True,
        time_fallback_seconds=None,
        object_bridge_tag_ids=DEFAULT_OBJECT_BRIDGE_TAG_IDS,
    )
    baseline_boundaries = boundaries_from_assignments(
        events,
        baseline_assignments,
    )

    repair_started = time.perf_counter()
    repaired = repair_episode_boundaries(
        events,
        baseline_boundaries,
        config=EpisodeBoundaryRepairConfig(
            relation_object_tag_ids=DEFAULT_OBJECT_BRIDGE_TAG_IDS,
        ),
    )
    repair_ms = (time.perf_counter() - repair_started) * 1000.0

    decoder_started = time.perf_counter()
    decoded = decode_episode_boundaries(
        events,
        baseline_boundaries,
        config=GlobalEpisodeDecoderConfig(
            relation_object_tag_ids=DEFAULT_OBJECT_BRIDGE_TAG_IDS,
        ),
    )
    decoder_ms = (time.perf_counter() - decoder_started) * 1000.0

    gold = {row.event_id: row.gold_episode_id for row in rows}
    evidence_events = [
        event
        for event in events
        if event.condition_tag_id is None and event.condition_scores
    ]
    changed_decisions = [
        decision
        for decision in repaired.decisions
        if decision.changed
    ]
    return {
        "purpose": (
            "Offline, leakage-free comparison of conservative boundary "
            "repair and global semi-Markov Episode decoding."
        ),
        "gold_used_after_grouping_only": True,
        "condition_score_gate": {
            "min_top_similarity": min_top_similarity,
            "min_top_margin": min_top_margin,
            "null_condition_events_with_score_view": len(evidence_events),
            "null_condition_score_coverage": (
                len(evidence_events)
                / sum(event.condition_tag_id is None for event in events)
                if events
                else 1.0
            ),
        },
        "object_typing": {
            "relation_tag_ids": list(DEFAULT_OBJECT_BRIDGE_TAG_IDS),
            "substantive_by_default": True,
            "note": (
                "conflict_scope remains substantive because its meaning "
                "depends on sentence direction and context."
            ),
        },
        "baseline": {
            "metrics": _metrics(rows, baseline_assignments),
            "boundary_count": len(baseline_boundaries),
            "reason_counts": dict(
                Counter(
                    decision["reason"]
                    for decision in baseline_decisions
                )
            ),
        },
        "bidirectional_repair": {
            "metrics": _metrics(rows, repaired.assignments),
            "runtime_ms": repair_ms,
            "boundary_count": len(repaired.boundaries),
            "changed_boundary_count": len(changed_decisions),
            "decision_reason_counts": dict(
                Counter(
                    decision.reason
                    for decision in repaired.decisions
                )
            ),
            "changed_decisions": [
                decision.to_dict() for decision in changed_decisions
            ],
            "decisions": [
                decision.to_dict()
                for decision in repaired.decisions
            ],
            "errors": _error_examples(rows, repaired.assignments),
        },
        "global_decoder": {
            "metrics": _metrics(rows, decoded.assignments),
            "runtime_ms": decoder_ms,
            "boundary_count": len(decoded.boundaries),
            "score": decoded.score,
            "changed_boundary_positions": sorted(
                set(decoded.boundaries) ^ set(baseline_boundaries)
            ),
            "segments": [asdict(segment) for segment in decoded.segments],
            "errors": _error_examples(rows, decoded.assignments),
        },
        "diagnostic_only": {
            "baseline_boundary_positions": list(baseline_boundaries),
            "gold_boundary_count": sum(
                gold[rows[index - 1].event_id]
                != gold[rows[index].event_id]
                for index in range(1, len(rows))
            ),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--matches", type=Path, default=DEFAULT_MATCHES)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--condition-score-min-similarity",
        type=float,
        default=0.70,
    )
    parser.add_argument(
        "--condition-score-min-margin",
        type=float,
        default=0.03,
    )
    args = parser.parse_args()

    rows = _read_matches(args.matches)
    raw_rows = _raw_match_rows(args.matches)
    output = evaluate(
        rows,
        raw_rows,
        min_top_similarity=args.condition_score_min_similarity,
        min_top_margin=args.condition_score_min_margin,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(output, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "condition_score_gate": output["condition_score_gate"],
                "baseline": output["baseline"]["metrics"],
                "bidirectional_repair": {
                    "metrics": output["bidirectional_repair"]["metrics"],
                    "runtime_ms": output["bidirectional_repair"]["runtime_ms"],
                    "changed_boundary_count": output[
                        "bidirectional_repair"
                    ]["changed_boundary_count"],
                },
                "global_decoder": {
                    "metrics": output["global_decoder"]["metrics"],
                    "runtime_ms": output["global_decoder"]["runtime_ms"],
                    "changed_boundary_count": len(
                        output["global_decoder"][
                            "changed_boundary_positions"
                        ]
                    ),
                },
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
