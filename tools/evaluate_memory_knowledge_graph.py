from __future__ import annotations

import argparse
import json
from pathlib import Path
from time import perf_counter
from typing import Any

from src.memory_engine.layered_memory_graph import (
    EpisodeGraphNode,
    LayeredMemoryKnowledgeGraph,
    LayeredMemoryKnowledgeGraphBuilder,
    ObservationGraphNode,
)
from src.memory_engine.memory_graph import (
    MemoryGraphNode,
    ObservationRelationSignal,
)
from src.memory_engine.preference_episode import PreferenceEpisodeMemory


DEFAULT_PREFERENCE_INPUT = Path(
    "outputs/remote_preference_frame_audit/"
    "kylin_os_agent_preference_episodes_v1.json"
)
DEFAULT_OUTPUT = Path(
    "outputs/memory_knowledge_graph/fixed_mixed_layered_audit.json"
)


def _preference_memories(path: Path) -> dict[str, PreferenceEpisodeMemory]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    memories = {}
    tuple_fields = (
        "source_observation_ids",
        "source_event_ids",
        "source_memory_ids",
    )
    for episode in payload["episodes"]:
        for raw in episode.get("memories") or ():
            value = dict(raw)
            for name in tuple_fields:
                value[name] = tuple(value.get(name) or ())
            memory = PreferenceEpisodeMemory(**value)
            memories[memory.memory_id] = memory
    return memories


def _log_node(
    memory_id: str,
    *,
    episode_id: str,
    condition: str,
    object_id: str,
    event_id: str,
    label: str,
    source_excerpt: str,
    strength: float,
) -> MemoryGraphNode:
    return MemoryGraphNode(
        memory_id=memory_id,
        episode_id=episode_id,
        user_id="os-agent-v31-user",
        source_kind="log_event",
        strength=strength,
        condition_tag_ids=(condition,),
        object_tag_ids=(object_id,),
        source_event_ids=(event_id,),
        metadata={
            "label": label,
            "source_excerpt": source_excerpt,
        },
    )


def _text_node(
    memory_id: str,
    *,
    episode_id: str,
    condition: str,
    object_id: str,
    event_id: str,
    label: str,
    source_excerpt: str,
    strength: float,
) -> MemoryGraphNode:
    return MemoryGraphNode(
        memory_id=memory_id,
        episode_id=episode_id,
        user_id="os-agent-v31-user",
        source_kind="observation",
        strength=strength,
        condition_tag_ids=(condition,),
        object_tag_ids=(object_id,),
        attitude_polarity="support",
        source_observation_ids=(f"observation:{event_id}",),
        source_event_ids=(event_id,),
        metadata={
            "label": label,
            "source_excerpt": source_excerpt,
        },
    )


