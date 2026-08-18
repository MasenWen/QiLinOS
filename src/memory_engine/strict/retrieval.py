from __future__ import annotations

import json
import math
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping
from src.memory_engine.vector_index import HNSWVectorIndex

from .contracts import (
    AtomicEvidence,
    ConflictType,
    LifecycleStatus,
    StrictConflictGroup,
    StrictMemory,
    EvidenceAdmission,
)
from .rendering import render_memory


TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]")


@dataclass(frozen=True)
class StrictRetrievalContext:
    user_id: str
    query_text: str
    query_time: datetime
    task: str = ""
    goal: str = ""
    memory_need: str = ""
    memory_scope: str = ""
    condition: Mapping[str, Any] = field(default_factory=dict)
    include_historical: bool = False

    @classmethod
    def from_mapping(
        cls,
        query: str,
        context: Mapping[str, Any] | None,
    ) -> "StrictRetrievalContext":
        data = dict(context or {})
        query_time = data.get("query_time")
        if isinstance(query_time, datetime):
            parsed_time = query_time
        elif query_time:
            parsed_time = datetime.fromisoformat(
                str(query_time).replace("Z", "+00:00")
            )
        else:
            parsed_time = datetime.now(timezone.utc)
        if parsed_time.tzinfo is None:
            parsed_time = parsed_time.replace(tzinfo=timezone.utc)
        condition = dict(data.get("condition") or {})
        for key in (
            "customer_type",
            "project_id",
            "device_id",
            "account_id",
            "risk_level",
            "task_type",
            "scene",
            "app",
            "activity",
        ):
            if data.get(key) not in (None, ""):
                condition[key] = data[key]
        task = str(data.get("task") or data.get("current_task") or "").strip()
        if task:
            condition.setdefault("task", task)
        memory_need = str(data.get("memory_need") or "").strip()
        return cls(
            user_id=str(data.get("user_id") or "nex_user"),
            query_text=query,
            query_time=parsed_time,
            task=task,
            goal=str(data.get("goal") or data.get("current_goal") or "").strip(),
            memory_need=memory_need,
            memory_scope=_infer_memory_scope(
                str(data.get("memory_scope") or "").strip(),
                f"{query} {memory_need}",
            ),
            condition=condition,
            include_historical=(
                bool(data.get("include_historical"))
                or _infer_historical(f"{query} {memory_need}")
            ),
        )


class StructuredSimilarityActivation:
    module_id = "scoring.activation.structured_similarity.v1"

    def __init__(self, config: Mapping[str, Any]):
        self.weights = {
            "condition": float(config["condition_weight"]),
            "slot": float(config["slot_weight"]),
            "task_goal": float(config["task_goal_weight"]),
            "semantic": float(config["semantic_weight"]),
            "recency": float(config["recency_weight"]),
        }
        self.recency_half_life_days = float(
            config["recency_half_life_days"]
        )

    def score(
        self,
        memory: StrictMemory,
        context: StrictRetrievalContext,
        *,
        semantic_score: float,
    ) -> dict[str, float]:
        condition = _condition_score(memory.condition, context.condition)
        slot = _text_overlap(
            context.memory_need or context.query_text,
            f"{memory.slot_key} {memory.candidate_kind}",
        )
        task_goal = _text_overlap(
            f"{context.task} {context.goal} {context.query_text}",
            " ".join(
                (
                    str(memory.condition.get("task") or ""),
                    str(memory.condition.get("scene") or ""),
                    memory.slot_key,
                )
            ),
        )
        recency = _recency_score(
            memory.valid_from or memory.updated_at,
            context.query_time,
            self.recency_half_life_days,
        )
        components = {
            "condition": condition,
            "slot": slot,
            "task_goal": task_goal,
            "semantic": max(0.0, min(float(semantic_score), 1.0)),
            "recency": recency,
        }
        total = sum(
            self.weights[name] * value
            for name, value in components.items()
        )
        return {
            **{name: round(value, 8) for name, value in components.items()},
            "total": round(total, 8),
        }


