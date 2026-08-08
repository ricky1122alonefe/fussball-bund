"""match_xg 聚合测试。"""
from fussball_bund.storage.match_xg import build_match_xg
from fussball_bund.storage.team_map import upsert_mapping


def test_build_match_xg_basic(tmp_db, insert_match, insert_xg_match):
    """understat + map + matches → build 后 1 行，home_team 为 canonical。"""
    insert_match("TST", "2024-2025", "2024-08-17", "Arsenal", "Chelsea", 2, 0, "H")
    insert_xg_match("TST", "2024-2025", "2024-08-17", "Arsenal FC", "Chelsea FC", 2.5, 0.8, "m1")
    upsert_mapping(tmp_db, "understat", "Arsenal FC", "TST", "Arsenal")
    upsert_mapping(tmp_db, "understat", "Chelsea FC", "TST", "Chelsea")

    r = build_match_xg(tmp_db, "TST", "2024-2025")
    assert r["written"] == 1
    assert r["skipped_unmapped"] == 0

    rows = tmp_db.execute(
        "SELECT match_id, home_team, away_team, home_xg, away_xg FROM match_xg"
    )
    assert len(rows) == 1
    row = rows[0]
    assert row["home_team"] == "Arsenal"  # canonical，不是 "Arsenal FC"
    assert row["away_team"] == "Chelsea"
    assert abs(row["home_xg"] - 2.5) < 1e-6
    assert abs(row["away_xg"] - 0.8) < 1e-6
    assert row["match_id"] is not None  # 对齐了 matches.id


def test_build_match_xg_no_map(tmp_db, insert_xg_match):
    """无 map 时 written=0，不抛异常。"""
    insert_xg_match("TST", "2024-2025", "2024-08-01", "Team A", "Team B", 2.0, 1.0, "m1")
    r = build_match_xg(tmp_db, "TST", "2024-2025")
    assert r["written"] == 0
    assert r["skipped_unmapped"] == 1
    n = tmp_db.execute("SELECT COUNT(*) AS n FROM match_xg")[0]["n"]
    assert n == 0


def test_build_match_xg_partial_map(tmp_db, insert_xg_match):
    """主客任一未映射 → skipped_unmapped。"""
    insert_xg_match("TST", "2024-2025", "2024-08-01", "Arsenal FC", "Unknown FC", 2.0, 1.0, "m1")
    upsert_mapping(tmp_db, "understat", "Arsenal FC", "TST", "Arsenal")
    # Unknown FC 无映射
    r = build_match_xg(tmp_db, "TST", "2024-2025")
    assert r["written"] == 0
    assert r["skipped_unmapped"] == 1


def test_build_match_xg_idempotent(tmp_db, insert_match, insert_xg_match):
    """重复 build 不产生重复行（upsert）。"""
    insert_match("TST", "2024-2025", "2024-08-17", "Arsenal", "Chelsea", 2, 0, "H")
    insert_xg_match("TST", "2024-2025", "2024-08-17", "Arsenal FC", "Chelsea FC", 2.0, 0.5, "m1")
    upsert_mapping(tmp_db, "understat", "Arsenal FC", "TST", "Arsenal")
    upsert_mapping(tmp_db, "understat", "Chelsea FC", "TST", "Chelsea")

    build_match_xg(tmp_db, "TST", "2024-2025")
    build_match_xg(tmp_db, "TST", "2024-2025")  # 重复
    n = tmp_db.execute("SELECT COUNT(*) AS n FROM match_xg")[0]["n"]
    assert n == 1
