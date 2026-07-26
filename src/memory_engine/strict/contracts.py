from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any, Mapping


STRICT_SCHEMA_VERSION = "memory_engine.strict.contracts.v1"


class SourceType(StrEnum):
    DIALOGUE = "dialogue"
    GUI_ACTION = "gui_action"
    TOOL_RESULT = "tool_result"
    MANUAL_CONFIG = "manual_config"
    SYSTEM_EVENT = "system_event"


class Completion(StrEnum):
    UNKNOWN = "unknown"
    INCOMPLETE = "incomplete"
    COMPLETED = "completed"
    FAILED = "failed"


class LifecycleStatus(StrEnum):
    CANDIDATE = "candidate"
    STABLE = "stable"
    HISTORICAL = "historical"
    ARCHIVE = "archive"
    RECOVER = "recover"
    BLOCKED = "blocked"
    DELETED = "deleted"


class ImpactAction(StrEnum):
    SUPPORT = "support"
    CONTRADICT = "contradict"
    SUPERSEDE = "supersede"
    SPECIALIZE = "specialize"
    CREATE = "create"
    NOOP = "noop"
    UNRESOLVED = "unresolved"


class ConflictType(StrEnum):
    STATIC = "static"
    DYNAMIC = "dynamic"
    CONDITIONAL = "conditional"
    UNRESOLVED = "unresolved"


class ConditionRelation(StrEnum):
    EQUAL = "equal"
    SUBSET = "subset"
    SUPERSET = "superset"
    DISJOINT = "disjoint"
    OVERLAP = "overlap"
    UNKNOWN = "unknown"


class EvidenceAdmission(StrEnum):
    LONG_TERM_CANDIDATE = "long_term_candidate"
    SCOPED_ONLY = "scoped_only"
    CASE_CANDIDATE = "case_candidate"
    NO_PREFERENCE_CANDIDATE = "no_preference_candidate"
    REJECTED = "rejected"


def _iso(value: str | datetime | None) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.astimezone().isoformat()
    text = str(value).strip()
    if not text:
        return ""
    return datetime.fromisoformat(text.replace("Z", "+00:00")).isoformat()


def _strings(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value.strip(),) if value.strip() else ()
    return tuple(str(item).strip() for item in value if str(item).strip())


