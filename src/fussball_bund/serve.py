"""竞彩 HTTP 服务（stdlib ThreadingHTTPServer，对照 gyl serve.py）。

路由：
  GET  /                         → 竞彩列表（HTML）
  GET  /match/{match_num}        → 单场详情（HTML）
  GET  /health                   → 健康检查（JSON）
  GET  /api/jingcai/list         → 列表 API（JSON）
  GET  /api/jingcai/{match_num}  → 单场 API（JSON）
  POST /api/poll                 → 触发采集（JSON）
"""
from __future__ import annotations

import json
import logging
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlparse

from fussball_bund.storage.db import get_db

log = logging.getLogger(__name__)

_CSS = """
<style>
body{font-family:system-ui,sans-serif;max-width:960px;margin:20px auto;padding:0 16px;color:#222}
table{border-collapse:collapse;width:100%;font-size:14px}
th,td{border:1px solid #ddd;padding:6px 10px;text-align:center}
th{background:#f5f5f5}
.pick-ok{color:#d32f2f;font-weight:bold}
.pick-skip{color:#888}
a{color:#1565c0;text-decoration:none}
a:hover{text-decoration:underline}
.btn{display:inline-block;padding:6px 16px;background:#1565c0;color:#fff;border-radius:4px;
     border:none;cursor:pointer;font-size:14px;text-decoration:none}
.btn:hover{background:#0d47a1}
.muted{color:#888;font-size:12px}
</style>
"""

_JS_POLL = """
<script>
async function poll(){
  const r = await fetch('/api/poll',{method:'POST'});
  const d = await r.json();
  alert('采集完成: ' + d.matches + ' 场, SPF ' + d.spf + ', RQSPF ' + d.rqspf);
  location.reload();
}
</script>
"""


def _list_matches(db):
    """取竞彩列表 + 最新赔率 + 推荐。"""
    from fussball_bund.analysis.jingcai_pick import (
        compute_pick,
        get_latest_odds_by_market,
    )

    rows = db.execute(
        "SELECT match_num, fixture_id, kickoff, league_name, home_team, away_team, "
        "handicap, sell_status FROM jingcai_matches ORDER BY kickoff"
    )
    out = []
    for r in rows:
        m = dict(r)
        by_mkt = get_latest_odds_by_market(db, m["match_num"])
        odds = by_mkt.get("spf") or by_mkt.get("rqspf")
        m["pick"] = compute_pick(m, odds)
        m["latest_odds"] = odds
        m["odds_spf"] = by_mkt.get("spf")
        m["odds_rqspf"] = by_mkt.get("rqspf")
        out.append(m)
    return out


def _fmt_sp(odds: dict | None, *, with_line: bool = False) -> str:
    if not odds:
        return "—"
    triple = f"{odds.get('sp_home', '—')}/{odds.get('sp_draw', '—')}/{odds.get('sp_away', '—')}"
    if with_line and odds.get("line") is not None:
        return f"({odds['line']}){triple}"
    return triple


def _html_list(matches: list[dict]) -> str:
    rows_html = ""
    for m in matches:
        spf = _fmt_sp(m.get("odds_spf"))
        rqsp = _fmt_sp(m.get("odds_rqspf"), with_line=True)
        pk = m["pick"]
        pk_cls = "pick-ok" if pk["pick"] != "skip" else "pick-skip"
        pk_text = f"{pk['pick_cn']}（{pk['market_label']}）" if pk["pick"] != "skip" else pk["pick_cn"]
        rows_html += (
            f"<tr>"
            f"<td><a href='/match/{m['match_num']}'>{m['match_num']}</a></td>"
            f"<td>{m.get('kickoff') or '—'}</td>"
            f"<td>{m.get('league_name') or '—'}</td>"
            f"<td>{m.get('home_team','')} vs {m.get('away_team','')}</td>"
            f"<td>{spf}</td>"
            f"<td>{rqsp}</td>"
            f"<td class='{pk_cls}'>{pk_text}</td>"
            f"</tr>"
        )
    return f"""<!DOCTYPE html><html><head><meta charset='utf-8'>
<title>竞彩关注清单</title>{_CSS}</head><body>
<h1>⚽ 竞彩关注清单</h1>
<p><button class='btn' onclick='poll()'>刷新采集</button>
<span class='muted'>共 {len(matches)} 场</span></p>
{_JS_POLL}
<table>
<tr><th>编号</th><th>开赛</th><th>联赛</th><th>对阵</th>
<th>胜平负SP</th><th>让球SP</th><th>推荐</th></tr>
{rows_html}
</table>
<p class='muted'>⚠️ 仅供研究参考，不构成投注建议。SP 隐含概率分散时建议观望。</p>
</body></html>"""


