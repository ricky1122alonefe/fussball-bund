"""fussball-bund 命令行入口。

用法:
    fussball collect-history --league EPL --season 2024-2025
    fussball collect-history --all              # 五大联赛+欧冠 全部默认赛季
    fussball collect-odds --league EPL           # 实时赔率（需 ODDS_API_KEY）
    fussball collect-fundamentals --league EPL --season 2024-2025 --source fbref
    fussball query --league EPL --season 2024-2025 --limit 10
    fussball stats                               # 数据库统计
"""
from __future__ import annotations

import logging

import click

from fussball_bund.config import load_default_seasons, load_leagues
from fussball_bund.storage.db import get_db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("fussball_bund")


@click.group()
def cli() -> None:
    """fussball-bund: 五大联赛与欧冠足彩数据分析。"""


@cli.command("collect-history")
@click.option("--league", "-l", help="联赛 key（EPL/LALIGA/SERIE_A/BUNDESLIGA/LIGUE_1/UCL）")
@click.option("--season", "-s", help="赛季，如 2024-2025")
@click.option("--all", "fetch_all", is_flag=True, help="抓取全部默认联赛+赛季")
def collect_history(league: str | None, season: str | None, fetch_all: bool) -> None:
    """从 Football-Data.co.uk 抓取历史赔率与战绩（最稳定数据源）。"""
    from fussball_bund.collectors import FootballDataUKCollector

    c = FootballDataUKCollector(db=get_db())
    leagues = load_leagues()
    seasons = [season] if season else load_default_seasons()

    if fetch_all:
        c.collect_many(list(leagues.keys()), seasons)
    elif league:
        if league not in leagues:
            raise click.UsageError(f"未知联赛: {league}，可选: {list(leagues)}")
        for s in seasons:
            c.collect_season(league, s)
    else:
        raise click.UsageError("请指定 --league 或 --all")


@cli.command("collect-odds")
@click.option("--league", "-l", required=True, help="联赛 key")
def collect_odds(league: str) -> None:
    """从 The Odds API 抓取实时/即将开赛赔率（需 ODDS_API_KEY）。"""
    from fussball_bund.collectors import OddsApiCollector

    c = OddsApiCollector(db=get_db())
    c.collect_odds(league)


@cli.command("collect-fundamentals")
@click.option("--league", "-l", required=True, help="联赛 key")
@click.option("--season", "-s", required=True, help="赛季")
@click.option(
    "--source",
    type=click.Choice(["fbref", "understat", "clubelo"]),
    default="fbref",
    help="数据源",
)
@click.option("--team", help="clubelo 模式下的球队名")
def collect_fundamentals(league: str, season: str, source: str, team: str | None) -> None:
    """从 SoccerData 抓取基本面（FBref/Understat/ClubElo）。"""
    from fussball_bund.collectors import FundamentalsCollector

    c = FundamentalsCollector(db=get_db())
    if source == "fbref":
        n = c.collect_fbref_schedule(league, season)
        click.echo(f"FBref 赛程写入 {n} 行")
    elif source == "understat":
        n = c.collect_understat(league, season)
        click.echo(f"Understat 射门事件写入 {n} 行")
    elif source == "clubelo":
        if not team:
            raise click.UsageError("clubelo 需要 --team")
        n = c.collect_clubelo(team)
        click.echo(f"ClubElo 写入 {n} 行")


@cli.command("query")
@click.option("--league", "-l", help="联赛 key")
@click.option("--season", "-s", help="赛季")
@click.option("--limit", "-n", default=20, help="返回行数")
def query(league: str | None, season: str | None, limit: int) -> None:
    """查询比赛与赔率。"""
    db = get_db()
    where, params = [], []
    if league:
        where.append("league_code=?")
        params.append(league)
    if season:
        where.append("season=?")
        params.append(season)
    clause = ("WHERE " + " AND ".join(where)) if where else ""
    rows = db.execute(
        f"SELECT league_code,season,match_date,home_team,away_team,"
        f"ft_home_goals,ft_away_goals,ft_result FROM matches {clause} "
        f"ORDER BY match_date DESC LIMIT ?",
        tuple(params) + (limit,),
    )
    if not rows:
        click.echo("无数据")
        return
    click.echo(
        f"{'联赛':<12}{'日期':<12}{'主队':<16}{'客队':<16}{'比分':<6}{'结果'}"
    )
    for r in rows:
        hg = r["ft_home_goals"]
        ag = r["ft_away_goals"]
        score = (
            f"{hg}-{ag}"
            if hg is not None and ag is not None
            else f"{hg if hg is not None else '-'}-{ag if ag is not None else '-'}"
        )
        click.echo(
            f"{r['league_code']:<12}{r['match_date'] or '':<12}"
            f"{r['home_team']:<16}{r['away_team']:<16}{score:<6}{r['ft_result'] or ''}"
        )


