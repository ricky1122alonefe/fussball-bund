"""竞猜分析简报生成。

输出 Markdown 格式报告：球队实力排名、模型预测准确率、价值投注清单。
用前一赛季数据拟合模型，对目标赛季生成分析。
"""
from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from fussball_bund.storage.db import Database, get_db

logger = logging.getLogger(__name__)


def _resolve_fit_seasons(target_season: str, n_seasons: int = 3) -> list[str]:
    start = int(target_season.split("-")[0])
    return [f"{start - i}-{start - i + 1}" for i in range(1, n_seasons + 1)]


def _build_model(name: str, db: Database, league: str, seasons: list[str]):
    if name == "dixoncoles":
        from fussball_bund.analysis import DixonColesModel

        return DixonColesModel(db=db).fit(league, seasons)
    from fussball_bund.analysis import PoissonModel

    return PoissonModel(db=db).fit(league, seasons)


def generate_report(
    league_code: str,
    season: str,
    model_name: str = "dixoncoles",
    db: Database | None = None,
    output: str | None = None,
    calibrate: bool = False,
    fit_seasons: str | None = None,
) -> str:
    """生成竞猜分析简报（Markdown）。"""
    db = db or get_db()
    from fussball_bund.config import load_leagues

    cfg = load_leagues()[league_code]
    seasons = [s.strip() for s in fit_seasons.split(",")] if fit_seasons else _resolve_fit_seasons(season)
    mdl = _build_model(model_name, db, league_code, seasons)

    lines: list[str] = []
    lines.append(f"# {cfg.name}（{cfg.name_en}）{season} 竞猜分析简报")
    lines.append(
        f"\n> 预测模型: **{model_name}** ｜ 拟合数据: {seasons} ｜ "
        f"生成: {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    )

    # ---- 1. 球队实力排名 ----
    lines.append("\n## 一、球队实力排名\n")
    lines.append("综合评分 = 攻击强度 − 防守强度（越高越强）；正值高于联赛均值。\n")
    lines.append("| 排名 | 球队 | 攻击 | 防守 | 综合 |")
    lines.append("|:---:|---|:---:|:---:|:---:|")
    # Dixon-Coles 有 attack/defense；Poisson 用强度表
    attack = getattr(mdl, "attack", {})
    defense = getattr(mdl, "defense", {})
    if not attack:
        attack = mdl.home_attack
        defense = mdl.home_defense
    teams = sorted(attack.keys(), key=lambda t: attack[t] - defense.get(t, 0), reverse=True)
    for i, t in enumerate(teams, 1):
        a = attack.get(t, 0.0)
        d = defense.get(t, 0.0)
        lines.append(f"| {i} | {t} | {a:+.2f} | {d:+.2f} | {a - d:+.2f} |")

    # ---- 2. 预测准确率 ----
    lines.append("\n## 二、模型预测准确率\n")
    rows = db.execute(
        "SELECT home_team, away_team, ft_result FROM matches "
        "WHERE league_code=? AND season=? AND ft_result IS NOT NULL",
        (league_code, season),
    )
    correct = total = 0
    result_dist = {"H": 0, "D": 0, "A": 0}
    pred_dist = {"H": 0, "D": 0, "A": 0}
    for r in rows:
        pred = mdl.predict(r["home_team"], r["away_team"])
        probs = {"H": pred.p_home, "D": pred.p_draw, "A": pred.p_away}
        pred_res = max(probs, key=probs.get)
        actual = r["ft_result"]
        pred_dist[pred_res] += 1
        result_dist[actual] += 1
        if pred_res == actual:
            correct += 1
        total += 1
    acc = correct / total if total else 0
    lines.append(f"- 样本: **{total}** 场已完赛")
    lines.append(f"- 命中率（取最大概率）: **{acc:.1%}**")
    lines.append(
        f"- 实际结果分布: 主胜 {result_dist['H']} / 平 {result_dist['D']} / 客胜 {result_dist['A']}"
    )
    lines.append(
        f"- 模型预测分布: 主胜 {pred_dist['H']} / 平 {pred_dist['D']} / 客胜 {pred_dist['A']}"
    )
    # 平局往往被低估，提示校准
    if pred_dist["D"] == 0 and result_dist["D"] > 0:
        lines.append("- ⚠️ 模型从未预测平局（Poisson 类模型通病），实际平局占比较高，需结合赔率判断")

    # ---- 3. 价值投注清单 ----
    lines.append("\n## 三、价值投注清单（Top 15）\n")
    lines.append(
        "> 模型概率显著高于庄家隐含概率的投注。\n"
        "> ⚠️ 回测显示基础模型对 Pinnacle 收盘 ROI 为负（市场效率），"
        "以下仅作参考，不构成投注建议。\n"
    )
    from fussball_bund.analysis import ValueBetFinder

    finder = ValueBetFinder(db=db, model=mdl, calibrate=calibrate)
    bets = finder.find(league_code, season, min_edge=0.02)
    # 过滤极端冷门（高赔率下模型概率估计不可靠）并按 edge 降序
    bets = sorted([b for b in bets if b.odds <= 8.0], key=lambda b: b.edge, reverse=True)
    if bets:
        lines.append("| 日期 | 主队 | 客队 | 市场 | 赔率 | 模型概率 | 隐含概率 | Edge | EV |")
        lines.append("|---|---|---|---|:---:|:---:|:---:|:---:|:---:|")
        for b in bets[:15]:
            lines.append(
                f"| {b.match_date or ''} | {b.home_team} | {b.away_team} | "
                f"{b.market} | {b.odds:.2f} | {b.model_prob:.1%} | "
                f"{b.implied_prob:.1%} | {b.edge:+.1%} | {b.ev:+.1%} |"
            )
        lines.append(f"\n共识别 {len(bets)} 笔潜在价值投注")
    else:
        lines.append("无价值投注")

    # ---- 4. 回测概览 ----
    lines.append("\n## 四、策略回测概览\n")
    bt = finder.backtest(league_code, season, min_edge=0.03)
    lines.append(f"- 投注笔数: {bt['total_bets']}")
    lines.append(f"- 命中率: {bt['win_rate']:.1%}")
    lines.append(f"- 盈亏: {bt['profit']:+.2f}（单位注）")
    lines.append(f"- ROI: {bt['roi']:+.1f}%")
    lines.append(
        "\n> 结论: 基础进球模型难以稳定击败 Pinnacle 收盘赔率。"
        "改进方向：多赛季加权拟合、xG 替代进球、加入近期状态/伤停因子。"
    )

    content = "\n".join(lines)
    if output:
        p = Path(output)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        logger.info("简报已保存至 %s", output)
    return content