class StructuredBM25Retriever:
    module_id = "retrieval.structured_bm25.v1"

    def __init__(
        self,
        config: Mapping[str, Any],
        activation: StructuredSimilarityActivation,
    ):
        self.k1 = float(config["bm25_k1"])
        self.b = float(config["bm25_b"])
        self.lexical_weight = float(config["lexical_weight"])
        self.semantic_weight = float(config["kylin_semantic_weight"])
        self.candidate_limit = int(config["candidate_limit"])
        self.activation = activation

    def retrieve(
        self,
        memories: list[StrictMemory],
        groups: list[StrictConflictGroup],
        context: StrictRetrievalContext,
        *,
        top_k: int,
        kylin_semantic_scores: Mapping[str, float] | None = None,
        semantic_scorer: Any | None = None,
    ) -> dict[str, Any]:
        candidates, hard_filter_trace = _hard_filter(memories, context)
        semantic_backend = "provided_scores"
        if kylin_semantic_scores is None and semantic_scorer is not None:
            kylin_semantic_scores = semantic_scorer.score(
                " ".join(
                    (
                        context.query_text,
                        context.memory_need,
                        context.task,
                        context.goal,
                    )
                ).strip(),
                candidates,
            )
            semantic_backend = semantic_scorer.backend_id
        semantic_scores = dict(kylin_semantic_scores or {})
        documents = {
            item.memory_id: render_memory(item)
            for item in candidates
        }
        lexical_scores = _bm25(
            context.query_text
            + " "
            + context.memory_need
            + " "
            + context.task
            + " "
            + context.goal,
            documents,
            k1=self.k1,
            b=self.b,
        )
        max_lexical = max(lexical_scores.values(), default=0.0)
        normalized_lexical = {
            memory_id: (
                score / max_lexical if max_lexical > 0 else 0.0
            )
            for memory_id, score in lexical_scores.items()
        }

        conflict_decisions = _resolve_conflicts(
            candidates,
            groups,
            context,
        )
        allowed_ids = conflict_decisions["allowed_ids"]
        advisory_ids = set(conflict_decisions["advisory_ids"])
        ranked: list[dict[str, Any]] = []
        for memory in candidates:
            if memory.memory_id not in allowed_ids:
                continue
            lexical = normalized_lexical.get(memory.memory_id, 0.0)
            kylin = max(
                0.0,
                min(float(semantic_scores.get(memory.memory_id, 0.0)), 1.0),
            )
            hybrid = (
                self.lexical_weight * lexical
                + self.semantic_weight * kylin
            )
            activation = self.activation.score(
                memory,
                context,
                semantic_score=hybrid,
            )
            confidence_abstain = bool(memory.confidence.get("abstain", True))
            if confidence_abstain:
                advisory_ids.add(memory.memory_id)
            ranked.append(
                {
                    "memory_id": memory.memory_id,
                    "slot_key": memory.slot_key,
                    "semantic_value": memory.semantic_value,
                    "condition": dict(memory.condition),
                    "status": memory.status.value,
                    "confidence": dict(memory.confidence),
                    "stability": dict(memory.stability),
                    "scores": {
                        "bm25": round(lexical, 8),
                        "kylin_semantic": round(kylin, 8),
                        "hybrid": round(hybrid, 8),
                        "activation": activation,
                    },
                    "decision": (
                        "advisory"
                        if memory.memory_id in advisory_ids
                        else "actionable"
                    ),
                    "lineage": {
                        "evidence_ids": list(memory.evidence_ids),
                        "support_unit_ids": list(memory.support_unit_ids),
                    },
                }
            )
        ranked.sort(
            key=lambda item: (
                item["decision"] == "actionable",
                item["scores"]["activation"]["total"],
                item["scores"]["hybrid"],
                item["memory_id"],
            ),
            reverse=True,
        )
        limited = ranked[: max(0, min(top_k, self.candidate_limit))]
        selected = [
            item["memory_id"]
            for item in limited
            if item["decision"] == "actionable"
        ]
        advisory = [
            item["memory_id"]
            for item in limited
            if item["decision"] == "advisory"
        ]
        return {
            "items": limited,
            "planner": {
                "selected_memory_ids": selected,
                "advisory_memory_ids": advisory,
                "clarifications": conflict_decisions["clarifications"],
                "abstained": bool(not selected and (advisory or conflict_decisions["clarifications"])),
            },
            "trace": {
                "module_id": self.module_id,
                "activation_module_id": self.activation.module_id,
                "hard_filter": hard_filter_trace,
                "conflict_decisions": {
                    key: value
                    for key, value in conflict_decisions.items()
                    if key != "allowed_ids"
                },
                "semantic_backend": (
                    semantic_backend
                    if kylin_semantic_scores is not None
                    else "not_provided"
                ),
                "fallback_used": False,
            },
        }


