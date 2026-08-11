from __future__ import annotations

import hashlib

import numpy as np

from src.memory_engine.knowledge_tags import (
    WorkplaceTagKnowledgeBase,
    load_seed_tags,
    merge_canonical_tags,
)
from src.memory_engine.observation import ObservationMatcher
from src.memory_engine.preference_matching import (
    CanonicalRoleMatch,
    CanonicalTag,
    PreferenceObservationOptions,
)


class HashEmbedder:
    def embed(self, texts: list[str]) -> list[np.ndarray]:
        vectors = []
        for text in texts:
            digest = hashlib.sha256(text.encode("utf-8")).digest()
            vector = np.frombuffer(digest[:16], dtype=np.uint8).astype(np.float32)
            vector -= 127.5
            vector /= max(1e-9, float(np.linalg.norm(vector)))
            vectors.append(vector)
        return vectors


def _tags() -> tuple[CanonicalTag, ...]:
    return (
        CanonicalTag(
            "app:codex",
            "Codex",
            ("condition", "object"),
            ("ChatGPT Codex", "代码助手"),
            ("用于编程和代码解释的智能助手",),
        ),
        CanonicalTag(
            "action:confirm_send",
            "Confirm Before Sending",
            ("object",),
            ("发送前确认", "发出前让我确认"),
            ("邮件真正发送前先获得用户确认",),
        ),
        CanonicalTag(
            "condition:network",
            "Unstable Network",
            ("condition",),
            ("网络不稳定", "网络异常"),
            ("网络连接无法可靠使用的场景",),
        ),
    )


def test_exact_alias_and_bm25_candidates(tmp_path):
    knowledge = WorkplaceTagKnowledgeBase.build(tmp_path / "tags.sqlite", _tags())

    values = knowledge.query("以后用 ChatGPT Codex 解释代码")

    assert values[0].tag_id == "app:codex"
    assert values[0].exact_alias is True
    assert "condition" in values[0].groups
    assert "object" in values[0].groups


def test_group_limits_are_independent(tmp_path):
    knowledge = WorkplaceTagKnowledgeBase.build(tmp_path / "tags.sqlite", _tags())

    values = knowledge.query(
        "网络异常时邮件发出前让我确认",
        top_k_per_group=1,
    )

    assert {value.tag_id for value in values} == {
        "condition:network",
        "action:confirm_send",
    }


def test_observation_options_fill_only_open_roles(tmp_path):
    knowledge = WorkplaceTagKnowledgeBase.build(tmp_path / "tags.sqlite", _tags())
    matcher = ObservationMatcher(
        HashEmbedder(),
        knowledge_base=knowledge,
        tags=(),
    )
    base = PreferenceObservationOptions(
        condition_tag_ids=("condition:existing",),
        object_tag_ids=(),
        temporal_labels=("temporal_short",),
    )

    options, candidates = matcher.knowledge_options(
        "网络不稳定时用Codex，发出前让我确认",
        options=base,
    )

    assert options.condition_tag_ids[0] == "condition:existing"
    assert "condition:network" not in options.condition_tag_ids
    assert "app:codex" not in options.condition_tag_ids
    assert "action:confirm_send" in options.object_tag_ids
    assert candidates


def test_closed_role_options_are_not_expanded_by_knowledge(tmp_path):
    knowledge = WorkplaceTagKnowledgeBase.build(tmp_path / "tags.sqlite", _tags())
    matcher = ObservationMatcher(
        HashEmbedder(),
        knowledge_base=knowledge,
        tags=(),
    )
    base = PreferenceObservationOptions(
        condition_tag_ids=("condition:existing",),
        object_tag_ids=("object:existing",),
        temporal_labels=("temporal_short",),
    )

    options, candidates = matcher.knowledge_options(
        "网络不稳定时用 Codex，发出前让我确认",
        options=base,
    )

    assert options.condition_tag_ids == base.condition_tag_ids
    assert options.object_tag_ids == base.object_tag_ids
    assert candidates


def test_full_seed_has_all_selected_packs_and_excludes_deferred_packs():
    tags, packs, _ = load_seed_tags("knowledge/workplace_tags_seed_v1.json")
    selected = set(packs.values())

    assert len(tags) >= 80
    assert len(selected) == 18
    assert "business-workflows" not in selected
    assert "organization-private" not in selected
    assert len(merge_canonical_tags(tags, tags)) == len(tags)


def _role(group: str, start: int, end: int) -> CanonicalRoleMatch:
    return CanonicalRoleMatch(
        start=start,
        end=end,
        text="Excel",
        group=group,
        tag_id="app:spreadsheet",
        tag_name="Spreadsheet",
        score=1.16,
        similarity=1.0,
        exact_alias=True,
        hypothesis_score=1.0,
        sources=("knowledge_test",),
    )


def test_knowledge_role_cues_separate_condition_and_object():
    condition_text = "在Excel里整理预算"
    condition_roles, condition_changes = ObservationMatcher._resolve_knowledge_roles(
        condition_text,
        (_role("condition", 1, 6), _role("object", 1, 6)),
        {"app:spreadsheet"},
    )
    object_text = "优先使用Excel"
    object_roles, object_changes = ObservationMatcher._resolve_knowledge_roles(
        object_text,
        (_role("condition", 4, 9), _role("object", 4, 9)),
        {"app:spreadsheet"},
    )

    assert [value.group for value in condition_roles] == ["condition"]
    assert [value.group for value in object_roles] == ["object"]
    assert condition_changes == object_changes == 1
