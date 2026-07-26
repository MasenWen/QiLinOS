from __future__ import annotations

import math
from dataclasses import replace
from datetime import datetime
from typing import Any, Iterable, Mapping

from .contracts import (
    ConditionRelation,
    ConflictType,
    MemoryCandidate,
    StrictConflictGroup,
    StrictMemory,
)
from .conflict import condition_relation


class EvidenceShareConfidence:
    module_id = "scoring.confidence.evidence_share.v1"

    def __init__(self, config: Mapping[str, Any]):
        self.epsilon = float(config["epsilon"])
        self.absolute_threshold = float(config["absolute_threshold"])
        self.margin_threshold = float(config["margin_threshold"])
        self.minimum_support = int(config["minimum_support"])

    def score(
        self,
        memories: Iterable[StrictMemory],
        groups: Iterable[StrictConflictGroup],
    ) -> list[StrictMemory]:
        state = {memory.memory_id: memory for memory in memories}
        grouped_ids = {
            memory_id
            for group in groups
            for memory_id in group.memory_ids
        }
        for group in groups:
            members = [state[memory_id] for memory_id in group.memory_ids]
            if group.conflict_type is ConflictType.CONDITIONAL:
                for memory in members:
                    state[memory.memory_id] = replace(
                        memory,
                        confidence=self._score_one(
                            memory,
                            choice=1.0,
                            margin=1.0,
                            unresolved=group.status != "partitioned",
                            group=group,
                        ),
                    )
                continue
            denominator = sum(
                self.epsilon + len(memory.support_unit_ids)
                for memory in members
            )
            choices = {
                memory.memory_id: (
                    self.epsilon + len(memory.support_unit_ids)
                )
                / denominator
                for memory in members
            }
            ordered_choices = sorted(choices.values(), reverse=True)
            margin = (
                ordered_choices[0] - ordered_choices[1]
                if len(ordered_choices) > 1
                else 1.0
            )
            for memory in members:
                state[memory.memory_id] = replace(
                    memory,
                    confidence=self._score_one(
                        memory,
                        choice=choices[memory.memory_id],
                        margin=margin,
                        unresolved=group.status == "unresolved",
                        group=group,
                    ),
                )
        for memory_id, memory in list(state.items()):
            if memory_id in grouped_ids:
                continue
            state[memory_id] = replace(
                memory,
                confidence=self._score_one(
                    memory,
                    choice=1.0,
                    margin=1.0,
                    unresolved=False,
                    group=None,
                ),
            )
        return list(state.values())

    def _score_one(
        self,
        memory: StrictMemory,
        *,
        choice: float,
        margin: float,
        unresolved: bool,
        group: StrictConflictGroup | None,
    ) -> dict[str, Any]:
        support = len(memory.support_unit_ids)
        oppose = len(memory.oppose_unit_ids)
        absolute = (self.epsilon + support) / (
            2 * self.epsilon + support + oppose
        )
        reasons: list[str] = []
        if absolute < self.absolute_threshold:
            reasons.append("absolute_below_threshold")
        if margin < self.margin_threshold:
            reasons.append("choice_margin_below_threshold")
        if support < self.minimum_support:
            reasons.append("insufficient_independent_support")
        if unresolved:
            reasons.append("conflict_unresolved")
        return {
            "absolute": round(absolute, 8),
            "choice": round(choice, 8),
            "margin": round(margin, 8),
            "support_independent_units": support,
            "oppose_independent_units": oppose,
            "support_unit_ids": list(memory.support_unit_ids),
            "oppose_unit_ids": list(memory.oppose_unit_ids),
            "source_breakdown": {
                "directness": memory.provenance.get("directness"),
                "source_module_id": memory.provenance.get("source_module_id"),
            },
            "conflict_group_id": (
                group.conflict_group_id if group else ""
            ),
            "abstain": bool(reasons),
            "abstain_reasons": reasons,
            "parameters": {
                "epsilon": self.epsilon,
                "absolute_threshold": self.absolute_threshold,
                "margin_threshold": self.margin_threshold,
                "minimum_support": self.minimum_support,
            },
        }


