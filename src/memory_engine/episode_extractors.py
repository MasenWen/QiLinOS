from __future__ import annotations

import hashlib
import re
from dataclasses import replace
from typing import Any

from .extractors import PREFERENCE_MARKERS, SAFETY_MARKERS, explicit_fact_to_evidence
from .models import Episode, Evidence, Observation
from .store import MemoryEngineStore


EXPLICIT_HINTS = (
    *PREFERENCE_MARKERS,
    *SAFETY_MARKERS,
    "请记住",
    "以后",
    "不再",
    "usd",
    "人民币",
    "美元",
    "简洁",
    "详细",
    "prefer",
    "default",
    "always",
    "never",
    "remember",
)


def _stable_id(prefix: str, value: str) -> str:
    return f"{prefix}_{hashlib.sha256(value.encode('utf-8')).hexdigest()[:24]}"


def _condition(observation: Observation) -> dict[str, Any]:
    explicit = observation.context.get("condition")
    if isinstance(explicit, dict):
        return dict(explicit)
    allowed = (
        "customer_type",
        "project_id",
        "device_id",
        "account_id",
        "risk_level",
        "task_type",
        "scene",
    )
    return {
        key: observation.context[key]
        for key in allowed
        if observation.context.get(key) not in (None, "")
    }


def _split_claims(content: str) -> list[str]:
    values = [
        value.strip()
        for value in re.split(r"[，,、；;。]|(?:并且)|(?:同时)", content)
        if value.strip()
    ]
    return values or ([content.strip()] if content.strip() else [])


def _explicit_evidence(observation: Observation, episode: Episode) -> list[Evidence]:
    if observation.source_type != "dialogue" or observation.actor != "user":
        return []
    evidence: list[Evidence] = []
    for claim in _split_claims(observation.content):
        lowered = claim.lower()
        if not any(marker.lower() in lowered for marker in EXPLICIT_HINTS):
            continue
        base = explicit_fact_to_evidence(observation, claim)
        evidence.append(
            replace(
                base,
                evidence_id=_stable_id(
                    "ev",
                    f"{episode.episode_id}|explicit|{base.claim_slot}|{base.claim_value}",
                ),
                source_episode_ids=(episode.episode_id,),
                independent_unit_id=episode.episode_id,
                condition=_condition(observation),
                extractor={
                    "method": "episode_explicit_rule",
                    "version": "1.0.0",
                },
            )
        )
    return evidence


def _tool_outcome_evidence(observation: Observation, episode: Episode) -> Evidence:
    success = bool(observation.result.get("success"))
    error_signature = str(observation.result.get("error_signature") or "")
    outcome = "success" if success else f"failure:{error_signature or 'unknown'}"
    return Evidence(
        evidence_id=_stable_id(
            "ev",
            f"{episode.episode_id}|tool_outcome|{observation.observation_id}|{outcome}",
        ),
        user_id=observation.user_id,
        evidence_type="tool_result",
        memory_family="knowledge",
        memory_type="short_term",
        memory_category="tool_outcome",
        claim_subject=observation.user_id,
        claim_slot=f"tool:{observation.tool or 'unknown'}:outcome",
        claim_value=outcome,
        claim_polarity="support",
        condition=_condition(observation),
        observed_time=observation.event_time,
        valid_from=observation.event_time,
        source_observation_ids=(observation.observation_id,),
        source_episode_ids=(episode.episode_id,),
        independent_unit_id=episode.episode_id,
        directness="tool_observed",
        source_reliability=observation.source_reliability,
        extraction_confidence=1.0,
        statistics={
            "success": success,
            "error_signature": error_signature,
            "output_schema_valid": bool(
                observation.result.get("output_schema_valid")
            ),
            "state_changed": bool(observation.result.get("state_changed")),
            "latency_ms": float(observation.result.get("latency_ms") or 0.0),
            "available_tools": list(observation.available_tools),
            "is_fallback": False,
        },
        extractor={"method": "episode_tool_outcome_rule", "version": "1.0.0"},
        privacy=observation.privacy,
    )


