"""队名映射基础设施。

不同数据源（understat/fbref/clubelo/odds_api）队名不一致，统一映射到
football-data 队名（canonical_name）。

堵住 xG 同日盲匹配（LIMIT 1 串队）：用同日 + home/away 同时对齐 + 归一化相似度配对。
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from fussball_bund.storage.db import Database

logger = logging.getLogger(__name__)

# 归一化时去除的常见后缀（小写单词边界）
_STRIP_SUFFIXES = ("fc", "afc", "cf", "sc", "ac")


def normalize(name: str) -> str:
    """队名归一化：lower、去标点、去 fc/afc 等后缀、压缩空白。"""
    s = (name or "").lower().strip()
    s = re.sub(r"[^\w\s]", " ", s)  # 标点转空格
    for suf in _STRIP_SUFFIXES:
        s = re.sub(rf"\b{suf}\b", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


@dataclass
class Mapping:
    source: str
    source_name: str
    league_code: str
    canonical_name: str


def upsert_mapping(
    db: Database, source: str, source_name: str, league_code: str, canonical_name: str
) -> None:
    """写入/覆盖一条映射。"""
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO team_name_map(source, source_name, league_code, canonical_name) "
            "VALUES (?,?,?,?) ON CONFLICT(source, source_name, league_code) "
            "DO UPDATE SET canonical_name=excluded.canonical_name",
            (source, source_name, league_code, canonical_name),
        )


def resolve(db: Database, source: str, source_name: str, league_code: str) -> str | None:
    """查询映射，返回 canonical_name 或 None。"""
    rows = db.execute(
        "SELECT canonical_name FROM team_name_map "
        "WHERE source=? AND source_name=? AND league_code=?",
        (source, source_name, league_code),
    )
    return rows[0]["canonical_name"] if rows else None


def list_unmapped(db: Database, source: str, league_code: str) -> list[str]:
    """列出某源某联赛未映射的 understat 队名（基于 understat_shots）。"""
    try:
        rows = db.execute(
            "SELECT DISTINCT home_team AS n FROM understat_shots WHERE league=? "
            "UNION SELECT DISTINCT away_team FROM understat_shots WHERE league=?",
            (league_code, league_code),
        )
    except Exception:
        return []
    return sorted(
        r["n"] for r in rows if not resolve(db, source, r["n"], league_code)
    )


def _str_sim(a: str, b: str) -> float:
    """归一化字符串相似度（0-1）：相等 1.0，包含 0.8，否则词集 Jaccard。"""
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    if a in b or b in a:
        return 0.8
    wa, wb = set(a.split()), set(b.split())
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / len(wa | wb)


def _pair_sim(us_h: str, us_a: str, fd_h: str, fd_a: str) -> float:
    """两场比赛主客配对相似度（0-2，需两边都对上否则 0）。"""
    sh = _str_sim(us_h, fd_h)
    sa = _str_sim(us_a, fd_a)
    if sh == 0 or sa == 0:
        return 0.0
    return sh + sa


def build_understat_mappings(db: Database, league_code: str, season: str) -> list[Mapping]:
    """从 understat_shots + matches 生成候选映射。

    规则：同日 + home/away 同时对齐优先；同日多场按归一化最相似配对（禁止 LIMIT 1）。
    """
    # 兜底建表（未采集 understat 时返回空，不报错）
    with db.transaction() as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS understat_shots ("
            "league TEXT, season TEXT, event_id TEXT, match_id TEXT, date TEXT, "
            "home_team TEXT, away_team TEXT, team TEXT, h_a TEXT, "
            "minute INTEGER, player TEXT, "
            "x FLOAT, y FLOAT, xg FLOAT, result TEXT, situation TEXT, "
            "UNIQUE(league, season, event_id))"
        )
    us_rows = db.execute(
        "SELECT DISTINCT date, home_team, away_team FROM understat_shots "
        "WHERE league=? AND season=? AND date IS NOT NULL AND date != '' "
        "ORDER BY date",
        (league_code, season),
    )
    fd_rows = db.execute(
        "SELECT match_date, home_team, away_team FROM matches "
        "WHERE league_code=? AND match_date IS NOT NULL AND match_date != ''",
        (league_code,),
    )
    fd_by_date: dict[str, list] = {}
    for r in fd_rows:
        fd_by_date.setdefault(r["match_date"], []).append(r)

    mappings: dict[str, str] = {}  # source_name -> canonical
    matched = 0
    for us in us_rows:
        fd_day = fd_by_date.get(us["date"], [])
        if not fd_day:
            continue
        us_h = normalize(us["home_team"])
        us_a = normalize(us["away_team"])
        best, best_score = None, 0.0
        for fd in fd_day:
            score = _pair_sim(us_h, us_a, normalize(fd["home_team"]), normalize(fd["away_team"]))
            if score > best_score:
                best_score, best = score, fd
        if best and best_score > 0:
            mappings[us["home_team"]] = best["home_team"]
            mappings[us["away_team"]] = best["away_team"]
            matched += 1

    logger.info("understat 映射: %d 场匹配, %d 个队名", matched, len(mappings))
    return [Mapping("understat", k, league_code, v) for k, v in mappings.items()]