@cli.command("stats")
def stats() -> None:
    """数据库各表行数统计。"""
    db = get_db()
    for table in ["matches", "match_stats", "odds_1x2", "odds_totals", "odds_asian_handicap"]:
        row = db.execute(f"SELECT COUNT(*) AS n FROM {table}")[0]
        click.echo(f"{table:<24}{row['n']}")
    click.echo("\n按联赛/赛季分布:")
    for r in db.execute(
        "SELECT league_code, season, COUNT(*) AS n FROM matches "
        "GROUP BY league_code, season ORDER BY league_code, season"
    ):
        click.echo(f"  {r['league_code']:<12}{r['season']:<12}{r['n']}")


# ============ 分析层 ============


def _build_model(name: str, db, league: str, seasons: list[str]):
    """根据名称构建并拟合预测模型。"""
    if name == "dixoncoles":
        from fussball_bund.analysis import DixonColesModel

        return DixonColesModel(db=db).fit(league, seasons)
    if name == "xgpoisson":
        from fussball_bund.analysis import XGPoissonModel

        return XGPoissonModel(db=db).fit(league, seasons)
    from fussball_bund.analysis import PoissonModel

    return PoissonModel(db=db).fit(league, seasons)


@cli.command("predict")
@click.option("--league", "-l", required=True, help="联赛 key")
@click.option("--season", "-s", required=True, help="预测比赛所在赛季")
@click.option("--home", required=True, help="主队名（英文，如 Man City）")
@click.option("--away", required=True, help="客队名")
@click.option(
    "--fit-seasons",
    help="拟合用历史赛季，逗号分隔，默认用回测赛季前一赛季",
)
@click.option(
    "--model",
    type=click.Choice(["poisson", "dixoncoles", "xgpoisson"]),
    default="poisson",
    help="预测模型（poisson 基础 / dixoncoles 低比分修正+时间衰减）",
)
def predict(league: str, season: str, home: str, away: str, fit_seasons: str | None, model: str) -> None:
    """进球模型预测比赛（胜平负 + 大小球 + 比分）。"""
    db = get_db()
    seasons = _resolve_fit_seasons(season, fit_seasons)
    mdl = _build_model(model, db, league, seasons)
    pred = mdl.predict(home, away)
    click.echo(f"\n  {home} vs {away}  (拟合赛季: {seasons})")
    click.echo(f"  期望进球: 主 {pred.lambda_home:.2f}  客 {pred.lambda_away:.2f}")
    click.echo(
        f"  胜平负:  主 {pred.p_home:.1%}  平 {pred.p_draw:.1%}  客 {pred.p_away:.1%}"
    )
    click.echo(f"  大小球:  大2.5 {pred.p_over_2_5:.1%}  小2.5 {pred.p_under_2_5:.1%}")
    click.echo("  最可能比分:")
    for (h, a), p in pred.top_scores:
        click.echo(f"    {h}-{a}   {p:.1%}")


@cli.command("value")
@click.option("--league", "-l", required=True, help="联赛 key")
@click.option("--season", "-s", required=True, help="赛季")
@click.option("--min-edge", default=0.03, type=float, help="最小优势阈值")
@click.option("--bookmaker", default="Pinnacle", help="对比庄家")
@click.option("--limit", default=20, type=int, help="返回笔数")
@click.option("--fit-seasons", help="拟合用历史赛季，逗号分隔")
@click.option(
    "--model",
    type=click.Choice(["poisson", "dixoncoles", "xgpoisson"]),
    default="poisson",
    help="预测模型",
)
@click.option("--calibrate", is_flag=True, help="启用平局校准（混合庄家隐含平局概率）")
@click.option("--bet-period", type=click.Choice(["opening", "closing"]), default="opening",
              help="下注赔率周期（opening 默认；closing 复现旧基线）")
@click.option("--protocol", type=click.Choice(["default", "legacy"]), default="default",
              help="legacy=强制 closing 复现旧基线")
