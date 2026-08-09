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
        if hasattr(self._embedder, "score"):
            return self._embedder.score(query, documents)
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
