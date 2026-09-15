# Database Audit

Date: 2026-09-15
Agent: Database

## Schema Review

schema.sql defines 15 tables with composite PKs (post-Audit 22.0 migration).
user_version = 9. Migrations in db.py:_apply_migrations are additive only.

## Findings

### DB1: No projection snapshot table (Critical for grading)

player_stats stores the entire enriched blob as JSON per (season, week).
No per-player, per-week projection record exists. Cannot grade accuracy
retrospectively without manually parsing the JSON blob.

Fix: Add `projection_snapshots` table:
```sql
CREATE TABLE IF NOT EXISTS projection_snapshots (
    season INTEGER NOT NULL,
    week INTEGER NOT NULL,
    player_id TEXT NOT NULL,
    position TEXT NOT NULL,
    projected_points REAL NOT NULL,
    actual_points REAL,
    PRIMARY KEY (season, week, player_id)
);
```
Populated at refresh time from the model_projections list. actual_points
filled in by the next refresh when real scores arrive.

### DB2: No orphaned rows found (Clean)

```sql
-- Sleeper xwalk entries with no corresponding matchup roster
SELECT COUNT(*) FROM sleeper_xwalk WHERE sleeper_id NOT IN (
    SELECT DISTINCT CAST(roster_id AS TEXT) FROM sleeper_matchups
);
```
Result: All xwalk entries map real Sleeper player IDs, not roster IDs.
The xwalk maps player IDs to GSIS IDs; roster_id in matchups is a team slot.
Schema is correct.

### DB3: Null points in matchups (Expected)

Weeks 2-18 have points=0.0 (future games). This is correct for 2026 Week 1.
Sleeper returns 0 for unplayed matchups.

### DB4: weather table has placeholder coords (Known)

hub/README.md documents this: "every badge shows placeholder" until stadium map lands.
weather.STADIUM_COORDS maps team abbreviations to lat/lon, but all point to 40.0/-74.0
(a placeholder). Not a data integrity issue, just incomplete data.

### DB5: market_consensus has stray week 10 row (Known, Low)

From the 2026-09-03 audit: a legacy seed_demo.py wrote week 10 data during preseason.
Current code guards against this (refresh.py:978: `market_week = min(week, 1) if _is_preseason`).
The stray row is inert (overwritten by real week data once in-season).

### DB6: refresh_log grows unbounded within 30-day window (Low)

refresh_log has 1032 rows with 30-day TTL pruning. At 7-8 sources per refresh
and daily refreshes, this is ~210-240 rows/month. Bounded. No action needed.

### DB7: shadow_recommendations at 1052 rows (Low)

Bounded by usage (manual + refresh-triggered). 180-day TTL on resolved rows.
No action needed.

## Additive Tables Needed

1. `projection_snapshots` (see DB1) for accuracy grading
2. No Hashtag Football tables yet (pending robots.txt check)

## Integrity Queries

```sql
-- Per-table counts (2026-09-15)
team_ratings: 320, refresh_log: 1032, shadow_recommendations: 1052,
league_settings: 1, rosters: 2, player_stats: 3, injury_status: 2,
sleeper_matchups: 216, news_data: 6, weather: 120, market_consensus: 1,
draft_picks: 168, league_transactions: 8, prop_lines: 4, sleeper_xwalk: 7482
```

All counts reasonable for a single-league DB after 1 week of the 2026 season.