def value(
    league, season, min_edge, bookmaker, limit, fit_seasons, model, calibrate, bet_period, protocol
) -> None:
    """识别价值投注（模型概率 vs 庄家赔率）。"""
    from fussball_bund.analysis import ValueBetFinder

    db = get_db()
    seasons = _resolve_fit_seasons(season, fit_seasons)
    model = _build_model(model, db, league, seasons)
    if protocol == "legacy":
        bet_period = "closing"
    bets = ValueBetFinder(db=db, model=model, calibrate=calibrate).find(
        league, season, bookmaker=bookmaker, period=bet_period, min_edge=min_edge
    )
    if not bets:
        click.echo("未发现价值投注（尝试降低 --min-edge）")
        return
    click.echo(
        f"\n{'日期':<12}{'主队':<14}{'客队':<14}{'市场':<11}{'赔率':<6}"
        f"{'模型':<7}{'隐含':<7}{'EV':<7}{'Kelly':<7}"
    )
    for b in bets[:limit]:
        click.echo(
            f"{(b.match_date or ''):<12}{b.home_team:<14}{b.away_team:<14}"
            f"{b.market:<11}{b.odds:<6.2f}{b.model_prob:<7.1%}{b.implied_prob:<7.1%}"
            f"{b.ev:<+7.1%}{b.kelly:<7.1%}"
        )
    click.echo(f"\n共 {len(bets)} 笔价值投注")


@cli.command("backtest")
@click.option("--league", "-l", required=True, help="联赛 key")
@click.option("--season", "-s", required=True, help="回测赛季")
@click.option("--min-edge", default=0.03, type=float, help="最小优势阈值")
@click.option("--bookmaker", default="Pinnacle", help="对比庄家")
@click.option("--fit-seasons", help="拟合用历史赛季，逗号分隔，默认回测赛季前一赛季")
@click.option(
    "--model",
    type=click.Choice(["poisson", "dixoncoles", "xgpoisson"]),
    default="poisson",
    help="预测模型",
)
@click.option("--calibrate", is_flag=True, help="启用平局校准")
@click.option("--bet-period", type=click.Choice(["opening", "closing"]), default="opening",
              help="下注赔率周期（opening 默认；closing 复现旧基线）")
@click.option("--protocol", type=click.Choice(["default", "legacy"]), default="default",
              help="legacy=强制 closing 复现旧基线")
def backtest(league, season, min_edge, bookmaker, fit_seasons, model, calibrate, bet_period, protocol) -> None:
    """回测价值投注策略（用历史赛季拟合，回测目标赛季实际盈亏）。"""
    from fussball_bund.analysis import ValueBetFinder

    db = get_db()
    seasons = _resolve_fit_seasons(season, fit_seasons)
    model = _build_model(model, db, league, seasons)
    if protocol == "legacy":
        bet_period = "closing"
    result = ValueBetFinder(db=db, model=model, calibrate=calibrate).backtest(
        league, season, bookmaker=bookmaker, period=bet_period, min_edge=min_edge
    )
    click.echo(f"\n  回测 {league} {season}  (拟合: {seasons}, 庄家: {bookmaker}, 下注: {bet_period})")
    click.echo(f"  投注笔数:   {result['total_bets']}")
    click.echo(f"  命中/未中:  {result['wins']}/{result['losses']}")
    click.echo(f"  命中率:     {result['win_rate']:.1%}")
    click.echo(f"  平均赔率:   {result['avg_odds']}")
    click.echo(f"  盈亏:       {result['profit']:+.2f}")
    click.echo(f"  ROI:        {result['roi']:+.1f}%")


