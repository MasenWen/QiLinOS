from __future__ import annotations

import hashlib
import math
import re
from dataclasses import asdict, dataclass, field, replace
from typing import Iterable, Mapping

from .memory_graph import (
    MemoryGraphNode,
    MemoryKnowledgeGraph,
    MemoryKnowledgeGraphBuilder,
    ObservationRelationSignal,
)


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
class ObservationGraphNode:
    observation_id: str
    episode_id: str
    user_id: str
    source_kind: str
    strength: float = 1.0
    condition_tag_ids: tuple[str, ...] = ()
    object_tag_ids: tuple[str, ...] = ()
    attitude_polarity: str = ""
    source_refs: tuple[str, ...] = ()
    metadata: Mapping[str, object] = field(default_factory=dict)
    schema_version: str = "memory_graph.observation_node.v1"

    def __post_init__(self) -> None:
        if not self.observation_id or not self.episode_id or not self.user_id:
            raise ValueError(
                "observation_id, episode_id and user_id are required"
            )
        if not self.source_kind:
            raise ValueError("source_kind is required")
        if not 0.0 <= float(self.strength) <= 1.0:
            raise ValueError("strength must be in [0, 1]")
        for name in (
            "condition_tag_ids",
            "object_tag_ids",
            "source_refs",
        ):
            object.__setattr__(self, name, _clean(getattr(self, name)))

    @property
    def aliases(self) -> tuple[str, ...]:
        return _clean((self.observation_id, *self.source_refs))

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class EpisodeGraphNode:
    episode_id: str
    user_id: str
    source_kind: str
    observation_ids: tuple[str, ...]
    base_strength: float
    memory_ids: tuple[str, ...] = ()
    condition_tag_ids: tuple[str, ...] = ()
    object_tag_ids: tuple[str, ...] = ()
    metadata: Mapping[str, object] = field(default_factory=dict)
    schema_version: str = "memory_graph.episode_node.v1"

    def __post_init__(self) -> None:
        if not self.episode_id or not self.user_id or not self.source_kind:
            raise ValueError(
                "episode_id, user_id and source_kind are required"
            )
        if not 0.0 <= float(self.base_strength) <= 1.0:
            raise ValueError("base_strength must be in [0, 1]")
        for name in (
            "observation_ids",
            "memory_ids",
            "condition_tag_ids",
            "object_tag_ids",
        ):
            object.__setattr__(self, name, _clean(getattr(self, name)))
        if not self.observation_ids:
            raise ValueError("episode must contain at least one observation")

    @property
    def promoted(self) -> bool:
        return bool(self.memory_ids)

    def to_dict(self) -> dict[str, object]:
        value = asdict(self)
        value["promoted"] = self.promoted
        return value


@dataclass(frozen=True)
class ObservationRelationEvidence:
    evidence_id: str
    source_observation_id: str
    target_observation_id: str
    source_ref: str
    target_ref: str
    relation_type: str
    directed: bool
    association: float
    confidence: float
    proof_strength: float
    independent_unit_id: str
    source_memory_hint: str = ""
    target_memory_hint: str = ""
    metadata: Mapping[str, object] = field(default_factory=dict)
    schema_version: str = "memory_graph.observation_evidence.v1"

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class ObservationGraphEdge:
    edge_id: str
    source_observation_id: str
    target_observation_id: str
    relation_type: str
    directed: bool
    weight: float
    association_strength: float
    support_count: int
    evidence: tuple[ObservationRelationEvidence, ...]
    schema_version: str = "memory_graph.observation_edge.v1"

    def to_dict(self) -> dict[str, object]:
        value = asdict(self)
        value["evidence"] = [item.to_dict() for item in self.evidence]
        return value


