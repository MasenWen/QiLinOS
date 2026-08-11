from __future__ import annotations

import unittest

import numpy as np

from src.memory_engine.observation import (
    ObservationMatcher,
    condition_contexts,
    condition_context_views,
)
from src.memory_engine.preference_matching import (
    CanonicalTag,
    PreferenceObservationOptions,
)
from src.memory_engine.semantic_episode import (
    SemanticEpisodeConfig,
    SemanticEpisodeEvent,
    group_semantic_episode_events,
)
from src.memory_engine.span_matching import CharacterSpanTokenizer


def _event(
    index: int,
    *,
    condition: str = "",
    obj: str = "",
) -> SemanticEpisodeEvent:
    return SemanticEpisodeEvent(
        event_id=f"event-{index}",
        observed_time=f"2026-01-01T00:00:{index:02d}+00:00",
        condition_tag_ids=(condition,) if condition else (),
        object_tag_ids=(obj,) if obj else (),
    )


class SemanticEpisodeGroupingTest(unittest.TestCase):
    def test_unknown_condition_is_reassigned_after_next_condition(
        self,
    ) -> None:
        result = group_semantic_episode_events(
            [
                _event(0, condition="task:a", obj="object:x"),
                _event(1, obj="object:y"),
                _event(2, condition="task:b", obj="object:y"),
            ],
            config=SemanticEpisodeConfig(
                retroactive_unknown_condition=True,
                object_conflict_confirmation=2,
            ),
        )

        self.assertNotEqual(
            result.assignments["event-0"],
            result.assignments["event-1"],
        )
        self.assertEqual(
            result.assignments["event-1"],
            result.assignments["event-2"],
        )
        self.assertEqual(
            "condition_unknown_reassigned",
            result.decisions[1].reason,
        )

    def test_one_object_conflict_does_not_split(self) -> None:
        result = group_semantic_episode_events(
            [
                _event(0, obj="object:x"),
                _event(1, obj="object:y"),
                _event(2, obj="object:x"),
            ],
            config=SemanticEpisodeConfig(
                object_conflict_confirmation=2
            ),
        )

        self.assertEqual(1, len(set(result.assignments.values())))
        self.assertEqual(
            "object_conflict_pending",
            result.decisions[1].reason,
        )

    def test_two_object_conflicts_confirm_the_first_boundary(
        self,
    ) -> None:
        result = group_semantic_episode_events(
            [
                _event(0, obj="object:x"),
                _event(1, obj="object:y"),
                _event(2, obj="object:y"),
            ],
            config=SemanticEpisodeConfig(
                object_conflict_confirmation=2
            ),
        )

        self.assertNotEqual(
            result.assignments["event-0"],
            result.assignments["event-1"],
        )
        self.assertEqual(
            result.assignments["event-1"],
            result.assignments["event-2"],
        )
        self.assertEqual(
            "object_conflict_confirmed",
            result.decisions[1].reason,
        )

    def test_unresolved_object_conflict_keeps_original_split(
        self,
    ) -> None:
        result = group_semantic_episode_events(
            [
                _event(0, obj="object:x"),
                _event(1, obj="object:y"),
                _event(2),
            ],
            config=SemanticEpisodeConfig(
                object_conflict_confirmation=2
            ),
        )

        self.assertNotEqual(
            result.assignments["event-0"],
            result.assignments["event-1"],
        )
        self.assertEqual(
            result.assignments["event-1"],
            result.assignments["event-2"],
        )
        self.assertEqual(
            "object_conflict_unresolved_split",
            result.decisions[1].reason,
        )

    def test_condition_reassignment_requires_object_support(
        self,
    ) -> None:
        result = group_semantic_episode_events(
            [
                _event(0, condition="task:a", obj="object:x"),
                _event(1),
                _event(2, condition="task:b", obj="object:y"),
            ],
            config=SemanticEpisodeConfig(
                retroactive_unknown_condition=True
            ),
        )

        self.assertEqual(
            result.assignments["event-0"],
            result.assignments["event-1"],
        )
        self.assertNotEqual(
            result.assignments["event-1"],
            result.assignments["event-2"],
        )
        self.assertEqual(
            "condition_conflict",
            result.decisions[2].reason,
        )

    def test_object_confirmation_can_be_disabled(self) -> None:
        result = group_semantic_episode_events(
            [
                _event(0, obj="object:x"),
                _event(1, obj="object:y"),
            ],
            config=SemanticEpisodeConfig(
                object_conflict_confirmation=1
            ),
        )

        self.assertNotEqual(
            result.assignments["event-0"],
            result.assignments["event-1"],
        )
        self.assertEqual("object_conflict", result.decisions[1].reason)

    def test_relation_object_can_bridge_a_substantive_object(self) -> None:
        result = group_semantic_episode_events(
            [
                _event(0, obj="object:output"),
                _event(1, obj="object:versioning"),
                _event(2, obj="object:output"),
            ],
            config=SemanticEpisodeConfig(
                object_bridge_tag_ids=("object:versioning",)
            ),
        )

        self.assertEqual(1, len(set(result.assignments.values())))
        self.assertEqual(
            "object_bridge_compatible",
            result.decisions[1].reason,
        )

    def test_condition_evidence_has_priority_over_object_debounce(
        self,
    ) -> None:
        result = group_semantic_episode_events(
            [
                _event(0, condition="task:a", obj="object:x"),
                _event(1, condition="task:b", obj="object:x"),
            ]
        )

        self.assertNotEqual(
            result.assignments["event-0"],
            result.assignments["event-1"],
        )
        self.assertEqual(
            "condition_conflict",
            result.decisions[1].reason,
        )


