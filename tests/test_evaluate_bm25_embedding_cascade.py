from __future__ import annotations

import unittest

from tools.evaluate_bm25_embedding_cascade import (
    BALANCED_THRESHOLD_FLOOR,
    CascadeThresholds,
    RankedCandidate,
    _early_decision,
    _is_multi_task,
)


class _FastPath:
    def condition_is_conflicted(self, condition):
        return condition == "condition:conflict"


def _candidate(
    memory_id="memory-1",
    *,
    condition="condition:clean",
    semantic=0.80,
    combined=0.82,
):
    return RankedCandidate(
        memory_id=memory_id,
        condition_tag_id=condition,
        bm25_score=4.0,
        bm25_ratio=1.0,
        semantic_score=semantic,
        identifier_coverage=1.0,
        combined_score=combined,
        matched_terms=("report.xlsx",),
    )


class BM25EmbeddingCascadeTest(unittest.TestCase):
    def setUp(self):
        self.thresholds = BALANCED_THRESHOLD_FLOOR
        self.fast_path = _FastPath()

    def test_clear_high_margin_candidate_exits(self):
        selected = _early_decision(
            (_candidate(), _candidate("memory-2", combined=0.70)),
            text="处理 report.xlsx 的收入列",
            ambiguous=False,
            fast_path=self.fast_path,
            thresholds=self.thresholds,
        )
        self.assertEqual(("memory-1",), selected)

    def test_ambiguous_multi_and_conflict_cases_fall_back(self):
        ranked = (_candidate(), _candidate("memory-2", combined=0.70))
        self.assertEqual(
            (),
            _early_decision(
                ranked,
                text="report.xlsx 按之前那个处理",
                ambiguous=True,
                fast_path=self.fast_path,
                thresholds=self.thresholds,
            ),
        )
        self.assertTrue(
            _is_multi_task("分别处理 a.xlsx 和 b.xlsx，各自按原规则完成")
        )
        self.assertEqual(
            (),
            _early_decision(
                (_candidate(condition="condition:conflict"),),
                text="处理 report.xlsx",
                ambiguous=False,
                fast_path=self.fast_path,
                thresholds=self.thresholds,
            ),
        )

    def test_low_margin_candidate_falls_back(self):
        selected = _early_decision(
            (_candidate(), _candidate("memory-2", combined=0.79)),
            text="处理 report.xlsx",
            ambiguous=False,
            fast_path=self.fast_path,
            thresholds=self.thresholds,
        )
        self.assertEqual((), selected)

    def test_balanced_floor_rejects_ambiguous_shadow_score(self):
        candidate = _candidate(semantic=0.836, combined=0.814)
        selected = _early_decision(
            (candidate, _candidate("memory-2", combined=0.729)),
            text="处理 report.xlsx",
            ambiguous=False,
            fast_path=self.fast_path,
            thresholds=self.thresholds,
        )
        self.assertEqual((), selected)


if __name__ == "__main__":
    unittest.main()
