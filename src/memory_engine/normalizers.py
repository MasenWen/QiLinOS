from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any, Callable, Mapping

from .models import Observation
from .security import is_engine_safe


SOURCE_ALIASES = {
    "chat": "dialogue",
    "message": "dialogue",
    "gui": "gui_action",
    "ui_action": "gui_action",
    "tool": "tool_result",
    "tool_call": "tool_result",
    "config": "manual_config",
    "configuration": "manual_config",
    "system": "system_event",
}

ACTION_ALIASES = {
    "clicked": "click",
    "tap": "click",
    "tapped": "click",
    "double_clicked": "double_click",
    "typed": "type",
    "input": "type",
    "entered": "type",
    "opened": "open",
    "closed": "close",
    "saved": "save",
    "submitted": "submit",
    "sent": "send",
    "completed": "complete",
    "finished": "complete",
    "failed": "fail",
    "errored": "fail",
    "succeeded": "success",
}

STRUCTURED_CONTEXT_FIELDS = (
    "scenario_id",
    "competition_ability_id",
    "ability_group",
    "utterance_role",
    "memory_signal_type",
    "preference_scope",
    "effective_scope",
    "referenced_app_ids",
    "supersedes_event_id",
    "conflict_group_id",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _stable_id(prefix: str, value: str) -> str:
    return f"{prefix}_{hashlib.sha256(value.encode('utf-8')).hexdigest()[:24]}"


def _text(value: Any) -> str:
    return str(value or "").strip()


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _values(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return tuple(part.strip() for part in re.split(r"[,;]", value) if part.strip())
    if isinstance(value, (list, tuple, set)):
        return tuple(_text(item) for item in value if _text(item))
    text = _text(value)
    return (text,) if text else ()


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))


def normalize_action(value: Any) -> str:
    action = re.sub(r"[\s-]+", "_", _text(value).lower())
    return ACTION_ALIASES.get(action, action)


def _privacy_gate(event: Mapping[str, Any]) -> None:
    if not is_engine_safe(_canonical(event)):
        raise ValueError("unsafe_source_event")


def _source_id(event: Mapping[str, Any], source_type: str) -> str:
    supplied = _text(event.get("source_event_id") or event.get("event_id") or event.get("id"))
    if supplied:
        return supplied
    return _stable_id(source_type, _canonical(event))


def _completeness(required: tuple[str, ...], values: Mapping[str, Any]) -> dict[str, Any]:
    present = tuple(name for name in required if values.get(name) not in (None, "", (), [], {}))
    missing = tuple(name for name in required if name not in present)
    return {
        "required": required,
        "present": present,
        "missing": missing,
        "schema_valid": not missing,
        "ratio": len(present) / len(required) if required else 1.0,
    }


def _build(
    event: Mapping[str, Any],
    *,
    source_type: str,
    actor: str,
    content: str,
    app: str = "",
    tool: str = "",
    action: str = "",
    state: Mapping[str, Any] | None = None,
    result: Mapping[str, Any] | None = None,
    required: tuple[str, ...] = ("user_id", "session_id", "content"),
    reliability: float = 1.0,
) -> Observation:
    _privacy_gate(event)
    source_event_id = _source_id(event, source_type)
    context = _mapping(event.get("context"))
    for field_name in STRUCTURED_CONTEXT_FIELDS:
        if field_name in event and field_name not in context:
            context[field_name] = event[field_name]
    values = {
        "user_id": _text(event.get("user_id")) or "nex_user",
        "session_id": _text(event.get("session_id")) or "unknown",
        "content": content,
        "app": app,
        "tool": tool,
        "action": action,
    }
    return Observation(
        observation_id=_stable_id("obs", source_event_id),
        source_event_id=source_event_id,
        user_id=values["user_id"],
        session_id=values["session_id"],
        event_time=_text(event.get("event_time") or event.get("timestamp")) or _now(),
        ingest_time=_now(),
        source_type=source_type,
        actor=actor,
        content=content,
        sequence_no=int(event["sequence_no"]) if event.get("sequence_no") is not None else None,
        app=app,
        tool=tool,
        action=action,
        artifact_refs=_values(event.get("artifact_refs") or event.get("artifacts")),
        entity_refs=_values(event.get("entity_refs") or event.get("entities")),
        available_tools=_values(event.get("available_tools")),
        input_refs=_values(event.get("input_refs")),
        output_refs=_values(event.get("output_refs")),
        state=dict(state or {}),
        result=dict(result or {}),
        raw_source_ref=_text(event.get("raw_source_ref")),
        completeness=_completeness(required, values),
        task_hint=_text(event.get("task_hint") or event.get("task") or context.get("task")),
        goal_hint=_text(event.get("goal_hint") or event.get("goal") or context.get("goal")),
        context=context,
        source_reliability=float(event.get("source_reliability", reliability)),
        privacy=_mapping(event.get("privacy"))
        or {"sensitivity": "normal", "deletion_scope": "user"},
    )


