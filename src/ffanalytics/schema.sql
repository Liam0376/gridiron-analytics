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
    source TEXT NOT NULL,           -- 'nflreadpy', 'sleeper', 'open-meteo'
    ran_at TEXT NOT NULL,           -- ISO8601, passed in by caller (no Date.now in workflows, but fine at runtime)
    success INTEGER NOT NULL,       -- 0/1
    error_message TEXT,
    PRIMARY KEY (source, ran_at)
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

-- Audit 22.0: these tables used AUTOINCREMENT PKs with UNIQUE constraints,
-- causing INSERT OR REPLACE to create new rowids (b-tree bloat, future FK
-- orphans). For fresh DBs, use composite PKs instead. Existing DBs need a
-- rebuild migration (deferred — no FKs reference these ids today).

CREATE TABLE IF NOT EXISTS rosters (
    season INTEGER NOT NULL,
    week INTEGER NOT NULL,
    data JSON NOT NULL,
    PRIMARY KEY (season, week)
);

CREATE TABLE IF NOT EXISTS player_stats (
    season INTEGER NOT NULL,
    week INTEGER NOT NULL,
    data JSON NOT NULL,
    PRIMARY KEY (season, week)
);

CREATE TABLE IF NOT EXISTS injury_status (
    season INTEGER NOT NULL,
    data JSON NOT NULL,
    PRIMARY KEY (season)
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
    season INTEGER NOT NULL,
    week INTEGER NOT NULL,
    kind TEXT NOT NULL,  -- 'trending' or 'injuries'
    data JSON NOT NULL,
    fetched_at TEXT NOT NULL,
    PRIMARY KEY (season, week, kind)
);

CREATE TABLE IF NOT EXISTS weather (
    lat REAL NOT NULL,
    lon REAL NOT NULL,
    game_time_iso TEXT NOT NULL,
    temp_f REAL,
    wind_mph REAL,
    precip_prob REAL,
    fetched_at TEXT NOT NULL,
    PRIMARY KEY (lat, lon, game_time_iso)
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

-- Player props (spec 2026-09-09): manually entered book lines. Manual entry
-- only — no odds feed ($0 constraint). why side in UNIQUE: over and under on
-- the same market/book are independent trackable positions.
CREATE TABLE IF NOT EXISTS prop_lines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id TEXT NOT NULL,
    season INTEGER NOT NULL,
    week INTEGER NOT NULL,
    market TEXT NOT NULL,   -- passing_yards, passing_tds, rushing_yards, receiving_yards, receptions, anytime_td
    side TEXT NOT NULL,     -- 'over'/'under' (normal) or 'yes'/'no' (anytime_td)
    line REAL,              -- book line; NULL for yes/no markets
    price REAL NOT NULL,    -- American price on `side`
    book TEXT NOT NULL DEFAULT 'manual',
    created_at TEXT NOT NULL,
    UNIQUE(player_id, season, week, market, side, book)
);

-- Props shadow dedupe (council vote 2026-09-09), partial to prop kinds +
-- non-unique so legacy rows (NULL players, repeated trade snapshots) can
-- never fail creation on old DBs. The prop-edge logger this served
-- (log_prop_edge_once) was deleted 2026-09-10 — kept per migration
-- discipline (additive only, never DROP); harmless on old rows.
CREATE INDEX IF NOT EXISTS idx_shadow_prop_dedupe
ON shadow_recommendations(kind, season, week, player_id)
WHERE kind LIKE 'prop:%';

-- Sleeper->GSIS id crosswalk for roster joins (start-sit/waiver/trade).
-- Derived cache, whole-table replaced per refresh; single global snapshot
-- (per-league DBs each hold their own copy).
CREATE TABLE IF NOT EXISTS sleeper_xwalk (
    sleeper_id TEXT PRIMARY KEY,
    gsis_id TEXT NOT NULL
);

-- P0 audit: per-source refresh history lookups (hub refresh-log, /ready checks)
-- why: refresh_log grows unbounded (one row per source per refresh); without
-- this index every ORDER BY ran_at DESC scan is a full table scan.
CREATE INDEX IF NOT EXISTS idx_refresh_log_src_time ON refresh_log(source, ran_at DESC);

-- Database-audit v8: shadow.count_logged/count_resolved (kind, kind+actual_
-- outcome) and rating_updates.py's season-scoped team_ratings read were full
-- table scans with no covering index.
CREATE INDEX IF NOT EXISTS idx_shadow_kind ON shadow_recommendations(kind);
CREATE INDEX IF NOT EXISTS idx_shadow_resolved
ON shadow_recommendations(kind, actual_outcome)
WHERE actual_outcome IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_team_ratings_season ON team_ratings(season);

-- Audit 22.0: player_stats is the most-queried table. The hub's common
-- pattern is ORDER BY season DESC, rowid DESC LIMIT 1 (latest season).
-- The UNIQUE(season, week) implicit index covers season filtering;
-- SQLite's natural rowid ordering handles the DESC scan.
-- No explicit rowid index needed — rowid can't be referenced by name
-- in index definitions on tables with composite (non-INTEGER) PKs.

-- Audit 22.0: sleeper_matchups WHERE week = ? — week is the 2nd column
-- in the (season, week, roster_id) PK; a dedicated week index avoids
-- scanning all-season rows for a single-week query.
CREATE INDEX IF NOT EXISTS idx_matchups_week ON sleeper_matchups(week);

-- Reliability audit v10: per-player per-week projection snapshots for
-- accuracy grading (DB1). Frozen at refresh time before games resolve.
CREATE TABLE IF NOT EXISTS projection_snapshots (
    season INTEGER NOT NULL,
    week INTEGER NOT NULL,
    player_id TEXT NOT NULL,
    position TEXT NOT NULL,
    projected_points REAL NOT NULL,
    projection_low REAL,
    projection_high REAL,
    snapped_at TEXT NOT NULL,
    PRIMARY KEY (season, week, player_id)
);

-- Market blend shadow v13: model + Sleeper market + blend points frozen
-- together per player-week, written only before that player's kickoff.
CREATE TABLE IF NOT EXISTS market_snapshots (
    season INTEGER NOT NULL,
    week INTEGER NOT NULL,
    player_id TEXT NOT NULL,
    position TEXT NOT NULL,
    team TEXT,
    model_points REAL NOT NULL,
    market_points REAL,
    blend_points REAL NOT NULL,
    w_model REAL NOT NULL,
    kickoff_utc TEXT NOT NULL,
    snapped_at TEXT NOT NULL,
    PRIMARY KEY (season, week, player_id)
);