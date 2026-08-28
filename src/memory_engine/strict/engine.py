# ============================================================
# ⚠️ 预留组件（2025-08 审计）：未接入主流程，保留供后续启用；勿假设其生效
# ============================================================
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from time import perf_counter
from typing import Any, Mapping
from uuid import NAMESPACE_URL, uuid4, uuid5

from .candidates import strict_candidate_modules
from .config import StrictMemoryEngineConfig
from .conflict import (
    ConditionPartitionResolver,
    ExplicitTimeRecentWindowDynamicResolver,
    HierarchicalConflictClassifier,
    SourceVersionCountStaticResolver,
)
from .contracts import StageOutput
from .episode import SplitMergeEpisodeRepair, TimeTaskArtifactSTM
from .evidence import TypedRuleEvidenceExtractor
from .errors import StrictConfigurationError, StrictStageUnavailableError
from .observation import (
    TypedRuleObservationNormalizer,
    UnsafeObservationError,
)
from .lifecycle import StabilityThresholdLifecycle
from .forgetting import LineageRetractionForgetting
from .kylin import SemanticScorer
from .reflection import GroundedRuleConsolidation
from .registry import StrictModuleRegistry
from .retrieval import (
    scoped_evidence_memories,
    StrictRetrievalContext,
    StructuredBM25Retriever,
    StructuredHNSWRetriever,
    StructuredSimilarityActivation,
)
from .scoring import EvidenceShareConfidence, OpportunityWindowStability
from .store import StrictMemoryEngineStore
from .updater import SlotImpactMemoryUpdater


