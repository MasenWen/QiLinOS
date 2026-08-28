from __future__ import annotations

import hashlib
import re
from typing import Any, Iterable, Mapping
from uuid import NAMESPACE_URL, uuid5

from .contracts import (
    AtomicEvidence,
    Completion,
    EvidenceAdmission,
    ExecutionFragment,
    SourceType,
    StrictObservation,
)


CLAIM_SPLIT = re.compile(
    r"(?:[，,；;。]\s*)|(?:\s+(?:and|also|同时|并且)\s+)",
    re.IGNORECASE,
)
LONG_TERM_MARKERS = (
    "以后",
    "今后",
    "默认",
    "一直",
    "总是",
    "记住",
    "长期",
    "prefer",
    "preference",
    "by default",
    "always",
    "remember",
)
TEMPORARY_MARKERS = (
    "这次",
    "本次",
    "当前任务",
    "临时",
    "仅这一次",
    "this time",
    "for this task",
    "temporarily",
)
SAFETY_MARKERS = (
    "发送前确认",
    "发送前必须确认",
    "必须确认",
    "不要保存",
    "不得发送",
    "must confirm",
    "do not save",
    "never send",
)
OUTPUT_STYLE_VALUES = {
    "简洁": "简洁",
    "精简": "简洁",
    "concise": "简洁",
    "详细": "详细",
    "详尽": "详细",
    "detailed": "详细",
    "要点": "要点式",
    "bullet": "要点式",
}
CURRENCY_VALUES = {
    "usd": "USD",
    "美元": "USD",
    "人民币": "CNY",
    "cny": "CNY",
    "欧元": "EUR",
    "eur": "EUR",
}
CONDITION_KEYS = (
    "customer_type",
    "project_id",
    "device_id",
    "account_id",
    "risk_level",
    "task_type",
    "scene",
    "app",
    "activity",
)


