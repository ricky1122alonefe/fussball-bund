"""价值投注识别。

对比模型预测概率与庄家隐含概率，找出期望值为正的投注机会。
- EV (期望值) = 模型概率 × 赔率 - 1
- Edge (优势) = 模型概率 - 庄家隐含概率
- Kelly (凯利仓位) = (p×o - 1)/(o - 1)，建议投注资金比例
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from fussball_bund.analysis.models import PoissonModel
from fussball_bund.storage.db import Database, get_db

logger = logging.getLogger(__name__)


@dataclass
class ValueBet:
    match_id: int
    home_team: str
    away_team: str
    match_date: str | None
    market: str  # home / draw / away / over_2_5 / under_2_5
    bookmaker: str
    period: str
    odds: float
    model_prob: float
    implied_prob: float
    ev: float
    edge: float
    kelly: float


class ValueBetFinder:
    """基于 Poisson 模型预测 + 庄家收盘赔率，识别价值投注。"""

    def __init__(
        self,
        db: Database | None = None,
        model: PoissonModel | None = None,
        calibrate: bool = False,
        calibrate_alpha: float = 0.4,
    ) -> None:
        self.db = db or get_db()
        self.model = model
        self.calibrate = calibrate
        self.calibrate_alpha = calibrate_alpha

    def find(
        self,
        league_code: str,
        season: str,
        bookmaker: str = "Pinnacle",
        period: str = "opening",
        min_edge: float = 0.03,
        min_odds: float = 1.5,
    ) -> list[ValueBet]:
        """查找价值投注。

        Args:
            bookmaker: 用哪家庄家的赔率对比（Pinnacle 最准，去水后接近真实概率）
            period: closing（收盘赔率最具参考价值）
            min_edge: 最小优势阈值，过滤噪声
            min_odds: 最低赔率，过滤无意义低赔
        """
        from fussball_bund.analysis.probability import implied_probabilities

        if self.model is None or not self.model._fitted:
            raise RuntimeError("需先拟合 Poisson 模型")

        # 取该联赛赛季所有比赛（含赔率与结果）
        rows = self.db.execute(
            "SELECT m.id, m.home_team, m.away_team, m.match_date, m.ft_result, "
            "o.home AS oh, o.draw AS od, o.away AS oa "
            "FROM matches m JOIN odds_1x2 o ON o.match_id=m.id "
            "WHERE m.league_code=? AND m.season=? AND o.bookmaker=? AND o.period=? "
            "AND o.home IS NOT NULL AND o.draw IS NOT NULL AND o.away IS NOT NULL "
            "ORDER BY m.match_date",
            (league_code, season, bookmaker, period),
        )
        logger.info("待分析比赛 %d 场（%s %s）", len(rows), league_code, season)

        results: list[ValueBet] = []
        for r in rows:
            pred = self.model.predict(r["home_team"], r["away_team"])
            odds = (r["oh"], r["od"], r["oa"])
            # 庄家隐含概率（已去水）
            implied = implied_probabilities(odds)
            if self.calibrate:
                from fussball_bund.analysis.calibration import calibrate_draw

                p_h, p_d, p_a = calibrate_draw(pred, implied, self.calibrate_alpha)
            else:
                p_h, p_d, p_a = pred.p_home, pred.p_draw, pred.p_away
            markets = [
                ("home", p_h, r["oh"], implied[0]),
                ("draw", p_d, r["od"], implied[1]),
                ("away", p_a, r["oa"], implied[2]),
            ]
            # 大小球（如有）
            tot = self.db.execute(
                "SELECT over, under FROM odds_totals WHERE match_id=? AND bookmaker=? "
                "AND period=? AND line=2.5",
                (r["id"], bookmaker, period),
            )
            if tot:
                ov, un = tot[0]["over"], tot[0]["under"]
                if ov and un:
                    imp_ou = implied_probabilities((ov, un))
                    markets.append(("over_2_5", pred.p_over_2_5, ov, imp_ou[0]))
                    markets.append(("under_2_5", pred.p_under_2_5, un, imp_ou[1]))

            for market, p_model, o, p_imp in markets:
                if not o or o < min_odds:
                    continue
                ev = p_model * o - 1
                edge = p_model - p_imp
                kelly = (p_model * o - 1) / (o - 1) if o > 1 else 0
                if edge >= min_edge and ev > 0:
                    results.append(ValueBet(
                        match_id=r["id"], home_team=r["home_team"], away_team=r["away_team"],
                        match_date=r["match_date"], market=market, bookmaker=bookmaker,
                        period=period, odds=o, model_prob=p_model, implied_prob=p_imp,
                        ev=ev, edge=edge, kelly=max(kelly, 0),
                    ))
        results.sort(key=lambda v: v.ev, reverse=True)
        logger.info("识别价值投注 %d 笔", len(results))
        return results

    def backtest(
        self, league_code: str, season: str,
        bookmaker: str = "Pinnacle", period: str = "closing",
        min_edge: float = 0.03, stake: float = 1.0,
    ) -> dict:
        """回测：对历史已完赛比赛的价值投注，计算实际盈亏。"""
        bets = self.find(league_code, season, bookmaker, period, min_edge)
        wins = losses = 0
        profit = 0.0
        for b in bets:
            row = self.db.execute(
                "SELECT ft_result, ft_home_goals, ft_away_goals FROM matches WHERE id=?",
                (b.match_id,),
            )
            if not row:
                continue
            r = row[0]
            res = r["ft_result"]
            # 判定市场是否中奖
            if b.market == "home":
                hit = res == "H"
            elif b.market == "draw":
                hit = res == "D"
            elif b.market == "away":
                hit = res == "A"
            elif b.market == "over_2_5":
                hit = (r["ft_home_goals"] or 0) + (r["ft_away_goals"] or 0) > 2
            elif b.market == "under_2_5":
                hit = (r["ft_home_goals"] or 0) + (r["ft_away_goals"] or 0) <= 2
            else:
                continue
            if hit:
                profit += stake * (b.odds - 1)
                wins += 1
            else:
                profit -= stake
                losses += 1
        total = wins + losses
        return {
            "total_bets": total,
            "wins": wins,
            "losses": losses,
            "win_rate": wins / total if total else 0,
            "profit": round(profit, 2),
            "roi": round(profit / (total * stake) * 100, 1) if total else 0,
            "avg_odds": round(sum(b.odds for b in bets) / total, 2) if total else 0,
        }