class StructuredHNSWRetriever:
    """向量检索器：BM25 粗筛 top-N → 麒麟 embedding → HNSW ANN 精排。

    与 StructuredBM25Retriever 输入输出契约完全一致（registry 按 module_id 切换），
    便于两种检索后端对比。config.modules["retrieval"] 选择:
      - "retrieval.structured_bm25.v1"  → 纯 BM25（默认，保留原架构）
      - "retrieval.structured_hnsw.v1"  → BM25 粗筛 + HNSW 向量精排
    """

    module_id = "retrieval.structured_hnsw.v1"

    def __init__(self, config: Mapping[str, Any], activation: Any):
        self.k1 = float(config.get("bm25_k1", 1.5))
        self.b = float(config.get("bm25_b", 0.75))
        self.lexical_weight = float(config.get("lexical_weight", 0.6))
        self.semantic_weight = float(config.get("kylin_semantic_weight", 0.4))
        self.candidate_limit = int(config.get("candidate_limit", 50))
        self.hnsw_dim = int(config.get("hnsw_dim", 768))
        self.hnsw_m = int(config.get("hnsw_m", 16))
        self.hnsw_ef_construction = int(config.get("hnsw_ef_construction", 200))
        self.hnsw_ef = int(config.get("hnsw_ef", 100))
        self.activation = activation
        self._embedder = None

    def _get_embedder(self):
        if self._embedder is None:
            from src.memory.kylin_embedder import KylinEmbedder
            self._embedder = KylinEmbedder()
        return self._embedder

    def _query_text(self, context) -> str:
        return " ".join(
            (
                context.query_text,
                context.memory_need,
                context.task,
                context.goal,
            )
        ).strip()

    def retrieve(
        self,
        memories: list[StrictMemory],
        groups: list[StrictConflictGroup],
        context: StrictRetrievalContext,
        *,
        top_k: int,
        kylin_semantic_scores: Mapping[str, float] | None = None,
        semantic_scorer: Any | None = None,
    ) -> dict[str, Any]:
        candidates, hard_filter_trace = _hard_filter(memories, context)
        documents = {
            item.memory_id: render_memory(item)
            for item in candidates
        }
        # 1) BM25 粗筛 top-N（保留词面召回架构）
        query_text = self._query_text(context)
        lexical_scores = _bm25(query_text, documents, k1=self.k1, b=self.b)
        preselect = sorted(lexical_scores, key=lexical_scores.get, reverse=True)[
            : max(0, min(self.candidate_limit, top_k * 4))
        ]
        if not preselect:
            return {
                "items": [],
                "planner": {"selected_memory_ids": [], "advisory_memory_ids": [], "clarifications": [], "abstained": True},
                "trace": {"module_id": self.module_id, "activation_module_id": self.activation.module_id,
                          "hard_filter": hard_filter_trace, "conflict_decisions": {}, "semantic_backend": "hnsw", "fallback_used": True},
            }
        # 2) 麒麟 embedding 向量化（粗筛候选 + query）
        emb = self._get_embedder()
        qv = emb.embed(query_text[:200])
        vecs = {mid: emb.embed(documents[mid][:150]) for mid in preselect}
        # 3) HNSW ANN 检索
        idx = HNSWVectorIndex(
            dim=self.hnsw_dim,
            m=self.hnsw_m,
            ef_construction=self.hnsw_ef_construction,
            ef=self.hnsw_ef,
        )
        idx.build(list(preselect), [vecs[mid] for mid in preselect], [documents[mid] for mid in preselect])
        ann = idx.search(qv, top_k=max(1, top_k))
        idx.close()
        ann_score = dict(ann)
        ann_ids = set(ann_score)

        # 4) 冲突解决 + 激活 + 分数（与 BM25 检索器同格式）
        conflict_decisions = _resolve_conflicts(candidates, groups, context)
        allowed_ids = conflict_decisions["allowed_ids"]
        advisory_ids = set(conflict_decisions["advisory_ids"])
        max_lexical = max((lexical_scores.get(mid, 0.0) for mid in preselect), default=0.0)
        ranked: list[dict[str, Any]] = []
        for memory in candidates:
            if memory.memory_id not in allowed_ids or memory.memory_id not in ann_ids:
                continue
            lexical_n = (lexical_scores.get(memory.memory_id, 0.0) / max_lexical) if max_lexical > 0 else 0.0
            hnsw = max(0.0, min(float(ann_score.get(memory.memory_id, 0.0)), 1.0))
            hybrid = self.lexical_weight * lexical_n + self.semantic_weight * hnsw
            activation = self.activation.score(memory, context, semantic_score=hybrid)
            confidence_abstain = bool(memory.confidence.get("abstain", True))
            if confidence_abstain:
                advisory_ids.add(memory.memory_id)
            ranked.append(
                {
                    "memory_id": memory.memory_id,
                    "slot_key": memory.slot_key,
                    "semantic_value": memory.semantic_value,
                    "condition": dict(memory.condition),
                    "status": memory.status.value,
                    "confidence": dict(memory.confidence),
                    "stability": dict(memory.stability),
                    "scores": {
                        "bm25": round(lexical_n, 8),
                        "hnsw": round(hnsw, 8),
                        "hybrid": round(hybrid, 8),
                        "activation": activation,
                    },
                    "decision": "advisory" if memory.memory_id in advisory_ids else "actionable",
                    "lineage": {
                        "evidence_ids": list(memory.evidence_ids),
                        "support_unit_ids": list(memory.support_unit_ids),
                    },
                }
            )
        ranked.sort(
            key=lambda item: (
                item["decision"] == "actionable",
                item["scores"]["activation"]["total"],
                item["scores"]["hybrid"],
                item["memory_id"],
            ),
            reverse=True,
        )
        limited = ranked[: max(0, min(top_k, len(ranked)))]
        selected = [item["memory_id"] for item in limited if item["decision"] == "actionable"]
        advisory = [item["memory_id"] for item in limited if item["decision"] == "advisory"]
        return {
            "items": limited,
            "planner": {
                "selected_memory_ids": selected,
                "advisory_memory_ids": advisory,
                "clarifications": conflict_decisions["clarifications"],
                "abstained": bool(not selected and (advisory or conflict_decisions["clarifications"])),
            },
            "trace": {
                "module_id": self.module_id,
                "activation_module_id": self.activation.module_id,
                "hard_filter": hard_filter_trace,
                "conflict_decisions": {
                    key: value for key, value in conflict_decisions.items() if key != "allowed_ids"
                },
                "semantic_backend": "hnsw",
                "fallback_used": False,
            },
        }


