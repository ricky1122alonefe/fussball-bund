"""测试共享 fixtures。"""
from __future__ import annotations

import pytest

from fussball_bund.storage.db import Database


@pytest.fixture
def tmp_db(tmp_path):
    """临时数据库（已建表），测试间隔离。"""
    return Database(str(tmp_path / "test.db"))


@pytest.fixture
def insert_match(tmp_db):
    """插入一场比赛 + 开盘/收盘赔率，返回 match_id。"""

    def _insert(
        league: str,
        season: str,
        date: str,
        home: str,
        away: str,
        hg: int,
        ag: int,
        res: str,
        bookmaker: str = "Pinnacle",
        opening=(1.5, 4.0, 6.0),
        closing=(1.6, 4.2, 5.8),
    ) -> int:
        with tmp_db.transaction() as conn:
            row = conn.execute(
                "INSERT INTO matches(league_code,season,match_date,home_team,away_team,"
                "ft_home_goals,ft_away_goals,ft_result) VALUES (?,?,?,?,?,?,?,?) "
                "ON CONFLICT(league_code,season,match_date,home_team,away_team) DO UPDATE SET "
                "ft_home_goals=excluded.ft_home_goals,ft_away_goals=excluded.ft_away_goals,"
                "ft_result=excluded.ft_result RETURNING id",
                (league, season, date, home, away, hg, ag, res),
            ).fetchone()
            mid = row["id"] if row else conn.execute(
                "SELECT id FROM matches WHERE league_code=? AND season=? AND match_date=? "
                "AND home_team=? AND away_team=?",
                (league, season, date, home, away),
            ).fetchone()["id"]
            for period, (h, d, a) in (("opening", opening), ("closing", closing)):
                conn.execute(
                    "INSERT INTO odds_1x2(match_id,bookmaker,period,home,draw,away) "
                    "VALUES (?,?,?,?,?,?) ON CONFLICT(match_id,bookmaker,period) "
                    "DO UPDATE SET home=excluded.home,draw=excluded.draw,away=excluded.away",
                    (mid, bookmaker, period, h, d, a),
                )
        return mid

    return _insert


@pytest.fixture
def insert_xg_match(tmp_db):
    """插入一场 understat xG 数据（主/客各一条射门），用于 xG 模型测试。"""

    def _insert(league, season, date, home, away, home_xg, away_xg, match_id="m1"):
        with tmp_db.transaction() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS understat_shots ("
                "league TEXT, season TEXT, event_id TEXT, match_id TEXT, date TEXT, "
                "home_team TEXT, away_team TEXT, team TEXT, h_a TEXT, "
                "minute INTEGER, player TEXT, "
                "x FLOAT, y FLOAT, xg FLOAT, result TEXT, situation TEXT, "
                "UNIQUE(league, season, event_id))"
            )
            for suffix, team, h_a, xg in (
                ("h", home, "h", home_xg),
                ("a", away, "a", away_xg),
            ):
                conn.execute(
                    "INSERT OR IGNORE INTO understat_shots"
                    "(league,season,event_id,match_id,date,home_team,away_team,team,h_a,xg) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (league, season, match_id + suffix, match_id, date, home, away, team, h_a, xg),
                )
        return match_id

    return _insert


@pytest.fixture
def insert_match_xg(tmp_db):
    """插入一行 match_xg（canonical 队名，每场一行），用于 xG 模型 fit 测试。"""

    def _insert(league, season, date, home, away, home_xg, away_xg, match_id=None):
        with tmp_db.transaction() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS match_xg ("
                "match_id INTEGER, league_code TEXT NOT NULL, season TEXT NOT NULL, "
                "match_date TEXT, home_team TEXT NOT NULL, away_team TEXT NOT NULL, "
                "home_xg REAL, away_xg REAL, source TEXT DEFAULT 'understat', "
                "UNIQUE(league_code, season, match_date, home_team, away_team))"
            )
            conn.execute(
                "INSERT INTO match_xg(match_id, league_code, season, match_date, "
                "home_team, away_team, home_xg, away_xg) "
                "VALUES (?,?,?,?,?,?,?,?) "
                "ON CONFLICT(league_code, season, match_date, home_team, away_team) "
                "DO UPDATE SET home_xg=excluded.home_xg, away_xg=excluded.away_xg",
                (match_id, league, season, date, home, away, home_xg, away_xg),
            )

    return _insert
