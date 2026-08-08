"""竞彩模块测试：解析 + 推荐 + 服务健康。

不依赖外部网络；全部用 mock HTML / mock 数据。
"""
import json
import socket
import threading
import time
import urllib.request

from fussball_bund.analysis.jingcai_pick import (
    compute_pick,
    market_mode,
)
from fussball_bund.collectors.jingcai_500 import (
    parse_jczq_meta,
    parse_live_fixtures,
    parse_live_odds_list,
)

# ============ J1：500.com 解析 ============

MOCK_LIVE_HTML = """
<html><head><script>
var liveOddsList = {
  "12345": {"sp": ["1.85", "3.40", "4.20"], "rqsp": ["2.10", "3.20", "3.00"]},
  "12346": {"sp": ["1.50", "4.00", "6.00"]}
};
</script></head><body>
<table>
<tr order="1001" fid="12345" gy="英超,Man City,Arsenal">
  <td>周一001</td><td>英超</td>
  <td><a href="youliao-12345.shtml">析</a></td>
  <td>08-09 20:00</td>
  <td>Man City|vs|Arsenal</td>
</tr>
<tr order="1002" fid="12346" gy="西甲,Barcelona,Madrid">
  <td>周一002</td><td>西甲</td>
  <td><a href="youliao-12346.shtml">析</a></td>
  <td>08-09 22:00</td>
  <td>Barcelona|vs|Madrid</td>
</tr>
</table>
</body></html>
"""

MOCK_TRADE_HTML = """
<html><body>
<table>
<tr data-processname="1001" data-rangqiu="-1" data-homesxname="曼城"
    data-awaysxname="阿森纳" data-matchnum="周一001"><td>曼城 vs 阿森纳</td></tr>
<tr data-processname="1002" data-rangqiu="1" data-homesxname="巴塞罗那"
    data-awaysxname="皇马" data-matchnum="周一002"><td>巴萨 vs 皇马</td></tr>
</table>
</body></html>
"""


def test_parse_live_odds_list():
    """liveOddsList 解析出 SP 数据。"""
    result = parse_live_odds_list(MOCK_LIVE_HTML)
    assert "12345" in result
    assert result["12345"]["sp"] == ["1.85", "3.40", "4.20"]
    assert result["12345"]["rqsp"] == ["2.10", "3.20", "3.00"]
    assert "12346" in result
    assert result["12346"]["sp"] == ["1.50", "4.00", "6.00"]


def test_parse_jczq_meta():
    """trade.500.com 元数据解析：让球 + 队名。"""
    meta = parse_jczq_meta(MOCK_TRADE_HTML)
    assert "1001" in meta
    assert meta["1001"]["handicap"] == -1
    assert meta["1001"]["home"] == "曼城"
    assert meta["1001"]["away"] == "阿森纳"
    assert meta["1001"]["match_num"] == "周一001"
    assert meta["1002"]["handicap"] == 1


def test_parse_live_fixtures():
    """live.500.com 赛程解析：fixture_id + 编号 + order_id。"""
    fixtures = parse_live_fixtures(MOCK_LIVE_HTML)
    assert len(fixtures) == 2
    f = fixtures[0]
    assert f["fixture_id"] in ("12345", "12346")
    assert f["order_id"] in ("1001", "1002")


def test_parse_live_odds_list_empty():
    """无 liveOddsList 时返回空 dict。"""
    assert parse_live_odds_list("<html>nothing</html>") == {}


# ============ J4：推荐引擎 ============


def test_pick_spf_clear_favorite():
    """SPF 有明显热门 → 取向该方向。"""
    match = {"match_num": "周一001", "home_team": "A", "away_team": "B", "handicap": None}
    odds = {"market": "spf", "sp_home": 1.50, "sp_draw": 4.00, "sp_away": 6.00, "line": None}
    pick = compute_pick(match, odds)
    assert pick["pick"] == "home"
    assert pick["pick_cn"] == "主胜"
    assert pick["market"] == "spf"
    assert pick["sp"] == 1.50


def test_pick_spf_even_skip():
    """SPF 概率分散（无热门）→ 观望。"""
    match = {"match_num": "周一002", "home_team": "A", "away_team": "B", "handicap": None}
    odds = {"market": "spf", "sp_home": 2.80, "sp_draw": 3.10, "sp_away": 2.90, "line": None}
    pick = compute_pick(match, odds)
    assert pick["pick"] == "skip"
    assert pick["pick_cn"] == "观望"


def test_pick_rqspf():
    """RQSP 玩法有赔率 → 取向。"""
    match = {"match_num": "周一003", "home_team": "A", "away_team": "B", "handicap": 1}
    odds = {"market": "rqspf", "sp_home": 2.10, "sp_draw": 3.20, "sp_away": 3.00, "line": 1}
    pick = compute_pick(match, odds)
    assert pick["market"] == "rqspf"
    assert pick["pick"] != "skip"  # 2.10 是热门，应该有推荐
    assert "+1" in pick["market_label"]


def test_pick_no_odds():
    """无赔率 → 观望。"""
    match = {"match_num": "周一004", "home_team": "A", "away_team": "B", "handicap": None}
    pick = compute_pick(match, None)
    assert pick["pick"] == "skip"
    assert pick["pick_cn"] == "观望"
    assert pick["market"] == "none"


def test_market_mode():
    """market_mode 正确识别可用玩法。"""
    assert market_mode(None) == "none"
    assert market_mode({"market": "spf", "sp_home": 1.5}) == "spf"
    assert market_mode({"market": "rqspf", "sp_home": 2.0}) == "rqspf"
    assert market_mode({"market": "spf", "sp_home": None}) == "none"


# ============ J2：HTTP 服务健康 ============


def _free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def test_serve_health():
    """HTTP 服务 /health 返回 ok。"""
    from fussball_bund.serve import JingcaiHandler, serve
    from http.server import ThreadingHTTPServer

    port = _free_port()
    server = ThreadingHTTPServer(("127.0.0.1", port), JingcaiHandler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    time.sleep(0.3)
    try:
        resp = urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=3)
        data = json.loads(resp.read())
        assert data["status"] == "ok"
        assert "matches" in data
    finally:
        server.shutdown()
        server.server_close()


def test_serve_list_empty(tmp_db):
    """空库时 /api/jingcai/list 返回 count=0。"""
    from http.server import ThreadingHTTPServer
    from fussball_bund.serve import JingcaiHandler
    from fussball_bund.storage.db import _db

    # 临时替换全局 db
    import fussball_bund.storage.db as dbmod
    orig = dbmod._db
    dbmod._db = tmp_db
    try:
        port = _free_port()
        server = ThreadingHTTPServer(("127.0.0.1", port), JingcaiHandler)
        t = threading.Thread(target=server.serve_forever, daemon=True)
        t.start()
        time.sleep(0.3)
        try:
            resp = urllib.request.urlopen(
                f"http://127.0.0.1:{port}/api/jingcai/list", timeout=3
            )
            data = json.loads(resp.read())
            assert data["count"] == 0
        finally:
            server.shutdown()
            server.server_close()
    finally:
        dbmod._db = orig
