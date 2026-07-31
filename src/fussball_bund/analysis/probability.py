"""赔率 → 隐含概率（去水）。

庄家赔率含 margin（水位），直接 1/odds 归一化会高估冷门概率。
本模块提供三种去水方法：

1. shin  —— Shin 方法（最准确，考虑内幕投注者偏好偏差）
            优先使用 mberk/shin 库；若未安装则回退到 power 方法
2. power —— Power 方法（Shin 的良好近似，纯实现无 scipy 依赖）
            求 k>1 使 Σ r_i^k = 1，p_i = r_i^k，r_i=1/odds_i
3. naive —— 朴素归一化（仅做 margin 比例缩放，最简单但偏差最大）

验证（odds [2.6, 2.4, 4.3]，margin 3.38%）:
    shin  → [0.3730, 0.4048, 0.2222]  (z=0.0169)
    power → [0.3726, 0.4048, 0.2217]  (k≈1.033)
    naive → [0.3720, 0.4030, 0.2250]
Shin 把 margin 更多归因于冷门被高估，去水后冷门概率下调、热门上调。
"""
from __future__ import annotations

import logging
import math

logger = logging.getLogger(__name__)

try:
    import shin as _shin_lib  # type: ignore

    _HAS_SHIN = True
except ImportError:  # pragma: no cover
    _HAS_SHIN = False


def implied_probabilities(odds, method: str = "shin") -> list[float]:
    """从赔率反推隐含概率（已去水，和为 1）。

    Args:
        odds: decimal 赔率序列，如 (2.6, 2.4, 4.3)
        method: shin / power / naive
    """
    odds = [float(o) for o in odds]
    if method == "shin":
        if _HAS_SHIN:
            return list(_shin_lib.calculate_implied_probabilities(odds))
        logger.debug("shin 库未安装，回退到 power 方法")
        return power_probabilities(odds)
    if method == "power":
        return power_probabilities(odds)
    if method == "naive":
        return naive_probabilities(odds)
    raise ValueError(f"未知方法: {method}，可选 shin/power/naive")


def naive_probabilities(odds) -> list[float]:
    """朴素归一化：p_i = (1/o_i) / Σ(1/o_j)。"""
    r = [1.0 / o for o in odds]
    s = sum(r)
    return [x / s for x in r]


def power_probabilities(odds, max_iter: int = 200, tol: float = 1e-12) -> list[float]:
    """Power 方法：求 k>1 使 Σ r_i^k = 1，p_i = r_i^k。

    r_i = 1/o_i（未归一化，Σ r = 1 + margin > 1）。
    因 r_i < 1，r_i^k 随 k 增大单调递减，故 Σ r_i^k 关于 k 单调递减，
    用二分法在 [1, 5] 内求根。
    """
    r = [1.0 / o for o in odds]

    def f(k: float) -> float:
        return sum(x ** k for x in r) - 1.0

    if f(1.0) <= 0:  # 无 margin，直接归一化
        s = sum(r)
        return [x / s for x in r]

    lo, hi = 1.0, 5.0
    for _ in range(max_iter):
        k = (lo + hi) / 2
        v = f(k)
        if abs(v) < tol:
            break
        if v > 0:  # sum 仍 > 1，需增大 k
            lo = k
        else:
            hi = k
    return [x ** k for x in r]


def bookmaker_margin(odds) -> float:
    """计算庄家水位（margin）：Σ(1/o_i) - 1。"""
    return sum(1.0 / o for o in odds) - 1.0
