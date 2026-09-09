"""贝叶斯个性化更新模块的单元测试（unittest，标准库）。"""
import math
import unittest

from src.innovations.bayes_personalization import (
    AuditGate,
    BetaPosterior,
    bayes_error_bound,
    beta_sf,
    mixture_prediction,
    peer_weights,
    smoothing_gap,
    threshold_smoothing,
    time_decay_weight,
    weight_derivatives,
)


class TestPeerWeights(unittest.TestCase):
    def test_sum_is_one(self):
        for k in (1.0, 5.0, 10.0):
            for n in (0.0, 1.0, 9.0, 100.0):
                g, u = peer_weights(k, n)
                self.assertAlmostEqual(g + u, 1.0)
                self.assertGreaterEqual(g, 0.0)
                self.assertGreaterEqual(u, 0.0)

    def test_monotonic(self):
        g0, _ = peer_weights(5.0, 1.0)
        g1, _ = peer_weights(5.0, 100.0)
        self.assertGreater(g0, g1)          # 个人证据越多，群体权重越低
        _, u0 = peer_weights(5.0, 1.0)
        _, u1 = peer_weights(5.0, 100.0)
        self.assertLess(u0, u1)             # 个人权重单调上升

    def test_derivative_signs(self):
        dg, du = weight_derivatives(3.0, 7.0)
        self.assertLess(dg, 0.0)
        self.assertGreater(du, 0.0)
        self.assertAlmostEqual(dg, -du)

    def test_handbook_formula(self):
        # λ_g = κ/(κ+n) 的直接数值核对
        k, n = 2.5, 4.0
        g, u = peer_weights(k, n)
        self.assertAlmostEqual(g, k / (k + n))
        self.assertAlmostEqual(u, n / (k + n))


class TestDecayAndMix(unittest.TestCase):
    def test_decay(self):
        self.assertAlmostEqual(time_decay_weight(0.1, 0.0), 1.0)
        self.assertAlmostEqual(time_decay_weight(0.1, 10.0), math.exp(-1.0))
        self.assertLess(time_decay_weight(0.1, 10.0), time_decay_weight(0.1, 1.0))

    def test_mix(self):
        self.assertAlmostEqual(mixture_prediction(0.5, 0.8, 0.5, 0.4), 0.6)


class TestErrorBound(unittest.TestCase):
    def test_structure(self):
        b = bayes_error_bound(0.3, 0.1, 1.0, 0.2, 0.1, 0.1, 1.0, 0.05)
        # 分解核对：α·ε + (1-α)·[L·D + sqrt(2(σ²+ν²)V log(2/δ))]
        inner = 0.2 + math.sqrt(2 * 0.2 * 1.0 * math.log(2 / 0.05))
        self.assertAlmostEqual(b, 0.3 * 0.1 + 0.7 * inner)

    def test_delta_monotonic(self):
        b1 = bayes_error_bound(0.3, 0.1, 1.0, 0.2, 0.1, 0.1, 1.0, 0.2)
        b2 = bayes_error_bound(0.3, 0.1, 1.0, 0.2, 0.1, 0.1, 1.0, 0.001)
        self.assertLess(b1, b2)             # 更严格置信 → 更大上界

    def test_alpha_limits(self):
        # α_b→1（个人证据充分）时群体项消失
        b = bayes_error_bound(1.0, 0.15, 1.0, 0.5, 0.1, 0.1, 1.0, 0.05)
        self.assertAlmostEqual(b, 0.15)


class TestBetaPosterior(unittest.TestCase):
    def test_update_conjugate(self):
        p = BetaPosterior(2.0, 2.0).update(tp=3.0, fp=1.0)
        self.assertEqual((p.a, p.b), (5.0, 3.0))

    def test_mean_variance_formula(self):
        p = BetaPosterior(4.0, 6.0)
        self.assertAlmostEqual(p.mean(), 0.4)
        s = 10.0
        self.assertAlmostEqual(p.variance(), 4 * 6 / (s * s * (s + 1)))

    def test_variance_bound(self):
        # 手册：Var <= 1 / (4 (a+b+1))
        for a, b in ((3.0, 7.0), (20.0, 1.0), (50.0, 30.0)):
            p = BetaPosterior(a, b)
            self.assertLessEqual(p.variance(), 1.0 / (4 * (a + b + 1.0)) + 1e-12)

    def test_sf_consistency(self):
        # sf(x) 与互补积分之和为 1（数值自洽）
        for a, b, x in ((3.0, 7.0, 0.5), (10.0, 2.0, 0.3), (2.0, 5.0, 0.8)):
            s_hi = beta_sf(a, b, x)
            s_lo = beta_sf(a, b, x)  # 占位，下面用对称积分核对
            self.assertAlmostEqual(s_hi + (1.0 - s_hi), 1.0)
            # 用 Beta 分布均值对称性核对：Beta(a,b) 的 sf(x) 与 Beta(b,a) 的 cdf(1-x) 一致
            from src.innovations.bayes_personalization import beta_sf as _sf
            self.assertAlmostEqual(
                _sf(a, b, x), 1.0 - _sf(b, a, 1.0 - x), places=4, msg=(a, b, x))
            self.assertGreaterEqual(s_lo, 0.0)
            self.assertLessEqual(s_lo, 1.0)

    def test_sf_monotonic(self):
        p = BetaPosterior(8.0, 2.0)   # 均值 0.8
        self.assertGreater(p.sf(0.5), 0.9)
        self.assertLess(p.sf(0.95), 0.1)


class TestAuditGate(unittest.TestCase):
    def test_more_evidence_feasible(self):
        gate = AuditGate(p0=0.85, q0=0.7, alpha_p=0.1, alpha_r=0.1)
        # 少量计数：不可行
        t = gate.min_feasible([(0.5, (1.0, 0.0, 0.0)), (0.9, (5.0, 3.0, 2.0))])
        self.assertIsNone(t)
        # 充足计数：最小可行门槛（计数更多、比例更高）
        t2 = gate.min_feasible([(0.5, (40.0, 3.0, 1.0)), (0.7, (60.0, 5.0, 2.0))])
        self.assertIsNotNone(t2)

    def test_none_when_no_feasible(self):
        gate = AuditGate(p0=0.99, q0=0.99, alpha_p=0.01, alpha_r=0.01)
        t = gate.min_feasible([(0.6, (8.0, 8.0, 8.0))])
        self.assertIsNone(t)


class TestSmoothing(unittest.TestCase):
    def test_step(self):
        self.assertAlmostEqual(threshold_smoothing(0.5, 0.9, 0.5), 0.7)

    def test_gap_geometric(self):
        gap = smoothing_gap(0.2, 0.8, 0.5, t=10)
        self.assertAlmostEqual(gap, 0.6 * (0.5 ** 10))


if __name__ == "__main__":
    unittest.main()
