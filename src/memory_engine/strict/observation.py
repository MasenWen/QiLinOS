from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any, Mapping
from uuid import NAMESPACE_URL, uuid5

from .contracts import Completion, SourceType, StrictObservation


SECRET_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bxai-[A-Za-z0-9_-]{20,}\b"),
    re.compile(
        r"(?i)\b(api[_ -]?key|access[_ -]?token|private[_ -]?key|password)"
        r"\s*[:=]\s*['\"]?[^\s,'\"]{8,}"
    ),
)

SOURCE_RELIABILITY = {
    SourceType.DIALOGUE: 0.85,
    SourceType.GUI_ACTION: 0.80,
    SourceType.TOOL_RESULT: 0.95,
    SourceType.MANUAL_CONFIG: 1.00,
    SourceType.SYSTEM_EVENT: 0.95,
}


class UnsafeObservationError(ValueError):
    pass


class TypedRuleObservationNormalizer:
    module_id = "observation.typed_rule_normalization.v1"

    def normalize(
        self,
        event: Mapping[str, Any],
        *,
        ingest_time: datetime | None = None,
    ) -> StrictObservation:
        source_type = SourceType(str(event.get("source_type") or "").strip())
        source_event_id = _required(event, "source_event_id")
        user_id = _required(event, "user_id")
        session_id = _required(event, "session_id")
        semantic = _semantic_event(event)
        secret_matches = _find_secrets(semantic)
        if secret_matches:
            raise UnsafeObservationError(
                f"unsafe source event ({', '.join(secret_matches)})"
            )

        now = ingest_time or datetime.now(timezone.utc)
        event_time = str(event.get("event_time") or now.isoformat())
        content = _content(source_type, event)
        completion = _completion(source_type, event)
        content_hash = hashlib.sha256(
            json.dumps(
                semantic,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            ).encode("utf-8")
        ).hexdigest()
        observation_id = "obs-" + uuid5(
            NAMESPACE_URL,
            f"strict:{user_id}:{session_id}:{source_event_id}:{content_hash}",
        ).hex

        pre_state = dict(event.get("pre_state") or {})
        post_state = dict(event.get("post_state") or event.get("state") or {})
        result = _result(source_type, event)
        return StrictObservation(
            observation_id=observation_id,
            source_event_id=source_event_id,
            content_hash=content_hash,
            user_id=user_id,
            session_id=session_id,
            sequence_no=_integer_or_none(event.get("sequence_no")),
            event_time=event_time,
            ingest_time=now.isoformat(),
            source_type=source_type,
            actor=_actor(source_type, event),
            content=content,
            task_hint=str(event.get("task") or event.get("task_hint") or "").strip(),
            goal_hint=str(event.get("goal") or event.get("goal_hint") or "").strip(),
            app=str(event.get("app") or "").strip(),
            tool=str(event.get("tool") or event.get("tool_name") or "").strip(),
            action=str(event.get("action") or event.get("event") or "").strip(),
            artifact_refs=_strings(event.get("artifact_refs")),
            entity_refs=_strings(event.get("entity_refs")),
            input_refs=_strings(event.get("input_refs")),
            output_refs=_strings(event.get("output_refs")),
            pre_state=pre_state,
            post_state=post_state,
            result=result,
            context=dict(event.get("context") or {}),
            completion=completion,
            source_reliability=float(
                event.get("source_reliability", SOURCE_RELIABILITY[source_type])
            ),
            privacy={
                "admission": "allowed",
                "secret_scan": "passed",
                "raw_payload_persisted": False,
            },
            raw_source_ref=str(event.get("raw_source_ref") or "").strip(),
        )


def _semantic_event(event: Mapping[str, Any]) -> dict[str, Any]:
    excluded = {"ingest_time", "retry_count", "transport_id"}
    return {
        str(key): value
        for key, value in event.items()
        if key not in excluded
    }


def _find_secrets(event: Mapping[str, Any]) -> list[str]:
    text = json.dumps(event, ensure_ascii=False, sort_keys=True, default=str)
    return [
        f"pattern_{index + 1}"
        for index, pattern in enumerate(SECRET_PATTERNS)
        if pattern.search(text)
    ]


def _required(event: Mapping[str, Any], name: str) -> str:
    value = str(event.get(name) or "").strip()
    if not value:
        raise ValueError(f"strict observation requires {name}")
    return value


def _actor(source_type: SourceType, event: Mapping[str, Any]) -> str:
    explicit = str(event.get("actor") or "").strip()
    if explicit:
        return explicit
    if source_type is SourceType.DIALOGUE:
        return "user"
    if source_type is SourceType.MANUAL_CONFIG:
        return str(event.get("changed_by") or "user")
    return "system"


def _content(source_type: SourceType, event: Mapping[str, Any]) -> str:
    explicit = str(event.get("content") or event.get("message") or "").strip()
    if explicit:
        return explicit
    if source_type is SourceType.GUI_ACTION:
        return " ".join(
            part
            for part in (
                str(event.get("action") or "").strip(),
                str(event.get("target") or "").strip(),
            )
            if part
        )
    if source_type is SourceType.TOOL_RESULT:
        tool = str(event.get("tool") or event.get("tool_name") or "tool").strip()
        status = "success" if bool(event.get("success")) else "failure"
        return f"{tool} {status}"
    if source_type is SourceType.MANUAL_CONFIG:
        namespace = str(event.get("namespace") or "").strip()
        key = str(event.get("key") or "").strip()
        return f"{namespace}.{key} configuration changed".strip(".")
    return str(event.get("event") or "system event").strip()


def _result(
    source_type: SourceType,
    event: Mapping[str, Any],
) -> dict[str, Any]:
    if source_type is SourceType.TOOL_RESULT:
        return {
            "success": bool(event.get("success")),
            "error_signature": str(event.get("error_signature") or ""),
            "output_schema_valid": event.get("output_schema_valid"),
            "state_changed": event.get("state_changed"),
            "latency_ms": event.get("latency_ms"),
        }
    if source_type is SourceType.MANUAL_CONFIG:
        return {
            "namespace": event.get("namespace"),
            "key": event.get("key"),
            "old_value": event.get("old_value"),
            "new_value": event.get("new_value"),
            "version": event.get("version"),
            "scope": event.get("scope"),
            "changed_by": event.get("changed_by"),
        }
    return dict(event.get("result") or {})


def _completion(
    source_type: SourceType,
    event: Mapping[str, Any],
) -> Completion:
    explicit = str(event.get("completion") or "").strip().lower()
    aliases = {
        "complete": Completion.COMPLETED,
        "completed": Completion.COMPLETED,
        "success": Completion.COMPLETED,
        "incomplete": Completion.INCOMPLETE,
        "failed": Completion.FAILED,
        "failure": Completion.FAILED,
        "unknown": Completion.UNKNOWN,
    }
    if explicit in aliases:
        return aliases[explicit]
    marker = str(event.get("event") or event.get("action") or "").lower()
    if marker in {"task_complete", "task_completed", "submitted", "finished"}:
        return Completion.COMPLETED
    if marker in {"task_failed", "failed", "cancelled"}:
        return Completion.FAILED
    if source_type is SourceType.SYSTEM_EVENT and marker in {
        "task_started",
        "task_resumed",
    }:
        return Completion.INCOMPLETE
    return Completion.UNKNOWN


def _strings(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value.strip(),) if value.strip() else ()
    return tuple(str(item).strip() for item in value if str(item).strip())


def _integer_or_none(value: Any) -> int | None:
    if value in (None, ""):
        return None
    return int(value)