class StrictMemoryEngine:
    """Strict pipeline entry point with explicit stage activation.

    It contains no import or runtime fallback to the baseline MemoryEngine.
    """

    def __init__(
        self,
        config: StrictMemoryEngineConfig | None = None,
        store: StrictMemoryEngineStore | None = None,
        registry: StrictModuleRegistry | None = None,
        semantic_scorer: SemanticScorer | None = None,
    ):
        self.config = config or StrictMemoryEngineConfig.load()
        self.store = store or StrictMemoryEngineStore(self.config.database_path)
        self.registry = registry or build_strict_v1_registry(
            self.config
        )
        self.semantic_scorer = semantic_scorer
        self.registry.validate(
            self.config,
            self.config.stages_through("episode_repair"),
        )
        if self.config.strict_full_activation:
            self.registry.validate_full(self.config)

    def validate_full_activation(self) -> None:
        self.registry.validate_full(self.config)

    def retrieve(
        self,
        query: str,
        context: Mapping[str, Any] | None = None,
        *,
        top_k: int = 5,
        kylin_semantic_scores: Mapping[str, float] | None = None,
    ) -> dict[str, Any]:
        self.registry.validate(
            self.config,
            self.config.stages_through("retrieval"),
        )
        if top_k <= 0:
            raise ValueError("top_k must be positive")
        started = perf_counter()
        created_at = datetime.now(timezone.utc).isoformat()
        run_id = f"strict-run-{uuid4().hex}"
        retrieval_context = StrictRetrievalContext.from_mapping(query, context)
        memories = self.store.list_memories(retrieval_context.user_id)
        memories.extend(
            scoped_evidence_memories(
                self.store.list_evidence(retrieval_context.user_id),
                query_time=retrieval_context.query_time,
            )
        )
        groups = self.store.list_conflict_groups(retrieval_context.user_id)
        if kylin_semantic_scores is None:
            if self.semantic_scorer is None:
                if self.config.retrieval.get("require_kylin_semantic", False):
                    raise StrictConfigurationError(
                        "strict retrieval requires Kylin SDK semantic scores"
                    )
        retriever = self.registry.resolve(
            "retrieval",
            self.config.modules["retrieval"],
        )
        result = retriever.retrieve(
            memories,
            groups,
            retrieval_context,
            top_k=top_k,
            kylin_semantic_scores=kylin_semantic_scores,
            semantic_scorer=self.semantic_scorer,
        )
        activation_output = _stage_output(
            run_id=run_id,
            stage="activation",
            module_id=self.config.modules["activation"],
            input_ids=tuple(item.memory_id for item in memories),
            output_ids=tuple(item["memory_id"] for item in result["items"]),
            payload={
                "scores": {
                    item["memory_id"]: item["scores"]["activation"]
                    for item in result["items"]
                }
            },
            created_at=created_at,
        )
        retrieval_output = _stage_output(
            run_id=run_id,
            stage="retrieval",
            module_id=self.config.modules["retrieval"],
            input_ids=tuple(item.memory_id for item in memories),
            output_ids=tuple(item["memory_id"] for item in result["items"]),
            payload=result,
            created_at=created_at,
        )
        self.store.put_stage_output(activation_output)
        self.store.put_stage_output(retrieval_output)
        latency_ms = (perf_counter() - started) * 1000
        module_versions = {
            stage: self.config.modules[stage]
            for stage in self.config.stages_through("retrieval")
        }
        self.store.put_engine_run(
            {
                "run_id": run_id,
                "operation": "retrieve",
                "stage_limit": "retrieval",
                "module_versions": module_versions,
                "input_ids": [query],
                "output_ids": [
                    activation_output.output_id,
                    retrieval_output.output_id,
                ],
                "trace": result["trace"],
                "status": "ok",
                "latency_ms": latency_ms,
                "created_at": created_at,
            }
        )
        return {
            **result,
            "run_id": run_id,
            "module_versions": {
                "activation": self.config.modules["activation"],
                "retrieval": self.config.modules["retrieval"],
            },
            "latency_ms": latency_ms,
        }

    def forget(
        self,
        request: Mapping[str, Any],
        *,
        dry_run: bool = True,
    ) -> dict[str, Any]:
        self.registry.validate(
            self.config,
            self.config.stages_through("forgetting"),
        )
        started = perf_counter()
        created_at = datetime.now(timezone.utc).isoformat()
        run_id = f"strict-run-{uuid4().hex}"
        module = self.registry.resolve(
            "forgetting",
            self.config.modules["forgetting"],
        )
        record = module.forget(
            self.store,
            request,
            dry_run=dry_run,
            now=created_at,
        )
        output = _stage_output(
            run_id=run_id,
            stage="forgetting",
            module_id=self.config.modules["forgetting"],
            input_ids=tuple(record.candidate_memory_ids),
            output_ids=(record.request_id,),
            payload=record.to_dict(),
            created_at=created_at,
        )
        self.store.put_stage_output(output)
        latency_ms = (perf_counter() - started) * 1000
        self.store.put_engine_run(
            {
                "run_id": run_id,
                "operation": "forget",
                "stage_limit": "forgetting",
                "module_versions": {
                    "forgetting": self.config.modules["forgetting"]
                },
                "input_ids": list(record.candidate_memory_ids),
                "output_ids": [output.output_id],
                "trace": {
                    "fallback_used": False,
                    "residual_verified": record.report.get(
                        "residual_verified"
                    ),
                },
                "status": record.status,
                "latency_ms": latency_ms,
                "created_at": created_at,
            }
        )
        return {
            **record.to_dict(),
            "run_id": run_id,
            "fallback_used": False,
            "latency_ms": latency_ms,
        }

    def reflect(self, user_id: str) -> dict[str, Any]:
        self.registry.validate_full(self.config)
        started = perf_counter()
        created_at = datetime.now(timezone.utc).isoformat()
        run_id = f"strict-run-{uuid4().hex}"
        module = self.registry.resolve(
            "reflection",
            self.config.modules["reflection"],
        )
        artifacts = module.reflect(
            user_id,
            self.store.list_memories(user_id),
            self.store.list_evidence(user_id),
            now=created_at,
        )
        for artifact in artifacts:
            self.store.put_reflection(artifact)
        output = _stage_output(
            run_id=run_id,
            stage="reflection",
            module_id=self.config.modules["reflection"],
            input_ids=tuple(
                memory.memory_id
                for memory in self.store.list_memories(user_id)
            ),
            output_ids=tuple(
                artifact.reflection_id for artifact in artifacts
            ),
            payload={
                "artifacts": [
                    artifact.to_dict() for artifact in artifacts
                ]
            },
            created_at=created_at,
        )
        self.store.put_stage_output(output)
        latency_ms = (perf_counter() - started) * 1000
        self.store.put_engine_run(
            {
                "run_id": run_id,
                "operation": "reflect",
                "stage_limit": "reflection",
                "module_versions": {
                    "reflection": self.config.modules["reflection"]
                },
                "input_ids": [user_id],
                "output_ids": [output.output_id],
                "trace": {
                    "fallback_used": False,
                    "grounded_count": sum(
                        artifact.grounding_verified
                        for artifact in artifacts
                    ),
                },
                "status": "ok",
                "latency_ms": latency_ms,
                "created_at": created_at,
            }
        )
        return {
            "status": "ok",
            "artifacts": [
                artifact.to_dict() for artifact in artifacts
            ],
            "run_id": run_id,
            "fallback_used": False,
            "latency_ms": latency_ms,
        }

    def ingest_observation(
        self,
        event: Mapping[str, Any],
        *,
        stage_limit: str = "episode_repair",
    ) -> dict[str, Any]:
        allowed = self.config.stages_through(stage_limit)
        self.registry.validate(self.config, allowed)
        started = perf_counter()
        created_at = datetime.now(timezone.utc).isoformat()
        run_id = f"strict-run-{uuid4().hex}"
        outputs: list[StageOutput] = []
        input_ids = [str(event.get("source_event_id") or "")]
        trace: dict[str, Any] = {"fallback_used": False}
        try:
            normalizer = self.registry.resolve(
                "observation",
                self.config.modules["observation"],
            )
            observation = normalizer.normalize(event)
            created = self.store.put_observation(observation)
            if not created:
                stored = self.store.get_observation_by_source_event(
                    observation.source_event_id
                )
                if stored is None:
                    raise RuntimeError("idempotent observation disappeared")
                observation = stored
            observation_output = _stage_output(
                run_id=run_id,
                stage="observation",
                module_id=self.config.modules["observation"],
                input_ids=tuple(input_ids),
                output_ids=(observation.observation_id,),
                payload={
                    "created": created,
                    "observation": observation.to_dict(),
                },
                created_at=created_at,
            )
            self.store.put_stage_output(observation_output)
            outputs.append(observation_output)

            if stage_limit == "observation":
                return self._complete_run(
                    run_id,
                    stage_limit,
                    input_ids,
                    outputs,
                    trace,
                    started,
                    created_at,
                    result={
                        "status": "ok",
                        "observation_id": observation.observation_id,
                        "observation_created": created,
                    },
                )

            stm = self.registry.resolve("stm", self.config.modules["stm"])
            observations = self.store.list_observations(
                observation.user_id,
                observation.session_id,
            )
            provisional = {
                item.observation_id: stm.provisional_episode_id(item)
                for item in observations
            }
            stm_output = _stage_output(
                run_id=run_id,
                stage="stm",
                module_id=self.config.modules["stm"],
                input_ids=tuple(item.observation_id for item in observations),
                output_ids=tuple(sorted(set(provisional.values()))),
                payload={"observation_episode_map": provisional},
                created_at=created_at,
            )
            self.store.put_stage_output(stm_output)
            outputs.append(stm_output)

            if stage_limit == "stm":
                return self._complete_run(
                    run_id,
                    stage_limit,
                    input_ids,
                    outputs,
                    trace,
                    started,
                    created_at,
                    result={
                        "status": "ok",
                        "observation_id": observation.observation_id,
                        "observation_created": created,
                        "provisional_episode_id": provisional[
                            observation.observation_id
                        ],
                    },
                )

            repair = self.registry.resolve(
                "episode_repair",
                self.config.modules["episode_repair"],
            )
            execution, fragments, fingerprint = repair.repair(
                observations,
                provisional,
            )
            self.store.replace_execution(
                execution,
                fragments,
                input_fingerprint=fingerprint,
                created_at=created_at,
            )
            repair_output = _stage_output(
                run_id=run_id,
                stage="episode_repair",
                module_id=self.config.modules["episode_repair"],
                input_ids=tuple(item.observation_id for item in observations),
                output_ids=(execution.execution_id,)
                + tuple(item.fragment_id for item in fragments),
                payload={
                    "execution": execution.to_dict(),
                    "fragments": [item.to_dict() for item in fragments],
                },
                created_at=created_at,
            )
            self.store.put_stage_output(repair_output)
            outputs.append(repair_output)
            trace["path_valid"] = execution.path_valid
            repair_result = {
                "status": "ok",
                "observation_id": observation.observation_id,
                "observation_created": created,
                "execution_id": execution.execution_id,
                "fragment_ids": list(execution.fragment_ids),
                "path_valid": execution.path_valid,
                "repair_trace": list(execution.repair_trace),
            }
            if stage_limit == "episode_repair":
                return self._complete_run(
                    run_id,
                    stage_limit,
                    input_ids,
                    outputs,
                    trace,
                    started,
                    created_at,
                    result=repair_result,
                )

            evidence_extractor = self.registry.resolve(
                "evidence",
                self.config.modules["evidence"],
            )
            observation_map = {
                item.observation_id: item
                for item in observations
            }
            extracted_evidence = evidence_extractor.extract(
                fragments,
                observation_map,
            )
            suppressed_evidence = [
                item
                for item in extracted_evidence
                if self.store.evidence_is_suppressed(item)
            ]
            evidence = [
                item
                for item in extracted_evidence
                if item not in suppressed_evidence
            ]
            created_evidence = [
                item.evidence_id
                for item in evidence
                if self.store.put_evidence(item)
            ]
            evidence_output = _stage_output(
                run_id=run_id,
                stage="evidence",
                module_id=self.config.modules["evidence"],
                input_ids=tuple(item.fragment_id for item in fragments),
                output_ids=tuple(item.evidence_id for item in evidence),
                payload={
                    "evidence": [item.to_dict() for item in evidence],
                    "created_evidence_ids": created_evidence,
                    "suppressed_evidence_ids": [
                        item.evidence_id for item in suppressed_evidence
                    ],
                },
                created_at=created_at,
            )
            self.store.put_stage_output(evidence_output)
            outputs.append(evidence_output)
            trace["evidence_count"] = len(evidence)
            trace["suppressed_evidence_count"] = len(suppressed_evidence)
            trace["candidate_eligible_count"] = sum(
                item.eligible_for_candidate for item in evidence
            )
            evidence_result = {
                **repair_result,
                "evidence_ids": [item.evidence_id for item in evidence],
                "created_evidence_ids": created_evidence,
                "suppressed_evidence_ids": [
                    item.evidence_id for item in suppressed_evidence
                ],
                "candidate_eligible_count": trace[
                    "candidate_eligible_count"
                ],
            }
            if stage_limit == "evidence":
                return self._complete_run(
                    run_id,
                    stage_limit,
                    input_ids,
                    outputs,
                    trace,
                    started,
                    created_at,
                    result=evidence_result,
                )

            candidate_stages = (
                "tool_preference",
                "output_style",
                "safety",
                "fact",
                "workflow",
                "case",
                "template",
            )
            candidate_ids: list[str] = []
            created_candidate_ids: list[str] = []
            for candidate_stage in candidate_stages:
                candidate_module = self.registry.resolve(
                    candidate_stage,
                    self.config.modules[candidate_stage],
                )
                proposed = candidate_module.propose(evidence)
                created_for_stage = [
                    item.candidate_id
                    for item in proposed
                    if self.store.put_candidate(item)
                ]
                candidate_ids.extend(item.candidate_id for item in proposed)
                created_candidate_ids.extend(created_for_stage)
                candidate_output = _stage_output(
                    run_id=run_id,
                    stage=candidate_stage,
                    module_id=self.config.modules[candidate_stage],
                    input_ids=tuple(item.evidence_id for item in evidence),
                    output_ids=tuple(item.candidate_id for item in proposed),
                    payload={
                        "candidates": [item.to_dict() for item in proposed],
                        "created_candidate_ids": created_for_stage,
                    },
                    created_at=created_at,
                )
                self.store.put_stage_output(candidate_output)
                outputs.append(candidate_output)
                if stage_limit == candidate_stage:
                    trace["candidate_count"] = len(set(candidate_ids))
                    return self._complete_run(
                        run_id,
                        stage_limit,
                        input_ids,
                        outputs,
                        trace,
                        started,
                        created_at,
                        result={
                            **evidence_result,
                            "candidate_ids": list(dict.fromkeys(candidate_ids)),
                            "created_candidate_ids": created_candidate_ids,
                        },
                    )
            updater = self.registry.resolve(
                "memory_update",
                self.config.modules["memory_update"],
            )
            unapplied_candidates = self.store.list_unapplied_candidates(
                observation.user_id
            )
            stored_candidates = self.store.list_candidates(
                observation.user_id,
                status="pending",
            )
            existing_memories = self.store.list_memories(
                observation.user_id
            )
            impacts, memory_state = updater.apply(
                unapplied_candidates,
                existing_memories,
                now=created_at,
            )
            for memory in memory_state:
                self.store.put_memory(memory)
            created_impact_ids = [
                item.impact_id
                for item in impacts
                if self.store.put_impact(item)
            ]
            memory_output = _stage_output(
                run_id=run_id,
                stage="memory_update",
                module_id=self.config.modules["memory_update"],
                input_ids=tuple(
                    item.candidate_id for item in unapplied_candidates
                ),
                output_ids=(
                    tuple(item.impact_id for item in impacts)
                    + tuple(item.memory_id for item in memory_state)
                ),
                payload={
                    "impacts": [item.to_dict() for item in impacts],
                    "memories": [item.to_dict() for item in memory_state],
                    "created_impact_ids": created_impact_ids,
                },
                created_at=created_at,
            )
            self.store.put_stage_output(memory_output)
            outputs.append(memory_output)
            trace["impact_count"] = len(impacts)
            trace["memory_count"] = len(memory_state)
            trace["unapplied_candidate_count"] = len(
                unapplied_candidates
            )
            if stage_limit == "memory_update":
                return self._complete_run(
                    run_id,
                    stage_limit,
                    input_ids,
                    outputs,
                    trace,
                    started,
                    created_at,
                    result={
                        **evidence_result,
                        "candidate_ids": list(dict.fromkeys(candidate_ids)),
                        "created_candidate_ids": created_candidate_ids,
                        "impact_ids": [item.impact_id for item in impacts],
                        "created_impact_ids": created_impact_ids,
                        "memory_ids": [
                            item.memory_id for item in memory_state
                        ],
                    },
                )

            classifier = self.registry.resolve(
                "conflict_classifier",
                self.config.modules["conflict_classifier"],
            )
            conflict_groups = classifier.classify(
                memory_state,
                now=created_at,
            )
            retired_conflict_group_ids = (
                self.store.retire_conflict_groups(
                    observation.user_id,
                    {
                        group.conflict_group_id
                        for group in conflict_groups
                    },
                    updated_at=created_at,
                )
            )
            group_ids_by_memory: dict[str, list[str]] = {}
            for group in conflict_groups:
                self.store.put_conflict_group(group)
                for memory_id in group.memory_ids:
                    group_ids_by_memory.setdefault(memory_id, []).append(
                        group.conflict_group_id
                    )
            memory_state = [
                replace(
                    memory,
                    conflict_group_ids=tuple(
                        dict.fromkeys(
                            memory.conflict_group_ids
                            + tuple(group_ids_by_memory.get(memory.memory_id, ()))
                        )
                    ),
                )
                for memory in memory_state
            ]
            for memory in memory_state:
                self.store.put_memory(memory)
            conflict_output = _stage_output(
                run_id=run_id,
                stage="conflict_classifier",
                module_id=self.config.modules["conflict_classifier"],
                input_ids=tuple(item.memory_id for item in memory_state),
                output_ids=tuple(
                    item.conflict_group_id for item in conflict_groups
                ),
                payload={
                    "conflict_groups": [
                        item.to_dict() for item in conflict_groups
                    ],
                    "retired_conflict_group_ids": (
                        retired_conflict_group_ids
                    ),
                },
                created_at=created_at,
            )
            self.store.put_stage_output(conflict_output)
            outputs.append(conflict_output)
            if stage_limit == "conflict_classifier":
                return self._complete_run(
                    run_id,
                    stage_limit,
                    input_ids,
                    outputs,
                    trace,
                    started,
                    created_at,
                    result={
                        **evidence_result,
                        "memory_ids": [
                            item.memory_id for item in memory_state
                        ],
                        "conflict_group_ids": [
                            item.conflict_group_id
                            for item in conflict_groups
                        ],
                    },
                )

            memories_by_id = {
                item.memory_id: item for item in memory_state
            }
            resolver_stages = (
                "static_resolver",
                "dynamic_resolver",
                "conditional_resolver",
            )
            for resolver_stage in resolver_stages:
                resolver = self.registry.resolve(
                    resolver_stage,
                    self.config.modules[resolver_stage],
                )
                conflict_groups = [
                    resolver.resolve(group, memories_by_id)
                    for group in conflict_groups
                ]
                for group in conflict_groups:
                    self.store.put_conflict_group(group)
                resolver_output = _stage_output(
                    run_id=run_id,
                    stage=resolver_stage,
                    module_id=self.config.modules[resolver_stage],
                    input_ids=tuple(
                        item.conflict_group_id for item in conflict_groups
                    ),
                    output_ids=tuple(
                        item.conflict_group_id for item in conflict_groups
                    ),
                    payload={
                        "conflict_groups": [
                            item.to_dict() for item in conflict_groups
                        ]
                    },
                    created_at=created_at,
                )
                self.store.put_stage_output(resolver_output)
                outputs.append(resolver_output)
                if stage_limit == resolver_stage:
                    return self._complete_run(
                        run_id,
                        stage_limit,
                        input_ids,
                        outputs,
                        trace,
                        started,
                        created_at,
                        result={
                            **evidence_result,
                            "memory_ids": [
                                item.memory_id for item in memory_state
                            ],
                            "conflict_group_ids": [
                                item.conflict_group_id
                                for item in conflict_groups
                            ],
                        },
                    )

            confidence_module = self.registry.resolve(
                "confidence",
                self.config.modules["confidence"],
            )
            memory_state = confidence_module.score(
                memory_state,
                conflict_groups,
            )
            memories_by_id = {
                item.memory_id: item for item in memory_state
            }
            conflict_groups = [
                replace(
                    group,
                    confidence={
                        memory_id: memories_by_id[memory_id].confidence
                        for memory_id in group.memory_ids
                    },
                )
                for group in conflict_groups
            ]
            for memory in memory_state:
                self.store.put_memory(memory)
            for group in conflict_groups:
                self.store.put_conflict_group(group)
            confidence_output = _stage_output(
                run_id=run_id,
                stage="confidence",
                module_id=self.config.modules["confidence"],
                input_ids=tuple(item.memory_id for item in memory_state),
                output_ids=tuple(item.memory_id for item in memory_state),
                payload={
                    "memories": [item.to_dict() for item in memory_state],
                    "conflict_groups": [
                        item.to_dict() for item in conflict_groups
                    ],
                },
                created_at=created_at,
            )
            self.store.put_stage_output(confidence_output)
            outputs.append(confidence_output)
            if stage_limit == "confidence":
                return self._complete_run(
                    run_id,
                    stage_limit,
                    input_ids,
                    outputs,
                    trace,
                    started,
                    created_at,
                    result={
                        **evidence_result,
                        "memory_ids": [
                            item.memory_id for item in memory_state
                        ],
                        "conflict_group_ids": [
                            item.conflict_group_id
                            for item in conflict_groups
                        ],
                    },
                )

            stability_module = self.registry.resolve(
                "stability",
                self.config.modules["stability"],
            )
            memory_state = stability_module.score(
                memory_state,
                stored_candidates,
            )
            for memory in memory_state:
                self.store.put_memory(memory)
            stability_output = _stage_output(
                run_id=run_id,
                stage="stability",
                module_id=self.config.modules["stability"],
                input_ids=tuple(item.memory_id for item in memory_state),
                output_ids=tuple(item.memory_id for item in memory_state),
                payload={
                    "memories": [item.to_dict() for item in memory_state]
                },
                created_at=created_at,
            )
            self.store.put_stage_output(stability_output)
            outputs.append(stability_output)
            if stage_limit == "stability":
                return self._complete_run(
                    run_id,
                    stage_limit,
                    input_ids,
                    outputs,
                    trace,
                    started,
                    created_at,
                    result={
                        **evidence_result,
                        "memory_ids": [
                            item.memory_id for item in memory_state
                        ],
                    },
                )

            lifecycle_module = self.registry.resolve(
                "lifecycle",
                self.config.modules["lifecycle"],
            )
            memory_state, lifecycle_events = lifecycle_module.apply(
                memory_state,
                now=created_at,
            )
            for memory in memory_state:
                self.store.put_memory(memory)
            for event in lifecycle_events:
                self.store.put_lifecycle_event(event)
            lifecycle_output = _stage_output(
                run_id=run_id,
                stage="lifecycle",
                module_id=self.config.modules["lifecycle"],
                input_ids=tuple(item.memory_id for item in memory_state),
                output_ids=(
                    tuple(item.memory_id for item in memory_state)
                    + tuple(item.event_id for item in lifecycle_events)
                ),
                payload={
                    "memories": [item.to_dict() for item in memory_state],
                    "lifecycle_events": [
                        item.to_dict() for item in lifecycle_events
                    ],
                },
                created_at=created_at,
            )
            self.store.put_stage_output(lifecycle_output)
            outputs.append(lifecycle_output)
            if stage_limit == "lifecycle":
                return self._complete_run(
                    run_id,
                    stage_limit,
                    input_ids,
                    outputs,
                    trace,
                    started,
                    created_at,
                    result={
                        **evidence_result,
                        "memory_ids": [
                            item.memory_id for item in memory_state
                        ],
                        "lifecycle_event_ids": [
                            item.event_id for item in lifecycle_events
                        ],
                    },
                )
            raise StrictStageUnavailableError(
                f"strict stage {stage_limit!r} is not implemented after lifecycle"
            )
        except UnsafeObservationError as exc:
            trace["privacy_rejection"] = str(exc)
            return self._complete_run(
                run_id,
                stage_limit,
                input_ids,
                outputs,
                trace,
                started,
                created_at,
                status="rejected",
                result={"status": "rejected", "reason": "unsafe_source_event"},
            )

    def _complete_run(
        self,
        run_id: str,
        stage_limit: str,
        input_ids: list[str],
        outputs: list[StageOutput],
        trace: dict[str, Any],
        started: float,
        created_at: str,
        *,
        result: dict[str, Any],
        status: str = "ok",
    ) -> dict[str, Any]:
        latency_ms = (perf_counter() - started) * 1000
        module_versions = {
            stage: self.config.modules[stage]
            for stage in self.config.stages_through(stage_limit)
        }
        self.store.put_engine_run(
            {
                "run_id": run_id,
                "operation": "ingest_observation",
                "stage_limit": stage_limit,
                "module_versions": module_versions,
                "input_ids": input_ids,
                "output_ids": [item.output_id for item in outputs],
                "trace": trace,
                "status": status,
                "latency_ms": latency_ms,
                "created_at": created_at,
            }
        )
        return {
            **result,
            "run_id": run_id,
            "stage_limit": stage_limit,
            "module_versions": module_versions,
            "fallback_used": False,
            "latency_ms": latency_ms,
        }


