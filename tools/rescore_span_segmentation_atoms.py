from __future__ import annotations

import argparse
import json
import re
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Sequence

from src.memory_engine.span_segmentation import punctuation_boundaries

try:
    import jieba
except ImportError:
    jieba = None


DEFAULT_CASES = Path("tests/data/span_segmentation_cases_v2.json")
DEFAULT_ATOMS = Path("tests/data/span_segmentation_atoms_v3.json")
DEFAULT_ADAPTIVE = Path(
    "../outputs/kylin_span_segmentation_v2_global_adaptive_v1.json"
)
DEFAULT_OUTPUT = Path(
    "../outputs/kylin_span_segmentation_atom_rescore_v3.json"
)
DEFAULT_LIMITS = (2, 4, 8)
PRIMARY_LIMIT = 4
ASCII_LEXEME = re.compile(
    r"[A-Za-z0-9_](?:[A-Za-z0-9_.:!()\-]*[A-Za-z0-9_)])?"
)
NEGATION_PREFIXES = frozenset({"不", "未", "无", "非", "别", "勿", "莫"})
CHINESE_TOKENIZER_AVAILABLE = jieba is not None


def _content_length(text: str) -> int:
    return sum(
        not character.isspace()
        and not unicodedata.category(character).startswith("P")
        for character in text
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


def resolve_atoms(
    text: str,
    definitions: Sequence[dict[str, Any]],
) -> list[dict[str, Any]]:
    atoms = []
    for definition in definitions:
        atom_text = str(definition["text"])
        occurrence = int(definition.get("occurrence", 0))
        starts = _occurrences(text, atom_text)
        if occurrence >= len(starts):
            raise ValueError(
                f"atom_not_found:{atom_text!r}:occurrence={occurrence}:text={text!r}"
            )
        start = starts[occurrence]
        atoms.append(
            {
                **definition,
                "start": start,
                "end": start + len(atom_text),
            }
        )
    ordered = sorted(atoms, key=lambda atom: (atom["start"], atom["end"]))
    for left, right in zip(ordered, ordered[1:]):
        if left["end"] > right["start"]:
            raise ValueError(
                f"overlapping_atoms:{left['text']!r}:{right['text']!r}:"
                f"text={text!r}"
            )
    return atoms


def _protected_ranges(atom: dict[str, Any]) -> list[tuple[int, int]]:
    ranges = [
        (atom["start"] + match.start(), atom["start"] + match.end())
        for match in ASCII_LEXEME.finditer(atom["text"])
    ]
    if jieba is not None:
        ranges.extend(
            (
                atom["start"] + start,
                atom["start"] + end,
            )
            for token, start, end in jieba.tokenize(atom["text"], HMM=True)
            if end - start > 1
            and any("\u3400" <= character <= "\u9fff" for character in token)
        )
    for protected in atom.get("protected", []):
        starts = _occurrences(atom["text"], str(protected))
        if not starts:
            raise ValueError(
                f"protected_lexeme_not_in_atom:{protected!r}:{atom['text']!r}"
            )
        ranges.extend(
            (
                atom["start"] + start,
                atom["start"] + start + len(str(protected)),
            )
            for start in starts
        )
    return ranges


def _recoverable_morpheme_split(
    text: str,
    boundary: int,
    start: int,
    end: int,
) -> bool:
    token = text[start:end]
    relative = boundary - start
    return (
        relative == 1
        and token[:1] in NEGATION_PREFIXES
        and len(token) > 1
    )


def _segment_ranges(text_length: int, boundaries: Iterable[int]) -> list[tuple[int, int]]:
    points = [0, *sorted({int(value) for value in boundaries}), text_length]
    if any(left >= right for left, right in zip(points, points[1:])):
        raise ValueError("boundaries_must_be_strictly_inside_text")
    return list(zip(points, points[1:]))


def score_atom_partition(
    text: str,
    atom_definitions: Sequence[dict[str, Any]],
    boundaries: Iterable[int],
    *,
    contamination_limits: Sequence[int] = DEFAULT_LIMITS,
) -> dict[str, Any]:
    boundary_set = {int(value) for value in boundaries}
    ranges = _segment_ranges(len(text), boundary_set)
    atoms = resolve_atoms(text, atom_definitions)
    rows = []
    for index, atom in enumerate(atoms):
        internal_boundaries = sorted(
            boundary
            for boundary in boundary_set
            if atom["start"] < boundary < atom["end"]
        )
        split = bool(internal_boundaries)
        protected_ranges = _protected_ranges(atom)
        catastrophic_split = any(
            start < boundary < end
            for boundary in internal_boundaries
            for start, end in protected_ranges
            if not _recoverable_morpheme_split(
                text,
                boundary,
                start,
                end,
            )
        )
        benign_split = split and not catastrophic_split
        host = next(
            (
                (start, end)
                for start, end in ranges
                if start <= atom["start"] and atom["end"] <= end
            ),
            None,
        )
        contained = []
        if host is not None:
            contained = [
                other_index
                for other_index, other in enumerate(atoms)
                if host[0] <= other["start"] and other["end"] <= host[1]
            ]
        collision = len(contained) > 1
        foreign_chars = None
        host_text = None
        if host is not None:
            host_text = text[host[0] : host[1]]
            relative_start = atom["start"] - host[0]
            relative_end = atom["end"] - host[0]
            foreign_chars = _content_length(
                host_text[:relative_start] + host_text[relative_end:]
            )
        recoverable = {
            str(limit): (
                not split
                and not collision
                and foreign_chars is not None
                and foreign_chars <= limit
            )
            for limit in contamination_limits
        }
        recovery_credit = {
            str(limit): (
                0.0
                if catastrophic_split
                else 0.5
                if benign_split
                else 1.0
                if recoverable[str(limit)]
                else 0.0
            )
            for limit in contamination_limits
        }
        rows.append(
            {
                **atom,
                "split": split,
                "internal_boundaries": internal_boundaries,
                "catastrophic_split": catastrophic_split,
                "benign_split": benign_split,
                "collision": collision,
                "host_segment": host_text,
                "foreign_chars": foreign_chars,
                "recoverable": recoverable,
                "recovery_credit": recovery_credit,
            }
        )

    total = len(rows)
    intact = sum(not row["split"] for row in rows)
    isolated = sum(
        not row["split"] and not row["collision"] for row in rows
    )
    recoverable_counts = {
        str(limit): sum(row["recoverable"][str(limit)] for row in rows)
        for limit in contamination_limits
    }
    recovery_credit = {
        str(limit): sum(row["recovery_credit"][str(limit)] for row in rows)
        for limit in contamination_limits
    }
    return {
        "atoms": total,
        "segments": len(ranges),
        "segment_count_sufficient": len(ranges) >= total,
        "intact_atoms": intact,
        "isolated_atoms": isolated,
        "split_atoms": total - intact,
        "catastrophic_split_atoms": sum(
            row["catastrophic_split"] for row in rows
        ),
        "benign_split_atoms": sum(row["benign_split"] for row in rows),
        "merged_atoms": sum(row["collision"] for row in rows),
        "integrity_rate": intact / total if total else 1.0,
        "isolation_rate": isolated / total if total else 1.0,
        "recoverable_atoms": recoverable_counts,
        "recovery_credit": recovery_credit,
        "recoverable_rate": {
            str(limit): recoverable_counts[str(limit)] / total
            if total
            else 1.0
            for limit in contamination_limits
        },
        "atom_results": rows,
    }


def aggregate(
    rows: Sequence[dict[str, Any]],
    *,
    contamination_limits: Sequence[int] = DEFAULT_LIMITS,
) -> dict[str, Any]:
    totals = Counter()
    for row in rows:
        totals.update(
            {
                "atoms": row["atoms"],
                "intact_atoms": row["intact_atoms"],
                "isolated_atoms": row["isolated_atoms"],
                "split_atoms": row["split_atoms"],
                "catastrophic_split_atoms": row[
                    "catastrophic_split_atoms"
                ],
                "benign_split_atoms": row["benign_split_atoms"],
                "merged_atoms": row["merged_atoms"],
            }
        )
        for limit in contamination_limits:
            totals[f"recoverable_{limit}"] += row["recoverable_atoms"][str(limit)]
            totals[f"credit_{limit}"] += row["recovery_credit"][str(limit)]
    atoms = totals["atoms"]
    recoverable = {
        str(limit): totals[f"recoverable_{limit}"]
        for limit in contamination_limits
    }
    rates = {
        str(limit): recoverable[str(limit)] / atoms if atoms else 1.0
        for limit in contamination_limits
    }
    credit = {
        str(limit): totals[f"credit_{limit}"]
        for limit in contamination_limits
    }
    credit_rates = {
        str(limit): credit[str(limit)] / atoms if atoms else 1.0
        for limit in contamination_limits
    }
    lexical_credit = (
        totals["intact_atoms"] + 0.5 * totals["benign_split_atoms"]
    )
    lexical_rate = lexical_credit / atoms if atoms else 1.0
    return {
        "cases": len(rows),
        "atoms": atoms,
        "segment_count_sufficient_cases": sum(
            bool(row["segment_count_sufficient"]) for row in rows
        ),
        "segment_count_sufficient_case_rate": (
            sum(bool(row["segment_count_sufficient"]) for row in rows)
            / len(rows)
            if rows
            else 1.0
        ),
        "intact_atoms": totals["intact_atoms"],
        "isolated_atoms": totals["isolated_atoms"],
        "split_atoms": totals["split_atoms"],
        "catastrophic_split_atoms": totals["catastrophic_split_atoms"],
        "benign_split_atoms": totals["benign_split_atoms"],
        "merged_atoms": totals["merged_atoms"],
        "integrity_rate": totals["intact_atoms"] / atoms if atoms else 1.0,
        "isolation_rate": totals["isolated_atoms"] / atoms if atoms else 1.0,
        "recoverable_atoms": recoverable,
        "recoverable_rate": rates,
        "recovery_credit": credit,
        "weighted_recovery_rate": credit_rates,
        "primary_contamination_limit": PRIMARY_LIMIT,
        "lexical_recovery_credit": lexical_credit,
        "lexical_recovery_rate": lexical_rate,
        "lexical_score_10": lexical_rate * 10.0,
        "span_match_isolation_score_10": (
            credit_rates[str(PRIMARY_LIMIT)] * 10.0
        ),
        "score_10": credit_rates[str(PRIMARY_LIMIT)] * 10.0,
        "complete_case_rate": (
            sum(
                row["segment_count_sufficient"]
                and all(
                    atom["recoverable"][str(PRIMARY_LIMIT)]
                    for atom in row["atom_results"]
                )
                for row in rows
            )
            / len(rows)
            if rows
            else 1.0
        ),
    }


def _algorithm_rows(
    cases: Sequence[dict[str, Any]],
    annotations: dict[str, dict[str, Any]],
    boundaries_by_id: dict[str, set[int]],
) -> list[dict[str, Any]]:
    rows = []
    for case in cases:
        annotation = annotations[case["id"]]
        scored = score_atom_partition(
            case["text"],
            annotation["atoms"],
            boundaries_by_id[case["id"]],
        )
        rows.append(
            {
                "id": case["id"],
                "challenge": case["challenge"],
                "text": case["text"],
                "annotation_source": annotation.get(
                    "annotation_source", "rubric"
                ),
                "boundaries": sorted(boundaries_by_id[case["id"]]),
                **scored,
            }
        )
    return rows


def main() -> None:
    if jieba is None:
        raise RuntimeError(
            "jieba_is_required_for_complete_chinese_lexical_scoring"
        )
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--atoms", type=Path, default=DEFAULT_ATOMS)
    parser.add_argument("--adaptive-result", type=Path, default=DEFAULT_ADAPTIVE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    cases = json.loads(args.cases.read_text(encoding="utf-8"))
    atom_rows = json.loads(args.atoms.read_text(encoding="utf-8"))
    annotations = {row["id"]: row for row in atom_rows}
    case_ids = {case["id"] for case in cases}
    if set(annotations) != case_ids:
        raise ValueError("atom_annotations_must_match_case_ids")

    adaptive_document = json.loads(
        args.adaptive_result.read_text(encoding="utf-8")
    )
    adaptive_cases = adaptive_document["algorithms"][
        "kylin_embedding_global_adaptive"
    ]["cases"]
    adaptive_boundaries = {
        row["id"]: {
            int(boundary["position"]) for boundary in row["boundaries"]
        }
        for row in adaptive_cases
    }
    punctuation = {
        case["id"]: {
            boundary.position
            for boundary in punctuation_boundaries(case["text"])
        }
        for case in cases
    }

    algorithms = {}
    for name, boundary_map in (
        ("punctuation_only", punctuation),
        ("kylin_embedding_global_adaptive", adaptive_boundaries),
    ):
        rows = _algorithm_rows(cases, annotations, boundary_map)
        algorithms[name] = {
            "metrics": aggregate(rows),
            "cases": rows,
        }

    output = {
        "purpose": (
            "Evaluate whether temporal, condition, attitude, and object atoms "
            "remain intact, are isolated from other atoms, and carry limited "
            "unrelated text."
        ),
        "contamination_limits": list(DEFAULT_LIMITS),
        "primary_contamination_limit": PRIMARY_LIMIT,
        "lexical_protection": {
            "chinese": "jieba-0.42.1-hmm",
            "ascii": "identifier-regex",
            "recoverable_prefixes": sorted(NEGATION_PREFIXES),
        },
        "algorithms": algorithms,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(output, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                name: document["metrics"]
                for name, document in algorithms.items()
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
