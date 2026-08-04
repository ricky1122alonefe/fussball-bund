"""calibrate-scan 测试：grid 产出含 raw + 多个 α，且有 brier 字段。"""
from fussball_bund.analysis.calibrate_scan import run_calibrate_scan


def test_calibrate_scan_has_raw_and_alphas(tmp_db, insert_match):
    """grid 产出含 raw + 3 个 α，共 4 行，每行有 brier 字段。"""
    # 构造足够历史让 walk-forward 能跑（8 场，3 队轮转）
    teams_cycle = [("A", "B"), ("C", "A"), ("B", "C")]
    for i in range(8):
        home, away = teams_cycle[i % 3]
        hg, ag = i % 3, (i + 1) % 3
        res = "H" if hg > ag else ("D" if hg == ag else "A")
        insert_match("TST", "2024-2025", f"2024-08-{i + 1:02d}", home, away, hg, ag, res)

    scan = run_calibrate_scan(
        "TST", "2024-2025", model_name="poisson",
        alphas=(0.3, 0.4, 0.5), db=tmp_db,
    )
    labels = [r["label"] for r in scan["rows"]]
    assert "raw" in labels
    assert "α=0.3" in labels
    assert "α=0.4" in labels
    assert "α=0.5" in labels
    assert len(scan["rows"]) == 4  # raw + 3 α
    assert all("brier" in r for r in scan["rows"])
    # Brier 为有限非负数
    assert all(r["brier"] == r["brier"] and r["brier"] >= 0 for r in scan["rows"])


def test_calibrate_scan_sorted_by_brier(tmp_db, insert_match):
    """结果按 Brier 升序排列（主排序字段）。"""
    teams_cycle = [("A", "B"), ("C", "A"), ("B", "C")]
    for i in range(8):
        home, away = teams_cycle[i % 3]
        hg, ag = i % 3, (i + 1) % 3
        res = "H" if hg > ag else ("D" if hg == ag else "A")
        insert_match("TST", "2024-2025", f"2024-08-{i + 1:02d}", home, away, hg, ag, res)

    scan = run_calibrate_scan(
        "TST", "2024-2025", model_name="poisson",
        alphas=(0.3, 0.5), db=tmp_db,
    )
    briers = [r["brier"] for r in scan["rows"]]
    assert briers == sorted(briers)
