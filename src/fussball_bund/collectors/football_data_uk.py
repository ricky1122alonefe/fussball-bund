"""Football-Data.co.uk 采集器 —— 核心数据源。

可信度/稳定性评估（实证验证）：
    - 直连 CSV 静态文件下载，HTTP 200，content-type: text/csv
    - 学术界金标准，被大量博彩/体育研究论文引用
    - 覆盖 2000-01 赛季至今，五大联赛 + 欧冠 + 杯赛
    - 含开盘/收盘赔率、多博彩公司（bet365/Pinnacle/William Hill 等）
    - 含大小球、亚洲盘聚合（BetBrain max/avg）
    - 有速率限制（1000），但 CSV 下载频次低，稳定可靠
    - 无反爬/无 JS 渲染，最稳定的赔率数据源

URL 格式: https://www.football-data.co.uk/mmz4281/{season_code}/{league}.csv
    season_code: 2024-2025 -> 2425
    league:      E0=英超 SP1=西甲 I1=意甲 D1=德甲 F1=法甲 CL=欧冠
"""
from __future__ import annotations

import io
import logging
from typing import Any

import numpy as np
import pandas as pd

from fussball_bund.collectors.base import BaseCollector

logger = logging.getLogger(__name__)

# Football-Data.co.uk 列前缀 -> 博彩公司名（1X2 赔率）
BOOKMAKERS: dict[str, str] = {
    "B365": "bet365",
    "BS": "Blue Square",
    "BW": "Bet&Win",
    "GB": "Gamebookers",
    "IW": "Interwetten",
    "LB": "Ladbrokes",
    "PS": "Pinnacle",
    "SO": "Sporting Odds",
    "SB": "Sportingbet",
    "SJ": "Stan James",
    "SY": "Stanleybet",
    "VC": "VC Bet",
    "WH": "William Hill",
}