def mixed_fixture(
    preference_input: Path,
) -> tuple[
    tuple[MemoryGraphNode, ...],
    tuple[ObservationRelationSignal, ...],
]:
    memories = _preference_memories(preference_input)
    selected_ids = (
        "epmem_f2e9b4f4cd5aa04606677323",
        "epmem_e068b92b67fcd0eca65ab0ff",
        "epmem_fc91eada9375097ef9d08397",
        "epmem_607dd8dcc96c090978abca3b",
        "epmem_d6cb6a6a9d17add5fb28205a",
    )
    missing = set(selected_ids) - memories.keys()
    if missing:
        raise ValueError(f"fixture_memories_missing:{sorted(missing)}")

    nodes = []
    for memory_id in selected_ids:
        memory = memories[memory_id]
        nodes.append(
            MemoryGraphNode.from_preference_memory(
                memory,
                metadata={
                    "label": (
                        f"{memory.condition_name or memory.condition_tag_id}"
                        f" / {memory.object_name or memory.object_tag_id}"
                    ),
                    "condition": memory.condition_tag_id,
                    "object": memory.object_tag_id,
                },
            )
        )

    nodes.extend(
        (
            _text_node(
                "memory-text-codex-code-explanation",
                episode_id="episode-text-codex-preference",
                condition="condition:task:code_explanation",
                object_id="object:app:chatgpt_codex",
                event_id="text-codex-rule",
                label="代码解释优先使用 ChatGPT Codex",
                source_excerpt=(
                    "以后统一用 ChatGPT Codex 处理代码解释，"
                    "普通聊天不需要。"
                ),
                strength=0.91,
            ),
            _log_node(
                "memory-log-time-resync-request",
                episode_id="episode-log-time-request",
                condition="condition:service:w32time",
                object_id="object:time_resync_request",
                event_id="log-w32time-resync-request",
                label="W32time 收到重新同步请求",
                source_excerpt=(
                    "W32time Service received notification to rediscover "
                    "its time sources and/or resynchronize time."
                ),
                strength=0.88,
            ),
            _log_node(
                "memory-log-time-source-sync",
                episode_id="episode-log-time-source-sync",
                condition="condition:service:w32time",
                object_id="object:time_source_sync",
                event_id="log-w32time-source-sync",
                label="W32time 与 time.windows.com 同步",
                source_excerpt=(
                    "The time service is now synchronizing the system "
                    "time with the reference time source "
                    "time.windows.com,0x9."
                ),
                strength=0.93,
            ),
            _log_node(
                "memory-log-system-time-updated",
                episode_id="episode-log-time-updated",
                condition="condition:service:w32time",
                object_id="object:system_time_update",
                event_id="log-w32time-system-time-updated",
                label="W32time 已设置系统时间",
                source_excerpt=(
                    "W32time service has set the system time to "
                    "2026-07-26T06:48:32.986Z(UTC)."
                ),
                strength=0.96,
            ),
            _log_node(
                "memory-log-dell-power-manager-start",
                episode_id="episode-log-dell-process",
                condition="condition:app:dell_power_manager",
                object_id="object:process_creation",
                event_id="log-dell-power-manager-process",
                label="Dell Power Manager 创建进程",
                source_excerpt=(
                    "已经为程序包 DellInc.DellPowerManager_3.14.40.0_x64 "
                    "中的应用程序 DellPowerManager 创建进程。"
                ),
                strength=0.83,
            ),
            _log_node(
                "memory-log-codex-start",
                episode_id="episode-log-codex-process",
                condition="condition:app:chatgpt_codex",
                object_id="object:process_creation",
                event_id="log-codex-process",
                label="OpenAI Codex 创建进程",
                source_excerpt=(
                    "已经为程序包 OpenAI.Codex_26.721.4979.0_x64 "
                    "中的应用程序 OpenAI.Codex 创建进程。"
                ),
                strength=0.86,
            ),
        )
    )

    sales_total = nodes[0]
    sales_repeat = nodes[1]
    sales_line = nodes[2]
    ambiguous_workflow = nodes[3]
    student_fill = nodes[4]
    signals = (
        ObservationRelationSignal(
            sales_total.source_event_ids[0],
            sales_repeat.source_event_ids[0],
            0.90,
            independent_unit_id="salesrep-total-growth",
            metadata={
                "basis": "same file, action family and preference direction",
            },
        ),
        ObservationRelationSignal(
            sales_total.source_event_ids[1],
            sales_repeat.source_event_ids[0],
            0.86,
            independent_unit_id="salesrep-total-growth",
            metadata={
                "basis": "duplicate frame from the same relation unit",
            },
        ),
        ObservationRelationSignal(
            sales_total.source_event_ids[0],
            sales_line.source_event_ids[0],
            0.76,
            metadata={
                "basis": "same file and monthly chart workflow",
            },
        ),
        ObservationRelationSignal(
            sales_repeat.source_event_ids[0],
            sales_line.source_event_ids[0],
            0.69,
            metadata={
                "basis": "same file with overlapping chart objective",
            },
        ),
        ObservationRelationSignal(
            sales_total.source_event_ids[0],
            ambiguous_workflow.source_event_ids[0],
            0.61,
            metadata={
                "basis": "same file but vague prior-workflow object",
            },
        ),
        ObservationRelationSignal(
            sales_total.source_event_ids[0],
            student_fill.source_event_ids[0],
            0.25,
            metadata={
                "basis": "spreadsheet surface only; task semantics differ",
            },
        ),
        ObservationRelationSignal(
            "log-w32time-resync-request",
            "log-w32time-source-sync",
            0.91,
            relation_type="precedes",
            directed=True,
            metadata={"basis": "explicit service event sequence"},
        ),
        ObservationRelationSignal(
            "log-w32time-source-sync",
            "log-w32time-system-time-updated",
            0.94,
            relation_type="precedes",
            directed=True,
            metadata={"basis": "explicit service event sequence"},
        ),
        ObservationRelationSignal(
            "log-w32time-resync-request",
            "log-w32time-system-time-updated",
            0.73,
            relation_type="causes",
            directed=True,
            metadata={"basis": "request-to-result relation"},
        ),
        ObservationRelationSignal(
            "log-codex-process",
            "text-codex-rule",
            0.66,
            relation_type="activates",
            directed=True,
            metadata={
                "basis": (
                    "application launch can activate an app-scoped "
                    "preference but does not prove the preference"
                ),
            },
        ),
        ObservationRelationSignal(
            "log-dell-power-manager-process",
            "log-codex-process",
            0.18,
            metadata={"basis": "both are process creation events only"},
        ),
        ObservationRelationSignal(
            "log-w32time-system-time-updated",
            "log-dell-power-manager-process",
            0.08,
            metadata={"basis": "temporal proximity without semantic link"},
        ),
    )
    return tuple(nodes), signals


