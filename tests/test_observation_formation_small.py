from __future__ import annotations

from tools.evaluate_observation_formation_small import (
    frame_is_correct,
    maximum_frame_matching,
)


def _expected(object_tag_id: str) -> dict:
    return {
        "condition_tag_ids": ["condition:one"],
        "object_tag_id": object_tag_id,
        "attitude_directions": ["positive"],
        "temporal_labels": [None],
    }


def _prediction(object_tag_id: str) -> dict:
    return {
        "condition_tag_id": "condition:one",
        "object_tag_id": object_tag_id,
        "attitude_direction": "positive",
        "temporal_label": None,
    }


def test_frame_correctness_requires_all_four_roles() -> None:
    expected = _expected("object:one")
    assert frame_is_correct(_prediction("object:one"), expected)
    wrong = _prediction("object:one")
    wrong["attitude_direction"] = "negative"
    assert not frame_is_correct(wrong, expected)


def test_frame_matching_is_one_to_one() -> None:
    predictions = [
        _prediction("object:one"),
        _prediction("object:one"),
        _prediction("object:two"),
    ]
    expected = [_expected("object:one"), _expected("object:two")]
    pairs = maximum_frame_matching(predictions, expected)
    assert len(pairs) == 2
    assert {right for _, right in pairs} == {0, 1}
