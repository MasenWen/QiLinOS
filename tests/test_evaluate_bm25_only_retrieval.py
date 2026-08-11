from __future__ import annotations

import unittest

from tools.evaluate_bm25_only_retrieval import (
    JiebaIdentifierTokenizer,
    PrebuiltBM25Index,
    _quality,
)


class _WhitespaceTokenizer:
    @staticmethod
    def tokenize(text: str) -> tuple[str, ...]:
        return tuple(text.casefold().split())


class BM25OnlyRetrievalEvaluationTest(unittest.TestCase):
    def test_identifier_tokenizer_preserves_file_and_cell_range(self) -> None:
        try:
            tokenizer = JiebaIdentifierTokenizer()
        except RuntimeError as exc:
            self.skipTest(str(exc))
        tokens = tokenizer.tokenize(
            "处理 Student_Level_Fill_Blank.xlsx 的 B1:E30"
        )

        self.assertIn("student_level_fill_blank.xlsx", tokens)
        self.assertIn("b1:e30", tokens)

    def test_rare_exact_identifier_ranks_matching_memory_first(self) -> None:
        index = PrebuiltBM25Index(
            {
                "target": (
                    "Student_Level_Fill_Blank.xlsx B1:E30 填充空白"
                ),
                "other": "WeeklySales.xlsx 计算每周毛利",
            },
            _WhitespaceTokenizer(),
        )

        hits = index.search(
            "Student_Level_Fill_Blank.xlsx 的 B1:E30",
            top_k=2,
        )

        self.assertEqual("target", hits[0].document_id)
        self.assertGreater(hits[0].score, 0.0)

    def test_zero_overlap_returns_no_candidate(self) -> None:
        index = PrebuiltBM25Index(
            {"memory": "WeeklySales.xlsx 计算每周毛利"},
            _WhitespaceTokenizer(),
        )

        self.assertEqual((), index.search("完全无关的天气问题"))

    def test_quality_reports_recall_and_candidate_precision(self) -> None:
        quality = _quality(
            (
                {
                    "required_ids": ["a", "b"],
                    "selected_ids": ["a", "x"],
                },
                {
                    "required_ids": [],
                    "selected_ids": [],
                },
            )
        )

        self.assertEqual(0.5, quality["required_memory_hit_recall"])
        self.assertEqual(0.5, quality["selected_memory_precision"])
        self.assertEqual(1.0, quality["clarification_abstention_rate"])


if __name__ == "__main__":
    unittest.main()
