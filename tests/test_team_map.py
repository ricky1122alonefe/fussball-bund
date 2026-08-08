"""队名映射测试：归一化、resolve 读写、同日不串。"""
from fussball_bund.storage.team_map import (
    build_understat_mappings,
    normalize,
    resolve,
    upsert_mapping,
)


def test_normalize():
    assert normalize("Manchester United FC") == "manchester united"
    assert normalize("Arsenal AFC") == "arsenal"
    assert normalize("Brighton & Hove Albion") == "brighton hove albion"
    assert normalize("Wolves") == "wolves"


def test_resolve_to_canonical_alias(tmp_db):
    from fussball_bund.storage.team_map import resolve_to_canonical

    # football-data 历史里已有短名
    with tmp_db.transaction() as conn:
        conn.execute(
            "INSERT INTO matches(league_code,season,match_date,home_team,away_team,ft_result) "
            "VALUES ('EPL','2024-2025','2024-08-01','Man City','Arsenal','H')"
        )
    assert resolve_to_canonical(tmp_db, "EPL", "Manchester City", source="fbref") == "Man City"
    assert resolve_to_canonical(tmp_db, "EPL", "Wolverhampton Wanderers") == "Wolves"


def test_resolve_upsert(tmp_db):
    upsert_mapping(tmp_db, "understat", "Manchester United", "EPL", "Man United")
    assert resolve(tmp_db, "understat", "Manchester United", "EPL") == "Man United"
    assert resolve(tmp_db, "understat", "Unknown", "EPL") is None
    # upsert 覆盖
    upsert_mapping(tmp_db, "understat", "Manchester United", "EPL", "Man Utd")
    assert resolve(tmp_db, "understat", "Manchester United", "EPL") == "Man Utd"


def test_same_day_no_cross(tmp_db, insert_match, insert_xg_match):
    """同日两场不同对阵，映射不会串（不 LIMIT 1 盲取）。"""
    # football-data 同日两场
    insert_match("TST", "2024-2025", "2024-08-17", "Arsenal", "Chelsea", 2, 0, "H")
    insert_match("TST", "2024-2025", "2024-08-17", "Liverpool", "Man United", 1, 1, "D")
    # understat 同日两场（队名带后缀，确保归一化后能对齐）
    insert_xg_match("TST", "2024-2025", "2024-08-17", "Arsenal FC", "Chelsea FC", 2.0, 0.5, "m1")
    insert_xg_match("TST", "2024-2025", "2024-08-17", "Liverpool FC", "Man United", 1.0, 1.0, "m2")

    mappings = build_understat_mappings(tmp_db, "TST", "2024-2025")
    m = {x.source_name: x.canonical_name for x in mappings}
    # 不串：Arsenal FC -> Arsenal（不是 Liverpool）
    assert m.get("Arsenal FC") == "Arsenal"
    assert m.get("Chelsea FC") == "Chelsea"
    assert m.get("Liverpool FC") == "Liverpool"
    assert m.get("Man United") == "Man United"