@dataclass(frozen=True)
class EpisodeRelationEvidence:
    evidence_id: str
    observation_edge_id: str
    source_observation_id: str
    target_observation_id: str
    proof_strength: float
    association_strength: float
    schema_version: str = "memory_graph.episode_evidence.v1"

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class EpisodeGraphEdge:
    edge_id: str
    source_episode_id: str
    target_episode_id: str
    relation_type: str
    directed: bool
    weight: float
    association_strength: float
    support_count: int
    source_coverage: int
    target_coverage: int
    evidence: tuple[EpisodeRelationEvidence, ...]
    schema_version: str = "memory_graph.episode_edge.v1"

    def to_dict(self) -> dict[str, object]:
        value = asdict(self)
        value["evidence"] = [item.to_dict() for item in self.evidence]
        return value


@dataclass(frozen=True)
class EpisodePromotionState:
    episode_id: str
    status: str
    base_strength: float
    supporting_strength: float
    conflict_strength: float
    relation_reinforcement: float
    conflict_penalty: float
    effective_strength: float
    supporting_episode_ids: tuple[str, ...] = ()
    conflicting_episode_ids: tuple[str, ...] = ()
    schema_version: str = "memory_graph.episode_promotion_state.v1"

    @property
    def promotion_candidate(self) -> bool:
        return self.status == "promotion_candidate"

    def to_dict(self) -> dict[str, object]:
        value = asdict(self)
        value["promotion_candidate"] = self.promotion_candidate
        return value


@dataclass(frozen=True)
class LayeredGraphDiagnostics:
    input_signal_count: int
    observation_edge_count: int
    episode_edge_count: int
    memory_edge_count: int
    internal_episode_relation_count: int
    promoted_episode_count: int
    latent_episode_count: int
    promotion_candidate_count: int
    relation_reinforced_episode_count: int
    below_signal_threshold_count: int
    below_observation_edge_threshold_count: int
    below_episode_edge_threshold_count: int
    unresolved_signal_count: int
    ambiguous_signal_count: int
    cross_user_signal_count: int
    self_relation_count: int
    duplicate_evidence_count: int

    def to_dict(self) -> dict[str, int]:
        return asdict(self)


def _matrix(
    node_ids: Iterable[str],
    edges: Iterable[object],
    *,
    source_name: str,
    target_name: str,
    relation_type: str | None = None,
) -> dict[str, dict[str, float]]:
    selected = _relation_type(relation_type) if relation_type else None
    matrix = {node_id: {} for node_id in node_ids}
    for edge in edges:
        if selected and edge.relation_type != selected:
            continue
        source = getattr(edge, source_name)
        target = getattr(edge, target_name)
        matrix[source][target] = max(
            matrix[source].get(target, 0.0),
            edge.weight,
        )
        if not edge.directed:
            matrix[target][source] = max(
                matrix[target].get(source, 0.0),
                edge.weight,
            )
    return matrix


@dataclass(frozen=True)
class ObservationKnowledgeGraph:
    nodes: tuple[ObservationGraphNode, ...]
    edges: tuple[ObservationGraphEdge, ...]

    def relation_matrix(
        self,
        *,
        relation_type: str | None = None,
    ) -> dict[str, dict[str, float]]:
        return _matrix(
            (node.observation_id for node in self.nodes),
            self.edges,
            source_name="source_observation_id",
            target_name="target_observation_id",
            relation_type=relation_type,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "nodes": [node.to_dict() for node in self.nodes],
            "edges": [edge.to_dict() for edge in self.edges],
            "relation_matrix": self.relation_matrix(),
        }


@dataclass(frozen=True)
class EpisodeKnowledgeGraph:
    nodes: tuple[EpisodeGraphNode, ...]
    edges: tuple[EpisodeGraphEdge, ...]
    internal_relation_counts: Mapping[str, int]
    promotion_states: tuple[EpisodePromotionState, ...] = ()

    def relation_matrix(
        self,
        *,
        relation_type: str | None = None,
    ) -> dict[str, dict[str, float]]:
        return _matrix(
            (node.episode_id for node in self.nodes),
            self.edges,
            source_name="source_episode_id",
            target_name="target_episode_id",
            relation_type=relation_type,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "nodes": [node.to_dict() for node in self.nodes],
            "edges": [edge.to_dict() for edge in self.edges],
            "relation_matrix": self.relation_matrix(),
            "internal_relation_counts": dict(
                self.internal_relation_counts
            ),
            "promotion_states": [
                state.to_dict() for state in self.promotion_states
            ],
        }

    def promotion_state(
        self,
        episode_id: str,
    ) -> EpisodePromotionState:
        for state in self.promotion_states:
            if state.episode_id == episode_id:
                return state
        raise KeyError(f"episode_not_found:{episode_id}")


