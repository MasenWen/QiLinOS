from __future__ import annotations

import hashlib
import os
import time
from datetime import datetime, timezone
from typing import Any, Mapping

from .episode import EpisodeManager
from .episode_extractors import extract_episode_evidence
from .extractors import explicit_fact_to_evidence
from .forgetting import LineageForgetter
from .models import RetrievalContext, RetrievalResponse
from .normalizers import dialogue_to_observation, observation_from_event
from .retrieval import SearchBackend, StructuredHybridRetriever
from .security import is_engine_safe
from .store import MemoryEngineStore
from .updater import apply_evidence


class MemoryEngine:
    """Strangler facade for MemoryEngine modules.

    Phase 1 replaces retrieval only. The backend remains Mem0 so write and
    lifecycle behavior can be migrated independently in later phases.
    """

    def __init__(
        self,
        search_backend: SearchBackend | None = None,
        candidate_top_k: int = 50,
        store: MemoryEngineStore | None = None,
    ):
        search_backend = search_backend or (lambda _query, _user_id, _limit: [])
        self.retriever = StructuredHybridRetriever(search_backend, candidate_top_k=candidate_top_k)
        self.store = store

    def ingest_event(
        self,
        event: Mapping[str, Any],
        *,
        segment: bool = True,
    ) -> dict[str, Any]:
        """Normalize and persist one source event without triggering extraction."""
        store = self.store or MemoryEngineStore()
        try:
            observation = observation_from_event(event)
        except ValueError as exc:
            return {"status": "skipped", "reason": str(exc)}

        created = store.put_observation(observation)
        episode = store.find_episode_for_observation(observation.observation_id)
        boundary = None
        if segment and created:
            episode, decision = EpisodeManager(store).attach(observation)
            boundary = decision.to_dict()
            if (
                episode.status == "closed"
                and self._evidence_mode() == "shadow_episode_v1"
            ):
                self.extract_evidence(episode.episode_id, persist=True)
        return {
            "status": "ok",
            "observation_id": observation.observation_id,
            "observation_created": created,
            "source_type": observation.source_type,
            "schema_valid": bool(observation.completeness.get("schema_valid")),
            "episode_id": episode.episode_id if episode else None,
            "episode_status": episode.status if episode else None,
            "boundary": boundary,
        }

    def close_episode(
        self,
        session_id: str | int,
        *,
        user_id: str = "nex_user",
        reason: str = "manual",
    ) -> dict[str, Any]:
        store = self.store or MemoryEngineStore()
        episode = store.latest_open_episode(user_id, str(session_id))
        if episode is None:
            return {"status": "skipped", "reason": "open_episode_not_found"}
        last = (
            store.get_observation(episode.observation_ids[-1])
            if episode.observation_ids
            else None
        )
        episode.status = "closed"
        episode.end_time = last.event_time if last else datetime.now(timezone.utc).isoformat()
        episode.boundary_reason = reason
        episode.boundary_confidence = 1.0 if reason == "manual" else 0.8
        store.put_episode(episode)
        extraction = None
        if self._evidence_mode() == "shadow_episode_v1":
            extraction = self.extract_evidence(episode.episode_id, persist=True)
        return {
            "status": "ok",
            "episode_id": episode.episode_id,
            "episode_status": episode.status,
            "extraction": extraction,
        }

    def extract_evidence(
        self,
        episode_id: str,
        *,
        persist: bool = True,
    ) -> dict[str, Any]:
        """Run the Episode Evidence Baseline in shadow mode."""
        started = time.perf_counter()
        store = self.store or MemoryEngineStore()
        evidence = extract_episode_evidence(store, episode_id)
        created_ids: list[str] = []
        if persist:
            for item in evidence:
                if store.put_evidence(item):
                    created_ids.append(item.evidence_id)

        run_id = self._stable_id(
            "run",
            f"episode_evidence.shadow.v1|{episode_id}",
        )
        created_at = datetime.now(timezone.utc).isoformat()
        store.put_engine_run(
            {
                "run_id": run_id,
                "operation": "extract_episode_evidence",
                "module_versions": {
                    "episode": "episode.initial_rule.v1",
                    "evidence": "evidence.episode_shadow.v1",
                    "impact": "disabled",
                    "memory_update": "disabled",
                },
                "input_ids": [episode_id],
                "output_ids": [item.evidence_id for item in evidence],
                "trace": {
                    "shadow": True,
                    "persist": persist,
                    "created_ids": created_ids,
                    "evidence_types": [item.evidence_type for item in evidence],
                    "memory_categories": [
                        item.memory_category for item in evidence
                    ],
                },
                "status": "ok",
                "latency_ms": (time.perf_counter() - started) * 1000.0,
                "created_at": created_at,
            }
        )
        return {
            "status": "ok",
            "mode": "shadow_episode_v1",
            "episode_id": episode_id,
            "evidence_count": len(evidence),
            "evidence_ids": [item.evidence_id for item in evidence],
            "created_count": len(created_ids),
            "shadow": True,
        }

    def retrieve(
        self,
        query: str,
        context: Mapping[str, Any] | RetrievalContext | None = None,
        top_k: int = 5,
        user_id: str | None = None,
    ) -> RetrievalResponse:
        if isinstance(context, RetrievalContext):
            current = context
        else:
            current = RetrievalContext.from_mapping(query, context, user_id=user_id)
        return self.retriever.retrieve(current, top_k=top_k)

    def remember_fact(
        self,
        fact: str,
        *,
        mem0_store_obj=None,
        source_text: str | None = None,
        context: Mapping[str, Any] | None = None,
        index: bool = True,
    ) -> dict[str, Any]:
        """Persist one reviewed fact through Observation/Evidence/Impact/Memory."""
        if not fact or not fact.strip():
            return {"status": "skipped", "reason": "empty_fact"}
        if not is_engine_safe(fact):
            return {"status": "skipped", "reason": "unsafe_content"}
        store = self.store or MemoryEngineStore()
        current = dict(context or {})
        user_id = str(current.get("user_id") or "nex_user")
        session_id = str(current.get("session_id") or "unknown")
        event_time = str(current.get("event_time") or datetime.now(timezone.utc).isoformat())
        source_event_id = str(current.get("source_event_id") or "") or None
        observation = dialogue_to_observation(
            source_text or fact,
            actor="user",
            user_id=user_id,
            session_id=session_id,
            source_event_id=source_event_id,
            event_time=event_time,
            context=current,
        )
        observation_created = store.put_observation(observation)
        episode = store.find_episode_for_observation(observation.observation_id)
        if observation_created:
            episode, _ = EpisodeManager(store).attach(observation)
        evidence = explicit_fact_to_evidence(observation, fact)
        evidence_created = store.put_evidence(evidence)
        memory = store.find_memory(evidence.user_id, evidence.claim_slot, evidence.claim_value)
        if evidence_created or memory is None:
            memory, impact = apply_evidence(store, evidence)
        else:
            impact = {
                "impact_id": "",
                "evidence_id": evidence.evidence_id,
                "target_memory_id": memory.memory_id,
                "action": "NOOP",
                "reason_code": "duplicate_source_event",
            }

        indexed_ids: list[str] = []
        if index and mem0_store_obj is not None and not store.get_index_refs(memory.memory_id):
            metadata = {
                "memory_id": memory.memory_id,
                "memory_family": memory.memory_family,
                "memory_type": memory.memory_type,
                "memory_category": memory.memory_category,
                "status": memory.status,
                "slot_key": memory.slot_key,
                "start_time": memory.created_at,
                "schema_version": memory.schema_version,
            }
            result = mem0_store_obj._memory.add(
                memory.semantic_value,
                user_id=user_id,
                infer=False,
                metadata=metadata,
            )
            indexed_ids = self._extract_index_ids(result)
            for backend_id in indexed_ids:
                store.put_index_ref(
                    memory.memory_id,
                    backend_id,
                    updated_at=memory.updated_at,
                )

        return {
            "status": "ok",
            "observation_id": observation.observation_id,
            "observation_created": observation_created,
            "episode_id": episode.episode_id if episode else None,
            "evidence_id": evidence.evidence_id,
            "evidence_created": evidence_created,
            "impact_id": impact["impact_id"],
            "impact_action": impact["action"],
            "memory_id": memory.memory_id,
            "memory_status": memory.status,
            "indexed_ids": indexed_ids,
            "store_counts": store.counts(),
        }

    def forget(
        self,
        keyword: str,
        *,
        user_id: str = "nex_user",
        dry_run: bool = True,
        mem0_store_obj=None,
    ) -> dict[str, Any]:
        store = self.store or MemoryEngineStore()
        return LineageForgetter(store, mem0_store_obj=mem0_store_obj).forget(
            keyword,
            user_id,
            dry_run=dry_run,
        )

    @staticmethod
    def _extract_index_ids(result: Any) -> list[str]:
        if isinstance(result, dict):
            values = result.get("results") or result.get("data") or []
        elif isinstance(result, list):
            values = result
        else:
            values = []
        ids = []
        for value in values:
            if isinstance(value, dict) and value.get("id"):
                ids.append(str(value["id"]))
        return ids

    @staticmethod
    def _evidence_mode() -> str:
        return os.getenv("NEX_MEMORY_EVIDENCE_MODE", "off").strip().lower()

    @staticmethod
    def _stable_id(prefix: str, value: str) -> str:
        return f"{prefix}_{hashlib.sha256(value.encode('utf-8')).hexdigest()[:24]}"
