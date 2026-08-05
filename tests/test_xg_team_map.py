"""XGPoissonModel 队名解析测试：走 team_name_map、不串队、无 map 不挂。"""
from fussball_bund.analysis.xg_model import XGPoissonModel
from fussball_bund.storage.team_map import upsert_mapping


def test_xg_fit_uses_team_map_no_cross(tmp_db, insert_match, insert_xg_match):
    """fit 通过 team_name_map 解析队名，同日两场不串，强度按 canonical 名归集。"""
    # football-data 同日两场
    insert_match("TST", "2024-2025", "2024-08-17", "Arsenal", "Chelsea", 2, 0, "H")
    insert_match("TST", "2024-2025", "2024-08-17", "Liverpool", "Man United", 1, 1, "D")
    # understat 同日两场（understat 名，与 football-data 不同写法）
    insert_xg_match("TST", "2024-2025", "2024-08-17", "Arsenal FC", "Chelsea FC", 3.0, 0.5, "m1")
    insert_xg_match("TST", "2024-2025", "2024-08-17", "Liverpool FC", "Man United", 2.0, 1.0, "m2")
    # 映射表
    upsert_mapping(tmp_db, "understat", "Arsenal FC", "TST", "Arsenal")
    upsert_mapping(tmp_db, "understat", "Chelsea FC", "TST", "Chelsea")
    upsert_mapping(tmp_db, "understat", "Liverpool FC", "TST", "Liverpool")
    upsert_mapping(tmp_db, "understat", "Man United", "TST", "Man United")

    m = XGPoissonModel(db=tmp_db).fit("TST", seasons=["2024-2025"], min_matches=1)
    # 强度按 canonical 名归集，不应出现 understat 名
    assert "Arsenal" in m.home_attack
    assert "Arsenal FC" not in m.home_attack
    assert "Liverpool" in m.home_attack
    assert "Liverpool FC" not in m.home_attack
    # Arsenal 主场 xG=3.0（高于均值 2.5），强度 > 1
    assert m.home_attack["Arsenal"] > 1.0
    # 不串：Arsenal 强度来自 Arsenal FC 的数据，不是 Liverpool FC
    assert m.home_attack["Arsenal"] != m.home_attack.get("Liverpool")


def test_xg_fit_no_map_uses_raw_name_no_crash(tmp_db, insert_xg_match):
    """无 team_name_map 时回退原样队名，不挂 TypeError，并 warning。"""
    insert_xg_match("TST", "2024-2025", "2024-08-01", "Team A", "Team B", 2.0, 1.0, "m1")
    # 不 apply 任何映射
    m = XGPoissonModel(db=tmp_db).fit("TST", seasons=["2024-2025"], min_matches=1)
    assert m._fitted
    # 回退原样队名，强度按 understat 名
    assert "Team A" in m.home_attack


def test_xg_fit_max_date_uses_team_map(tmp_db, insert_match, insert_xg_match):
    """max_date 路径也走 team_name_map（两条 fit 路径都生效）。"""
    insert_match("TST", "2024-2025", "2024-08-01", "Arsenal", "Chelsea", 2, 0, "H")
    insert_xg_match("TST", "2024-2025", "2024-08-01", "Arsenal FC", "Chelsea FC", 2.0, 0.5, "m1")
    upsert_mapping(tmp_db, "understat", "Arsenal FC", "TST", "Arsenal")
    upsert_mapping(tmp_db, "understat", "Chelsea FC", "TST", "Chelsea")

    m = XGPoissonModel(db=tmp_db).fit("TST", max_date="2024-08-02", min_matches=1)
    assert "Arsenal" in m.home_attack
    assert "Arsenal FC" not in m.home_attack
