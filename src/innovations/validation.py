"""创新模块运行验证入口（python -m src.innovations.validation）。

对两项创新做可复现的数值验证，输出 JSON 摘要：
- 贝叶斯：权重迁移随个人证据量变化、误差上界随置信度/证据量变化、
  决策门槛可行性示例、门槛平滑收敛步数；
- 高维稀疏：草图内积无偏与方差界（经验）、中位数相关度误差经验界、
  候选召回与全量 Top-k 重合、理论复杂度对照。

用法：``python -m src.innovations.validation [n_memories]``
"""
from __future__ import annotations

import json
import math
import random
import os
import sys
import time

from src.innovations.bayes_personalization import (
    AuditGate,
    beta_sf,
    peer_weights,
    smoothing_gap,
    threshold_smoothing,
)
from src.innovations.sparse_sketch import (
    SparseSketch,
    brute_force_topk,
    sketch_candidate_recall,
    sparse_complexity,
)


def _random_sparse(nnz, dim, seed):
    rng = random.Random(seed)
    idx = rng.sample(range(dim), nnz)
    return {j: (rng.random() - 0.5) * 2.0 for j in idx}


def run_bayes() -> dict:
    out = {}
    # 1) 权重迁移
    kappa = 5.0
    weights = [{"n": n, "lambda_g": round(peer_weights(kappa, n)[0], 4),
                "lambda_u": round(peer_weights(kappa, n)[1], 4)}
               for n in (0, 1, 2, 5, 10, 20, 50)]
    out["weight_transfer"] = weights
    # 2) 误差界随证据量（alpha_b = n/(n+kappa) 的贝叶斯形式）
    alpha_b = lambda n: n / (n + kappa)  # noqa: E731
    bounds = []
    for n in (1, 5, 20, 100):
        a = alpha_b(n)
        b = (a * 0.10 + (1 - a) * (0.20 + math.sqrt(2 * 0.2 * 1.0 * math.log(2 / 0.05))))
        bounds.append({"n": n, "alpha_b": round(a, 3), "bound": round(b, 4)})
    out["error_bound_vs_evidence"] = bounds
    # 3) 门槛可行性（合成审计计数：高门槛 → 样本少而精；低门槛 → 样本多）
    gate = AuditGate(p0=0.85, q0=0.70, alpha_p=0.10, alpha_r=0.10)
    tau_counts = [
        (0.50, (60.0, 10.0, 5.0)),
        (0.65, (70.0, 6.0, 4.0)),
        (0.80, (40.0, 2.0, 2.0)),
        (0.90, (30.0, 1.0, 1.0)),
    ]
    out["gate"] = {
        "min_feasible_tau": gate.min_feasible(tau_counts),
        "no_evidence_tau": gate.min_feasible([(0.5, (2.0, 2.0, 2.0))]),
    }
    # 4) 平滑收敛步数
    tau0, taustar, eta = 0.4, 0.85, 0.2
    t = 0
    while smoothing_gap(tau0, taustar, eta, t) > 0.01 and t < 500:
        t += 1
    out["smoothing"] = {"eta": eta, "steps_to_1pct": t}
    return out


