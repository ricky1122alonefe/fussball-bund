"""结算与评估指标测试。"""
import math

from fussball_bund.analysis.metrics import (
    aggregate_clv,
    brier_score,
    clv,
    log_loss,
    opening_roi,
    settle,
    settle_1x2,
)


def test_settle_1x2_hit():
    assert settle_1x2("home", "H") is True
    assert settle_1x2("draw", "D") is True
    assert settle_1x2("away", "A") is True


def test_settle_1x2_miss():
    assert settle_1x2("home", "A") is False
    assert settle_1x2("draw", "H") is False


def test_settle_win_loses_correct():
    assert settle(2.0, "home", "H") == 1.0      # 赢：净赚 (2.0-1)*1
    assert settle(2.0, "home", "A") == -1.0     # 输：亏 1
    assert settle(3.5, "draw", "D") == 2.5      # 赔率3.5 赢平局


class TestBrier:
    def test_perfect(self):
        assert brier_score([(1.0, 0.0, 0.0)], ["H"]) == 0.0

    def test_worst(self):
        # 完全猜反：实际 H，预测 A=1
        assert abs(brier_score([(0.0, 0.0, 1.0)], ["H"]) - 2.0) < 1e-9

    def test_uniform(self):
        # (1/3-1)^2 + (1/3)^2 + (1/3)^2 = 4/9 + 1/9 + 1/9 = 6/9 ≈ 0.667
        b = brier_score([(1 / 3, 1 / 3, 1 / 3)], ["H"])
        assert abs(b - 6 / 9) < 1e-9


class TestLogLoss:
    def test_perfect(self):
        assert log_loss([(1.0, 0.0, 0.0)], ["H"]) < 0.01

    def test_uniform(self):
        ll = log_loss([(1 / 3, 1 / 3, 1 / 3)], ["H"])
        assert abs(ll - (-math.log(1 / 3))) < 0.01


def test_clv_beat_closing():
    # bet 2.2 > closing 2.0 → 下注赔率高于收盘 → beat closing（正）
    assert clv(2.2, 2.0) > 0
    assert abs(clv(2.2, 2.0) - (2.2 / 2.0 - 1)) < 1e-9


def test_clv_lost_to_closing():
    # bet 2.0 < closing 2.2 → 输给收盘（负）
    assert clv(2.0, 2.2) < 0


def test_clv_no_closing():
    assert clv(2.0, None) is None
    assert clv(2.0, 0) is None


def test_aggregate_clv():
    # 2.2/2.0-1=+0.1(正), 2.0/1.8-1=+0.111(正) → 都正
    r = aggregate_clv([2.2, 2.0], [2.0, 1.8])
    assert r["n"] == 2
    assert r["positive_pct"] == 1.0


class TestOpeningRoi:
    def test_all_win(self):
        class Bet:
            def __init__(self, o, m):
                self.odds, self.market = o, m
        bets = [Bet(2.0, "home"), Bet(3.0, "draw")]
        r = opening_roi(bets, ["H", "D"])
        assert r["n_bets"] == 2
        assert r["wins"] == 2
        # 盈利 (2-1)+(3-1)=3, 成本 2, ROI=3/2*100=150
        assert r["roi_pct"] == 150.0

    def test_mixed(self):
        class Bet:
            def __init__(self, o, m):
                self.odds, self.market = o, m
        bets = [Bet(2.0, "home"), Bet(2.0, "home")]
        r = opening_roi(bets, ["H", "A"])  # 一赢一输
        assert r["wins"] == 1
        assert r["n_bets"] == 2
        assert abs(r["profit"] - 0.0) < 1e-9  # +1 -1 = 0
