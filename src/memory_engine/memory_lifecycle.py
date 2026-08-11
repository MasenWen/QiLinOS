from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from typing import Iterable, Mapping


def _clip(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _instant(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _iso(value: str | datetime) -> str:
    return _instant(value).isoformat()


def _days_between(left: str | datetime, right: str | datetime) -> float:
    return max(
        0.0,
        (_instant(right) - _instant(left)).total_seconds() / 86400.0,
    )


def _clean(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(value for value in values if value))


@dataclass(frozen=True)
class ConfidenceEvidence:
    evidence_id: str
    observed_at: str
    source_kind: str
    quality: float
    supports: bool = True
    independent_unit_id: str = ""

    def __post_init__(self) -> None:
        if not self.evidence_id or not self.source_kind:
            raise ValueError("evidence_id and source_kind are required")
        if not 0.0 <= self.quality <= 1.0:
            raise ValueError("quality must be in [0, 1]")
        _instant(self.observed_at)


@dataclass(frozen=True)
class MemoryLifeSeed:
    memory_id: str
    user_id: str
    created_at: str
    source_kind: str
    temporal_label: str
    temporal_confidence: float
    explicit_long_term: bool
    base_strength: float
    condition_tag_ids: tuple[str, ...]
    object_tag_ids: tuple[str, ...]
    attitude_polarity: str
    evidence: tuple[ConfidenceEvidence, ...]
    conflicting_strength: float = 0.0
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.memory_id or not self.user_id or not self.source_kind:
            raise ValueError("memory_id, user_id and source_kind are required")
        _instant(self.created_at)
        for name in (
            "temporal_confidence",
            "base_strength",
            "conflicting_strength",
        ):
            if not 0.0 <= float(getattr(self, name)) <= 1.0:
                raise ValueError(f"{name} must be in [0, 1]")
        object.__setattr__(
            self,
            "condition_tag_ids",
            _clean(self.condition_tag_ids),
        )
        object.__setattr__(
            self,
            "object_tag_ids",
            _clean(self.object_tag_ids),
        )
        if not self.evidence:
            raise ValueError("memory seed requires at least one evidence")


@dataclass(frozen=True)
class LifecycleObservation:
    observation_id: str
    user_id: str
    observed_at: str
    source_kind: str
    condition_tag_ids: tuple[str, ...] = ()
    object_tag_ids: tuple[str, ...] = ()
    attitude_polarity: str = ""
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.observation_id or not self.user_id:
            raise ValueError("observation_id and user_id are required")
        _instant(self.observed_at)
        object.__setattr__(
            self,
            "condition_tag_ids",
            _clean(self.condition_tag_ids),
        )
        object.__setattr__(
            self,
            "object_tag_ids",
            _clean(self.object_tag_ids),
        )


@dataclass(frozen=True)
class MemoryLifeRelation:
    relation_id: str
    source_memory_id: str
    target_memory_id: str
    relation_type: str
    weight: float
    observed_at: str
    directed: bool = False
    affects_confidence: bool = True

    def __post_init__(self) -> None:
        if (
            not self.relation_id
            or not self.source_memory_id
            or not self.target_memory_id
        ):
            raise ValueError("relation ids and endpoints are required")
        if not 0.0 <= self.weight <= 1.0:
            raise ValueError("weight must be in [0, 1]")
        _instant(self.observed_at)


@dataclass
class MemoryLifeState:
    seed: MemoryLifeSeed
    status: str
    stability: dict[str, object]
    confidence: dict[str, object]
    relation_support: dict[str, float] = field(default_factory=dict)
    relation_conflict: dict[str, float] = field(default_factory=dict)
    conflict_factors: dict[str, float] = field(default_factory=dict)
    activation_count: int = 0
    last_activated_at: str = ""
    forgotten_at: str = ""
    reflection_penalty: float = 1.0
    reflection_review_ids: list[str] = field(default_factory=list)
    merged_into: str = ""
    events: list[dict[str, object]] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "memory_id": self.seed.memory_id,
            "status": self.status,
            "source_kind": self.seed.source_kind,
            "temporal_label": self.seed.temporal_label,
            "temporal_confidence": self.seed.temporal_confidence,
            "explicit_long_term": self.seed.explicit_long_term,
            "base_strength": self.seed.base_strength,
            "condition_tag_ids": list(self.seed.condition_tag_ids),
            "object_tag_ids": list(self.seed.object_tag_ids),
            "attitude_polarity": self.seed.attitude_polarity,
            "stability": dict(self.stability),
            "confidence": dict(self.confidence),
            "relation_support": dict(self.relation_support),
            "relation_conflict": dict(self.relation_conflict),
            "conflict_factors": dict(self.conflict_factors),
            "activation_count": self.activation_count,
            "last_activated_at": self.last_activated_at,
            "forgotten_at": self.forgotten_at,
            "reflection_penalty": self.reflection_penalty,
            "reflection_review_ids": list(self.reflection_review_ids),
            "merged_into": self.merged_into,
            "events": list(self.events),
            "metadata": dict(self.seed.metadata),
        }


def _reflection_obsolete_context(
    state: MemoryLifeState,
    at: str | datetime,
) -> dict[str, object]:
    reviewed_at = _instant(at)
    created_at = _instant(state.seed.created_at)
    evidence_times = [
        _instant(evidence.observed_at)
        for evidence in state.seed.evidence
        if (
            evidence.supports
            and _instant(evidence.observed_at) <= reviewed_at
        )
    ]
    activation_times = [
        _instant(str(event["at"]))
        for event in state.events
        if (
            event.get("type") == "activation"
            and event.get("at")
            and _instant(str(event["at"])) <= reviewed_at
        )
    ]
    latest_activity = max((created_at, *evidence_times, *activation_times))
    activation_span_days = (
        max(
            0.0,
            (max(activation_times) - min(activation_times)).total_seconds()
            / 86400.0,
        )
        if len(activation_times) > 1
        else 0.0
    )
    base_horizon = {
        "temporal_short": 60.0,
        "temporal_medium": 180.0,
        "temporal_long": 365.0,
    }.get(state.seed.temporal_label, 90.0)
    if state.seed.explicit_long_term:
        base_horizon = max(base_horizon, 365.0)
    recurrence_bonus = min(
        240.0,
        0.5 * activation_span_days
        + 10.0 * max(0, len(activation_times) - 1),
    )
    obsolete_after_days = base_horizon + recurrence_bonus
    inactivity_days = max(
        0.0,
        (reviewed_at - latest_activity).total_seconds() / 86400.0,
    )
    return {
        "latest_activity_at": latest_activity.isoformat(),
        "first_activated_at": (
            min(activation_times).isoformat() if activation_times else ""
        ),
        "activation_span_days": round(activation_span_days, 6),
        "inactivity_days": round(inactivity_days, 6),
        "obsolete_after_days": round(obsolete_after_days, 6),
        "guarded": inactivity_days < obsolete_after_days,
    }


@dataclass(frozen=True)
class LifecycleSelection:
    memory_id: str
    match_score: float
    retrieval_score: float
    confidence: float
    stability_before: float
    stability_after: float
    rescued: bool
    match_components: Mapping[str, float]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class LifecycleQueryResult:
    observation_id: str
    selected: tuple[LifecycleSelection, ...]
    considered_count: int
    forgotten_during_query: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "observation_id": self.observation_id,
            "selected": [item.to_dict() for item in self.selected],
            "considered_count": self.considered_count,
            "forgotten_during_query": list(
                self.forgotten_during_query
            ),
        }


