# -*- coding: utf-8 -*-
"""内存充足条件下的检索优化：稀疏草图**候选扩展** + 贝叶斯先验平滑。

两项优化均以"内存充足"为前提（判定见 :mod:`resource_gate`），并遵守两条原则：

1. **不劣化基线**：草图用于“扩展”候选，而不是裁剪掉向量检索已给出的候选——
   最终候选集为"向量序前 K 条"与"草图相关度最高的 K 条"的并集（上限 2K），
   因此相较未启用时不会丢失任何原有候选，只是多出草图发现的候选。
2. **可回落、可观测**：未启用时本模块不参与检索，行为与既有精确路径一致；
   启用时把判定原因、召回规模、扩展条数与先验权重一并写入检索 trace。

对应手册第六章两项创新：高维稀疏检索（草图候选召回）与贝叶斯个性化记忆更新（先验混合）。
"""
from __future__ import annotations

import time
import zlib
from typing import Any, Iterable, Mapping, Sequence

from ..innovations.bayes_personalization import mixture_prediction, peer_weights
from ..innovations.sparse_sketch import SparseSketch, SparseVector

VERSION = "retrieval.optimization.v1"
DEFAULT_SKETCH_BUCKETS = 256
DEFAULT_KAPPA_G = 5.0


def token_coordinate(token: str) -> int:
    """词元 → 稀疏向量坐标（稳定哈希，跨进程一致）。"""
    return zlib.crc32(token.encode("utf-8")) & 0x7FFFFFFF


def tokens_to_sparse(tokens: Iterable[str]) -> SparseVector:
    """词元序列 → 稀疏向量（坐标=词元哈希，权重=词频）。"""
    vector: SparseVector = {}
    for token in tokens:
        text = str(token or "").strip()
        if not text:
            continue
        coord = token_coordinate(text)
        vector[coord] = vector.get(coord, 0.0) + 1.0
    return vector


class SketchCandidateExtender:
    """用低维草图估计相关度，为向量召回结果补充额外候选。

    复杂度与候选的非零坐标总数成正比，不构造稠密矩阵——这正是"内存充足时可用、
    内存紧张时可关"的工程前提。
    """

    def __init__(self, buckets: int = DEFAULT_SKETCH_BUCKETS, seed: int = 0):
        if buckets < 1:
            raise ValueError("草图桶数需 >= 1")
        self.buckets = int(buckets)
        self.sketch = SparseSketch(int(buckets), seed=seed)

    def extend(
        self,
        query_vector: SparseVector,
        entries: Sequence[tuple[Any, SparseVector]],
        base_keep: int,
        extra_keep: int,
    ) -> tuple[list[Any], dict[str, Any]]:
        """返回 (候选列表, 元信息)。

        ``entries`` 需按**向量检索原序**给出（下标即向量序）；返回结果保留原序前
        ``base_keep`` 条，并补入草图相关度最高的 ``extra_keep`` 条（不重复计入）。
        """
        started = time.perf_counter()
        head = list(entries[: max(0, int(base_keep))])
        rest = list(entries[max(0, int(base_keep)):])
        extras: list[Any] = []
        scored_pairs: list[tuple[float, Any]] = []
        if rest and extra_keep > 0 and query_vector:
            for item, vector in rest:
                if not vector:
                    continue
                scored_pairs.append((self.sketch.correlation(query_vector, vector), item))
            scored_pairs.sort(key=lambda pair: -pair[0])
            extras = [item for _, item in scored_pairs[: int(extra_keep)]]
        kept = [item for item, _ in head] + extras
        meta = {
            "version": VERSION,
            "buckets": self.buckets,
            "candidates": len(entries),
            "base": len(head),
            "sketch_added": len(extras),
            "kept": len(kept),
            "extend_ms": round((time.perf_counter() - started) * 1000.0, 3),
        }
        return kept, meta


def bayes_prior_adjust(
    score: float,
    evidence_n: float,
    peer_prior: float,
    kappa_g: float = DEFAULT_KAPPA_G,
) -> tuple[float, dict[str, Any]]:
    """按贝叶斯个性化更新对单条得分做先验混合。

    ``lambda_g = kappa_g / (kappa_g + n)``、``lambda_u = n / (kappa_g + n)``，
    混合结果 ``lambda_g * peer_prior + lambda_u * score``：
    个人证据少（冷启动）时结果向群体参考靠拢，证据积累后逐步回到个人得分。
    """
    lam_g, lam_u = peer_weights(max(0.0, float(kappa_g)), max(0.0, float(evidence_n)))
    adjusted = mixture_prediction(lam_g, float(peer_prior), lam_u, float(score))
    clamped = min(1.0, max(0.0, float(adjusted)))
    return clamped, {
        "lambda_g": round(lam_g, 6),
        "lambda_u": round(lam_u, 6),
        "evidence_n": float(evidence_n),
        "peer_prior": round(float(peer_prior), 6),
        "score_before": round(float(score), 6),
    }


def apply_prior_smoothing(
    items: list[dict[str, Any]],
    evidence_n: float | None,
    kappa_g: float = DEFAULT_KAPPA_G,
) -> dict[str, Any] | None:
    """对候选得分做一次先验混合；证据量未知时不做改动并说明原因。

    先验取**逐候选的群体系信号**（``activation_components["semantic"]``，即通用向量相似度），
    而不是候选集均分——后者在冷启动时会把所有分数拉平、反而破坏排序。
    语义分量缺失时退回候选集均分作为兜底。
    """
    if evidence_n is None:
        return {"active": False, "reason": "evidence_provider_unavailable"}
    if not items:
        return {"active": False, "reason": "no_candidates"}
    scores = [float(item.get("activation") or 0.0) for item in items]
    fallback_prior = sum(scores) / len(scores)
    for item in items:
        components = item.get("activation_components")
        peer = None
        if isinstance(components, dict):
            raw = components.get("semantic")
            if isinstance(raw, (int, float)):
                peer = float(raw)
        adjusted, meta = bayes_prior_adjust(
            float(item.get("activation") or 0.0),
            float(evidence_n),
            fallback_prior if peer is None else peer,
            kappa_g,
        )
        meta["peer_source"] = "fallback_mean" if peer is None else "item_semantic"
        item["activation"] = adjusted
        if isinstance(components, dict):
            components["bayes_prior"] = meta
    return {
        "active": True,
        "version": VERSION,
        "evidence_n": float(evidence_n),
        "kappa_g": float(kappa_g),
        "peer_source": "item_semantic",
        "peer_fallback_mean": round(fallback_prior, 6),
    }


def route_summary(decision: Mapping[str, Any], prune: Mapping[str, Any] | None,
                  bayes: Mapping[str, Any] | None) -> str:
    """把一次优化路由压成一行，便于运行追溯。"""
    if not decision.get("enabled"):
        return "优化未启用（原因：%s）" % decision.get("reason")
    parts = ["优化已启用"]
    if prune:
        parts.append("候选 %s→%s（草图补入 %s）" % (prune.get("candidates"), prune.get("kept"),
                                                 prune.get("sketch_added")))
    if bayes and bayes.get("active"):
        parts.append("先验平滑 n=%s" % bayes.get("evidence_n"))
    elif bayes:
        parts.append("先验平滑未生效（%s）" % bayes.get("reason"))
    return "，".join(parts)