def _completion_evidence(observation: Observation, episode: Episode) -> Evidence:
    task = observation.task_hint or episode.task_hint or episode.episode_id
    return Evidence(
        evidence_id=_stable_id(
            "ev",
            f"{episode.episode_id}|task_completion|{observation.observation_id}",
        ),
        user_id=observation.user_id,
        evidence_type="workflow_relation",
        memory_family="knowledge",
        memory_type="short_term",
        memory_category="task_outcome",
        claim_subject=observation.user_id,
        claim_slot=f"task:{task}:completion",
        claim_value="completed",
        claim_polarity="support",
        condition=_condition(observation),
        observed_time=observation.event_time,
        valid_from=observation.event_time,
        source_observation_ids=(observation.observation_id,),
        source_episode_ids=(episode.episode_id,),
        independent_unit_id=episode.episode_id,
        directness="tool_observed"
        if observation.source_type == "tool_result"
        else "explicit",
        source_reliability=observation.source_reliability,
        extraction_confidence=1.0,
        statistics={"task_result": "completed"},
        extractor={"method": "episode_completion_rule", "version": "1.0.0"},
        privacy=observation.privacy,
    )


def _recovery_evidence(
    failed: Observation,
    recovered: Observation,
    episode: Episode,
) -> Evidence:
    task = recovered.task_hint or failed.task_hint or episode.task_hint or "unknown"
    error_signature = str(failed.result.get("error_signature") or "unknown")
    condition = {
        **_condition(failed),
        "error_signature": error_signature,
        "failed_tool": failed.tool or "unknown",
    }
    value = f"{failed.tool or 'unknown'}->{recovered.tool or 'unknown'}"
    return Evidence(
        evidence_id=_stable_id(
            "ev",
            f"{episode.episode_id}|recovery|{failed.observation_id}|"
            f"{recovered.observation_id}|{value}",
        ),
        user_id=failed.user_id,
        evidence_type="workflow_relation",
        memory_family="knowledge",
        memory_type="mid_term",
        memory_category="recovery_case",
        claim_subject=failed.user_id,
        claim_slot=f"workflow:{task}:recovery",
        claim_value=value,
        claim_polarity="support",
        condition=condition,
        observed_time=recovered.event_time,
        valid_from=recovered.event_time,
        source_observation_ids=(
            failed.observation_id,
            recovered.observation_id,
        ),
        source_episode_ids=(episode.episode_id,),
        independent_unit_id=episode.episode_id,
        directness="tool_observed",
        source_reliability=min(
            failed.source_reliability,
            recovered.source_reliability,
        ),
        extraction_confidence=1.0,
        statistics={
            "is_fallback": True,
            "failed_tool": failed.tool,
            "recovery_tool": recovered.tool,
            "error_signature": error_signature,
            "recovery_success": True,
        },
        extractor={"method": "episode_recovery_rule", "version": "1.0.0"},
        privacy=failed.privacy,
    )


def extract_episode_evidence(
    store: MemoryEngineStore,
    episode_id: str,
) -> list[Evidence]:
    episode = store.get_episode(episode_id)
    if episode is None:
        raise KeyError(f"episode_not_found:{episode_id}")
    observations = [
        store.get_observation(observation_id)
        for observation_id in episode.observation_ids
    ]
    ordered = [observation for observation in observations if observation is not None]
    evidence: list[Evidence] = []

    for observation in ordered:
        evidence.extend(_explicit_evidence(observation, episode))
        if observation.source_type == "tool_result":
            evidence.append(_tool_outcome_evidence(observation, episode))
        if (
            observation.action
            in {
                "complete",
                "task_complete",
                "submit",
                "send",
                "file_submitted",
                "email_sent",
            }
            or observation.result.get("task_complete")
            or observation.state.get("task_complete")
        ):
            evidence.append(_completion_evidence(observation, episode))

    failed_tools = [
        observation
        for observation in ordered
        if observation.source_type == "tool_result"
        and not observation.result.get("success")
    ]
    for failed in failed_tools:
        recovered = next(
            (
                observation
                for observation in ordered
                if observation.source_type == "tool_result"
                and observation.result.get("success")
                and observation.tool != failed.tool
                and observation.event_time >= failed.event_time
            ),
            None,
        )
        if recovered is not None:
            evidence.append(_recovery_evidence(failed, recovered, episode))

    by_id = {item.evidence_id: item for item in evidence}
    return list(by_id.values())
