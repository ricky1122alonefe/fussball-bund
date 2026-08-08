"""500.com 竞彩足球采集器。

对照 gyl 的 jingcai_500 / download_500 / poll_500，在本仓重新实现。
数据流：
  1. live.500.com  → 赛程表（fixture_id, 编号, 对阵, 开赛）+ liveOddsList（SP 数据）
  2. trade.500.com/jczq → 竞彩元数据（编号, 让球, 队名）
  3. 合并写入 jingcai_matches + jingcai_odds

不 import guess_you_like；逻辑本仓自洽。
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta
from typing import Any

from bs4 import BeautifulSoup

from fussball_bund.collectors.base import BaseCollector
from fussball_bund.storage.db import Database, get_db

log = logging.getLogger(__name__)

LIVE_URL = "https://live.500.com/"
TRADE_URL = "https://trade.500.com/jczq/?playid=269&g=2"
TIMEOUT = 30


def _decode(content: bytes) -> str:
    """500.com 用 GB18030 编码，依次尝试。"""
    for enc in ("gb18030", "gbk", "utf-8"):
        try:
            return content.decode(enc)
        except UnicodeDecodeError:
            continue
    return content.decode("gb18030", errors="replace")


def _to_float(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _sp_triple(values: list | None) -> tuple[float | None, float | None, float | None]:
    """从 liveOddsList 的 sp/rqsp 数组取前三（胜/平/负）。"""
    if not values or len(values) < 3:
        return None, None, None
    return _to_float(values[0]), _to_float(values[1]), _to_float(values[2])


# ============ 解析函数（纯函数，可单测） ============

def parse_live_odds_list(html_text: str) -> dict[str, dict]:
    """从 live.500.com HTML 中提取 var liveOddsList = {...}。"""
    m = re.search(r"var\s+liveOddsList\s*=\s*(\{.*?\});", html_text, re.S)
    if not m:
        return {}
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError:
        return {}


def parse_jczq_meta(html_text: str) -> dict[str, dict[str, Any]]:
    """从 trade.500.com/jczq HTML 解析竞彩元数据（data-processname → 信息）。"""
    soup = BeautifulSoup(html_text, "html.parser")
    out: dict[str, dict[str, Any]] = {}
    for tr in soup.find_all("tr", attrs={"data-processname": True}):
        order = str(tr.get("data-processname", "")).strip()
        if not order:
            continue
        handicap_raw = tr.get("data-rangqiu")
        try:
            handicap = int(handicap_raw) if handicap_raw not in (None, "") else None
        except ValueError:
            handicap = None
        out[order] = {
            "match_num": tr.get("data-matchnum") or "",
            "handicap": handicap,
            "home": tr.get("data-homesxname") or "",
            "away": tr.get("data-awaysxname") or "",
        }
    return out


def parse_live_fixtures(html_text: str) -> list[dict[str, Any]]:
    """从 live.500.com 解析赛程表（fixture_id, 编号, 对阵, 开赛, order_id）。

    真实 HTML 结构：
      <tr id="..." order="6001" fid="1418869" gy="日职,大阪樱花,冈山绿雉" ...>
        <td>周六001</td><td>日职</td><td>第1轮</td><td>08-08 18:00</td>...
      </tr>
    队名优先从 tr.gy 属性取（格式 "联赛,主队,客队"），回退 td 文本。
    """
    soup = BeautifulSoup(html_text, "html.parser")
    fixtures: list[dict[str, Any]] = []
    seen: set[str] = set()

    for a in soup.find_all("a", href=re.compile(r"youliao-\d+\.shtml")):
        m = re.search(r"youliao-(\d+)\.shtml", a.get("href", ""))
        if not m:
            continue
        fid = m.group(1)
        if fid in seen:
            continue
        seen.add(fid)

        tr = a.find_parent("tr")
        if not tr:
            continue
        row_text = tr.get_text("|", strip=True)

        # 开赛时间
        kickoff = _parse_kickoff(row_text)

        # 队名：优先 tr.gy 属性（"联赛,主队,客队"）
        home, away = "", ""
        gy = tr.get("gy", "")
        if gy:
            parts = [p.strip() for p in gy.split(",")]
            if len(parts) >= 3:
                home, away = parts[1], parts[2]
        if not home or not away:
            home, away = _parse_teams_from_row(row_text)

        # 联赛名
        league = ""
        if gy:
            parts = [p.strip() for p in gy.split(",")]
            if parts:
                league = parts[0]
        if not league:
            tds = tr.find_all("td")
            if len(tds) > 1:
                league = tds[1].get_text(strip=True)

        # order_id（用于关联 trade 页元数据）
        order_id = str(tr.get("order", "")).strip()

        # 竞彩编号（如 周六001）：从 td[0] 取
        match_num = ""
        tds = tr.find_all("td")
        if tds:
            txt = tds[0].get_text(strip=True)
            if txt and re.match(r"周[一二三四五六日天]\d+", txt):
                match_num = txt

        fixtures.append({
            "fixture_id": fid,
            "match_num": match_num,
            "home": home,
            "away": away,
            "league": league,
            "kickoff": kickoff,
            "order_id": order_id,
        })

    fixtures.sort(key=lambda f: f.get("kickoff") or "9999")
    return fixtures


def _parse_kickoff(text: str) -> str:
    """从行文本解析开赛时间 '08-09 20:00' → ISO 日期。"""
    m = re.search(r"(\d{2})-(\d{2})\s+(\d{2}):(\d{2})", text)
    if not m:
        return ""
    month, day = int(m.group(1)), int(m.group(2))
    hour, minute = int(m.group(3)), int(m.group(4))
    now = datetime.now()
    year = now.year
    dt = datetime(year, month, day, hour, minute)
    if dt < now - timedelta(days=180):
        dt = dt.replace(year=year + 1)
    return dt.strftime("%Y-%m-%d %H:%M")


def _parse_teams_from_row(text: str) -> tuple[str, str]:
    """从行文本解析主客队名。"""
    parts = [p.strip() for p in text.split("|") if p.strip()]
    skip = {"未", "析", "亚", "欧", "推荐", "置顶", "-", "完"}
    teams: list[str] = []
    for p in parts:
        if re.match(r"^周[一二三四五六日天]", p):
            continue
        if re.match(r"^\d{2}-\d{2}", p):
            continue
        if re.match(r"^\[\d+\]$", p):
            continue
        if p in skip:
            continue
        if re.match(r"^\([+\-]\d+\)$", p):
            continue
        if re.search(r"球|/|平手|受让", p) and len(p) < 12:
            continue
        if len(p) >= 2 and not p.isdigit():
            teams.append(re.sub(r"\[\d+\]", "", p).strip())
        if len(teams) >= 2:
            break
    return (teams[0], teams[1]) if len(teams) >= 2 else ("", "")


# ============ 采集器 ============

class JingcaiCollector(BaseCollector):
    """500.com 竞彩足球采集器。"""

    name = "jingcai_500"

    def __init__(self, db: Database | None = None) -> None:
        super().__init__(db)

    def poll(self) -> dict[str, int]:
        """执行一轮竞彩采集：拉 live + trade 页 → 解析 → 写库。

        Returns:
            {"matches": N, "spf": M, "rqspf": K}
        """
        # 1. 拉 live.500.com（timeout 由 BaseCollector._get / settings 统一注入，勿再传 timeout）
        resp = self._get(LIVE_URL)
        live_html = _decode(resp.content)
        fixtures = parse_live_fixtures(live_html)
        live_odds = parse_live_odds_list(live_html)
        log.info("live.500.com: %d 场赛程, %d 条 SP", len(fixtures), len(live_odds))

        # 2. 拉 trade.500.com/jczq
        jczq_meta: dict[str, dict] = {}
        try:
            resp2 = self.session.get(
                TRADE_URL, timeout=TIMEOUT,
                headers={"Referer": LIVE_URL},
            )
            resp2.raise_for_status()
            jczq_meta = parse_jczq_meta(_decode(resp2.content))
            log.info("trade.500.com/jczq: %d 条元数据", len(jczq_meta))
        except Exception as exc:
            log.warning("竞彩元数据抓取失败: %s", exc)

        # 3. 合并 + 写库
        counts = {"matches": 0, "spf": 0, "rqspf": 0}
        with self.db.transaction() as conn:
            now_iso = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            for fx in fixtures:
                fid = fx["fixture_id"]
                order_id = fx.get("order_id", "")
                meta = jczq_meta.get(order_id, {})

                match_num = fx.get("match_num") or meta.get("match_num") or ""
                if not match_num:
                    continue  # 无编号 = 非竞彩场，跳过

                home = meta.get("home") or fx.get("home") or ""
                away = meta.get("away") or fx.get("away") or ""
                handicap = meta.get("handicap")

                # upsert match
                conn.execute(
                    "INSERT INTO jingcai_matches(match_num, fixture_id, kickoff, "
                    "league_name, home_team, away_team, handicap, updated_at) "
                    "VALUES (?,?,?,?,?,?,?,?) "
                    "ON CONFLICT(match_num) DO UPDATE SET "
                    "fixture_id=excluded.fixture_id, kickoff=excluded.kickoff, "
                    "league_name=excluded.league_name, home_team=excluded.home_team, "
                    "away_team=excluded.away_team, handicap=COALESCE(excluded.handicap, "
                    "jingcai_matches.handicap), updated_at=excluded.updated_at",
                    (match_num, fid, fx.get("kickoff") or "",
                     fx.get("league") or "", home, away, handicap, now_iso),
                )
                counts["matches"] += 1

                # SP 数据
                item = live_odds.get(str(fid)) or {}
                sp_h, sp_d, sp_a = _sp_triple(item.get("sp"))
                rq_h, rq_d, rq_a = _sp_triple(item.get("rqsp"))

                if sp_h is not None:
                    conn.execute(
                        "INSERT INTO jingcai_odds(match_num, market, line, "
                        "sp_home, sp_draw, sp_away, source, ts) "
                        "VALUES (?,?,?,?,?,?,?,?)",
                        (match_num, "spf", None, sp_h, sp_d, sp_a, "500", now_iso),
                    )
                    counts["spf"] += 1
                if rq_h is not None:
                    conn.execute(
                        "INSERT INTO jingcai_odds(match_num, market, line, "
                        "sp_home, sp_draw, sp_away, source, ts) "
                        "VALUES (?,?,?,?,?,?,?,?)",
                        (match_num, "rqspf", handicap, rq_h, rq_d, rq_a, "500", now_iso),
                    )
                    counts["rqspf"] += 1

        self.db.log_collection(self.name, "success",
                               f"matches={counts['matches']}, spf={counts['spf']}, "
                               f"rqspf={counts['rqspf']}")
        log.info("竞彩采集完成: %s", counts)
        return counts


def poll_jingcai(db: Database | None = None) -> dict[str, int]:
    """便捷入口：执行一轮竞彩采集。"""
    c = JingcaiCollector(db=db or get_db())
    return c.poll()
