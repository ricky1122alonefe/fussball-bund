"""赛前关注清单生成器。

整理即将开赛场次 + 模型概率（+ 有则附庄家盘/edge）→ 输出 Markdown。
不做自动下注、不做竞彩串关。

数据流：
1. 从 matches 取未来场（ft_result IS NULL AND match_date >= today AND <= today+days）
2. 拟合模型（复用 _resolve_fit_seasons 逻辑；UCL 等无前序 FD 数据时回退 max_date）
3. 对每场预测概率 + 查赔率 + 算 edge/EV
4. 输出 Markdown（固定头部 + 每场表格）
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime

from fussball_bund.storage.db import Database, get_db

logger = logging.getLogger(__name__)

# 赔率 period 优先级（最当前优先）
_PERIOD_PRIORITY = {"live": 0, "opening": 1, "closing": 2}


@dataclass
class PreviewOdds:
    market: str
    bookmaker: str
    period: str
    odds: float
    implied_prob: float
    model_prob: float
    edge: float
    ev: float
    label: str  # "关注" or "中性"


@dataclass
class PreviewMatch:
    match_id: int
    match_date: str | None
    home_team: str
    away_team: str
    p_home: float
    p_draw: float
    p_away: float
    lambda_home: float
    lambda_away: float
    top_scores: list[tuple[tuple[int, int], float]]
    odds: list[PreviewOdds] = field(default_factory=list)
    has_odds: bool = False


@dataclass
class PreviewResult:
    league: str
    league_name: str
    model: str
    calibrate: bool
    fit_info: str
    matches: list[PreviewMatch]
    n_no_odds: int
    warnings: list[str]
    generated_at: str

    @property
    def n_matches(self) -> int:
        return len(self.matches)


def _resolve_fit_seasons(target_season: str, n_seasons: int = 3) -> list[str]:
    """与 cli._resolve_fit_seasons 同逻辑：目标赛季前 n 个赛季。"""
    start = int(target_season.split("-")[0])
    return [f"{start - i}-{start - i + 1}" for i in range(1, n_seasons + 1)]


def _fit_model(model_name: str, db: Database, league: str,
               current_season: str, first_future_date: str):
    """构建并拟合模型。优先赛季模式；失败回退 max_date 模式。

    Returns:
        (model, fit_info) 或 (None, "")
    """
    from fussball_bund.analysis import DixonColesModel, PoissonModel, XGPoissonModel

    if model_name == "dixoncoles":
        model = DixonColesModel(db=db)
    elif model_name == "xgpoisson":
        model = XGPoissonModel(db=db)
    else:
        model = PoissonModel(db=db)

    # 优先：赛季模式（与 predict 一致）
    seasons = _resolve_fit_seasons(current_season)
    try:
        model.fit(league, seasons)
        return model, f"赛季 {', '.join(seasons)}（多赛季拟合）"
    except ValueError:
        pass

    # 回退：max_date 模式（跨赛季全部历史，适配 UCL 等无 FD 前序数据的联赛）
    try:
        model.fit(league, max_date=first_future_date)
        return model, f"全部 match_date < {first_future_date} 的完赛数据（跨赛季，max_date 模式）"
    except ValueError:
        return None, ""


def generate_preview(
    league: str,
    days: int = 7,
    model_name: str = "dixoncoles",
    calibrate: bool = False,
    calibrate_alpha: float = 0.4,
    bookmaker: str = "Pinnacle",
    min_edge: float = 0.03,
    db: Database | None = None,
) -> PreviewResult:
    """生成赛前关注清单。

    Args:
        league: 联赛 key
        days: 未来天数范围
        model_name: poisson/dixoncoles/xgpoisson
        calibrate: 启用平局校准（仅在有赔率时生效）
        bookmaker: 对比庄家
        min_edge: 关注阈值
    """
    db = db or get_db()
    from fussball_bund.analysis.probability import implied_probabilities
    from fussball_bund.config import load_leagues

    leagues = load_leagues()
    league_cfg = leagues.get(league)
    league_name = league_cfg.name if league_cfg else league
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # 1. 查未来场
    future = db.execute(
        "SELECT id, match_date, home_team, away_team FROM matches "
        "WHERE league_code=? AND ft_result IS NULL AND match_date IS NOT NULL "
        "AND match_date >= date('now') "
        f"AND match_date <= date('now', '+{int(days)} days') "
        "ORDER BY match_date, home_team",
        (league,),
    )

    warnings: list[str] = []
    if not future:
        total = db.execute(
            "SELECT COUNT(*) AS n FROM matches WHERE league_code=?", (league,)
        )[0]["n"]
        if total == 0:
            warnings.append(
                f"库内无 {league} 数据，请先（免费）采集历史："
                f"fussball collect-history -l {league} -s <season>"
            )
        else:
            # 零付费默认：FBref 赛程写未完赛；Odds API 可选（非必须）
            warnings.append(
                f"有 {total} 场历史比赛但无未来场。"
                f"免费拉赛程：fussball collect-fundamentals -l {league} -s <当前赛季> --source fbref "
                f"（写入未完赛后即可 preview，无需买 API）。"
                f"可选实时盘：配置 ODDS_API_KEY 后 fussball collect-odds -l {league}"
            )
        return PreviewResult(
            league=league, league_name=league_name, model=model_name,
            calibrate=calibrate, fit_info="（无未来场，未拟合）",
            matches=[], n_no_odds=0, warnings=warnings, generated_at=now_str,
        )

    # 2. 推断当前赛季 + 拟合
    first_date = future[0]["match_date"]
    y, m = int(first_date[:4]), int(first_date[5:7])
    current_season = f"{y}-{y + 1}" if m >= 7 else f"{y - 1}-{y}"

    model, fit_info = _fit_model(model_name, db, league, current_season, first_date)
    if model is None:
        warnings.append(
            f"拟合失败：{league} 历史完赛数据不足，无法预测。"
            f"请先采集更多历史数据。"
        )
        return PreviewResult(
            league=league, league_name=league_name, model=model_name,
            calibrate=calibrate, fit_info="（拟合失败）",
            matches=[], n_no_odds=0, warnings=warnings, generated_at=now_str,
        )

    # 3. 逐场预测 + 查赔率
    preview_matches: list[PreviewMatch] = []
    n_no_odds = 0

    for fm in future:
        pred = model.predict(fm["home_team"], fm["away_team"])

        # 查赔率（period 优先 live > opening > closing）
        odds_rows = db.execute(
            "SELECT bookmaker, period, home, draw, away FROM odds_1x2 "
            "WHERE match_id=? AND bookmaker=? "
            "ORDER BY CASE period WHEN 'live' THEN 0 WHEN 'opening' THEN 1 ELSE 2 END",
            (fm["id"], bookmaker),
        )

        pm = PreviewMatch(
            match_id=fm["id"], match_date=fm["match_date"],
            home_team=fm["home_team"], away_team=fm["away_team"],
            p_home=pred.p_home, p_draw=pred.p_draw, p_away=pred.p_away,
            lambda_home=pred.lambda_home, lambda_away=pred.lambda_away,
            top_scores=pred.top_scores,
        )

        if odds_rows and odds_rows[0]["home"]:
            o = odds_rows[0]
            oh, od, oa = o["home"], o["draw"], o["away"]
            try:
                implied = implied_probabilities((oh, od, oa))
            except Exception:
                implied = None

            if implied and len(implied) >= 3:
                # 校准（仅在有赔率时生效）
                if calibrate:
                    from fussball_bund.analysis.calibration import calibrate_draw
                    ph, pd, pa = calibrate_draw(pred, implied, calibrate_alpha)
                else:
                    ph, pd, pa = pred.p_home, pred.p_draw, pred.p_away

                for i, (market, p_model, odds_val, p_imp) in enumerate([
                    ("home", ph, oh, implied[0]),
                    ("draw", pd, od, implied[1]),
                    ("away", pa, oa, implied[2]),
                ]):
                    if not odds_val:
                        continue
                    edge = p_model - p_imp
                    ev = p_model * odds_val - 1
                    label = "关注" if edge >= min_edge and ev > 0 else "中性"
                    pm.odds.append(PreviewOdds(
                        market=market, bookmaker=o["bookmaker"],
                        period=o["period"], odds=odds_val,
                        implied_prob=round(p_imp, 4),
                        model_prob=round(p_model, 4),
                        edge=round(edge, 4), ev=round(ev, 4),
                        label=label,
                    ))
                pm.has_odds = bool(pm.odds)

        if not pm.has_odds:
            n_no_odds += 1

        preview_matches.append(pm)

    if n_no_odds > 0:
        warnings.append(f"{n_no_odds} 场无盘口（字段标「无盘口」，不伪造 edge）")

    return PreviewResult(
        league=league, league_name=league_name, model=model_name,
        calibrate=calibrate, fit_info=fit_info,
        matches=preview_matches, n_no_odds=n_no_odds,
        warnings=warnings, generated_at=now_str,
    )


def format_markdown(result: PreviewResult) -> str:
    """格式化为 Markdown 报告。"""
    lines: list[str] = []

    # 头部
    lines.append(f"# 赛前关注清单 — {result.league_name}（{result.league}）")
    lines.append("")
    lines.append(f"- 生成时间: {result.generated_at}")
    lines.append(f"- 联赛: {result.league}（{result.league_name}）")
    calib_str = f"（calibrate: on, α=0.4）" if result.calibrate else "（calibrate: off）"
    lines.append(f"- 模型: {result.model}{calib_str}")
    lines.append(f"- 拟合: {result.fit_info}")
    lines.append(f"- 未来场: {result.n_matches} 场")
    if result.n_no_odds > 0:
        lines.append(f"- 赔率缺失: {result.n_no_odds} 场无盘口")
    lines.append("")
    lines.append(
        "> ⚠️ 风险声明：本报告仅供研究参考，不构成投注建议。"
        "模型概率基于历史数据，不反映伤停、动机、天气等实时因素。"
        "请结合多方信息研判，勿只跟 edge。"
    )
    lines.append("")
    lines.append("> 🤖 AI 使用提示：以下数字供研判，请结合伤停/动机，勿只跟 edge。")
    lines.append("")
    lines.append("---")

    if not result.matches:
        lines.append("")
        for w in result.warnings:
            lines.append(f"- {w}")
        return "\n".join(lines)

    # 每场
    for pm in result.matches:
        lines.append("")
        date_str = pm.match_date or "未知日期"
        lines.append(f"## {date_str} {pm.home_team} vs {pm.away_team}")
        lines.append("")
        lines.append("| 项目 | 值 |")
        lines.append("|------|-----|")
        lines.append(
            f"| 模型胜平负 | 主 {pm.p_home:.1%} / 平 {pm.p_draw:.1%} / 客 {pm.p_away:.1%} |"
        )
        lines.append(
            f"| 期望进球 λ | 主 {pm.lambda_home:.2f} / 客 {pm.lambda_away:.2f} |"
        )
        if pm.top_scores:
            scores_str = " / ".join(
                f"{h}-{a} ({p:.1%})" for (h, a), p in pm.top_scores[:3]
            )
            lines.append(f"| Top 3 比分 | {scores_str} |")

        if pm.has_odds:
            o0 = pm.odds[0]
            lines.append("")
            lines.append(f"**盘口**（{o0.bookmaker} / {o0.period}）:")
            lines.append("")
            lines.append(
                "| 市场 | 赔率 | 隐含概率 | 模型概率 | Edge | EV | 标记 |"
            )
            lines.append(
                "|------|------|---------|---------|------|-----|------|"
            )
            for o in pm.odds:
                market_cn = {"home": "主胜", "draw": "平", "away": "客胜"}.get(
                    o.market, o.market
                )
                lines.append(
                    f"| {market_cn} | {o.odds:.2f} | {o.implied_prob:.1%} | "
                    f"{o.model_prob:.1%} | {o.edge:+.1%} | {o.ev:+.1%} | {o.label} |"
                )
        else:
            lines.append("")
            lines.append("**无盘口**")

        lines.append("")
        lines.append("---")

    return "\n".join(lines)
