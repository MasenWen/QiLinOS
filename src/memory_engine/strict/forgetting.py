from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from typing import Any, Mapping, Protocol
from uuid import NAMESPACE_URL, uuid5

from .contracts import (
    LifecycleStatus,
    StrictConflictGroup,
    StrictForgetRequest,
    StrictLifecycleEvent,
    StrictMemory,
    SuppressionRule,
)
from .store import StrictMemoryEngineStore


class IndexDeletionBackend(Protocol):
    backend_id: str

    def delete_memory(self, memory_id: str) -> list[str]: ...

    def residual_search(
        self,
        user_id: str,
        slot_key: str,
        semantic_value: str,
    ) -> list[str]: ...


class LineageRetractionForgetting:
    module_id = "forgetting.lineage_retraction.v1"

    def __init__(
        self,
        *,
        updater: Any,
        classifier: Any,
        resolvers: tuple[Any, ...],
        confidence: Any,
        stability: Any,
        lifecycle: Any,
        index_backend: IndexDeletionBackend | None = None,
    ):
        self.updater = updater
        self.classifier = classifier
        self.resolvers = resolvers
        self.confidence = confidence
        self.stability = stability
        self.lifecycle = lifecycle
        self.index_backend = index_backend

    def forget(
        self,
        store: StrictMemoryEngineStore,
        request: Mapping[str, Any],
        *,
        dry_run: bool,
        now: str | None = None,
    ) -> StrictForgetRequest:
        timestamp = now or datetime.now(timezone.utc).isoformat()
        user_id = str(request.get("user_id") or "").strip()
        if not user_id:
            raise ValueError("strict forget requires user_id")
        selectors = _selectors(request)
        memories = store.list_memories(user_id)
        selected = _select_memories(memories, selectors)
        request_id = "forget-" + uuid5(
            NAMESPACE_URL,
            f"{user_id}|{selectors}|{timestamp}|{dry_run}",
        ).hex
        record = StrictForgetRequest(
            request_id=request_id,
            user_id=user_id,
            selectors=selectors,
            reason=str(request.get("reason") or "user_request"),
            dry_run=dry_run,
            candidate_memory_ids=tuple(
                memory.memory_id for memory in selected
            ),
            status="planned" if dry_run else "executing",
            created_at=timestamp,
            report={
                "candidate_count": len(selected),
                "candidate_memories": [
                    {
                        "memory_id": memory.memory_id,
                        "slot_key": memory.slot_key,
                        "semantic_value": memory.semantic_value,
                        "evidence_ids": list(memory.evidence_ids),
                    }
                    for memory in selected
                ],
            },
        )
        store.put_forget_request(record)
        if dry_run or not selected:
            status = "planned" if dry_run else "completed_no_match"
            completed = replace(
                record,
                status=status,
                completed_at="" if dry_run else timestamp,
            )
            store.put_forget_request(completed)
            return completed

        blocked = [
            replace(
                memory,
                status=LifecycleStatus.BLOCKED,
                version=memory.version + 1,
                updated_at=timestamp,
            )
            for memory in selected
        ]
        for before, after in zip(selected, blocked):
            store.put_memory(after)
            store.put_lifecycle_event(
                _lifecycle_event(
                    before,
                    after,
                    "forget_block_first",
                    timestamp,
                )
            )

        selected_evidence_ids = {
            evidence_id
            for memory in selected
            for evidence_id in memory.evidence_ids
        }
        evidence = store.list_evidence(user_id)
        evidence_by_id = {
            item.evidence_id: item for item in evidence
        }
        retracted_evidence_ids: list[str] = []
        for evidence_id in sorted(selected_evidence_ids):
            if store.set_evidence_status(evidence_id, "retracted"):
                retracted_evidence_ids.append(evidence_id)

        candidates = store.list_candidates(user_id)
        suppressed_candidate_ids: list[str] = []
        for candidate in candidates:
            if candidate.evidence_id in selected_evidence_ids:
                store.set_candidate_status(candidate.candidate_id, "suppressed")
                suppressed_candidate_ids.append(candidate.candidate_id)

        suppression_ids: list[str] = []
        for memory in selected:
            source_ids = tuple(
                dict.fromkeys(
                    observation_id
                    for evidence_id in memory.evidence_ids
                    if evidence_id in evidence_by_id
                    for observation_id in evidence_by_id[
                        evidence_id
                    ].source_observation_ids
                )
            )
            suppression = SuppressionRule(
                suppression_id="suppress-"
                + uuid5(
                    NAMESPACE_URL,
                    (
                        f"{user_id}|{memory.slot_key}|"
                        f"{memory.semantic_value}"
                    ),
                ).hex,
                user_id=user_id,
                slot_key=memory.slot_key,
                semantic_value=memory.semantic_value,
                source_observation_ids=source_ids,
                reason=record.reason,
                active=True,
                created_at=timestamp,
            )
            store.put_suppression(suppression)
            suppression_ids.append(suppression.suppression_id)

        deleted_index_refs: dict[str, list[str]] = {}
        if self.index_backend is not None:
            for memory in selected:
                deleted_index_refs[memory.memory_id] = (
                    self.index_backend.delete_memory(memory.memory_id)
                )

        active_candidates = store.list_candidates(user_id, status="pending")
        rebuilt_impacts, rebuilt_memories = self.updater.apply(
            active_candidates,
            [],
            now=timestamp,
        )
        old_by_id = {memory.memory_id: memory for memory in memories}
        rebuilt_memories = [
            replace(
                memory,
                created_at=old_by_id.get(memory.memory_id, memory).created_at,
                version=old_by_id.get(memory.memory_id, memory).version + 1,
            )
            for memory in rebuilt_memories
        ]
        groups = self.classifier.classify(
            rebuilt_memories,
            now=timestamp,
        )
        rebuilt_by_id = {
            memory.memory_id: memory for memory in rebuilt_memories
        }
        for resolver in self.resolvers:
            groups = [
                resolver.resolve(group, rebuilt_by_id)
                for group in groups
            ]
        rebuilt_memories = self.confidence.score(
            rebuilt_memories,
            groups,
        )
        rebuilt_memories = self.stability.score(
            rebuilt_memories,
            active_candidates,
        )
        rebuilt_memories, lifecycle_events = self.lifecycle.apply(
            rebuilt_memories,
            now=timestamp,
        )
        group_ids_by_memory = {
            memory.memory_id: tuple(
                group.conflict_group_id
                for group in groups
                if memory.memory_id in group.memory_ids
            )
            for memory in rebuilt_memories
        }
        rebuilt_memories = [
            replace(
                memory,
                conflict_group_ids=group_ids_by_memory[memory.memory_id],
            )
            for memory in rebuilt_memories
        ]
        for impact in rebuilt_impacts:
            store.put_impact(impact)
        for memory in rebuilt_memories:
            store.put_memory(memory)
        for event in lifecycle_events:
            store.put_lifecycle_event(event)
        for old_group in store.list_conflict_groups(user_id):
            store.put_conflict_group(
                replace(
                    old_group,
                    status="retracted",
                    winner_memory_id="",
                    unresolved_reason="lineage_recomputed_after_forget",
                    updated_at=timestamp,
                )
            )
        for group in groups:
            store.put_conflict_group(group)

        deleted_memory_ids: list[str] = []
        for blocked_memory in blocked:
            deleted = replace(
                blocked_memory,
                status=LifecycleStatus.DELETED,
                version=blocked_memory.version + 1,
                updated_at=timestamp,
            )
            store.put_memory(deleted)
            store.put_lifecycle_event(
                _lifecycle_event(
                    blocked_memory,
                    deleted,
                    "forget_lineage_deleted",
                    timestamp,
                )
            )
            deleted_memory_ids.append(deleted.memory_id)

        local_residual_ids = [
            memory.memory_id
            for memory in store.list_memories(user_id)
            if memory.memory_id in deleted_memory_ids
            and memory.status
            not in {LifecycleStatus.BLOCKED, LifecycleStatus.DELETED}
        ]
        index_residual_ids: list[str] = []
        if self.index_backend is not None:
            for memory in selected:
                index_residual_ids.extend(
                    self.index_backend.residual_search(
                        user_id,
                        memory.slot_key,
                        memory.semantic_value,
                    )
                )
        report = {
            **record.report,
            "blocked_memory_ids": deleted_memory_ids,
            "retracted_evidence_ids": retracted_evidence_ids,
            "suppressed_candidate_ids": suppressed_candidate_ids,
            "suppression_ids": suppression_ids,
            "deleted_index_refs": deleted_index_refs,
            "recomputed_memory_ids": [
                memory.memory_id for memory in rebuilt_memories
            ],
            "local_residual_ids": local_residual_ids,
            "index_residual_ids": sorted(set(index_residual_ids)),
            "residual_verified": not local_residual_ids
            and not index_residual_ids,
            "index_verification": (
                self.index_backend.backend_id
                if self.index_backend is not None
                else "not_applicable_no_strict_index_refs"
            ),
        }
        completed = replace(
            record,
            status="completed"
            if report["residual_verified"]
            else "residual_detected",
            completed_at=timestamp,
            report=report,
        )
        store.put_forget_request(completed)
        return completed


