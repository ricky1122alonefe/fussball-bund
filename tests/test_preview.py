"""preview 测试：未来场预测 + 有/无赔率 + 无未来场不崩。"""
from datetime import datetime, timedelta

from fussball_bund.analysis.preview import format_markdown, generate_preview


def _future_date(offset: int = 1) -> str:
    return (datetime.now() + timedelta(days=offset)).strftime("%Y-%m-%d")


def _seed_completed(insert_match, n: int = 8):
    """插入 n 场完赛用于拟合（3 队轮转）。"""
    teams_cycle = [("A", "B"), ("C", "A"), ("B", "C")]
    for i in range(n):
        home, away = teams_cycle[i % 3]
        hg, ag = i % 3, (i + 1) % 3
        res = "H" if hg > ag else ("D" if hg == ag else "A")
        insert_match("TST", "2024-2025", f"2024-08-{i + 1:02d}", home, away, hg, ag, res)


def test_preview_with_odds(tmp_db, insert_match):
    """2 场未来（有赔率）+ 8 场完赛 → preview 出 2 行，有概率有赔率。"""
    _seed_completed(insert_match)
    # insert_match 自动写入 opening+closing 赔率
    insert_match("TST", "2024-2025", _future_date(1), "A", "B", None, None, None)
    insert_match("TST", "2024-2025", _future_date(2), "C", "A", None, None, None)

    result = generate_preview("TST", days=7, model_name="poisson", db=tmp_db)
    assert result.n_matches == 2
    assert all(m.p_home >= 0 and m.p_draw >= 0 and m.p_away >= 0 for m in result.matches)
    # insert_match 写入了 Pinnacle opening/closing 赔率
    assert all(m.has_odds for m in result.matches)
    assert result.n_no_odds == 0

    md = format_markdown(result)
    assert "赛前关注清单" in md
    assert "A vs B" in md
    assert "C vs A" in md
    assert "盘口" in md


def test_preview_no_odds(tmp_db):
    """未来场无赔率 → 标「无盘口」，不伪造 edge。"""
    # 直接插比赛不插赔率
    with tmp_db.transaction() as conn:
        for i in range(8):
            home, away = [("A", "B"), ("C", "A"), ("B", "C")][i % 3]
            hg, ag = i % 3, (i + 1) % 3
            res = "H" if hg > ag else ("D" if hg == ag else "A")
            conn.execute(
                "INSERT INTO matches(league_code,season,match_date,home_team,away_team,"
                "ft_home_goals,ft_away_goals,ft_result) VALUES (?,?,?,?,?,?,?,?)",
                ("TST", "2024-2025", f"2024-08-{i + 1:02d}", home, away, hg, ag, res),
            )
        conn.execute(
            "INSERT INTO matches(league_code,season,match_date,home_team,away_team) "
            "VALUES (?,?,?,?,?)",
            ("TST", "2024-2025", _future_date(1), "A", "B"),
        )

    result = generate_preview("TST", days=7, model_name="poisson", db=tmp_db)
    assert result.n_matches == 1
    assert result.n_no_odds == 1
    assert not result.matches[0].has_odds

    md = format_markdown(result)
    assert "无盘口" in md


def test_preview_no_future_matches(tmp_db, insert_match):
    """无未来场 → 不崩，退出码 0 等效（无异常），文案提示。"""
    _seed_completed(insert_match)

    result = generate_preview("TST", days=7, model_name="poisson", db=tmp_db)
    assert result.n_matches == 0
    assert any("未来场为零" in w or "无未来场" in w for w in result.warnings)

    md = format_markdown(result)
    assert "未来场为零" in md or "无未来场" in md
