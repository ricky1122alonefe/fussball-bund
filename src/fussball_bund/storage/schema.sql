-- fussball-bund 数据库表结构
-- 存储：比赛基本信息 / 比赛统计 / 三类赔率（1X2、大小球、亚盘）

CREATE TABLE IF NOT EXISTS matches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    league_code TEXT NOT NULL,
    season TEXT NOT NULL,
    match_date TEXT,
    match_time TEXT,
    home_team TEXT NOT NULL,
    away_team TEXT NOT NULL,
    ht_home_goals INTEGER,
    ht_away_goals INTEGER,
    ht_result TEXT,
    ft_home_goals INTEGER,
    ft_away_goals INTEGER,
    ft_result TEXT,
    referee TEXT,
    UNIQUE(league_code, season, match_date, home_team, away_team)
);

CREATE TABLE IF NOT EXISTS match_stats (
    match_id INTEGER PRIMARY KEY,
    home_shots INTEGER, away_shots INTEGER,
    home_shots_on_target INTEGER, away_shots_on_target INTEGER,
    home_fouls INTEGER, away_fouls INTEGER,
    home_corners INTEGER, away_corners INTEGER,
    home_yellow INTEGER, away_yellow INTEGER,
    home_red INTEGER, away_red INTEGER,
    FOREIGN KEY(match_id) REFERENCES matches(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS odds_1x2 (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id INTEGER NOT NULL,
    bookmaker TEXT NOT NULL,
    period TEXT NOT NULL,        -- opening / closing
    home REAL, draw REAL, away REAL,
    UNIQUE(match_id, bookmaker, period),
    FOREIGN KEY(match_id) REFERENCES matches(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS odds_totals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id INTEGER NOT NULL,
    bookmaker TEXT NOT NULL,
    period TEXT NOT NULL,
    line REAL,
    over REAL, under REAL,
    UNIQUE(match_id, bookmaker, period, line),
    FOREIGN KEY(match_id) REFERENCES matches(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS odds_asian_handicap (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id INTEGER NOT NULL,
    bookmaker TEXT NOT NULL,
    period TEXT NOT NULL,
    handicap REAL,
    home REAL, away REAL,
    UNIQUE(match_id, bookmaker, period, handicap),
    FOREIGN KEY(match_id) REFERENCES matches(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_matches_date ON matches(match_date);
CREATE INDEX IF NOT EXISTS idx_matches_league_season ON matches(league_code, season);
CREATE INDEX IF NOT EXISTS idx_odds_match ON odds_1x2(match_id);

-- 采集日志（记录每次运行，便于追踪数据新鲜度）
CREATE TABLE IF NOT EXISTS collection_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    collector TEXT NOT NULL,
    league_code TEXT,
    season TEXT,
    status TEXT NOT NULL,        -- success / partial / failed
    detail TEXT,
    run_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- 队名映射：统一各数据源队名到 football-data canonical_name
-- 堵住 xG 同日盲匹配（LIMIT 1 串队）
CREATE TABLE IF NOT EXISTS team_name_map (
    source TEXT NOT NULL,           -- understat | fbref | clubelo | odds_api | football_data
    source_name TEXT NOT NULL,
    league_code TEXT NOT NULL,
    canonical_name TEXT NOT NULL,   -- 统一用 football-data 队名
    UNIQUE(source, source_name, league_code)
);
CREATE INDEX IF NOT EXISTS idx_team_map_lookup ON team_name_map(source, league_code);

-- match 级 xG 聚合表（每场一行，canonical 队名，供模型/回测直接读，避免扫全表射门）
CREATE TABLE IF NOT EXISTS match_xg (
    match_id INTEGER,                 -- 能对齐 matches.id 则填，否则 NULL
    league_code TEXT NOT NULL,
    season TEXT NOT NULL,
    match_date TEXT,
    home_team TEXT NOT NULL,           -- canonical = football-data 名
    away_team TEXT NOT NULL,
    home_xg REAL,
    away_xg REAL,
    source TEXT DEFAULT 'understat',
    UNIQUE(league_code, season, match_date, home_team, away_team)
);
CREATE INDEX IF NOT EXISTS idx_match_xg_league_season ON match_xg(league_code, season);
CREATE INDEX IF NOT EXISTS idx_match_xg_date ON match_xg(match_date);

-- ============ 竞彩足球（500.com 数据源） ============

-- 竞彩在售场次（每次 poll upsert）
CREATE TABLE IF NOT EXISTS jingcai_matches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    match_num TEXT NOT NULL UNIQUE,     -- 竞彩编号，如 周一001
    fixture_id TEXT,                     -- 500.com 分析 ID
    kickoff TEXT,                        -- 开赛时间 ISO
    league_name TEXT,                    -- 联赛名（500 展示）
    home_team TEXT,
    away_team TEXT,
    sell_status TEXT DEFAULT '在售',
    handicap INTEGER,                    -- 让球数（rqspf 用）
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_jc_matches_num ON jingcai_matches(match_num);

-- 竞彩赔率快照（每次 poll 追加一行，保留历史变动）
CREATE TABLE IF NOT EXISTS jingcai_odds (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    match_num TEXT NOT NULL,
    market TEXT NOT NULL,               -- spf | rqspf
    line INTEGER,                       -- 让球数（spf 为 NULL）
    sp_home REAL,
    sp_draw REAL,
    sp_away REAL,
    source TEXT DEFAULT '500',
    ts TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_jc_odds_num ON jingcai_odds(match_num);
CREATE INDEX IF NOT EXISTS idx_jc_odds_ts ON jingcai_odds(ts);