_TEMPORAL_DAYS = {
    "temporal_short": 21.0,
    "temporal_medium": 90.0,
    "temporal_long": 365.0,
}


def temporal_retention_days(seed: MemoryLifeSeed) -> float:
    neutral_days = 60.0
    label_days = _TEMPORAL_DAYS.get(
        seed.temporal_label,
        neutral_days,
    )
    reliability = seed.temporal_confidence
    if seed.explicit_long_term:
        reliability = max(reliability, 0.95)
    blended = math.exp(
        (1.0 - reliability) * math.log(neutral_days)
        + reliability * math.log(label_days)
    )
    support_count = len(
        {
            item.independent_unit_id or item.evidence_id
            for item in seed.evidence
            if item.supports
        }
    )
    support_factor = 1.0 + 0.18 * math.log1p(
        max(0, support_count - 1)
    )
    strength_factor = 0.75 + 0.45 * seed.base_strength
    return max(3.0, blended * support_factor * strength_factor)


class StabilityStrategy:
    name = "stability.base"

    def initialize(self, seed: MemoryLifeSeed) -> dict[str, object]:
        raise NotImplementedError

    def value(
        self,
        state: dict[str, object],
        at: str | datetime,
    ) -> float:
        raise NotImplementedError

    def activate(
        self,
        state: dict[str, object],
        at: str | datetime,
        match_score: float,
    ) -> tuple[float, float]:
        raise NotImplementedError

    def reinforce(
        self,
        state: dict[str, object],
        at: str | datetime,
        weight: float,
    ) -> tuple[float, float]:
        raise NotImplementedError


class WeibullSurvivalStability(StabilityStrategy):
    name = "stability.weibull_survival.v1"

    def initialize(self, seed: MemoryLifeSeed) -> dict[str, object]:
        value = _clip(0.55 + 0.40 * seed.base_strength)
        return {
            "method": self.name,
            "value": round(value, 8),
            "anchor_at": _iso(seed.created_at),
            "anchor_value": value,
            "retention_days": temporal_retention_days(seed),
            "shape": 1.15,
            "activation_count": 0,
            "relation_uplift": 0.0,
        }

    def value(
        self,
        state: dict[str, object],
        at: str | datetime,
    ) -> float:
        age = _days_between(str(state["anchor_at"]), at)
        retention = max(0.1, float(state["retention_days"]))
        shape = float(state["shape"])
        survival = float(state["anchor_value"]) * math.exp(
            -math.log(2.0) * (age / retention) ** shape
        )
        state["value"] = round(_clip(survival), 8)
        return float(state["value"])

    def activate(
        self,
        state: dict[str, object],
        at: str | datetime,
        match_score: float,
    ) -> tuple[float, float]:
        before = self.value(state, at)
        match = _clip(match_score)
        state["retention_days"] = float(
            state["retention_days"]
        ) * (1.0 + 0.35 * match + 0.65 * match * (1.0 - before))
        state["anchor_value"] = _clip(
            before + (1.0 - before) * (0.55 + 0.30 * match)
        )
        state["anchor_at"] = _iso(at)
        state["activation_count"] = int(
            state["activation_count"]
        ) + 1
        after = self.value(state, at)
        return before, after

    def reinforce(
        self,
        state: dict[str, object],
        at: str | datetime,
        weight: float,
    ) -> tuple[float, float]:
        before = self.value(state, at)
        strength = _clip(weight)
        state["retention_days"] = float(
            state["retention_days"]
        ) * (1.0 + 0.35 * strength)
        state["anchor_value"] = _clip(
            before + 0.16 * strength * (1.0 - before)
        )
        state["anchor_at"] = _iso(at)
        state["relation_uplift"] = _clip(
            float(state["relation_uplift"]) + 0.16 * strength
        )
        after = self.value(state, at)
        return before, after