@dataclass(frozen=True)
class StrictObservation:
    observation_id: str
    source_event_id: str
    content_hash: str
    user_id: str
    session_id: str
    sequence_no: int | None
    event_time: str
    ingest_time: str
    source_type: SourceType
    actor: str
    content: str
    task_hint: str = ""
    goal_hint: str = ""
    app: str = ""
    tool: str = ""
    action: str = ""
    artifact_refs: tuple[str, ...] = ()
    entity_refs: tuple[str, ...] = ()
    input_refs: tuple[str, ...] = ()
    output_refs: tuple[str, ...] = ()
    pre_state: Mapping[str, Any] = field(default_factory=dict)
    post_state: Mapping[str, Any] = field(default_factory=dict)
    result: Mapping[str, Any] = field(default_factory=dict)
    context: Mapping[str, Any] = field(default_factory=dict)
    completion: Completion = Completion.UNKNOWN
    source_reliability: float = 1.0
    privacy: Mapping[str, Any] = field(default_factory=dict)
    raw_source_ref: str = ""
    schema_version: str = "strict.observation.v1"

    def __post_init__(self) -> None:
        required = {
            "observation_id": self.observation_id,
            "source_event_id": self.source_event_id,
            "content_hash": self.content_hash,
            "user_id": self.user_id,
            "session_id": self.session_id,
            "event_time": self.event_time,
            "ingest_time": self.ingest_time,
        }
        missing = [name for name, value in required.items() if not str(value).strip()]
        if missing:
            raise ValueError(f"missing observation fields: {', '.join(missing)}")
        object.__setattr__(self, "event_time", _iso(self.event_time))
        object.__setattr__(self, "ingest_time", _iso(self.ingest_time))
        object.__setattr__(self, "artifact_refs", _strings(self.artifact_refs))
        object.__setattr__(self, "entity_refs", _strings(self.entity_refs))
        object.__setattr__(self, "input_refs", _strings(self.input_refs))
        object.__setattr__(self, "output_refs", _strings(self.output_refs))
        if not 0.0 <= self.source_reliability <= 1.0:
            raise ValueError("source_reliability must be between 0 and 1")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class BoundaryDecision:
    should_split: bool
    score: float
    reason_codes: tuple[str, ...]
    features: Mapping[str, float]
    forced: bool = False
    schema_version: str = "strict.boundary_decision.v1"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ExecutionFragment:
    fragment_id: str
    user_id: str
    session_id: str
    observation_ids: tuple[str, ...]
    start_time: str
    end_time: str
    task: str
    goal: str
    pre_state: Mapping[str, Any]
    post_state: Mapping[str, Any]
    actions: tuple[str, ...]
    artifact_refs: tuple[str, ...]
    entity_refs: tuple[str, ...]
    apps: tuple[str, ...]
    completion: Completion
    source_episode_ids: tuple[str, ...]
    boundary_before: BoundaryDecision | None = None
    schema_version: str = "strict.execution_fragment.v1"

    def __post_init__(self) -> None:
        if not self.observation_ids:
            raise ValueError("execution fragment requires observations")
        if datetime.fromisoformat(self.start_time) > datetime.fromisoformat(self.end_time):
            raise ValueError("fragment start_time must not exceed end_time")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RepairedExecution:
    execution_id: str
    user_id: str
    session_id: str
    fragment_ids: tuple[str, ...]
    observation_ids: tuple[str, ...]
    start_time: str
    end_time: str
    path_valid: bool
    repair_trace: tuple[Mapping[str, Any], ...]
    schema_version: str = "strict.repaired_execution.v1"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AtomicEvidence:
    evidence_id: str
    user_id: str
    independent_unit_id: str
    evidence_type: str
    memory_family: str
    candidate_kind: str
    claim_subject: str
    claim_slot: str
    claim_value: str
    claim_polarity: str
    condition: Mapping[str, Any]
    observed_time: str
    valid_from: str
    valid_to: str
    source_observation_ids: tuple[str, ...]
    source_fragment_ids: tuple[str, ...]
    directness: str
    source_reliability: float
    extraction_confidence: float
    admission: EvidenceAdmission
    admission_reasons: tuple[str, ...]
    statistics: Mapping[str, Any] = field(default_factory=dict)
    extractor: Mapping[str, Any] = field(default_factory=dict)
    privacy: Mapping[str, Any] = field(default_factory=dict)
    status: str = "active"
    schema_version: str = "strict.atomic_evidence.v1"

    def __post_init__(self) -> None:
        if not self.source_observation_ids or not self.source_fragment_ids:
            raise ValueError("atomic evidence requires observation and fragment lineage")
        if not all(
            (
                self.evidence_id,
                self.user_id,
                self.independent_unit_id,
                self.claim_subject,
                self.claim_slot,
                self.claim_value,
                self.observed_time,
            )
        ):
            raise ValueError("atomic evidence has empty required fields")
        if not 0.0 <= self.source_reliability <= 1.0:
            raise ValueError("source_reliability must be between 0 and 1")
        if not 0.0 <= self.extraction_confidence <= 1.0:
            raise ValueError("extraction_confidence must be between 0 and 1")

    @property
    def eligible_for_candidate(self) -> bool:
        return self.admission in {
            EvidenceAdmission.LONG_TERM_CANDIDATE,
            EvidenceAdmission.CASE_CANDIDATE,
        }

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MemoryCandidate:
    candidate_id: str
    evidence_id: str
    user_id: str
    independent_unit_id: str
    memory_family: str
    candidate_kind: str
    slot_key: str
    semantic_value: str
    polarity: str
    condition: Mapping[str, Any]
    valid_from: str
    valid_to: str
    cardinality: str
    source_module_id: str
    source_observation_ids: tuple[str, ...]
    source_fragment_ids: tuple[str, ...]
    signals: Mapping[str, Any] = field(default_factory=dict)
    status: str = "pending"
    schema_version: str = "strict.memory_candidate.v1"

    def __post_init__(self) -> None:
        if self.cardinality not in {"single", "multi"}:
            raise ValueError("candidate cardinality must be single or multi")
        if not all(
            (
                self.candidate_id,
                self.evidence_id,
                self.user_id,
                self.independent_unit_id,
                self.slot_key,
                self.semantic_value,
                self.source_module_id,
            )
        ):
            raise ValueError("memory candidate has empty required fields")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class StrictImpact:
    impact_id: str
    candidate_id: str
    evidence_id: str
    target_memory_id: str
    action: ImpactAction
    reason_code: str
    before_snapshot: Mapping[str, Any]
    after_snapshot: Mapping[str, Any]
    created_at: str
    schema_version: str = "strict.impact.v1"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class StrictMemory:
    memory_id: str
    user_id: str
    memory_family: str
    candidate_kind: str
    slot_key: str
    semantic_value: str
    condition: Mapping[str, Any]
    scope: Mapping[str, Any]
    cardinality: str
    status: LifecycleStatus
    evidence_ids: tuple[str, ...]
    support_unit_ids: tuple[str, ...]
    oppose_unit_ids: tuple[str, ...]
    applicable_unit_ids: tuple[str, ...]
    valid_from: str
    valid_to: str
    predecessor_memory_ids: tuple[str, ...]
    successor_memory_ids: tuple[str, ...]
    conflict_group_ids: tuple[str, ...]
    confidence: Mapping[str, Any]
    stability: Mapping[str, Any]
    provenance: Mapping[str, Any]
    version: int
    created_at: str
    updated_at: str
    schema_version: str = "strict.memory.v1"

    def __post_init__(self) -> None:
        if self.cardinality not in {"single", "multi"}:
            raise ValueError("memory cardinality must be single or multi")
        if not self.evidence_ids:
            raise ValueError("strict memory requires evidence lineage")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class StrictConflictGroup:
    conflict_group_id: str
    user_id: str
    slot_key: str
    conflict_type: ConflictType
    memory_ids: tuple[str, ...]
    condition_relations: Mapping[str, str]
    condition_partition: Mapping[str, Any]
    timeline: tuple[Mapping[str, Any], ...]
    winner_memory_id: str
    unresolved_reason: str
    status: str
    confidence: Mapping[str, Any]
    updated_at: str
    schema_version: str = "strict.conflict_group.v1"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class StrictLifecycleEvent:
    event_id: str
    memory_id: str
    from_status: LifecycleStatus
    to_status: LifecycleStatus
    reason_code: str
    created_at: str
    schema_version: str = "strict.lifecycle_event.v1"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class StrictForgetRequest:
    request_id: str
    user_id: str
    selectors: Mapping[str, Any]
    reason: str
    dry_run: bool
    candidate_memory_ids: tuple[str, ...]
    status: str
    created_at: str
    completed_at: str = ""
    report: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = "strict.forget_request.v1"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SuppressionRule:
    suppression_id: str
    user_id: str
    slot_key: str
    semantic_value: str
    source_observation_ids: tuple[str, ...]
    reason: str
    active: bool
    created_at: str
    schema_version: str = "strict.suppression_rule.v1"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ReflectionArtifact:
    reflection_id: str
    user_id: str
    reflection_type: str
    claim: str
    memory_ids: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    grounding_verified: bool
    grounding_errors: tuple[str, ...]
    created_at: str
    schema_version: str = "strict.reflection_artifact.v1"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class StageOutput:
    output_id: str
    run_id: str
    stage: str
    module_id: str
    input_ids: tuple[str, ...]
    output_ids: tuple[str, ...]
    payload: Mapping[str, Any]
    created_at: str
    schema_version: str = "strict.stage_output.v1"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
