from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Iterable, Mapping, Sequence

from .memory_graph import ObservationRelationSignal
from .memory_lifecycle import (
    LifecycleObservation,
    LifecycleQueryResult,
    MemoryLifeRelation,
    MemoryLifecycleEngine,
)


def _clip(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _stable_id(prefix: str, value: str) -> str:
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:24]
    return f"{prefix}_{digest}"


def _instant(value: str) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _normalized_text(value: object) -> str:
    if isinstance(value, str):
        normalized = unicodedata.normalize("NFKC", value).casefold().strip()
        normalized = re.sub(
            r"(?<=\w)[\s_-]+(?=\w)",
            " ",
            normalized,
            flags=re.UNICODE,
        )
        return re.sub(r"\s+", " ", normalized)
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _source_reliability(source_kind: str) -> float:
    normalized = source_kind.strip().casefold()
    if normalized in {"text", "dialogue", "query", "manual_config"}:
        return 1.0
    if normalized in {"observation", "structured_event"}:
        return 0.88
    if normalized in {"log", "log_event", "event_log"}:
        return 0.68
    return 0.80


@dataclass(frozen=True)
class ConflictMemory:
    memory_id: str
    user_id: str
    slot_key: str
    value: object
    confidence: float
    source_kind: str
    observed_at: str
    cardinality: str = "single"
    conditions: Mapping[str, str] = field(default_factory=dict)
    condition_tag_ids: tuple[str, ...] = ()
    valid_from: str = ""
    valid_to: str = ""
    supersedes_memory_ids: tuple[str, ...] = ()
    evidence_strength: float = 1.0
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.memory_id or not self.user_id or not self.slot_key:
            raise ValueError("memory_id, user_id and slot_key are required")
        if self.cardinality not in {"single", "set", "ranked"}:
            raise ValueError("cardinality must be single, set or ranked")
        if not 0.0 <= float(self.confidence) <= 1.0:
            raise ValueError("confidence must be in [0, 1]")
        if not 0.0 <= float(self.evidence_strength) <= 1.0:
            raise ValueError("evidence_strength must be in [0, 1]")
        _instant(self.observed_at)
        valid_from = _instant(self.valid_from)
        valid_to = _instant(self.valid_to)
        if (
            valid_from is not None
            and valid_to is not None
            and valid_from >= valid_to
        ):
            raise ValueError("valid_from must be earlier than valid_to")
        if self.memory_id in self.supersedes_memory_ids:
            raise ValueError("memory cannot supersede itself")
        object.__setattr__(
            self,
            "condition_tag_ids",
            tuple(dict.fromkeys(self.condition_tag_ids)),
        )
        object.__setattr__(
            self,
            "supersedes_memory_ids",
            tuple(dict.fromkeys(self.supersedes_memory_ids)),
        )

    @property
    def reliability(self) -> float:
        return _clip(
            self.confidence
            * self.evidence_strength
            * _source_reliability(self.source_kind)
        )

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    @classmethod
    def from_dict(
        cls,
        value: Mapping[str, object],
    ) -> ConflictMemory:
        payload = dict(value)
        payload["condition_tag_ids"] = tuple(
            payload.get("condition_tag_ids") or ()
        )
        payload["supersedes_memory_ids"] = tuple(
            payload.get("supersedes_memory_ids") or ()
        )
        return cls(**payload)


