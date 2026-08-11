from __future__ import annotations

import json
import math
import unittest
from pathlib import Path

from src.memory_engine.span_segmentation import (
    AdaptiveGlobalEmbeddingPartitionSegmenter,
    Boundary,
    CharacterGapProposer,
    CrfBoundaryProposer,
    EmbeddingCandidateSegmenter,
    GlobalEmbeddingPartitionSegmenter,
    PeltEmbeddingSegmenter,
    PredicateArgument,
    SemanticTilingSegmenter,
    SyntacticAnalysis,
    SyntacticBoundaryProposer,
    SyntacticToken,
    _window_change_point_position,
    build_result,
)
from tools.evaluate_kylin_span_segmentation import _score_case
from tools.rescore_span_segmentation_atoms import (
    CHINESE_TOKENIZER_AVAILABLE,
    score_atom_partition,
)


DATA_PATH = Path(__file__).parent / "data" / "span_segmentation_cases.json"
DATA_V2_PATH = (
    Path(__file__).parent / "data" / "span_segmentation_cases_v2.json"
)


class _FakeAnalyzer:
    def analyze(self, text: str) -> SyntacticAnalysis:
        self.asserted_text = text
        return SyntacticAnalysis(
            tokens=(
                SyntacticToken(0, "以后", 0, 2, "NT", 1, "ADV"),
                SyntacticToken(1, "默认用", 2, 5, "VV", -1, "HED"),
                SyntacticToken(2, "柱状图", 5, 8, "NN", 1, "VOB"),
                SyntacticToken(3, "。", 8, 9, "PU", 1, "WP"),
            ),
            arguments=(
                PredicateArgument(0, 1),
                PredicateArgument(2, 3),
            ),
        )


