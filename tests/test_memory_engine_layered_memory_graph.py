from __future__ import annotations

import unittest

from src.memory_engine.layered_memory_graph import (
    EpisodeGraphNode,
    LayeredMemoryKnowledgeGraphBuilder,
    ObservationGraphNode,
)
from src.memory_engine.memory_graph import (
    MemoryGraphNode,
    ObservationRelationSignal,
)


def _observation(
    index: int,
    episode: int,
    *,
    source_kind: str = "observation",
    object_id: str = "object:chart",
    polarity: str = "support",
) -> ObservationGraphNode:
    return ObservationGraphNode(
        observation_id=f"observation-{index}",
        episode_id=f"episode-{episode}",
        user_id="user-1",
        source_kind=source_kind,
        strength=0.9,
        condition_tag_ids=("condition:spreadsheet",),
        object_tag_ids=(object_id,),
        attitude_polarity=polarity,
        source_refs=(f"event-{index}",),
    )


def _episode(
    index: int,
    observation_ids: tuple[str, ...],
    *,
    base_strength: float,
    promoted: bool,
    source_kind: str = "observation",
) -> EpisodeGraphNode:
    return EpisodeGraphNode(
        episode_id=f"episode-{index}",
        user_id="user-1",
        source_kind=source_kind,
        observation_ids=observation_ids,
        base_strength=base_strength,
        memory_ids=(f"memory-{index}",) if promoted else (),
        condition_tag_ids=("condition:spreadsheet",),
        object_tag_ids=("object:chart",),
    )


def _memory(
    index: int,
    observation_ids: tuple[str, ...],
    event_ids: tuple[str, ...],
) -> MemoryGraphNode:
    return MemoryGraphNode(
        memory_id=f"memory-{index}",
        episode_id=f"episode-{index}",
        user_id="user-1",
        source_kind="observation",
        strength=0.9,
        condition_tag_ids=("condition:spreadsheet",),
        object_tag_ids=("object:chart",),
        attitude_polarity="support",
        source_observation_ids=observation_ids,
        source_event_ids=event_ids,
    )


