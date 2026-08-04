"""平局校准 α 网格对比（walk-forward 上）。

对同一 league/season/model，对比 raw（不校准）与多个 α 的 walk-forward 表现。
选型主排序字段：Brier（越低越好）；**禁止只因 opening ROI 最高选 α**（ROI 受方差影响，易过拟合）。

复用 run_walkforward，不重写回测引擎。每组独立跑一次 walk-forward（calibrate 参数不同）。
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path

from fussball_bund.analysis.walkforward import run_walkforward
from fussball_bund.storage.db import Database, get_db

logger = logging.getLogger(__name__)

DEFAULT_ALPHAS = (0.3, 0.4, 0.5)


@dataclass
class ScanRow:
    label: str
    alpha: float | None
    brier: float
    log_loss: float
    opening_roi_pct: float
    n_bets: int
    win_rate: float
    clv_mean: float | None
    clv_positive_pct: float | None


def run_calibrate_scan(
    league_code: str,
    season: str,
    model_name: str = "dixoncoles",
    alphas: tuple[float, ...] = DEFAULT_ALPHAS,
    bet_period: str = "opening",
    bookmaker: str = "Pinnacle",
    min_edge: float = 0.03,
    db: Database | None = None,
) -> dict:
    """跑 raw + 各 α 的 walk-forward，返回按 Brier 升序的对比结果。"""
    db = db or get_db()
    rows: list[ScanRow] = []

    def _run(label: str, alpha: float | None, calibrate: bool, calibrate_alpha: float) -> ScanRow:
        r = run_walkforward(
            league_code, season, model_name=model_name, bet_period=bet_period,
            bookmaker=bookmaker, min_edge=min_edge,
            calibrate=calibrate, calibrate_alpha=calibrate_alpha, db=db,
        )
        return ScanRow(
            label=label, alpha=alpha, brier=r.brier, log_loss=r.log_loss,
            opening_roi_pct=r.opening_roi["roi_pct"], n_bets=r.n_bets,
            win_rate=r.opening_roi["win_rate"],
            clv_mean=r.clv.get("mean_clv"), clv_positive_pct=r.clv.get("positive_pct"),
        )

    logger.info("calibrate-scan: raw（不校准）")
    rows.append(_run("raw", None, False, 0.4))
    for a in alphas:
        logger.info("calibrate-scan: α=%.2f", a)
        rows.append(_run(f"α={a}", a, True, a))

    rows.sort(key=lambda x: x.brier)  # Brier 升序（越低越好）
    return {
        "league": league_code, "season": season, "model": model_name,
        "bet_period": bet_period, "bookmaker": bookmaker, "min_edge": min_edge,
        "rows": [asdict(r) for r in rows],
        "sort_key": "brier",
        "note": "选型先看 Brier/CLV；禁止只因 opening ROI 最高选 α",
    }


def format_table(scan: dict) -> str:
    header = (
        f"{'配置':<10}{'Brier':>8}{'log-loss':>10}{'openROI':>10}"
        f"{'n_bets':>8}{'命中率':>8}{'CLV':>9}"
    )
    lines = [header, "-" * len(header)]
    for r in scan["rows"]:
        clv = f"{r['clv_mean']:+.2%}" if r["clv_mean"] is not None else "  -"
        lines.append(
            f"{r['label']:<10}{r['brier']:>8.4f}{r['log_loss']:>10.4f}"
            f"{r['opening_roi_pct']:>+9.1f}%{r['n_bets']:>8}"
            f"{r['win_rate']:>7.1%}{clv:>9}"
        )
    return "\n".join(lines)


def save_scan(scan: dict, path: str) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(scan, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("calibrate-scan 结果已保存至 %s", path)
