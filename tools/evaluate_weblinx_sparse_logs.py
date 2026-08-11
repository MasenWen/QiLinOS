from __future__ import annotations

import argparse
import json
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from typing import Any, Iterable, Mapping

from src.memory_engine.span_matching import (
    FOUR_ROLE_GROUP_SCORE_THRESHOLDS_V1,
    JiebaSpanTokenizer,
    MultiPrototypeContrastiveMatcher,
    PrototypeEmbeddingScorer,
    SemiMarkovSpanLatticeMatcher,
    SpanMatch,
    label_group,
)
from tools.evaluate_kylin_span_segmentation import CachedEmbedder


DEFAULT_OUTPUT = Path(
    "runtime/results/weblinx_sparse_logs/weblinx_sparse_logs.json"
)
SEMANTIC_FIELDS = (
    "event_time_basis",
    "apps_involved",
    "app_scope",
    "source_modalities",
    "activity_families",
    "action_keys",
    "workflow_scope",
)
CONTEXT_STRING_FIELDS = ("timestamp_recovery",)


def read_ndjson(path: Path) -> list[dict[str, Any]]:
    rows = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"ndjson_row_is_not_object:{line_number}")
            rows.append(value)
    return rows


def semantic_values(row: Mapping[str, Any]) -> tuple[tuple[str, str], ...]:
    values = []
    for field in SEMANTIC_FIELDS:
        raw = row.get(field)
        items: Iterable[Any] = raw if isinstance(raw, list) else (raw,)
        for item in items:
            if isinstance(item, str) and item:
                values.append((field, item))
    context = row.get("context_json")
    if isinstance(context, Mapping):
        for field in CONTEXT_STRING_FIELDS:
            item = context.get(field)
            if isinstance(item, str) and item:
                values.append((f"context_json.{field}", item))
    return tuple(values)


def _match_key(match: SpanMatch) -> tuple[int, int, str]:
    return match.start, match.end, match.label


def _summarize_matcher(
    rows: list[dict[str, Any]],
    value_matches: Mapping[tuple[str, str], tuple[SpanMatch, ...]],
) -> dict[str, Any]:
    role_counts: Counter[str] = Counter()
    weighted_role_counts: Counter[str] = Counter()
    value_frequency: Counter[tuple[str, str]] = Counter()
    episodes_with_matches = 0
    episodes_with_attitude = 0
    episodes_with_frame_evidence = 0
    matched_value_instances = 0
    match_instances = 0

    for row in rows:
        episode_matches = []
        for value in semantic_values(row):
            value_frequency[value] += 1
            matches = value_matches[value]
            if matches:
                matched_value_instances += 1
                match_instances += len(matches)
                episode_matches.extend(matches)
                for match in matches:
                    weighted_role_counts[label_group(match.label)] += 1
        roles = {label_group(match.label) for match in episode_matches}
        if episode_matches:
            episodes_with_matches += 1
        if "attitude" in roles:
            episodes_with_attitude += 1
        if "attitude" in roles and (
            roles & {"condition", "object", "temporal"}
        ):
            episodes_with_frame_evidence += 1

    values = []
    for value in sorted(value_matches):
        matches = value_matches[value]
        for match in matches:
            role_counts[label_group(match.label)] += 1
        values.append(
            {
                "field": value[0],
                "text": value[1],
                "frequency": value_frequency[value],
                "matches": [asdict(match) for match in matches],
            }
        )

    semantic_value_instances = sum(value_frequency.values())
    unique_values_with_matches = sum(
        bool(matches) for matches in value_matches.values()
    )
    return {
        "episodes": len(rows),
        "semantic_value_instances": semantic_value_instances,
        "unique_field_values": len(value_matches),
        "unique_values_with_matches": unique_values_with_matches,
        "unique_value_match_rate": (
            unique_values_with_matches / len(value_matches)
            if value_matches
            else 0.0
        ),
        "matched_value_instances": matched_value_instances,
        "matched_value_instance_rate": (
            matched_value_instances / semantic_value_instances
            if semantic_value_instances
            else 0.0
        ),
        "match_instances": match_instances,
        "episodes_with_matches": episodes_with_matches,
        "episode_match_rate": (
            episodes_with_matches / len(rows) if rows else 0.0
        ),
        "episodes_with_attitude": episodes_with_attitude,
        "episodes_with_frame_evidence": episodes_with_frame_evidence,
        "unique_role_counts": dict(sorted(role_counts.items())),
        "weighted_role_counts": dict(sorted(weighted_role_counts.items())),
        "values": values,
    }


def main() -> None:
    try:
        from src.rag.kylin_embedding_sdk import KylinTextEmbedding
    except ImportError:
        from tools.evaluate_kylin_embedding_preference_object_blind import (
            KylinTextEmbedding,
        )

    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    rows = read_ndjson(args.input)
    unique_values = sorted(
        {
            value
            for row in rows
            for value in semantic_values(row)
        }
    )
    embedder = CachedEmbedder(KylinTextEmbedding())
    scorer = PrototypeEmbeddingScorer(embedder)
    tokenizer = JiebaSpanTokenizer()
    matchers = (
        MultiPrototypeContrastiveMatcher(
            scorer,
            tokenizer,
            group_score_thresholds=FOUR_ROLE_GROUP_SCORE_THRESHOLDS_V1,
        ),
        SemiMarkovSpanLatticeMatcher(
            scorer,
            tokenizer,
            group_score_thresholds=FOUR_ROLE_GROUP_SCORE_THRESHOLDS_V1,
        ),
    )

    outputs = {}
    for matcher in matchers:
        value_matches = {}
        for value in unique_values:
            result = matcher.match(value[1])
            value_matches[value] = tuple(
                sorted(result.matches, key=_match_key)
            )
        outputs[matcher.name] = _summarize_matcher(rows, value_matches)

    output = {
        "purpose": (
            "Sparse extraction audit over real WebLINX episode metadata. "
            "No narrative text is synthesized."
        ),
        "input": str(args.input),
        "semantic_fields": list(SEMANTIC_FIELDS),
        "context_string_fields": list(CONTEXT_STRING_FIELDS),
        "excluded_identity_fields": [
            "episode_id",
            "source_trace_id",
            "user_id",
            "device_id",
        ],
        "group_score_thresholds": FOUR_ROLE_GROUP_SCORE_THRESHOLDS_V1,
        "embedding_cache": {
            "requested": embedder.requested,
            "computed": embedder.computed,
            "cache_hits": embedder.requested - embedder.computed,
        },
        "matchers": outputs,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(output, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                name: {
                    key: value[key]
                    for key in (
                        "episodes",
                        "semantic_value_instances",
                        "unique_field_values",
                        "unique_values_with_matches",
                        "matched_value_instance_rate",
                        "episodes_with_matches",
                        "episode_match_rate",
                        "episodes_with_attitude",
                        "episodes_with_frame_evidence",
                        "weighted_role_counts",
                    )
                }
                for name, value in outputs.items()
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
