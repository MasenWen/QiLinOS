from __future__ import annotations

import unittest

from src.memory_engine.span_matching import SpanMatch
from tools.evaluate_kylin_span_matching import _gold_spans, _score_matches


class SpanMatchingEvaluationTest(unittest.TestCase):
    def test_scoring_allows_compact_partial_span(self):
        text = "以后默认用柱状图"
        gold = _gold_spans(
            text,
            [
                {"text": "默认用", "label": "attitude_positive"},
                {"text": "柱状图", "label": "object"},
            ],
        )
        predicted = [
            SpanMatch(
                start=2,
                end=4,
                text="默认",
                label="attitude_positive",
                score=0.8,
                similarity=0.7,
                margin=0.1,
                source="test",
            ),
            SpanMatch(
                start=5,
                end=8,
                text="柱状图",
                label="object",
                score=0.8,
                similarity=0.7,
                margin=0.1,
                source="test",
            ),
        ]
        score = _score_matches(predicted, gold)
        self.assertEqual(2, score["tp"])
        self.assertEqual(0, score["fp"])
        self.assertEqual(0, score["fn"])

    def test_wrong_temporal_subtype_is_detected_but_not_subtype_correct(self):
        text = "以后默认使用"
        gold = _gold_spans(
            text,
            [{"text": "以后", "label": "temporal_long"}],
        )
        predicted = [
            SpanMatch(
                start=0,
                end=2,
                text="以后",
                label="temporal_short",
                score=0.8,
                similarity=0.7,
                margin=0.1,
                source="test",
            )
        ]
        score = _score_matches(predicted, gold)
        self.assertEqual(1, score["tp"])
        self.assertEqual(0, score["subtype_correct"])


if __name__ == "__main__":
    unittest.main()
