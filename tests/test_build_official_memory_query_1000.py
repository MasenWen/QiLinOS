from __future__ import annotations

from collections import Counter

from tools.build_official_memory_query_1000 import (
    QUERY_TYPES,
    _choose_variants,
    _largest_remainder,
    _ordered_queries,
)


def _variants(group: str, duplicate: str = "") -> list[dict[str, str]]:
    return [
        {
            "answer_group_id": group,
            "query_type": kind,
            "query_text": duplicate or f"{group}:{kind}",
        }
        for kind in QUERY_TYPES
    ]


def test_largest_remainder_preserves_total() -> None:
    result = _largest_remainder(Counter({"a": 7, "b": 2, "c": 1}), 16)
    assert result == {"a": 11, "b": 3, "c": 2}


def test_variant_selection_keeps_four_and_caps_exact_text() -> None:
    texts: Counter[str] = Counter()
    omitted: Counter[str] = Counter()
    first = _choose_variants(_variants("g1"), texts, omitted)
    assert first is not None
    assert len(first[0]) == 4
    texts["same"] = 2
    blocked = _choose_variants(_variants("g2", "same"), texts, omitted)
    assert blocked is None


def test_round_order_never_places_same_case_adjacent() -> None:
    cases = [
        {
            "precedent_case_id": f"case-{index}",
            "queries": _variants(f"group-{index}")[:4],
        }
        for index in range(8)
    ]
    rows = _ordered_queries(cases)
    assert len(rows) == 32
    assert all(
        left["precedent_case_id"] != right["precedent_case_id"]
        for left, right in zip(rows, rows[1:])
    )