@dataclass(frozen=True)
class ConflictReason:
    code: str
    summary: str
    strength: float
    evidence: Mapping[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class ConflictLink:
    source_memory_id: str
    target_memory_id: str
    relation_type: str
    weight: float
    directed: bool

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class ConflictAssessment:
    detector: str
    conflict_type: str
    memory_ids: tuple[str, str]
    probability: float
    condition_relation: str
    time_relation: str
    explanation: str
    reasons: tuple[ConflictReason, ...]
    confidence_factors: Mapping[str, float]
    links: tuple[ConflictLink, ...]
    conflict_scope: Mapping[str, object] = field(default_factory=dict)
    predecessor_memory_id: str = ""
    successor_memory_id: str = ""
    schema_version: str = "memory_conflict.assessment.v1"

    @property
    def detected(self) -> bool:
        return self.conflict_type != "none"

    def to_dict(self) -> dict[str, object]:
        value = asdict(self)
        value["detected"] = self.detected
        value["reasons"] = [item.to_dict() for item in self.reasons]
        value["links"] = [item.to_dict() for item in self.links]
        return value

    def graph_signals(self) -> tuple[ObservationRelationSignal, ...]:
        return tuple(
            ObservationRelationSignal(
                source_ref=link.source_memory_id,
                target_ref=link.target_memory_id,
                association=link.weight,
                relation_type=link.relation_type,
                directed=link.directed,
                confidence=self.probability,
                independent_unit_id=_stable_id(
                    "conflict_unit",
                    (
                        f"{self.detector}|{self.conflict_type}|"
                        f"{link.source_memory_id}|{link.target_memory_id}"
                    ),
                ),
                source_memory_hint=link.source_memory_id,
                target_memory_hint=link.target_memory_id,
                metadata={
                    "conflict_type": self.conflict_type,
                    "explanation": self.explanation,
                    "conflict_scope": dict(self.conflict_scope),
                },
            )
            for link in self.links
        )

    def lifecycle_relations(
        self,
        observed_at: str,
    ) -> tuple[MemoryLifeRelation, ...]:
        if not self.detected:
            return ()
        relations = []
        for link in self.links:
            relation_type = link.relation_type
            weight = link.weight
            if self.conflict_type == "unresolved":
                weight *= 0.35
            relations.append(
                MemoryLifeRelation(
                    relation_id=_stable_id(
                        "conflict_relation",
                        (
                            f"{self.detector}|{self.conflict_type}|"
                            f"{link.source_memory_id}|"
                            f"{link.target_memory_id}"
                        ),
                    ),
                    source_memory_id=link.source_memory_id,
                    target_memory_id=link.target_memory_id,
                    relation_type=relation_type,
                    weight=round(_clip(weight), 8),
                    observed_at=observed_at,
                    directed=link.directed,
                    affects_confidence=False,
                )
            )
        return tuple(relations)


@dataclass(frozen=True)
class ConflictDetectorConfig:
    slot_aliases: Mapping[str, str] = field(default_factory=dict)
    weighted_static_threshold: float = 0.73
    weighted_unresolved_threshold: float = 0.55
    hybrid_minimum_probability: float = 0.52

    def __post_init__(self) -> None:
        for name in (
            "weighted_static_threshold",
            "weighted_unresolved_threshold",
            "hybrid_minimum_probability",
        ):
            if not 0.0 <= float(getattr(self, name)) <= 1.0:
                raise ValueError(f"{name} must be in [0, 1]")


def _slot_key(memory: ConflictMemory, config: ConflictDetectorConfig) -> str:
    normalized = memory.slot_key.strip().casefold().replace("-", "_")
    aliases = {
        key.strip().casefold().replace("-", "_"): (
            value.strip().casefold().replace("-", "_")
        )
        for key, value in config.slot_aliases.items()
    }
    return aliases.get(normalized, normalized)


def _values_conflict(left: ConflictMemory, right: ConflictMemory) -> bool:
    if left.cardinality != right.cardinality:
        return False
    if left.cardinality == "set":
        semantics = {
            str(left.metadata.get("set_semantics") or "additive"),
            str(right.metadata.get("set_semantics") or "additive"),
        }
        if semantics == {"snapshot"}:
            left_values = (
                left.value
                if isinstance(left.value, (list, tuple, set))
                else (left.value,)
            )
            right_values = (
                right.value
                if isinstance(right.value, (list, tuple, set))
                else (right.value,)
            )
            return {
                _normalized_text(item) for item in left_values
            } != {
                _normalized_text(item) for item in right_values
            }
        return False
    if left.cardinality == "ranked":
        left_values = (
            tuple(left.value)
            if isinstance(left.value, (list, tuple))
            else (left.value,)
        )
        right_values = (
            tuple(right.value)
            if isinstance(right.value, (list, tuple))
            else (right.value,)
        )
        if not left_values or not right_values:
            return False
        full_ranking = (
            left.metadata.get("ranking_semantics") == "full"
            or right.metadata.get("ranking_semantics") == "full"
        )
        if not full_ranking:
            return _normalized_text(left_values[0]) != _normalized_text(
                right_values[0]
            )
        return tuple(map(_normalized_text, left_values)) != tuple(
            map(_normalized_text, right_values)
        )
    return _normalized_text(left.value) != _normalized_text(right.value)


def _tag_axis_value(value: str) -> tuple[str, str] | None:
    parts = tuple(
        item.strip().casefold()
        for item in value.split(":")
        if item.strip()
    )
    if len(parts) < 3:
        return None
    return ":".join(parts[:-1]), parts[-1]


def condition_relation(
    left: ConflictMemory,
    right: ConflictMemory,
) -> str:
    left_values = dict(left.conditions)
    right_values = dict(right.conditions)
    if left_values or right_values:
        if not left_values or not right_values:
            return "unknown"
        shared = set(left_values) & set(right_values)
        if any(left_values[key] != right_values[key] for key in shared):
            return "disjoint"
        if left_values == right_values:
            return "equal"
        return "overlap"

    left_tags = set(left.condition_tag_ids)
    right_tags = set(right.condition_tag_ids)
    if not left_tags and not right_tags:
        return "equal"
    if not left_tags or not right_tags:
        return "unknown"
    if left_tags == right_tags:
        return "equal"
    if left_tags & right_tags:
        return "overlap"
    left_axes: dict[str, set[str]] = {}
    right_axes: dict[str, set[str]] = {}
    for tag in left_tags:
        parsed = _tag_axis_value(tag)
        if parsed is None:
            return "unknown"
        left_axes.setdefault(parsed[0], set()).add(parsed[1])
    for tag in right_tags:
        parsed = _tag_axis_value(tag)
        if parsed is None:
            return "unknown"
        right_axes.setdefault(parsed[0], set()).add(parsed[1])
    shared_axes = set(left_axes) & set(right_axes)
    if any(
        left_axes[axis].isdisjoint(right_axes[axis])
        for axis in shared_axes
    ):
        return "disjoint"
    return "overlap"


def _memory_condition_scope(
    memory: ConflictMemory,
) -> dict[str, object]:
    return {
        "conditions": dict(memory.conditions),
        "condition_tag_ids": list(memory.condition_tag_ids),
    }


def _conflict_scope(
    left: ConflictMemory,
    right: ConflictMemory,
    relation: str,
) -> dict[str, object]:
    left_scope = _memory_condition_scope(left)
    right_scope = _memory_condition_scope(right)
    if relation == "disjoint":
        return {
            "kind": "partition",
            "alternatives": {
                left.memory_id: left_scope,
                right.memory_id: right_scope,
            },
        }
    if relation == "unknown":
        return {
            "kind": "unknown",
            "memory_scopes": {
                left.memory_id: left_scope,
                right.memory_id: right_scope,
            },
        }
    conditions = dict(left.conditions)
    conditions.update(right.conditions)
    condition_tag_ids = sorted(
        {
            *left.condition_tag_ids,
            *right.condition_tag_ids,
        }
    )
    if not conditions and not condition_tag_ids:
        return {"kind": "global"}
    return {
        "kind": "intersection",
        "conditions": conditions,
        "condition_tag_ids": condition_tag_ids,
    }


def time_relation(left: ConflictMemory, right: ConflictMemory) -> str:
    left_has_validity = bool(left.valid_from or left.valid_to)
    right_has_validity = bool(right.valid_from or right.valid_to)
    if not left_has_validity and not right_has_validity:
        return "unbounded"
    if not left_has_validity or not right_has_validity:
        return "unknown"
    minimum = datetime.min.replace(tzinfo=timezone.utc)
    maximum = datetime.max.replace(tzinfo=timezone.utc)
    left_start = _instant(left.valid_from) or minimum
    right_start = _instant(right.valid_from) or minimum
    left_end = _instant(left.valid_to)
    right_end = _instant(right.valid_to)
    left_end = left_end or maximum
    right_end = right_end or maximum
    overlap = (
        right_start < left_end
        and left_start < right_end
    )
    return "overlap" if overlap else "disjoint"


def _supersession(
    left: ConflictMemory,
    right: ConflictMemory,
) -> tuple[ConflictMemory, ConflictMemory] | None:
    if left.memory_id in right.supersedes_memory_ids:
        return left, right
    if right.memory_id in left.supersedes_memory_ids:
        return right, left
    return None


def _mutual_supersession(
    left: ConflictMemory,
    right: ConflictMemory,
) -> bool:
    return (
        left.memory_id in right.supersedes_memory_ids
        and right.memory_id in left.supersedes_memory_ids
    )


def _ordered(
    left: ConflictMemory,
    right: ConflictMemory,
) -> tuple[ConflictMemory, ConflictMemory]:
    left_start = _instant(left.valid_from)
    right_start = _instant(right.valid_from)
    left_end = _instant(left.valid_to)
    right_end = _instant(right.valid_to)
    if left_end is not None and right_start is not None:
        if left_end <= right_start:
            return left, right
    if right_end is not None and left_start is not None:
        if right_end <= left_start:
            return right, left
    if left_start is not None and right_start is not None:
        return (left, right) if left_start <= right_start else (right, left)
    left_time = _instant(left.observed_at)
    right_time = _instant(right.observed_at)
    if left_time is None or right_time is None:
        return (left, right)
    return (left, right) if left_time <= right_time else (right, left)


def _confidence_factors(
    conflict_type: str,
    probability: float,
    left: ConflictMemory,
    right: ConflictMemory,
    condition: str,
    predecessor: ConflictMemory | None = None,
) -> dict[str, float]:
    if conflict_type in {"none", "conditional"}:
        return {left.memory_id: 1.0, right.memory_id: 1.0}
    if conflict_type == "static" and condition == "overlap":
        return {left.memory_id: 1.0, right.memory_id: 1.0}
    if conflict_type == "dynamic" and predecessor is not None:
        successor = right if predecessor is left else left
        return {
            predecessor.memory_id: round(1.0 - 0.58 * probability, 8),
            successor.memory_id: 1.0,
        }
    if conflict_type == "unresolved":
        factor = round(1.0 - 0.12 * probability, 8)
        return {left.memory_id: factor, right.memory_id: factor}

    left_reliability = left.reliability
    right_reliability = right.reliability
    gap = abs(left_reliability - right_reliability)
    if gap < 0.08:
        factor = round(1.0 - 0.30 * probability, 8)
        return {left.memory_id: factor, right.memory_id: factor}
    weaker, stronger = (
        (left, right)
        if left_reliability < right_reliability
        else (right, left)
    )
    return {
        weaker.memory_id: round(1.0 - 0.50 * probability, 8),
        stronger.memory_id: round(1.0 - 0.12 * probability, 8),
    }


def _links(
    conflict_type: str,
    probability: float,
    left: ConflictMemory,
    right: ConflictMemory,
    predecessor: ConflictMemory | None = None,
) -> tuple[ConflictLink, ...]:
    if conflict_type == "none":
        return ()
    if conflict_type == "dynamic" and predecessor is not None:
        successor = right if predecessor is left else left
        return (
            ConflictLink(
                source_memory_id=successor.memory_id,
                target_memory_id=predecessor.memory_id,
                relation_type="supersedes",
                weight=round(probability, 8),
                directed=True,
            ),
        )
    relation = {
        "conditional": "conditional_alternative",
        "static": "conflicts",
        "unresolved": "possible_conflict",
    }[conflict_type]
    source, target = sorted((left.memory_id, right.memory_id))
    return (
        ConflictLink(
            source_memory_id=source,
            target_memory_id=target,
            relation_type=relation,
            weight=round(probability, 8),
            directed=False,
        ),
    )


def _explanation(
    conflict_type: str,
    left: ConflictMemory,
    right: ConflictMemory,
    condition: str,
    time: str,
    predecessor: ConflictMemory | None,
) -> str:
    values = f"{left.value!r} versus {right.value!r}"
    if conflict_type == "none":
        return "The memories do not make mutually exclusive claims."
    if conflict_type == "conditional":
        return (
            f"The same slot has {values}, but the conditions are disjoint; "
            "keep both as scoped alternatives."
        )
    if conflict_type == "dynamic" and predecessor is not None:
        successor = right if predecessor is left else left
        return (
            f"{successor.memory_id} supersedes {predecessor.memory_id} for "
            f"the same slot; retain both for history and prefer the successor."
        )
    if conflict_type == "static":
        return (
            f"The same slot has incompatible values ({values}) under "
            f"{condition} conditions and {time} validity."
        )
    return (
        f"The same slot has incompatible values ({values}), but condition "
        "or time evidence is incomplete; retrieve both for disambiguation."
    )


def _base_reasons(
    left: ConflictMemory,
    right: ConflictMemory,
    condition: str,
    time: str,
) -> tuple[ConflictReason, ...]:
    return (
        ConflictReason(
            "same_slot",
            "Both memories describe the same normalized slot.",
            1.0,
            {"slot_key": left.slot_key},
        ),
        ConflictReason(
            "incompatible_values",
            "The slot values cannot both be selected as the active value.",
            1.0,
            {"left": left.value, "right": right.value},
        ),
        ConflictReason(
            "condition_relation",
            f"Condition relation is {condition}.",
            {
                "equal": 1.0,
                "overlap": 0.82,
                "unknown": 0.48,
                "disjoint": 0.20,
            }[condition],
        ),
        ConflictReason(
            "time_relation",
            f"Validity relation is {time}.",
            {
                "overlap": 1.0,
                "unbounded": 0.82,
                "unknown": 0.45,
                "disjoint": 0.10,
            }[time],
        ),
    )


class ConflictDetector:
    name = "conflict.base"

    def __init__(
        self,
        config: ConflictDetectorConfig | None = None,
    ):
        self.config = config or ConflictDetectorConfig()

    def assess(
        self,
        left: ConflictMemory,
        right: ConflictMemory,
    ) -> ConflictAssessment:
        raise NotImplementedError

    def _early_exit(
        self,
        left: ConflictMemory,
        right: ConflictMemory,
    ) -> ConflictAssessment | None:
        if left.memory_id == right.memory_id:
            raise ValueError("conflict comparison requires distinct memories")
        reason = ""
        explicit_reference = (
            left.memory_id in right.supersedes_memory_ids
            or right.memory_id in left.supersedes_memory_ids
        )
        if left.user_id != right.user_id:
            reason = "different users"
        elif (
            _slot_key(left, self.config)
            != _slot_key(right, self.config)
            and not explicit_reference
        ):
            reason = "different normalized slots"
        elif left.cardinality != right.cardinality:
            return self._assessment(
                left,
                right,
                conflict_type="unresolved",
                probability=0.56,
                condition=condition_relation(left, right),
                time=time_relation(left, right),
                extra_reasons=(
                    ConflictReason(
                        "cardinality_mismatch",
                        "The slot cardinality schemas do not agree.",
                        0.85,
                    ),
                ),
            )
        elif left.cardinality == "set":
            set_semantics = {
                str(
                    left.metadata.get("set_semantics")
                    or "additive"
                ),
                str(
                    right.metadata.get("set_semantics")
                    or "additive"
                ),
            }
            if len(set_semantics) > 1:
                return self._assessment(
                    left,
                    right,
                    conflict_type="unresolved",
                    probability=0.56,
                    condition=condition_relation(left, right),
                    time=time_relation(left, right),
                    extra_reasons=(
                        ConflictReason(
                            "set_semantics_mismatch",
                            "Set merge semantics do not agree.",
                            0.85,
                        ),
                    ),
                )
            if not _values_conflict(left, right):
                reason = "compatible values or multi-value cardinality"
        elif not _values_conflict(left, right):
            reason = "compatible values or multi-value cardinality"
        if not reason:
            return None
        return ConflictAssessment(
            detector=self.name,
            conflict_type="none",
            memory_ids=(left.memory_id, right.memory_id),
            probability=0.0,
            condition_relation=condition_relation(left, right),
            time_relation=time_relation(left, right),
            explanation=f"No conflict: {reason}.",
            reasons=(
                ConflictReason("hard_gate", reason, 1.0),
            ),
            confidence_factors={
                left.memory_id: 1.0,
                right.memory_id: 1.0,
            },
            links=(),
            conflict_scope=_conflict_scope(
                left,
                right,
                condition_relation(left, right),
            ),
        )

    def _assessment(
        self,
        left: ConflictMemory,
        right: ConflictMemory,
        *,
        conflict_type: str,
        probability: float,
        condition: str,
        time: str,
        predecessor: ConflictMemory | None = None,
        extra_reasons: Sequence[ConflictReason] = (),
    ) -> ConflictAssessment:
        probability = _clip(probability)
        successor = (
            right if predecessor is left else left
        ) if predecessor is not None else None
        return ConflictAssessment(
            detector=self.name,
            conflict_type=conflict_type,
            memory_ids=(left.memory_id, right.memory_id),
            probability=round(probability, 8),
            condition_relation=condition,
            time_relation=time,
            explanation=_explanation(
                conflict_type,
                left,
                right,
                condition,
                time,
                predecessor,
            ),
            reasons=(
                *_base_reasons(left, right, condition, time),
                *extra_reasons,
            ),
            confidence_factors=_confidence_factors(
                conflict_type,
                probability,
                left,
                right,
                condition,
                predecessor,
            ),
            links=_links(
                conflict_type,
                probability,
                left,
                right,
                predecessor,
            ),
            conflict_scope=_conflict_scope(left, right, condition),
            predecessor_memory_id=(
                predecessor.memory_id if predecessor is not None else ""
            ),
            successor_memory_id=(
                successor.memory_id if successor is not None else ""
            ),
        )


class HierarchicalRuleConflictDetector(ConflictDetector):
    name = "conflict.hierarchical_rules.v1"

    def assess(
        self,
        left: ConflictMemory,
        right: ConflictMemory,
    ) -> ConflictAssessment:
        early = self._early_exit(left, right)
        if early is not None:
            return early
        condition = condition_relation(left, right)
        time = time_relation(left, right)
        if _mutual_supersession(left, right):
            return self._assessment(
                left,
                right,
                conflict_type="unresolved",
                probability=0.72,
                condition=condition,
                time=time,
                extra_reasons=(
                    ConflictReason(
                        "mutual_supersession",
                        "Both memories claim to supersede each other.",
                        1.0,
                    ),
                ),
            )
        explicit = _supersession(left, right)
        if explicit is not None:
            predecessor, _ = explicit
            return self._assessment(
                left,
                right,
                conflict_type="dynamic",
                probability=0.96,
                condition=condition,
                time=time,
                predecessor=predecessor,
                extra_reasons=(
                    ConflictReason(
                        "explicit_supersession",
                        "One memory explicitly supersedes the other.",
                        1.0,
                    ),
                ),
            )
        if condition == "disjoint":
            return self._assessment(
                left,
                right,
                conflict_type="conditional",
                probability=0.82,
                condition=condition,
                time=time,
                extra_reasons=(
                    ConflictReason(
                        "supported_partition",
                        "Disjoint conditions provide a usable partition.",
                        0.90,
                    ),
                ),
            )
        if time == "disjoint" and condition in {"equal", "overlap"}:
            predecessor, _ = _ordered(left, right)
            return self._assessment(
                left,
                right,
                conflict_type="dynamic",
                probability=0.78,
                condition=condition,
                time=time,
                predecessor=predecessor,
            )
        if (
            condition in {"equal", "overlap"}
            and time in {"overlap", "unbounded"}
        ):
            probability = 0.91 if time == "overlap" else 0.80
            return self._assessment(
                left,
                right,
                conflict_type="static",
                probability=probability,
                condition=condition,
                time=time,
            )
        return self._assessment(
            left,
            right,
            conflict_type="unresolved",
            probability=0.58,
            condition=condition,
            time=time,
        )


class WeightedEvidenceConflictDetector(ConflictDetector):
    name = "conflict.weighted_evidence.v1"

    def assess(
        self,
        left: ConflictMemory,
        right: ConflictMemory,
    ) -> ConflictAssessment:
        early = self._early_exit(left, right)
        if early is not None:
            return early
        condition = condition_relation(left, right)
        time = time_relation(left, right)
        if _mutual_supersession(left, right):
            return self._assessment(
                left,
                right,
                conflict_type="unresolved",
                probability=0.72,
                condition=condition,
                time=time,
                extra_reasons=(
                    ConflictReason(
                        "mutual_supersession",
                        "Both memories claim to supersede each other.",
                        1.0,
                    ),
                ),
            )
        explicit = _supersession(left, right)
        reliability = math.sqrt(left.reliability * right.reliability)
        condition_score = {
            "equal": 1.0,
            "overlap": 0.82,
            "unknown": 0.48,
            "disjoint": 0.15,
        }[condition]
        time_score = {
            "overlap": 1.0,
            "unbounded": 0.82,
            "unknown": 0.35,
            "disjoint": 0.05,
        }[time]
        static_score = _clip(
            0.42
            + 0.25 * condition_score
            + 0.18 * time_score
            + 0.15 * reliability
        )
        if explicit is not None:
            predecessor, _ = explicit
            return self._assessment(
                left,
                right,
                conflict_type="dynamic",
                probability=0.90 + 0.08 * reliability,
                condition=condition,
                time=time,
                predecessor=predecessor,
            )
        if condition == "disjoint":
            return self._assessment(
                left,
                right,
                conflict_type="conditional",
                probability=0.72 + 0.18 * reliability,
                condition=condition,
                time=time,
            )
        if time == "disjoint" and condition != "unknown":
            predecessor, _ = _ordered(left, right)
            return self._assessment(
                left,
                right,
                conflict_type="dynamic",
                probability=0.68 + 0.20 * reliability,
                condition=condition,
                time=time,
                predecessor=predecessor,
            )
        if condition == "unknown" or time == "unknown":
            return self._assessment(
                left,
                right,
                conflict_type="unresolved",
                probability=min(static_score, 0.69),
                condition=condition,
                time=time,
            )
        if static_score >= self.config.weighted_static_threshold:
            return self._assessment(
                left,
                right,
                conflict_type="static",
                probability=static_score,
                condition=condition,
                time=time,
            )
        if static_score >= self.config.weighted_unresolved_threshold:
            return self._assessment(
                left,
                right,
                conflict_type="unresolved",
                probability=static_score,
                condition=condition,
                time=time,
            )
        return self._assessment(
            left,
            right,
            conflict_type="none",
            probability=0.0,
            condition=condition,
            time=time,
        )


class HybridConflictDetector(ConflictDetector):
    name = "conflict.hybrid_conservative.v1"

    def __init__(
        self,
        config: ConflictDetectorConfig | None = None,
    ):
        super().__init__(config)
        self.rules = HierarchicalRuleConflictDetector(self.config)
        self.weighted = WeightedEvidenceConflictDetector(self.config)

    def assess(
        self,
        left: ConflictMemory,
        right: ConflictMemory,
    ) -> ConflictAssessment:
        early = self._early_exit(left, right)
        if early is not None:
            return early
        if _mutual_supersession(left, right):
            condition = condition_relation(left, right)
            time = time_relation(left, right)
            return self._assessment(
                left,
                right,
                conflict_type="unresolved",
                probability=0.72,
                condition=condition,
                time=time,
                extra_reasons=(
                    ConflictReason(
                        "mutual_supersession",
                        "Both memories claim to supersede each other.",
                        1.0,
                    ),
                ),
            )
        rule = self.rules.assess(left, right)
        weighted = self.weighted.assess(left, right)
        explicit_type = rule.conflict_type in {"conditional", "dynamic"}
        if explicit_type or rule.conflict_type == weighted.conflict_type:
            conflict_type = rule.conflict_type
        elif "unresolved" in {
            rule.conflict_type,
            weighted.conflict_type,
        }:
            conflict_type = "unresolved"
        else:
            conflict_type = "unresolved"
        probability = (
            0.62 * rule.probability + 0.38 * weighted.probability
        )
        if (
            conflict_type == "unresolved"
            and probability < self.config.hybrid_minimum_probability
        ):
            conflict_type = "none"
            probability = 0.0
        predecessor = None
        if conflict_type == "dynamic":
            predecessor_id = (
                rule.predecessor_memory_id
                or weighted.predecessor_memory_id
            )
            predecessor = (
                left if left.memory_id == predecessor_id else right
            )
        return self._assessment(
            left,
            right,
            conflict_type=conflict_type,
            probability=probability,
            condition=rule.condition_relation,
            time=rule.time_relation,
            predecessor=predecessor,
            extra_reasons=(
                ConflictReason(
                    "method_agreement",
                    (
                        "Rule and weighted methods agree."
                        if rule.conflict_type == weighted.conflict_type
                        else (
                            "Methods disagree; the hybrid keeps the "
                            "result unresolved."
                        )
                    ),
                    1.0 if rule.conflict_type == weighted.conflict_type else 0.5,
                    {
                        "rule": rule.conflict_type,
                        "weighted": weighted.conflict_type,
                    },
                ),
            ),
        )


@dataclass(frozen=True)
class ConflictRetrievalCandidate:
    memory_id: str
    conflict_type: str
    probability: float
    confidence_factor: float
    explanation: str
    relation_type: str
    directed_from_root: bool
    conflict_scope: Mapping[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class ConflictRetrievalGroup:
    root_memory_id: str
    companions: tuple[ConflictRetrievalCandidate, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "root_memory_id": self.root_memory_id,
            "companions": [item.to_dict() for item in self.companions],
        }


class ConflictIndex:
    """Keep conflicting memories retrievable together without endorsing both."""

    def __init__(
        self,
        assessments: Iterable[ConflictAssessment] = (),
    ):
        self._by_memory: dict[str, list[ConflictAssessment]] = {}
        self._seen: set[tuple[object, ...]] = set()
        for assessment in assessments:
            self.add(assessment)

    def add(self, assessment: ConflictAssessment) -> None:
        if not assessment.detected:
            return
        link_signature = tuple(
            (
                link.source_memory_id,
                link.target_memory_id,
                link.relation_type,
                link.directed,
            )
            for link in assessment.links
        )
        key = (
            assessment.detector,
            assessment.conflict_type,
            tuple(sorted(assessment.memory_ids)),
            link_signature,
        )
        if key in self._seen:
            return
        self._seen.add(key)
        for memory_id in assessment.memory_ids:
            self._by_memory.setdefault(memory_id, []).append(assessment)

    def expand(
        self,
        selected_memory_ids: Iterable[str],
        *,
        minimum_probability: float = 0.45,
        max_companions_per_memory: int = 3,
    ) -> tuple[ConflictRetrievalGroup, ...]:
        groups = []
        for root in tuple(dict.fromkeys(selected_memory_ids)):
            candidates = []
            for assessment in self._by_memory.get(root, ()):
                if assessment.probability < minimum_probability:
                    continue
                other = next(
                    memory_id
                    for memory_id in assessment.memory_ids
                    if memory_id != root
                )
                link = assessment.links[0]
                candidates.append(
                    ConflictRetrievalCandidate(
                        memory_id=other,
                        conflict_type=assessment.conflict_type,
                        probability=assessment.probability,
                        confidence_factor=float(
                            assessment.confidence_factors.get(other, 1.0)
                        ),
                        explanation=assessment.explanation,
                        relation_type=link.relation_type,
                        directed_from_root=(
                            link.directed
                            and link.source_memory_id == root
                        ),
                        conflict_scope=dict(
                            assessment.conflict_scope
                        ),
                    )
                )
            candidates.sort(
                key=lambda item: (
                    -item.probability,
                    item.memory_id,
                )
            )
            groups.append(
                ConflictRetrievalGroup(
                    root_memory_id=root,
                    companions=tuple(
                        candidates[:max_companions_per_memory]
                    ),
                )
            )
        return tuple(groups)


@dataclass(frozen=True)
class ConflictResolution:
    memory_id: str
    candidate_count: int
    assessments: tuple[ConflictAssessment, ...]

    @property
    def conflicts(self) -> tuple[ConflictAssessment, ...]:
        return tuple(
            assessment
            for assessment in self.assessments
            if assessment.detected
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "memory_id": self.memory_id,
            "candidate_count": self.candidate_count,
            "conflict_count": len(self.conflicts),
            "assessments": [
                assessment.to_dict()
                for assessment in self.assessments
            ],
        }


@dataclass(frozen=True)
class ConflictAwareRetrieval:
    query_result: LifecycleQueryResult
    conflict_groups: tuple[ConflictRetrievalGroup, ...]


class ConflictResolver:
    """Compare a new memory only with same-user, same-slot candidates."""

    def __init__(
        self,
        detector: ConflictDetector | None = None,
        *,
        config: ConflictDetectorConfig | None = None,
    ):
        if detector is not None and config is not None:
            raise ValueError("pass detector or config, not both")
        self.detector = detector or HierarchicalRuleConflictDetector(
            config
        )
        self.memories: dict[str, ConflictMemory] = {}
        self.index = ConflictIndex()
        self._by_slot: dict[
            tuple[str, str],
            list[str],
        ] = {}
        self._waiting_by_target: dict[str, list[str]] = {}

    def pending_supersessions(self) -> dict[str, tuple[str, ...]]:
        return {
            target_id: tuple(memory_ids)
            for target_id, memory_ids in self._waiting_by_target.items()
            if memory_ids
        }

    def prune_pending_supersessions(
        self,
        *,
        before: str,
    ) -> tuple[tuple[str, str], ...]:
        cutoff = _instant(before)
        if cutoff is None:
            raise ValueError("before is required")
        expired = []
        for target_id, memory_ids in tuple(
            self._waiting_by_target.items()
        ):
            retained = []
            for memory_id in memory_ids:
                memory = self.memories.get(memory_id)
                observed_at = (
                    _instant(memory.observed_at)
                    if memory is not None
                    else None
                )
                if observed_at is None or observed_at < cutoff:
                    expired.append((target_id, memory_id))
                else:
                    retained.append(memory_id)
            if retained:
                self._waiting_by_target[target_id] = retained
            else:
                self._waiting_by_target.pop(target_id, None)
        return tuple(expired)

    def snapshot(self) -> dict[str, object]:
        return {
            "schema_version": "memory_conflict.resolver.v1",
            "detector": self.detector.name,
            "config": asdict(self.detector.config),
            "memories": [
                memory.to_dict()
                for memory in self.memories.values()
            ],
            "pending_supersessions": {
                target_id: list(memory_ids)
                for target_id, memory_ids
                in self.pending_supersessions().items()
            },
        }

    @classmethod
    def from_snapshot(
        cls,
        value: Mapping[str, object],
        *,
        detector: ConflictDetector | None = None,
        config: ConflictDetectorConfig | None = None,
    ) -> ConflictResolver:
        if (
            value.get("schema_version")
            != "memory_conflict.resolver.v1"
        ):
            raise ValueError("unsupported conflict resolver snapshot")
        if detector is not None and config is not None:
            raise ValueError("pass detector or config, not both")
        if detector is None:
            if config is None:
                config_value = value.get("config")
                config_payload = (
                    dict(config_value)
                    if isinstance(config_value, Mapping)
                    else {}
                )
                config = ConflictDetectorConfig(**config_payload)
            detector_types = {
                detector_type.name: detector_type
                for detector_type in (
                    HierarchicalRuleConflictDetector,
                    WeightedEvidenceConflictDetector,
                    HybridConflictDetector,
                )
            }
            detector_type = detector_types.get(str(value.get("detector")))
            if detector_type is None:
                raise ValueError("unknown conflict detector in snapshot")
            detector = detector_type(config)
        resolver = cls(detector)
        memories = value.get("memories")
        if not isinstance(memories, Sequence):
            raise ValueError("snapshot memories must be a sequence")
        for memory in memories:
            if not isinstance(memory, Mapping):
                raise ValueError("snapshot memory must be a mapping")
            resolver.add(ConflictMemory.from_dict(memory))
        pending = value.get("pending_supersessions")
        if not isinstance(pending, Mapping):
            raise ValueError(
                "snapshot pending_supersessions must be a mapping"
            )
        restored_pending: dict[str, list[str]] = {}
        for target_id, memory_ids in pending.items():
            if not isinstance(target_id, str) or not isinstance(
                memory_ids,
                Sequence,
            ):
                raise ValueError("invalid pending supersession entry")
            selected = []
            for memory_id in memory_ids:
                if (
                    not isinstance(memory_id, str)
                    or memory_id not in resolver.memories
                    or target_id in resolver.memories
                    or target_id not in resolver.memories[
                        memory_id
                    ].supersedes_memory_ids
                ):
                    raise ValueError(
                        "pending supersession does not match memories"
                    )
                selected.append(memory_id)
            if selected:
                restored_pending[target_id] = list(
                    dict.fromkeys(selected)
                )
        resolver._waiting_by_target = restored_pending
        return resolver

    def add(self, memory: ConflictMemory) -> ConflictResolution:
        if memory.memory_id in self.memories:
            raise ValueError(
                f"memory_already_exists:{memory.memory_id}"
            )
        key = (
            memory.user_id,
            _slot_key(memory, self.detector.config),
        )
        candidate_ids = tuple(
            dict.fromkeys(
                (
                    *self._by_slot.get(key, ()),
                    *(
                        memory_id
                        for memory_id
                        in memory.supersedes_memory_ids
                        if (
                            memory_id in self.memories
                            and self.memories[memory_id].user_id
                            == memory.user_id
                        )
                    ),
                    *(
                        memory_id
                        for memory_id
                        in self._waiting_by_target.pop(
                            memory.memory_id,
                            (),
                        )
                        if (
                            memory_id in self.memories
                            and self.memories[memory_id].user_id
                            == memory.user_id
                        )
                    ),
                )
            )
        )
        assessments = tuple(
            self.detector.assess(self.memories[memory_id], memory)
            for memory_id in candidate_ids
        )
        for assessment in assessments:
            self.index.add(assessment)
        self.memories[memory.memory_id] = memory
        self._by_slot.setdefault(key, []).append(memory.memory_id)
        for target_id in memory.supersedes_memory_ids:
            if target_id not in self.memories:
                self._waiting_by_target.setdefault(
                    target_id,
                    [],
                ).append(memory.memory_id)
        return ConflictResolution(
            memory_id=memory.memory_id,
            candidate_count=len(candidate_ids),
            assessments=assessments,
        )

    def query_with_conflicts(
        self,
        engine: MemoryLifecycleEngine,
        observation: LifecycleObservation,
        *,
        top_k: int = 3,
        minimum_conflict_probability: float = 0.45,
        max_companions_per_memory: int = 3,
    ) -> ConflictAwareRetrieval:
        query_result = engine.query(observation, top_k=top_k)
        groups = self.index.expand(
            (
                selection.memory_id
                for selection in query_result.selected
            ),
            minimum_probability=minimum_conflict_probability,
            max_companions_per_memory=max_companions_per_memory,
        )
        return ConflictAwareRetrieval(
            query_result=query_result,
            conflict_groups=groups,
        )


def apply_conflict_assessment(
    engine: MemoryLifecycleEngine,
    assessment: ConflictAssessment,
    *,
    observed_at: str,
) -> tuple[str, ...]:
    relation_ids = []
    for relation in assessment.lifecycle_relations(observed_at):
        engine.add_relation(relation)
        relation_ids.append(relation.relation_id)
    pair = "|".join(sorted(assessment.memory_ids))
    for memory_id, factor in assessment.confidence_factors.items():
        engine.apply_conflict_factor(
            memory_id,
            factor_id=_stable_id(
                "conflict_factor",
                (
                    f"{assessment.detector}|"
                    f"{pair}|{memory_id}"
                ),
            ),
            factor=float(factor),
            at=observed_at,
            rationale=assessment.explanation,
        )
    return tuple(relation_ids)


CONFLICT_DETECTORS = {
    "hierarchical_rules": HierarchicalRuleConflictDetector,
    "weighted_evidence": WeightedEvidenceConflictDetector,
    "hybrid_conservative": HybridConflictDetector,
}


__all__ = [
    "CONFLICT_DETECTORS",
    "ConflictAssessment",
    "ConflictAwareRetrieval",
    "ConflictDetector",
    "ConflictDetectorConfig",
    "ConflictIndex",
    "ConflictLink",
    "ConflictMemory",
    "ConflictReason",
    "ConflictResolution",
    "ConflictResolver",
    "ConflictRetrievalCandidate",
    "ConflictRetrievalGroup",
    "HierarchicalRuleConflictDetector",
    "HybridConflictDetector",
    "WeightedEvidenceConflictDetector",
    "apply_conflict_assessment",
    "condition_relation",
    "time_relation",
]