class FootballDataUKCollector(BaseCollector):
    name = "football_data_uk"
    BASE_URL = "https://www.football-data.co.uk/mmz4281"

    def collect_season(self, league_key: str, season: str) -> dict[str, int]:
        """抓取并存储某联赛某赛季全部数据。

        Args:
            league_key: 联赛配置 key（EPL/LALIGA/...）
            season: 赛季，如 2024-2025
        Returns:
            各表写入计数。
        """
        from fussball_bund.config import load_leagues

        leagues = load_leagues()
        if league_key not in leagues:
            raise ValueError(f"未知联赛 key: {league_key}")
        code = leagues[league_key].football_data_uk
        if not code:
            logger.warning(
                "%s 在 Football-Data.co.uk 不可用（欧冠 CSV 已停止维护），"
                "请用 collect-odds / collect-fundamentals 补充",
                league_key,
            )
            self.db.log_collection(self.name, "skipped", "football_data_uk code is null", league_key, season)
            return {"matches": 0, "skipped": 1}
        season_code = self._season_code(season)
        url = f"{self.BASE_URL}/{season_code}/{code}.csv"

        logger.info("抓取 %s %s -> %s", league_key, season, url)
        try:
            resp = self._get(url)
        except Exception as e:
            logger.error("下载失败 %s: %s", url, e)
            self.db.log_collection(self.name, "failed", str(e), league_key, season)
            return {"matches": 0, "error": 1}

        df = pd.read_csv(io.BytesIO(resp.content))
        # 清洗：去掉无对阵的空行
        df = df.dropna(subset=["HomeTeam", "AwayTeam"])
        logger.info("解析到 %d 场比赛", len(df))

        counts = self._store(df, league_key, season)
        self.db.log_collection(
            self.name, "success",
            f"{counts['matches']} matches, {counts['odds_1x2']} odds",
            league_key, season,
        )
        logger.info("完成 %s %s: %s", league_key, season, counts)
        return counts

    def collect_many(
        self, league_keys: list[str], seasons: list[str], delay: float = 1.0
    ) -> list[dict[str, int]]:
        """批量抓取多联赛多赛季。每个请求间留延迟避免触发限流。"""
        results = []
        for lk in league_keys:
            for s in seasons:
                results.append(self.collect_season(lk, s))
                self._sleep(delay)
        return results

    # ---------- 内部 ----------
    @staticmethod
    def _season_code(season: str) -> str:
        """2024-2025 -> 2425"""
        start, end = season.split("-")
        return start[-2:] + end[-2:]

    def _store(self, df: pd.DataFrame, league_key: str, season: str) -> dict[str, int]:
        counts = {"matches": 0, "stats": 0, "odds_1x2": 0, "odds_totals": 0, "odds_asian": 0}
        with self.db.transaction() as conn:
            for _, row in df.iterrows():
                match_id = self._upsert_match(conn, row, league_key, season)
                if match_id is None:
                    continue
                counts["matches"] += 1
                if self._upsert_stats(conn, row, match_id):
                    counts["stats"] += 1
                counts["odds_1x2"] += self._upsert_1x2_all(conn, row, match_id)
                counts["odds_totals"] += self._upsert_totals_all(conn, row, match_id)
                counts["odds_asian"] += self._upsert_asian_all(conn, row, match_id)
        return counts

    def _upsert_match(self, conn, row, league_key, season) -> int | None:
        data = {
            "league_code": league_key,
            "season": season,
            "match_date": self._parse_date(row.get("Date")),
            "match_time": self._clean(row.get("Time")),
            "home_team": str(row["HomeTeam"]).strip(),
            "away_team": str(row["AwayTeam"]).strip(),
            "ht_home_goals": self._int(row.get("HTHG")),
            "ht_away_goals": self._int(row.get("HTAG")),
            "ht_result": self._clean(row.get("HTR")),
            "ft_home_goals": self._int(row.get("FTHG")),
            "ft_away_goals": self._int(row.get("FTAG")),
            "ft_result": self._clean(row.get("FTR")),
            "referee": self._clean(row.get("Referee")),
        }
        row_res = conn.execute(
            "INSERT INTO matches(league_code,season,match_date,match_time,home_team,"
            "away_team,ht_home_goals,ht_away_goals,ht_result,ft_home_goals,"
            "ft_away_goals,ft_result,referee) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(league_code,season,match_date,home_team,away_team) "
            "DO UPDATE SET match_time=excluded.match_time,ht_home_goals=excluded.ht_home_goals,"
            "ht_away_goals=excluded.ht_away_goals,ht_result=excluded.ht_result,"
            "ft_home_goals=excluded.ft_home_goals,ft_away_goals=excluded.ft_away_goals,"
            "ft_result=excluded.ft_result,referee=excluded.referee "
            "RETURNING id",
            tuple(data.values()),
        ).fetchone()
        return row_res["id"] if row_res else None

    def _upsert_stats(self, conn, row, match_id) -> bool:
        data = {
            "match_id": match_id,
            "home_shots": self._int(row.get("HS")),
            "away_shots": self._int(row.get("AS")),
            "home_shots_on_target": self._int(row.get("HST")),
            "away_shots_on_target": self._int(row.get("AST")),
            "home_fouls": self._int(row.get("HF")),
            "away_fouls": self._int(row.get("AF")),
            "home_corners": self._int(row.get("HC")),
            "away_corners": self._int(row.get("AC")),
            "home_yellow": self._int(row.get("HY")),
            "away_yellow": self._int(row.get("AY")),
            "home_red": self._int(row.get("HR")),
            "away_red": self._int(row.get("AR")),
        }
        if all(v is None for k, v in data.items() if k != "match_id"):
            return False
        cols = ",".join(data.keys())
        ph = ",".join("?" * len(data))
        conn.execute(
            f"INSERT INTO match_stats({cols}) VALUES ({ph}) "
            "ON CONFLICT(match_id) DO UPDATE SET "
            + ",".join(f"{c}=excluded.{c}" for c in data if c != "match_id"),
            tuple(data.values()),
        )
        return True

    def _upsert_1x2_all(self, conn, row, match_id) -> int:
        n = 0
        # per-bookmaker 开盘/收盘
        for prefix, name in BOOKMAKERS.items():
            # opening
            h, d, a = row.get(f"{prefix}H"), row.get(f"{prefix}D"), row.get(f"{prefix}A")
            if self._has_val(h, d, a):
                self._upsert_1x2(conn, match_id, name, "opening", self._flt(h), self._flt(d), self._flt(a))
                n += 1
            # closing
            ch, cd, ca = row.get(f"{prefix}CH"), row.get(f"{prefix}CD"), row.get(f"{prefix}CA")
            if self._has_val(ch, cd, ca):
                self._upsert_1x2(conn, match_id, name, "closing", self._flt(ch), self._flt(cd), self._flt(ca))
                n += 1
        # BetBrain 聚合 max/avg（opening）
        n += self._upsert_bb_1x2(conn, row, match_id, "opening")
        n += self._upsert_bb_1x2(conn, row, match_id, "closing")
        return n

    def _upsert_bb_1x2(self, conn, row, match_id, period) -> int:
        suf = "" if period == "opening" else "C"
        n = 0
        for agg, label in (("Mx", "BbMax"), ("Av", "BbAvg")):
            h = row.get(f"Bb{agg}{suf}H")
            d = row.get(f"Bb{agg}{suf}D")
            a = row.get(f"Bb{agg}{suf}A")
            if self._has_val(h, d, a):
                self._upsert_1x2(conn, match_id, label, period, self._flt(h), self._flt(d), self._flt(a))
                n += 1
        return n

    def _upsert_1x2(self, conn, match_id, bookmaker, period, h, d, a) -> None:
        conn.execute(
            "INSERT INTO odds_1x2(match_id,bookmaker,period,home,draw,away) VALUES (?,?,?,?,?,?) "
            "ON CONFLICT(match_id,bookmaker,period) DO UPDATE SET "
            "home=excluded.home,draw=excluded.draw,away=excluded.away",
            (match_id, bookmaker, period, h, d, a),
        )

    # 新版 CSV（2017-18 起）per-bookmaker 大小球/亚盘前缀
    _EXTRA_PREFIXES = {
        "B365": "bet365",
        "P": "Pinnacle",
        "BFE": "Betfair Exchange",
        "Max": "BbMax",
        "Avg": "BbAvg",
    }

    def _upsert_totals_all(self, conn, row, match_id) -> int:
        n = 0
        # 新格式：{prefix}>2.5 / {prefix}<2.5，收盘 {prefix}C>2.5
        for prefix, name in self._EXTRA_PREFIXES.items():
            for period, suf in (("opening", ""), ("closing", "C")):
                over = row.get(f"{prefix}{suf}>2.5")
                under = row.get(f"{prefix}{suf}<2.5")
                if self._has_val(over, under):
                    conn.execute(
                        "INSERT INTO odds_totals(match_id,bookmaker,period,line,over,under) "
                        "VALUES (?,?,?,?,?,?) ON CONFLICT(match_id,bookmaker,period,line) "
                        "DO UPDATE SET over=excluded.over,under=excluded.under",
                        (match_id, name, period, 2.5, self._flt(over), self._flt(under)),
                    )
                    n += 1
        # 老格式：BbMx>2.5 / BbAv>2.5，收盘 BbMxC>2.5
        for agg, label in (("Mx", "BbMax"), ("Av", "BbAvg")):
            for period, suf in (("opening", ""), ("closing", "C")):
                over = row.get(f"Bb{agg}{suf}>2.5")
                under = row.get(f"Bb{agg}{suf}<2.5")
                if self._has_val(over, under):
                    conn.execute(
                        "INSERT INTO odds_totals(match_id,bookmaker,period,line,over,under) "
                        "VALUES (?,?,?,?,?,?) ON CONFLICT(match_id,bookmaker,period,line) "
                        "DO UPDATE SET over=excluded.over,under=excluded.under",
                        (match_id, label, period, 2.5, self._flt(over), self._flt(under)),
                    )
                    n += 1
        return n

    def _upsert_asian_all(self, conn, row, match_id) -> int:
        n = 0
        # 新格式盘口：AHh(开盘) / AHCh(收盘)
        hcap_open = self._flt(row.get("AHh"))
        hcap_close = self._flt(row.get("AHCh"))
        for prefix, name in self._EXTRA_PREFIXES.items():
            home = row.get(f"{prefix}AHH")
            away = row.get(f"{prefix}AHA")
            if self._has_val(home, away):
                self._insert_asian(conn, match_id, name, "opening", hcap_open, home, away)
                n += 1
            home_c = row.get(f"{prefix}CAHH")
            away_c = row.get(f"{prefix}CAHA")
            if self._has_val(home_c, away_c):
                self._insert_asian(conn, match_id, name, "closing", hcap_close, home_c, away_c)
                n += 1
        # 老格式：BbAHh(开盘) / BbCAHh(收盘)，BbMxAHH 等
        hcap_old_open = self._flt(row.get("BbAHh"))
        hcap_old_close = self._flt(row.get("BbCAHh"))
        for agg, label in (("Mx", "BbMax"), ("Av", "BbAvg")):
            home = row.get(f"Bb{agg}AHH")
            away = row.get(f"Bb{agg}AHA")
            if self._has_val(home, away):
                self._insert_asian(conn, match_id, label, "opening", hcap_old_open, home, away)
                n += 1
            home_c = row.get(f"Bb{agg}CAHH")
            away_c = row.get(f"Bb{agg}CAHA")
            if self._has_val(home_c, away_c):
                self._insert_asian(conn, match_id, label, "closing", hcap_old_close, home_c, away)
                n += 1
        return n

    def _insert_asian(self, conn, match_id, bookmaker, period, handicap, home, away) -> None:
        conn.execute(
            "INSERT INTO odds_asian_handicap(match_id,bookmaker,period,handicap,home,away) "
            "VALUES (?,?,?,?,?,?) ON CONFLICT(match_id,bookmaker,period,handicap) "
            "DO UPDATE SET home=excluded.home,away=excluded.away",
            (match_id, bookmaker, period, handicap, self._flt(home), self._flt(away)),
        )

    # ---------- 类型转换工具 ----------
    @staticmethod
    def _clean(v: Any) -> str | None:
        if v is None or (isinstance(v, float) and np.isnan(v)):
            return None
        s = str(v).strip()
        return s if s and s.lower() != "nan" else None

    @staticmethod
    def _int(v: Any) -> int | None:
        if v is None or (isinstance(v, float) and np.isnan(v)):
            return None
        try:
            return int(float(v))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _flt(v: Any) -> float | None:
        if v is None or (isinstance(v, float) and np.isnan(v)):
            return None
        try:
            f = float(v)
            return f if f == f else None  # nan check
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _has_val(*vals) -> bool:
        return any(
            v is not None and not (isinstance(v, float) and np.isnan(v)) for v in vals
        )

    @staticmethod
    def _parse_date(v: Any) -> str | None:
        if v is None or (isinstance(v, float) and np.isnan(v)):
            return None
        try:
            return pd.to_datetime(v, dayfirst=True, errors="coerce").strftime("%Y-%m-%d")
        except Exception:
            s = str(v).strip()
            return s if s.lower() != "nan" else None
