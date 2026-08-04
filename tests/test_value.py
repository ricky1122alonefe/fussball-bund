"""ValueBetFinder 默认 period 对齐回测协议的测试。

协议要求默认 opening（见 docs/BACKTEST_PROTOCOL.md）。
CLI 已显式传 period，但直接从 Python 调 find/backtest 时必须默认 opening，
避免 silently 用 closing（含未来信息）。
"""
import inspect

from fussball_bund.analysis.value import ValueBetFinder


def test_find_default_period_is_opening():
    """find 默认 period 必须是 opening。"""
    sig = inspect.signature(ValueBetFinder.find)
    assert sig.parameters["period"].default == "opening"


def test_backtest_default_period_is_opening():
    """backtest 默认 period 必须是 opening（对齐协议/CLI）。"""
    sig = inspect.signature(ValueBetFinder.backtest)
    assert sig.parameters["period"].default == "opening"


def test_backtest_default_uses_opening_odds(tmp_db, insert_match):
    """行为确认：默认 backtest 走 opening 赔率（opening 与 closing 不同时可区分）。"""
    from fussball_bund.analysis.models import PoissonModel

    # 构造历史让模型能拟合（A 主场强）
    for i in range(6):
        insert_match(
            "TST", "2024-2025", f"2024-09-{i + 1:02d}", "A", "B",
            2 + (i % 2), i % 2, "H" if (i % 2 == 0) else "A",
            opening=(1.3, 5.0, 8.0),
            closing=(1.3, 5.0, 8.0),
        )
    # 目标场：opening home=10.0（高赔率，模型若看好主队则有 edge）, closing home=1.05（极低）
    insert_match(
        "TST", "2024-2025", "2024-10-01", "A", "B", 3, 0, "H",
        opening=(10.0, 5.0, 1.05),
        closing=(1.05, 5.0, 10.0),
    )
    m = PoissonModel(db=tmp_db).fit("TST", max_date="2024-10-01")
    finder = ValueBetFinder(db=tmp_db, model=m)

    # 默认（应 opening）：A 主场强，opening home=10.0 极高 → 会有 home 投注
    bt_open = finder.backtest("TST", "2024-2025", min_edge=0.0)
    # closing：home=1.05 极低（< min_odds 默认1.5），不会有 home 投注
    bt_close = finder.backtest("TST", "2024-2025", period="closing", min_edge=0.0)

    # 默认走 opening 时应识别到投注（opening home 高赔率），closing 时无
    assert bt_open["total_bets"] > bt_close["total_bets"], (
        f"默认 backtest 未走 opening（open={bt_open['total_bets']}, close={bt_close['total_bets']}）"
    )
