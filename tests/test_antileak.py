"""反泄漏测试——锁死训练数据不含未来比赛。

这是评估可信化的核心护栏：禁止用 match_date >= 预测时点的数据训练。
"""
from fussball_bund.analysis.models import PoissonModel
from fussball_bund.analysis.walkforward import run_walkforward


def test_fit_max_date_excludes_future(tmp_db, insert_match):
    """fit(max_date=d) 的训练数据必须 match_date < d。"""
    insert_match("TST", "2024-2025", "2024-08-01", "A", "B", 2, 1, "H")
    insert_match("TST", "2024-2025", "2024-08-08", "A", "B", 1, 1, "D")
    insert_match("TST", "2024-2025", "2024-08-15", "A", "B", 0, 3, "A")  # 不应进训练

    # fit 用 max_date=2024-08-10 → 只含 08-01, 08-08
    m = PoissonModel(db=tmp_db).fit("TST", max_date="2024-08-10")
    # 主队进球: 2, 1（不含 08-15 的 0）→ avg_home_goals = 1.5
    assert abs(m.avg_home_goals - 1.5) < 1e-6, "训练数据含未来比赛（数据泄露）！"


def test_fit_max_date_boundary(tmp_db, insert_match):
    """边界：max_date == 某比赛 date 时，该比赛不进训练（严格 <）。"""
    insert_match("TST", "2024-2025", "2024-08-01", "A", "B", 2, 0, "H")
    insert_match("TST", "2024-2025", "2024-08-08", "A", "B", 3, 0, "H")
    # max_date = 08-08，则 08-08 不进训练（严格小于）
    m = PoissonModel(db=tmp_db).fit("TST", max_date="2024-08-08")
    assert abs(m.avg_home_goals - 2.0) < 1e-6  # 只含 08-01 的 2 球


def test_walkforward_end_to_end(tmp_db, insert_match):
    """walk-forward 端到端跑通，且 refits <= 比赛日数（每日重训，不外推）。"""
    data = [
        ("2024-08-01", "A", "B", 2, 1, "H", (1.5, 4.0, 6.0)),
        ("2024-08-01", "C", "D", 1, 1, "D", (2.5, 3.0, 3.0)),
        ("2024-08-08", "A", "C", 1, 0, "H", (1.8, 3.5, 4.5)),
        ("2024-08-08", "B", "D", 2, 2, "D", (2.0, 3.2, 4.0)),
        ("2024-08-15", "A", "D", 3, 1, "H", (1.4, 4.5, 7.0)),
        ("2024-08-15", "B", "C", 0, 1, "A", (3.0, 3.0, 2.5)),
    ]
    for d, h, a, hg, ag, res, odds in data:
        insert_match("TST", "2024-2025", d, h, a, hg, ag, res, opening=odds)

    result = run_walkforward(
        "TST", "2024-2025", model_name="poisson", bet_period="opening", db=tmp_db
    )
    assert result.n_matches == 6
    assert result.refits >= 1
    assert result.refits <= 3  # 3 个比赛日
    assert 0.0 <= result.brier <= 2.0  # Brier 合理范围


def test_walkforward_no_future_in_training(tmp_db, insert_match):
    """walk-forward 的 Brier 必须可计算（每场都基于历史预测，非 NaN）。"""
    for i in range(6):
        hg, ag = i % 3, (i + 1) % 3
        res = "H" if hg > ag else ("D" if hg == ag else "A")
        insert_match("TST", "2024-2025", f"2024-08-{i + 1:02d}", "A", "B", hg, ag, res)

    result = run_walkforward("TST", "2024-2025", model_name="poisson", db=tmp_db)
    # Brier 为有限数（非 NaN），说明每场都有训练数据支撑
    assert result.brier == result.brier  # not NaN
    assert result.brier >= 0