@cli.command("walkforward")
@click.option("--league", "-l", required=True, help="联赛 key")
@click.option("--season", "-s", required=True, help="赛季")
@click.option("--model", type=click.Choice(["poisson", "dixoncoles", "xgpoisson"]), default="dixoncoles", help="预测模型")
@click.option("--bet-period", type=click.Choice(["opening", "closing"]), default="opening", help="下注赔率周期")
@click.option("--bookmaker", default="Pinnacle", help="庄家")
@click.option("--min-edge", default=0.03, type=float, help="最小优势阈值")
@click.option("--calibrate", is_flag=True, help="启用平局校准")
@click.option("-o", "--output", help="输出 JSON 路径")
def walkforward(league, season, model, bet_period, bookmaker, min_edge, calibrate, output) -> None:
    """Walk-forward 评估（严格反泄漏：训练只用 match_date < 当前比赛）。"""
    from fussball_bund.analysis.walkforward import run_walkforward, save_result

    result = run_walkforward(
        league, season, model_name=model, bet_period=bet_period,
        bookmaker=bookmaker, min_edge=min_edge, calibrate=calibrate,
    )
    click.echo(f"\n  Walk-Forward {league} {season}  (模型: {model}, 下注: {bet_period})")
    click.echo(f"  比赛: {result.n_matches}  重训: {result.refits}  投注: {result.n_bets}")
    click.echo(f"  Brier:       {result.brier:.4f}  (越低越好)")
    click.echo(f"  Log-loss:    {result.log_loss:.4f}  (越低越好)")
    roi = result.opening_roi
    click.echo(f"  下注 ROI:    {roi['roi_pct']:+.2f}%  ({roi['n_bets']}笔, 命中{roi['win_rate']:.1%})")
    if result.clv.get("mean_clv") is not None:
        click.echo(f"  CLV:         {result.clv['mean_clv']:+.2%}  (正=beat closing, {result.clv['positive_pct']:.0%}为正)")
    else:
        click.echo("  CLV:         无收盘数据")
    click.echo("  (选型优先级: CLV > Brier > opening ROI；禁止用 closing ROI 选型)")
    if output:
        save_result(result, output)
        click.echo(f"  详情: {output}")


@cli.command("calibrate-scan")
@click.option("--league", "-l", required=True, help="联赛 key")
@click.option("--season", "-s", required=True, help="赛季")
@click.option("--model", type=click.Choice(["poisson", "dixoncoles", "xgpoisson"]), default="dixoncoles", help="预测模型")
@click.option("--alphas", default="0.3,0.4,0.5", help="待对比的 α，逗号分隔")
@click.option("--bet-period", type=click.Choice(["opening", "closing"]), default="opening", help="下注赔率周期")
@click.option("--bookmaker", default="Pinnacle", help="庄家")
@click.option("--min-edge", default=0.03, type=float, help="最小优势阈值")
@click.option("-o", "--output", help="输出 JSON 路径")
def calibrate_scan(league, season, model, alphas, bet_period, bookmaker, min_edge, output) -> None:
    """平局校准 α 网格对比（walk-forward，主排序 Brier，禁止只看 ROI）。"""
    from fussball_bund.analysis.calibrate_scan import (
        format_table,
        run_calibrate_scan,
        save_scan,
    )

    alpha_list = tuple(float(x) for x in alphas.split(","))
    scan = run_calibrate_scan(
        league, season, model_name=model, alphas=alpha_list,
        bet_period=bet_period, bookmaker=bookmaker, min_edge=min_edge,
    )
    click.echo(f"\n  校准 α 网格对比 {league} {season}  (模型: {model}, 下注: {bet_period})")
    for line in format_table(scan).splitlines():
        click.echo("  " + line)
    click.echo("\n  选型优先级: Brier/CLV 优先；禁止只因 opening ROI 最高选 α")
    if output:
        save_scan(scan, output)
        click.echo(f"  JSON: {output}")


@cli.command("model-compare")
@click.option("--league", "-l", required=True, help="联赛 key")
@click.option("--season", "-s", required=True, help="赛季")
@click.option("--models", default="poisson,dixoncoles,xgpoisson", help="待对比的模型，逗号分隔")
@click.option("--bet-period", type=click.Choice(["opening", "closing"]), default="opening", help="下注赔率周期")
@click.option("--bookmaker", default="Pinnacle", help="庄家")
@click.option("--min-edge", default=0.03, type=float, help="最小优势阈值")
@click.option("--calibrate", is_flag=True, help="启用平局校准（默认 raw，与 walkforward 一致）")
@click.option("--calibrate-alpha", default=0.4, type=float, help="平局校准 α（需配合 --calibrate）")
@click.option("-o", "--output", help="输出 JSON 路径")
@click.option("--md", help="输出 Markdown 路径")
def model_compare(league, season, models, bet_period, bookmaker, min_edge, calibrate, calibrate_alpha, output, md) -> None:
    """模型对比报告（poisson/dixoncoles/xgpoisson 统一 walk-forward 表）。

    一条命令出对比表 + JSON/Markdown，固化「选型用 Brier/CLV，不用 closing ROI」。
    """
    from fussball_bund.analysis.model_compare import (
        format_table,
        run_model_compare,
        save_compare,
        save_markdown,
    )

    model_list = tuple(m.strip() for m in models.split(",") if m.strip())
    compare = run_model_compare(
        league, season, models=model_list, bet_period=bet_period,
        bookmaker=bookmaker, min_edge=min_edge,
        calibrate=calibrate, calibrate_alpha=calibrate_alpha,
    )
    click.echo(f"\n  模型对比 {league} {season}  (下注: {bet_period}, 模型: {list(model_list)})")
    for line in format_table(compare).splitlines():
        click.echo("  " + line)
    click.echo("\n  选型优先级: Brier → CLV → opening ROI；禁止用 closing ROI 选型")
    if output:
        save_compare(compare, output)
        click.echo(f"  JSON: {output}")
    if md:
        save_markdown(compare, md)
        click.echo(f"  MD:   {md}")


