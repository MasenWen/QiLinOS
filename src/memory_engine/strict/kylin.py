from __future__ import annotations

import math
from typing import Any, Protocol

from .contracts import StrictMemory
from .rendering import render_memory


class SemanticScorer(Protocol):
    backend_id: str

    def score(
        self,
        query: str,
        memories: list[StrictMemory],
    ) -> dict[str, float]: ...



class KylinSDKSemanticScorer:
    """Strict semantic scorer backed by the openKylin text embedding SDK.

    Preferred: EmbeddingService with session-pool pattern (prevents ctypes segfault).
    Fallback: Legacy KylinEmbedder (shared-session, may crash after 5-6 calls).

    The SDK wrapper is imported lazily so schema/unit tests can run on
    non-Kylin development hosts.
    """

    backend_id = "openkylin_text_embedding_sdk"

    def __init__(self, embedder: Any | None = None):
        if embedder is not None:
            self._embedder = embedder
        else:
            self._embedder = self._init_embedder()

    def _init_embedder(self):
        """Try EmbeddingService (session-pool) first, fallback to KylinEmbedder."""
        try:
            from src.memory_engine.embedding_service import get_embedding_service
            svc = get_embedding_service()
            if svc.is_available:
                import logging
                logging.getLogger(__name__).info(
                    "KylinSDKSemanticScorer using EmbeddingService (session-pool mode)"
                )
                return svc
        except Exception:
            pass
        from src.memory.kylin_embedder import KylinEmbedder
        return KylinEmbedder()

    def score(
        self,
        query: str,
        memories: list,
    ) -> dict[str, float]:
        if not memories:
            return {}
        from .rendering import render_memory
        documents = [render_memory(memory) for memory in memories]
        ids = [str(getattr(m, "memory_id", "") or "") for m in memories]
        # 2026-09-10 修：EmbeddingService.score() 返回的键是"下标字符串"（{"0":…}），
        # 而 strict/retrieval 是按 memory_id 取值（semantic_scores.get(memory.memory_id)），
        # 旧实现直接转发 → 语义分数恒为 0（语义精排实际未生效）。
        # 这里统一自己算余弦并回填 memory_id；任何提供 embed_batch 的嵌入后端都适用。
        if hasattr(self._embedder, "embed_batch"):
            try:
                try:
                    vectors = self._embedder.embed_batch([query, *documents])
                except TypeError:
                    vectors = self._embedder.embed_batch([query, *documents], "search")
                import numpy as _np
                vectors = [_np.asarray(v, dtype=_np.float32) for v in vectors]
                q = vectors[0]
                qn = float(_np.linalg.norm(q))
                out: dict[str, float] = {}
                for mid, d in zip(ids, vectors[1:]):
                    dn = float(_np.linalg.norm(d))
                    if qn > 0 and dn > 0:
                        out[mid] = max(0.0, min(float(q @ d / (qn * dn)), 1.0))
                    else:
                        out[mid] = 0.0
                return out
            except Exception as _e:
                print(f"[strict.scorer] 语义打分失败，回退：{str(_e)[:120]}", flush=True)
        if hasattr(self._embedder, "score"):
            raw = self._embedder.score(query, documents) or {}
            # 兼容"下标键"实现：按下标映射回 memory_id
            mapped: dict[str, float] = {}
            for k, v in raw.items():
                ks = str(k)
                if ks in ids:
                    mapped[ks] = float(v)
                elif ks.isdigit() and int(ks) < len(ids):
                    mapped[ids[int(ks)]] = float(v)
            return mapped
        # Legacy KylinEmbedder path
        vectors = self._embedder.embed_batch([query, *documents], "search")
        query_vector = vectors[0]
        from math import sqrt
        result = {}
        for memory, vector in zip(memories, vectors[1:]):
            dot = sum(a * b for a, b in zip(query_vector, vector))
            q_norm = sqrt(sum(v * v for v in query_vector))
            d_norm = sqrt(sum(v * v for v in vector))
            if q_norm > 0 and d_norm > 0:
                sim = dot / (q_norm * d_norm)
                result[memory.memory_id] = max(0.0, min(sim, 1.0))
            else:
                result[memory.memory_id] = 0.0
        return result



def _cosine(left: list[float], right: list[float]) -> float:
    numerator = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    value = numerator / (left_norm * right_norm)
    return max(0.0, min(value, 1.0))