class TypedRuleEvidenceExtractor:
    module_id = "evidence.typed_rule_extractor.v1"

    def extract(
        self,
        fragments: Iterable[ExecutionFragment],
        observations: Mapping[str, StrictObservation],
    ) -> list[AtomicEvidence]:
        evidence: list[AtomicEvidence] = []
        for fragment in fragments:
            ordered = [
                observations[observation_id]
                for observation_id in fragment.observation_ids
                if observation_id in observations
            ]
            evidence.extend(self._dialogue_evidence(fragment, ordered))
            evidence.extend(self._manual_config_evidence(fragment, ordered))
            evidence.extend(self._behavior_evidence(fragment, ordered))
            evidence.extend(self._tool_evidence(fragment, ordered))
            evidence.extend(self._workflow_evidence(fragment, ordered))
        return list({item.evidence_id: item for item in evidence}.values())

    def _dialogue_evidence(
        self,
        fragment: ExecutionFragment,
        observations: list[StrictObservation],
    ) -> list[AtomicEvidence]:
        result: list[AtomicEvidence] = []
        for observation in observations:
            if (
                observation.source_type is not SourceType.DIALOGUE
                or observation.actor != "user"
            ):
                continue
            full_text = observation.content.casefold()
            durable_context = (
                any(marker in full_text for marker in LONG_TERM_MARKERS)
                and not any(marker in full_text for marker in TEMPORARY_MARKERS)
            )
            temporary_context = (
                any(marker in full_text for marker in TEMPORARY_MARKERS)
                and not any(marker in full_text for marker in LONG_TERM_MARKERS)
            )
            for claim in _split_claims(observation.content):
                classified = _classify_claim(
                    claim,
                    observation,
                    durable_context=durable_context,
                    temporary_context=temporary_context,
                )
                if classified is None:
                    continue
                result.append(
                    _make_evidence(
                        fragment=fragment,
                        source=(observation,),
                        evidence_type=classified["evidence_type"],
                        memory_family=classified["memory_family"],
                        candidate_kind=classified["candidate_kind"],
                        claim_slot=classified["claim_slot"],
                        claim_value=classified["claim_value"],
                        claim_polarity=classified["claim_polarity"],
                        condition=_condition(observation, fragment),
                        directness="explicit_user",
                        extraction_confidence=classified["confidence"],
                        admission=classified["admission"],
                        admission_reasons=classified["admission_reasons"],
                        statistics={
                            "atomic_claim_text": claim,
                            "temporary": classified["temporary"],
                            "agent_recommendation": False,
                        },
                    )
                )
        return result

    def _behavior_evidence(
        self,
        fragment: ExecutionFragment,
        observations: list[StrictObservation],
    ) -> list[AtomicEvidence]:
        result: list[AtomicEvidence] = []
        for observation in observations:
            if observation.source_type is not SourceType.GUI_ACTION:
                continue
            action = observation.action.casefold()
            if not action or action in {
                "click",
                "clicked",
                "double_click",
                "mouse_move",
                "mousemove",
                "window_focus",
                "window_blur",
                "scroll",
            }:
                continue
            task = fragment.task or observation.task_hint or "unknown"
            context_action = any(
                marker in action
                for marker in ("open", "select", "focus", "navigate")
            )
            slot = (
                f"context:{task}:recent_object"
                if context_action
                else f"task:{task}:{action}"
            )
            scoped = _make_evidence(
                fragment=fragment,
                source=(observation,),
                evidence_type=(
                    "current_context"
                    if context_action
                    else "task_state"
                ),
                memory_family="knowledge",
                candidate_kind="fact",
                claim_slot=slot,
                claim_value=observation.content,
                claim_polarity="support",
                condition=_condition(observation, fragment),
                directness="observed_gui_action",
                extraction_confidence=0.95,
                admission=EvidenceAdmission.SCOPED_ONLY,
                admission_reasons=(
                    "runtime_context_must_not_become_ltm",
                ),
                statistics={
                    "action": observation.action,
                    "app": observation.app,
                    "task_state": not context_action,
                    "temporary": True,
                },
            )
            result.append(scoped)

            behavior_condition = _behavior_condition(observation)
            behavior_kind = (
                "template"
                if "template" in " ".join(
                    (observation.content, *observation.artifact_refs)
                ).casefold()
                else "fact"
            )
            result.append(
                _make_evidence(
                    fragment=fragment,
                    source=(observation,),
                    evidence_type="observed_behavior",
                    memory_family="knowledge",
                    candidate_kind=behavior_kind,
                    claim_slot=_behavior_slot(
                        observation,
                        behavior_condition,
                    ),
                    claim_value=_behavior_claim_value(observation),
                    claim_polarity="support",
                    condition=behavior_condition,
                    directness="observed_gui_action",
                    extraction_confidence=0.80,
                    admission=EvidenceAdmission.LONG_TERM_CANDIDATE,
                    admission_reasons=(
                        "repeated_observed_behavior_may_form_knowledge",
                    ),
                    statistics={
                        "action": observation.action,
                        "app": observation.app,
                        "behavior_choice": True,
                        "preference_inference_forbidden": True,
                        "requires_independent_repetition": True,
                        "available_alternatives": list(
                            observation.context.get("available_alternatives")
                            or ()
                        ),
                    },
                )
            )
        return result

    def _manual_config_evidence(
        self,
        fragment: ExecutionFragment,
        observations: list[StrictObservation],
    ) -> list[AtomicEvidence]:
        result: list[AtomicEvidence] = []
        for observation in observations:
            if observation.source_type is not SourceType.MANUAL_CONFIG:
                continue
            namespace = str(observation.result.get("namespace") or "config")
            key = str(observation.result.get("key") or "unknown")
            value = observation.result.get("new_value")
            changed_by = str(observation.result.get("changed_by") or observation.actor)
            version = observation.result.get("version")
            user_owned = changed_by in {"user", observation.user_id}
            admission = (
                EvidenceAdmission.LONG_TERM_CANDIDATE
                if user_owned
                else EvidenceAdmission.NO_PREFERENCE_CANDIDATE
            )
            result.append(
                _make_evidence(
                    fragment=fragment,
                    source=(observation,),
                    evidence_type="manual_config_version",
                    memory_family="preference" if user_owned else "knowledge",
                    candidate_kind="fact" if not user_owned else "tool_preference",
                    claim_slot=f"config:{namespace}:{key}",
                    claim_value=_scalar(value),
                    claim_polarity="support",
                    condition=_condition(observation, fragment),
                    directness="versioned_config",
                    extraction_confidence=1.0,
                    admission=admission,
                    admission_reasons=(
                        ("user_owned_versioned_config",)
                        if user_owned
                        else ("system_config_is_not_user_preference",)
                    ),
                    statistics={
                        "version": version,
                        "changed_by": changed_by,
                        "old_value": observation.result.get("old_value"),
                    },
                )
            )
        return result

    def _tool_evidence(
        self,
        fragment: ExecutionFragment,
        observations: list[StrictObservation],
    ) -> list[AtomicEvidence]:
        result: list[AtomicEvidence] = []
        for observation in observations:
            if observation.source_type is not SourceType.TOOL_RESULT:
                continue
            success = bool(observation.result.get("success"))
            error = str(observation.result.get("error_signature") or "unknown")
            result.append(
                _make_evidence(
                    fragment=fragment,
                    source=(observation,),
                    evidence_type="tool_workflow_outcome",
                    memory_family="knowledge",
                    candidate_kind="workflow" if success else "case",
                    claim_slot=f"tool:{observation.tool or 'unknown'}:outcome",
                    claim_value="success" if success else f"failure:{error}",
                    claim_polarity="support",
                    condition=_condition(observation, fragment),
                    directness="observed_tool_result",
                    extraction_confidence=1.0,
                    admission=(
                        EvidenceAdmission.SCOPED_ONLY
                        if success
                        else EvidenceAdmission.CASE_CANDIDATE
                    ),
                    admission_reasons=(
                        ("single_success_is_execution_scoped",)
                        if success
                        else ("single_failure_is_case_not_stable_rule",)
                    ),
                    statistics={
                        "success": success,
                        "error_signature": error if not success else "",
                        "output_schema_valid": observation.result.get(
                            "output_schema_valid"
                        ),
                        "state_changed": observation.result.get("state_changed"),
                        "single_failure": not success,
                        "is_fallback": False,
                    },
                )
            )
        return result

    def _workflow_evidence(
        self,
        fragment: ExecutionFragment,
        observations: list[StrictObservation],
    ) -> list[AtomicEvidence]:
        tools = [
            item
            for item in observations
            if item.source_type is SourceType.TOOL_RESULT
        ]
        successful = [item for item in tools if item.result.get("success")]
        if fragment.completion is not Completion.COMPLETED or not successful:
            return self._recovery_cases(fragment, tools)

        workflow = _workflow_value(fragment, successful)
        source = tuple(successful)
        result = [
            _make_evidence(
                fragment=fragment,
                source=source,
                evidence_type="complete_workflow",
                memory_family="knowledge",
                candidate_kind="workflow",
                claim_slot=f"workflow:{fragment.task or fragment.goal or 'unknown'}",
                claim_value=workflow,
                claim_polarity="support",
                condition=_combined_condition(source, fragment),
                directness="observed_complete_execution",
                extraction_confidence=1.0,
                admission=EvidenceAdmission.LONG_TERM_CANDIDATE,
                admission_reasons=(
                    "complete_workflow_is_knowledge_not_preference",
                ),
                statistics={
                    "completion": fragment.completion.value,
                    "required_steps": list(fragment.actions),
                    "is_fallback": any(
                        not item.result.get("success") for item in tools
                    ),
                    "preference_inference_forbidden": True,
                },
            )
        ]
        result.extend(self._recovery_cases(fragment, tools))
        return result

    def _recovery_cases(
        self,
        fragment: ExecutionFragment,
        tools: list[StrictObservation],
    ) -> list[AtomicEvidence]:
        cases: list[AtomicEvidence] = []
        for index, failed in enumerate(tools):
            if failed.result.get("success"):
                continue
            recovered = next(
                (
                    item
                    for item in tools[index + 1 :]
                    if item.result.get("success") and item.tool != failed.tool
                ),
                None,
            )
            if recovered is None:
                continue
            error = str(failed.result.get("error_signature") or "unknown")
            cases.append(
                _make_evidence(
                    fragment=fragment,
                    source=(failed, recovered),
                    evidence_type="recovery_case",
                    memory_family="knowledge",
                    candidate_kind="case",
                    claim_slot=(
                        f"case:{fragment.task or fragment.goal or 'unknown'}:"
                        f"{error}"
                    ),
                    claim_value=f"{failed.tool}->{recovered.tool}",
                    claim_polarity="support",
                    condition={
                        **_combined_condition((failed, recovered), fragment),
                        "error_signature": error,
                        "failed_tool": failed.tool,
                    },
                    directness="observed_recovery",
                    extraction_confidence=1.0,
                    admission=EvidenceAdmission.CASE_CANDIDATE,
                    admission_reasons=(
                        "fallback_is_recovery_case_not_tool_preference",
                    ),
                    statistics={
                        "is_fallback": True,
                        "failed_tool": failed.tool,
                        "recovery_tool": recovered.tool,
                        "single_case": True,
                        "preference_inference_forbidden": True,
                    },
                )
            )
        return cases