class FSRSPowerStability(StabilityStrategy):
    name = "stability.fsrs_power.v1"

    def initialize(self, seed: MemoryLifeSeed) -> dict[str, object]:
        value = _clip(0.58 + 0.38 * seed.base_strength)
        return {
            "method": self.name,
            "value": round(value, 8),
            "anchor_at": _iso(seed.created_at),
            "anchor_value": value,
            "stability_days": temporal_retention_days(seed),
            "decay": 0.90,
            "activation_count": 0,
            "relation_uplift": 0.0,
        }

    def value(
        self,
        state: dict[str, object],
        at: str | datetime,
    ) -> float:
        age = _days_between(str(state["anchor_at"]), at)
        stability_days = max(0.1, float(state["stability_days"]))
        decay = float(state["decay"])
        factor = 2.0 ** (1.0 / decay) - 1.0
        retrievability = float(state["anchor_value"]) * (
            1.0 + factor * age / stability_days
        ) ** (-decay)
        state["value"] = round(_clip(retrievability), 8)
        return float(state["value"])

    def activate(
        self,
        state: dict[str, object],
        at: str | datetime,
        match_score: float,
    ) -> tuple[float, float]:
        before = self.value(state, at)
        match = _clip(match_score)
        growth = 1.0 + 0.55 * match + 1.25 * match * (1.0 - before)
        state["stability_days"] = float(
            state["stability_days"]
        ) * growth
        state["anchor_value"] = _clip(
            0.92 + 0.06 * match
        )
        state["anchor_at"] = _iso(at)
        state["activation_count"] = int(
            state["activation_count"]
        ) + 1
        after = self.value(state, at)
        return before, after

    def reinforce(
        self,
        state: dict[str, object],
        at: str | datetime,
        weight: float,
    ) -> tuple[float, float]:
        before = self.value(state, at)
        strength = _clip(weight)
        state["stability_days"] = float(
            state["stability_days"]
        ) * (1.0 + 0.55 * strength)
        state["anchor_value"] = _clip(
            before + 0.22 * strength * (1.0 - before)
        )
        state["anchor_at"] = _iso(at)
        state["relation_uplift"] = _clip(
            float(state["relation_uplift"]) + 0.22 * strength
        )
        after = self.value(state, at)
        return before, after


class ACTRTraceStability(StabilityStrategy):
    name = "stability.actr_trace.v1"

    def initialize(self, seed: MemoryLifeSeed) -> dict[str, object]:
        initial_weight = 0.70 + 0.30 * seed.base_strength
        state: dict[str, object] = {
            "method": self.name,
            "value": 0.0,
            "scale_days": temporal_retention_days(seed),
            "decay": 1.55,
            "traces": [
                {
                    "at": _iso(seed.created_at),
                    "weight": initial_weight,
                    "kind": "formation",
                }
            ],
            "activation_count": 0,
            "relation_uplift": 0.0,
        }
        self.value(state, seed.created_at)
        return state

    def value(
        self,
        state: dict[str, object],
        at: str | datetime,
    ) -> float:
        scale = max(0.1, float(state["scale_days"]))
        decay = float(state["decay"])
        mass = 0.0
        for trace in list(state["traces"]):
            age = _days_between(str(trace["at"]), at)
            mass += float(trace["weight"]) * (
                1.0 + age / scale
            ) ** (-decay)
        value = 1.0 - math.exp(-1.70 * mass)
        state["value"] = round(_clip(value), 8)
        return float(state["value"])

    def activate(
        self,
        state: dict[str, object],
        at: str | datetime,
        match_score: float,
    ) -> tuple[float, float]:
        before = self.value(state, at)
        match = _clip(match_score)
        traces = state["traces"]
        if not isinstance(traces, list):
            raise TypeError("ACT-R traces must be a list")
        traces.append(
            {
                "at": _iso(at),
                "weight": 0.55 + 0.45 * match,
                "kind": "activation",
            }
        )
        state["activation_count"] = int(
            state["activation_count"]
        ) + 1
        after = self.value(state, at)
        return before, after

    def reinforce(
        self,
        state: dict[str, object],
        at: str | datetime,
        weight: float,
    ) -> tuple[float, float]:
        before = self.value(state, at)
        strength = _clip(weight)
        traces = state["traces"]
        if not isinstance(traces, list):
            raise TypeError("ACT-R traces must be a list")
        traces.append(
            {
                "at": _iso(at),
                "weight": 0.35 * strength,
                "kind": "relation",
            }
        )
        state["relation_uplift"] = _clip(
            float(state["relation_uplift"]) + 0.18 * strength
        )
        after = self.value(state, at)
        return before, after


def _source_prior(source_kind: str) -> tuple[float, float]:
    normalized = source_kind.strip().casefold()
    if normalized in {"text", "dialogue", "query", "observation"}:
        return 4.5, 1.2
    if normalized in {"log", "log_event", "event_log"}:
        return 1.8, 3.2
    return 3.0, 2.0


