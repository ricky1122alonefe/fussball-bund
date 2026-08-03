"""评估指标：Brier / log-loss / opening ROI / CLV。

指标优先级（见 docs/BACKTEST_PROTOCOL.md）：
1. CLV（Closing Line Value）—— 最可靠的价值指标，不受单场结果方差影响
2. Brier score —— 概率预测质量（均方误差，越低越好）
3. log-loss —— 概率预测质量（对数损失，越低越好）
4. opening ROI —— 开盘赔率结算盈亏（受方差影响，需大样本才稳定）

禁止用 closing ROI 作为模型选型唯一依据（closing 已是高效市场，且含未来信息）。
"""
from __future__ import annotations

import math
from typing import Iterable, Sequence


def brier_score(
    probabilities: Sequence[tuple[float, float, float]],
    actuals: Sequence[str],
) -> float:
    """多分类 Brier score（1X2）。越低越好。

    Args:
        probabilities: [(p_home, p_draw, p_away), ...]
        actuals: ['H', 'D', 'A', ...]
    """
    total = 0.0
    for (ph, pd, pa), actual in zip(probabilities, actuals):
        yh = 1.0 if actual == "H" else 0.0
        yd = 1.0 if actual == "D" else 0.0
        ya = 1.0 if actual == "A" else 0.0
        total += (ph - yh) ** 2 + (pd - yd) ** 2 + (pa - ya) ** 2
    n = len(actuals)
    return total / n if n else 0.0


def log_loss(
    probabilities: Sequence[tuple[float, float, float]],
    actuals: Sequence[str],
    eps: float = 1e-15,
) -> float:
    """多分类 log-loss（1X2）。越低越好。"""
    total = 0.0
    for (ph, pd, pa), actual in zip(probabilities, actuals):
        p = {"H": ph, "D": pd, "A": pa}.get(actual, 1 / 3)
        p = max(min(p, 1 - eps), eps)
        total -= math.log(p)
    n = len(actuals)
    return total / n if n else 0.0


def settle_1x2(market: str, actual: str) -> bool:
    """1X2 市场命中判定。"""
    return {"home": actual == "H", "draw": actual == "D", "away": actual == "A"}.get(
        market, False
    )


def settle(bet_odds: float, market: str, actual: str, stake: float = 1.0) -> float:
    """结算单笔投注，返回盈亏（正=赢，负=输）。"""
    if settle_1x2(market, actual):
        return stake * (bet_odds - 1)
    return -stake


def opening_roi(bets: Sequence, actuals: Sequence[str], stake: float = 1.0) -> dict:
    """开盘/下注赔率 ROI。

    Args:
        bets: 可迭代对象，每个有 .odds（或 .bet_odds）和 .market
        actuals: 对应的实际结果 'H'/'D'/'A'
    """
    profit = 0.0
    wins = 0
    n = 0
    for bet, actual in zip(bets, actuals):
        odds = getattr(bet, "odds", None)
        if odds is None:
            odds = getattr(bet, "bet_odds", 0.0)
        market = getattr(bet, "market", "")
        pnl = settle(odds, market, actual, stake)
        profit += pnl
        if pnl > 0:
            wins += 1
        n += 1
    return {
        "n_bets": n,
        "wins": wins,
        "win_rate": round(wins / n, 4) if n else 0,
        "profit": round(profit, 4),
        "roi_pct": round(profit / (n * stake) * 100, 2) if n else 0,
    }


def clv(bet_odds: float, closing_odds: float | None) -> float | None:
    """单笔 CLV（Closing Line Value）= bet_odds / closing_odds - 1。

    正值表示下注赔率优于收盘（beat the closing line），是长期盈利的可靠先行指标。
    不受单场结果方差影响，优于 ROI（需更小样本即可显著）。
    """
    if not closing_odds or closing_odds <= 1:
        return None
    return bet_odds / closing_odds - 1


def aggregate_clv(
    bet_odds_list: Iterable[float],
    closing_odds_list: Iterable[float | None],
) -> dict:
    """聚合 CLV 统计。"""
    clvs = [clv(b, c) for b, c in zip(bet_odds_list, closing_odds_list)]
    clvs = [c for c in clvs if c is not None]
    n = len(clvs)
    if not n:
        return {"n": 0, "mean_clv": None, "positive_pct": None}
    return {
        "n": n,
        "mean_clv": round(sum(clvs) / n, 4),
        "positive_pct": round(sum(1 for c in clvs if c > 0) / n, 3),
    }
