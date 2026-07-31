"""数据模型（dataclass），描述采集到的核心实体。"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Match:
    league_code: str
    season: str
    match_date: str
    match_time: str | None
    home_team: str
    away_team: str
    ht_home_goals: int | None = None
    ht_away_goals: int | None = None
    ht_result: str | None = None
    ft_home_goals: int | None = None
    ft_away_goals: int | None = None
    ft_result: str | None = None
    referee: str | None = None


@dataclass
class MatchStats:
    match_id: int
    home_shots: int | None = None
    away_shots: int | None = None
    home_shots_on_target: int | None = None
    away_shots_on_target: int | None = None
    home_fouls: int | None = None
    away_fouls: int | None = None
    home_corners: int | None = None
    away_corners: int | None = None
    home_yellow: int | None = None
    away_yellow: int | None = None
    home_red: int | None = None
    away_red: int | None = None


@dataclass
class Odds1x2:
    match_id: int
    bookmaker: str
    period: str  # opening / closing
    home: float | None = None
    draw: float | None = None
    away: float | None = None


@dataclass
class OddsTotals:
    match_id: int
    bookmaker: str
    period: str
    line: float | None
    over: float | None = None
    under: float | None = None


@dataclass
class OddsAsian:
    match_id: int
    bookmaker: str
    period: str
    handicap: float | None
    home: float | None = None
    away: float | None = None


@dataclass
class CollectedSeason:
    """一次赛季采集的结果汇总。"""
    league_code: str
    season: str
    matches: int = 0
    stats: int = 0
    odds_1x2: int = 0
    odds_totals: int = 0
    odds_asian: int = 0
    errors: list[str] = field(default_factory=list)