def layered_fixture(
    preference_input: Path,
) -> tuple[
    tuple[ObservationGraphNode, ...],
    tuple[EpisodeGraphNode, ...],
    tuple[MemoryGraphNode, ...],
    tuple[ObservationRelationSignal, ...],
]:
    memories, base_signals = mixed_fixture(preference_input)
    observations: list[ObservationGraphNode] = []
    episode_parts: dict[str, dict[str, Any]] = {}

    for memory in memories:
        source_refs = (
            memory.source_event_ids
            or memory.source_observation_ids
            or (memory.memory_id,)
        )
        observation_ids = []
        for index, source_ref in enumerate(source_refs):
            observation_id = (
                f"graph-observation:{memory.memory_id}:{index}"
            )
            aliases = [source_ref]
            if index < len(memory.source_observation_ids):
                aliases.append(memory.source_observation_ids[index])
            if index == 0:
                aliases.extend((memory.memory_id, *memory.source_memory_ids))
            observations.append(
                ObservationGraphNode(
                    observation_id=observation_id,
                    episode_id=memory.episode_id,
                    user_id=memory.user_id,
                    source_kind=memory.source_kind,
                    strength=memory.strength,
                    condition_tag_ids=memory.condition_tag_ids,
                    object_tag_ids=memory.object_tag_ids,
                    attitude_polarity=memory.attitude_polarity,
                    source_refs=tuple(aliases),
                    metadata={
                        "label": memory.metadata.get(
                            "label",
                            memory.memory_id,
                        ),
                        "source_ref": source_ref,
                    },
                )
            )
            observation_ids.append(observation_id)

        part = episode_parts.setdefault(
            memory.episode_id,
            {
                "user_id": memory.user_id,
                "source_kinds": [],
                "observation_ids": [],
                "memory_ids": [],
                "strengths": [],
                "condition_tag_ids": [],
                "object_tag_ids": [],
            },
        )
        part["source_kinds"].append(memory.source_kind)
        part["observation_ids"].extend(observation_ids)
        part["memory_ids"].append(memory.memory_id)
        part["strengths"].append(memory.strength)
        part["condition_tag_ids"].extend(memory.condition_tag_ids)
        part["object_tag_ids"].extend(memory.object_tag_ids)

    episodes = []
    for episode_id, part in episode_parts.items():
        source_kinds = tuple(dict.fromkeys(part["source_kinds"]))
        episodes.append(
            EpisodeGraphNode(
                episode_id=episode_id,
                user_id=part["user_id"],
                source_kind=(
                    source_kinds[0]
                    if len(source_kinds) == 1
                    else "mixed"
                ),
                observation_ids=tuple(part["observation_ids"]),
                base_strength=max(part["strengths"]),
                memory_ids=tuple(part["memory_ids"]),
                condition_tag_ids=tuple(
                    dict.fromkeys(part["condition_tag_ids"])
                ),
                object_tag_ids=tuple(
                    dict.fromkeys(part["object_tag_ids"])
                ),
            )
        )

    sales_memory = memories[0]
    weak_specs = (
        {
            "observation_id": "observation:latent:salesrep-confirmed",
            "episode_id": "episode:latent:salesrep-confirmed",
            "source_ref": "event:latent:salesrep-confirmed",
            "source_kind": "observation",
            "strength": 0.79,
            "condition_tag_ids": sales_memory.condition_tag_ids,
            "object_tag_ids": sales_memory.object_tag_ids,
            "attitude_polarity": "support",
            "label": "A weak repeated SalesRep chart preference",
        },
        {
            "observation_id": "observation:latent:codex-process",
            "episode_id": "episode:latent:codex-process",
            "source_ref": "event:latent:codex-process",
            "source_kind": "log_event",
            "strength": 0.79,
            "condition_tag_ids": ("condition:app:chatgpt_codex",),
            "object_tag_ids": ("object:process_creation",),
            "attitude_polarity": "",
            "label": "A weak generic Codex process event",
        },
        {
            "observation_id": "observation:latent:salesrep-conflicted",
            "episode_id": "episode:latent:salesrep-conflicted",
            "source_ref": "event:latent:salesrep-conflicted",
            "source_kind": "observation",
            "strength": 0.79,
            "condition_tag_ids": sales_memory.condition_tag_ids,
            "object_tag_ids": sales_memory.object_tag_ids,
            "attitude_polarity": "support",
            "label": "A weak SalesRep preference with contrary evidence",
        },
    )
    for spec in weak_specs:
        observations.append(
            ObservationGraphNode(
                observation_id=spec["observation_id"],
                episode_id=spec["episode_id"],
                user_id="os-agent-v31-user",
                source_kind=spec["source_kind"],
                strength=spec["strength"],
                condition_tag_ids=spec["condition_tag_ids"],
                object_tag_ids=spec["object_tag_ids"],
                attitude_polarity=spec["attitude_polarity"],
                source_refs=(spec["source_ref"],),
                metadata={"label": spec["label"]},
            )
        )
        episodes.append(
            EpisodeGraphNode(
                episode_id=spec["episode_id"],
                user_id="os-agent-v31-user",
                source_kind=spec["source_kind"],
                observation_ids=(spec["observation_id"],),
                base_strength=spec["strength"],
                condition_tag_ids=spec["condition_tag_ids"],
                object_tag_ids=spec["object_tag_ids"],
                metadata={"label": spec["label"]},
            )
        )

    sales_source = memories[0].source_event_ids[0]
    sales_repeat_source = memories[1].source_event_ids[0]
    extra_signals = (
        ObservationRelationSignal(
            sales_source,
            "event:latent:salesrep-confirmed",
            0.92,
            relation_type="supports",
            metadata={
                "basis": "repeated same-scope preference evidence",
            },
        ),
        ObservationRelationSignal(
            "log-codex-process",
            "event:latent:codex-process",
            0.92,
            relation_type="activates",
            directed=True,
            metadata={
                "basis": "process continuity is not preference support",
            },
        ),
        ObservationRelationSignal(
            sales_source,
            "event:latent:salesrep-conflicted",
            0.88,
            relation_type="supports",
            metadata={"basis": "one agreeing memory"},
        ),
        ObservationRelationSignal(
            sales_repeat_source,
            "event:latent:salesrep-conflicted",
            0.92,
            relation_type="conflicts",
            metadata={"basis": "stronger contrary memory"},
        ),
    )
    return (
        tuple(observations),
        tuple(episodes),
        memories,
        (*base_signals, *extra_signals),
    )