def _html_detail(match: dict, odds_history: list[dict], pick: dict) -> str:
    odds_rows = ""
    for o in odds_history:
        odds_rows += (
            f"<tr><td>{o['market']}</td><td>{o.get('line') or '—'}</td>"
            f"<td>{o.get('sp_home') or '—'}</td><td>{o.get('sp_draw') or '—'}</td>"
            f"<td>{o.get('sp_away') or '—'}</td><td>{o['ts']}</td></tr>"
        )
    pk_cls = "pick-ok" if pick["pick"] != "skip" else "pick-skip"
    return f"""<!DOCTYPE html><html><head><meta charset='utf-8'>
<title>{match['match_num']} 详情</title>{_CSS}</head><body>
<h1>{match['match_num']} — {match.get('home_team','')} vs {match.get('away_team','')}</h1>
<p><a href='/'>← 返回列表</a></p>
<table>
<tr><th>编号</th><th>开赛</th><th>联赛</th><th>让球</th></tr>
<tr><td>{match['match_num']}</td><td>{match.get('kickoff') or '—'}</td>
<td>{match.get('league_name') or '—'}</td><td>{match.get('handicap') or '—'}</td></tr>
</table>
<h2>推荐</h2>
<p class='{pk_cls}' style='font-size:18px'>{pick['pick_cn']}（{pick['market_label']}）
{f'SP {pick["sp"]}' if pick.get('sp') else ''}</p>
<p class='muted'>{pick['reason']}</p>
<h2>SP 历史</h2>
<table>
<tr><th>玩法</th><th>让球</th><th>主胜</th><th>平</th><th>客胜</th><th>时间</th></tr>
{odds_rows}
</table>
<p class='muted'>⚠️ 仅供研究参考，不构成投注建议。</p>
</body></html>"""


class JingcaiHandler(BaseHTTPRequestHandler):
    """竞彩 HTTP 请求处理器。"""

    def log_message(self, fmt, *args):
        log.info("%s - %s", self.address_string(), fmt % args)

    def _send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, html, status=200):
        body = html.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urlparse(self.path).path
        db = get_db()

        if path in ("/health", "/api/health"):
            n = 0
            last_poll = None
            try:
                n = db.execute("SELECT COUNT(*) AS c FROM jingcai_matches")[0]["c"]
                rows = db.execute(
                    "SELECT MAX(ts) AS t FROM jingcai_odds"
                )
                last_poll = rows[0]["t"] if rows else None
            except Exception:
                pass
            self._send_json({
                "status": "ok",
                "matches": n,
                "last_odds_ts": last_poll,
            })
            return

        if path == "/" or path == "/api/jingcai/list":
            matches = _list_matches(db)
            if path.startswith("/api/"):
                self._send_json({"count": len(matches), "matches": matches})
            else:
                self._send_html(_html_list(matches))
            return

        m = re.match(r"^/match/(.+)$", path)
        m_api = re.match(r"^/api/jingcai/(.+)$", path)
        match_num = (m or m_api)
        if match_num:
            mn = unquote(match_num.group(1))
            rows = db.execute(
                "SELECT * FROM jingcai_matches WHERE match_num=?", (mn,)
            )
            if not rows:
                self._send_json({"error": "not found"}, 404)
                return
            match = dict(rows[0])
            from fussball_bund.analysis.jingcai_pick import (
                compute_pick,
                get_latest_odds,
            )
            odds_history = [dict(r) for r in db.execute(
                "SELECT * FROM jingcai_odds WHERE match_num=? ORDER BY ts DESC", (mn,)
            )]
            pick = compute_pick(match, get_latest_odds(db, mn))
            if m_api:
                self._send_json({"match": match, "odds_history": odds_history, "pick": pick})
            else:
                self._send_html(_html_detail(match, odds_history, pick))
            return

        self._send_json({"error": "not found"}, 404)

    def do_POST(self):
        path = urlparse(self.path).path
        if path == "/api/poll":
            try:
                from fussball_bund.collectors.jingcai_500 import poll_jingcai
                counts = poll_jingcai()
                self._send_json({"ok": True, **counts})
            except Exception as exc:
                log.exception("poll failed")
                self._send_json({"ok": False, "error": str(exc)}, 500)
            return
        self._send_json({"error": "not found"}, 404)


def serve(host: str = "127.0.0.1", port: int = 8901) -> None:
    """启动竞彩 HTTP 服务。"""
    server = ThreadingHTTPServer((host, port), JingcaiHandler)
    log.info("竞彩服务启动: http://%s:%d", host, port)
    print(f"竞彩服务启动: http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n服务已停止")
        server.shutdown()
