"""竞彩推荐引擎（对照 gyl jingcai_pick，本仓简化实现）。

规则：
- 有 SPF SP → 按隐含概率取向；最高 < 34% → 观望
- 仅 RQSP → 让球玩法同理，附让球线
- 无 SP → 观望（禁止无 SP 冒充可购）

不依赖外盘/模型；v1 纯 SP 驱动。
"""
from __future__ import annotations

from typing import Any

SP_CN = {"home": "主胜", "draw": "平局", "away": "客胜", "skip": "观望"}
RQ_CN = {"home": "胜", "draw": "平", "away": "负", "skip": "观望"}
NO_JINGCAI = "暂无竞彩"


def market_mode(latest_odds: dict | None) -> str:
    """返回可购玩法：spf | rqspf | none。"""
    if not latest_odds:
        return "none"
    if latest_odds.get("market") == "spf" and latest_odds.get("sp_home"):
        return "spf"
    if latest_odds.get("market") == "rqspf" and latest_odds.get("sp_home"):
        return "rqspf"
    return "none"


def _implied_probs(sp_h: float, sp_d: float, sp_a: float) -> dict[str, float]:
    """朴素去水：p_i = (1/odds_i) / Σ(1/odds_j)。"""
    rh = 1.0 / sp_h if sp_h and sp_h > 0 else 0
    rd = 1.0 / sp_d if sp_d and sp_d > 0 else 0
    ra = 1.0 / sp_a if sp_a and sp_a > 0 else 0
    total = rh + rd + ra
    if total <= 0:
        return {"home": 0, "draw": 0, "away": 0}
    return {"home": rh / total, "draw": rd / total, "away": ra / total}


def _handicap_label(handicap: int | None) -> str:
    if handicap is None:
        return "—"
    if handicap > 0:
        return f"+{handicap}"
    return str(handicap)


def compute_pick(match: dict, latest_odds: dict | None) -> dict[str, Any]:
    """从竞彩场次 + 最新赔率快照计算推荐。

    Args:
        match: jingcai_matches 行（含 match_num, home_team, away_team, handicap）
        latest_odds: 最新 jingcai_odds 行（含 market, sp_home, sp_draw, sp_away, line）

    Returns:
        {market, market_label, pick, pick_cn, sp, reason}
    """
    mode = market_mode(latest_odds)
    if mode == "none" or not latest_odds:
        return {
            "market": "none",
            "market_label": "—",
            "pick": "skip",
            "pick_cn": "观望",
            "sp": None,
            "reason": "暂无竞彩开售数据",
        }

    sp_h = latest_odds.get("sp_home")
    sp_d = latest_odds.get("sp_draw")
    sp_a = latest_odds.get("sp_away")
    if not sp_h or not sp_a:
        return {
            "market": mode,
            "market_label": "胜平负" if mode == "spf" else f"让球({_handicap_label(latest_odds.get('line'))})",
            "pick": "skip",
            "pick_cn": "观望",
            "sp": None,
            "reason": "SP 数据不完整",
        }

    probs = _implied_probs(float(sp_h), float(sp_d) or 0, float(sp_a))
    best = max(probs, key=probs.get)
    best_pct = probs[best]

    cn_map = SP_CN if mode == "spf" else RQ_CN
    mkt_label = "胜平负" if mode == "spf" else f"让球({_handicap_label(latest_odds.get('line'))})"

    if best_pct < 0.40:
        return {
            "market": mode,
            "market_label": mkt_label,
            "pick": "skip",
            "pick_cn": "观望",
            "sp": None,
            "reason": (
                f"{mkt_label} SP 隐含概率分散"
                f"（主{probs['home']:.0%}/平{probs['draw']:.0%}/客{probs['away']:.0%}），建议观望"
            ),
        }

    sp_map = {"home": sp_h, "draw": sp_d, "away": sp_a}
    return {
        "market": mode,
        "market_label": mkt_label,
        "pick": best,
        "pick_cn": cn_map[best],
        "sp": round(float(sp_map[best]), 2) if sp_map[best] else None,
        "reason": (
            f"{mkt_label} SP 隐含"
            f"主{probs['home']:.0%}/平{probs['draw']:.0%}/客{probs['away']:.0%}，"
            f"取向{cn_map[best]}"
        ),
    }


def get_latest_odds(db, match_num: str) -> dict | None:
    """取某场最新一条赔率快照（优先 spf，其次 rqspf）。"""
    by_market = get_latest_odds_by_market(db, match_num)
    return by_market.get("spf") or by_market.get("rqspf")


def get_latest_odds_by_market(db, match_num: str) -> dict[str, dict]:
    """分别取 spf / rqspf 最新快照，供列表页双列展示。"""
    out: dict[str, dict] = {}
    for market in ("spf", "rqspf"):
        rows = db.execute(
            "SELECT match_num, market, line, sp_home, sp_draw, sp_away, source, ts "
            "FROM jingcai_odds WHERE match_num=? AND market=? ORDER BY ts DESC LIMIT 1",
            (match_num, market),
        )
        if rows:
            out[market] = dict(rows[0])
    return out