def _posterior(
    seed: MemoryLifeSeed,
    evidence: Iterable[tuple[bool, float]],
    relation_support: Mapping[str, float],
    relation_conflict: Mapping[str, float],
) -> tuple[float, float]:
    alpha, beta = _source_prior(seed.source_kind)
    for supports, quality in evidence:
        if supports:
            alpha += _clip(quality)
        else:
            beta += _clip(quality)
    alpha += 0.80 * sum(_clip(value) for value in relation_support.values())
    beta += 1.00 * sum(_clip(value) for value in relation_conflict.values())
    beta += 1.20 * seed.conflicting_strength
    return alpha, beta


class ConfidenceStrategy:
    name = "confidence.base"

    def score(
        self,
        state: MemoryLifeState,
        at: str | datetime,
    ) -> dict[str, object]:
        raise NotImplementedError


class SourceBetaMeanConfidence(ConfidenceStrategy):
    name = "confidence.source_beta_mean.v1"

    def score(
        self,
        state: MemoryLifeState,
        at: str | datetime,
    ) -> dict[str, object]:
        values = (
            (item.supports, item.quality)
            for item in state.seed.evidence
        )
        alpha, beta = _posterior(
            state.seed,
            values,
            state.relation_support,
            state.relation_conflict,
        )
        value = alpha / (alpha + beta)
        return {
            "method": self.name,
            "value": round(_clip(value), 8),
            "alpha": round(alpha, 8),
            "beta": round(beta, 8),
            "source_prior": state.seed.source_kind,
            "independent_units": len(
                {
                    item.independent_unit_id or item.evidence_id
                    for item in state.seed.evidence
                }
            ),
        }


class TemporalWindowBetaConfidence(ConfidenceStrategy):
    name = "confidence.temporal_window_beta.v1"

    def score(
        self,
        state: MemoryLifeState,
        at: str | datetime,
    ) -> dict[str, object]:
        origin = min(
            _instant(item.observed_at)
            for item in state.seed.evidence
        )
        windows: dict[tuple[bool, int], float] = {}
        for item in state.seed.evidence:
            window = int(
                (_instant(item.observed_at) - origin).total_seconds()
                // (14.0 * 86400.0)
            )
            key = (item.supports, window)
            windows[key] = max(windows.get(key, 0.0), item.quality)
        values = [
            (supports, quality)
            for (supports, _), quality in windows.items()
        ]
        alpha, beta = _posterior(
            state.seed,
            values,
            state.relation_support,
            state.relation_conflict,
        )
        positive_windows = sum(
            supports for supports, _ in windows
        )
        if positive_windows > 1:
            alpha += 0.25 * math.log1p(positive_windows - 1)
        value = alpha / (alpha + beta)
        return {
            "method": self.name,
            "value": round(_clip(value), 8),
            "alpha": round(alpha, 8),
            "beta": round(beta, 8),
            "source_prior": state.seed.source_kind,
            "independent_windows": len(windows),
        }


class ConservativeBetaBoundConfidence(ConfidenceStrategy):
    name = "confidence.conservative_beta_bound.v1"

    def score(
        self,
        state: MemoryLifeState,
        at: str | datetime,
    ) -> dict[str, object]:
        values = (
            (item.supports, item.quality)
            for item in state.seed.evidence
        )
        alpha, beta = _posterior(
            state.seed,
            values,
            state.relation_support,
            state.relation_conflict,
        )
        total = alpha + beta
        mean = alpha / total
        variance = alpha * beta / (total * total * (total + 1.0))
        lower = mean - 0.85 * math.sqrt(max(0.0, variance))
        independent = len(
            {
                item.independent_unit_id or item.evidence_id
                for item in state.seed.evidence
            }
        )
        value = lower + min(0.04, 0.01 * max(0, independent - 1))
        return {
            "method": self.name,
            "value": round(_clip(value), 8),
            "posterior_mean": round(mean, 8),
            "posterior_sd": round(math.sqrt(variance), 8),
            "alpha": round(alpha, 8),
            "beta": round(beta, 8),
            "source_prior": state.seed.source_kind,
            "independent_units": independent,
        }


