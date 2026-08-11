from __future__ import annotations

import hashlib
import math
import re
from dataclasses import asdict, dataclass, field
from typing import Iterable, Mapping

from .preference_episode import PreferenceEpisodeMemory


def _stable_id(prefix: str, value: str) -> str:
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:24]
    return f"{prefix}_{digest}"


def _clip(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _clean(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(value for value in values if value))


def _aggregate(values: Iterable[float], gain: float) -> float:
    ordered = sorted((_clip(value) for value in values), reverse=True)
    if not ordered:
        return 0.0
    result = ordered[0]
    for value in ordered[1:]:
        result += (1.0 - result) * gain * value
    return _clip(result)


def _relation_type(value: str) -> str:
    normalized = value.strip().casefold().replace("-", "_").replace(" ", "_")
    if not re.fullmatch(r"[a-z][a-z0-9_]*", normalized):
        raise ValueError("relation_type must be a non-empty identifier")
    return normalized


@dataclass(frozen=True)
class MemoryGraphNode:
    memory_id: str
    episode_id: str
    user_id: str
    source_kind: str
    strength: float
    condition_tag_ids: tuple[str, ...] = ()
    object_tag_ids: tuple[str, ...] = ()
    attitude_polarity: str = ""
    source_observation_ids: tuple[str, ...] = ()
    source_event_ids: tuple[str, ...] = ()
    source_memory_ids: tuple[str, ...] = ()
    observed_time: str = ""
    metadata: Mapping[str, object] = field(default_factory=dict)
    schema_version: str = "memory_graph.node.v1"

    def __post_init__(self) -> None:
        if not self.memory_id or not self.episode_id or not self.user_id:
            raise ValueError("memory_id, episode_id and user_id are required")
        if not self.source_kind:
            raise ValueError("source_kind is required")
        if not 0.0 <= float(self.strength) <= 1.0:
            raise ValueError("strength must be in [0, 1]")
        for name in (
            "condition_tag_ids",
            "object_tag_ids",
            "source_observation_ids",
            "source_event_ids",
            "source_memory_ids",
        ):
            object.__setattr__(self, name, _clean(getattr(self, name)))

    @property
    def aliases(self) -> tuple[str, ...]:
        return _clean(
            (
                self.memory_id,
                *self.source_observation_ids,
                *self.source_event_ids,
                *self.source_memory_ids,
            )
        )

    @classmethod
    def from_preference_memory(
        cls,
        memory: PreferenceEpisodeMemory,
        *,
        source_kind: str = "observation",
        observed_time: str = "",
        metadata: Mapping[str, object] | None = None,
    ) -> MemoryGraphNode:
        return cls(
            memory_id=memory.memory_id,
            episode_id=memory.episode_id,
            user_id=memory.user_id,
            source_kind=source_kind,
            strength=memory.strength,
            condition_tag_ids=(memory.condition_tag_id,),
            object_tag_ids=(memory.object_tag_id,),
            attitude_polarity=memory.attitude_polarity,
            source_observation_ids=memory.source_observation_ids,
            source_event_ids=memory.source_event_ids,
            source_memory_ids=memory.source_memory_ids,
            observed_time=observed_time,
            metadata=metadata or {},
        )

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class ObservationRelationSignal:
    source_ref: str
    target_ref: str
    association: float
    relation_type: str = "related"
    directed: bool = False
    confidence: float = 1.0
    independent_unit_id: str = ""
    source_observation_hint: str = ""
    target_observation_hint: str = ""
    source_memory_hint: str = ""
    target_memory_hint: str = ""
    metadata: Mapping[str, object] = field(default_factory=dict)
    schema_version: str = "memory_graph.relation_signal.v1"

    def __post_init__(self) -> None:
        if not self.source_ref or not self.target_ref:
            raise ValueError("source_ref and target_ref are required")
        if not 0.0 <= float(self.association) <= 1.0:
            raise ValueError("association must be in [0, 1]")
        if not 0.0 <= float(self.confidence) <= 1.0:
            raise ValueError("confidence must be in [0, 1]")
        object.__setattr__(
            self,
            "relation_type",
            _relation_type(self.relation_type),
        )


@dataclass(frozen=True)
class MemoryRelationEvidence:
    evidence_id: str
    source_memory_id: str
    target_memory_id: str
    source_ref: str
    target_ref: str
    relation_type: str
    directed: bool
    association: float
    confidence: float
    proof_strength: float
    independent_unit_id: str
    metadata: Mapping[str, object] = field(default_factory=dict)
    schema_version: str = "memory_graph.relation_evidence.v1"

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class MemoryGraphEdge:
    edge_id: str
    source_memory_id: str
    target_memory_id: str
    relation_type: str
    directed: bool
    weight: float
    association_strength: float
    node_reliability: float
    support_count: int
    evidence: tuple[MemoryRelationEvidence, ...]
    schema_version: str = "memory_graph.edge.v1"

    def to_dict(self) -> dict[str, object]:
        value = asdict(self)
        value["evidence"] = [item.to_dict() for item in self.evidence]
        return value


@dataclass(frozen=True)
class MemoryGraphDiagnostics:
    input_signal_count: int
    admitted_evidence_count: int
    edge_count: int
    below_signal_threshold_count: int
    unresolved_signal_count: int
    ambiguous_signal_count: int
    cross_user_signal_count: int
    self_relation_count: int
    duplicate_evidence_count: int
    below_edge_threshold_count: int

    def to_dict(self) -> dict[str, int]:
        return asdict(self)


@dataclass(frozen=True)
class MemoryKnowledgeGraph:
    nodes: tuple[MemoryGraphNode, ...]
    edges: tuple[MemoryGraphEdge, ...]
    diagnostics: MemoryGraphDiagnostics
    schema_version: str = "memory_graph.v1"

    def relation_matrix(
        self,
        *,
        relation_type: str | None = None,
    ) -> dict[str, dict[str, float]]:
        selected_type = (
            _relation_type(relation_type) if relation_type else None
        )
        matrix = {node.memory_id: {} for node in self.nodes}
        for edge in self.edges:
            if selected_type and edge.relation_type != selected_type:
                continue
            current = matrix[edge.source_memory_id].get(
                edge.target_memory_id,
                0.0,
            )
            matrix[edge.source_memory_id][edge.target_memory_id] = max(
                current,
                edge.weight,
            )
            if not edge.directed:
                reverse = matrix[edge.target_memory_id].get(
                    edge.source_memory_id,
                    0.0,
                )
                matrix[edge.target_memory_id][edge.source_memory_id] = max(
                    reverse,
                    edge.weight,
                )
        return matrix

    def neighbors(
        self,
        memory_id: str,
        *,
        direction: str = "both",
    ) -> tuple[MemoryGraphEdge, ...]:
        if memory_id not in {node.memory_id for node in self.nodes}:
            raise KeyError(f"memory_not_found:{memory_id}")
        if direction not in {"both", "incoming", "outgoing"}:
            raise ValueError(
                "direction must be both, incoming or outgoing"
            )
        return tuple(
            edge
            for edge in self.edges
            if (
                not edge.directed
                and memory_id
                in {
                    edge.source_memory_id,
                    edge.target_memory_id,
                }
            )
            or (
                edge.directed
                and (
                    (
                        direction in {"both", "outgoing"}
                        and edge.source_memory_id == memory_id
                    )
                    or (
                        direction in {"both", "incoming"}
                        and edge.target_memory_id == memory_id
                    )
                )
            )
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "nodes": [node.to_dict() for node in self.nodes],
            "edges": [edge.to_dict() for edge in self.edges],
            "relation_matrix": self.relation_matrix(),
            "diagnostics": self.diagnostics.to_dict(),
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True)
class MemoryGraphConfig:
    minimum_signal_association: float = 0.45
    minimum_edge_weight: float = 0.55
    secondary_evidence_gain: float = 0.35
    infer_semantic_relation_type: bool = True

    def __post_init__(self) -> None:
        for name in (
            "minimum_signal_association",
            "minimum_edge_weight",
            "secondary_evidence_gain",
        ):
            if not 0.0 <= float(getattr(self, name)) <= 1.0:
                raise ValueError(f"{name} must be in [0, 1]")


class MemoryKnowledgeGraphBuilder:
    """Aggregate source-level relation evidence into a sparse memory graph."""

    def __init__(self, config: MemoryGraphConfig | None = None):
        self.config = config or MemoryGraphConfig()

    def build(
        self,
        memories: Iterable[MemoryGraphNode],
        signals: Iterable[ObservationRelationSignal],
    ) -> MemoryKnowledgeGraph:
        nodes = tuple(memories)
        by_id = {node.memory_id: node for node in nodes}
        if len(by_id) != len(nodes):
            raise ValueError("memory_id must be unique")

        aliases: dict[str, list[MemoryGraphNode]] = {}
        for node in nodes:
            for alias in node.aliases:
                aliases.setdefault(alias, []).append(node)

        signal_values = tuple(signals)
        grouped: dict[
            tuple[str, str, str, bool],
            dict[str, MemoryRelationEvidence],
        ] = {}
        counters = {
            "below_signal_threshold_count": 0,
            "unresolved_signal_count": 0,
            "ambiguous_signal_count": 0,
            "cross_user_signal_count": 0,
            "self_relation_count": 0,
            "duplicate_evidence_count": 0,
            "below_edge_threshold_count": 0,
        }

        for signal in signal_values:
            if (
                signal.association
                < self.config.minimum_signal_association
            ):
                counters["below_signal_threshold_count"] += 1
                continue

            source, source_reason = self._resolve(
                signal.source_ref,
                signal.source_memory_hint,
                aliases,
                by_id,
            )
            target, target_reason = self._resolve(
                signal.target_ref,
                signal.target_memory_hint,
                aliases,
                by_id,
            )
            if source is None or target is None:
                if "ambiguous" in {source_reason, target_reason}:
                    counters["ambiguous_signal_count"] += 1
                else:
                    counters["unresolved_signal_count"] += 1
                continue
            if source.user_id != target.user_id:
                counters["cross_user_signal_count"] += 1
                continue
            if source.memory_id == target.memory_id:
                counters["self_relation_count"] += 1
                continue

            relation = self._semantic_relation_type(
                signal.relation_type,
                source,
                target,
            )
            source_ref = signal.source_ref
            target_ref = signal.target_ref
            if not signal.directed and (
                target.memory_id < source.memory_id
            ):
                source, target = target, source
                source_ref, target_ref = target_ref, source_ref
            key = (
                source.memory_id,
                target.memory_id,
                relation,
                signal.directed,
            )
            unit_refs = (
                (source_ref, target_ref)
                if signal.directed
                else tuple(
                    sorted((source_ref, target_ref))
                )
            )
            unit_id = signal.independent_unit_id or _stable_id(
                "relation_unit",
                (
                    f"{unit_refs[0]}|{unit_refs[1]}|"
                    f"{relation}|{signal.directed}"
                ),
            )
            node_reliability = math.sqrt(
                source.strength * target.strength
            )
            proof_strength = signal.association * (
                0.80
                + 0.12 * signal.confidence
                + 0.08 * node_reliability
            )
            evidence = MemoryRelationEvidence(
                evidence_id=_stable_id(
                    "mre",
                    (
                        f"{source.memory_id}|{target.memory_id}|"
                        f"{relation}|{signal.directed}|{unit_id}"
                    ),
                ),
                source_memory_id=source.memory_id,
                target_memory_id=target.memory_id,
                source_ref=source_ref,
                target_ref=target_ref,
                relation_type=relation,
                directed=signal.directed,
                association=round(signal.association, 6),
                confidence=round(signal.confidence, 6),
                proof_strength=round(_clip(proof_strength), 6),
                independent_unit_id=unit_id,
                metadata=signal.metadata,
            )
            prior = grouped.setdefault(key, {}).get(unit_id)
            if prior is not None:
                counters["duplicate_evidence_count"] += 1
                if prior.proof_strength >= evidence.proof_strength:
                    continue
            grouped[key][unit_id] = evidence

        edges = []
        admitted_evidence_count = 0
        for key, by_unit in grouped.items():
            source_id, target_id, relation, directed = key
            evidence = tuple(
                sorted(
                    by_unit.values(),
                    key=lambda item: (
                        -item.proof_strength,
                        item.evidence_id,
                    ),
                )
            )
            weight = _aggregate(
                (item.proof_strength for item in evidence),
                self.config.secondary_evidence_gain,
            )
            if weight < self.config.minimum_edge_weight:
                counters["below_edge_threshold_count"] += 1
                continue
            association = _aggregate(
                (item.association for item in evidence),
                self.config.secondary_evidence_gain,
            )
            reliability = math.sqrt(
                by_id[source_id].strength * by_id[target_id].strength
            )
            admitted_evidence_count += len(evidence)
            edges.append(
                MemoryGraphEdge(
                    edge_id=_stable_id(
                        "medge",
                        (
                            f"{source_id}|{target_id}|"
                            f"{relation}|{directed}"
                        ),
                    ),
                    source_memory_id=source_id,
                    target_memory_id=target_id,
                    relation_type=relation,
                    directed=directed,
                    weight=round(weight, 6),
                    association_strength=round(association, 6),
                    node_reliability=round(reliability, 6),
                    support_count=len(evidence),
                    evidence=evidence,
                )
            )
        edges.sort(
            key=lambda edge: (
                -edge.weight,
                edge.source_memory_id,
                edge.target_memory_id,
                edge.relation_type,
            )
        )

        diagnostics = MemoryGraphDiagnostics(
            input_signal_count=len(signal_values),
            admitted_evidence_count=admitted_evidence_count,
            edge_count=len(edges),
            **counters,
        )
        return MemoryKnowledgeGraph(
            nodes=nodes,
            edges=tuple(edges),
            diagnostics=diagnostics,
        )

    @staticmethod
    def _resolve(
        reference: str,
        hint: str,
        aliases: Mapping[str, list[MemoryGraphNode]],
        by_id: Mapping[str, MemoryGraphNode],
    ) -> tuple[MemoryGraphNode | None, str]:
        candidates = aliases.get(reference, [])
        if hint:
            hinted = by_id.get(hint)
            if hinted is None or hinted not in candidates:
                return None, "unresolved"
            return hinted, "resolved"
        if len(candidates) == 1:
            return candidates[0], "resolved"
        if not candidates:
            return None, "unresolved"
        return None, "ambiguous"

    def _semantic_relation_type(
        self,
        relation: str,
        source: MemoryGraphNode,
        target: MemoryGraphNode,
    ) -> str:
        if (
            not self.config.infer_semantic_relation_type
            or relation != "related"
        ):
            return relation
        shared_objects = bool(
            set(source.object_tag_ids) & set(target.object_tag_ids)
        )
        condition_compatible = bool(
            not source.condition_tag_ids
            or not target.condition_tag_ids
            or set(source.condition_tag_ids)
            & set(target.condition_tag_ids)
        )
        if not shared_objects or not condition_compatible:
            return relation
        polarities = {
            source.attitude_polarity,
            target.attitude_polarity,
        }
        if polarities == {"support", "oppose"}:
            return "conflicts"
        if (
            source.attitude_polarity
            and source.attitude_polarity
            == target.attitude_polarity
        ):
            return "supports"
        return relation


__all__ = [
    "MemoryGraphConfig",
    "MemoryGraphDiagnostics",
    "MemoryGraphEdge",
    "MemoryGraphNode",
    "MemoryKnowledgeGraph",
    "MemoryKnowledgeGraphBuilder",
    "MemoryRelationEvidence",
    "ObservationRelationSignal",
]
