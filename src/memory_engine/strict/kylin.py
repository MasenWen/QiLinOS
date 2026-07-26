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

    The SDK wrapper is imported lazily so schema/unit tests can run on
    non-Kylin development hosts. Production strict retrieval must construct
    this scorer or provide already-computed Kylin scores.
    """

    backend_id = "openkylin_text_embedding_sdk"

    def __init__(self, embedder: Any | None = None):
        if embedder is None:
            from src.memory.kylin_embedder import KylinEmbedder

            embedder = KylinEmbedder()
        self.embedder = embedder

    def score(
        self,
        query: str,
        memories: list[StrictMemory],
    ) -> dict[str, float]:
        if not memories:
            return {}
        documents = [render_memory(memory) for memory in memories]
        vectors = self.embedder.embed_batch([query, *documents], "search")
        query_vector = vectors[0]
        return {
            memory.memory_id: _cosine(query_vector, vector)
            for memory, vector in zip(memories, vectors[1:])
        }

def _cosine(left: list[float], right: list[float]) -> float:
    numerator = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    value = numerator / (left_norm * right_norm)
    return max(0.0, min(value, 1.0))
