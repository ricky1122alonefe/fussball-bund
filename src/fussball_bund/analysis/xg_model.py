"""xG 进球模型（基于预期进球）。

用 Understat 的 xG（预期进球）替代实际进球估计球队攻防强度。
xG 比实际进球更稳定——去除了射门转化的随机性（进球与否的运气），
理论上能更准确地反映球队真实实力，预测更稳定。

球队名映射：
    Understat 球队名（如 "Manchester United"）与 football-data（如 "Man United"）不一致。
    本模型通过比赛日期自动匹配两表，建立 Understat 名 → football-data 名映射，
    使 xG 模型能无缝接入基于 football-data 赔率的回测与价值投注识别。

局限：
    - Understat 仅覆盖五大联赛（不含欧冠）
    - 需先采集 understat 数据（collect-fundamentals --source understat）
    - 单赛季 xG 样本量较小（380 场），强度估计波动较大
"""
from __future__ import annotations

import logging
import math
from collections import defaultdict

from fussball_bund.analysis.models import MatchPrediction
from fussball_bund.storage.db import Database, get_db

logger = logging.getLogger(__name__)


class XGPoissonModel:
    """基于 xG 的 Poisson 进球预测模型。

    结构与 PoissonModel 一致，但 fit 数据源为 Understat xG（而非实际进球）。
    """

    def __init__(
        self,
        db: Database | None = None,
        new_team_prior: tuple[float, float] = (0.85, 1.15),
    ) -> None:
        self.db = db or get_db()
        self.new_team_prior = new_team_prior
        self.avg_home_xg: float = 0.0
        self.avg_away_xg: float = 0.0
        self.home_attack: dict[str, float] = {}
        self.home_defense: dict[str, float] = {}
        self.away_attack: dict[str, float] = {}
        self.away_defense: dict[str, float] = {}
        self._fitted = False

    def fit(
        self,
        league_code: str,
        seasons: list[str] | None = None,
        min_matches: int = 5,
        max_date: str | None = None,
    ) -> "XGPoissonModel":
        # 1. 从 understat_shots 聚合每场 home_xg/away_xg + date + understat 球队名
        # walk-forward 模式：用 date < max_date 的 xG（跨赛季，严格反泄漏）
        if max_date is not None:
            rows = self.db.execute(
                "SELECT match_id, date, home_team, away_team, "
                "SUM(CASE WHEN h_a='h' THEN xg END) AS home_xg, "
                "SUM(CASE WHEN h_a='a' THEN xg END) AS away_xg "
                "FROM understat_shots WHERE league=? AND date < ? "
                "GROUP BY match_id, date, home_team, away_team",
                (league_code, max_date),
            )
            label = f"xG<{max_date}"
        else:
            ph = ",".join("?" * len(seasons))
            rows = self.db.execute(
                f"SELECT match_id, date, home_team, away_team, "
                f"SUM(CASE WHEN h_a='h' THEN xg END) AS home_xg, "
                f"SUM(CASE WHEN h_a='a' THEN xg END) AS away_xg "
                f"FROM understat_shots WHERE league=? AND season IN ({ph}) "
                f"GROUP BY match_id, date, home_team, away_team",
                (league_code, *seasons),
            )
            label = str(seasons)
        if not rows:
            raise ValueError(
                f"无 Understat xG 数据: {league_code} {label}，"
                "请先执行 fussball collect-fundamentals --source understat 采集对应赛季/日期范围"
            )

        # 2. 用 date 匹配 matches 表，建 Understat 名 → football-data 名映射
        name_map: dict[str, str] = {}
        matched = 0
        for r in rows:
            if not r["date"]:
                continue
            m = self.db.execute(
                "SELECT home_team, away_team FROM matches "
                "WHERE league_code=? AND match_date=? LIMIT 1",
                (league_code, r["date"]),
            )
            if m:
                if r["home_team"] and m[0]["home_team"]:
                    name_map[r["home_team"]] = m[0]["home_team"]
                if r["away_team"] and m[0]["away_team"]:
                    name_map[r["away_team"]] = m[0]["away_team"]
                matched += 1
        logger.info("xG 球队名映射: %d 场匹配, %d 个队名", matched, len(name_map))

        # 3. 用 football-data 名聚合 xG 攻防强度
        home_xg_for = defaultdict(list)
        home_xg_against = defaultdict(list)
        away_xg_for = defaultdict(list)
        away_xg_against = defaultdict(list)
        total_home = total_away = 0.0
        n = 0
        for r in rows:
            hxg = r["home_xg"] or 0.0
            axg = r["away_xg"] or 0.0
            h_team = name_map.get(r["home_team"], r["home_team"])
            a_team = name_map.get(r["away_team"], r["away_team"])
            home_xg_for[h_team].append(hxg)
            home_xg_against[h_team].append(axg)
            away_xg_for[a_team].append(axg)
            away_xg_against[a_team].append(hxg)
            total_home += hxg
            total_away += axg
            n += 1

        self.avg_home_xg = total_home / n if n else 1.5
        self.avg_away_xg = total_away / n if n else 1.2
        self.avg_home_xg = self.avg_home_xg or 1.5
        self.avg_away_xg = self.avg_away_xg or 1.2

        def _mean(xs):
            return sum(xs) / len(xs) if xs else None

        for team, vals in home_xg_for.items():
            if len(vals) >= min_matches:
                self.home_attack[team] = (_mean(vals) or self.avg_home_xg) / self.avg_home_xg
        for team, vals in home_xg_against.items():
            if len(vals) >= min_matches:
                self.home_defense[team] = (_mean(vals) or self.avg_away_xg) / self.avg_away_xg
        for team, vals in away_xg_for.items():
            if len(vals) >= min_matches:
                self.away_attack[team] = (_mean(vals) or self.avg_away_xg) / self.avg_away_xg
        for team, vals in away_xg_against.items():
            if len(vals) >= min_matches:
                self.away_defense[team] = (_mean(vals) or self.avg_home_xg) / self.avg_home_xg

        self._fitted = True
        logger.info(
            "xG Poisson 拟合完成 %s %s: %d 场, avg_home_xg=%.2f, avg_away_xg=%.2f, 队数=%d",
            league_code, label, n, self.avg_home_xg, self.avg_away_xg, len(self.home_attack),
        )
        return self

    def predict(self, home_team: str, away_team: str, max_goals: int = 10) -> MatchPrediction:
        if not self._fitted:
            raise RuntimeError("模型未拟合，请先调用 fit()")
        atk_prior, def_prior = self.new_team_prior
        ha = self.home_attack.get(home_team, atk_prior)
        hd = self.home_defense.get(home_team, def_prior)
        aa = self.away_attack.get(away_team, atk_prior)
        ad = self.away_defense.get(away_team, def_prior)

        lam_h = ha * ad * self.avg_home_xg
        lam_a = aa * hd * self.avg_away_xg

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
    if lam <= 0:
        return 1.0 if k == 0 else 0.0
    return math.exp(-lam) * (lam ** k) / math.factorial(k)
