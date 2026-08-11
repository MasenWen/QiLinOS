from __future__ import annotations

import argparse
import json
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.memory_engine.reflection import (
    ReflectionScheduleInput,
    calculate_reflection_schedule,
)


DEFAULT_OUTPUT = Path(
    "outputs/memory_reflection/reflection_schedule_v1.json"
)
BASE = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _at(hours: float) -> str:
    return (BASE + timedelta(hours=hours)).isoformat()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    ready = ReflectionScheduleInput(
        now=_at(240),
        last_reflection_at=_at(0),
        active_memory_count=500,
        unreviewed_memory_count=300,
        changed_memory_count=80,
        high_risk_memory_count=30,
        idle_seconds=3600,
        predicted_idle_seconds=2400,
        predicted_idle_probability=0.95,
        active_task_count=0,
        resource_pressure=0.10,
    )
    scenarios = {
        "large_idle_backlog": ready,
        "active_user_task": replace(ready, active_task_count=1),
        "insufficient_current_idle": replace(ready, idle_seconds=120),
        "short_predicted_window": replace(
            ready,
            predicted_idle_seconds=180,
        ),
        "weak_idle_prediction": replace(
            ready,
            predicted_idle_probability=0.45,
        ),
        "resource_pressure": replace(ready, resource_pressure=0.95),
        "small_clean_store": replace(
            ready,
            active_memory_count=12,
            unreviewed_memory_count=0,
            changed_memory_count=0,
            high_risk_memory_count=0,
        ),
        "immediate_repeat": replace(
            ready,
            last_reflection_at=_at(239.5),
            unreviewed_memory_count=0,
            changed_memory_count=0,
        ),
    }
    rows = {
        name: {
            "input": asdict(value),
            "decision": calculate_reflection_schedule(value).to_dict(),
        }
        for name, value in scenarios.items()
    }
    expected = {
        "large_idle_backlog": True,
        "active_user_task": False,
        "insufficient_current_idle": False,
        "short_predicted_window": False,
        "weak_idle_prediction": False,
        "resource_pressure": False,
        "small_clean_store": False,
        "immediate_repeat": False,
    }
    checks = {
        name: rows[name]["decision"]["should_reflect"] == value
        for name, value in expected.items()
    }
    if not all(checks.values()):
        raise AssertionError(f"schedule checks failed: {checks}")
    output = {
        "purpose": (
            "Reflection scheduling is tested separately from quality "
            "evaluation so background maintenance cannot affect users."
        ),
        "formula_properties": {
            "elapsed_since_last_reflection": "positive_saturating",
            "memory_backlog": "strong_positive_saturating",
            "active_task": "hard_block",
            "current_idle": "hard_gate",
            "predicted_idle_window": "hard_gate",
            "cooldown": "hard_gate",
            "resource_pressure": "hard_block",
        },
        "checks": checks,
        "scenarios": rows,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(output, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "output": str(args.output),
                "all_checks_passed": all(checks.values()),
                "checks": checks,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