def build_strict_v1_registry(
    config: StrictMemoryEngineConfig,
) -> StrictModuleRegistry:
    registry = StrictModuleRegistry()
    registry.register(
        "observation",
        TypedRuleObservationNormalizer.module_id,
        TypedRuleObservationNormalizer(),
    )
    registry.register(
        "stm",
        TimeTaskArtifactSTM.module_id,
        TimeTaskArtifactSTM(),
    )
    registry.register(
        "episode_repair",
        SplitMergeEpisodeRepair.module_id,
        SplitMergeEpisodeRepair(config.episode),
    )
    registry.register(
        "evidence",
        TypedRuleEvidenceExtractor.module_id,
        TypedRuleEvidenceExtractor(),
    )
    for stage, module in strict_candidate_modules().items():
        registry.register(stage, module.module_id, module)
    updater = SlotImpactMemoryUpdater(config.conflict)
    classifier = HierarchicalConflictClassifier()
    static_resolver = SourceVersionCountStaticResolver()
    dynamic_resolver = ExplicitTimeRecentWindowDynamicResolver()
    conditional_resolver = ConditionPartitionResolver()
    confidence = EvidenceShareConfidence(config.confidence)
    stability = OpportunityWindowStability(config.stability)
    lifecycle = StabilityThresholdLifecycle(config.lifecycle)
    registry.register(
        "memory_update",
        SlotImpactMemoryUpdater.module_id,
        updater,
    )
    registry.register(
        "conflict_classifier",
        HierarchicalConflictClassifier.module_id,
        classifier,
    )
    registry.register(
        "static_resolver",
        SourceVersionCountStaticResolver.module_id,
        static_resolver,
    )
    registry.register(
        "dynamic_resolver",
        ExplicitTimeRecentWindowDynamicResolver.module_id,
        dynamic_resolver,
    )
    registry.register(
        "conditional_resolver",
        ConditionPartitionResolver.module_id,
        conditional_resolver,
    )
    registry.register(
        "confidence",
        EvidenceShareConfidence.module_id,
        confidence,
    )
    registry.register(
        "stability",
        OpportunityWindowStability.module_id,
        stability,
    )
    registry.register(
        "lifecycle",
        StabilityThresholdLifecycle.module_id,
        lifecycle,
    )
    activation = StructuredSimilarityActivation(config.activation)
    registry.register(
        "activation",
        StructuredSimilarityActivation.module_id,
        activation,
    )
    registry.register(
        "retrieval",
        StructuredBM25Retriever.module_id,
        StructuredBM25Retriever(config.retrieval, activation),
    )
    # HNSW 向量检索器（配置切换，保留 BM25 便于对比）
    registry.register(
        "retrieval",
        StructuredHNSWRetriever.module_id,
        StructuredHNSWRetriever(config.retrieval, activation),
    )
    registry.register(
        "forgetting",
        LineageRetractionForgetting.module_id,
        LineageRetractionForgetting(
            updater=updater,
            classifier=classifier,
            resolvers=(
                static_resolver,
                dynamic_resolver,
                conditional_resolver,
            ),
            confidence=confidence,
            stability=stability,
            lifecycle=lifecycle,
        ),
    )
    registry.register(
        "reflection",
        GroundedRuleConsolidation.module_id,
        GroundedRuleConsolidation(),
    )
    return registry


def _stage_output(
    *,
    run_id: str,
    stage: str,
    module_id: str,
    input_ids: tuple[str, ...],
    output_ids: tuple[str, ...],
    payload: Mapping[str, Any],
    created_at: str,
) -> StageOutput:
    output_id = "stage-" + uuid5(
        NAMESPACE_URL,
        f"{run_id}:{stage}:{':'.join(output_ids)}",
    ).hex
    return StageOutput(
        output_id=output_id,
        run_id=run_id,
        stage=stage,
        module_id=module_id,
        input_ids=input_ids,
        output_ids=output_ids,
        payload=payload,
        created_at=created_at,
    )
