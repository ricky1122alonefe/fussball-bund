"""去水（赔率→隐含概率）测试。"""
from fussball_bund.analysis.probability import (
    bookmaker_margin,
    implied_probabilities,
    naive_probabilities,
    power_probabilities,
)

ODDS = [2.6, 2.4, 4.3]  # margin ~3.4%


def test_shin_sums_to_one():
    p = implied_probabilities(ODDS, method="shin")
    assert len(p) == 3
    assert abs(sum(p) - 1.0) < 1e-9


def test_power_sums_to_one():
    p = power_probabilities(ODDS)
    assert abs(sum(p) - 1.0) < 1e-9


def test_naive_sums_to_one():
    p = naive_probabilities(ODDS)
    assert abs(sum(p) - 1.0) < 1e-9


def test_margin_positive_when_overround():
    # 1/2 + 1/3 + 1/6 = 1.0，无水位
    assert abs(bookmaker_margin([2.0, 3.0, 6.0])) < 1e-9
    # 有水位
    assert bookmaker_margin(ODDS) > 0


def test_shin_boosts_favorites():
    """Shin 去水后，热门（低赔率）概率高于朴素归一化。"""
    shin = implied_probabilities(ODDS, method="shin")
    naive = naive_probabilities(ODDS)
    # 最低赔率 = 2.4（客胜位置 index=1）应是热门
    fav_idx = ODDS.index(min(ODDS))
    assert shin[fav_idx] > naive[fav_idx]


def test_shin_close_to_power():
    """Shin 与 Power 方法结果接近（Power 是 Shin 的良好近似）。"""
    shin = implied_probabilities(ODDS, method="shin")
    power = power_probabilities(ODDS)
    for a, b in zip(shin, power):
        assert abs(a - b) < 0.02