class LayeredMemoryKnowledgeGraphTest(unittest.TestCase):
    def test_observation_episode_and_memory_layers_are_distinct(
        self,
    ) -> None:
        observations = (
            _observation(1, 1),
            _observation(2, 1),
            _observation(3, 2),
            _observation(4, 3),
        )
        episodes = (
            _episode(
                1,
                ("observation-1", "observation-2"),
                base_strength=0.9,
                promoted=True,
            ),
            _episode(
                2,
                ("observation-3",),
                base_strength=0.85,
                promoted=True,
            ),
            _episode(
                3,
                ("observation-4",),
                base_strength=0.7,
                promoted=False,
            ),
        )
        memories = (
            _memory(
                1,
                ("observation-1", "observation-2"),
                ("event-1", "event-2"),
            ),
            _memory(2, ("observation-3",), ("event-3",)),
        )
        signals = (
            ObservationRelationSignal("event-1", "event-2", 0.9),
            ObservationRelationSignal("event-2", "event-3", 0.8),
            ObservationRelationSignal("event-3", "event-4", 0.75),
        )

        graph = LayeredMemoryKnowledgeGraphBuilder().build(
            observations,
            episodes,
            memories,
            signals,
        )

        self.assertEqual(3, len(graph.observation_graph.edges))
        self.assertEqual(2, len(graph.episode_graph.edges))
        self.assertEqual(1, len(graph.memory_graph.edges))
        self.assertEqual(
            1,
            graph.episode_graph.internal_relation_counts["episode-1"],
        )
        self.assertEqual(1, graph.diagnostics.latent_episode_count)
        self.assertIn(
            "episode-3",
            graph.episode_graph.relation_matrix()["episode-2"],
        )
        self.assertNotIn(
            "memory-3",
            graph.memory_graph.relation_matrix(),
        )

    def test_directed_relation_keeps_direction_across_layers(self) -> None:
        observations = (
            _observation(1, 1, source_kind="log_event"),
            _observation(2, 2, source_kind="log_event"),
        )
        episodes = (
            _episode(
                1,
                ("observation-1",),
                base_strength=0.9,
                promoted=True,
                source_kind="log_event",
            ),
            _episode(
                2,
                ("observation-2",),
                base_strength=0.9,
                promoted=True,
                source_kind="log_event",
            ),
        )
        memories = (
            _memory(1, ("observation-1",), ("event-1",)),
            _memory(2, ("observation-2",), ("event-2",)),
        )

        graph = LayeredMemoryKnowledgeGraphBuilder().build(
            observations,
            episodes,
            memories,
            [
                ObservationRelationSignal(
                    "event-1",
                    "event-2",
                    0.9,
                    relation_type="precedes",
                    directed=True,
                )
            ],
        )

        observation_matrix = graph.observation_graph.relation_matrix()
        episode_matrix = graph.episode_graph.relation_matrix()
        memory_matrix = graph.memory_graph.relation_matrix()
        self.assertIn("observation-2", observation_matrix["observation-1"])
        self.assertNotIn("observation-1", observation_matrix["observation-2"])
        self.assertIn("episode-2", episode_matrix["episode-1"])
        self.assertNotIn("episode-1", episode_matrix["episode-2"])
        self.assertIn("memory-2", memory_matrix["memory-1"])
        self.assertNotIn("memory-1", memory_matrix["memory-2"])

    def test_reversed_undirected_signal_keeps_provenance_aligned(
        self,
    ) -> None:
        observations = (
            _observation(1, 1),
            _observation(2, 2),
        )
        episodes = (
            _episode(
                1,
                ("observation-1",),
                base_strength=0.9,
                promoted=True,
            ),
            _episode(
                2,
                ("observation-2",),
                base_strength=0.9,
                promoted=True,
            ),
        )
        memories = (
            _memory(1, ("observation-1",), ("event-1",)),
            _memory(2, ("observation-2",), ("event-2",)),
        )

        graph = LayeredMemoryKnowledgeGraphBuilder().build(
            observations,
            episodes,
            memories,
            (
                ObservationRelationSignal(
                    "event-2",
                    "event-1",
                    0.9,
                    source_memory_hint="memory-2",
                    target_memory_hint="memory-1",
                ),
            ),
        )

        observation_edge = graph.observation_graph.edges[0]
        observation_evidence = observation_edge.evidence[0]
        self.assertEqual(
            ("observation-1", "event-1", "memory-1"),
            (
                observation_evidence.source_observation_id,
                observation_evidence.source_ref,
                observation_evidence.source_memory_hint,
            ),
        )
        self.assertEqual(
            ("observation-2", "event-2", "memory-2"),
            (
                observation_evidence.target_observation_id,
                observation_evidence.target_ref,
                observation_evidence.target_memory_hint,
            ),
        )

        episode_edge = graph.episode_graph.edges[0]
        episode_evidence = episode_edge.evidence[0]
        self.assertEqual(
            "episode-1",
            episode_edge.source_episode_id,
        )
        self.assertEqual(
            "observation-1",
            episode_evidence.source_observation_id,
        )
        self.assertEqual(1, len(graph.memory_graph.edges))
        memory_evidence = graph.memory_graph.edges[0].evidence[0]
        self.assertEqual(
            ("memory-1", "event-1"),
            (
                memory_evidence.source_memory_id,
                memory_evidence.source_ref,
            ),
        )

    def test_multiple_observation_edges_aggregate_to_episode_edge(
        self,
    ) -> None:
        observations = (
            _observation(1, 1),
            _observation(2, 1),
            _observation(3, 2),
            _observation(4, 2),
        )
        episodes = (
            _episode(
                1,
                ("observation-1", "observation-2"),
                base_strength=0.75,
                promoted=False,
            ),
            _episode(
                2,
                ("observation-3", "observation-4"),
                base_strength=0.75,
                promoted=False,
            ),
        )
        signals = (
            ObservationRelationSignal(
                "event-1",
                "event-3",
                0.62,
                independent_unit_id="pair-1",
            ),
            ObservationRelationSignal(
                "event-2",
                "event-4",
                0.62,
                independent_unit_id="pair-2",
            ),
        )

        graph = LayeredMemoryKnowledgeGraphBuilder().build(
            observations,
            episodes,
            (),
            signals,
        )

        self.assertEqual(2, len(graph.observation_graph.edges))
        self.assertEqual(1, len(graph.episode_graph.edges))
        edge = graph.episode_graph.edges[0]
        self.assertEqual(2, edge.support_count)
        self.assertEqual(2, edge.source_coverage)
        self.assertEqual(2, edge.target_coverage)
        self.assertGreater(
            edge.weight,
            graph.observation_graph.edges[0].weight,
        )

    def test_weak_episode_and_its_relations_survive_without_memory(
        self,
    ) -> None:
        observations = (
            _observation(1, 1),
            _observation(2, 2),
        )
        episodes = (
            _episode(
                1,
                ("observation-1",),
                base_strength=0.9,
                promoted=True,
            ),
            _episode(
                2,
                ("observation-2",),
                base_strength=0.6,
                promoted=False,
            ),
        )
        graph = LayeredMemoryKnowledgeGraphBuilder().build(
            observations,
            episodes,
            (_memory(1, ("observation-1",), ("event-1",)),),
            [ObservationRelationSignal("event-1", "event-2", 0.8)],
        )

        self.assertEqual(1, len(graph.episode_graph.edges))
        self.assertEqual(0, len(graph.memory_graph.edges))
        latent = next(
            node
            for node in graph.episode_graph.nodes
            if node.episode_id == "episode-2"
        )
        self.assertFalse(latent.promoted)

    def test_invalid_lineage_is_rejected(self) -> None:
        observation = _observation(1, 1)
        wrong_episode = _episode(
            1,
            ("observation-2",),
            base_strength=0.6,
            promoted=False,
        )

        with self.assertRaisesRegex(
            ValueError,
            "must include every observation",
        ):
            LayeredMemoryKnowledgeGraphBuilder().build(
                (observation,),
                (wrong_episode,),
                (),
                (),
            )

    def test_support_from_promoted_episode_creates_candidate(self) -> None:
        observations = (
            _observation(1, 1),
            _observation(2, 2),
        )
        episodes = (
            _episode(
                1,
                ("observation-1",),
                base_strength=0.9,
                promoted=True,
            ),
            _episode(
                2,
                ("observation-2",),
                base_strength=0.79,
                promoted=False,
            ),
        )
        graph = LayeredMemoryKnowledgeGraphBuilder().build(
            observations,
            episodes,
            (_memory(1, ("observation-1",), ("event-1",)),),
            [
                ObservationRelationSignal(
                    "event-1",
                    "event-2",
                    0.9,
                    relation_type="supports",
                )
            ],
        )

        state = graph.episode_graph.promotion_state("episode-2")
        self.assertEqual("promotion_candidate", state.status)
        self.assertGreater(state.relation_reinforcement, 0.0)
        self.assertGreaterEqual(state.effective_strength, 0.82)
        self.assertEqual((state,), graph.promotion_candidates)

    def test_non_supporting_relation_types_do_not_promote(self) -> None:
        for relation in (
            "related",
            "activates",
            "precedes",
            "causes",
        ):
            with self.subTest(relation=relation):
                observations = (
                    _observation(1, 1),
                    _observation(
                        2,
                        2,
                        object_id="object:different",
                    ),
                )
                episodes = (
                    _episode(
                        1,
                        ("observation-1",),
                        base_strength=0.95,
                        promoted=True,
                    ),
                    _episode(
                        2,
                        ("observation-2",),
                        base_strength=0.79,
                        promoted=False,
                    ),
                )
                graph = LayeredMemoryKnowledgeGraphBuilder().build(
                    observations,
                    episodes,
                    (
                        _memory(
                            1,
                            ("observation-1",),
                            ("event-1",),
                        ),
                    ),
                    [
                        ObservationRelationSignal(
                            "event-1",
                            "event-2",
                            0.95,
                            relation_type=relation,
                            directed=relation != "related",
                        )
                    ],
                )

                state = graph.episode_graph.promotion_state(
                    "episode-2"
                )
                self.assertEqual("latent", state.status)
                self.assertEqual(0.0, state.relation_reinforcement)

    def test_weak_episodes_cannot_bootstrap_each_other(self) -> None:
        observations = (
            _observation(1, 1),
            _observation(2, 2),
        )
        episodes = (
            _episode(
                1,
                ("observation-1",),
                base_strength=0.79,
                promoted=False,
            ),
            _episode(
                2,
                ("observation-2",),
                base_strength=0.79,
                promoted=False,
            ),
        )
        graph = LayeredMemoryKnowledgeGraphBuilder().build(
            observations,
            episodes,
            (),
            [
                ObservationRelationSignal(
                    "event-1",
                    "event-2",
                    0.95,
                    relation_type="supports",
                )
            ],
        )

        self.assertEqual((), graph.promotion_candidates)
        self.assertTrue(
            all(
                state.relation_reinforcement == 0.0
                for state in graph.episode_graph.promotion_states
            )
        )

    def test_conflict_blocks_relation_based_promotion(self) -> None:
        observations = (
            _observation(1, 1),
            _observation(2, 2),
            _observation(3, 3, polarity="oppose"),
        )
        episodes = (
            _episode(
                1,
                ("observation-1",),
                base_strength=0.92,
                promoted=True,
            ),
            _episode(
                2,
                ("observation-2",),
                base_strength=0.79,
                promoted=False,
            ),
            _episode(
                3,
                ("observation-3",),
                base_strength=0.92,
                promoted=True,
            ),
        )
        memories = (
            _memory(1, ("observation-1",), ("event-1",)),
            _memory(3, ("observation-3",), ("event-3",)),
        )
        graph = LayeredMemoryKnowledgeGraphBuilder().build(
            observations,
            episodes,
            memories,
            (
                ObservationRelationSignal(
                    "event-1",
                    "event-2",
                    0.9,
                    relation_type="supports",
                ),
                ObservationRelationSignal(
                    "event-3",
                    "event-2",
                    0.9,
                    relation_type="conflicts",
                ),
            ),
        )

        state = graph.episode_graph.promotion_state("episode-2")
        self.assertEqual("latent", state.status)
        self.assertGreater(state.relation_reinforcement, 0.0)
        self.assertGreater(state.conflict_penalty, 0.0)
        self.assertLess(state.effective_strength, state.base_strength)

    def test_directed_support_only_reinforces_target(self) -> None:
        observations = (
            _observation(1, 1),
            _observation(2, 2),
        )
        episodes = (
            _episode(
                1,
                ("observation-1",),
                base_strength=0.9,
                promoted=True,
            ),
            _episode(
                2,
                ("observation-2",),
                base_strength=0.79,
                promoted=False,
            ),
        )
        memory = _memory(
            1,
            ("observation-1",),
            ("event-1",),
        )
        builder = LayeredMemoryKnowledgeGraphBuilder()
        forward = builder.build(
            observations,
            episodes,
            (memory,),
            [
                ObservationRelationSignal(
                    "event-1",
                    "event-2",
                    0.9,
                    relation_type="supports",
                    directed=True,
                )
            ],
        )
        reverse = builder.build(
            observations,
            episodes,
            (memory,),
            [
                ObservationRelationSignal(
                    "event-2",
                    "event-1",
                    0.9,
                    relation_type="supports",
                    directed=True,
                )
            ],
        )

        self.assertTrue(
            forward.episode_graph.promotion_state(
                "episode-2"
            ).promotion_candidate
        )
        self.assertEqual(
            "latent",
            reverse.episode_graph.promotion_state(
                "episode-2"
            ).status,
        )

    def test_episode_can_become_candidate_from_new_internal_strength(
        self,
    ) -> None:
        graph = LayeredMemoryKnowledgeGraphBuilder().build(
            (_observation(1, 1),),
            (
                _episode(
                    1,
                    ("observation-1",),
                    base_strength=0.83,
                    promoted=False,
                ),
            ),
            (),
            (),
        )

        state = graph.episode_graph.promotion_state("episode-1")
        self.assertTrue(state.promotion_candidate)
        self.assertEqual(0.0, state.relation_reinforcement)


if __name__ == "__main__":
    unittest.main()
