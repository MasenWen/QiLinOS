"""Stable public entry point for Observation extraction."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import Any

from .fast_preference_matching import (
    FastPreferenceFrameMatcher,
    ObservationBudget,
)
from .preference_matching import (
    DEFAULT_CANONICAL_TAGS_V1,
    TEMPORAL_INITIALIZATION_V1,
    CanonicalRoleMatch,
    PreferenceFrameResult,
    PreferenceObservationOptions,
)
from .knowledge_tags import (
    KnowledgeTagCandidate,
    WorkplaceTagKnowledgeBase,
    merge_canonical_tags,
)
from .span_matching import RoleHypothesis


_CLAUSE_BOUNDARY = re.compile(r"[\n\r，,；;。.!?！？]+")
_CJK_CONDITION_END = re.compile(
    r"(?:时候|期间|过程中|场景下|任务中|工作中|时)"
)
_ENGLISH_CONDITION_START = re.compile(
    r"\b(?:when|while|during|in\s+the\s+context\s+of)\b",
    re.IGNORECASE,
)
_KNOWLEDGE_CONDITION_PREFIX = re.compile(
    r"(?:在|当|每当|如果|若|针对|关于)\s*$|"
    r"\b(?:in|when|while|during|within|for)\s+$",
    re.IGNORECASE,
)
_KNOWLEDGE_CONDITION_SUFFIX = re.compile(
    r"^\s*(?:中|里|内|时|期间|场景下|环境下|过程中|前|之前)|"
    r"^\s*(?:context|workflow|task|session)\b",
    re.IGNORECASE,
)
_KNOWLEDGE_OBJECT_PREFIX = re.compile(
    r"(?:用|使用|采用|选择|改用|换成|通过|交给|调用|检查|"
    r"喜欢|偏好|优先|尽量|避免|不要|别用)\s*$|"
    r"\b(?:use|choose|prefer|avoid|switch\s+to|call)\s+$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ConditionContext:
    start: int
    end: int
    text: str


@dataclass(frozen=True)
class ConditionContextMatch:
    context: ConditionContext
    result: PreferenceFrameResult


def condition_contexts(text: str) -> tuple[ConditionContext, ...]:
    """Return short structural context clauses for strict fallback matching."""

    values: list[ConditionContext] = []
    clause_start = 0
    for boundary in (*_CLAUSE_BOUNDARY.finditer(text), None):
        clause_end = boundary.start() if boundary is not None else len(text)
        raw = text[clause_start:clause_end]
        leading = len(raw) - len(raw.lstrip())
        trailing = len(raw.rstrip())
        start = clause_start + leading
        end = clause_start + trailing
        clause = text[start:end]
        if 2 <= len(clause) <= 80:
            cjk_end = None
            for marker in _CJK_CONDITION_END.finditer(clause):
                candidate_end = marker.end()
                if 2 <= candidate_end <= 36:
                    cjk_end = candidate_end
            if cjk_end is not None:
                values.append(
                    ConditionContext(
                        start=start,
                        end=start + cjk_end,
                        text=clause[:cjk_end],
                    )
                )
            english = _ENGLISH_CONDITION_START.search(clause)
            if english is not None:
                values.append(
                    ConditionContext(
                        start=start,
                        end=end,
                        text=clause,
                    )
                )
            if not values and clause_start == 0 and len(clause) <= 32:
                values.append(
                    ConditionContext(
                        start=start,
                        end=end,
                        text=clause,
                    )
                )
        clause_start = (
            boundary.end() if boundary is not None else len(text)
        )

    unique = {}
    for value in values:
        if value.text != text.strip():
            unique[(value.start, value.end)] = value
    return tuple(unique.values())[:3]


def condition_context_views(text: str) -> tuple[ConditionContext, ...]:
    """Add bounded full-clause views to the short structural contexts."""

    base = condition_contexts(text)
    values = list(base)
    for context in base:
        clause_start = context.start
        clause_end = len(text)
        for boundary in _CLAUSE_BOUNDARY.finditer(text):
            if boundary.end() <= context.start:
                clause_start = boundary.end()
                continue
            if boundary.start() >= context.end:
                clause_end = boundary.start()
                break
        raw = text[clause_start:clause_end]
        leading = len(raw) - len(raw.lstrip())
        trailing = len(raw.rstrip())
        start = clause_start + leading
        end = clause_start + trailing
        clause = text[start:end]
        if (
            4 <= len(clause) <= 64
            and (start, end) != (context.start, context.end)
        ):
            values.append(
                ConditionContext(start=start, end=end, text=clause)
            )
    stripped = text.strip()
    stripped_start = len(text) - len(text.lstrip())
    if base and 4 <= len(stripped) <= 64:
        values.append(
            ConditionContext(
                start=stripped_start,
                end=stripped_start + len(stripped),
                text=stripped,
            )
        )
    unique = {
        (value.start, value.end): value
        for value in values
        if value.text
    }
    return tuple(unique.values())[:6]


class ObservationMatcher(FastPreferenceFrameMatcher):
    """Production Observation matcher selected by the fixed evaluations."""

    name = "kylin_observation_v1"

    def __init__(
        self,
        embedder: Any,
        *,
        knowledge_base: WorkplaceTagKnowledgeBase | None = None,
        knowledge_top_k_per_group: int = 12,
        **kwargs: Any,
    ):
        tags = kwargs.pop("tags", DEFAULT_CANONICAL_TAGS_V1)
        if knowledge_base is not None:
            tags = merge_canonical_tags(tags, knowledge_base.tags)
        super().__init__(embedder, tags=tags, **kwargs)
        self.knowledge_base = knowledge_base
        self.knowledge_top_k_per_group = knowledge_top_k_per_group

    def match(
        self,
        text: str,
        *,
        options: PreferenceObservationOptions | None = None,
        budget: ObservationBudget | None = None,
    ) -> PreferenceFrameResult:
        if self.knowledge_base is None:
            return super().match(text, options=options, budget=budget)
        enriched, candidates = self.knowledge_options(text, options=options)
        result = super().match(text, options=enriched, budget=budget)
        candidate_ids = {value.tag_id for value in candidates}
        canonical, role_changes = self._resolve_knowledge_roles(
            text,
            result.canonical_matches,
            candidate_ids,
        )
        if role_changes:
            frames = self.assembler.assemble(
                text,
                canonical,
                result.attitudes,
                result.temporals,
            )
            result = replace(
                result,
                canonical_matches=canonical,
                frames=frames,
            )
        diagnostics = {
            **dict(result.diagnostics),
            "knowledge_tags": {
                "candidate_count": len(candidates),
                "condition_candidate_count": sum(
                    "condition" in value.groups for value in candidates
                ),
                "object_candidate_count": sum(
                    "object" in value.groups for value in candidates
                ),
                "exact_candidate_count": sum(
                    value.exact_alias for value in candidates
                ),
                "candidate_tag_ids": tuple(
                    value.tag_id for value in candidates
                ),
                "closed_condition_vocabulary": bool(
                    options and options.condition_tag_ids
                ),
                "closed_object_vocabulary": bool(
                    options and options.object_tag_ids
                ),
                "admitted_condition_tag_ids": tuple(
                    tag_id
                    for tag_id in enriched.condition_tag_ids
                    if not options
                    or tag_id not in options.condition_tag_ids
                ),
                "admitted_object_tag_ids": tuple(
                    tag_id
                    for tag_id in enriched.object_tag_ids
                    if not options or tag_id not in options.object_tag_ids
                ),
                "role_changes": role_changes,
            },
        }
        return replace(result, diagnostics=diagnostics)

    def knowledge_options(
        self,
        text: str,
        *,
        options: PreferenceObservationOptions | None = None,
    ) -> tuple[
        PreferenceObservationOptions,
        tuple[KnowledgeTagCandidate, ...],
    ]:
        if self.knowledge_base is None:
            if options is None:
                raise ValueError("observation_options_required_without_knowledge_base")
            return options, ()
        candidates = self.knowledge_base.query(
            text,
            top_k_per_group=self.knowledge_top_k_per_group,
        )
        # Non-empty caller options define a closed role vocabulary. Knowledge
        # fills an open role, but must not introduce labels that the downstream
        # memory index cannot retrieve.
        supplied_conditions = tuple(
            options.condition_tag_ids if options else ()
        )
        supplied_objects = tuple(options.object_tag_ids if options else ())
        condition_ids = tuple(
            dict.fromkeys(
                (
                    *supplied_conditions,
                    *(
                        value.tag_id
                        for value in candidates
                        if "condition" in value.groups
                        and not supplied_conditions
                    ),
                )
            )
        )
        object_ids = tuple(
            dict.fromkeys(
                (
                    *supplied_objects,
                    *(
                        value.tag_id
                        for value in candidates
                        if "object" in value.groups
                        and not supplied_objects
                    ),
                )
            )
        )
        temporal_labels = (
            options.temporal_labels
            if options and options.temporal_labels
            else tuple(TEMPORAL_INITIALIZATION_V1)
        )
        enriched = PreferenceObservationOptions(
            condition_tag_ids=condition_ids,
            object_tag_ids=object_ids,
            temporal_labels=temporal_labels,
        )
        return enriched, candidates

    @staticmethod
    def _resolve_knowledge_roles(
        text: str,
        canonical: tuple[CanonicalRoleMatch, ...],
        candidate_ids: set[str],
    ) -> tuple[tuple[CanonicalRoleMatch, ...], int]:
        by_span: dict[tuple[int, int], list[CanonicalRoleMatch]] = {}
        for match in canonical:
            if match.tag_id in candidate_ids and match.exact_alias:
                by_span.setdefault((match.start, match.end), []).append(match)
        suppressed: set[int] = set()
        changes = 0
        for (start, end), matches in by_span.items():
            prefix = text[max(0, start - 14) : start]
            suffix = text[end : min(len(text), end + 10)]
            condition_evidence = bool(
                _KNOWLEDGE_CONDITION_PREFIX.search(prefix)
                or _KNOWLEDGE_CONDITION_SUFFIX.search(suffix)
            )
            object_evidence = bool(_KNOWLEDGE_OBJECT_PREFIX.search(prefix))
            preferred = None
            if condition_evidence:
                preferred = "condition"
            elif object_evidence:
                preferred = "object"
            if preferred is None:
                continue
            for match in matches:
                if match.group != preferred:
                    suppressed.add(id(match))
                    changes += 1
        return (
            tuple(match for match in canonical if id(match) not in suppressed),
            changes,
        )

    def match_condition_contexts(
        self,
        text: str,
        *,
        options: PreferenceObservationOptions,
        multiview: bool = False,
        top_k_per_context: int | None = None,
        include_below_threshold: bool = False,
    ) -> tuple[ConditionContextMatch, ...]:
        matches = []
        contexts = (
            condition_context_views(text)
            if multiview
            else condition_contexts(text)
        )
        for context in contexts:
            requested_before = self.embedder.requested
            computed_before = self.embedder.computed
            hypothesis = RoleHypothesis(
                start=0,
                end=len(context.text),
                text=context.text,
                group="condition",
                label="condition",
                score=1.0,
                similarity=1.0,
                null_margin=1.0,
                competition_margin=1.0,
                sources=("condition_context_fallback",),
            )
            canonical = self.canonical_matcher.match(
                (hypothesis,),
                allowed_tag_ids={
                    "condition": options.condition_tag_ids,
                },
                top_k_per_hypothesis=top_k_per_context,
                include_below_threshold=include_below_threshold,
            )
            matches.append(
                ConditionContextMatch(
                    context=context,
                    result=PreferenceFrameResult(
                        algorithm="condition_context_closed_choice",
                        text=context.text,
                        hypotheses=(hypothesis,),
                        canonical_matches=canonical,
                        attitudes=(),
                        temporals=(),
                        frames=(),
                        diagnostics={
                            "embedding_requested_delta": (
                                self.embedder.requested
                                - requested_before
                            ),
                            "embedding_computed_delta": (
                                self.embedder.computed
                                - computed_before
                            ),
                        },
                    ),
                )
            )
        return tuple(matches)


__all__ = [
    "ConditionContext",
    "ConditionContextMatch",
    "ObservationBudget",
    "ObservationMatcher",
    "condition_contexts",
    "condition_context_views",
]
