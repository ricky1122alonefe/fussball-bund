"""Dixon-Coles 进球模型。

对基础 Poisson 的三项关键改进：
1. 最大似然参数估计：联合估计每队攻击/防守强度、主场优势、低比分相关性
   （基础 Poisson 仅用均值比率，Dixon-Coles 用数值优化求最优参数）
2. 低比分修正函数 τ：修正 Poisson 对 0-0/1-0/0-1/1-1 的系统性偏差
3. 时间衰减权重 w(t) = exp(-ξ·Δt)：近期比赛权重更高，捕捉球队状态变化

Dixon-Coles τ 函数（λ=主队期望进球, μ=客队期望进球, ρ=相关性参数，通常为负）:
    τ(0,0) = 1 - λμρ      （Poisson 高估 0-0，ρ<0 时上调）
    τ(0,1) = 1 + λρ        （修正 0-1）
    τ(1,0) = 1 + μρ        （修正 1-0）
    τ(1,1) = 1 - ρ         （Poisson 低估 1-1，ρ<0 时上调）
    其他   = 1

参数化：
    λ_home = exp(attack[home] + defense[away] + home_adv)
    λ_away = exp(attack[away] + defense[home])
    约束: Σ attack = 0 （可识别性）

参考: Dixon & Coles (1997), "Modelling Association Football Scores and
      Inefficiencies in the Football Betting Market"
"""
from __future__ import annotations

import logging
import math
from datetime import datetime

import numpy as np
from scipy.optimize import minimize
from scipy.special import gammaln

from fussball_bund.analysis.models import MatchPrediction
from fussball_bund.storage.db import Database, get_db

logger = logging.getLogger(__name__)


def _dc_tau(m: int, n: int, lam: float, mu: float, rho: float) -> float:
    """Dixon-Coles 低比分修正函数。"""
    if m == 0 and n == 0:
        return 1.0 - lam * mu * rho
    if m == 0 and n == 1:
        return 1.0 + lam * rho
    if m == 1 and n == 0:
        return 1.0 + mu * rho
    if m == 1 and n == 1:
        return 1.0 - rho
    return 1.0


