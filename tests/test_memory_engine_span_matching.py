from __future__ import annotations

import unittest

import numpy as np

from src.memory_engine.span_matching import (
    CandidateSpan,
    CharacterSpanTokenizer,
    FOUR_ROLE_GROUP_SCORE_THRESHOLDS_V1,
    HighRecallRoleHypothesisMatcher,
    LABEL_PROTOTYPES,
    MultiPrototypeContrastiveMatcher,
    PrototypeEmbeddingScorer,
    SemiMarkovSpanLatticeMatcher,
)


class _SemanticToyEmbedder:
    labels = tuple(LABEL_PROTOTYPES)

    def embed(self, texts: list[str]) -> np.ndarray:
        return np.asarray([self._vector(text) for text in texts], dtype=np.float32)

    def _vector(self, text: str) -> np.ndarray:
        values = np.full(len(self.labels), 0.001, dtype=np.float32)
        patterns = {
            "attitude_positive": (
                "偏好",
                "优先",
                "默认",
                "继续保持",
                "认可",
            ),
            "attitude_negative": (
                "不喜欢",
                "避免",
                "不要",
                "不适合",
                "撤销",
            ),
            "attitude_uncertain": (
                "不确定",
                "或许",
                "勉强",
                "尚未决定",
                "再讨论",
            ),
            "temporal_short": (
                "当前",
                "本次",
                "这一次",
                "今天",
                "本轮",
                "暂时",
                "失效",
                "only for this task",
            ),
            "temporal_medium": (
                "接下来",
                "下次",
                "这一周",
                "后续",
                "近期",
                "项目期间",
                "同一个文件",
                "limited period",
            ),
            "temporal_long": (
                "以后",
                "今后",
                "每次",
                "长期",
                "一直",
                "所有类似任务",
                "通用规则",
                "跨不同",
                "all future tasks",
            ),
            "object": (
                "工具",
                "软件",
                "文件",
                "报告",
                "图表",
                "对象",
                "模板",
                "设置",
                "柱状图",
            ),
            "condition": (
                "场景",
                "情况下",
                "工作内容",
                "业务条件",
                "任务",
            ),
            "residual": (
                "礼貌",
                "无关",
                "催促",
                "运行事实",
                "没有可提取",
            ),
        }
        matched = False
        for index, label in enumerate(self.labels):
            if any(pattern in text for pattern in patterns[label]):
                values[index] = 1.0
                matched = True
        if not matched:
            values[self.labels.index("residual")] = 1.0
        return values


class _ConstantEmbedder:
    def embed(self, texts: list[str]) -> np.ndarray:
        return np.ones((len(texts), 8), dtype=np.float32)