def _classify_claim(
    claim: str,
    observation: StrictObservation,
    *,
    durable_context: bool,
    temporary_context: bool,
) -> dict[str, Any] | None:
    lowered = claim.casefold()
    temporary = (
        any(marker in lowered for marker in TEMPORARY_MARKERS)
        or temporary_context
    )
    durable = (
        any(marker in lowered for marker in LONG_TERM_MARKERS)
        or durable_context
    ) and not temporary
    admission = (
        EvidenceAdmission.SCOPED_ONLY
        if temporary
        else EvidenceAdmission.LONG_TERM_CANDIDATE
        if durable
        else EvidenceAdmission.SCOPED_ONLY
    )
    reasons = (
        ("temporary_instruction",)
        if temporary
        else ("explicit_long_term_signal",)
        if durable
        else ("instruction_without_long_term_signal",)
    )
    polarity = (
        "oppose"
        if any(marker in lowered for marker in ("不再", "不要", "never", "do not"))
        else "support"
    )

    for marker, value in CURRENCY_VALUES.items():
        if marker in lowered:
            return {
                "evidence_type": "explicit_preference",
                "memory_family": "preference",
                "candidate_kind": "fact",
                "claim_slot": "preference:currency",
                "claim_value": value,
                "claim_polarity": polarity,
                "confidence": 0.98,
                "admission": admission,
                "admission_reasons": reasons,
                "temporary": temporary,
            }
    for marker, value in OUTPUT_STYLE_VALUES.items():
        if marker in lowered:
            return {
                "evidence_type": "output_style",
                "memory_family": "preference",
                "candidate_kind": "output_style",
                "claim_slot": "preference:output_style",
                "claim_value": value,
                "claim_polarity": polarity,
                "confidence": 0.95,
                "admission": admission,
                "admission_reasons": reasons,
                "temporary": temporary,
            }
    if any(marker in lowered for marker in SAFETY_MARKERS):
        return {
            "evidence_type": "explicit_safety",
            "memory_family": "preference",
            "candidate_kind": "safety",
            "claim_slot": "safety:send_or_persist",
            "claim_value": _normalize_text(claim),
            "claim_polarity": polarity,
            "confidence": 0.96,
            "admission": admission,
            "admission_reasons": reasons,
            "temporary": temporary,
        }
    if "模板" in lowered or "template" in lowered:
        return {
            "evidence_type": "template_reuse",
            "memory_family": "knowledge",
            "candidate_kind": "template",
            "claim_slot": f"template:{observation.task_hint or 'general'}",
            "claim_value": _normalize_text(claim),
            "claim_polarity": polarity,
            "confidence": 0.90,
            "admission": admission,
            "admission_reasons": reasons,
            "temporary": temporary,
        }
    if (
        any(marker in lowered for marker in LONG_TERM_MARKERS)
        or any(marker in lowered for marker in TEMPORARY_MARKERS)
    ):
        if not _instruction_payload(lowered):
            return None
        return {
            "evidence_type": "explicit_preference",
            "memory_family": "preference",
            "candidate_kind": "tool_preference",
            "claim_slot": _generic_slot(observation, claim),
            "claim_value": _normalize_text(claim),
            "claim_polarity": polarity,
            "confidence": 0.82,
            "admission": admission,
            "admission_reasons": reasons,
            "temporary": temporary,
        }
    return None


