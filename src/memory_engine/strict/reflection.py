from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable
from uuid import NAMESPACE_URL, uuid5

from .contracts import (
    AtomicEvidence,
    LifecycleStatus,
    ReflectionArtifact,
    StrictMemory,
)


class GroundedRuleConsolidation:
    module_id = "reflection.grounded_rule_consolidation.v1"

    def reflect(
        self,
        user_id: str,
        memories: Iterable[StrictMemory],
        evidence: Iterable[AtomicEvidence],
        *,
        now: str | None = None,
    ) -> list[ReflectionArtifact]:
        timestamp = now or datetime.now(timezone.utc).isoformat()
        evidence_by_id = {
            item.evidence_id: item
            for item in evidence
            if item.status == "active"
        }
        artifacts: list[ReflectionArtifact] = []
        for memory in memories:
            if memory.user_id != user_id or memory.status not in {
                LifecycleStatus.CANDIDATE,
                LifecycleStatus.STABLE,
                LifecycleStatus.RECOVER,
            }:
                continue
            cited = tuple(
                evidence_id
                for evidence_id in memory.evidence_ids
                if evidence_id in evidence_by_id
            )
            errors: list[str] = []
            missing = set(memory.evidence_ids) - set(cited)
            if missing:
                errors.append("missing_or_retracted_evidence")
            if not cited:
                errors.append("no_active_evidence")
            if any(
                evidence_by_id[evidence_id].claim_slot != memory.slot_key
                or evidence_by_id[evidence_id].claim_value
                != memory.semantic_value
                for evidence_id in cited
            ):
                errors.append("claim_not_entailed_by_evidence")
            claim = _grounded_claim(memory)
            identity = (
                f"{memory.memory_id}|{claim}|{'|'.join(sorted(cited))}"
            )
            artifacts.append(
                ReflectionArtifact(
                    reflection_id="reflection-"
                    + uuid5(NAMESPACE_URL, identity).hex,
                    user_id=user_id,
                    reflection_type=_reflection_type(memory),
                    claim=claim,
                    memory_ids=(memory.memory_id,),
                    evidence_ids=cited,
                    grounding_verified=not errors,
                    grounding_errors=tuple(errors),
                    created_at=timestamp,
                )
            )
        return artifacts


def _grounded_claim(memory: StrictMemory) -> str:
    condition = (
        " when "
        + ", ".join(
            f"{key}={value}" for key, value in sorted(memory.condition.items())
        )
        if memory.condition
        else ""
    )
    return f"{memory.slot_key} = {memory.semantic_value}{condition}"


def _reflection_type(memory: StrictMemory) -> str:
    if memory.candidate_kind == "workflow":
        return "workflow"
    if memory.candidate_kind == "case":
        return "case"
    if memory.candidate_kind == "template":
        return "template"
    return "grounded_memory"