def _memory_local_view(
    graph: LayeredMemoryKnowledgeGraph,
) -> list[dict[str, Any]]:
    by_id = {
        node.memory_id: node for node in graph.memory_graph.nodes
    }
    return [
        {
            "source": edge.source_memory_id,
            "source_label": by_id[edge.source_memory_id].metadata.get(
                "label",
                edge.source_memory_id,
            ),
            "relation": edge.relation_type,
            "directed": edge.directed,
            "target": edge.target_memory_id,
            "target_label": by_id[edge.target_memory_id].metadata.get(
                "label",
                edge.target_memory_id,
            ),
            "weight": edge.weight,
            "association_strength": edge.association_strength,
            "support_count": edge.support_count,
            "evidence_refs": [
                [item.source_ref, item.target_ref]
                for item in edge.evidence
            ],
        }
        for edge in graph.memory_graph.edges
    ]


def _episode_local_view(
    graph: LayeredMemoryKnowledgeGraph,
) -> list[dict[str, Any]]:
    by_id = {
        node.episode_id: node for node in graph.episode_graph.nodes
    }
    return [
        {
            "source": edge.source_episode_id,
            "source_label": by_id[edge.source_episode_id].metadata.get(
                "label",
                edge.source_episode_id,
            ),
            "relation": edge.relation_type,
            "directed": edge.directed,
            "target": edge.target_episode_id,
            "target_label": by_id[edge.target_episode_id].metadata.get(
                "label",
                edge.target_episode_id,
            ),
            "weight": edge.weight,
            "support_count": edge.support_count,
            "source_coverage": edge.source_coverage,
            "target_coverage": edge.target_coverage,
        }
        for edge in graph.episode_graph.edges
    ]


