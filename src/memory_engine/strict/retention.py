from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

from .contracts import LifecycleStatus, StrictMemory


ACTIVE_STATUSES = frozenset(
    {
        LifecycleStatus.CANDIDATE,
        LifecycleStatus.STABLE,
        LifecycleStatus.RECOVER,
    }
)


@dataclass(frozen=True)
class RetentionCurveConfig:
    """Parameters for the unconnected retention/archival planner."""

    reference_active_count: int = 800
    hard_active_count: int = 1000
    maintenance_interval_hours: float = 24.0
    pressure_exponent: float = 1.25
    base_archive_threshold: float = 0.30
    pressure_threshold_gain: float = 0.025
    activation_half_life_days: float = 30.0
    minimum_age_days: float = 1.0
    confidence_weight: float = 0.30
    stability_weight: float = 0.30
    activation_weight: float = 0.20
    support_weight: float = 0.15
    source_weight: float = 0.05

    def __post_init__(self) -> None:
        if self.reference_active_count <= 0:
            raise ValueError("reference_active_count must be positive")
        if self.hard_active_count < self.reference_active_count:
            raise ValueError("hard_active_count must not be below reference count")
        if self.maintenance_interval_hours <= 0:
            raise ValueError("maintenance_interval_hours must be positive")
        if self.pressure_exponent <= 0 or self.activation_half_life_days <= 0:
            raise ValueError("pressure exponent and half-life must be positive")
        if self.minimum_age_days < 0:
            raise ValueError("minimum_age_days must not be negative")
        weights = (
            self.confidence_weight,
            self.stability_weight,
            self.activation_weight,
            self.support_weight,
            self.source_weight,
        )
        if any(value < 0 for value in weights) or not math.isclose(
            sum(weights), 1.0, abs_tol=1e-9
        ):
            raise ValueError("retention weights must be non-negative and sum to 1")


@dataclass(frozen=True)
class RetentionDecision:
    memory_id: str
    retention_score: float
    archive_threshold: float
    should_archive: bool
    protected_by_grace_period: bool
    components: Mapping[str, float]


@dataclass(frozen=True)
class RetentionMaintenancePlan:
    active_count: int
    elapsed_hours: float
    time_factor: float
    pressure: float
    archive_threshold: float
    hard_cap_reached: bool
    archive_memory_ids: tuple[str, ...]
    decisions: tuple[RetentionDecision, ...]


class RetentionCurveArchivePlanner:
    """Plan pressure-aware archival without mutating the memory store.

    The planner uses an Ebbinghaus-style exponential time factor and a
    pressure term based on active memory count. It archives every eligible
    memory below the dynamic threshold, rather than selecting a fixed number
    of the lowest-scoring memories.
    """

    module_id = "retention.curve_threshold_archive.v1"

    def __init__(self, config: RetentionCurveConfig | None = None):
        self.config = config or RetentionCurveConfig()

    def plan(
        self,
        memories: Iterable[StrictMemory],
        *,
        now: str | datetime,
        last_maintenance_at: str | datetime | None = None,
    ) -> RetentionMaintenancePlan:
        timestamp = _parse_time(now)
        active = [memory for memory in memories if memory.status in ACTIVE_STATUSES]
        elapsed_hours = self._elapsed_hours(timestamp, last_maintenance_at)
        time_factor = 1.0 - math.exp(
            -elapsed_hours / self.config.maintenance_interval_hours
        )
        count_ratio = len(active) / self.config.reference_active_count
        pressure = count_ratio**self.config.pressure_exponent * time_factor
        archive_threshold = min(
            1.0,
            self.config.base_archive_threshold
            + self.config.pressure_threshold_gain * max(0.0, pressure - 1.0),
        )

        decisions = tuple(
            self._decide(
                memory,
                timestamp=timestamp,
                archive_threshold=archive_threshold,
            )
            for memory in sorted(active, key=lambda item: item.memory_id)
        )
        archive_ids = tuple(
            decision.memory_id
            for decision in decisions
            if decision.should_archive
        )
        return RetentionMaintenancePlan(
            active_count=len(active),
            elapsed_hours=round(elapsed_hours, 8),
            time_factor=round(time_factor, 8),
            pressure=round(pressure, 8),
            archive_threshold=round(archive_threshold, 8),
            hard_cap_reached=len(active) >= self.config.hard_active_count,
            archive_memory_ids=archive_ids,
            decisions=decisions,
        )

    def _decide(
        self,
        memory: StrictMemory,
        *,
        timestamp: datetime,
        archive_threshold: float,
    ) -> RetentionDecision:
        components = self._components(memory, timestamp)
        retention_score = sum(components.values())
        age_days = _age_days(memory, timestamp)
        protected = age_days < self.config.minimum_age_days
        return RetentionDecision(
            memory_id=memory.memory_id,
            retention_score=round(retention_score, 8),
            archive_threshold=round(archive_threshold, 8),
            should_archive=not protected and retention_score < archive_threshold,
            protected_by_grace_period=protected,
            components={
                key: round(value, 8) for key, value in components.items()
            },
        )

    def _components(
        self,
        memory: StrictMemory,
        timestamp: datetime,
    ) -> dict[str, float]:
        confidence = _bounded(
            memory.confidence.get("absolute", memory.confidence.get("value", 0.0))
        )
        stability = _bounded(memory.stability.get("value", 0.0))
        last_activity = _last_activity(memory)
        activity_age = max(
            0.0,
            (timestamp - last_activity).total_seconds() / 86400,
        )
        half_life = self.config.activation_half_life_days
        activation = 0.5 ** (activity_age / half_life)
        support = min(
            1.0,
            len(memory.support_unit_ids)
            / max(1, int(memory.stability.get("parameters", {}).get("target_n", 5))),
        )
        source = _source_reliability(memory.provenance)
        return {
            "confidence": self.config.confidence_weight * confidence,
            "stability": self.config.stability_weight * stability,
            "activation": self.config.activation_weight * activation,
            "support": self.config.support_weight * support,
            "source": self.config.source_weight * source,
        }

    def _elapsed_hours(
        self,
        timestamp: datetime,
        last_maintenance_at: str | datetime | None,
    ) -> float:
        if last_maintenance_at is None:
            return 0.0
        return max(
            0.0,
            (timestamp - _parse_time(last_maintenance_at)).total_seconds() / 3600,
        )


def _parse_time(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _age_days(memory: StrictMemory, timestamp: datetime) -> float:
    return max(0.0, (timestamp - _parse_time(memory.created_at)).total_seconds() / 86400)


def _last_activity(memory: StrictMemory) -> datetime:
    provenance = memory.provenance
    values: list[str] = []
    for key in ("last_activated_at", "last_activation_at"):
        if provenance.get(key):
            values.append(str(provenance[key]))
    history = provenance.get("activation_history") or ()
    if isinstance(history, (list, tuple)):
        values.extend(str(value) for value in history if value)
    if values:
        return max(_parse_time(value) for value in values)
    return _parse_time(memory.created_at)


def _source_reliability(provenance: Mapping[str, Any]) -> float:
    explicit = provenance.get("directness")
    if explicit in {"explicit_user", "versioned_config"}:
        return 1.0
    if explicit == "observed_behavior":
        return 0.75
    value = provenance.get("source_reliability", 0.5)
    return _bounded(value)


def _bounded(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(number, 1.0))