class SpanMatchingTest(unittest.TestCase):
    def test_temporal_prototypes_encode_relative_validity_scope(self):
        short = " ".join(LABEL_PROTOTYPES["temporal_short"])
        medium = " ".join(LABEL_PROTOTYPES["temporal_medium"])
        long = " ".join(LABEL_PROTOTYPES["temporal_long"])

        self.assertIn("当前", short)
        self.assertIn("失效", short)
        self.assertIn("项目期间", medium)
        self.assertIn("同一个文件", medium)
        self.assertIn("后续", LABEL_PROTOTYPES["temporal_medium"])
        self.assertIn("所有类似任务", long)
        self.assertIn("跨不同文件和任务", long)
        self.assertIn("今后", LABEL_PROTOTYPES["temporal_long"])
        self.assertIn("每次", LABEL_PROTOTYPES["temporal_long"])
        self.assertNotIn("上次", long)
        self.assertNotIn("之前", long)
        self.assertNotIn("同一个文件", long)

    def test_four_role_threshold_profile_covers_every_output_role(self):
        self.assertEqual(
            {"condition", "temporal", "attitude", "object"},
            set(FOUR_ROLE_GROUP_SCORE_THRESHOLDS_V1),
        )

    def _matchers(self):
        scorer = PrototypeEmbeddingScorer(
            _SemanticToyEmbedder(),
            min_similarity=0.45,
            min_margin=0.01,
        )
        tokenizer = CharacterSpanTokenizer()
        return (
            MultiPrototypeContrastiveMatcher(scorer, tokenizer),
            SemiMarkovSpanLatticeMatcher(scorer, tokenizer),
        )

    def test_matchers_find_long_term_attitude_and_object(self):
        for matcher in self._matchers():
            with self.subTest(matcher=matcher.name):
                result = matcher.match("以后默认用柱状图")
                labels = {match.label for match in result.matches}
                self.assertIn("temporal_long", labels)
                self.assertIn("attitude_positive", labels)
                self.assertIn("object", labels)
                result.assert_valid()

    def test_matchers_preserve_absolute_offsets(self):
        for matcher in self._matchers():
            with self.subTest(matcher=matcher.name):
                result = matcher.match("今天不要用柱状图", offset=11)
                self.assertTrue(result.matches)
                for match in result.matches:
                    self.assertGreaterEqual(match.start, 11)

    def test_contrastive_null_does_not_force_labels(self):
        scorer = PrototypeEmbeddingScorer(
            _ConstantEmbedder(),
            min_similarity=0.45,
            min_margin=0.01,
        )
        tokenizer = CharacterSpanTokenizer()
        matchers = (
            MultiPrototypeContrastiveMatcher(scorer, tokenizer),
            SemiMarkovSpanLatticeMatcher(scorer, tokenizer),
        )
        for matcher in matchers:
            with self.subTest(matcher=matcher.name):
                self.assertEqual((), matcher.match("普通陈述").matches)

    def test_group_threshold_can_reject_one_group_independently(self):
        scorer = PrototypeEmbeddingScorer(
            _SemanticToyEmbedder(),
            min_similarity=0.45,
            min_margin=0.01,
        )
        tokenizer = CharacterSpanTokenizer()
        matchers = (
            MultiPrototypeContrastiveMatcher(
                scorer,
                tokenizer,
                group_score_thresholds={"temporal": 10.0},
            ),
            SemiMarkovSpanLatticeMatcher(
                scorer,
                tokenizer,
                group_score_thresholds={"temporal": 10.0},
            ),
        )
        for matcher in matchers:
            with self.subTest(matcher=matcher.name):
                labels = {
                    match.label
                    for match in matcher.match(
                        "\u4ee5\u540e\u9ed8\u8ba4\u7528"
                        "\u67f1\u72b6\u56fe"
                    ).matches
                }
                self.assertFalse(
                    any(label.startswith("temporal_") for label in labels)
                )
                self.assertIn("attitude_positive", labels)
                self.assertIn("object", labels)

    def test_group_assessment_retains_cross_role_alternatives(self):
        scorer = PrototypeEmbeddingScorer(
            _SemanticToyEmbedder(),
            min_similarity=0.45,
            min_margin=0.01,
        )
        assessments = scorer.assess_by_group(
            [
                CandidateSpan(
                    start=0,
                    end=4,
                    text="长期设置",
                    token_count=4,
                )
            ]
        )
        accepted = {
            assessment.group
            for assessment in assessments
            if assessment.accepted
        }
        self.assertIn("temporal", accepted)
        self.assertIn("object", accepted)

    def test_high_recall_matcher_allows_overlapping_role_hypotheses(self):
        scorer = PrototypeEmbeddingScorer(
            _SemanticToyEmbedder(),
            min_similarity=0.45,
            min_margin=0.01,
        )
        result = HighRecallRoleHypothesisMatcher(
            scorer,
            CharacterSpanTokenizer(),
        ).match("长期设置")
        whole_span_groups = {
            hypothesis.group
            for hypothesis in result.hypotheses
            if hypothesis.start == 0 and hypothesis.end == 4
        }
        self.assertIn("temporal", whole_span_groups)
        self.assertIn("object", whole_span_groups)
        result.assert_valid()


if __name__ == "__main__":
    unittest.main()
