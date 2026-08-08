"""XGPoissonModel.fit 读 match_xg 测试（数据源已切到 match_xg，队名 canonical）。"""
from fussball_bund.analysis.xg_model import XGPoissonModel


def test_xg_fit_reads_match_xg_canonical(tmp_db, insert_match_xg):
    """fit 从 match_xg 读，队名已是 canonical，强度按 canonical 归集。"""
    insert_match_xg("TST", "2024-2025", "2024-08-17", "Arsenal", "Chelsea", 3.0, 0.5)
    insert_match_xg("TST", "2024-2025", "2024-08-17", "Liverpool", "Man United", 2.0, 1.0)
    m = XGPoissonModel(db=tmp_db).fit("TST", seasons=["2024-2025"], min_matches=1)
    assert "Arsenal" in m.home_attack
    assert "Liverpool" in m.home_attack
    assert m.home_attack["Arsenal"] > 1.0  # xG=3.0 高于均值


def test_xg_fit_max_date_excludes_future(tmp_db, insert_match_xg):
    """max_date 反泄漏：match_xg 里 date >= max_date 的场不进 avg。"""
    insert_match_xg("TST", "2024-2025", "2024-08-01", "A", "B", 2.0, 0.5)
    insert_match_xg("TST", "2024-2025", "2024-08-08", "A", "B", 1.0, 0.5)
    insert_match_xg("TST", "2024-2025", "2024-08-15", "A", "B", 0.5, 0.5)  # 不进训练
    m = XGPoissonModel(db=tmp_db).fit("TST", max_date="2024-08-10", min_matches=1)
    # 主队 xG: 2.0, 1.0（不含 0.5）→ avg_home_xg = 1.5
    assert abs(m.avg_home_xg - 1.5) < 1e-6, "xG 训练数据含未来比赛（数据泄露）！"


def test_xg_fit_max_date_boundary(tmp_db, insert_match_xg):
    """边界：max_date == 某比赛 date 时该比赛不进训练（严格 <）。"""
    insert_match_xg("TST", "2024-2025", "2024-08-01", "A", "B", 2.0, 1.0)
    insert_match_xg("TST", "2024-2025", "2024-08-08", "A", "B", 4.0, 1.0)
    m = XGPoissonModel(db=tmp_db).fit("TST", max_date="2024-08-08", min_matches=1)
    assert abs(m.avg_home_xg - 2.0) < 1e-6  # 只含 08-01 的 2.0


def test_xg_fit_no_match_xg_value_error(tmp_db):
    """无 match_xg 数据 → ValueError 含 build-xg 提示。"""
    try:
        XGPoissonModel(db=tmp_db).fit("TST", seasons=["2024-2025"])
        assert False, "应抛 ValueError"
    except ValueError as e:
        assert "build-xg" in str(e)


def test_xg_fit_seasons_only(tmp_db, insert_match_xg):
    """seasons 路径仅用指定赛季。"""
    insert_match_xg("TST", "2023-2024", "2023-08-01", "A", "B", 4.0, 0.5)
    insert_match_xg("TST", "2024-2025", "2024-08-01", "A", "B", 1.0, 0.5)
    m = XGPoissonModel(db=tmp_db).fit("TST", seasons=["2023-2024"], min_matches=1)
    assert abs(m.avg_home_xg - 4.0) < 1e-6  # 只用 2023-2024