def _selectors(request: Mapping[str, Any]) -> dict[str, Any]:
    selectors = dict(request.get("selectors") or {})
    for key in ("memory_ids", "slot_key", "semantic_value", "keyword"):
        if request.get(key) not in (None, "", []):
            selectors[key] = request[key]
    if not selectors:
        raise ValueError("strict forget requires at least one selector")
    return selectors


def _select_memories(
    memories: list[StrictMemory],
    selectors: Mapping[str, Any],
) -> list[StrictMemory]:
    memory_ids = set(selectors.get("memory_ids") or ())
    slot_key = str(selectors.get("slot_key") or "").casefold()
    value = str(selectors.get("semantic_value") or "").casefold()
    keyword = str(selectors.get("keyword") or "").casefold()
    selected: list[StrictMemory] = []
    for memory in memories:
        tests = []
        if memory_ids:
            tests.append(memory.memory_id in memory_ids)
        if slot_key:
            tests.append(memory.slot_key.casefold() == slot_key)
        if value:
            tests.append(memory.semantic_value.casefold() == value)
        if keyword:
            tests.append(
                keyword
                in f"{memory.slot_key} {memory.semantic_value}".casefold()
            )
        if tests and all(tests):
            selected.append(memory)
    return selected


def _lifecycle_event(
    before: StrictMemory,
    after: StrictMemory,
    reason: str,
    timestamp: str,
) -> StrictLifecycleEvent:
    identity = (
        f"{before.memory_id}|{before.status.value}|"
        f"{after.status.value}|{after.version}|{reason}"
    )
    return StrictLifecycleEvent(
        event_id="lifecycle-" + uuid5(NAMESPACE_URL, identity).hex,
        memory_id=before.memory_id,
        from_status=before.status,
        to_status=after.status,
        reason_code=reason,
        created_at=timestamp,
    )
