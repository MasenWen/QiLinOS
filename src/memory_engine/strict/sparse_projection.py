from __future__ import annotations

import hashlib
import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Iterable, Mapping


TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]")


@dataclass(frozen=True)
class SparseProjectionSettings:
    """Configuration for the experimental candidate generator.

    The module is deliberately independent of memory semantics. It only
    proposes candidate IDs; the caller must perform exact rechecking.
    """

    bucket_count: int = 128
    repeats: int = 3
    seed: int = 17
    candidate_k: int = 50
    oversample: int = 4

    def __post_init__(self) -> None:
        if self.bucket_count <= 0 or self.repeats <= 0:
            raise ValueError("bucket_count and repeats must be positive")
        if self.candidate_k <= 0 or self.oversample <= 0:
            raise ValueError("candidate_k and oversample must be positive")


class SparseProjectionIndex:
    """Small deterministic sparse random-projection candidate index.

    This is a candidate generator, not a semantic scorer. A caller should
    still apply hard filters and the existing BM25/Kylin exact ranking.
    """

    def __init__(self, settings: SparseProjectionSettings | None = None):
        self.settings = settings or SparseProjectionSettings()
        self._documents: dict[str, tuple[tuple[str, float], ...]] = {}
        self._postings: list[dict[int, dict[str, float]]] = [
            defaultdict(dict) for _ in range(self.settings.repeats)
        ]

    def upsert(
        self,
        document_id: str,
        features: Mapping[str, float] | Iterable[tuple[str, float]],
    ) -> None:
        self.remove(document_id)
        normalized = _normalize_features(features)
        self._documents[document_id] = normalized
        for repeat, vector in enumerate(self._project(normalized)):
            for bucket, value in vector.items():
                self._postings[repeat][bucket][document_id] = value

    def remove(self, document_id: str) -> None:
        previous = self._documents.pop(document_id, None)
        if previous is None:
            return
        for repeat, vector in enumerate(self._project(previous)):
            for bucket in vector:
                self._postings[repeat].get(bucket, {}).pop(document_id, None)

    def search(
        self,
        features: Mapping[str, float] | Iterable[tuple[str, float]],
        *,
        top_k: int | None = None,
    ) -> list[tuple[str, float]]:
        query = _normalize_features(features)
        if not query or not self._documents:
            return []
        limit = top_k or self.settings.candidate_k
        per_repeat_limit = max(limit * self.settings.oversample, limit)
        scores: dict[str, list[float]] = defaultdict(list)
        projected_query = self._project(query)
        for repeat, query_vector in enumerate(projected_query):
            repeat_scores: dict[str, float] = defaultdict(float)
            for bucket, query_value in query_vector.items():
                for document_id, document_value in self._postings[repeat].get(
                    bucket, {}
                ).items():
                    repeat_scores[document_id] += query_value * document_value
            ranked = sorted(
                repeat_scores.items(),
                key=lambda item: (-item[1], item[0]),
            )[:per_repeat_limit]
            for document_id, value in ranked:
                scores[document_id].append(value)

        ranked = []
        for document_id, values in scores.items():
            padded = values + [0.0] * (self.settings.repeats - len(values))
            padded.sort()
            median = padded[len(padded) // 2]
            ranked.append((document_id, median))
        ranked.sort(key=lambda item: (-item[1], item[0]))
        return ranked[:limit]

    def _project(
        self,
        features: Iterable[tuple[str, float]],
    ) -> list[dict[int, float]]:
        vectors = [defaultdict(float) for _ in range(self.settings.repeats)]
        for feature, value in features:
            for repeat in range(self.settings.repeats):
                bucket, sign = _bucket_and_sign(
                    feature,
                    seed=self.settings.seed,
                    repeat=repeat,
                    bucket_count=self.settings.bucket_count,
                )
                vectors[repeat][bucket] += sign * value
        return [dict(vector) for vector in vectors]


def text_features(text: str) -> dict[str, float]:
    """Encode text into deterministic sparse lexical features for smoke use."""

    return {
        f"token:{token}": float(count)
        for token, count in Counter(
            token.casefold() for token in TOKEN_PATTERN.findall(text)
        ).items()
    }


def _normalize_features(
    features: Mapping[str, float] | Iterable[tuple[str, float]],
) -> tuple[tuple[str, float], ...]:
    values = features.items() if isinstance(features, Mapping) else features
    normalized = [
        (str(feature), float(value))
        for feature, value in values
        if str(feature) and math.isfinite(float(value)) and float(value) != 0.0
    ]
    normalized.sort()
    return tuple(normalized)


def _bucket_and_sign(
    feature: str,
    *,
    seed: int,
    repeat: int,
    bucket_count: int,
) -> tuple[int, float]:
    payload = f"{seed}:{repeat}:{feature}".encode("utf-8")
    digest = hashlib.blake2b(payload, digest_size=16).digest()
    number = int.from_bytes(digest, "big")
    bucket = number % bucket_count
    sign = 1.0 if (number >> 8) & 1 else -1.0
    return bucket, sign
