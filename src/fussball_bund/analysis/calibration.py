"""预测概率校准。

Poisson/Dixon-Coles 类模型系统性低估平局（平局概率极少为最大值）。
本模块提供平局校准：将模型平局概率与庄家隐含平局概率混合，
从主客胜按比例扣除差值，保持归一化。

校准后平局预测更接近真实，同时保留模型对主客胜的独立判断。
"""
from __future__ import annotations

from fussball_bund.analysis.models import MatchPrediction


def calibrate_draw(
    pred: MatchPrediction,
    implied: tuple[float, float, float],
    alpha: float = 0.4,
) -> tuple[float, float, float]:
    """平局校准：混合模型与庄家隐含平局概率。

    Args:
        pred: 模型预测
        implied: 庄家隐含概率 (home, draw, away)（已去水，和为 1）
        alpha: 模型权重，1-alpha 为庄家权重。
               0.4 = 40% 模型 + 60% 庄家（庄家平局概率更准，给较高权重）
    Returns:
        校准后 (home, draw, away) 概率，和为 1
    """
    p_h, p_d, p_a = pred.p_home, pred.p_draw, pred.p_away
    p_d_new = alpha * p_d + (1.0 - alpha) * implied[1]
    diff = p_d_new - p_d
    # 从主客胜按现有比例分摊差值
    if abs(diff) > 1e-9 and (p_h + p_a) > 0:
        ratio_h = p_h / (p_h + p_a)
        p_h -= diff * ratio_h
        p_a -= diff * (1.0 - ratio_h)
    # 防负 + 归一化
    p_h = max(p_h, 0.0)
    p_a = max(p_a, 0.0)
    p_d_new = max(p_d_new, 0.0)
    s = p_h + p_d_new + p_a
    if s > 0:
        p_h, p_d_new, p_a = p_h / s, p_d_new / s, p_a / s
    return p_h, p_d_new, p_a
