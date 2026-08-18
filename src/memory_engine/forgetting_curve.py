"""遗忘曲线（报告 10.2）：Confidence × Stability 双维随时间衰减

支持指数衰减与艾宾浩斯（幂律）两种形态；接入现有 confidence/stability 评分体系。
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta


def _hours_since(last_seen: str | None, now: str | None = None) -> float:
    try:
        last = datetime.fromisoformat(last_seen) if last_seen else datetime.now()
        ref = datetime.fromisoformat(now) if now else datetime.now()
    except ValueError:
        return 0.0
    return max(0.0, (ref - last).total_seconds() / 3600.0)


@dataclass(frozen=True)
class ForgettingCurveConfig:
    """遗忘曲线参数。"""

    half_life_hours: float = 24.0   # 强度衰减到一半所需小时数（指数形态）
    decay_exponent: float = 0.5     # 幂律衰减指数（艾宾浩斯形态）
    reinforcement: float = 0.2      # 每次激活/反思的强化增量


def exponential_decay(strength: float, elapsed_hours: float, half_life_hours: float) -> float:
    """指数衰减：S(t) = S0 * 0.5^(t / T_half)。"""
    return strength * (0.5 ** (elapsed_hours / max(1e-6, half_life_hours)))


def power_law_decay(strength: float, elapsed_hours: float, exponent: float) -> float:
    """幂律（艾宾浩斯近似）：S(t) = S0 / (1 + t)^exp。"""
    return strength / ((1.0 + elapsed_hours) ** max(0.0, exponent))


class ForgettingCurve:
    """双维遗忘曲线：confidence 与 stability 分别按时间衰减，再合成记忆强度。"""

    def __init__(self, config: ForgettingCurveConfig | None = None):
        self.config = config or ForgettingCurveConfig()

    def strength_at(
        self,
        confidence: float,
        stability: float,
        last_seen: str | None,
        now: str | None = None,
    ) -> float:
        t = _hours_since(last_seen, now)
        c = exponential_decay(confidence, t, self.config.half_life_hours)
        s = power_law_decay(stability, t, self.config.decay_exponent)
        return round((c + s) / 2.0, 4)

    def reinforce(self, strength: float) -> float:
        """激活机制：反思通过后强化。"""
        return round(min(1.0, strength + self.config.reinforcement), 4)

    def decay_threshold(self, threshold: float = 0.3) -> bool:
        """判断是否需要进入衰退流程（弱记忆判定）。"""
        # 阈值判定在调用侧用 strength_at 结果比较；此方法保留为曲线语义占位
        return False
