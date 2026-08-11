from __future__ import annotations

import os
import re
from pathlib import Path
from unittest.mock import patch

import tools.evaluate_mainline_generalization as mainline
from src.memory_engine.conflict import (
    ConflictAssessment,
    ConflictLink,
    ConflictReason,
)
from tools.build_mainline_generalization_observations import build_dataset
from tools.evaluate_mainline_generalization import (
    candidate_evaluation,
    conflict_evaluation,
    episode_evaluation,
    lifecycle_evaluation,
    structured_observation_evaluation,
)


WORKSPACE_ROOT = Path(
    os.getenv(
        "MAINLINE_DATASET_ROOT",
        str(Path(__file__).resolve().parents[2]),
    )
)


def _normalized(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().casefold()


def test_holdout_observation_dataset_is_deduplicated_and_closed_choice():
    payload = build_dataset(WORKSPACE_ROOT)
    cases = payload["cases"]
    assert len(cases) >= 45
    assert len({_normalized(case["text"]) for case in cases}) == len(cases)
    assert set(payload["audit"]["source_counts"]) == {
        "v1",
        "memory_test",
    }
    for case in cases:
        options = case["options"]
        for gold in case["gold_observations"]:
            assert (
                gold["condition_tag_id"]
                in options["condition_tag_ids"]
            )
            assert gold["object_tag_id"] in options["object_tag_ids"]
            assert gold["support"]["attitude"] == "implicit"
            assert gold["support"]["temporal"] == "implicit"


def test_structured_observation_holdout_preserves_source_keys():
    payload = structured_observation_evaluation(WORKSPACE_ROOT)
    assert payload["input"]["event_count"] == 852
    assert payload["all_required_fields_exact"]["accuracy"] == 1.0
    assert not payload["failures"]


def test_episode_generalization_reports_session_and_continuous_tracks():
    payload = episode_evaluation(WORKSPACE_ROOT)
    tracks = {item["dataset"]: item for item in payload["tracks"]}
    assert len(tracks) == 6
    assert (
        tracks["agent_memory_challenge_v2/continuous"][
            "semantic_target"
        ]["merge_recall"]
        == 1.0
    )
    assert (
        tracks["os_agent_memory_benchmark_v1/continuous"][
            "session_target"
        ]["pure_predicted_rate"]
        < 1.0
    )


def test_candidate_and_lifecycle_oracle_tracks_are_explicitly_bounded():
    candidate = candidate_evaluation(WORKSPACE_ROOT)
    assert candidate["observation_relations"]["precision"] == 1.0
    assert candidate["observation_relations"]["recall"] == 1.0
    assert candidate["memory_relations"]["precision"] == 1.0
    assert candidate["memory_relations"]["recall"] == 1.0
    assert (
        candidate["input"]["gold_observation_relation_pairs"] == 48
    )
    assert candidate["input"]["gold_memory_relation_pairs"] == 36
    assert not candidate["input"]["unsupported_gold_groups"]
    assert candidate["matrix_undirected_symmetric"]
    assert "ConflictResolver" in candidate["scope_note"]

    conflict = conflict_evaluation(WORKSPACE_ROOT)
    assert conflict["input"]["scored_conflict_pairs"] == 36
    assert conflict["detection"]["precision"] >= 0.90
    assert conflict["detection"]["recall"] >= 0.90
    assert conflict["detection"]["type_accuracy"] >= 0.90
    assert conflict["direction"]["accuracy"] == 1.0
    assert conflict["confidence"]["policy_accuracy"] == 1.0
    assert (
        conflict["integration"]["retrieval_companion_accuracy"]
        == 1.0
    )
    assert (
        conflict["integration"]["snapshot_roundtrip_accuracy"]
        == 1.0
    )

    lifecycle = lifecycle_evaluation(WORKSPACE_ROOT)
    exact = lifecycle["retrieval_activation"]
    stress = lifecycle["missing_condition_stress"]
    assert exact["required_memory_hit_recall"] == 1.0
    assert 0.70 <= stress["required_memory_hit_recall"] < 1.0
    assert (
        lifecycle["recession_transitions"][
            "supported_action_accuracy"
        ]
        == 1.0
    )
    assert set(
        lifecycle["recession_transitions"]["unsupported_actions"]
    ) == {"ARCHIVE", "ERASE"}
    assert (
        exact["conflict_aware_retrieval"][
            "companion_non_activation_accuracy"
        ]
        == 1.0
    )


def test_candidate_scores_extra_inferred_conflicts_as_unexpected():
    base = (
        WORKSPACE_ROOT
        / "os_agent_memory_benchmark_v1"
        / "os_agent_memory_benchmark_v1"
    )
    memories = [
        row
        for row in mainline._rows(
            base / "data" / "memory_ground_truth.csv"
        )
        if row["split"] == "test"
    ]
    evidence = [
        row
        for row in mainline._rows(
            base / "data" / "evidence_ground_truth.csv"
        )
        if row["split"] == "test"
    ]
    evidence_by_id = {row["evidence_id"]: row for row in evidence}
    runtime = mainline._build_conflict_runtime(
        memories,
        evidence_by_id,
    )
    left_id = "MEM-U025-MAIL-CONFIRM"
    right_id = "MEM-U025-OFFICE-APP"
    injected = ConflictAssessment(
        detector="test.injected",
        conflict_type="static",
        memory_ids=(left_id, right_id),
        probability=0.95,
        condition_relation="equal",
        time_relation="unbounded",
        explanation="Injected false positive for leakage regression.",
        reasons=(
            ConflictReason(
                code="test",
                summary="Synthetic extra prediction.",
                strength=1.0,
            ),
        ),
        confidence_factors={left_id: 0.8, right_id: 0.8},
        links=(
            ConflictLink(
                source_memory_id=left_id,
                target_memory_id=right_id,
                relation_type="conflicts",
                weight=0.95,
                directed=False,
            ),
        ),
        conflict_scope={"kind": "global"},
    )
    patched_runtime = {
        **runtime,
        "assessments": (*runtime["assessments"], injected),
    }

    with patch.object(
        mainline,
        "_build_conflict_runtime",
        return_value=patched_runtime,
    ):
        payload = mainline.candidate_evaluation(WORKSPACE_ROOT)

    assert payload["observation_relations"]["precision"] < 1.0
    assert payload["memory_relations"]["precision"] < 1.0
    assert payload["observation_relations"]["unexpected"]
    assert payload["memory_relations"]["unexpected"]
