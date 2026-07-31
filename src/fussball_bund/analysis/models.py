"""Poisson 进球模型。

基于历史比赛结果估计每队攻防强度，用 Poisson 分布预测各比分概率。
经典足球预测模型（Dixon-Coles 的简化版）。

模型假设：
    - 进球数服从 Poisson 分布
    - 主队进球 λ_home = 主队主场攻击强度 × 客队客场防守强度 × 联赛平均主场进球
    - 客队进球 λ_away = 客队客场攻击强度 × 主队主场防守强度 × 联赛平均客场进球

强度定义（相对联赛均值）：
    home_attack(team)  = 该队主场场均进球 / 联赛平均主场进球
    home_defense(team) = 该队主场场均失球 / 联赛平均客场进球
    away_attack(team)  = 该队客场场均进球 / 联赛平均客场进球
    away_defense(team) = 该队客场场均失球 / 联赛平均主场进球
"""
from __future__ import annotations

import logging
import math
from collections import defaultdict
from dataclasses import dataclass, field

from fussball_bund.storage.db import Database, get_db

logger = logging.getLogger(__name__)


@dataclass
class MatchPrediction:
    home_team: str
    away_team: str
    lambda_home: float
    lambda_away: float
    p_home: float
    p_draw: float
    p_away: float
    p_over_2_5: float
    p_under_2_5: float
    # 最可能比分（前3）
    top_scores: list[tuple[tuple[int, int], float]] = field(default_factory=list)

    @property
    def p_triple(self) -> tuple[float, float, float]:
        return self.p_home, self.p_draw, self.p_away


class PoissonModel:
    """基于历史比分的 Poisson 进球预测模型。"""

    def __init__(
        self,
        db: Database | None = None,
        new_team_prior: tuple[float, float] = (0.85, 1.15),
    ) -> None:
        self.db = db or get_db()
        self.new_team_prior = new_team_prior
        self.avg_home_goals: float = 0.0
        self.avg_away_goals: float = 0.0
        self.home_attack: dict[str, float] = {}
        self.home_defense: dict[str, float] = {}
        self.away_attack: dict[str, float] = {}
        self.away_defense: dict[str, float] = {}
        self._fitted = False

    def fit(self, league_code: str, seasons: list[str], min_matches: int = 5) -> "PoissonModel":
        """用指定联赛+赛季的历史比赛拟合模型。

        Args:
            min_matches: 球队至少参赛场次，不足则回退到联赛均值(强度=1.0)
        """
        ph = ", ".join("?" * len(seasons))
        rows = self.db.execute(
            f"SELECT home_team, away_team, ft_home_goals, ft_away_goals FROM matches "
            f"WHERE league_code=? AND season IN ({ph}) "
            f"AND ft_home_goals IS NOT NULL AND ft_away_goals IS NOT NULL",
            (league_code, *seasons),
        )
        if not rows:
            raise ValueError(f"无历史比赛数据: {league_code} {seasons}")

        home_scored = defaultdict(list)  # 主队主场进球
        home_conceded = defaultdict(list)  # 主队主场失球
        away_scored = defaultdict(list)
        away_conceded = defaultdict(list)
        total_home = total_away = 0.0
        n = 0
        for r in rows:
            hg, ag = r["ft_home_goals"], r["ft_away_goals"]
            home_scored[r["home_team"]].append(hg)
            home_conceded[r["home_team"]].append(ag)
            away_scored[r["away_team"]].append(ag)
            away_conceded[r["away_team"]].append(hg)
            total_home += hg
            total_away += ag
            n += 1

        self.avg_home_goals = total_home / n if n else 1.35
        self.avg_away_goals = total_away / n if n else 1.15
        # 防止除零
        self.avg_home_goals = self.avg_home_goals or 1.35
        self.avg_away_goals = self.avg_away_goals or 1.15

        def _mean(xs):
            return sum(xs) / len(xs) if xs else None

        for team, vals in home_scored.items():
            if len(vals) >= min_matches:
                self.home_attack[team] = (_mean(vals) or self.avg_home_goals) / self.avg_home_goals
        for team, vals in home_conceded.items():
            if len(vals) >= min_matches:
                self.home_defense[team] = (_mean(vals) or self.avg_away_goals) / self.avg_away_goals
        for team, vals in away_scored.items():
            if len(vals) >= min_matches:
                self.away_attack[team] = (_mean(vals) or self.avg_away_goals) / self.avg_away_goals
        for team, vals in away_conceded.items():
            if len(vals) >= min_matches:
                self.away_defense[team] = (_mean(vals) or self.avg_home_goals) / self.avg_home_goals

        self._fitted = True
        logger.info(
            "Poisson 拟合完成 %s %s: %d 场比赛, 平均主队进球=%.2f, 平均客队进球=%.2f, 球队数=%d",
            league_code, seasons, n, self.avg_home_goals, self.avg_away_goals,
            len(self.home_attack),
        )
        return self

    def _strength(self, table: dict[str, float], team: str, default: float = 1.0) -> float:
        # 未达 min_matches 的球队回退到联赛均值（强度=1.0）
        return table.get(team, default)

    def predict(self, home_team: str, away_team: str, max_goals: int = 10) -> MatchPrediction:
        """预测比赛。"""
        if not self._fitted:
            raise RuntimeError("模型未拟合，请先调用 fit()")

        atk_prior, def_prior = self.new_team_prior
        ha = self.home_attack.get(home_team, atk_prior)
        hd = self.home_defense.get(home_team, def_prior)
        aa = self.away_attack.get(away_team, atk_prior)
        ad = self.away_defense.get(away_team, def_prior)

        lam_h = ha * ad * self.avg_home_goals
        lam_a = aa * hd * self.avg_away_goals

        # 比分矩阵
        p_home = p_draw = p_away = 0.0
        p_over = 0.0
        scores: list[tuple[tuple[int, int], float]] = []
        for i in range(max_goals + 1):
            for j in range(max_goals + 1):
                p = _poisson_pmf(i, lam_h) * _poisson_pmf(j, lam_a)
                if i > j:
                    p_home += p
                elif i == j:
                    p_draw += p
                else:
                    p_away += p
                if i + j > 2:
                    p_over += p
                scores.append(((i, j), p))

        scores.sort(key=lambda x: x[1], reverse=True)
        # 归一化（截断 max_goals 会有少量概率损失）
        s = p_home + p_draw + p_away
        if s > 0:
            p_home, p_draw, p_away = p_home / s, p_draw / s, p_away / s
            p_over = p_over / s

        return MatchPrediction(
            home_team=home_team,
            away_team=away_team,
            lambda_home=lam_h,
            lambda_away=lam_a,
            p_home=p_home,
            p_draw=p_draw,
            p_away=p_away,
            p_over_2_5=p_over,
            p_under_2_5=1 - p_over,
            top_scores=scores[:3],
        )


def _poisson_pmf(k: int, lam: float) -> float:
    """Poisson 概率质量函数（纯 math 实现，避免 scipy 依赖）。"""
    if lam <= 0:
        return 1.0 if k == 0 else 0.0
    return math.exp(-lam) * (lam ** k) / math.factorial(k)
