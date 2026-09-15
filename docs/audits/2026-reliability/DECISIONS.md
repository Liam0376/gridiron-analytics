# Autonomous Decisions Log

Decisions made without Liam's confirmation during the 2026-09-15 reliability audit.

## D1: Matchup clobber assessment

**Question:** Is the 2026-09-15 matchup clobber still present?
**Options:** (a) Bug still exists, needs fix. (b) Already fixed, verify with evidence.
**Picked:** (b) Already fixed.
**Why:** Code at refresh.py:548-556 sets `m["week"] = wk` per loop iteration.
Write at refresh.py:1086 uses `m.get("week", week)` with per-row week.
DB query confirms: week 1 has 12 rows/1692.98 pts, weeks 2-18 have 12 rows/0 pts each.
Zero points for future weeks is correct (games not played). Commit ca754c0 was the fix.
Test `test_matchups_stored_per_week_not_clobbered` guards against regression.

## D2: player_stats blob design

**Question:** Is the single-blob-per-(season,week) design for player_stats a data loss risk?
**Options:** (a) Normalize to per-player rows. (b) Keep blob, add snapshot table. (c) Keep blob, accept limit.
**Picked:** (b) Add a projection_snapshots table for weekly grading, keep existing blob.
**Why:** Normalizing player_stats is a large migration with no immediate accuracy gain.
A lightweight snapshot table (season, week, player_id, projected_points, actual_points)
written at refresh time enables the accuracy scorecard without touching existing schema.
Additive migration only.

## D3: Hashtag Football scraping

**Question:** Should we scrape Hashtag Football for model features?
**Options:** (a) Scrape. (b) Manual cross-check only. (c) Skip entirely.
**Picked:** Deferred to D3b after robots.txt check by research agent.
**Why:** Must check robots.txt and ToS first. nflverse covers target_share, snap_share,
carries already. Only features nflverse LACKS would justify scraping.

## D4: Scorecard baseline choice

**Question:** What baseline should the accuracy scorecard compare against?
**Options:** (a) FantasyPros consensus only. (b) Sleeper market projections only. (c) Both.
**Picked:** (c) Both, since both are already fetched during refresh.
**Why:** comparison.py already joins model vs Sleeper market + FPros ECR.
Using both baselines costs zero extra API calls.

## D5: Hub vendored scoring duplication

**Question:** Should we deduplicate hub/server.py's vendored DEFAULT_SCORING now?
**Options:** (a) Import from ffanalytics (isolation lifted). (b) Keep vendored, flag as debt.
**Picked:** (b) Keep vendored, flag as Medium.
**Why:** architecture.md says isolation was lifted 2026-09-15 but "existing vendored mirrors
stay until refactored, no flag day." Changing the import pattern is a separate refactor
with its own test pass, not a reliability fix. Flag for later.

## D6: Interval width factors duplication

**Question:** projection.py and decision.py both define POS_WIDTH_FACTORS. Deduplicate?
**Options:** (a) Move to config.py, import everywhere. (b) Keep duplicated with parity test.
**Picked:** (b) Keep with parity test.
**Why:** Both files reference "parity test" and "INTERVAL_FACTORS_VERSION = 1".
The duplication is intentional (decision.py is the start/sit path, projection.py
is the projection path). A parity test exists or should exist. Verify and add if missing.

## D7: No new dependencies for scorecard

**Question:** Should the scorecard use scipy for statistical tests?
**Options:** (a) Add scipy. (b) Implement t-test/correlation from scratch. (c) Use only stdlib + existing deps.
**Picked:** (c) Use stdlib math + existing conformal.py. Spearman via rank sort (stdlib).
**Why:** $0 forever, vanilla by default. scipy is 150MB for two functions.
t-test and Spearman are 20 lines each in pure Python.

## D8: Matchup write hardening (P6)

**Question:** Remove `m.get("week", week)` fallback at refresh.py matchup write?
**Picked:** Yes. Changed to `m["week"]` — crash loud on missing week field.
**Why:** The all-weeks fetch (ca754c0) always sets `m["week"] = wk`. A missing
week field means a code regression, not missing data — crash is the correct behavior.
Regression test: test_matchup_missing_week_key_raises.

## D9: Projection snapshots table (DB1)

**Question:** Schema for projection_snapshots?
**Picked:** PK(season, week, player_id), columns: position, projected_points,
projection_low, projection_high, snapped_at. Migration v10 (additive).
**Why:** Enables per-week accuracy grading without modifying the existing player_stats
blob. INSERT OR REPLACE at refresh time, same transaction as player_stats write.

## D10: Refresh integrity assertion

**Question:** How to detect matchup clobber at runtime?
**Picked:** Post-write assertion checking row count (12) per (season, week).
Logs CRITICAL on wrong count, WARNING on zero-points past week.
**Why:** Defense in depth — test prevents the bug, assertion detects it at runtime.
