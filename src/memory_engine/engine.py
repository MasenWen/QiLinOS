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
from .store import MemoryEngineStore
from dataclasses import replace
from .updater import apply_evidence
from .tag_pipeline import TagClassifier
from .knowledge_graph import KnowledgeGraph, EdgeType
from .matched import Matched, _stable_key
from .forgetting_curve import ForgettingCurve, ForgettingCurveConfig


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
        # 文档未激活组件（第 5/6/9/10 章）：惰性初始化
        self._tag_classifier = TagClassifier()
        self._forgetting_curve = ForgettingCurve(ForgettingCurveConfig())
        self._kg_path = os.path.expanduser("~/.nex-agent/memory_kg.json")
        self._kg = None

    def ingest_event(
        self,
        event: Mapping[str, Any],
        *,
        segment: bool = True,
    ) -> dict[str, Any]:
        """Normalize and persist one source event without triggering extraction."""
        from security import get_memory_guard, get_audit_logger

        store = self.store or MemoryEngineStore()
        try:
            observation = observation_from_event(event)
        except ValueError as exc:
            return {"status": "skipped", "reason": str(exc)}

        # Security guard: review observation content before persisting
        guard = get_memory_guard()
        review = guard.review(observation.content, category="observation", source="ingest_event")
        if not review.allowed:
            get_audit_logger().log_memory_review(
                "observation", "ingest_event", False, review.threat_ids, review.reason,
            )
            return {"status": "skipped", "reason": f"unsafe_content: {review.reason}"}
        if review.threat_ids or review.pii_redactions > 0:
            get_audit_logger().log_memory_review(
                "observation", "ingest_event", True, review.threat_ids, review.reason,
            )

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
        # 后台 LLM 槽位精修（异步，不阻塞；失败保留规则槽位）
        try:
            from .slot_llm import schedule_slot_review
            schedule_slot_review(memory.memory_id, str(memory.semantic_value))
        except Exception:
            pass

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
        # 后台 LLM 槽位精修（异步，不阻塞；失败保留规则槽位）
        try:
            from .slot_llm import schedule_slot_review
            schedule_slot_review(memory.memory_id, str(memory.semantic_value))
        except Exception:
            pass

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
        # 消费方：恢复案例（recovery_case）证据沉淀到知识图谱（工具经验复用）。
        # evidence 表本身是 shadow 审计用途（工具结果不进长期记忆，防污染），
        # 但"失败→恢复"案例有长期复用价值 → 写入 KG → _kg_prompt_block 注入对话。
        try:
            _kg = self._get_kg()
            _added = 0
            for item in evidence:
                if getattr(item, "memory_category", "") == "recovery_case":
                    _cond = dict(getattr(item, "condition", None) or {})
                    _text = f"{getattr(item, 'claim_value', '')}（错误: {_cond.get('error_signature', '')}）"
                    _kg.add_node(label="recovery_case", text=_text[:100], strength=0.6)
                    _added += 1
            if _added:
                _kg.save(self._kg_path)
                print(f"[MemoryEngine] {_added} 条恢复案例 → 知识图谱", flush=True)
        except Exception as _e:
            print(f"[MemoryEngine] recovery_case→KG 跳过: {_e}", flush=True)

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
        # 后台 LLM 槽位精修（异步，不阻塞；失败保留规则槽位）
        try:
            from .slot_llm import schedule_slot_review
            schedule_slot_review(memory.memory_id, str(memory.semantic_value))
        except Exception:
            pass

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

    def retrieve_matched(
        self,
        query: str,
        context: Mapping[str, Any] | RetrievalContext | None = None,
        top_k: int = 5,
        user_id: str | None = None,
    ) -> list[Matched]:
        """检索并生成 MATCHED 六字段结构化结果（技术报告第 6 章）。"""
        resp = self.retrieve(query, context, top_k=top_k, user_id=user_id)
        matched: list[Matched] = []
        for item in resp.items:
            text = str(item.get("text") or item.get("memory")
                       or item.get("content") or item.get("semantic_value") or "")
            if not text:
                continue
            try:
                tags = self._tag_classifier.classify(text)
            except Exception:
                tags = {}
            label_scores = {k: len(v) for k, v in tags.items() if isinstance(v, (list, tuple))}
            matched.append(Matched(
                key=_stable_key(text),
                condition="、".join(tags.get("condition", [])),
                obj="、".join(tags.get("obj", [])),
                preference="、".join(tags.get("preferences", [])),
                lasttime="、".join(tags.get("lastingtime", [])),
                text_input=text,
                matched_rate=float(item.get("score", item.get("matched_rate", 0.0)) or 0.0),
                label_scores=label_scores,
            ))
        return matched

    def _get_kg(self) -> KnowledgeGraph:
        """惰性加载知识图谱（JSON 持久化）。"""
        if self._kg is None:
            self._kg = KnowledgeGraph.load(self._kg_path)
        return self._kg

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
        from security import get_memory_guard, get_audit_logger

        if not fact or not fact.strip():
            return {"status": "skipped", "reason": "empty_fact"}

        # Security guard: replace is_engine_safe with full memory guard review
        guard = get_memory_guard()
        review = guard.review(fact, category="fact", source="remember_fact")
        if not review.allowed:
            get_audit_logger().log_memory_review(
                "fact", "remember_fact", False, review.threat_ids, review.reason,
            )
            return {"status": "skipped", "reason": f"unsafe_content: {review.reason}"}
        if review.threat_ids or review.pii_redactions > 0:
            get_audit_logger().log_memory_review(
                "fact", "remember_fact", True, review.threat_ids, review.reason,
            )
        fact = review.sanitized_text

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
        # --- 四主标签标注（技术报告 5.2）---
        try:
            tags = self._tag_classifier.classify(fact)
            if tags:
                extractor = dict(evidence.extractor)
                extractor["tag_pipeline_v1"] = {"labels": tags}
                # Evidence 是 frozen dataclass，须用 replace 重建
                evidence = replace(evidence, extractor=extractor)
        except Exception:
            pass
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

        # --- 知识图谱同步（技术报告 9 章）+ 遗忘强度（10.2 章）---
        kg_info = {}
        try:
            kg = self._get_kg()
            strength = self._forgetting_curve.reinforce(1.0)
            before = len(kg._nodes)
            node = kg.add_node(label=memory.memory_family, text=fact, strength=strength)
            if len(kg._nodes) == before:
                # 节点已存在（重复事实）→ AYES 强化边
                kg.add_edge(node.id, node.id, EdgeType.AYES, weight=strength)
            kg.save(self._kg_path)
            kg_info = {"nodes": len(kg._nodes), "edges": len(kg._edges),
                       "strength": round(strength, 3)}
        except Exception:
            pass

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

        # 后台 LLM 槽位精修（异步，不阻塞；失败保留规则槽位）
        try:
            from .slot_llm import schedule_slot_review
            schedule_slot_review(memory.memory_id, str(memory.semantic_value))
        except Exception:
            pass

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
            "tags": dict(evidence.extractor.get("tag_pipeline_v1", {})) if evidence else {},
            "kg": kg_info,
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
