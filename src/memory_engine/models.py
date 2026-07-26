from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Mapping


def _text(value: Any) -> str:
    return str(value or "").strip()


def _values(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        normalized = value.replace("；", ";").replace("，", ",")
        return tuple(part.strip() for part in normalized.replace(",", ";").split(";") if part.strip())
    if isinstance(value, (list, tuple, set)):
        return tuple(_text(item) for item in value if _text(item))
    return (_text(value),) if _text(value) else ()


def parse_time(value: Any) -> datetime | None:
    text = _text(value)
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


@dataclass(frozen=True)
class RetrievalContext:
    user_id: str = "nex_user"
    query_time: datetime | None = None
    query_text: str = ""
    task: str = ""
    goal: str = ""
    current_step: str = ""
    scene: str = ""
    apps: tuple[str, ...] = ()
    tools: tuple[str, ...] = ()
    artifact_ids: tuple[str, ...] = ()
    entity_ids: tuple[str, ...] = ()
    known_conditions: tuple[str, ...] = ()
    memory_need: str = ""
    task_type: str = ""
    hints: Mapping[str, str] = field(default_factory=dict)

    @classmethod
    def from_mapping(
        cls,
        query: str,
        context: Mapping[str, Any] | None = None,
        user_id: str | None = None,
    ) -> "RetrievalContext":
        data = dict(context or {})
        app_values = data.get("apps") or data.get("app") or data.get("current_app")
        return cls(
            user_id=user_id or _text(data.get("user_id")) or "nex_user",
            query_time=parse_time(data.get("query_time")),
            query_text=query,
            task=_text(data.get("task") or data.get("current_task")),
            goal=_text(data.get("goal") or data.get("current_goal")),
            current_step=_text(data.get("current_step")),
            scene=_text(data.get("scene")),
            apps=_values(app_values),
            tools=_values(data.get("tools")),
            artifact_ids=_values(data.get("artifact_ids")),
            entity_ids=_values(data.get("entity_ids")),
            known_conditions=_values(data.get("known_conditions")),
            memory_need=_text(data.get("memory_need")),
            task_type=_text(data.get("task_type")),
            hints={str(k): _text(v) for k, v in dict(data.get("hints") or {}).items()},
        )


@dataclass
class RetrievalResponse:
    items: list[dict[str, Any]]
    trace: dict[str, Any]

    def as_prompt(self) -> str:
        if not self.items:
            return ""
        grouped: dict[str, list[str]] = {"core": [], "recent": [], "conditional": []}
        for item in self.items:
            metadata = item.get("metadata") or {}
            memory_type = str(metadata.get("memory_type", ""))
            category = str(metadata.get("memory_category", ""))
            if category in {"conflict_update", "scenario_preference"}:
                bucket = "conditional"
            elif memory_type == "short_term" or item.get("tier") == "mid":
                bucket = "recent"
            else:
                bucket = "core"
            grouped[bucket].append(str(item.get("memory", "")))

        labels = (("core", "[核心偏好]"), ("recent", "[近期记忆]"), ("conditional", "[条件记忆]"))
        lines: list[str] = []
        for bucket, label in labels:
            if grouped[bucket]:
                lines.append(label)
                lines.extend(f"- {text}" for text in grouped[bucket])
        return "\n".join(lines)


@dataclass(frozen=True)
class Observation:
    observation_id: str
    source_event_id: str
    user_id: str
    session_id: str
    event_time: str
    ingest_time: str
    source_type: str
    actor: str
    content: str
    sequence_no: int | None = None
    app: str = ""
    tool: str = ""
    action: str = ""
    artifact_refs: tuple[str, ...] = ()
    entity_refs: tuple[str, ...] = ()
    available_tools: tuple[str, ...] = ()
    input_refs: tuple[str, ...] = ()
    output_refs: tuple[str, ...] = ()
    state: Mapping[str, Any] = field(default_factory=dict)
    result: Mapping[str, Any] = field(default_factory=dict)
    raw_source_ref: str = ""
    completeness: Mapping[str, Any] = field(default_factory=dict)
    task_hint: str = ""
    goal_hint: str = ""
    context: Mapping[str, Any] = field(default_factory=dict)
    source_reliability: float = 1.0
    privacy: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = "observation.v1"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Episode:
    episode_id: str
    user_id: str
    session_id: str
    observation_ids: list[str]
    start_time: str
    end_time: str | None = None
    status: str = "open"
    task_hint: str = ""
    goal_hint: str = ""
    apps: list[str] = field(default_factory=list)
    artifact_refs: list[str] = field(default_factory=list)
    entity_refs: list[str] = field(default_factory=list)
    task_instance_ids: list[str] = field(default_factory=list)
    boundary_confidence: float = 0.0
    boundary_reason: str = "initial"
    state: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = "episode.v1"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Evidence:
    evidence_id: str
    user_id: str
    evidence_type: str
    memory_family: str
    memory_type: str
    memory_category: str
    claim_subject: str
    claim_slot: str
    claim_value: str
    claim_polarity: str
    observed_time: str
    source_observation_ids: tuple[str, ...]
    independent_unit_id: str
    source_episode_ids: tuple[str, ...] = ()
    valid_from: str = ""
    valid_to: str = ""
    impact_ids: tuple[str, ...] = ()
    directness: str = "explicit"
    source_reliability: float = 1.0
    extraction_confidence: float = 1.0
    condition: Mapping[str, Any] = field(default_factory=dict)
    statistics: Mapping[str, Any] = field(default_factory=dict)
    extractor: Mapping[str, Any] = field(default_factory=dict)
    privacy: Mapping[str, Any] = field(default_factory=dict)
    status: str = "active"
    schema_version: str = "evidence.v1"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class MemoryRecord:
    memory_id: str
    user_id: str
    memory_family: str
    memory_type: str
    memory_category: str
    status: str
    slot_key: str
    semantic_value: str
    evidence_ids: list[str]
    condition: Mapping[str, Any] = field(default_factory=dict)
    scope: Mapping[str, Any] = field(default_factory=dict)
    statistics: Mapping[str, Any] = field(default_factory=dict)
    confidence: Mapping[str, Any] = field(default_factory=dict)
    stability: Mapping[str, Any] = field(default_factory=dict)
    provenance: Mapping[str, Any] = field(default_factory=dict)
    version: int = 1
    created_at: str = ""
    updated_at: str = ""
    schema_version: str = "memory.v1"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