@dataclass(frozen=True)
class LayeredMemoryKnowledgeGraph:
    observation_graph: ObservationKnowledgeGraph
    episode_graph: EpisodeKnowledgeGraph
    memory_graph: MemoryKnowledgeGraph
    diagnostics: LayeredGraphDiagnostics
    schema_version: str = "memory_graph.layered.v1"

    @property
    def promotion_candidates(self) -> tuple[EpisodePromotionState, ...]:
        return tuple(
            state
            for state in self.episode_graph.promotion_states
            if state.promotion_candidate
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "observation_graph": self.observation_graph.to_dict(),
            "episode_graph": self.episode_graph.to_dict(),
            "memory_graph": self.memory_graph.to_dict(),
            "promotion_candidates": [
                state.to_dict()
                for state in self.promotion_candidates
            ],
            "diagnostics": self.diagnostics.to_dict(),
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True)
class LayeredMemoryGraphConfig:
    minimum_signal_association: float = 0.45
    minimum_observation_edge_weight: float = 0.42
    minimum_episode_edge_weight: float = 0.55
    secondary_evidence_gain: float = 0.35
    memory_strength_threshold: float = 0.82
    relation_reinforcement_gain: float = 0.25
    conflict_penalty_weight: float = 0.20
    supporting_relation_types: tuple[str, ...] = (
        "supports",
        "confirms",
    )
    conflicting_relation_types: tuple[str, ...] = ("conflicts",)
    infer_semantic_relation_type: bool = True

    def __post_init__(self) -> None:
        for name in (
            "minimum_signal_association",
            "minimum_observation_edge_weight",
            "minimum_episode_edge_weight",
            "secondary_evidence_gain",
            "memory_strength_threshold",
            "relation_reinforcement_gain",
            "conflict_penalty_weight",
        ):
            if not 0.0 <= float(getattr(self, name)) <= 1.0:
                raise ValueError(f"{name} must be in [0, 1]")
        object.__setattr__(
            self,
            "supporting_relation_types",
            tuple(
                _relation_type(value)
                for value in self.supporting_relation_types
            ),
        )
        object.__setattr__(
            self,
            "conflicting_relation_types",
            tuple(
                _relation_type(value)
                for value in self.conflicting_relation_types
            ),
        )


