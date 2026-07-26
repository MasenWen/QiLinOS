from __future__ import annotations

import math
import time
from collections.abc import Callable
from datetime import datetime
from typing import Any

from .context import infer_apps, infer_category, infer_memory_type, infer_scene, tokenize
from .models import RetrievalContext, RetrievalResponse, parse_time


SearchBackend = Callable[[str, str, int], list[dict[str, Any]]]


def _metadata(item: dict[str, Any]) -> dict[str, Any]:
    value = item.get("metadata") or {}
    return value if isinstance(value, dict) else {}


def _same(left: str, right: str) -> float:
    if not left or not right:
        return 0.0
    left_normalized = left.strip().lower()
    right_normalized = right.strip().lower()
    if left_normalized == right_normalized:
        return 1.0
    if left_normalized in right_normalized or right_normalized in left_normalized:
        return 0.6
    return 0.0


def _jaccard(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def _timestamp(metadata: dict[str, Any], *names: str) -> datetime | None:
    for name in names:
        parsed = parse_time(metadata.get(name))
        if parsed:
            return parsed
    return None


class StructuredHybridRetriever:
    """MemoryEngine phase-1 retrieval: vector recall plus structured activation."""

    VERSION = "retrieval.structured_hybrid.v1"

    def __init__(self, backend: SearchBackend, candidate_top_k: int = 50):
        self.backend = backend
        self.candidate_top_k = max(5, candidate_top_k)

    def retrieve(self, context: RetrievalContext, top_k: int = 5) -> RetrievalResponse:
        started = time.perf_counter()
        recall_started = time.perf_counter()
        candidates = self.backend(context.query_text, context.user_id, self.candidate_top_k)
        recall_ms = (time.perf_counter() - recall_started) * 1000.0

        category = infer_category(context)
        memory_type = infer_memory_type(category)
        scene = infer_scene(context)
        apps = set(infer_apps(context))
        query_tokens = tokenize(
            " ".join(
                filter(
                    None,
                    (
                        context.query_text,
                        context.task,
                        context.goal,
                        context.current_step,
                        context.memory_need,
                        " ".join(context.known_conditions),
                    ),
                )
            )
        )

        filtered: list[dict[str, Any]] = []
        rejected: list[dict[str, str]] = []
        historical_query = any(term in context.query_text for term in ("以前", "过去", "当时", "历史"))
        for vector_rank, raw in enumerate(candidates, start=1):
            item = dict(raw)
            metadata = _metadata(item)
            status = str(metadata.get("status", "active")).lower()
            if status in {"blocked", "deleted", "archive"}:
                rejected.append({"id": str(item.get("id", "")), "reason": f"status:{status}"})
                continue
            if status == "historical" and not historical_query:
                rejected.append({"id": str(item.get("id", "")), "reason": "historical_not_requested"})
                continue
            start_time = _timestamp(metadata, "valid_from", "start_time", "created_at")
            if context.query_time and start_time and start_time > context.query_time:
                rejected.append({"id": str(item.get("id", "")), "reason": "future_memory"})
                continue
            item["_vector_rank"] = vector_rank
            filtered.append(item)

        raw_scores = [float(item.get("score") or 0.0) for item in filtered]
        score_min = min(raw_scores, default=0.0)
        score_max = max(raw_scores, default=0.0)

        scored: list[dict[str, Any]] = []
        for item in filtered:
            metadata = _metadata(item)
            components: dict[str, float] = {}
            known_weight = 0.0
            weighted = 0.0

            def add_component(name: str, weight: float, actual: str, expected: str) -> None:
                nonlocal known_weight, weighted
                if not expected:
                    return
                value = _same(actual, expected)
                components[name] = value
                known_weight += weight
                weighted += weight * value

            add_component("category", 0.35, str(metadata.get("memory_category", "")), category)
            add_component("memory_type", 0.15, str(metadata.get("memory_type", "")), memory_type)
            add_component("scene", 0.15, str(metadata.get("scene", "")), scene)
            if apps:
                app_score = max((_same(str(metadata.get("app", "")), app) for app in apps), default=0.0)
                components["app"] = app_score
                known_weight += 0.10
                weighted += 0.10 * app_score
            add_component("task_type", 0.25, str(metadata.get("task_type", "")), context.task_type)
            structured = weighted / known_weight if known_weight else 0.0

            memory_tokens = tokenize(
                " ".join(
                    (
                        str(item.get("memory", "")),
                        str(metadata.get("scene", "")),
                        str(metadata.get("app", "")),
                        str(metadata.get("task_type", "")),
                        str(metadata.get("memory_category", "")),
                    )
                )
            )
            lexical = _jaccard(query_tokens, memory_tokens)
            raw_score = float(item.get("score") or 0.0)
            if score_max > score_min:
                semantic = (raw_score - score_min) / (score_max - score_min)
            else:
                semantic = 1.0 / math.sqrt(float(item["_vector_rank"]))

            status = str(metadata.get("status", "active")).lower()
            status_factor = 1.0 if status != "outdated" or historical_query else 0.72
            activation = status_factor * (0.56 * structured + 0.18 * lexical + 0.26 * semantic)

            enriched = dict(item)
            enriched["activation"] = activation
            enriched["activation_components"] = {
                **components,
                "structured": structured,
                "lexical": lexical,
                "semantic": semantic,
                "status_factor": status_factor,
            }
            scored.append(enriched)

        scored.sort(key=lambda item: (-float(item["activation"]), int(item["_vector_rank"])))
        final_items = scored[:top_k]
        for item in final_items:
            item.pop("_vector_rank", None)

        trace = {
            "version": self.VERSION,
            "candidate_top_k": self.candidate_top_k,
            "candidate_count": len(candidates),
            "filtered_count": len(filtered),
            "rejected": rejected,
            "inferred": {
                "memory_category": category,
                "memory_type": memory_type,
                "scene": scene,
                "apps": sorted(apps),
                "task_type": context.task_type,
            },
            "latency_ms": {
                "recall": recall_ms,
                "total": (time.perf_counter() - started) * 1000.0,
            },
        }
        return RetrievalResponse(items=final_items, trace=trace)
