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
