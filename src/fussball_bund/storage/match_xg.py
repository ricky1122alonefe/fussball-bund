"""match 级 xG 聚合：从 understat_shots 聚合成每场一行，用 canonical 队名。

供后续模型/回测直接读 match_xg，避免每次 fit 扫全表射门事件。
用前需先 `fussball map-teams --apply` 建立队名映射。
"""
from __future__ import annotations

import logging

from fussball_bund.storage.db import Database
from fussball_bund.storage.team_map import resolve

logger = logging.getLogger(__name__)


def build_match_xg(db: Database, league_code: str, season: str) -> dict:
    """从 understat_shots 聚合 home_xg/away_xg，写入 match_xg。

    Returns: {"written": int, "skipped_unmapped": int, "skipped_other": int}
    """
    # 兜底建 understat_shots 表（未采集时不报错）
    with db.transaction() as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS understat_shots ("
            "league TEXT, season TEXT, event_id TEXT, match_id TEXT, date TEXT, "
            "home_team TEXT, away_team TEXT, team TEXT, h_a TEXT, "
            "minute INTEGER, player TEXT, "
            "x FLOAT, y FLOAT, xg FLOAT, result TEXT, situation TEXT, "
            "UNIQUE(league, season, event_id))"
        )

    rows = db.execute(
        "SELECT match_id, date, home_team, away_team, "
        "SUM(CASE WHEN h_a='h' THEN xg END) AS home_xg, "
        "SUM(CASE WHEN h_a='a' THEN xg END) AS away_xg "
        "FROM understat_shots WHERE league=? AND season=? "
        "GROUP BY match_id, date, home_team, away_team",
        (league_code, season),
    )

    # 队名解析（transaction 外，用 resolve + 缓存）
    _cache: dict[str, str | None] = {}

    def _resolve(name: str) -> str | None:
        if name not in _cache:
            _cache[name] = resolve(db, "understat", name, league_code)
        return _cache[name]

    parsed = []
    for r in rows:
        parsed.append((r, _resolve(r["home_team"]), _resolve(r["away_team"])))

    written = skipped_unmapped = skipped_other = 0
    with db.transaction() as conn:
        for r, home_canon, away_canon in parsed:
            # 主客都 resolve 成功才入库
            if not home_canon or not away_canon:
                skipped_unmapped += 1
                continue
            # 尝试补 match_id（对齐 matches）
            mid = None
            if r["date"]:
                m = conn.execute(
                    "SELECT id FROM matches WHERE league_code=? AND match_date=? "
                    "AND home_team=? AND away_team=? LIMIT 1",
                    (league_code, r["date"], home_canon, away_canon),
                ).fetchone()
                if m:
                    mid = m["id"]
            try:
                conn.execute(
                    "INSERT INTO match_xg(match_id, league_code, season, match_date, "
                    "home_team, away_team, home_xg, away_xg, source) "
                    "VALUES (?,?,?,?,?,?,?,?,?) "
                    "ON CONFLICT(league_code, season, match_date, home_team, away_team) "
                    "DO UPDATE SET match_id=excluded.match_id, home_xg=excluded.home_xg, "
                    "away_xg=excluded.away_xg",
                    (mid, league_code, season, r["date"], home_canon, away_canon,
                     r["home_xg"], r["away_xg"], "understat"),
                )
                written += 1
            except Exception as e:
                logger.warning("build-xg 写入失败 %s vs %s: %s", home_canon, away_canon, e)
                skipped_other += 1

    logger.info(
        "build-xg %s %s: written=%d, skipped_unmapped=%d, skipped_other=%d",
        league_code, season, written, skipped_unmapped, skipped_other,
    )
    return {"written": written, "skipped_unmapped": skipped_unmapped, "skipped_other": skipped_other}
