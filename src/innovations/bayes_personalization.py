"""贝叶斯个性化记忆更新 — 独立算法模块。

对应手册第六章 6.2 与第八章 8.4.1：把「相似用户群提供冷启动、个人证据逐步主导」
实现为可计算的权重迁移、Beta--Bernoulli 共轭更新与决策门槛。

符号与手册一致：
- ``kappa_g``：群体先验强度；``n``：个人有效证据量；
- ``lambda_g = kappa_g / (kappa_g + n)``、``lambda_u = n / (kappa_g + n)``；
- ``P_t(m|u,q) = lambda_g * P_g + lambda_u * P_u``（混合预测）；
- Beta 后验 ``Beta(a + TP, b + FP)``（精确率）/ ``Beta(a + TP, b + FN)``（召回率）。

所有函数为纯计算：不读写外部状态，不依赖第三方数值库
（Beta 尾部概率用对数密度 + 自适应 Simpson 数值积分实现）。
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable, Optional

# ---------------------------------------------------------------------------
# 权重迁移与混合预测（命题：群体参考向个人偏好的权重迁移）
# ---------------------------------------------------------------------------


def peer_weights(kappa_g: float, n: float) -> tuple[float, float]:
    """群体参考权重与个人证据权重。

    ``lambda_g = kappa_g / (kappa_g + n)``，``lambda_u = n / (kappa_g + n)``。
    返回 ``(lambda_g, lambda_u)``，两者之和恒为 1。
    """
    if kappa_g < 0:
        raise ValueError("kappa_g 必须非负")
    if n < 0:
        raise ValueError("n 必须非负")
    denom = kappa_g + n
    if denom == 0:
        raise ValueError("kappa_g 与 n 不能同时为零")
    lam_g = kappa_g / denom
    return lam_g, 1.0 - lam_g


def weight_derivatives(kappa_g: float, n: float) -> tuple[float, float]:
    """权重随个人证据量的导数（命题证明式）。

    ``d(lambda_g)/dn = -kappa_g / (kappa_g + n)^2 < 0``，
    ``d(lambda_u)/dn = +kappa_g / (kappa_g + n)^2 > 0``。
    """
    c = kappa_g / ((kappa_g + n) ** 2)
    return -c, c


def time_decay_weight(rate: float, dt: float) -> float:
    """时间衰减权重 ``w = exp(-rate * dt)``（rate>=0，dt 为距事件时间差）。"""
    if rate < 0:
        raise ValueError("衰减率必须非负")
    return math.exp(-rate * dt)


def mixture_prediction(lambda_g: float, p_g: float,
                       lambda_u: float, p_u: float) -> float:
    """混合预测 ``P_t(m|u,q) = lambda_g * P_g(m|q) + lambda_u * P_u(m|q)``。"""
    return lambda_g * p_g + lambda_u * p_u


def bayes_error_bound(alpha_b: float, eps_per: float, L: float, D_b: float,
                      sigma2: float, nu2: float, V_b: float, delta: float) -> float:
    """多用户融合预测的高概率误差上界（定理：多用户融合预测误差界）。

    ``|theta_hat - theta| <= alpha_b * eps_per
         + (1 - alpha_b) * [L * D_b + sqrt(2 (sigma2 + nu2) V_b log(2/delta))]``

    参数含义（与手册一致）：``eps_per`` 个人历史估计误差；
    ``L * D_b`` 相似用户距离导致的确定性差异；``sigma2`` 观测噪声方差、
    ``nu2`` 群体扰动方差、``V_b`` 群体方差项；``delta`` 失败概率。
    """
    if not 0.0 <= delta < 1.0:
        raise ValueError("delta 必须在 [0, 1) 内")
    inner = L * D_b + math.sqrt(2.0 * (sigma2 + nu2) * V_b * math.log(2.0 / delta))
    return alpha_b * eps_per + (1.0 - alpha_b) * inner


# ---------------------------------------------------------------------------
# Beta 后验数值工具（无第三方依赖）
# ---------------------------------------------------------------------------


def _log_beta(a: float, b: float) -> float:
    return math.lgamma(a) + math.lgamma(b) - math.lgamma(a + b)


def _beta_logpdf(x: float, a: float, b: float) -> float:
    if x <= 0.0 or x >= 1.0:
        return -math.inf
    return ((a - 1.0) * math.log(x) + (b - 1.0) * math.log1p(-x)
            - _log_beta(a, b))


def _adaptive_simpson(f, lo: float, hi: float, tol: float = 1e-7,
                      depth: int = 0) -> float:
    """自适应 Simpson 积分（相对容差 tol，最大递归深度 24）。"""
    mid = 0.5 * (lo + hi)
    whole = (hi - lo) / 6.0 * (f(lo) + 4.0 * f(mid) + f(hi))
    left = (mid - lo) / 6.0 * (f(lo) + 4.0 * f(0.5 * (lo + mid)) + f(mid))
    right = (hi - mid) / 6.0 * (f(mid) + 4.0 * f(0.5 * (mid + hi)) + f(hi))
    if depth > 24:
        return whole
    if abs(left + right - whole) <= 15.0 * tol * max(1.0, abs(whole)):
        return left + right + (left + right - whole) / 15.0
    return (_adaptive_simpson(f, lo, mid, tol / 2.0, depth + 1)
            + _adaptive_simpson(f, mid, hi, tol / 2.0, depth + 1))


def _beta_normal_approx_sf(a: float, b: float, x: float) -> float:
    """大样本（a+b 大）时用正态近似计算 Pr(X >= x)，标注 approximate。"""
    mu = a / (a + b)
    var = (a * b) / ((a + b) ** 2 * (a + b + 1.0))
    if var <= 0:
        return 1.0 if x <= mu else 0.0
    z = (mu - x) / math.sqrt(var)
    return 0.5 * math.erfc(z / math.sqrt(2.0))


def beta_sf(a: float, b: float, x: float) -> float:
    """``Pr(X >= x)``，X ~ Beta(a, b)（a,b >= 1）。

    小样本用对数密度 + 自适应积分（缩放至峰值附近避免下溢）；
    总量大时自动切换正态近似（对尾概率误差影响可忽略）。
    """
    if a < 1 or b < 1:
        raise ValueError("Beta 参数需 >= 1")
    if x <= 0.0:
        return 1.0
    if x >= 1.0:
        return 0.0
    if a + b >= 500.0:
        return _beta_normal_approx_sf(a, b, x)
    # 峰值位置（mode）用于缩放，避免 exp(-large) 下溢
    if a > 1 and b > 1:
        mode = (a - 1.0) / (a + b - 2.0)
    else:
        mode = a / (a + b)
    peak = _beta_logpdf(mode, a, b)

    def scaled(t: float) -> float:
        return math.exp(_beta_logpdf(t, a, b) - peak)

    # 有效支撑集中在均值 ± 20 个标准差内，其余尾部可忽略
    mu = a / (a + b)
    var = (a * b) / ((a + b) ** 2 * (a + b + 1.0))
    sd = math.sqrt(var)
    hi = min(1.0, mu + 20.0 * sd)
    lo = max(0.0, mu - 20.0 * sd)
    if x >= hi:
        return 0.0
    start = max(lo, x)
    num = _adaptive_simpson(scaled, start, hi)
    den = _adaptive_simpson(scaled, lo, hi)
    if den <= 0:
        return 0.0
    return num / den


@dataclass
class BetaPosterior:
    """Beta(a, b) 后验 — 共轭更新的可计算对象（精确率/召回率审计）。"""

    a: float
    b: float

    def __post_init__(self) -> None:
        if self.a < 1 or self.b < 1:
            raise ValueError("Beta 参数需 >= 1")

    def update(self, tp: float = 0.0, fp: float = 0.0,
               fn: float = 0.0) -> "BetaPosterior":
        """共轭更新：``Beta(a + TP, b + FP)``（精确率口径；
        召回率口径把假正例换成假负例，即 update(fp=0, fn=…)。"""
        if tp < 0 or fp < 0 or fn < 0:
            raise ValueError("计数不能为负")
        return BetaPosterior(self.a + tp + fn, self.b + fp)

    def mean(self) -> float:
        return self.a / (self.a + self.b)

    def variance(self) -> float:
        """``Var = ab / ((a+b)^2 (a+b+1))``（手册后验收敛证明式）。"""
        s = self.a + self.b
        return (self.a * self.b) / (s * s * (s + 1.0))

    def sf(self, p0: float) -> float:
        """``Pr(P >= p0 | D)``。"""
        return beta_sf(self.a, self.b, p0)


# ---------------------------------------------------------------------------
# 决策门槛（观察态 / 长期态）
# ---------------------------------------------------------------------------


@dataclass
class AuditGate:
    """基于后验概率约束的决策门槛。

    给定目标精确率 ``p0``、目标召回率 ``q0`` 与风险水平 ``alpha_p/alpha_r``，
    在候选门槛集合中取满足
    ``Pr(P_tau >= p0 | D) >= 1 - alpha_p`` 且 ``Pr(R_tau >= q0 | D) >= 1 - alpha_r``
    的最小 ``tau``（手册门槛选择式）；无满足者返回 None（进入观察态）。
    """

    p0: float
    q0: float
    alpha_p: float = 0.10
    alpha_r: float = 0.10

    def __post_init__(self) -> None:
        for v, lo, hi in ((self.p0, 0.0, 1.0), (self.q0, 0.0, 1.0),
                          (self.alpha_p, 0.0, 1.0), (self.alpha_r, 0.0, 1.0)):
            if not lo < v < hi:
                raise ValueError("p0/q0/alpha 需在 (0, 1) 内")

    def min_feasible(self, tau_counts: Iterable[tuple[float, tuple[float, float, float]]],
                     prior_p: tuple[float, float] = (1.0, 1.0),
                     prior_r: tuple[float, float] = (1.0, 1.0),
                     ) -> Optional[float]:
        """在 ``(tau, (TP, FP, FN))`` 序列中找最小可行门槛。

        返回最小的 tau；若没有任何候选满足双侧概率约束则返回 None。
        """
        feasible = None
        for tau, (tp, fp, fn) in tau_counts:
            pp = BetaPosterior(prior_p[0] + tp, prior_p[1] + fp)
            rr = BetaPosterior(prior_r[0] + tp, prior_r[1] + fn)
            if (pp.sf(self.p0) >= 1.0 - self.alpha_p
                    and rr.sf(self.q0) >= 1.0 - self.alpha_r):
                if feasible is None or tau < feasible:
                    feasible = tau
        return feasible


def threshold_smoothing(tau_t: float, tau_star: float, eta: float) -> float:
    """平滑门槛更新 ``tau_{t+1} = (1 - eta) tau_t + eta tau_star``。"""
    if not 0.0 < eta <= 1.0:
        raise ValueError("eta 需在 (0, 1] 内")
    return (1.0 - eta) * tau_t + eta * tau_star


def smoothing_gap(tau_0: float, tau_star: float, eta: float, t: int) -> float:
    """平滑收敛差距 ``|tau_t - tau_star| = (1 - eta)^t |tau_0 - tau_star|``。"""
    return abs((1.0 - eta) ** t * (tau_0 - tau_star))
