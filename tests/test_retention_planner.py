from __future__ import annotations

import unittest
from datetime import datetime, timezone

from src.memory_engine.strict.contracts import LifecycleStatus, StrictMemory
from src.memory_engine.strict.retention import (
    RetentionCurveArchivePlanner,
    RetentionCurveConfig,
)


def memory(
    memory_id: str,
    *,
    score: float,
    created_at: str = "2026-07-01T00:00:00+00:00",
    status: LifecycleStatus = LifecycleStatus.STABLE,
) -> StrictMemory:
    return StrictMemory(
        memory_id=memory_id,
        user_id="U001",
        memory_family="preference",
        candidate_kind="fact",
        slot_key="preference:tool",
        semantic_value=memory_id,
        condition={},
        scope={"user_id": "U001"},
        cardinality="single",
        status=status,
        evidence_ids=(f"evidence-{memory_id}",),
        support_unit_ids=(f"unit-{memory_id}",),
        oppose_unit_ids=(),
        applicable_unit_ids=(f"unit-{memory_id}",),
        valid_from=created_at,
        valid_to="",
        predecessor_memory_ids=(),
        successor_memory_ids=(),
        conflict_group_ids=(),
        confidence={"absolute": score},
        stability={
            "value": score,
            "parameters": {"target_n": 1},
        },
        provenance={"directness": "observed_behavior"},
        version=1,
        created_at=created_at,
        updated_at=created_at,
    )


class RetentionPlannerTest(unittest.TestCase):
    def test_no_previous_maintenance_is_conservative(self):
        planner = RetentionCurveArchivePlanner()
        plan = planner.plan(
            [memory("weak", score=0.0)],
            now="2026-07-10T00:00:00+00:00",
        )
        self.assertEqual(0.0, plan.time_factor)
        self.assertEqual((), plan.archive_memory_ids)

    def test_threshold_archives_all_insufficient_memories(self):
        planner = RetentionCurveArchivePlanner(
            RetentionCurveConfig(
                reference_active_count=1,
                hard_active_count=10,
                minimum_age_days=0.0,
            )
        )
        plan = planner.plan(
            [
                memory("weak-a", score=0.0),
                memory("weak-b", score=0.0),
                memory("strong", score=1.0),
            ],
            now="2026-07-10T00:00:00+00:00",
            last_maintenance_at="2026-07-01T00:00:00+00:00",
        )
        self.assertEqual(("weak-a", "weak-b"), plan.archive_memory_ids)
        self.assertNotIn("strong", plan.archive_memory_ids)

    def test_recent_memory_has_grace_period(self):
        planner = RetentionCurveArchivePlanner(
            RetentionCurveConfig(minimum_age_days=2.0)
        )
        recent = memory(
            "recent",
            score=0.0,
            created_at="2026-07-09T12:00:00+00:00",
        )
        plan = planner.plan(
            [recent],
            now=datetime(2026, 7, 10, tzinfo=timezone.utc),
            last_maintenance_at="2026-07-01T00:00:00+00:00",
        )
        self.assertEqual((), plan.archive_memory_ids)
        self.assertTrue(plan.decisions[0].protected_by_grace_period)