class OpportunityWindowStability:
    module_id = "scoring.stability.opportunity_window_index.v1"

    def __init__(self, config: Mapping[str, Any]):
        self.target_n = int(config["target_independent_units"])
        self.target_span_days = float(config["target_span_days"])
        self.weights = {
            "support_consistency": float(
                config["support_consistency_weight"]
            ),
            "window_consistency": float(
                config["window_consistency_weight"]
            ),
            "change_rate": float(config["change_rate_weight"]),
        }

    def score(
        self,
        memories: Iterable[StrictMemory],
        candidates: Iterable[MemoryCandidate],
    ) -> list[StrictMemory]:
        candidates_list = list(candidates)
        return [
            self._score_one(memory, candidates_list)
            for memory in memories
        ]

    def _score_one(
        self,
        memory: StrictMemory,
        candidates: list[MemoryCandidate],
    ) -> StrictMemory:
        applicable = [
            candidate
            for candidate in candidates
            if candidate.user_id == memory.user_id
            and candidate.slot_key == memory.slot_key
            and condition_relation(candidate.condition, memory.condition)
            is not ConditionRelation.DISJOINT
        ]
        by_unit: dict[str, list[MemoryCandidate]] = {}
        for candidate in applicable:
            by_unit.setdefault(candidate.independent_unit_id, []).append(candidate)
        observed_units = set(by_unit)
        supported_units = set(memory.support_unit_ids) & observed_units
        n_observed = len(observed_units)
        n_supported = len(supported_units)
        support_consistency = (
            n_supported / n_observed if n_observed else 0.0
        )

        unit_times = {
            unit_id: min(
                _candidate_time(candidate)
                for candidate in unit_candidates
            )
            for unit_id, unit_candidates in by_unit.items()
        }
        observed_windows = {
            (value.isocalendar().year, value.isocalendar().week)
            for value in unit_times.values()
        }
        supported_windows = {
            (
                unit_times[unit_id].isocalendar().year,
                unit_times[unit_id].isocalendar().week,
            )
            for unit_id in supported_units
            if unit_id in unit_times
        }
        window_consistency = (
            len(supported_windows) / len(observed_windows)
            if observed_windows
            else 0.0
        )

        ordered_units = sorted(
            by_unit,
            key=lambda unit_id: (unit_times[unit_id], unit_id),
        )
        choices = [
            _unit_choice(by_unit[unit_id])
            for unit_id in ordered_units
        ]
        switches = sum(
            left != right
            for left, right in zip(choices, choices[1:])
        )
        change_rate = switches / max(n_observed - 1, 1)
        if unit_times:
            span_days = (
                max(unit_times.values()) - min(unit_times.values())
            ).total_seconds() / 86400
        else:
            span_days = 0.0
        count_coverage = min(n_observed / self.target_n, 1.0)
        time_coverage = min(span_days / self.target_span_days, 1.0)
        coverage = math.sqrt(count_coverage * time_coverage)
        consistency = (
            self.weights["support_consistency"] * support_consistency
            + self.weights["window_consistency"] * window_consistency
            + self.weights["change_rate"] * (1.0 - change_rate)
        )
        stability = coverage * consistency
        explicit = memory.provenance.get("directness") in {
            "explicit_user",
            "versioned_config",
        }
        initial_floor_applied = bool(explicit and n_supported > 0)
        if initial_floor_applied:
            stability = max(stability, 0.60)
        return replace(
            memory,
            applicable_unit_ids=tuple(sorted(observed_units)),
            stability={
                "value": round(stability, 8),
                "support_consistency": round(support_consistency, 8),
                "window_consistency": round(window_consistency, 8),
                "change_rate": round(change_rate, 8),
                "count_coverage": round(count_coverage, 8),
                "time_coverage": round(time_coverage, 8),
                "coverage": round(coverage, 8),
                "n_observed": n_observed,
                "n_supported": n_supported,
                "span_days": round(span_days, 8),
                "switches": switches,
                "initial_explicit_floor_applied": initial_floor_applied,
                "eligible_for_archive": n_observed >= self.target_n,
                "parameters": {
                    "target_n": self.target_n,
                    "target_span_days": self.target_span_days,
                    "weights": self.weights,
                },
            },
        )


def _candidate_time(candidate: MemoryCandidate) -> datetime:
    value = str(candidate.signals.get("observed_time") or candidate.valid_from)
    return datetime.fromisoformat(value)


def _unit_choice(candidates: list[MemoryCandidate]) -> str:
    ordered = sorted(
        candidates,
        key=lambda item: (
            _candidate_time(item),
            item.candidate_id,
        ),
    )
    return ordered[-1].semantic_value
