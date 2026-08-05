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