@cli.command("preview")
@click.option("--league", "-l", required=True, help="联赛 key")
@click.option("--days", default=7, type=int, help="未来天数范围（默认 7）")
@click.option(
    "--model",
    type=click.Choice(["poisson", "dixoncoles", "xgpoisson"]),
    default="dixoncoles",
    help="预测模型",
)
@click.option("--calibrate", is_flag=True, help="启用平局校准（仅在有赔率时生效）")
@click.option("--calibrate-alpha", default=0.4, type=float, help="平局校准 α（需配合 --calibrate）")
@click.option("--bookmaker", default="Pinnacle", help="对比庄家")
@click.option("--min-edge", default=0.03, type=float, help="关注阈值（edge >= min_edge 且 EV>0 标「关注」）")
@click.option("-o", "--output", help="输出 Markdown 文件路径，不填则打印到终端")
def preview(league, days, model, calibrate, calibrate_alpha, bookmaker, min_edge, output) -> None:
    """赛前关注清单（未来场 + 模型概率 + 庄家盘/edge → Markdown）。"""
    from fussball_bund.analysis.preview import format_markdown, generate_preview

    result = generate_preview(
        league, days=days, model_name=model, calibrate=calibrate,
        calibrate_alpha=calibrate_alpha, bookmaker=bookmaker, min_edge=min_edge,
    )
    click.echo(f"\n  赛前关注清单 {league}  (模型: {model}, 天数: {days})")
    click.echo(f"  未来场: {result.n_matches}  无盘口: {result.n_no_odds}")
    for w in result.warnings:
        click.echo(f"  ⚠ {w}")

    md = format_markdown(result)
    if output:
        from pathlib import Path
        p = Path(output)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(md, encoding="utf-8")
        click.echo(f"  MD 已保存至 {output}")
    else:
        click.echo(md)


@cli.command("map-teams")
@click.option("--league", "-l", required=True, help="联赛 key")
@click.option("--source", type=click.Choice(["understat"]), default="understat", help="数据源")
@click.option("--season", "-s", required=True, help="赛季")
@click.option("--dry-run", is_flag=True, default=False, help="仅展示不写入（默认即 dry-run）")
@click.option("--apply", "do_apply", is_flag=True, default=False, help="写入 team_name_map")
def map_teams(league, source, season, dry_run, do_apply) -> None:
    """生成/写入队名映射（堵住同日盲匹配）。"""
    from fussball_bund.storage.team_map import build_understat_mappings, upsert_mapping

    db = get_db()
    mappings = build_understat_mappings(db, league, season)
    if not mappings:
        click.echo("无候选映射（确认已采集 understat 数据）")
        return
    click.echo(f"\n  队名映射 {league} {source} {season}")
    click.echo(f"  {'source_name':<32}{'canonical':<32}")
    click.echo(f"  {'-' * 32}{'-' * 32}")
    for m in mappings:
        click.echo(f"  {m.source_name:<32}{m.canonical_name:<32}")
    # 覆盖率
    try:
        all_rows = db.execute(
            "SELECT DISTINCT home_team AS n FROM understat_shots WHERE league=? "
            "UNION SELECT DISTINCT away_team FROM understat_shots WHERE league=?",
            (league, league),
        )
        all_names = {r["n"] for r in all_rows}
    except Exception:
        all_names = set()
    mapped_names = {m.source_name for m in mappings}
    cov = len(mapped_names & all_names) / len(all_names) if all_names else 0
    unmapped = sorted(all_names - mapped_names)
    click.echo(f"\n  覆盖率: {cov:.1%} ({len(mapped_names)}/{len(all_names)})")
    if unmapped:
        click.echo(f"  未匹配: {unmapped}")
    if do_apply:
        for m in mappings:
            upsert_mapping(db, m.source, m.source_name, m.league_code, m.canonical_name)
        click.echo(f"  已写入 team_name_map: {len(mappings)} 条")
    else:
        click.echo("  (dry-run，加 --apply 写入)")


