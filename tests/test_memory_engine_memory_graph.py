from __future__ import annotations

import unittest

from src.memory_engine.memory_graph import (
    MemoryGraphConfig,
    MemoryGraphNode,
    MemoryKnowledgeGraphBuilder,
    ObservationRelationSignal,
)
from src.memory_engine.preference_episode import PreferenceEpisodeMemory


def _node(
    index: int,
    *,
    user_id: str = "user-1",
    source_kind: str = "observation",
    strength: float = 0.9,
    condition: tuple[str, ...] = ("condition:spreadsheet",),
    objects: tuple[str, ...] = ("object:chart",),
    polarity: str = "support",
    event_ids: tuple[str, ...] | None = None,
) -> MemoryGraphNode:
    return MemoryGraphNode(
        memory_id=f"memory-{index}",
        episode_id=f"episode-{index}",
        user_id=user_id,
        source_kind=source_kind,
        strength=strength,
        condition_tag_ids=condition,
        object_tag_ids=objects,
        attitude_polarity=polarity,
        source_observation_ids=(f"observation-{index}",),
        source_event_ids=event_ids or (f"event-{index}",),
        source_memory_ids=(f"frame-{index}",),
    )


class MemoryKnowledgeGraphTest(unittest.TestCase):
    def test_independent_observation_relations_form_one_memory_edge(
        self,
    ) -> None:
        nodes = (_node(1), _node(2))
        signals = (
            ObservationRelationSignal(
                "observation-1",
                "observation-2",
                0.68,
                independent_unit_id="pair-1",
            ),
            ObservationRelationSignal(
                "event-1",
                "event-2",
                0.63,
                independent_unit_id="pair-2",
            ),
        )

        graph = MemoryKnowledgeGraphBuilder().build(nodes, signals)

        self.assertEqual(1, len(graph.edges))
        edge = graph.edges[0]
        self.assertEqual("supports", edge.relation_type)
        self.assertFalse(edge.directed)
        self.assertEqual(2, edge.support_count)
        self.assertGreater(edge.weight, edge.evidence[0].proof_strength)
        self.assertEqual(2, graph.diagnostics.admitted_evidence_count)

    def test_duplicate_frames_from_one_unit_do_not_inflate_edge(
        self,
    ) -> None:
        nodes = (_node(1), _node(2))
        signals = (
            ObservationRelationSignal(
                "event-1",
                "event-2",
                0.61,
                independent_unit_id="same-source-pair",
            ),
            ObservationRelationSignal(
                "frame-1",
                "frame-2",
                0.76,
                independent_unit_id="same-source-pair",
            ),
        )

        graph = MemoryKnowledgeGraphBuilder().build(nodes, signals)

        self.assertEqual(1, len(graph.edges))
        self.assertEqual(1, graph.edges[0].support_count)
        self.assertEqual(
            0.76,
            graph.edges[0].evidence[0].association,
        )
        self.assertEqual(1, graph.diagnostics.duplicate_evidence_count)

    def test_directed_log_relation_is_one_way_in_matrix(self) -> None:
        nodes = (
            _node(
                1,
                source_kind="log_event",
                condition=("condition:time_service",),
                objects=("object:resync_request",),
                polarity="",
            ),
            _node(
                2,
                source_kind="log_event",
                condition=("condition:time_service",),
                objects=("object:system_time_update",),
                polarity="",
            ),
        )
        signal = ObservationRelationSignal(
            "event-1",
            "event-2",
            0.84,
            relation_type="precedes",
            directed=True,
        )

        graph = MemoryKnowledgeGraphBuilder().build(nodes, [signal])
        matrix = graph.relation_matrix()

        self.assertEqual(0.84, graph.edges[0].association_strength)
        self.assertIn("memory-2", matrix["memory-1"])
        self.assertNotIn("memory-1", matrix["memory-2"])

    def test_undirected_relation_is_symmetric_in_matrix(self) -> None:
        graph = MemoryKnowledgeGraphBuilder().build(
            (_node(1), _node(2)),
            [
                ObservationRelationSignal(
                    "event-2",
                    "event-1",
                    0.72,
                )
            ],
        )

        matrix = graph.relation_matrix()

        self.assertEqual(
            matrix["memory-1"]["memory-2"],
            matrix["memory-2"]["memory-1"],
        )

    def test_reversed_undirected_signal_is_duplicate_evidence(self) -> None:
        graph = MemoryKnowledgeGraphBuilder().build(
            (_node(1), _node(2)),
            (
                ObservationRelationSignal(
                    "event-1",
                    "event-2",
                    0.72,
                ),
                ObservationRelationSignal(
                    "event-2",
                    "event-1",
                    0.68,
                ),
            ),
        )

        self.assertEqual(1, graph.edges[0].support_count)
        self.assertEqual(1, graph.diagnostics.duplicate_evidence_count)

    def test_directed_neighbors_can_select_incoming_or_outgoing(
        self,
    ) -> None:
        graph = MemoryKnowledgeGraphBuilder().build(
            (_node(1), _node(2)),
            [
                ObservationRelationSignal(
                    "event-1",
                    "event-2",
                    0.8,
                    relation_type="activates",
                    directed=True,
                )
            ],
        )

        self.assertEqual(1, len(graph.neighbors("memory-1")))
        self.assertEqual(1, len(graph.neighbors("memory-2")))
        self.assertEqual(
            (),
            graph.neighbors("memory-2", direction="outgoing"),
        )
        self.assertEqual(
            1,
            len(graph.neighbors("memory-2", direction="incoming")),
        )

    def test_undirected_neighbors_are_visible_from_both_nodes(self) -> None:
        graph = MemoryKnowledgeGraphBuilder().build(
            (_node(1), _node(2)),
            [
                ObservationRelationSignal(
                    "event-1",
                    "event-2",
                    0.8,
                )
            ],
        )

        self.assertEqual(
            1,
            len(graph.neighbors("memory-1", direction="incoming")),
        )
        self.assertEqual(
            1,
            len(graph.neighbors("memory-2", direction="outgoing")),
        )

    def test_opposite_attitudes_infer_conflict_edge(self) -> None:
        graph = MemoryKnowledgeGraphBuilder().build(
            (_node(1), _node(2, polarity="oppose")),
            [
                ObservationRelationSignal(
                    "event-1",
                    "event-2",
                    0.86,
                )
            ],
        )

        self.assertEqual("conflicts", graph.edges[0].relation_type)

    def test_disjoint_conditions_do_not_infer_conflict(self) -> None:
        graph = MemoryKnowledgeGraphBuilder().build(
            (
                _node(1),
                _node(
                    2,
                    condition=("condition:email",),
                    polarity="oppose",
                ),
            ),
            [
                ObservationRelationSignal(
                    "event-1",
                    "event-2",
                    0.86,
                )
            ],
        )

        self.assertEqual("related", graph.edges[0].relation_type)

    def test_low_relation_does_not_pass_because_nodes_are_strong(
        self,
    ) -> None:
        nodes = (_node(1, strength=1.0), _node(2, strength=1.0))
        signals = [
            ObservationRelationSignal(
                "event-1",
                "event-2",
                0.46,
            )
        ]

        graph = MemoryKnowledgeGraphBuilder().build(nodes, signals)

        self.assertEqual((), graph.edges)
        self.assertEqual(
            1,
            graph.diagnostics.below_edge_threshold_count,
        )

    def test_below_signal_threshold_is_rejected_early(self) -> None:
        graph = MemoryKnowledgeGraphBuilder().build(
            (_node(1), _node(2)),
            [
                ObservationRelationSignal(
                    "event-1",
                    "event-2",
                    0.44,
                )
            ],
        )

        self.assertEqual((), graph.edges)
        self.assertEqual(
            1,
            graph.diagnostics.below_signal_threshold_count,
        )

    def test_ambiguous_alias_requires_memory_hint(self) -> None:
        nodes = (
            _node(1, event_ids=("shared-event",)),
            _node(2, event_ids=("shared-event",)),
            _node(3),
        )
        ambiguous = ObservationRelationSignal(
            "shared-event",
            "event-3",
            0.8,
        )
        resolved = ObservationRelationSignal(
            "shared-event",
            "event-3",
            0.8,
            source_memory_hint="memory-1",
        )

        graph = MemoryKnowledgeGraphBuilder().build(
            nodes,
            (ambiguous, resolved),
        )

        self.assertEqual(1, graph.diagnostics.ambiguous_signal_count)
        self.assertEqual(1, len(graph.edges))
        self.assertEqual(
            {"memory-1", "memory-3"},
            {
                graph.edges[0].source_memory_id,
                graph.edges[0].target_memory_id,
            },
        )

    def test_self_and_cross_user_relations_are_rejected(self) -> None:
        nodes = (
            _node(1),
            _node(2, user_id="user-2"),
        )
        graph = MemoryKnowledgeGraphBuilder().build(
            nodes,
            (
                ObservationRelationSignal(
                    "observation-1",
                    "event-1",
                    0.9,
                ),
                ObservationRelationSignal(
                    "event-1",
                    "event-2",
                    0.9,
                ),
            ),
        )

        self.assertEqual((), graph.edges)
        self.assertEqual(1, graph.diagnostics.self_relation_count)
        self.assertEqual(1, graph.diagnostics.cross_user_signal_count)

    def test_preference_episode_memory_preserves_source_aliases(self) -> None:
        memory = PreferenceEpisodeMemory(
            memory_id="preference-memory",
            episode_id="preference-episode",
            user_id="user-1",
            session_id="session-1",
            condition_tag_id="condition:spreadsheet",
            condition_name="Spreadsheet",
            object_tag_id="object:chart",
            object_name="Chart",
            attitude_polarity="support",
            attitude_value=0.6,
            temporal_label="temporal_long",
            memory_type="long_term",
            promotion_seed=1.0,
            explicit_long_term=True,
            strength=0.92,
            strongest_observation_strength=0.85,
            conflicting_strength=0.0,
            support_count=2,
            source_observation_ids=("observation-a",),
            source_event_ids=("event-a",),
            source_memory_ids=("frame-a",),
            representative_observation_id="observation-a",
            promotion_reason="coherent_aggregate",
        )

        node = MemoryGraphNode.from_preference_memory(memory)

        self.assertEqual("observation", node.source_kind)
        self.assertEqual(
            {
                "preference-memory",
                "observation-a",
                "event-a",
                "frame-a",
            },
            set(node.aliases),
        )

    def test_secondary_evidence_gain_is_bounded(self) -> None:
        builder = MemoryKnowledgeGraphBuilder(
            MemoryGraphConfig(secondary_evidence_gain=0.2)
        )
        graph = builder.build(
            (_node(1), _node(2)),
            [
                ObservationRelationSignal(
                    "event-1",
                    "event-2",
                    0.7,
                    independent_unit_id=f"unit-{index}",
                )
                for index in range(10)
            ],
        )

        self.assertEqual(1, len(graph.edges))
        self.assertLess(graph.edges[0].weight, 0.95)


if __name__ == "__main__":
    unittest.main()