def _audit_checks(
    graph: LayeredMemoryKnowledgeGraph,
) -> dict[str, bool]:
    states = {
        state.episode_id: state
        for state in graph.episode_graph.promotion_states
    }
    observation_matrix = graph.observation_graph.relation_matrix()
    episode_matrix = graph.episode_graph.relation_matrix()
    observations = {
        node.observation_id: node
        for node in graph.observation_graph.nodes
    }
    memories = {
        node.memory_id: node for node in graph.memory_graph.nodes
    }
    return {
        "undirected_observation_matrix_is_symmetric": all(
            edge.directed
            or observation_matrix[edge.source_observation_id].get(
                edge.target_observation_id
            )
            == observation_matrix[edge.target_observation_id].get(
                edge.source_observation_id
            )
            for edge in graph.observation_graph.edges
        ),
        "undirected_episode_matrix_is_symmetric": all(
            edge.directed
            or episode_matrix[edge.source_episode_id].get(
                edge.target_episode_id
            )
            == episode_matrix[edge.target_episode_id].get(
                edge.source_episode_id
            )
            for edge in graph.episode_graph.edges
        ),
        "observation_evidence_matches_canonical_endpoints": all(
            evidence.source_ref
            in observations[edge.source_observation_id].aliases
            and evidence.target_ref
            in observations[edge.target_observation_id].aliases
            for edge in graph.observation_graph.edges
            for evidence in edge.evidence
        ),
        "episode_evidence_matches_canonical_endpoints": all(
            observations[evidence.source_observation_id].episode_id
            == edge.source_episode_id
            and observations[evidence.target_observation_id].episode_id
            == edge.target_episode_id
            for edge in graph.episode_graph.edges
            for evidence in edge.evidence
        ),
        "memory_evidence_matches_canonical_endpoints": all(
            evidence.source_ref
            in memories[edge.source_memory_id].aliases
            and evidence.target_ref
            in memories[edge.target_memory_id].aliases
            for edge in graph.memory_graph.edges
            for evidence in edge.evidence
        ),
        "supported_weak_episode_becomes_candidate": (
            states[
                "episode:latent:salesrep-confirmed"
            ].status
            == "promotion_candidate"
        ),
        "generic_process_relation_does_not_promote": (
            states["episode:latent:codex-process"].status == "latent"
        ),
        "conflict_blocks_weak_episode_promotion": (
            states[
                "episode:latent:salesrep-conflicted"
            ].status
            == "latent"
        ),
        "latent_episodes_are_absent_from_memory_matrix": all(
            not memory_id.startswith("episode:latent:")
            for memory_id in graph.memory_graph.relation_matrix()
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--preference-input",
        type=Path,
        default=DEFAULT_PREFERENCE_INPUT,
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    observations, episodes, memories, signals = layered_fixture(
        args.preference_input
    )
    builder = LayeredMemoryKnowledgeGraphBuilder()

    started = perf_counter()
    graph = builder.build(
        observations,
        episodes,
        memories,
        signals,
    )
    elapsed_ms = (perf_counter() - started) * 1000.0

    repeats = 1000
    started = perf_counter()
    for _ in range(repeats):
        builder.build(
            observations,
            episodes,
            memories,
            signals,
        )
    mean_ms = (perf_counter() - started) * 1000.0 / repeats

    checks = _audit_checks(graph)
    output = {
        "purpose": (
            "Fixed mixed-source audit of Observation, Episode and "
            "promoted Memory relation layers."
        ),
        "score_origin": (
            "Relation scores are fixed upstream inputs for this test. "
            "The graph builder does not call an LLM or Embedding model."
        ),
        "source_mix": {
            "observation_node_count": len(observations),
            "episode_node_count": len(episodes),
            "promoted_memory_count": len(memories),
            "text_observation_count": sum(
                node.source_kind == "observation"
                for node in observations
            ),
            "log_observation_count": sum(
                node.source_kind == "log_event"
                for node in observations
            ),
        },
        "performance": {
            "single_build_ms": elapsed_ms,
            "mean_build_ms_over_1000": mean_ms,
        },
        "checks": checks,
        "promotion_states": [
            state.to_dict()
            for state in graph.episode_graph.promotion_states
            if state.status != "existing_memory"
        ],
        "episode_local_view": _episode_local_view(graph),
        "memory_local_view": _memory_local_view(graph),
        "graph": graph.to_dict(),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(output, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "source_mix": output["source_mix"],
                "performance": output["performance"],
                "checks": checks,
                "diagnostics": graph.diagnostics.to_dict(),
                "promotion_states": output["promotion_states"],
                "episode_local_view": output["episode_local_view"],
                "memory_local_view": output["memory_local_view"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
