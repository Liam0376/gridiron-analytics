CREATE TABLE IF NOT EXISTS team_ratings (
    team TEXT NOT NULL,
    position_group TEXT NOT NULL,  -- 'overall', 'vs_rb', 'vs_wr_slot', 'vs_te', etc.
    rating REAL NOT NULL,
    rating_deviation REAL NOT NULL,
    last_updated_week INTEGER NOT NULL,
    season INTEGER NOT NULL,
    PRIMARY KEY (team, position_group, season)
);

CREATE TABLE IF NOT EXISTS refresh_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,           -- 'nflreadpy', 'sleeper', 'open-meteo'
    ran_at TEXT NOT NULL,           -- ISO8601, passed in by caller (no Date.now in workflows, but fine at runtime)
    success INTEGER NOT NULL,       -- 0/1
    error_message TEXT
);

CREATE TABLE IF NOT EXISTS shadow_recommendations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,             -- 'start_sit', 'waiver', 'trade'
    season INTEGER NOT NULL,
    week INTEGER NOT NULL,
    player_id TEXT,
    recommendation TEXT NOT NULL,   -- JSON blob: inputs + output
    logged_at TEXT NOT NULL,
    actual_outcome TEXT             -- filled in later by refresh job; JSON or NULL
);

CREATE TABLE IF NOT EXISTS league_settings (
    season INTEGER PRIMARY KEY,
    data JSON NOT NULL
);

CREATE TABLE IF NOT EXISTS rosters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    season INTEGER NOT NULL,
    week INTEGER NOT NULL,
    data JSON NOT NULL,
    UNIQUE(season, week)
);

CREATE TABLE IF NOT EXISTS player_stats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    season INTEGER NOT NULL,
    week INTEGER NOT NULL,
    data JSON NOT NULL,
    UNIQUE(season, week)
);

CREATE TABLE IF NOT EXISTS injury_status (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    season INTEGER NOT NULL,
    data JSON NOT NULL,
    UNIQUE(season)
);

CREATE TABLE IF NOT EXISTS sleeper_matchups (
    season INTEGER NOT NULL,
    week INTEGER NOT NULL,
    roster_id INTEGER NOT NULL,
    matchup_id INTEGER NOT NULL,
    points REAL,
    starters TEXT,
    PRIMARY KEY (season, week, roster_id)
);

CREATE TABLE IF NOT EXISTS news_data (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    season INTEGER NOT NULL,
    week INTEGER NOT NULL,
    kind TEXT NOT NULL,  -- 'trending' or 'injuries'
    data JSON NOT NULL,
    fetched_at TEXT NOT NULL,
    UNIQUE(season, week, kind)
);

CREATE TABLE IF NOT EXISTS weather (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    lat REAL NOT NULL,
    lon REAL NOT NULL,
    game_time_iso TEXT NOT NULL,
    temp_f REAL,
    wind_mph REAL,
    precip_prob REAL,
    fetched_at TEXT NOT NULL,
    UNIQUE(lat, lon, game_time_iso)
);

CREATE TABLE IF NOT EXISTS market_consensus (
    season INTEGER NOT NULL,
    week INTEGER NOT NULL,
    data JSON NOT NULL,
    fetched_at TEXT NOT NULL,
    PRIMARY KEY (season, week)
);

CREATE TABLE IF NOT EXISTS draft_picks (
    season INTEGER NOT NULL,
    player_id TEXT NOT NULL,
    roster_id INTEGER NOT NULL,
    picked_by TEXT,
    amount REAL,
    metadata JSON,
    PRIMARY KEY (season, player_id)
);

CREATE TABLE IF NOT EXISTS league_transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    season INTEGER NOT NULL,
    week INTEGER NOT NULL,
    transaction_id TEXT UNIQUE NOT NULL,
    kind TEXT NOT NULL,
    data JSON NOT NULL,
    created_at TEXT NOT NULL
);