def run_sparse(n_mem: int = 2000) -> dict:
    out = {}
    dim, nnz, m = 2048, 24, 256
    q = _random_sparse(nnz, dim, seed=7)
    xs = [_random_sparse(nnz, dim, seed=100 + i) for i in range(n_mem)]
    # 相似簇（保证真实 top-k 有语义）
    for i in range(12):
        xs[i] = {j: v * (0.95 - 0.02 * i) for j, v in q.items()}

    # 1) 无偏性经验
    x, z = _random_sparse(nnz, dim, 1), _random_sparse(nnz, dim, 2)
    true_inner = sum(v * z.get(j, 0.0) for j, v in x.items())
    ests = [SparseSketch(m, seed=t).inner_estimate(x, z) for t in range(500)]
    mean_est = sum(ests) / len(ests)
    emp_var = sum((e - mean_est) ** 2 for e in ests) / len(ests)
    nx2 = sum(v * v for v in x.values())
    nz2 = sum(v * v for v in z.values())
    out["unbiasedness"] = {
        "true_inner": round(true_inner, 4), "emp_mean": round(mean_est, 4),
        "emp_var": round(emp_var, 5), "var_bound": round(nx2 * nz2 / m, 5),
    }
    # 2) 中位数相关度经验误差（理论：m>=4/e²、r>=8log(2/d) → 失败率<=d）
    eps, delta = 0.10, 0.05
    m_t = int(4 / eps ** 2)
    r_t = int(8 * math.log(2 / delta)) + 1
    w = _random_sparse(nnz, dim, seed=1234)
    x2 = {j: v * 0.85 + 0.4 * w.get(j, 0.0) for j, v in x.items()}
    norm_x = math.sqrt(sum(v * v for v in x.values()))
    norm_x2 = math.sqrt(sum(v * v for v in x2.values()))
    rho_true = sum(v * x2.get(j, 0.0) for j, v in x.items()) / (norm_x * norm_x2)
    trials, fails = 200, 0
    for t in range(trials):
        est = _median_corr(x, x2, m_t, r_t, t)
        if abs(est - rho_true) > eps:
            fails += 1
    out["median_error"] = {
        "m_theory": m_t, "r_theory": r_t, "emp_fail_rate": round(fails / trials, 4),
        "theory_delta": delta,
    }
    # 3) 候选召回 vs 全量
    k = 10
    t0 = time.time()
    ids_sk, _, stats = sketch_candidate_recall(xs, q, top_k=k, m=m, seed=3, cand_factor=4.0)
    t_sketch = time.time() - t0
    t0 = time.time()
    ids_br, _ = brute_force_topk(xs, q, top_k=k)
    t_full = time.time() - t0
    overlap = len(set(ids_sk) & set(ids_br))
    out["candidate_recall"] = {
        "n": n_mem, "top_k": k, "overlap_with_bruteforce": overlap,
        "candidates_considered": stats["candidates"],
        "sec_sketch": round(t_sketch, 4), "sec_bruteforce": round(t_full, 4),
        "note": "稀疏查询下全量内积已为 O(n·s)，草图优势体现在稠密查询/全量两两关系场景",
    }
    # 4) 稠密查询计时对照（记忆稀疏、查询稠密：全量需 O(n·d) 内积，草图只需投影+候选复核）
    import random as _rnd
    _rr = _rnd.Random(5)
    q_dense = {j: (_rr.random() - 0.5) * 2.0 for j in range(dim)}
    t0 = time.time()
    ids_sk2, _, _ = sketch_candidate_recall(xs, q_dense, top_k=k, m=m, seed=3, cand_factor=4.0)
    t_sketch_d = time.time() - t0
    t0 = time.time()
    ids_br2, _ = brute_force_topk(xs, q_dense, top_k=k)
    t_full_d = time.time() - t0
    out["dense_query_timing"] = {
        "n": n_mem, "dim": dim, "sec_sketch": round(t_sketch_d, 4),
        "sec_bruteforce": round(t_full_d, 4),
        "overlap": len(set(ids_sk2) & set(ids_br2)),
        "note": "稠密查询场景：全量需 O(n·d) 内积；重叠率为噪声主导场景参考值",
    }
    # 5) 复杂度理论对照
    out["complexity"] = sparse_complexity(n=10000, d=2048, s=32, m=256, r=3, k=64)
    return out


def _median_corr(x, z, m, r, seed):
    vals = [SparseSketch(m, seed=seed * 131 + s).correlation(x, z) for s in range(r)]
    vals.sort()
    return vals[len(vals) // 2]


def main() -> None:
    n_mem = int(sys.argv[1]) if len(sys.argv) > 1 else 2000
    result = {"bayes": run_bayes(), "sparse": run_sparse(n_mem)}
    print(json.dumps(result, ensure_ascii=False, indent=1))
    out_path = os.path.join(os.getcwd(), "innovations_validation.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