def scoped_evidence_memories(
    evidence: list[AtomicEvidence],
    *,
    query_time: datetime | None = None,
) -> list[StrictMemory]:
    latest: dict[tuple[str, str, str], AtomicEvidence] = {}
    for item in evidence:
        if (
            item.status != "active"
            or item.admission is not EvidenceAdmission.SCOPED_ONLY
        ):
            continue
        if query_time is not None and _time(item.observed_time) > query_time:
            continue
        scope_key = (
            item.user_id,
            item.claim_slot,
            json.dumps(
                item.condition,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            ),
        )
        previous = latest.get(scope_key)
        if previous is None or _time(item.observed_time) > _time(
            previous.observed_time
        ):
            latest[scope_key] = item

    result: list[StrictMemory] = []
    for item in sorted(
        latest.values(),
        key=lambda value: (value.observed_time, value.evidence_id),
    ):
        result.append(
            StrictMemory(
                memory_id="scoped-" + item.evidence_id,
                user_id=item.user_id,
                memory_family=item.memory_family,
                candidate_kind=item.candidate_kind,
                slot_key=item.claim_slot,
                semantic_value=item.claim_value,
                condition=dict(item.condition),
                scope={
                    "user_id": item.user_id,
                    "tier": "short_term",
                    "independent_unit_id": item.independent_unit_id,
                },
                cardinality="multi",
                status=LifecycleStatus.CANDIDATE,
                evidence_ids=(item.evidence_id,),
                support_unit_ids=(item.independent_unit_id,),
                oppose_unit_ids=(),
                applicable_unit_ids=(item.independent_unit_id,),
                valid_from=item.valid_from,
                valid_to=item.valid_to,
                predecessor_memory_ids=(),
                successor_memory_ids=(),
                conflict_group_ids=(),
                confidence={
                    "absolute": item.extraction_confidence,
                    "choice": 1.0,
                    "margin": 1.0,
                    "support_independent_units": 1,
                    "oppose_independent_units": 0,
                    "abstain": False,
                    "abstain_reasons": [],
                    "scope": "short_term_evidence",
                },
                stability={
                    "value": 0.0,
                    "scope": "short_term_evidence",
                    "promotion_forbidden": True,
                },
                provenance={
                    "scoped_evidence": True,
                    "directness": item.directness,
                },
                version=1,
                created_at=item.observed_time,
                updated_at=item.observed_time,
            )
        )
    return result