class ConditionContextTest(unittest.TestCase):
    def test_extracts_short_chinese_condition_clause(self) -> None:
        text = (
            "\u5904\u7406\u5185\u90e8\u4f1a\u8bae"
            "\u5b89\u6392\u65f6\uff0c\u6ca1\u6709"
            "\u6743\u9650\u4e0d\u8981\u5199\u5165"
        )

        contexts = condition_contexts(text)

        self.assertEqual(
            "\u5904\u7406\u5185\u90e8\u4f1a\u8bae"
            "\u5b89\u6392\u65f6",
            contexts[0].text,
        )

    def test_extracts_english_context_without_splitting_words(
        self,
    ) -> None:
        text = (
            "When preparing the quarterly report, "
            "keep the latest three items."
        )

        contexts = condition_contexts(text)

        self.assertEqual(
            "When preparing the quarterly report",
            contexts[0].text,
        )

    def test_multiview_keeps_short_and_full_condition_clause(
        self,
    ) -> None:
        text = (
            "\u5904\u7406\u5185\u90e8\u4f1a\u8bae"
            "\u5b89\u6392\u65f6\uff0c\u6ca1\u6709"
            "\u6743\u9650\u4e0d\u8981\u5199\u5165"
        )

        contexts = condition_context_views(text)

        self.assertEqual(
            {
                "\u5904\u7406\u5185\u90e8\u4f1a\u8bae"
                "\u5b89\u6392\u65f6",
                "\u5904\u7406\u5185\u90e8\u4f1a\u8bae"
                "\u5b89\u6392\u65f6\uff0c\u6ca1\u6709"
                "\u6743\u9650\u4e0d\u8981\u5199\u5165",
            },
            {context.text for context in contexts},
        )

    def test_closed_choice_fallback_bypasses_frame_candidate_filter(
        self,
    ) -> None:
        class _Embedder:
            def embed(self, texts: list[str]) -> np.ndarray:
                values = []
                for text in texts:
                    lowered = text.casefold()
                    if "report" in lowered:
                        values.append((1.0, 0.0, 0.0))
                    elif "meeting" in lowered:
                        values.append((0.0, 1.0, 0.0))
                    else:
                        values.append((0.0, 0.0, 1.0))
                return np.asarray(values, dtype=np.float32)

        tags = (
            CanonicalTag(
                tag_id="condition:report",
                name="quarterly report",
                groups=("condition",),
                aliases=(),
                prototypes=("prepare a report",),
            ),
            CanonicalTag(
                tag_id="condition:meeting",
                name="team meeting",
                groups=("condition",),
                aliases=(),
                prototypes=("arrange a meeting",),
            ),
        )
        matcher = ObservationMatcher(
            _Embedder(),
            tokenizer=CharacterSpanTokenizer(),
            tags=tags,
        )

        matches = matcher.match_condition_contexts(
            (
                "When preparing the quarterly report, "
                "keep only the latest items."
            ),
            options=PreferenceObservationOptions(
                condition_tag_ids=(
                    "condition:report",
                    "condition:meeting",
                )
            ),
        )

        self.assertEqual(
            "condition:report",
            matches[0].result.canonical_matches[0].tag_id,
        )
        self.assertEqual(
            "condition_context_closed_choice",
            matches[0].result.algorithm,
        )

    def test_closed_choice_can_return_score_view_below_threshold(
        self,
    ) -> None:
        class _Embedder:
            def embed(self, texts: list[str]) -> np.ndarray:
                values = []
                for text in texts:
                    lowered = text.casefold()
                    if "report" in lowered:
                        values.append((0.49, 0.0, 0.87))
                    elif "meeting" in lowered:
                        values.append((0.0, 0.48, 0.88))
                    else:
                        values.append((0.0, 0.0, 1.0))
                return np.asarray(values, dtype=np.float32)

        matcher = ObservationMatcher(
            _Embedder(),
            tokenizer=CharacterSpanTokenizer(),
            tags=(
                CanonicalTag(
                    tag_id="condition:report",
                    name="quarterly report",
                    groups=("condition",),
                    aliases=(),
                    prototypes=(),
                ),
                CanonicalTag(
                    tag_id="condition:meeting",
                    name="team meeting",
                    groups=("condition",),
                    aliases=(),
                    prototypes=(),
                ),
            ),
        )

        matches = matcher.match_condition_contexts(
            "When preparing an update, keep it brief.",
            options=PreferenceObservationOptions(
                condition_tag_ids=(
                    "condition:report",
                    "condition:meeting",
                )
            ),
            top_k_per_context=2,
            include_below_threshold=True,
        )

        self.assertEqual(
            {"condition:report", "condition:meeting"},
            {
                match.tag_id
                for match in matches[0].result.canonical_matches
            },
        )


if __name__ == "__main__":
    unittest.main()
