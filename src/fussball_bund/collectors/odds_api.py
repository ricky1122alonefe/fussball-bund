"""The Odds API 采集器 —— 实时/即将开赛赔率。

可信度/稳定性评估：
    - 官方 REST API，端点稳定可达（实证 401 需 key，符合预期）
    - 聚合 40+ 博彩公司（bet365/Pinnacle/William Hill/Unibet...）
    - 覆盖全球联赛，含五大联赛+欧冠
    - 免费额度 500 req/月，付费可扩展
    - 返回结构化 JSON，无需爬虫，最可靠的实时赔率源
    - 支持市场：h2h(1X2) / spreads(亚盘) / totals(大小球)

文档: https://the-odds-api.com/liveapi/guides/v4/
"""
from __future__ import annotations

import logging
from collections import defaultdict

from fussball_bund.collectors.base import BaseCollector

logger = logging.getLogger(__name__)


class OddsApiCollector(BaseCollector):
    name = "odds_api"
    BASE_URL = "https://api.the-odds-api.com/v4"

    def __init__(self, db=None, api_key: str | None = None) -> None:
        super().__init__(db)
        from fussball_bund.config import settings

        self.api_key = api_key or settings.odds_api_key
        if not self.api_key:
            logger.warning("ODDS_API_KEY 未设置，实时赔率采集将不可用")

    def collect_odds(self, league_key: str, regions: str = "eu", markets: str = "h2h,spreads,totals") -> dict[str, int]:
        """抓取某联赛当前可用赔率（即将开赛）。

        Args:
            league_key: EPL/LALIGA/...
            regions: eu/uk/us，多区域逗号分隔
            markets: h2h,spreads,totals
        """
        from fussball_bund.config import load_leagues

        leagues = load_leagues()
        if league_key not in leagues:
            raise ValueError(f"未知联赛 key: {league_key}")
        sport_key = leagues[league_key].odds_api
        if not self.api_key:
            raise RuntimeError("ODDS_API_KEY 未设置")

        url = f"{self.BASE_URL}/sports/{sport_key}/odds/"
        params = {"apiKey": self.api_key, "regions": regions, "markets": markets, "oddsFormat": "decimal"}
        logger.info("抓取实时赔率 %s (%s)", league_key, sport_key)
        resp = self._get(url, params=params)
        events = resp.json()
        logger.info("获取到 %d 场即将开赛比赛", len(events))

        counts = self._store(events, league_key)
        self.db.log_collection(self.name, "success",
                               f"{counts['matches']} matches, {counts['odds_1x2']} odds",
                               league_key, None)
        return counts

    def _store(self, events: list[dict], league_key: str) -> dict[str, int]:
        counts = {"matches": 0, "odds_1x2": 0, "odds_totals": 0, "odds_asian": 0}
        with self.db.transaction() as conn:
            for ev in events:
                season = self._infer_season(ev.get("commence_time", ""))
                match_date = (ev.get("commence_time", "") or "")[:10] or None
                match_id = self._upsert_match(
                    conn, league_key, season, match_date,
                    ev.get("home_team", ""), ev.get("away_team", ""),
                )
                if match_id is None:
                    continue
                counts["matches"] += 1
                for bm in ev.get("bookmakers", []):
                    bm_name = bm.get("title") or bm.get("key") or "unknown"
                    for market in bm.get("markets", []):
                        mk = market.get("key")
                        outcomes = {o["name"]: o for o in market.get("outcomes", [])}
                        if mk == "h2h":
                            h = outcomes.get(ev["home_team"], {}).get("price")
                            a = outcomes.get(ev["away_team"], {}).get("price")
                            d = outcomes.get("Draw", {}).get("price")
                            if h or d or a:
                                self._upsert_1x2(conn, match_id, bm_name, "live", h, d, a)
                                counts["odds_1x2"] += 1
                        elif mk == "totals":
                            ov = outcomes.get("Over", {})
                            un = outcomes.get("Under", {})
                            if ov.get("price") or un.get("price"):
                                conn.execute(
                                    "INSERT INTO odds_totals(match_id,bookmaker,period,line,over,under) "
                                    "VALUES (?,?,?,?,?,?) ON CONFLICT(match_id,bookmaker,period,line) "
                                    "DO UPDATE SET over=excluded.over,under=excluded.under",
                                    (match_id, bm_name, "live", ov.get("point"), ov.get("price"), un.get("price")),
                                )
                                counts["odds_totals"] += 1
                        elif mk == "spreads":
                            hp = outcomes.get(ev["home_team"], {})
                            ap = outcomes.get(ev["away_team"], {})
                            if hp.get("price") or ap.get("price"):
                                conn.execute(
                                    "INSERT INTO odds_asian_handicap(match_id,bookmaker,period,handicap,home,away) "
                                    "VALUES (?,?,?,?,?,?) ON CONFLICT(match_id,bookmaker,period,handicap) "
                                    "DO UPDATE SET home=excluded.home,away=excluded.away",
                                    (match_id, bm_name, "live", hp.get("point"), hp.get("price"), ap.get("price")),
                                )
                                counts["odds_asian"] += 1
        return counts

    def _upsert_match(self, conn, league_key, season, match_date, home, away) -> int | None:
        row = conn.execute(
            "INSERT INTO matches(league_code,season,match_date,home_team,away_team) "
            "VALUES (?,?,?,?,?) "
            "ON CONFLICT(league_code,season,match_date,home_team,away_team) DO NOTHING "
            "RETURNING id",
            (league_key, season, match_date, home, away),
        ).fetchone()
        if row is None:
            row = conn.execute(
                "SELECT id FROM matches WHERE league_code=? AND season=? AND match_date=? "
                "AND home_team=? AND away_team=?",
                (league_key, season, match_date, home, away),
            ).fetchone()
        return row["id"] if row else None

    def _upsert_1x2(self, conn, match_id, bookmaker, period, h, d, a) -> None:
        conn.execute(
            "INSERT INTO odds_1x2(match_id,bookmaker,period,home,draw,away) VALUES (?,?,?,?,?,?) "
            "ON CONFLICT(match_id,bookmaker,period) DO UPDATE SET "
            "home=excluded.home,draw=excluded.draw,away=excluded.away",
            (match_id, bookmaker, period, h, d, a),
        )

    @staticmethod
    def _infer_season(commence_time: str) -> str:
        """从开赛时间推断赛季：8月起算新赛季。2025-08-15 -> 2025-2026。"""
        try:
            y = int(commence_time[:4])
            m = int(commence_time[5:7])
        except (ValueError, IndexError):
            return "unknown"
        if m >= 8:
            return f"{y}-{y+1}"
        return f"{y-1}-{y}"