def dialogue_adapter(event: Mapping[str, Any]) -> Observation:
    actor = _text(event.get("actor") or event.get("role")) or "user"
    content = _text(event.get("content") or event.get("text") or event.get("message"))
    return _build(
        event,
        source_type="dialogue",
        actor=actor,
        content=content,
        app=_text(event.get("app")),
        action="message",
        reliability=1.0 if actor == "user" else 0.7,
    )


def gui_action_adapter(event: Mapping[str, Any]) -> Observation:
    app = _text(event.get("app") or event.get("application"))
    action = normalize_action(event.get("action") or event.get("event"))
    target = _text(event.get("target") or event.get("control") or event.get("element"))
    content = _text(event.get("content")) or " ".join(part for part in (action, target) if part)
    return _build(
        event,
        source_type="gui_action",
        actor=_text(event.get("actor")) or "user",
        content=content,
        app=app,
        action=action,
        state=_mapping(event.get("state")),
        result=_mapping(event.get("result")),
        required=("user_id", "session_id", "app", "action"),
        reliability=0.9,
    )


def tool_result_adapter(event: Mapping[str, Any]) -> Observation:
    tool = _text(event.get("tool") or event.get("tool_name"))
    success = bool(event.get("success", not event.get("error") and not event.get("error_signature")))
    result = {
        "success": success,
        "error_signature": _text(event.get("error_signature") or event.get("error")),
        "output_schema_valid": bool(event.get("output_schema_valid", True)),
        "state_changed": bool(event.get("state_changed", False)),
        "latency_ms": float(event.get("latency_ms") or event.get("latency") or 0.0),
        "output": event.get("output") if "output" in event else event.get("tool_result"),
    }
    action = normalize_action(event.get("action")) or ("success" if success else "fail")
    content = _text(event.get("content")) or f"{tool} {action}".strip()
    return _build(
        event,
        source_type="tool_result",
        actor=_text(event.get("actor")) or "agent",
        content=content,
        app=_text(event.get("app")),
        tool=tool,
        action=action,
        state=_mapping(event.get("state")),
        result=result,
        required=("user_id", "session_id", "tool", "action"),
        reliability=1.0,
    )


def manual_config_adapter(event: Mapping[str, Any]) -> Observation:
    namespace = _text(event.get("namespace"))
    key = _text(event.get("key"))
    changed = bool(event.get("success", event.get("changed", True)))
    result = {
        "namespace": namespace,
        "key": key,
        "old_value": event.get("old_value"),
        "new_value": event.get("new_value"),
        "version": _text(event.get("version")),
        "scope": _text(event.get("scope")),
        "changed_by": _text(event.get("changed_by") or event.get("actor")),
        "success": changed,
        "error_signature": _text(event.get("error_signature") or event.get("error")),
    }
    content = _text(event.get("content")) or f"configuration {namespace}.{key} changed"
    return _build(
        event,
        source_type="manual_config",
        actor=result["changed_by"] or "user",
        content=content,
        app=_text(event.get("app")),
        action="config_change" if changed else "config_change_failed",
        state=_mapping(event.get("state")),
        result=result,
        required=("user_id", "session_id", "action"),
        reliability=1.0,
    )


def system_event_adapter(event: Mapping[str, Any]) -> Observation:
    action = normalize_action(event.get("action") or event.get("event") or event.get("name"))
    content = _text(event.get("content") or event.get("message")) or action
    return _build(
        event,
        source_type="system_event",
        actor=_text(event.get("actor")) or "system",
        content=content,
        app=_text(event.get("app")),
        tool=_text(event.get("tool")),
        action=action,
        state=_mapping(event.get("state")),
        result=_mapping(event.get("result")),
        required=("user_id", "session_id", "action"),
        reliability=0.95,
    )


ADAPTERS: dict[str, Callable[[Mapping[str, Any]], Observation]] = {
    "dialogue": dialogue_adapter,
    "gui_action": gui_action_adapter,
    "tool_result": tool_result_adapter,
    "manual_config": manual_config_adapter,
    "system_event": system_event_adapter,
}


def observation_from_event(event: Mapping[str, Any]) -> Observation:
    source_type = _text(event.get("source_type") or event.get("type") or "dialogue").lower()
    source_type = SOURCE_ALIASES.get(source_type, source_type)
    adapter = ADAPTERS.get(source_type)
    if adapter is None:
        raise ValueError(f"unsupported_source_type:{source_type}")
    return adapter(event)


def dialogue_to_observation(
    content: str,
    *,
    actor: str,
    user_id: str,
    session_id: str,
    source_event_id: str | None = None,
    event_time: str | None = None,
    context: Mapping[str, Any] | None = None,
) -> Observation:
    event = {
        "source_type": "dialogue",
        "content": content,
        "actor": actor,
        "user_id": user_id,
        "session_id": session_id,
        "source_event_id": source_event_id,
        "event_time": event_time,
        "context": dict(context or {}),
    }
    return dialogue_adapter(event)
