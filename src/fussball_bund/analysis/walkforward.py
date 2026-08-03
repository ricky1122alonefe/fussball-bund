"""Walk-forward 评估（严格反泄漏）。

对目标赛季每场比赛 t（按比赛日推进）：
- 训练数据 = 该联赛所有 match_date < t 的比赛（跨赛季，绝不包含 t 及之后）
- 用训练好的模型预测 t
- 记录预测概率、实际结果、开盘赔率、收盘赔率
- 计算 CLV / Brier / log-loss / opening ROI

重训频率：按比赛日重训（同一天比赛共享一个模型），平衡精度与性能。
一个赛季约 100 个比赛日，Dixon-Coles 重训约 2-3 分钟。

这是模型选型的可信依据，禁止用 closing ROI（含未来信息）替代。
"""
from __future__ import annotations

import json
import logging
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path

from fussball_bund.storage.db import Database, get_db

logger = logging.getLogger(__name__)


@dataclass
class WalkForwardBet:
    match_id: int
    match_date: str | None
    home_team: str
    away_team: str
    market: str
    bookmaker: str
    bet_odds: float
    closing_odds: float | None
    model_prob: float
    implied_prob: float
    actual: str
    hit: bool
    pnl: float
    clv: float | None


@dataclass
class WalkForwardResult:
    league: str
    season: str
    model: str
    bet_period: str
    n_matches: int
    n_bets: int
    refits: int
    brier: float
    log_loss: float
    opening_roi: dict
    clv: dict
    bets: list = field(default_factory=list)


def _build_model(name: str, db: Database):
    if name == "dixoncoles":
        from fussball_bund.analysis import DixonColesModel

        return DixonColesModel(db=db)
    if name == "xgpoisson":
        from fussball_bund.analysis import XGPoissonModel

        return XGPoissonModel(db=db)
    from fussball_bund.analysis import PoissonModel

    return PoissonModel(db=db)


def run_walkforward(
    league_code: str,
    season: str,
    model_name: str = "dixoncoles",
    bet_period: str = "opening",
    closing_period: str = "closing",
    bookmaker: str = "Pinnacle",
    min_edge: float = 0.03,
    min_odds: float = 1.5,
    calibrate: bool = False,
    calibrate_alpha: float = 0.4,
    db: Database | None = None,
) -> WalkForwardResult:
    """运行 walk-forward 评估。

    Args:
        bet_period: 下注赔率周期（opening 默认，有可击败空间）
        closing_period: CLV 对齐的收盘周期
    """
    db = db or get_db()

    # 目标赛季所有已完赛比赛（按日期排序）
    matches = db.execute(
        "SELECT id, home_team, away_team, match_date, ft_result "
        "FROM matches WHERE league_code=? AND season=? "
        "AND ft_result IS NOT NULL AND match_date IS NOT NULL "
        "ORDER BY match_date, id",
        (league_code, season),
    )
    if not matches:
        raise ValueError(f"无比赛数据: {league_code} {season}")

    # 按比赛日分组（同日共享模型）
    by_date: dict[str, list] = defaultdict(list)
    for m in matches:
        by_date[m["match_date"]].append(m)
    sorted_dates = sorted(by_date.keys())

    from fussball_bund.analysis.probability import implied_probabilities
    from fussball_bund.analysis.metrics import (
        aggregate_clv,
        brier_score,
        clv as clv_fn,
        log_loss,
        opening_roi,
        settle,
        settle_1x2,
    )

    all_bets: list[WalkForwardBet] = []
    all_probs: list[tuple[float, float, float]] = []
    all_actuals: list[str] = []
    refits = 0

    for i, d in enumerate(sorted_dates):
        day_matches = by_date[d]
        # 训练：严格只用 match_date < d 的历史（跨赛季，反泄漏）
        model = _build_model(model_name, db)
        try:
            model.fit(league_code, max_date=d)
        except ValueError:
            # 历史数据不足（赛季初），跳过该日预测
            continue
        refits += 1

        for m in day_matches:
            pred = model.predict(m["home_team"], m["away_team"])
            all_probs.append((pred.p_home, pred.p_draw, pred.p_away))
            all_actuals.append(m["ft_result"])

            # 取该场下注周期 + 收盘赔率
            ob = db.execute(
                "SELECT home, draw, away FROM odds_1x2 "
                "WHERE match_id=? AND bookmaker=? AND period=?",
                (m["id"], bookmaker, bet_period),
            )
            cb = db.execute(
                "SELECT home, draw, away FROM odds_1x2 "
                "WHERE match_id=? AND bookmaker=? AND period=?",
                (m["id"], bookmaker, closing_period),
            )
            if not ob or not ob[0]["home"]:
                continue
            oh, od, oa = ob[0]["home"], ob[0]["draw"], ob[0]["away"]
            implied = implied_probabilities((oh, od, oa))

            if calibrate:
                from fussball_bund.analysis.calibration import calibrate_draw

                ph, pd, pa = calibrate_draw(pred, implied, calibrate_alpha)
            else:
                ph, pd, pa = pred.p_home, pred.p_draw, pred.p_away

            ch = cb[0]["home"] if cb and cb[0]["home"] else None
            cd = cb[0]["draw"] if cb and cb[0]["draw"] else None
            ca = cb[0]["away"] if cb and cb[0]["away"] else None

            market_defs = [
                ("home", ph, oh, ch, implied[0]),
                ("draw", pd, od, cd, implied[1]),
                ("away", pa, oa, ca, implied[2]),
            ]
            for market, p_model, o, co, p_imp in market_defs:
                if not o or o < min_odds:
                    continue
                edge = p_model - p_imp
                ev = p_model * o - 1
                if edge >= min_edge and ev > 0:
                    hit = settle_1x2(market, m["ft_result"])
                    all_bets.append(WalkForwardBet(
                        match_id=m["id"], match_date=m["match_date"],
                        home_team=m["home_team"], away_team=m["away_team"],
                        market=market, bookmaker=bookmaker, bet_odds=o,
                        closing_odds=co, model_prob=round(p_model, 4),
                        implied_prob=round(p_imp, 4), actual=m["ft_result"],
                        hit=hit, pnl=round(settle(o, market, m["ft_result"]), 4),
                        clv=(clv_fn(o, co) if co else None),
                    ))

        if (i + 1) % 20 == 0:
            logger.info("walk-forward 进度 %d/%d 比赛日, %d 笔投注", i + 1, len(sorted_dates), len(all_bets))

    return WalkForwardResult(
        league=league_code,
        season=season,
        model=model_name,
        bet_period=bet_period,
        n_matches=len(matches),
        n_bets=len(all_bets),
        refits=refits,
        brier=round(brier_score(all_probs, all_actuals), 4),
        log_loss=round(log_loss(all_probs, all_actuals), 4),
        opening_roi=opening_roi(all_bets, [b.actual for b in all_bets]),
        clv=aggregate_clv([b.bet_odds for b in all_bets], [b.closing_odds for b in all_bets]),
        bets=[asdict(b) for b in all_bets[-100:]],  # 存最近 100 条详情
    )


def save_result(result: WalkForwardResult, path: str) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps(asdict(result), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logger.info("walk-forward 结果已保存至 %s", path)
