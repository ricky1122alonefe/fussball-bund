"""基本面采集器 —— 封装 SoccerData 库。

数据源可信度评估（via SoccerData）：
    - FBref:   StatsBomb 级数据，含 xG/传球网络/球员统计，最权威的免费足球统计源
               稳定性：中（Cloudflare 反爬，但 SoccerData 内置 header + 缓存兜底）
    - Understat: 权威 xG/xA 数据源，覆盖五大联赛
               稳定性：中（网页抓取 + 缓存）
    - ClubElo:  全球球队 Elo 动态评级，基于真实比赛结果，学术认可
               稳定性：中-高（轻量 HTML，反爬弱）

注意：SoccerData 首次抓取会下载并缓存到 ~/.soccerdata_cache，较慢；
      后续命中缓存则快。数据以 Pandas DataFrame 返回。
"""
from __future__ import annotations

import logging

from fussball_bund.collectors.base import BaseCollector

logger = logging.getLogger(__name__)


class FundamentalsCollector(BaseCollector):
    name = "fundamentals"

    def collect_fbref_schedule(self, league_key: str, season: str) -> int:
        """抓取 FBref 赛程表（已完赛 + 未踢完场；未完赛 ft_* 为空）。

        **零付费路径**：不需要 Odds API。未完赛写入库后，``fussball preview`` 可直接出模型概率。

        FBref schedule 的比分在 ``score`` 列（格式 ``"H–A"``，en-dash 分隔），
        无独立 home_score/away_score 列。此方法同时兼容旧式列名（若存在）。

        队名：经 resolve_to_canonical 对齐到 football-data 短名，便于历史模型拟合。
        """
        from fussball_bund.config import load_leagues
        from fussball_bund.storage.team_map import resolve_to_canonical

        cfg = load_leagues()[league_key]
        if not cfg.fbref:
            logger.warning("%s 无 FBref 支持（免费赛程不可用，勿用付费 Odds 强求）", league_key)
            return 0

        import soccerdata as sd

        logger.info("FBref 赛程: %s %s", cfg.fbref, season)
        fbref = sd.FBref(leagues=[cfg.fbref], seasons=[season])
        df = fbref.read_schedule()
        if df is None or df.empty:
            logger.warning("FBref 无数据 %s %s", league_key, season)
            return 0
        n = 0
        n_unplayed = 0
        pending_maps: list[tuple[str, str]] = []  # (raw, canon) for fbref
        with self.db.transaction() as conn:
            for _, row in df.iterrows():
                if row.get("home_team") is None or row.get("away_team") is None:
                    continue
                date = str(row.get("date"))[:10] if row.get("date") is not None else None
                # 比分：优先 home_score/away_score 列；回退解析 score 列（"H–A" en-dash）
                home_score = self._safe_int(row.get("home_score"))
                away_score = self._safe_int(row.get("away_score"))
                if home_score is None or away_score is None:
                    hs, as_ = self._parse_score(row.get("score"))
                    home_score = home_score if home_score is not None else hs
                    away_score = away_score if away_score is not None else as_
                # 队名对齐 canonical（历史 FD 训练数据通用；免费路径）
                raw_h = str(row["home_team"]).strip()
                raw_a = str(row["away_team"]).strip()
                home = resolve_to_canonical(
                    self.db, league_key, raw_h, source="fbref", persist=False
                )
                away = resolve_to_canonical(
                    self.db, league_key, raw_a, source="fbref", persist=False
                )
                if home != raw_h:
                    pending_maps.append((raw_h, home))
                if away != raw_a:
                    pending_maps.append((raw_a, away))
                ft_result = self._result(home_score, away_score)
                if ft_result is None:
                    n_unplayed += 1
                conn.execute(
                    "INSERT INTO matches(league_code,season,match_date,home_team,away_team,"
                    "ft_home_goals,ft_away_goals,ft_result) "
                    "VALUES (?,?,?,?,?,?,?,?) "
                    "ON CONFLICT(league_code,season,match_date,home_team,away_team) DO UPDATE SET "
                    "ft_home_goals=COALESCE(excluded.ft_home_goals,matches.ft_home_goals),"
                    "ft_away_goals=COALESCE(excluded.ft_away_goals,matches.ft_away_goals),"
                    "ft_result=COALESCE(excluded.ft_result,matches.ft_result)",
                    (
                        league_key, season, date,
                        home,
                        away,
                        home_score,
                        away_score,
                        ft_result,
                    ),
                )
                n += 1
        from fussball_bund.storage.team_map import upsert_mapping

        for raw, canon in dict(pending_maps).items():  # 去重
            upsert_mapping(self.db, "fbref", raw, league_key, canon)
        self.db.log_collection(
            self.name, "success",
            f"fbref schedule {n} rows ({n_unplayed} unplayed)",
            league_key, season,
        )
        logger.info("FBref 写入 %d 行（其中未完赛 %d 行 → 可供 preview）", n, n_unplayed)
        return n

    def collect_clubelo(self, team: str) -> int:
        """抓取某球队 Club Elo 历史评级。存入独立表（按需创建）。"""
        import soccerdata as sd

        logger.info("ClubElo: %s", team)
        clubelo = sd.ClubElo()
        df = clubelo.read_team_history(team)
        if df is None or df.empty:
            return 0
        with self.db.transaction() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS club_elo "
                "(team TEXT, date TEXT, elo REAL, UNIQUE(team, date))"
            )
            n = 0
            for _, row in df.iterrows():
                conn.execute(
                    "INSERT INTO club_elo(team,date,elo) VALUES (?,?,?) "
                    "ON CONFLICT(team,date) DO UPDATE SET elo=excluded.elo",
                    (team, str(row.name)[:10] if row.name is not None else None,
                     float(row["elo"]) if row.get("elo") is not None else None),
                )
                n += 1
        self.db.log_collection(self.name, "success", f"clubelo {team} {len(df)} rows")
        return len(df)

    def collect_understat(self, league_key: str, season: str) -> int:
        """抓取 Understat 联赛 xG 数据。"""
        import soccerdata as sd

        from fussball_bund.config import load_leagues

        cfg = load_leagues()[league_key]
        if not cfg.understat:
            logger.warning("%s 无 Understat 支持", league_key)
            return 0
        logger.info("Understat: %s %s", cfg.understat, season)
        understat = sd.Understat(leagues=[cfg.understat], seasons=[season])
        df = understat.read_shot_events()
        if df is None or df.empty:
            return 0
        import pandas as pd
        df = df.reset_index().astype(object).fillna("")  # MultiIndex 转列，可空类型转 object，NA->""
        with self.db.transaction() as conn:
            # 旧表缺新列则重建（兼容升级）
            if conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='understat_shots'").fetchone():
                if "date" not in {r[1] for r in conn.execute("PRAGMA table_info(understat_shots)")}:
                    conn.execute("DROP TABLE understat_shots")
            conn.execute(
                "CREATE TABLE IF NOT EXISTS understat_shots ("
                "league TEXT, season TEXT, event_id TEXT, match_id TEXT, date TEXT, "
                "home_team TEXT, away_team TEXT, team TEXT, h_a TEXT, "
                "minute INTEGER, player TEXT, "
                "x FLOAT, y FLOAT, xg FLOAT, result TEXT, situation TEXT, "
                "UNIQUE(league, season, event_id))"
            )
            n = 0
            for _, row in df.iterrows():
                game = str(row.get("game") or "")
                # game 格式 "2024-08-16 HomeTeam-AwayTeam"
                date = game[:10] if len(game) >= 10 and game[4] == "-" else ""
                teams_str = game[11:] if len(game) > 11 else game
                team = str(row.get("team") or "")
                player = str(row.get("player") or "")
                if teams_str.startswith(team + "-"):
                    h_a, home_team, away_team = "h", team, teams_str[len(team) + 1:]
                elif teams_str and teams_str.endswith("-" + team):
                    h_a, home_team, away_team = "a", teams_str[: -(len(team) + 1)], team
                else:
                    h_a, home_team, away_team = "", "", ""
                conn.execute(
                    "INSERT OR IGNORE INTO understat_shots"
                    "(league,season,event_id,match_id,date,home_team,away_team,team,h_a,minute,player,x,y,xg,result,situation) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        league_key, season,
                        str(row.get("shot_id") or ""),
                        str(row.get("game_id") or ""),
                        date,
                        home_team,
                        away_team,
                        team,
                        h_a,
                        self._safe_int(row.get("minute")),
                        player,
                        self._safe_float(row.get("location_x")),
                        self._safe_float(row.get("location_y")),
                        self._safe_float(row.get("xg")),
                        str(row.get("result") or ""),
                        str(row.get("situation") or ""),
                    ),
                )
                n += 1
        self.db.log_collection(self.name, "success", f"understat {n} shots", league_key, season)
        return n

    @staticmethod
    def _safe_int(v) -> int | None:
        try:
            return int(float(v)) if v is not None else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _safe_float(v) -> float | None:
        try:
            f = float(v)
            return f if f == f else None  # nan -> None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _result(h, a) -> str | None:
        hi, ai = FundamentalsCollector._safe_int(h), FundamentalsCollector._safe_int(a)
        if hi is None or ai is None:
            return None
        return "H" if hi > ai else ("D" if hi == ai else "A")

    @staticmethod
    def _parse_score(score) -> tuple[int | None, int | None]:
        """解析 FBref schedule 的 score 列（格式 ``"H–A"``，en-dash 分隔）。

        兼容 en-dash (–)、em-dash (—)、普通 hyphen (-)。
        """
        if score is None:
            return None, None
        s = str(score).strip()
        if not s:
            return None, None
        for sep in ("\u2013", "\u2014", "-"):  # en-dash, em-dash, hyphen
            if sep in s:
                parts = s.split(sep)
                if len(parts) == 2:
                    try:
                        return int(parts[0].strip()), int(parts[1].strip())
                    except ValueError:
                        return None, None
        return None, None
