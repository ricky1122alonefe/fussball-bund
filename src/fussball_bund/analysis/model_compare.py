"""模型对比报告（poisson / dixoncoles / xgpoisson 统一 walk-forward 表）。

对同一 league/season，对多个模型分别跑 walk-forward，汇总到一张对比表，
固化「选型用 Brier/CLV，不用 closing ROI」流程。

选型主排序字段：Brier（越低越好）；次序 CLV → opening ROI。
**禁止用 closing ROI 选型**（closing 已是高效市场，且含未来信息）。

复用 run_walkforward，不重写回测引擎，不新造模型。
每组独立跑一次 walk-forward（model_name 不同）。
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path

from fussball_bund.analysis.walkforward import run_walkforward
from fussball_bund.storage.db import Database, get_db

logger = logging.getLogger(__name__)

SUPPORTED_MODELS = ("poisson", "dixoncoles", "xgpoisson")


@dataclass
class ModelCompareRow:
    model: str
    brier: float
    log_loss: float
    opening_roi_pct: float
    n_bets: int
    clv_mean: float | None
    clv_positive_pct: float | None
    n_matches: int
    refits: int


def run_model_compare(
    league_code: str,
    season: str,
    models: tuple[str, ...] = SUPPORTED_MODELS,
    bet_period: str = "opening",
    bookmaker: str = "Pinnacle",
    min_edge: float = 0.03,
    calibrate: bool = False,
    calibrate_alpha: float = 0.4,
    db: Database | None = None,
) -> dict:
    """对多个模型跑 walk-forward，返回按 Brier 升序的对比结果。

    Args:
        models: 待对比模型元组（poisson/dixoncoles/xgpoisson）
        calibrate: 启用平局校准（默认 raw，与 walkforward 默认一致）
        calibrate_alpha: 校准 α（仅 calibrate=True 时生效）
    """
    db = db or get_db()
    for m in models:
        if m not in SUPPORTED_MODELS:
            raise ValueError(f"未知模型: {m}，可选: {SUPPORTED_MODELS}")

    rows: list[ModelCompareRow] = []
    for m in models:
        logger.info("model-compare: %s", m)
        r = run_walkforward(
            league_code, season, model_name=m, bet_period=bet_period,
            bookmaker=bookmaker, min_edge=min_edge,
            calibrate=calibrate, calibrate_alpha=calibrate_alpha, db=db,
        )
        rows.append(ModelCompareRow(
            model=m, brier=r.brier, log_loss=r.log_loss,
            opening_roi_pct=r.opening_roi["roi_pct"], n_bets=r.n_bets,
            clv_mean=r.clv.get("mean_clv"),
            clv_positive_pct=r.clv.get("positive_pct"),
            n_matches=r.n_matches, refits=r.refits,
        ))

    rows.sort(key=lambda x: x.brier)  # Brier 升序（越低越好）
    return {
        "league": league_code, "season": season, "models": list(models),
        "bet_period": bet_period, "bookmaker": bookmaker, "min_edge": min_edge,
        "calibrate": calibrate,
        "calibrate_alpha": calibrate_alpha if calibrate else None,
        "rows": [asdict(r) for r in rows],
        "sort_key": "brier",
        "note": "选型优先级: Brier → CLV → opening ROI；禁止用 closing ROI 选型",
    }


def format_table(compare: dict) -> str:
    """终端表格。"""
    header = (
        f"{'模型':<14}{'Brier':>8}{'log-loss':>10}{'openROI':>10}"
        f"{'n_bets':>8}{'CLV':>9}{'CLV+%':>8}{'n_match':>9}{'refits':>8}"
    )
    lines = [header, "-" * len(header)]
    for r in compare["rows"]:
        clv = f"{r['clv_mean']:+.2%}" if r["clv_mean"] is not None else "  -"
        clvp = f"{r['clv_positive_pct']:.0%}" if r["clv_positive_pct"] is not None else "  -"
        lines.append(
            f"{r['model']:<14}{r['brier']:>8.4f}{r['log_loss']:>10.4f}"
            f"{r['opening_roi_pct']:>+9.1f}%{r['n_bets']:>8}{clv:>9}{clvp:>8}"
            f"{r['n_matches']:>9}{r['refits']:>8}"
        )
    return "\n".join(lines)


def format_markdown(compare: dict) -> str:
    """Markdown 报告。"""
    calib_line = f"- 校准: `{compare['calibrate']}`"
    if compare["calibrate"]:
        calib_line += f"  α=`{compare['calibrate_alpha']}`"
    lines = [
        f"# 模型对比报告 {compare['league']} {compare['season']}",
        "",
        f"- 下注周期: `{compare['bet_period']}`  庄家: `{compare['bookmaker']}`  "
        f"min_edge: `{compare['min_edge']}`",
        calib_line,
        f"- 排序: `{compare['sort_key']}` 升序（越低越好）",
        "",
        "| 模型 | Brier | log-loss | openROI% | n_bets | CLV | CLV+% | n_match | refits |",
        "|------|------:|---------:|---------:|-------:|----:|------:|--------:|-------:|",
    ]
    for r in compare["rows"]:
        clv = f"{r['clv_mean']:+.2%}" if r["clv_mean"] is not None else "-"
        clvp = f"{r['clv_positive_pct']:.0%}" if r["clv_positive_pct"] is not None else "-"
        lines.append(
            f"| {r['model']} | {r['brier']:.4f} | {r['log_loss']:.4f} | "
            f"{r['opening_roi_pct']:+.1f}% | {r['n_bets']} | {clv} | {clvp} | "
            f"{r['n_matches']} | {r['refits']} |"
        )
    lines.append("")
    lines.append(f"> {compare['note']}")
    return "\n".join(lines)


def save_compare(compare: dict, path: str) -> None:
    """保存 JSON。"""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(compare, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("model-compare JSON 已保存至 %s", path)


def save_markdown(compare: dict, path: str) -> None:
    """保存 Markdown。"""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(format_markdown(compare), encoding="utf-8")
    logger.info("model-compare Markdown 已保存至 %s", path)