class DixonColesModel:
    """Dixon-Coles 加权最大似然进球预测模型。"""

    def __init__(
        self,
        db: Database | None = None,
        decay: float = 0.0018,
        new_team_prior: tuple[float, float] = (-0.25, 0.25),
    ) -> None:
        """
        Args:
            decay: 时间衰减系数 ξ（单位：1/天）。
                   0.0018 ≈ 半衰期 385 天（约 1 年，Dixon-Coles 原论文值）
                   0.006  ≈ 半衰期 115 天（约 4 个月，更适合捕捉赛季内状态）
            new_team_prior: 未见过球队（如升级队）的先验 (attack, defense)。
                            默认 (-0.25, 0.25) 表示弱队先验（进攻低于均值、防守差于均值）。
        """
        self.db = db or get_db()
        self.decay = decay
        self.new_team_prior = new_team_prior
        self.attack: dict[str, float] = {}
        self.defense: dict[str, float] = {}
        self.home_adv: float = 0.0
        self.rho: float = 0.0
        self.teams: list[str] = []
        self._fitted = False

    def fit(
        self,
        league_code: str,
        seasons: list[str],
        ref_date: str | None = None,
    ) -> "DixonColesModel":
        rows = self.db.execute(
            f"SELECT home_team, away_team, ft_home_goals, ft_away_goals, match_date "
            f"FROM matches WHERE league_code=? AND season IN ({','.join('?' * len(seasons))}) "
            f"AND ft_home_goals IS NOT NULL AND ft_away_goals IS NOT NULL",
            (league_code, *seasons),
        )
        if not rows:
            raise ValueError(f"无历史数据: {league_code} {seasons}")

        teams = sorted({r["home_team"] for r in rows} | {r["away_team"] for r in rows})
        self.teams = teams
        idx = {t: i for i, t in enumerate(teams)}
        N = len(teams)

        # 参考日期：用最新比赛日（近期权重最高）
        dates = [r["match_date"] for r in rows if r["match_date"]]
        ref = ref_date or (max(dates) if dates else datetime.now().isoformat()[:10])

        # 预构建 numpy 数组（加速优化）
        hi = np.array([idx[r["home_team"]] for r in rows])
        ai = np.array([idx[r["away_team"]] for r in rows])
        m_arr = np.array([r["ft_home_goals"] for r in rows], dtype=float)
        n_arr = np.array([r["ft_away_goals"] for r in rows], dtype=float)
        weights = np.array([_weight(r["match_date"], ref, self.decay) for r in rows])
        lg_m = gammaln(m_arr + 1)  # log(k!) 预计算，不依赖参数
        lg_n = gammaln(n_arr + 1)

        def neg_log_likelihood(theta: np.ndarray) -> float:
            attack = theta[:N]
            defense = theta[N : 2 * N]
            home_adv = theta[2 * N]
            rho = theta[2 * N + 1]

            lam_h = np.exp(attack[hi] + defense[ai] + home_adv)
            lam_a = np.exp(attack[ai] + defense[hi])

            # τ 修正（向量化）
            tau = np.ones(len(rows))
            tau[(m_arr == 0) & (n_arr == 0)] = 1 - lam_h[(m_arr == 0) & (n_arr == 0)] * lam_a[(m_arr == 0) & (n_arr == 0)] * rho
            tau[(m_arr == 0) & (n_arr == 1)] = 1 + lam_h[(m_arr == 0) & (n_arr == 1)] * rho
            tau[(m_arr == 1) & (n_arr == 0)] = 1 + lam_a[(m_arr == 1) & (n_arr == 0)] * rho
            tau[(m_arr == 1) & (n_arr == 1)] = 1 - rho
            tau = np.maximum(tau, 1e-10)  # 防止 log(0)

            # log Poisson PMF: -λ + k·log(λ) - log(k!)
            log_p = (
                np.log(tau)
                - lam_h + m_arr * np.log(lam_h) - lg_m
                - lam_a + n_arr * np.log(lam_a) - lg_n
            )
            nll = -np.sum(weights * log_p)
            # 软约束: Σ attack = 0（可识别性）
            nll += 10.0 * (attack.sum() ** 2)
            return nll

        x0 = np.concatenate([
            np.full(N, 0.0),    # attack
            np.full(N, 0.0),    # defense
            [0.25],             # home_adv
            [-0.1],             # rho
        ])
        bounds = [(None, None)] * (2 * N) + [(None, None), (-0.5, 0.5)]

        result = minimize(neg_log_likelihood, x0, method="L-BFGS-B", bounds=bounds)
        theta = result.x
        self.attack = {t: float(theta[i]) for i, t in enumerate(teams)}
        self.defense = {t: float(theta[N + i]) for i, t in enumerate(teams)}
        self.home_adv = float(theta[2 * N])
        self.rho = float(theta[2 * N + 1])
        self._fitted = True

        logger.info(
            "Dixon-Coles 拟合完成 %s %s: %d 场, rho=%.4f, home_adv=%.4f, 收敛=%s",
            league_code, seasons, len(rows), self.rho, self.home_adv,
            result.success,
        )
        return self

    def predict(self, home_team: str, away_team: str, max_goals: int = 10) -> MatchPrediction:
        if not self._fitted:
            raise RuntimeError("模型未拟合，请先调用 fit()")
        # 未见过的新球队（如升级队）用弱队先验，避免高估
        atk_prior, def_prior = self.new_team_prior
        ah = self.attack.get(home_team, atk_prior)
        dh = self.defense.get(home_team, def_prior)
        aa = self.attack.get(away_team, atk_prior)
        da = self.defense.get(away_team, def_prior)

        lam_h = math.exp(ah + da + self.home_adv)
        lam_a = math.exp(aa + dh)

        p_home = p_draw = p_away = 0.0
        p_over = 0.0
        scores: list[tuple[tuple[int, int], float]] = []
        for i in range(max_goals + 1):
            for j in range(max_goals + 1):
                tau = _dc_tau(i, j, lam_h, lam_a, self.rho)
                base = math.exp(
                    _log_poisson(i, lam_h) + _log_poisson(j, lam_a)
                )
                p = max(tau, 0.0) * base
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


def _log_poisson(k: int, lam: float) -> float:
    if lam <= 0:
        return 0.0 if k == 0 else -1e10
    return -lam + k * math.log(lam) - math.lgamma(k + 1)


def _weight(match_date: str | None, ref_date: str, decay: float) -> float:
    """时间衰减权重 w = exp(-ξ · Δt_days)。"""
    if not match_date:
        return 1.0
    try:
        a = datetime.fromisoformat(match_date[:10])
        b = datetime.fromisoformat(ref_date[:10])
        days = max((b - a).days, 0)
        return math.exp(-decay * days)
    except Exception:
        return 1.0