class MemoryLifecycleEngine:
    """Evaluate retrieval activation and lazy forgetting for memory states."""

    supporting_relation_types = frozenset({"supports", "confirms"})
    conflicting_relation_types = frozenset(
        {"conflicts", "possible_conflict", "supersedes"}
    )

    def __init__(
        self,
        stability_strategy: StabilityStrategy,
        confidence_strategy: ConfidenceStrategy,
        *,
        forget_threshold: float = 0.15,
        rescue_floor: float = 0.05,
        rescue_match: float = 0.85,
        minimum_match: float = 0.45,
        minimum_selection_score: float = 0.32,
        secondary_selection_ratio: float = 0.78,
        conflict_secondary_gain: float = 0.18,
        conflict_penalty_floor: float = 0.25,
    ):
        if not 0.0 <= rescue_floor <= forget_threshold <= 1.0:
            raise ValueError("forget thresholds are invalid")
        if not 0.0 <= secondary_selection_ratio <= 1.0:
            raise ValueError("secondary selection ratio is invalid")
        if not 0.0 <= conflict_secondary_gain <= 1.0:
            raise ValueError("conflict_secondary_gain is invalid")
        if not 0.0 <= conflict_penalty_floor <= 1.0:
            raise ValueError("conflict_penalty_floor is invalid")
        self.stability_strategy = stability_strategy
        self.confidence_strategy = confidence_strategy
        self.forget_threshold = forget_threshold
        self.rescue_floor = rescue_floor
        self.rescue_match = rescue_match
        self.minimum_match = minimum_match
        self.minimum_selection_score = minimum_selection_score
        self.secondary_selection_ratio = secondary_selection_ratio
        self.conflict_secondary_gain = conflict_secondary_gain
        self.conflict_penalty_floor = conflict_penalty_floor
        self.states: dict[str, MemoryLifeState] = {}
        self.relations: dict[str, MemoryLifeRelation] = {}
        self.transitions: list[dict[str, object]] = []

    def _score_confidence(
        self,
        state: MemoryLifeState,
        at: str | datetime,
    ) -> dict[str, object]:
        scored = self.confidence_strategy.score(state, at)
        evidence_value = float(scored["value"])
        reflection_penalty = _clip(state.reflection_penalty)
        ordered_factors = sorted(
            _clip(value)
            for value in state.conflict_factors.values()
        )
        if ordered_factors:
            aggregate_penalty = 1.0 - ordered_factors[0]
            for factor in ordered_factors[1:]:
                aggregate_penalty += (
                    (1.0 - aggregate_penalty)
                    * self.conflict_secondary_gain
                    * (1.0 - factor)
                )
            conflict_penalty = max(
                self.conflict_penalty_floor,
                1.0 - aggregate_penalty,
            )
        else:
            conflict_penalty = 1.0
        return {
            **scored,
            "evidence_value": round(evidence_value, 8),
            "reflection_penalty": round(reflection_penalty, 8),
            "conflict_penalty": round(conflict_penalty, 8),
            "value": round(
                _clip(
                    evidence_value
                    * reflection_penalty
                    * conflict_penalty
                ),
                8,
            ),
        }

    def add_memory(self, seed: MemoryLifeSeed) -> MemoryLifeState:
        if seed.memory_id in self.states:
            raise ValueError(f"memory_already_exists:{seed.memory_id}")
        state = MemoryLifeState(
            seed=seed,
            status="active",
            stability=self.stability_strategy.initialize(seed),
            confidence={},
        )
        state.confidence = self._score_confidence(
            state,
            seed.created_at,
        )
        state.events.append(
            {
                "type": "formation",
                "at": _iso(seed.created_at),
                "stability": state.stability["value"],
                "confidence": state.confidence["value"],
                "temporal_label": seed.temporal_label,
                "temporal_confidence": seed.temporal_confidence,
                "source_kind": seed.source_kind,
            }
        )
        self.states[seed.memory_id] = state
        return state

    def add_relation(self, relation: MemoryLifeRelation) -> None:
        if relation.relation_id in self.relations:
            return
        if (
            relation.source_memory_id not in self.states
            or relation.target_memory_id not in self.states
        ):
            raise ValueError("relation endpoint memory is missing")
        self.relations[relation.relation_id] = relation
        affected = (
            (relation.target_memory_id,)
            if relation.directed
            else (
                relation.source_memory_id,
                relation.target_memory_id,
            )
        )
        for memory_id in affected:
            state = self.states[memory_id]
            before_confidence = float(state.confidence["value"])
            before_stability = self.stability_strategy.value(
                state.stability,
                relation.observed_at,
            )
            after_stability = before_stability
            if (
                relation.relation_type
                in self.supporting_relation_types
            ):
                state.relation_support[
                    relation.relation_id
                ] = relation.weight
                _, after_stability = self.stability_strategy.reinforce(
                    state.stability,
                    relation.observed_at,
                    relation.weight,
                )
            elif (
                relation.relation_type
                in self.conflicting_relation_types
                and relation.affects_confidence
            ):
                state.relation_conflict[
                    relation.relation_id
                ] = relation.weight
            state.confidence = self._score_confidence(
                state,
                relation.observed_at,
            )
            state.events.append(
                {
                    "type": "relation",
                    "relation_id": relation.relation_id,
                    "relation_type": relation.relation_type,
                    "at": _iso(relation.observed_at),
                    "stability_before": round(before_stability, 8),
                    "stability_after": round(after_stability, 8),
                    "confidence_before": round(before_confidence, 8),
                    "confidence_after": state.confidence["value"],
                }
            )

    def apply_conflict_factor(
        self,
        memory_id: str,
        *,
        factor_id: str,
        factor: float,
        at: str | datetime,
        rationale: str,
    ) -> bool:
        state = self.states.get(memory_id)
        if state is None or state.status != "active":
            return False
        if not factor_id:
            raise ValueError("factor_id is required")
        value = _clip(factor)
        prior = state.conflict_factors.get(factor_id)
        if prior == value:
            return False
        before_confidence = float(state.confidence["value"])
        before_penalty = float(
            state.confidence.get("conflict_penalty", 1.0)
        )
        state.conflict_factors[factor_id] = value
        state.confidence = self._score_confidence(state, at)
        state.events.append(
            {
                "type": "conflict_adjustment",
                "factor_id": factor_id,
                "at": _iso(at),
                "rationale": rationale,
                "factor": round(value, 8),
                "penalty_before": round(before_penalty, 8),
                "penalty_after": state.confidence[
                    "conflict_penalty"
                ],
                "confidence_before": round(before_confidence, 8),
                "confidence_after": state.confidence["value"],
            }
        )
        return True

    def query(
        self,
        observation: LifecycleObservation,
        *,
        top_k: int = 3,
    ) -> LifecycleQueryResult:
        rows = []
        forgotten = []
        for state in self.states.values():
            if state.status != "active":
                continue
            if state.seed.user_id != observation.user_id:
                continue
            match, components = self._match(observation, state.seed)
            if match < self.minimum_match:
                continue
            stability = self.stability_strategy.value(
                state.stability,
                observation.observed_at,
            )
            if stability < self.rescue_floor:
                self._forget(
                    state,
                    observation.observed_at,
                    "lazy_decay_below_rescue_floor",
                )
                forgotten.append(state.seed.memory_id)
                continue
            rescued = (
                stability < self.forget_threshold
                and match >= self.rescue_match
            )
            if (
                stability < self.forget_threshold
                and not rescued
            ):
                self._forget(
                    state,
                    observation.observed_at,
                    "lazy_decay_on_query",
                )
                forgotten.append(state.seed.memory_id)
                continue
            confidence = float(state.confidence["value"])
            retrieval_score = (
                match
                * (0.30 + 0.70 * confidence)
                * (0.55 + 0.45 * stability)
            )
            if retrieval_score < self.minimum_selection_score:
                continue
            rows.append(
                (
                    retrieval_score,
                    match,
                    stability,
                    confidence,
                    rescued,
                    components,
                    state,
                )
            )
        rows.sort(
            key=lambda item: (
                -item[0],
                -item[1],
                -item[3],
                item[6].seed.memory_id,
            )
        )
        selected_rows = rows[: max(1, top_k)]
        if selected_rows and self.secondary_selection_ratio > 0.0:
            best_score = selected_rows[0][0]
            selected_rows = [
                row
                for index, row in enumerate(selected_rows)
                if (
                    index == 0
                    or row[0]
                    >= best_score * self.secondary_selection_ratio
                )
            ]
        selections = []
        for (
            retrieval_score,
            match,
            stability,
            confidence,
            rescued,
            components,
            state,
        ) in selected_rows:
            _, after = self.stability_strategy.activate(
                state.stability,
                observation.observed_at,
                match,
            )
            state.activation_count += 1
            state.last_activated_at = _iso(observation.observed_at)
            state.events.append(
                {
                    "type": "activation",
                    "observation_id": observation.observation_id,
                    "at": _iso(observation.observed_at),
                    "match_score": round(match, 8),
                    "retrieval_score": round(retrieval_score, 8),
                    "stability_before": round(stability, 8),
                    "stability_after": round(after, 8),
                    "rescued": rescued,
                }
            )
            selections.append(
                LifecycleSelection(
                    memory_id=state.seed.memory_id,
                    match_score=round(match, 8),
                    retrieval_score=round(retrieval_score, 8),
                    confidence=round(confidence, 8),
                    stability_before=round(stability, 8),
                    stability_after=round(after, 8),
                    rescued=rescued,
                    match_components=components,
                )
            )
        return LifecycleQueryResult(
            observation_id=observation.observation_id,
            selected=tuple(selections),
            considered_count=len(rows),
            forgotten_during_query=tuple(forgotten),
        )

    def maintain(
        self,
        at: str | datetime,
        memory_ids: Iterable[str] | None = None,
    ) -> tuple[str, ...]:
        selected = (
            tuple(memory_ids)
            if memory_ids is not None
            else tuple(self.states)
        )
        forgotten = []
        for memory_id in selected:
            state = self.states.get(memory_id)
            if state is None or state.status != "active":
                continue
            value = self.stability_strategy.value(
                state.stability,
                at,
            )
            if value < self.forget_threshold:
                self._forget(
                    state,
                    at,
                    "lazy_decay_maintenance",
                )
                forgotten.append(memory_id)
        return tuple(forgotten)

    def apply_reflection_penalty(
        self,
        memory_id: str,
        *,
        penalty_factor: float,
        at: str | datetime,
        review_id: str,
        verdict: str,
        rationale: str,
        source_refs: Iterable[str] = (),
    ) -> bool:
        state = self.states.get(memory_id)
        if state is None or state.status != "active":
            return False
        if not review_id or review_id in state.reflection_review_ids:
            return False
        factor = _clip(penalty_factor)
        before_penalty = state.reflection_penalty
        before_confidence = float(state.confidence["value"])
        state.reflection_review_ids.append(review_id)
        obsolete_context = _reflection_obsolete_context(state, at)
        guarded_obsolete = (
            verdict == "obsolete_task_state"
            and bool(obsolete_context["guarded"])
        )
        if verdict == "supported":
            state.reflection_penalty = 1.0
        elif verdict != "unverifiable" and not guarded_obsolete:
            state.reflection_penalty = factor
        state.confidence = self._score_confidence(state, at)
        state.events.append(
            {
                "type": "reflection_review",
                "review_id": review_id,
                "at": _iso(at),
                "verdict": verdict,
                "rationale": rationale,
                "source_refs": list(_clean(source_refs)),
                "penalty_before": round(before_penalty, 8),
                "penalty_after": round(state.reflection_penalty, 8),
                "latest_activity_at": obsolete_context[
                    "latest_activity_at"
                ],
                "inactivity_days": obsolete_context["inactivity_days"],
                "obsolete_after_days": obsolete_context[
                    "obsolete_after_days"
                ],
                "activation_span_days": obsolete_context[
                    "activation_span_days"
                ],
                "guarded_obsolete": guarded_obsolete,
                "confidence_before": round(before_confidence, 8),
                "confidence_after": state.confidence["value"],
            }
        )
        return state.reflection_penalty != before_penalty

    def merge_memories(
        self,
        canonical_memory_id: str,
        duplicate_memory_ids: Iterable[str],
        *,
        at: str | datetime,
        review_id: str,
        rationale: str,
        source_refs: Iterable[str] = (),
    ) -> tuple[str, ...]:
        duplicate_ids = tuple(
            dict.fromkeys(
                memory_id
                for memory_id in duplicate_memory_ids
                if memory_id != canonical_memory_id
            )
        )
        canonical = self.states.get(canonical_memory_id)
        duplicates = [
            self.states[memory_id]
            for memory_id in duplicate_ids
            if memory_id in self.states
        ]
        if (
            canonical is None
            or canonical.status != "active"
            or len(duplicates) != len(duplicate_ids)
            or any(state.status != "active" for state in duplicates)
        ):
            return ()
        states = [canonical, *duplicates]
        semantic_keys = {
            (
                state.seed.user_id,
                state.seed.condition_tag_ids,
                state.seed.object_tag_ids,
                state.seed.attitude_polarity,
            )
            for state in states
        }
        if len(semantic_keys) != 1:
            return ()

        evidence_by_id = {
            evidence.evidence_id: evidence
            for state in states
            for evidence in state.seed.evidence
        }
        merged_ids = list(
            canonical.seed.metadata.get("merged_memory_ids") or ()
        )
        merged_ids.extend(duplicate_ids)
        pointer_keys = (
            "source_observation_ids",
            "source_event_ids",
            "source_log_ids",
            "raw_source_refs",
        )
        merged_metadata = {
            **dict(canonical.seed.metadata),
            "merged_memory_ids": list(dict.fromkeys(merged_ids)),
            "last_reflection_merge_id": review_id,
        }
        for key in pointer_keys:
            values = []
            for state in states:
                raw = state.seed.metadata.get(key) or ()
                values.extend((raw,) if isinstance(raw, str) else raw)
            if values:
                merged_metadata[key] = tuple(dict.fromkeys(values))
        strongest_stability = max(
            states,
            key=lambda state: self.stability_strategy.value(
                state.stability,
                at,
            ),
        ).stability
        activation_events = {}
        for state in states:
            for event in state.events:
                if event.get("type") != "activation":
                    continue
                key = (
                    str(event.get("observation_id") or ""),
                    str(event.get("at") or ""),
                )
                activation_events.setdefault(
                    key,
                    {
                        **event,
                        "merged_from_memory_id": state.seed.memory_id,
                    },
                )
        canonical.seed = replace(
            canonical.seed,
            created_at=min(
                (state.seed.created_at for state in states),
                key=_instant,
            ),
            explicit_long_term=any(
                state.seed.explicit_long_term for state in states
            ),
            base_strength=max(
                state.seed.base_strength for state in states
            ),
            conflicting_strength=max(
                state.seed.conflicting_strength for state in states
            ),
            evidence=tuple(
                evidence_by_id[evidence_id]
                for evidence_id in sorted(evidence_by_id)
            ),
            metadata=merged_metadata,
        )
        canonical.stability = dict(strongest_stability)
        canonical.reflection_penalty = max(
            state.reflection_penalty for state in states
        )
        canonical.conflict_factors = {
            factor_id: min(
                state.conflict_factors[factor_id]
                for state in states
                if factor_id in state.conflict_factors
            )
            for factor_id in {
                factor_id
                for state in states
                for factor_id in state.conflict_factors
            }
        }
        canonical.reflection_review_ids = list(
            dict.fromkeys(
                review_id
                for state in states
                for review_id in state.reflection_review_ids
            )
        )
        existing_activation_keys = {
            (
                str(event.get("observation_id") or ""),
                str(event.get("at") or ""),
            )
            for event in canonical.events
            if event.get("type") == "activation"
        }
        canonical.events.extend(
            event
            for key, event in sorted(activation_events.items())
            if key not in existing_activation_keys
        )
        canonical.activation_count = len(activation_events)
        if activation_events:
            canonical.last_activated_at = max(
                str(event["at"]) for event in activation_events.values()
            )
        canonical.confidence = self._score_confidence(canonical, at)
        canonical.events.append(
            {
                "type": "reflection_merge",
                "review_id": review_id,
                "at": _iso(at),
                "merged_memory_ids": list(duplicate_ids),
                "rationale": rationale,
                "source_refs": list(_clean(source_refs)),
            }
        )

        merged = []
        for state in duplicates:
            state.status = "merged"
            state.merged_into = canonical_memory_id
            state.events.append(
                {
                    "type": "reflection_merged_into",
                    "review_id": review_id,
                    "at": _iso(at),
                    "canonical_memory_id": canonical_memory_id,
                    "rationale": rationale,
                }
            )
            transition = {
                "type": "merge",
                "memory_id": state.seed.memory_id,
                "at": _iso(at),
                "from_status": "active",
                "to_status": "merged",
                "reason": "reflection_duplicate_merge",
                "canonical_memory_id": canonical_memory_id,
            }
            self.transitions.append(transition)
            merged.append(state.seed.memory_id)
        self._rewire_relations_after_merge(
            canonical_memory_id,
            set(merged),
            at,
        )
        return tuple(merged)

    def _rewire_relations_after_merge(
        self,
        canonical_memory_id: str,
        duplicate_memory_ids: set[str],
        at: str | datetime,
    ) -> None:
        selected: dict[
            tuple[str, str, str, bool],
            MemoryLifeRelation,
        ] = {}
        for relation in self.relations.values():
            source = (
                canonical_memory_id
                if relation.source_memory_id in duplicate_memory_ids
                else relation.source_memory_id
            )
            target = (
                canonical_memory_id
                if relation.target_memory_id in duplicate_memory_ids
                else relation.target_memory_id
            )
            if source == target:
                continue
            if not relation.directed and source > target:
                source, target = target, source
            key = (
                source,
                target,
                relation.relation_type,
                relation.directed,
            )
            candidate = replace(
                relation,
                relation_id=(
                    "reflection:"
                    f"{relation.relation_type}:{source}:{target}:"
                    f"{int(relation.directed)}"
                ),
                source_memory_id=source,
                target_memory_id=target,
            )
            previous = selected.get(key)
            if previous is None or candidate.weight > previous.weight:
                selected[key] = candidate
        self.relations = {
            relation.relation_id: relation
            for relation in selected.values()
        }
        for state in self.states.values():
            state.relation_support.clear()
            state.relation_conflict.clear()
        for relation in self.relations.values():
            affected = (
                (relation.target_memory_id,)
                if relation.directed
                else (
                    relation.source_memory_id,
                    relation.target_memory_id,
                )
            )
            for memory_id in affected:
                state = self.states[memory_id]
                if (
                    relation.relation_type
                    in self.supporting_relation_types
                ):
                    state.relation_support[
                        relation.relation_id
                    ] = relation.weight
                elif (
                    relation.relation_type
                    in self.conflicting_relation_types
                    and relation.affects_confidence
                ):
                    state.relation_conflict[
                        relation.relation_id
                    ] = relation.weight
        for state in self.states.values():
            if state.status == "active":
                state.confidence = self._score_confidence(state, at)

    def snapshot(
        self,
        at: str | datetime,
    ) -> tuple[dict[str, object], ...]:
        values = []
        for state in self.states.values():
            if state.status == "active":
                self.stability_strategy.value(state.stability, at)
            values.append(state.to_dict())
        return tuple(
            sorted(values, key=lambda item: str(item["memory_id"]))
        )

    def _forget(
        self,
        state: MemoryLifeState,
        at: str | datetime,
        reason: str,
    ) -> None:
        if state.status == "forgotten":
            return
        from_status = state.status
        state.status = "forgotten"
        state.forgotten_at = _iso(at)
        event = {
            "type": "forget",
            "memory_id": state.seed.memory_id,
            "at": state.forgotten_at,
            "from_status": from_status,
            "to_status": "forgotten",
            "reason": reason,
            "stability": state.stability["value"],
        }
        state.events.append(event)
        self.transitions.append(event)

    @staticmethod
    def _match(
        observation: LifecycleObservation,
        seed: MemoryLifeSeed,
    ) -> tuple[float, dict[str, float]]:
        observation_conditions = set(observation.condition_tag_ids)
        memory_conditions = set(seed.condition_tag_ids)
        observation_objects = set(observation.object_tag_ids)
        memory_objects = set(seed.object_tag_ids)
        condition = (
            1.0
            if observation_conditions & memory_conditions
            else 0.0
        )
        object_score = (
            1.0 if observation_objects & memory_objects else 0.0
        )
        attitude = (
            1.0
            if observation.attitude_polarity
            and observation.attitude_polarity
            == seed.attitude_polarity
            else 0.0
        )
        if (
            observation.attitude_polarity
            and seed.attitude_polarity
            and attitude == 0.0
        ):
            return (
                0.0,
                {
                    "condition": condition,
                    "object": object_score,
                    "attitude": attitude,
                },
            )
        score = 0.40 * condition + 0.50 * object_score
        if observation.attitude_polarity and seed.attitude_polarity:
            score += 0.10 * attitude
        if (
            observation_conditions
            and memory_conditions
            and condition == 0.0
        ):
            score *= 0.60
        if (
            observation_objects
            and memory_objects
            and object_score == 0.0
        ):
            score *= 0.35
        return (
            _clip(score),
            {
                "condition": condition,
                "object": object_score,
                "attitude": attitude,
            },
        )


STABILITY_STRATEGIES = {
    "weibull": WeibullSurvivalStability,
    "fsrs": FSRSPowerStability,
    "actr": ACTRTraceStability,
}

CONFIDENCE_STRATEGIES = {
    "beta_mean": SourceBetaMeanConfidence,
    "beta_temporal": TemporalWindowBetaConfidence,
    "beta_bound": ConservativeBetaBoundConfidence,
}


__all__ = [
    "ACTRTraceStability",
    "CONFIDENCE_STRATEGIES",
    "ConfidenceEvidence",
    "ConfidenceStrategy",
    "ConservativeBetaBoundConfidence",
    "FSRSPowerStability",
    "LifecycleObservation",
    "LifecycleQueryResult",
    "LifecycleSelection",
    "MemoryLifeRelation",
    "MemoryLifeSeed",
    "MemoryLifeState",
    "MemoryLifecycleEngine",
    "STABILITY_STRATEGIES",
    "SourceBetaMeanConfidence",
    "StabilityStrategy",
    "TemporalWindowBetaConfidence",
    "WeibullSurvivalStability",
    "temporal_retention_days",
]