def _instruction_payload(lowered: str) -> str:
    remainder = lowered
    for marker in LONG_TERM_MARKERS + TEMPORARY_MARKERS:
        remainder = remainder.replace(marker, " ")
    return re.sub(r"[\W_]+", "", remainder, flags=re.UNICODE)


def _make_evidence(
    *,
    fragment: ExecutionFragment,
    source: tuple[StrictObservation, ...],
    evidence_type: str,
    memory_family: str,
    candidate_kind: str,
    claim_slot: str,
    claim_value: str,
    claim_polarity: str,
    condition: Mapping[str, Any],
    directness: str,
    extraction_confidence: float,
    admission: EvidenceAdmission,
    admission_reasons: tuple[str, ...],
    statistics: Mapping[str, Any],
) -> AtomicEvidence:
    source_ids = tuple(item.observation_id for item in source)
    identity = "|".join(
        (
            fragment.fragment_id,
            claim_slot,
            claim_value,
            claim_polarity,
            *source_ids,
        )
    )
    return AtomicEvidence(
        evidence_id="sev-" + uuid5(NAMESPACE_URL, identity).hex,
        user_id=fragment.user_id,
        independent_unit_id=fragment.fragment_id,
        evidence_type=evidence_type,
        memory_family=memory_family,
        candidate_kind=candidate_kind,
        claim_subject=fragment.user_id,
        claim_slot=claim_slot,
        claim_value=claim_value,
        claim_polarity=claim_polarity,
        condition=dict(condition),
        observed_time=source[-1].event_time,
        valid_from=source[-1].event_time,
        valid_to="",
        source_observation_ids=source_ids,
        source_fragment_ids=(fragment.fragment_id,),
        directness=directness,
        source_reliability=min(item.source_reliability for item in source),
        extraction_confidence=extraction_confidence,
        admission=admission,
        admission_reasons=admission_reasons,
        statistics=dict(statistics),
        extractor={
            "module_id": TypedRuleEvidenceExtractor.module_id,
            "atomic_claim": True,
        },
        privacy={
            "secret_scan": "inherited_pass",
            "raw_payload_persisted": False,
        },
    )


