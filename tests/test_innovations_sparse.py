"""高维稀疏检索模块的单元测试（unittest，标准库）。"""
import math
import random
import unittest

from src.innovations.sparse_sketch import (
    SparseSketch,
    brute_force_topk,
    sketch_candidate_recall,
    sparse_complexity,
)


def random_sparse(nnz: int, dim: int, seed: int, scale: float = 1.0) -> dict:
    rng = random.Random(seed)
    idx = rng.sample(range(dim), nnz)
    return {j: (rng.random() - 0.5) * 2.0 * scale for j in idx}


class TestUnbiasedness(unittest.TestCase):
    def test_inner_estimate_unbiased(self):
        x = random_sparse(15, 300, seed=1)
        z = random_sparse(15, 300, seed=2)
        true_inner = sum(v * z.get(j, 0.0) for j, v in x.items())
        m = 64
        ests = []
        for t in range(400):
            sk = SparseSketch(m, seed=t)
            ests.append(sk.inner_estimate(x, z))
        mean_est = sum(ests) / len(ests)
        self.assertAlmostEqual(mean_est, true_inner, delta=0.35 * max(1.0, abs(true_inner)))

    def test_variance_bound(self):
        x = random_sparse(15, 300, seed=3)
        z = random_sparse(15, 300, seed=4)
        m = 32
        ests = []
        for t in range(300):
            sk = SparseSketch(m, seed=t)
            ests.append(sk.inner_estimate(x, z))
        mean_est = sum(ests) / len(ests)
        var = sum((e - mean_est) ** 2 for e in ests) / len(ests)
        nx2 = sum(v * v for v in x.values())
        nz2 = sum(v * v for v in z.values())
        self.assertLessEqual(var, nx2 * nz2 / m * 2.5)  # 经验方差应落在界附近（乘裕度抗随机性）

    def test_diagonal_exact(self):
        # 相同向量：单草图内积应等于 ||x||² 的估计且均值收敛到它
        x = random_sparse(10, 200, seed=5)
        sk = SparseSketch(50, seed=7)
        est = sk.inner_estimate(x, x)
        true_norm2 = sum(v * v for v in x.values())
        # 方差来自碰撞，但期望=||x||²；单次可能偏差，仅验证函数可算且有限
        self.assertTrue(math.isfinite(est))
        means = [SparseSketch(50, seed=s).inner_estimate(x, x) for s in range(200)]
        self.assertAlmostEqual(sum(means) / len(means), true_norm2, delta=0.3 * true_norm2)


class TestMedianCorrelation(unittest.TestCase):
    def test_median_close_for_similar(self):
        x = random_sparse(20, 400, seed=10)
        z = {j: v * 0.9 for j, v in x.items()}
        rho = _median(x, z, m=128, r=15)
        # 真相关 = 0.9（z 是 x 的 0.9 倍）
        self.assertAlmostEqual(rho, 0.9, delta=0.08)


def _median(x, z, m, r):
    vals = [SparseSketch(m, seed=s).correlation(x, z) for s in range(r)]
    vals.sort()
    return vals[len(vals) // 2]


class TestCandidateRecall(unittest.TestCase):
    def test_recall_matches_bruteforce(self):
        rng = random.Random(99)
        dim = 500
        q = random_sparse(12, dim, seed=42)
        # 带结构数据：前 15 条与 q 高度相似（构成真实 top-k），其余为噪声
        xs = []
        for i in range(15):
            xs.append({j: v * (1.0 - 0.05 * i) + rng.random() * 0.05 for j, v in q.items()})
        for i in range(185):
            xs.append(random_sparse(12, dim, seed=2000 + i))
        k = 10
        ids_sketch, _, stats = sketch_candidate_recall(xs, q, top_k=k, m=128, seed=3)
        ids_brute, _ = brute_force_topk(xs, q, top_k=k)
        overlap = len(set(ids_sketch) & set(ids_brute))
        self.assertGreaterEqual(overlap, int(k * 0.8))  # 草图候选与全量 top-k 应高度重合
        self.assertGreaterEqual(stats["candidates"], k)


class TestComplexity(unittest.TestCase):
    def test_ratio(self):
        c = sparse_complexity(n=5000, d=2000, s=20, m=256, r=3, k=50)
        self.assertGreater(c["time_ratio_full_over_sparse"], 1.0)
        self.assertLess(c["sparse_time"], c["full_time"])
        self.assertLess(c["sparse_space"], c["full_space"])


if __name__ == "__main__":
    unittest.main()