def _hard_filter(
    memories: list[StrictMemory],
    context: StrictRetrievalContext,
) -> tuple[list[StrictMemory], dict[str, list[str]]]:
    included: list[StrictMemory] = []
    excluded: dict[str, list[str]] = {}
    for memory in memories:
        reasons: list[str] = []
        if memory.user_id != context.user_id:
            reasons.append("user_scope")
        if memory.status in {
            LifecycleStatus.BLOCKED,
            LifecycleStatus.DELETED,
            LifecycleStatus.ARCHIVE,
        }:
            reasons.append("inactive_status")
        if (
            memory.status is LifecycleStatus.HISTORICAL
            and not context.include_historical
        ):
            reasons.append("historical_status")
        valid_from = _time(memory.valid_from) if memory.valid_from else None
        valid_to = _time(memory.valid_to) if memory.valid_to else None
        if valid_from and valid_from > context.query_time:
            reasons.append("future_validity")
        if (
            valid_to
            and context.query_time > valid_to
            and not (
                context.include_historical
                and memory.status is LifecycleStatus.HISTORICAL
            )
        ):
            reasons.append("expired_validity")
        memory_scope = str(memory.scope.get("tier") or "mid_term")
        if context.memory_scope and memory_scope != context.memory_scope:
            reasons.append("memory_scope")
        if _condition_score(memory.condition, context.condition) == 0.0:
            reasons.append("condition_conflict")
        if reasons:
            excluded[memory.memory_id] = reasons
        else:
            included.append(memory)
    return included, {
        "included_ids": [item.memory_id for item in included],
        "excluded": excluded,
    }


def _resolve_conflicts(
    memories: list[StrictMemory],
    groups: list[StrictConflictGroup],
    context: StrictRetrievalContext,
) -> dict[str, Any]:
    candidate_ids = {item.memory_id for item in memories}
    by_id = {item.memory_id: item for item in memories}
    allowed = set(candidate_ids)
    advisory: set[str] = set()
    clarifications: list[dict[str, Any]] = []
    for group in groups:
        members = candidate_ids & set(group.memory_ids)
        if len(members) < 2:
            continue
        if (
            group.conflict_type is ConflictType.DYNAMIC
            and context.include_historical
        ):
            continue
        if (
            group.conflict_type
            in {ConflictType.STATIC, ConflictType.DYNAMIC}
            and group.winner_memory_id in members
        ):
            allowed -= members - {group.winner_memory_id}
            continue
        if group.conflict_type is ConflictType.CONDITIONAL:
            matches = [
                memory_id
                for memory_id in members
                if _condition_fully_known(
                    by_id[memory_id].condition,
                    context.condition,
                )
            ]
            if len(matches) == 1:
                allowed -= members - {matches[0]}
                continue
            advisory.update(members)
            clarifications.append(
                {
                    "conflict_group_id": group.conflict_group_id,
                    "slot_key": group.slot_key,
                    "reason": (
                        "multiple_condition_branches_match"
                        if len(matches) > 1
                        else "query_condition_missing_or_unmatched"
                    ),
                    "required_condition_keys": sorted(
                        {
                            key
                            for memory_id in members
                            for key in by_id[memory_id].condition
                            if key not in context.condition
                        }
                    ),
                    "candidate_memory_ids": sorted(members),
                }
            )
            continue
        advisory.update(members)
        clarifications.append(
            {
                "conflict_group_id": group.conflict_group_id,
                "slot_key": group.slot_key,
                "reason": group.unresolved_reason or "conflict_unresolved",
                "candidate_memory_ids": sorted(members),
            }
        )
    return {
        "allowed_ids": allowed,
        "advisory_ids": sorted(advisory),
        "clarifications": clarifications,
    }