def _split_claims(content: str) -> list[str]:
    return [
        item.strip()
        for item in CLAIM_SPLIT.split(content)
        if item and item.strip()
    ]


def _condition(
    observation: StrictObservation,
    fragment: ExecutionFragment,
) -> dict[str, Any]:
    explicit = observation.context.get("condition")
    condition = dict(explicit) if isinstance(explicit, Mapping) else {}
    condition.update(
        {
            key: observation.context[key]
            for key in CONDITION_KEYS
            if observation.context.get(key) not in (None, "")
        }
    )
    if fragment.task:
        condition.setdefault("task", fragment.task)
    if observation.app:
        condition.setdefault("app", observation.app)
    return condition


def _behavior_condition(
    observation: StrictObservation,
) -> dict[str, Any]:
    explicit = observation.context.get("condition")
    condition = dict(explicit) if isinstance(explicit, Mapping) else {}
    condition.update(
        {
            key: observation.context[key]
            for key in CONDITION_KEYS
            if key != "app"
            and observation.context.get(key) not in (None, "")
        }
    )
    if observation.app:
        condition.setdefault("app", observation.app)
    return condition


def _behavior_slot(
    observation: StrictObservation,
    condition: Mapping[str, Any],
) -> str:
    domain = str(
        condition.get("scene")
        or condition.get("app")
        or "general"
    )
    action = observation.action or "action"
    return (
        "behavior:"
        + re.sub(r"\W+", "_", domain.casefold(), flags=re.UNICODE).strip("_")
        + ":"
        + re.sub(r"\W+", "_", action.casefold(), flags=re.UNICODE).strip("_")
    )


def _behavior_claim_value(observation: StrictObservation) -> str:
    return re.sub(
        r"\s*对象\s*[:：]\s*.+$",
        "",
        observation.content,
        flags=re.UNICODE,
    ).strip()


def _combined_condition(
    observations: Iterable[StrictObservation],
    fragment: ExecutionFragment,
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for observation in observations:
        result.update(_condition(observation, fragment))
    return result


def _workflow_value(
    fragment: ExecutionFragment,
    successful: list[StrictObservation],
) -> str:
    semantic = list(fragment.actions)
    if not semantic:
        semantic = [f"tool:{item.tool}:success" for item in successful]
    return " -> ".join(semantic)


def _generic_slot(
    observation: StrictObservation,
    claim: str,
) -> str:
    digest = hashlib.sha256(_normalize_text(claim).encode("utf-8")).hexdigest()[:12]
    task = _normalize_text(observation.task_hint or "general").replace(" ", "_")
    return f"preference:{task}:{digest}"


def _normalize_text(value: str) -> str:
    return " ".join(value.strip().split())


def _scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "null"
    return str(value)