@cli.command("build-xg")
@click.option("--league", "-l", required=True, help="联赛 key")
@click.option("--season", "-s", required=True, help="赛季")
def build_xg(league, season) -> None:
    """从 understat_shots 聚合 match 级 xG（需先 map-teams --apply）。"""
    from fussball_bund.storage.match_xg import build_match_xg

    db = get_db()
    result = build_match_xg(db, league, season)
    click.echo(
        f"\n  build-xg {league} {season}: "
        f"written={result['written']}, "
        f"skipped_unmapped={result['skipped_unmapped']}, "
        f"skipped_other={result['skipped_other']}"
    )
    if result["skipped_unmapped"] > 0:
        click.echo("  提示：先 fussball map-teams --apply 补全队名映射")


@cli.command("margin")
@click.option("--league", "-l", required=True, help="联赛 key")
@click.option("--season", "-s", required=True, help="赛季")
@click.option("--bookmaker", default="Pinnacle", help="庄家")
@click.option("--period", default="closing", help="opening/closing")
def margin(league: str, season: str, bookmaker: str, period: str) -> None:
    """查看庄家水位（margin）统计。"""
    from fussball_bund.analysis import bookmaker_margin

    db = get_db()
    rows = db.execute(
        "SELECT home, draw, away FROM odds_1x2 o "
        "JOIN matches m ON m.id=o.match_id "
        "WHERE m.league_code=? AND m.season=? AND o.bookmaker=? AND o.period=? "
        "AND o.home IS NOT NULL",
        (league, season, bookmaker, period),
    )
    if not rows:
        click.echo("无数据")
        return
    margins = [bookmaker_margin((r["home"], r["draw"], r["away"])) for r in rows]
    import statistics

    click.echo(f"\n  {league} {season} {bookmaker} {period}")
    click.echo(f"  场次:     {len(margins)}")
    click.echo(f"  平均水位: {statistics.mean(margins):.2%}")
    click.echo(f"  中位水位: {statistics.median(margins):.2%}")
    click.echo(f"  最低:     {min(margins):.2%}")
    click.echo(f"  最高:     {max(margins):.2%}")


def _resolve_fit_seasons(target_season: str, fit_seasons: str | None, n_seasons: int = 3) -> list[str]:
    """解析拟合赛季：未指定则默认用目标赛季前 3 个赛季（多赛季拟合 + 时间衰减）。"""
    if fit_seasons:
        return [s.strip() for s in fit_seasons.split(",")]
    start = int(target_season.split("-")[0])
    return [f"{start - i}-{start - i + 1}" for i in range(1, n_seasons + 1)]


@cli.command("report")
@click.option("--league", "-l", required=True, help="联赛 key")
@click.option("--season", "-s", required=True, help="赛季")
@click.option(
    "--model",
    type=click.Choice(["poisson", "dixoncoles", "xgpoisson"]),
    default="dixoncoles",
    help="预测模型",
)
@click.option("--output", "-o", help="输出 Markdown 文件路径，不填则打印到终端")
@click.option("--calibrate", is_flag=True, help="启用平局校准")
@click.option("--fit-seasons", help="拟合用历史赛季，逗号分隔")
def report(league: str, season: str, model: str, output: str | None, calibrate: bool, fit_seasons: str | None) -> None:
    """生成竞猜分析简报（球队排名+预测准确率+价值投注+回测）。"""
    from fussball_bund.reporting import generate_report

    content = generate_report(league, season, model_name=model, output=output, calibrate=calibrate, fit_seasons=fit_seasons)
    if not output:
        click.echo(content)
    else:
        click.echo(f"简报已保存至 {output}")


@cli.command("poll")
def poll() -> None:
    """采集竞彩足球在售场次（500.com → SQLite）。"""
    from fussball_bund.collectors.jingcai_500 import poll_jingcai

    counts = poll_jingcai()
    click.echo(
        f"\n  竞彩采集完成: {counts['matches']} 场, "
        f"SPF {counts['spf']}, RQSPF {counts['rqspf']}"
    )
    if counts["matches"] == 0:
        click.echo("  提示：库内无竞彩数据，请检查 500.com 是否可访问")


@cli.command("serve")
@click.option("--host", default="127.0.0.1", help="监听地址")
@click.option("--port", default=8901, type=int, help="监听端口")
def serve(host: str, port: int) -> None:
    """启动竞彩 HTTP 服务（列表 + 详情 + 推荐）。"""
    from fussball_bund.serve import serve as _serve

    _serve(host, port)


if __name__ == "__main__":
    cli()
