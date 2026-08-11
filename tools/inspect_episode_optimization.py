from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any, Mapping


def _load(path: Path) -> Mapping[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, Mapping):
        raise ValueError(f"expected JSON object: {path}")
    return value


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--matches", type=Path, required=True)
    parser.add_argument("--optimization", type=Path, required=True)
    args = parser.parse_args()

    source = _load(args.matches)
    optimization = _load(args.optimization)
    rows = source["matches"]
    baseline = set(
        optimization["diagnostic_only"]["baseline_boundary_positions"]
    )
    decoded = {
        segment["start"]
        for segment in optimization["global_decoder"]["segments"][1:]
    }

    print("BOUNDARY_CHANGES")
    for position in sorted(baseline ^ decoded):
        gold_boundary = (
            rows[position - 1]["gold_episode_id"]
            != rows[position]["gold_episode_id"]
        )
        action = "removed" if position in baseline else "added"
        print(
            position,
            action,
            f"gold_boundary={gold_boundary}",
            rows[position - 1]["event_id"],
            "->",
            rows[position]["event_id"],
        )

    print("\nBIDIRECTIONAL_DECISIONS")
    repair_payload = optimization["bidirectional_repair"]
    repair_decisions = repair_payload.get(
        "decisions",
        repair_payload.get("changed_decisions", ()),
    )
    for decision in repair_decisions:
        old_gold = {
            position: (
                rows[position - 1]["gold_episode_id"]
                != rows[position]["gold_episode_id"]
            )
            for position in decision.get("old_boundaries", ())
        }
        new_position = decision["new_boundary"]
        new_gold = (
            rows[new_position - 1]["gold_episode_id"]
            != rows[new_position]["gold_episode_id"]
        )
        print(
            decision["left_anchor_event_id"],
            "->",
            decision["right_anchor_event_id"],
            decision["reason"],
            f"old={decision.get('old_boundaries')}",
            f"old_gold={old_gold}",
            f"new={decision['new_boundary']}",
            f"new_gold={new_gold}",
            f"old_score={decision['old_score']:.4f}",
            f"best={decision['new_score']:.4f}",
            f"runner_up={decision['runner_up_score']:.4f}",
            f"evidence={decision['evidence_event_ids']}",
        )

    fallback = [
        (index, row)
        for index, row in enumerate(rows)
        if row.get("condition_match_source")
        == "short_context_fallback"
    ]
    top_tag_counts: Counter[str] = Counter()
    tag_names: dict[str, str] = {}
    for row in rows:
        scores = row.get("condition_view_scores", {})
        if scores:
            top_tag_counts.update(
                [max(scores.items(), key=lambda item: item[1])[0]]
            )
        for match in row.get("canonical_matches", ()):
            if match.get("group") == "condition":
                tag_names[match["tag_id"]] = match["tag_name"]
    print("\nCONDITION_VIEW_TOP_TAGS")
    for tag_id, count in top_tag_counts.most_common():
        print(count, tag_id, tag_names.get(tag_id, ""))

    print(f"\nFALLBACK_MATCHES count={len(fallback)}")
    for index, row in fallback:
        scores = sorted(
            row.get("condition_view_scores", {}).values(),
            reverse=True,
        )
        margin = scores[0] - scores[1] if len(scores) > 1 else 0.0
        correct = (
            row["condition_tag_id"] == row["gold_condition_tag_id"]
        )
        previous_condition = None
        previous_distance = None
        next_condition = None
        next_distance = None
        for cursor in range(index - 1, max(-1, index - 5), -1):
            if rows[cursor].get("condition_tag_id"):
                previous_condition = rows[cursor]["condition_tag_id"]
                previous_distance = index - cursor
                break
        for cursor in range(index + 1, min(len(rows), index + 5)):
            if rows[cursor].get("condition_tag_id"):
                next_condition = rows[cursor]["condition_tag_id"]
                next_distance = cursor - index
                break
        print(
            index,
            row["event_id"],
            "correct" if correct else "wrong",
            f"similarity={row['condition_similarity']:.4f}",
            f"margin={margin:.4f}",
            row["condition_tag_id"],
            row["gold_condition_tag_id"],
            f"prev={previous_condition}@{previous_distance}",
            f"next={next_condition}@{next_distance}",
            (
                "prev_score="
                f"{row.get('condition_view_scores', {}).get(previous_condition)}"
            ),
            (
                "next_score="
                f"{row.get('condition_view_scores', {}).get(next_condition)}"
            ),
        )

    score_views = []
    for index, row in enumerate(rows):
        scores = row.get("condition_view_scores", {})
        if row.get("condition_tag_id") or len(scores) < 2:
            continue
        ranked = sorted(scores.items(), key=lambda item: -item[1])
        if ranked[0][1] >= 0.70 and ranked[0][1] - ranked[1][1] >= 0.03:
            score_views.append((index, row, ranked))
    print(f"\nNULL_SCORE_VIEWS count={len(score_views)}")
    for index, row, ranked in score_views:
        rendered = ",".join(
            f"{tag_id}:{score:.3f}"
            for tag_id, score in ranked[:3]
        )
        print(
            index,
            row["event_id"],
            f"top={rendered}",
            f"gold={row['gold_condition_tag_id']}",
        )


if __name__ == "__main__":
    main()