def _infer_memory_scope(explicit: str, text: str) -> str:
    normalized = explicit.casefold().replace("-", "_")
    aliases = {
        "short": "short_term",
        "short_term": "short_term",
        "current": "short_term",
        "mid": "mid_term",
        "medium": "mid_term",
        "mid_term": "mid_term",
        "long": "mid_term",
        "long_term": "mid_term",
    }
    if normalized:
        return aliases.get(normalized, "")
    lowered = text.casefold()
    mid_markers = (
        "中期",
        "长期",
        "稳定偏好",
        "稳定模式",
        "经常",
        "习惯",
        "通常",
        "多次",
        "最近一周",
        "最近几天",
        "最近几次",
        "例行",
        "每天",
        "固定的",
        "反复出现",
        "更新后的有效偏好",
        "routine",
        "usually",
        "often",
        "stable pattern",
        "long-term",
        "mid-term",
    )
    short_markers = (
        "短期",
        "刚才",
        "刚刚",
        "本次",
        "当前任务",
        "临时",
        "最近上下文",
        "just ",
        "temporary",
        "current context",
    )
    has_mid = any(marker in lowered for marker in mid_markers)
    has_short = any(marker in lowered for marker in short_markers)
    if has_mid and not has_short:
        return "mid_term"
    if has_short and not has_mid:
        return "short_term"
    return ""


def _infer_historical(text: str) -> bool:
    lowered = text.casefold()
    return any(
        marker in lowered
        for marker in (
            "历史记忆",
            "历史选择",
            "旧偏好",
            "旧记忆",
            "变更前",
            "变化前",
            "更新之前",
            "historical",
            "previous preference",
            "before the change",
        )
    )


def _condition_score(
    memory_condition: Mapping[str, Any],
    query_condition: Mapping[str, Any],
) -> float:
    for key in set(memory_condition) & set(query_condition):
        if memory_condition[key] != query_condition[key]:
            return 0.0
    if not memory_condition:
        return 1.0
    known = sum(
        key in query_condition and query_condition[key] == value
        for key, value in memory_condition.items()
    )
    return 0.5 + 0.5 * (known / len(memory_condition))


def _condition_fully_known(
    memory_condition: Mapping[str, Any],
    query_condition: Mapping[str, Any],
) -> bool:
    return bool(memory_condition) and all(
        key in query_condition and query_condition[key] == value
        for key, value in memory_condition.items()
    )


def _bm25(
    query: str,
    documents: Mapping[str, str],
    *,
    k1: float,
    b: float,
) -> dict[str, float]:
    tokenized = {
        document_id: _tokens(text)
        for document_id, text in documents.items()
    }
    if not tokenized:
        return {}
    query_terms = _tokens(query)
    document_count = len(tokenized)
    average_length = (
        sum(len(tokens) for tokens in tokenized.values()) / document_count
    ) or 1.0
    frequencies = Counter(
        term
        for term in set(query_terms)
        for tokens in tokenized.values()
        if term in tokens
    )
    scores: dict[str, float] = {}
    for document_id, tokens in tokenized.items():
        counts = Counter(tokens)
        score = 0.0
        for term in query_terms:
            document_frequency = frequencies.get(term, 0)
            if document_frequency == 0:
                continue
            inverse_frequency = math.log(
                1
                + (document_count - document_frequency + 0.5)
                / (document_frequency + 0.5)
            )
            frequency = counts[term]
            denominator = frequency + k1 * (
                1 - b + b * len(tokens) / average_length
            )
            score += inverse_frequency * (
                frequency * (k1 + 1) / denominator
            )
        scores[document_id] = score
    return scores


def _tokens(value: str) -> list[str]:
    return [
        token.casefold()
        for token in TOKEN_PATTERN.findall(value)
    ]


def _text_overlap(left: str, right: str) -> float:
    left_tokens = set(_tokens(left))
    right_tokens = set(_tokens(right))
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def _recency_score(
    value: str,
    query_time: datetime,
    half_life_days: float,
) -> float:
    age_days = max(
        (query_time - _time(value)).total_seconds() / 86400,
        0.0,
    )
    return math.exp(-math.log(2) * age_days / half_life_days)


def _time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return (
        parsed
        if parsed.tzinfo is not None
        else parsed.replace(tzinfo=timezone.utc)
    )