class LayeredMemoryKnowledgeGraphBuilder:
    """Build Observation, Episode and promoted Memory relation layers."""

    def __init__(
        self,
        config: LayeredMemoryGraphConfig | None = None,
    ):
        self.config = config or LayeredMemoryGraphConfig()

    def build(
        self,
        observations: Iterable[ObservationGraphNode],
        episodes: Iterable[EpisodeGraphNode],
        memories: Iterable[MemoryGraphNode],
        signals: Iterable[ObservationRelationSignal],
    ) -> LayeredMemoryKnowledgeGraph:
        observation_nodes = tuple(observations)
        episode_nodes = tuple(episodes)
        memory_nodes = tuple(memories)
        signal_values = tuple(signals)
        observation_by_id = self._validate_layers(
            observation_nodes,
            episode_nodes,
            memory_nodes,
        )
        episode_by_id = {
            episode.episode_id: episode for episode in episode_nodes
        }
        observation_graph, counters = self._observation_graph(
            observation_nodes,
            signal_values,
        )
        episode_graph, episode_counters = self._episode_graph(
            observation_graph,
            observation_by_id,
            episode_nodes,
            episode_by_id,
        )
        counters.update(episode_counters)
        promotion_states = self._promotion_states(episode_graph)
        episode_graph = replace(
            episode_graph,
            promotion_states=promotion_states,
        )

        memory_aliases = {
            alias
            for memory in memory_nodes
            for alias in memory.aliases
        }
        memory_signals = []
        for edge in observation_graph.edges:
            for evidence in edge.evidence:
                if (
                    evidence.source_ref not in memory_aliases
                    or evidence.target_ref not in memory_aliases
                ):
                    continue
                memory_signals.append(
                    ObservationRelationSignal(
                        source_ref=evidence.source_ref,
                        target_ref=evidence.target_ref,
                        association=evidence.association,
                        relation_type=edge.relation_type,
                        directed=edge.directed,
                        confidence=evidence.confidence,
                        independent_unit_id=(
                            evidence.independent_unit_id
                        ),
                        source_memory_hint=(
                            evidence.source_memory_hint
                        ),
                        target_memory_hint=(
                            evidence.target_memory_hint
                        ),
                        metadata=evidence.metadata,
                    )
                )
        memory_graph = MemoryKnowledgeGraphBuilder().build(
            memory_nodes,
            memory_signals,
        )

        diagnostics = LayeredGraphDiagnostics(
            input_signal_count=len(signal_values),
            observation_edge_count=len(observation_graph.edges),
            episode_edge_count=len(episode_graph.edges),
            memory_edge_count=len(memory_graph.edges),
            internal_episode_relation_count=sum(
                episode_graph.internal_relation_counts.values()
            ),
            promoted_episode_count=sum(
                episode.promoted for episode in episode_nodes
            ),
            latent_episode_count=sum(
                state.status == "latent"
                for state in promotion_states
            ),
            promotion_candidate_count=sum(
                state.promotion_candidate
                for state in promotion_states
            ),
            relation_reinforced_episode_count=sum(
                state.relation_reinforcement > 0.0
                for state in promotion_states
            ),
            **counters,
        )
        return LayeredMemoryKnowledgeGraph(
            observation_graph=observation_graph,
            episode_graph=episode_graph,
            memory_graph=memory_graph,
            diagnostics=diagnostics,
        )

    @staticmethod
    def _validate_layers(
        observations: tuple[ObservationGraphNode, ...],
        episodes: tuple[EpisodeGraphNode, ...],
        memories: tuple[MemoryGraphNode, ...],
    ) -> dict[str, ObservationGraphNode]:
        observation_by_id = {
            node.observation_id: node for node in observations
        }
        episode_by_id = {node.episode_id: node for node in episodes}
        memory_by_id = {node.memory_id: node for node in memories}
        if len(observation_by_id) != len(observations):
            raise ValueError("observation_id must be unique")
        if len(episode_by_id) != len(episodes):
            raise ValueError("episode_id must be unique")
        if len(memory_by_id) != len(memories):
            raise ValueError("memory_id must be unique")

        for observation in observations:
            episode = episode_by_id.get(observation.episode_id)
            if episode is None:
                raise ValueError(
                    f"episode_not_found:{observation.episode_id}"
                )
            if observation.user_id != episode.user_id:
                raise ValueError("observation and episode users must match")
            if observation.observation_id not in episode.observation_ids:
                raise ValueError(
                    "episode observation_ids must include every observation"
                )
        for episode in episodes:
            for observation_id in episode.observation_ids:
                observation = observation_by_id.get(observation_id)
                if observation is None:
                    raise ValueError(
                        f"observation_not_found:{observation_id}"
                    )
                if observation.episode_id != episode.episode_id:
                    raise ValueError(
                        "observation cannot belong to multiple episodes"
                    )
            for memory_id in episode.memory_ids:
                memory = memory_by_id.get(memory_id)
                if memory is None:
                    raise ValueError(f"memory_not_found:{memory_id}")
                if memory.episode_id != episode.episode_id:
                    raise ValueError(
                        "memory and episode lineage must match"
                    )
        return observation_by_id

    def _observation_graph(
        self,
        nodes: tuple[ObservationGraphNode, ...],
        signals: tuple[ObservationRelationSignal, ...],
    ) -> tuple[ObservationKnowledgeGraph, dict[str, int]]:
        by_id = {node.observation_id: node for node in nodes}
        aliases: dict[str, list[ObservationGraphNode]] = {}
        for node in nodes:
            for alias in node.aliases:
                aliases.setdefault(alias, []).append(node)

        grouped: dict[
            tuple[str, str, str, bool],
            dict[str, ObservationRelationEvidence],
        ] = {}
        counters = {
            "below_signal_threshold_count": 0,
            "below_observation_edge_threshold_count": 0,
            "unresolved_signal_count": 0,
            "ambiguous_signal_count": 0,
            "cross_user_signal_count": 0,
            "self_relation_count": 0,
            "duplicate_evidence_count": 0,
        }
        for signal in signals:
            if (
                signal.association
                < self.config.minimum_signal_association
            ):
                counters["below_signal_threshold_count"] += 1
                continue
            source, source_reason = self._resolve_observation(
                signal.source_ref,
                signal.source_observation_hint,
                aliases,
                by_id,
            )
            target, target_reason = self._resolve_observation(
                signal.target_ref,
                signal.target_observation_hint,
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
            if source.observation_id == target.observation_id:
                counters["self_relation_count"] += 1
                continue

            relation = self._semantic_relation_type(
                signal.relation_type,
                source,
                target,
            )
            source_ref = signal.source_ref
            target_ref = signal.target_ref
            source_memory_hint = signal.source_memory_hint
            target_memory_hint = signal.target_memory_hint
            if not signal.directed and (
                target.observation_id < source.observation_id
            ):
                source, target = target, source
                source_ref, target_ref = target_ref, source_ref
                source_memory_hint, target_memory_hint = (
                    target_memory_hint,
                    source_memory_hint,
                )
            key = (
                source.observation_id,
                target.observation_id,
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
                "observation_relation_unit",
                (
                    f"{unit_refs[0]}|{unit_refs[1]}|"
                    f"{relation}|{signal.directed}"
                ),
            )
            reliability = math.sqrt(
                source.strength * target.strength
            )
            proof = signal.association * (
                0.82
                + 0.10 * signal.confidence
                + 0.08 * reliability
            )
            evidence = ObservationRelationEvidence(
                evidence_id=_stable_id(
                    "ore",
                    (
                        f"{source.observation_id}|"
                        f"{target.observation_id}|{relation}|"
                        f"{signal.directed}|{unit_id}"
                    ),
                ),
                source_observation_id=source.observation_id,
                target_observation_id=target.observation_id,
                source_ref=source_ref,
                target_ref=target_ref,
                relation_type=relation,
                directed=signal.directed,
                association=round(signal.association, 6),
                confidence=round(signal.confidence, 6),
                proof_strength=round(_clip(proof), 6),
                independent_unit_id=unit_id,
                source_memory_hint=source_memory_hint,
                target_memory_hint=target_memory_hint,
                metadata=signal.metadata,
            )
            prior = grouped.setdefault(key, {}).get(unit_id)
            if prior is not None:
                counters["duplicate_evidence_count"] += 1
                if prior.proof_strength >= evidence.proof_strength:
                    continue
            grouped[key][unit_id] = evidence

        edges = []
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
            if weight < self.config.minimum_observation_edge_weight:
                counters[
                    "below_observation_edge_threshold_count"
                ] += 1
                continue
            association = _aggregate(
                (item.association for item in evidence),
                self.config.secondary_evidence_gain,
            )
            edges.append(
                ObservationGraphEdge(
                    edge_id=_stable_id(
                        "oedge",
                        (
                            f"{source_id}|{target_id}|"
                            f"{relation}|{directed}"
                        ),
                    ),
                    source_observation_id=source_id,
                    target_observation_id=target_id,
                    relation_type=relation,
                    directed=directed,
                    weight=round(weight, 6),
                    association_strength=round(association, 6),
                    support_count=len(evidence),
                    evidence=evidence,
                )
            )
        edges.sort(
            key=lambda edge: (
                -edge.weight,
                edge.source_observation_id,
                edge.target_observation_id,
                edge.relation_type,
            )
        )
        return (
            ObservationKnowledgeGraph(nodes=nodes, edges=tuple(edges)),
            counters,
        )

    def _promotion_states(
        self,
        graph: EpisodeKnowledgeGraph,
    ) -> tuple[EpisodePromotionState, ...]:
        by_id = {node.episode_id: node for node in graph.nodes}
        support_by_episode: dict[str, list[tuple[str, float]]] = {
            node.episode_id: [] for node in graph.nodes
        }
        conflict_by_episode: dict[str, list[tuple[str, float]]] = {
            node.episode_id: [] for node in graph.nodes
        }

        for edge in graph.edges:
            affected = self._affected_episode_pairs(edge)
            for source_id, target_id in affected:
                source = by_id[source_id]
                if not source.promoted:
                    continue
                contribution = edge.weight * source.base_strength
                if (
                    edge.relation_type
                    in self.config.supporting_relation_types
                ):
                    support_by_episode[target_id].append(
                        (source_id, contribution)
                    )
                elif (
                    edge.relation_type
                    in self.config.conflicting_relation_types
                ):
                    conflict_by_episode[target_id].append(
                        (source_id, contribution)
                    )

        states = []
        for node in graph.nodes:
            support_values = support_by_episode[node.episode_id]
            conflict_values = conflict_by_episode[node.episode_id]
            supporting_strength = _aggregate(
                (value for _, value in support_values),
                self.config.secondary_evidence_gain,
            )
            conflict_strength = _aggregate(
                (value for _, value in conflict_values),
                self.config.secondary_evidence_gain,
            )
            reinforcement = (
                (1.0 - node.base_strength)
                * self.config.relation_reinforcement_gain
                * supporting_strength
            )
            penalty = (
                node.base_strength
                * self.config.conflict_penalty_weight
                * conflict_strength
            )
            effective = _clip(
                node.base_strength + reinforcement - penalty
            )
            if node.promoted:
                status = "existing_memory"
            elif effective >= self.config.memory_strength_threshold:
                status = "promotion_candidate"
            else:
                status = "latent"
            states.append(
                EpisodePromotionState(
                    episode_id=node.episode_id,
                    status=status,
                    base_strength=round(node.base_strength, 6),
                    supporting_strength=round(
                        supporting_strength,
                        6,
                    ),
                    conflict_strength=round(conflict_strength, 6),
                    relation_reinforcement=round(reinforcement, 6),
                    conflict_penalty=round(penalty, 6),
                    effective_strength=round(effective, 6),
                    supporting_episode_ids=_clean(
                        source_id for source_id, _ in support_values
                    ),
                    conflicting_episode_ids=_clean(
                        source_id for source_id, _ in conflict_values
                    ),
                )
            )
        return tuple(states)

    @staticmethod
    def _affected_episode_pairs(
        edge: EpisodeGraphEdge,
    ) -> tuple[tuple[str, str], ...]:
        if edge.directed:
            return (
                (
                    edge.source_episode_id,
                    edge.target_episode_id,
                ),
            )
        return (
            (
                edge.source_episode_id,
                edge.target_episode_id,
            ),
            (
                edge.target_episode_id,
                edge.source_episode_id,
            ),
        )

    def _episode_graph(
        self,
        observation_graph: ObservationKnowledgeGraph,
        observation_by_id: Mapping[str, ObservationGraphNode],
        nodes: tuple[EpisodeGraphNode, ...],
        episode_by_id: Mapping[str, EpisodeGraphNode],
    ) -> tuple[EpisodeKnowledgeGraph, dict[str, int]]:
        grouped: dict[
            tuple[str, str, str, bool],
            list[EpisodeRelationEvidence],
        ] = {}
        internal_counts = {node.episode_id: 0 for node in nodes}
        below_threshold = 0

        for edge in observation_graph.edges:
            source_observation = observation_by_id[
                edge.source_observation_id
            ]
            target_observation = observation_by_id[
                edge.target_observation_id
            ]
            source_episode_id = source_observation.episode_id
            target_episode_id = target_observation.episode_id
            if source_episode_id == target_episode_id:
                internal_counts[source_episode_id] += 1
                continue

            source_episode = episode_by_id[source_episode_id]
            target_episode = episode_by_id[target_episode_id]
            source_observation_id = edge.source_observation_id
            target_observation_id = edge.target_observation_id
            if not edge.directed and (
                target_episode_id < source_episode_id
            ):
                source_episode_id, target_episode_id = (
                    target_episode_id,
                    source_episode_id,
                )
                source_episode, target_episode = (
                    target_episode,
                    source_episode,
                )
                source_observation_id, target_observation_id = (
                    target_observation_id,
                    source_observation_id,
                )
            reliability = math.sqrt(
                source_episode.base_strength
                * target_episode.base_strength
            )
            proof = edge.weight * (0.85 + 0.15 * reliability)
            key = (
                source_episode_id,
                target_episode_id,
                edge.relation_type,
                edge.directed,
            )
            grouped.setdefault(key, []).append(
                EpisodeRelationEvidence(
                    evidence_id=_stable_id(
                        "epe",
                        (
                            f"{source_episode_id}|"
                            f"{target_episode_id}|{edge.edge_id}"
                        ),
                    ),
                    observation_edge_id=edge.edge_id,
                    source_observation_id=source_observation_id,
                    target_observation_id=target_observation_id,
                    proof_strength=round(_clip(proof), 6),
                    association_strength=edge.association_strength,
                )
            )

        edges = []
        for key, evidence_values in grouped.items():
            source_id, target_id, relation, directed = key
            evidence = tuple(
                sorted(
                    evidence_values,
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
            if weight < self.config.minimum_episode_edge_weight:
                below_threshold += 1
                continue
            association = _aggregate(
                (item.association_strength for item in evidence),
                self.config.secondary_evidence_gain,
            )
            edges.append(
                EpisodeGraphEdge(
                    edge_id=_stable_id(
                        "epedge",
                        (
                            f"{source_id}|{target_id}|"
                            f"{relation}|{directed}"
                        ),
                    ),
                    source_episode_id=source_id,
                    target_episode_id=target_id,
                    relation_type=relation,
                    directed=directed,
                    weight=round(weight, 6),
                    association_strength=round(association, 6),
                    support_count=len(evidence),
                    source_coverage=len(
                        {
                            item.source_observation_id
                            for item in evidence
                        }
                    ),
                    target_coverage=len(
                        {
                            item.target_observation_id
                            for item in evidence
                        }
                    ),
                    evidence=evidence,
                )
            )
        edges.sort(
            key=lambda edge: (
                -edge.weight,
                edge.source_episode_id,
                edge.target_episode_id,
                edge.relation_type,
            )
        )
        return (
            EpisodeKnowledgeGraph(
                nodes=nodes,
                edges=tuple(edges),
                internal_relation_counts=internal_counts,
            ),
            {
                "below_episode_edge_threshold_count": (
                    below_threshold
                )
            },
        )

    @staticmethod
    def _resolve_observation(
        reference: str,
        hint: str,
        aliases: Mapping[str, list[ObservationGraphNode]],
        by_id: Mapping[str, ObservationGraphNode],
    ) -> tuple[ObservationGraphNode | None, str]:
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
        source: ObservationGraphNode,
        target: ObservationGraphNode,
    ) -> str:
        if (
            not self.config.infer_semantic_relation_type
            or relation != "related"
        ):
            return relation
        shared_objects = bool(
            set(source.object_tag_ids) & set(target.object_tag_ids)
        )
        compatible_conditions = bool(
            not source.condition_tag_ids
            or not target.condition_tag_ids
            or set(source.condition_tag_ids)
            & set(target.condition_tag_ids)
        )
        if not shared_objects or not compatible_conditions:
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
    "EpisodeGraphEdge",
    "EpisodeGraphNode",
    "EpisodeKnowledgeGraph",
    "EpisodePromotionState",
    "LayeredGraphDiagnostics",
    "LayeredMemoryGraphConfig",
    "LayeredMemoryKnowledgeGraph",
    "LayeredMemoryKnowledgeGraphBuilder",
    "ObservationGraphEdge",
    "ObservationGraphNode",
    "ObservationKnowledgeGraph",
    "ObservationRelationEvidence",
]