class _FakeEmbedder:
    def embed(self, texts: list[str]):
        vectors = []
        for text in texts:
            left_topic = sum(ord(char) for char in text[: max(1, len(text) // 2)])
            right_topic = sum(ord(char) for char in text[max(1, len(text) // 2) :])
            vector = [float((left_topic % 97) + 1), float((right_topic % 89) + 1)]
            norm = math.sqrt(sum(value * value for value in vector))
            vectors.append([value / norm for value in vector])
        return vectors


class _ConstantEmbedder:
    def embed(self, texts: list[str]):
        return [[1.0, 0.0] for _ in texts]


class SpanSegmentationTest(unittest.TestCase):
    def test_optional_boundaries_are_neither_rewards_nor_errors(self):
        acceptable = [["ab", "cd", "ef"], ["abcd", "ef"]]
        score = _score_case({2, 4}, 6, acceptable)
        self.assertEqual([4], score["required"])
        self.assertEqual([2], score["optional"])
        self.assertEqual(1, score["tp"])
        self.assertEqual(0, score["fp"])
        self.assertEqual(0, score["fn"])
        self.assertTrue(score["exact"])

    def test_every_final_algorithm_is_embedding_backed(self):
        for segmenter_type in (
            SemanticTilingSegmenter,
            GlobalEmbeddingPartitionSegmenter,
            AdaptiveGlobalEmbeddingPartitionSegmenter,
            PeltEmbeddingSegmenter,
            EmbeddingCandidateSegmenter,
        ):
            self.assertTrue(segmenter_type.embedding_backed)

    def test_reference_cases_are_lossless_and_have_no_labels(self):
        cases = json.loads(DATA_PATH.read_text(encoding="utf-8"))
        self.assertEqual(20, len(cases))
        for case in cases:
            for accepted in case["acceptable_segmentations"]:
                self.assertEqual(case["text"], "".join(accepted))
                self.assertTrue(all(segment for segment in accepted))
            self.assertNotIn("labels", case)

    def test_v2_reference_cases_are_lossless_and_challenging(self):
        cases = json.loads(DATA_V2_PATH.read_text(encoding="utf-8"))
        self.assertEqual(40, len(cases))
        challenges = {case["challenge"] for case in cases}
        self.assertGreaterEqual(len(challenges), 12)
        self.assertIn("no_punctuation", challenges)
        self.assertIn("irrelevant_fact", challenges)
        self.assertIn("double_negative", challenges)
        for case in cases:
            for accepted in case["acceptable_segmentations"]:
                self.assertEqual(case["text"], "".join(accepted))
                self.assertTrue(all(segment for segment in accepted))
            self.assertNotIn("labels", case)

    def test_syntax_backend_only_proposes_unlabelled_boundaries(self):
        boundaries = SyntacticBoundaryProposer(analyzer=_FakeAnalyzer()).propose(
            "以后默认用柱状图。"
        )
        self.assertEqual((2, 5), tuple(item.position for item in boundaries))
        self.assertFalse(
            any(
                word in boundary.source
                for boundary in boundaries
                for word in ("condition", "attitude", "object", "temporal")
            )
        )

    def test_crf_adapter_requires_lossless_prediction(self):
        boundaries = CrfBoundaryProposer(
            predictor=lambda text: ["以后", "默认用", "柱状图。"]
        ).propose("以后默认用柱状图。")
        self.assertEqual((2, 5), tuple(item.position for item in boundaries))
        with self.assertRaises(ValueError):
            CrfBoundaryProposer(
                predictor=lambda text: ["以后", "错误文本"]
            ).propose("以后默认用柱状图。")

    def test_candidate_boundaries_require_embedding_majority_decision(self):
        proposer = CrfBoundaryProposer(
            predictor=lambda text: ["以后", "默认用", "柱状图。"]
        )
        result = EmbeddingCandidateSegmenter(
            _FakeEmbedder(),
            [proposer],
            semantic_weight=0.70,
            threshold=0.0,
            target_segment_chars=3,
        ).segment("以后默认用柱状图。")
        self.assertEqual((2, 5), result.boundary_positions)
        self.assertTrue(
            all(
                "embedding_majority_decision" in boundary.evidence
                for boundary in result.boundaries
                if not boundary.hard
            )
        )

    def test_character_gap_route_is_embedding_decoded(self):
        result = EmbeddingCandidateSegmenter(
            _FakeEmbedder(),
            [CharacterGapProposer()],
            semantic_weight=0.70,
            threshold=0.0,
        ).segment("以后默认用柱状图。")
        result.assert_lossless()
        self.assertTrue(
            all(
                "embedding_majority_decision" in boundary.evidence
                for boundary in result.boundaries
                if not boundary.hard
            )
        )

    def test_no_semantic_change_does_not_force_a_boundary(self):
        text = "这个短语保持完整"
        candidate_result = EmbeddingCandidateSegmenter(
            _ConstantEmbedder(),
            [CharacterGapProposer()],
        ).segment(text)
        tiling_result = SemanticTilingSegmenter(_ConstantEmbedder()).segment(text)
        self.assertEqual((text,), tuple(item.text for item in candidate_result.segments))
        self.assertEqual((text,), tuple(item.text for item in tiling_result.segments))

    def test_global_embedding_partition_is_lossless(self):
        result = GlobalEmbeddingPartitionSegmenter(
            _FakeEmbedder(),
            penalty=0.01,
        ).segment("预算比较时柱形图不太适合，或许应该换成折线图。")
        result.assert_lossless()
        analyzed = [
            clause
            for clause in result.diagnostics["clauses"]
            if "partition" in clause
        ]
        self.assertTrue(analyzed)
        partition = analyzed[0]["partition"]
        self.assertGreater(partition["vector_norm_min"], 0.0)
        self.assertGreaterEqual(
            partition["no_split_cost"],
            partition["partition_cost"],
        )
        self.assertGreaterEqual(partition["relative_gain"], 0.0)
        self.assertLessEqual(partition["relative_gain"], 1.0)

    def test_adaptive_global_partition_preserves_null_decision(self):
        text = "这个短语应该保持完整没有变化"
        result = AdaptiveGlobalEmbeddingPartitionSegmenter(
            _ConstantEmbedder(),
        ).segment(text)
        result.assert_lossless()
        self.assertEqual((), result.boundary_positions)
        analyzed = [
            clause
            for clause in result.diagnostics["clauses"]
            if "model_selection" in clause
        ]
        self.assertTrue(analyzed)
        self.assertTrue(
            all(
                clause["model_selection"]["selected_segments"] == 1
                for clause in analyzed
            )
        )

    def test_adaptive_global_partition_is_lossless(self):
        result = AdaptiveGlobalEmbeddingPartitionSegmenter(
            _FakeEmbedder(),
        ).segment("预算比较时柱形图不太适合，或许应该换成折线图。")
        result.assert_lossless()

    def test_window_change_point_maps_to_semantic_center(self):
        self.assertEqual(
            8,
            _window_change_point_position([0, 2, 4, 6], 2, 8),
        )

    def test_atom_score_rewards_intact_isolated_targets(self):
        text = "当前会话先按这个模板走"
        atoms = [
            {"text": "当前会话", "label": "temporal"},
            {"text": "先按", "label": "attitude"},
            {"text": "这个模板", "label": "object"},
        ]
        score = score_atom_partition(text, atoms, {4, 6})
        self.assertEqual(3, score["intact_atoms"])
        self.assertEqual(3, score["isolated_atoms"])
        self.assertEqual(3, score["recoverable_atoms"]["4"])
        self.assertTrue(score["segment_count_sufficient"])

    def test_atom_score_rejects_split_and_merged_targets(self):
        text = "当前会话先按这个模板走"
        atoms = [
            {"text": "当前会话", "label": "temporal"},
            {"text": "先按", "label": "attitude"},
            {"text": "这个模板", "label": "object"},
        ]
        merged = score_atom_partition(text, atoms, set())
        split = score_atom_partition(text, atoms, {5, 6})
        self.assertEqual(3, merged["merged_atoms"])
        self.assertEqual(0, merged["isolated_atoms"])
        self.assertFalse(merged["segment_count_sufficient"])
        self.assertEqual(1, split["split_atoms"])
        self.assertFalse(split["atom_results"][1]["recoverable"]["8"])

    @unittest.skipUnless(
        CHINESE_TOKENIZER_AVAILABLE,
        "Jieba is required for generalized Chinese lexical protection",
    )
    def test_atom_score_only_fully_penalizes_lexical_splits(self):
        text = "以后统一用柱状图"
        atoms = [
            {
                "text": "以后统一",
                "label": "temporal",
            },
            {
                "text": "柱状图",
                "label": "object",
            },
        ]
        benign = score_atom_partition(text, atoms, {2, 4})
        destructive = score_atom_partition(text, atoms, {3, 4, 6})
        self.assertTrue(benign["atom_results"][0]["benign_split"])
        self.assertEqual(
            0.5,
            benign["atom_results"][0]["recovery_credit"]["4"],
        )
        self.assertTrue(
            destructive["atom_results"][0]["catastrophic_split"]
        )
        self.assertTrue(
            destructive["atom_results"][1]["catastrophic_split"]
        )
        self.assertEqual(
            0.0,
            destructive["atom_results"][1]["recovery_credit"]["4"],
        )
        negation = score_atom_partition(
            "不用记住",
            [{"text": "不用记住", "label": "attitude"}],
            {1},
        )
        self.assertTrue(negation["atom_results"][0]["benign_split"])

    def test_ascii_identifiers_are_lexically_indivisible(self):
        text = "use time.windows.com,0x9 now"
        atoms = [{"text": "time.windows.com,0x9", "label": "object"}]
        comma = text.index(",") + 1
        inside_domain = text.index(".") + 1
        benign = score_atom_partition(text, atoms, {comma})
        destructive = score_atom_partition(text, atoms, {inside_domain})
        self.assertTrue(benign["atom_results"][0]["benign_split"])
        self.assertTrue(
            destructive["atom_results"][0]["catastrophic_split"]
        )

    def test_semantic_tiling_returns_a_valid_partition(self):
        text = "预算比较时柱形图不太适合，或许应该换成折线图。"
        result = SemanticTilingSegmenter(_FakeEmbedder()).segment(text)
        result.assert_lossless()
        self.assertTrue(all(0 < position < len(text) for position in result.boundary_positions))
        self.assertTrue(
            all(
                result.boundary_positions[index]
                < result.boundary_positions[index + 1]
                for index in range(len(result.boundary_positions) - 1)
            )
        )

if __name__ == "__main__":
    unittest.main()
