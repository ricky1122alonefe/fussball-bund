"""model-compare 测试：2 个模型出 2 行且有 brier，按 Brier 升序。"""
from fussball_bund.analysis.model_compare import run_model_compare


def _seed_matches(insert_match):
    """构造足够历史让 walk-forward 能跑（8 场，3 队轮转）。"""
    teams_cycle = [("A", "B"), ("C", "A"), ("B", "C")]
    for i in range(8):
        home, away = teams_cycle[i % 3]
        hg, ag = i % 3, (i + 1) % 3
        res = "H" if hg > ag else ("D" if hg == ag else "A")
        insert_match("TST", "2024-2025", f"2024-08-{i + 1:02d}", home, away, hg, ag, res)


def test_model_compare_two_models_has_brier(tmp_db, insert_match):
    """2 个模型出 2 行，每行有 brier 字段（有限非负）。"""
    _seed_matches(insert_match)
    compare = run_model_compare(
        "TST", "2024-2025", models=("poisson", "dixoncoles"), db=tmp_db,
    )
    models = [r["model"] for r in compare["rows"]]
    assert "poisson" in models
    assert "dixoncoles" in models
    assert len(compare["rows"]) == 2
    assert all("brier" in r for r in compare["rows"])
    assert all(r["brier"] == r["brier"] and r["brier"] >= 0 for r in compare["rows"])


def test_model_compare_sorted_by_brier(tmp_db, insert_match):
    """结果按 Brier 升序排列（主排序字段）。"""
    _seed_matches(insert_match)
    compare = run_model_compare(
        "TST", "2024-2025", models=("poisson", "dixoncoles"), db=tmp_db,
    )
    briers = [r["brier"] for r in compare["rows"]]
    assert briers == sorted(briers)


def test_model_compare_unknown_model_raises(tmp_db, insert_match):
    """未知模型应 ValueError。"""
    _seed_matches(insert_match)
    import pytest

    with pytest.raises(ValueError):
        run_model_compare(
            "TST", "2024-2025", models=("poisson", "bogus"), db=tmp_db,
        )
