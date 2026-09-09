"""高维稀疏记忆检索 — 独立算法模块。

对应手册第六章 6.3 与第八章 8.4.2：稀疏表示 + 哈希随机投影
（每个特征一个桶、独立随机符号）→ 低维草图无偏内积估计 →
Top-k 候选召回 → 原空间复核。

符号与手册一致：
- 投影矩阵 ``R[j][ell] = sigma(j) if h(j) == ell else 0``；
- 单次草图内积估计 ``s_hat(x,z) = <xR, zR>``，满足
  ``E[s_hat] = <x,z>`` 且 ``Var[s_hat] <= ||x||^2 ||z||^2 / m``；
- 归一化相关度 ``rho = <x,z> / (||x|| ||z||)``，r 次独立草图取中位数；
- 参数关系：``m >= 4/eps^2``、``r >= 8 log(2/delta)`` 时
  ``Pr(|rho_hat - rho| > eps) <= delta``。

记忆表示为 ``dict[int, float]``（仅存非零坐标）。所有函数纯计算、无副作用。
"""
from __future__ import annotations

import math
import random
from statistics import median
from typing import Dict, List, Optional, Sequence, Tuple

SparseVector = Dict[int, float]


class SparseSketch:
    """稀疏随机投影器：d 维稀疏向量 -> m 维草图。

    哈希 ``h(j)`` 与符号 ``sigma(j)`` 在首次访问坐标时由种子随机生成并缓存，
    保证同一实例内投影一致；``m`` 为桶数（草图维度）。
    """

    def __init__(self, m: int, seed: int = 0):
        if m < 1:
            raise ValueError("桶数 m 需 >= 1")
        self.m = m
        self._seed = seed
        self._rng = random.Random(seed)
        self._h: Dict[int, int] = {}
        self._s: Dict[int, int] = {}

    def _coord(self, j: int) -> Tuple[int, int]:
        """惰性生成坐标 j 的 (桶号, 符号)。"""
        if j not in self._h:
            self._h[j] = self._rng.randrange(self.m)
            self._s[j] = 1 if self._rng.random() < 0.5 else -1
        return self._h[j], self._s[j]

    # ------------------------------------------------------------------
    def project(self, x: SparseVector) -> List[float]:
        """单条稀疏向量 -> m 维草图 ``y = xR``（只遍历非零坐标）。"""
        y = [0.0] * self.m
        for j, v in x.items():
            if v == 0.0:
                continue
            h_j, s_j = self._coord(j)
            y[h_j] += s_j * v
        return y

    def project_many(self, xs: Sequence[SparseVector]) -> List[List[float]]:
        """批量投影（候选生成阶段使用，复杂度与总非零坐标数成正比）。"""
        return [self.project(x) for x in xs]

    # ------------------------------------------------------------------
    def inner_estimate(self, x: SparseVector, z: SparseVector) -> float:
        """单次草图内积估计 ``s_hat = <xR, zR>``。"""
        yx = self.project(x)
        yz = self.project(z)
        return sum(a * b for a, b in zip(yx, yz))

    @staticmethod
    def _norm(x: SparseVector) -> float:
        return math.sqrt(sum(v * v for v in x.values()))

    def correlation(self, x: SparseVector, z: SparseVector) -> float:
        """单草图归一化相关度估计 ``rho_hat``。"""
        nx, nz = self._norm(x), self._norm(z)
        if nx == 0 or nz == 0:
            return 0.0
        return self.inner_estimate(x, z) / (nx * nz)

    def median_correlation(self, x: SparseVector, z: SparseVector,
                           r: int) -> float:
        """r 次独立草图（不同种子）的归一化相关度估计取中位数 ``rho_hat_r``。"""
        if r < 1:
            raise ValueError("r 需 >= 1")
        vals = []
        for t in range(r):
            sk = SparseSketch(self.m, seed=self._seed * 7919 + t)
            vals.append(sk.correlation(x, z))
        return median(vals)


def sketch_candidate_recall(xs: Sequence[SparseVector],
                            query: SparseVector,
                            top_k: int,
                            m: int,
                            seed: int = 0,
                            cand_factor: float = 3.0,
                            ) -> Tuple[List[int], List[float], Dict[str, float]]:
    """低维候选召回 + 原空间复核。

    1. 全部记忆投影为 m 维草图；
    2. 按草图内积取 ``top_k * cand_factor`` 个候选；
    3. 候选回原空间精排，返回最终 ``top_k`` 下标与相关度。

    返回 ``(ids, scores, stats)``；``stats`` 含候选规模等过程信息。
    """
    if top_k < 1 or m < 1:
        raise ValueError("top_k 与 m 需 >= 1")
    sk = SparseSketch(m, seed=seed)
    yq = sk.project(query)
    ys = sk.project_many(xs)
    scored = [(i, sum(a * b for a, b in zip(yq, ys[i]))) for i in range(len(xs))]
    cand_n = max(top_k, min(len(xs), int(top_k * cand_factor)))
    cand = sorted(scored, key=lambda t: t[1], reverse=True)[:cand_n]
    qn = SparseSketch._norm(query)
    refined = []
    for i, _ in cand:
        xn = SparseSketch._norm(xs[i])
        if qn == 0 or xn == 0:
            refined.append((i, 0.0))
        else:
            inner = sum(v * xs[i].get(j, 0.0) for j, v in query.items())
            refined.append((i, inner / (qn * xn)))
    refined.sort(key=lambda t: t[1], reverse=True)
    top = refined[:top_k]
    return ([i for i, _ in top], [s for _, s in top],
            {"candidates": len(cand), "projected": len(xs)})


def brute_force_topk(xs: Sequence[SparseVector],
                     query: SparseVector,
                     top_k: int) -> Tuple[List[int], List[float]]:
    """全量原空间比较基线（O(n d)，仅作对照与测试）。"""
    qn = SparseSketch._norm(query)
    scored = []
    for i, x in enumerate(xs):
        xn = SparseSketch._norm(x)
        if qn == 0 or xn == 0:
            scored.append((i, 0.0))
        else:
            inner = sum(v * x.get(j, 0.0) for j, v in query.items())
            scored.append((i, inner / (qn * xn)))
    scored.sort(key=lambda t: t[1], reverse=True)
    top = scored[:top_k]
    return [i for i, _ in top], [s for _, s in top]


def sparse_complexity(n: int, d: int, s: int, m: int, r: int, k: int) -> Dict[str, float]:
    """理论复杂度对照（命题：稀疏检索的复杂度优势）。

    稀疏方案时间 ``O(r n s + r n m + n k d)`` vs 全量 ``O(n^2 d)``；
    空间 ``O(n s + n m + n k)`` vs ``O(n^2)``。返回各口径的估算操作数。
    """
    return {
        "full_time": float(n * n * d),
        "sparse_time": float(r * n * s + r * n * m + n * k * d),
        "full_space": float(n * n),
        "sparse_space": float(n * s + n * m + n * k),
        "time_ratio_full_over_sparse": (n * n * d) / max(1.0, float(r * n * s + r * n * m + n * k * d)),
    }
