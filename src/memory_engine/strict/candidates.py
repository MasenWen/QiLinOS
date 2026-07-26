from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable
from uuid import NAMESPACE_URL, uuid5

from .contracts import AtomicEvidence, MemoryCandidate


@dataclass(frozen=True)
class RuleCandidateExtractor:
    module_id: str
    candidate_kind: str
    cardinality: str

    def propose(
        self,
        evidence: Iterable[AtomicEvidence],
    ) -> list[MemoryCandidate]:
        return [
            _candidate(item, self)
            for item in evidence
            if item.eligible_for_candidate
            and item.candidate_kind == self.candidate_kind
        ]


def strict_candidate_modules() -> dict[str, RuleCandidateExtractor]:
    return {
        "tool_preference": RuleCandidateExtractor(
            "candidate.tool_preference_rule.v1",
            "tool_preference",
            "single",
        ),
        "output_style": RuleCandidateExtractor(
            "candidate.output_style_rule.v1",
            "output_style",
            "single",
        ),
        "safety": RuleCandidateExtractor(
            "candidate.safety_rule.v1",
            "safety",
            "single",
        ),
        "fact": RuleCandidateExtractor(
            "candidate.fact_rule.v1",
            "fact",
            "single",
        ),
        "workflow": RuleCandidateExtractor(
            "candidate.workflow_rule.v1",
            "workflow",
            "single",
        ),
        "case": RuleCandidateExtractor(
            "candidate.case_rule.v1",
            "case",
            "multi",
        ),
        "template": RuleCandidateExtractor(
            "candidate.template_rule.v1",
            "template",
            "single",
        ),
    }


def _candidate(
    evidence: AtomicEvidence,
    extractor: RuleCandidateExtractor,
) -> MemoryCandidate:
    text = str(evidence.statistics.get("atomic_claim_text") or "").casefold()
    explicit_temporal = any(
        marker in text
        for marker in (
            "以后",
            "今后",
            "从今天起",
            "不再",
            "from now",
            "going forward",
            "no longer",
        )
    )
    config_version = evidence.statistics.get("version")
    action = str(evidence.statistics.get("action") or "").casefold()
    observed_behavior = evidence.evidence_type == "observed_behavior"
    exclusive_choice = observed_behavior and action in {
        "create_chart",
        "choose_tool",
        "select_tool",
        "set_default",
        "set_preference",
    }
    cardinality = (
        "single"
        if exclusive_choice
        else "multi"
        if observed_behavior
        else extractor.cardinality
    )
    identity = f"{evidence.evidence_id}|{extractor.module_id}"
    return MemoryCandidate(
        candidate_id="cand-" + uuid5(NAMESPACE_URL, identity).hex,
        evidence_id=evidence.evidence_id,
        user_id=evidence.user_id,
        independent_unit_id=evidence.independent_unit_id,
        memory_family=evidence.memory_family,
        candidate_kind=evidence.candidate_kind,
        slot_key=evidence.claim_slot,
        semantic_value=evidence.claim_value,
        polarity=evidence.claim_polarity,
        condition=dict(evidence.condition),
        valid_from=evidence.valid_from,
        valid_to=evidence.valid_to,
        cardinality=cardinality,
        source_module_id=extractor.module_id,
        source_observation_ids=evidence.source_observation_ids,
        source_fragment_ids=evidence.source_fragment_ids,
        signals={
            "directness": evidence.directness,
            "source_reliability": evidence.source_reliability,
            "extraction_confidence": evidence.extraction_confidence,
            "explicit_temporal": explicit_temporal,
            "config_version": config_version,
            "observed_time": evidence.observed_time,
            "evidence_type": evidence.evidence_type,
            "action": action,
            "behavior_choice": bool(
                evidence.statistics.get("behavior_choice")
            ),
            "fallback": bool(evidence.statistics.get("is_fallback")),
            "preference_inference_forbidden": bool(
                evidence.statistics.get("preference_inference_forbidden")
            ),
        },
    )
