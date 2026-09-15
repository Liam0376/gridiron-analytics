# Pipeline Reliability Audit

Date: 2026-09-15
Agent: Projections Pipeline Reliability

## Scope

Traced projection end-to-end: source ingest to features to model to stored value to hub/API output.

## Findings

### P1: Matchup clobber fix verified (Not a bug, VERIFIED)

The 2026-09-15 matchup clobber described in the task brief was already fixed in commit ca754c0.

Evidence:
- refresh.py:548-556 fetches all weeks 1-18, stamps `m["week"] = wk` per iteration
- refresh.py:1086 writes `m.get("week", week)` using per-row week field
- DB query: `SELECT season, week, COUNT(*), SUM(points) FROM sleeper_matchups GROUP BY season, week`
  shows week 1 = 12 rows / 1692.98 pts, weeks 2-18 = 12 rows / 0 pts each (correct)
- Regression test: `test_matchups_stored_per_week_not_clobbered` in tests/test_refresh.py:575

Residual risk: the `m.get("week", week)` fallback to `week` (current compute_nfl_week) would
silently stamp wrong weeks if Sleeper API returned matchups without a week field AND the loop
at line 552 failed to set it. Mitigate by removing the fallback (use `m["week"]` to crash loud).

### P2: player_stats overwrites week=0 blob every refresh (Medium)

refresh.py:1073-1078 writes `INSERT OR REPLACE INTO player_stats (season, week, data) VALUES (?, 0, ?)`.
The entire enriched player_stats list (all players, all stats + projections) goes into a single JSON blob.
Each refresh overwrites the previous blob. No per-player, per-week projection snapshot exists.

Impact: Cannot reproduce what was projected for week 1 once week 2's refresh runs.
The retention pruning (lines 1186-1207) keeps trailing 8 week-specific blobs, but the
week=0 "full season cache" is always overwritten.

Fix: Add a `projection_snapshots` table (season, week, player_id, projected_points, actual_points)
populated at refresh time, enabling retrospective accuracy grading.

### P3: Schedule cache drift (Low)

data/nfl_cache/schedule_2026.json is written at refresh.py:615-624 via atomic tmp->rename.
Hub reads this file for NFL slate display. The file is refreshed every POST /refresh.
Between refreshes, the file is stale. This is documented behavior (hub shows staleness dot).

### P4: Refresh job launchd reliability (Low)

scripts/refresh_job.sh runs via launchd at 7am daily. If the machine is asleep at 7am,
launchd fires it when the machine wakes. No retry on network failure beyond the per-source
isolation (refresh.py logs failures, continues with other sources).

Missing: no alert/notification when refresh fails. The hub shows "cold" staleness but
the user must open it to notice. Consider a launchd-aware failure notification (out of scope
for this audit, deferred).

### P5: Silent fallback on identity step failure (Medium)

refresh.py:706-731: if the weekly rosters or depth chart fetch fails, the code falls back to
a last-good JSON cache. If both the fetch AND the cache read fail, `_gsis_map` stays empty,
and all team patches fall through to the name-based fallback only. This is logged as a warning
but not surfaced to the user.

### P6: Matchup write should use m["week"] not m.get("week", week) (Low)

refresh.py:1086: `m.get("week", week)` has a fallback to the outer `week` variable.
The loop at 548-556 always sets `m["week"] = wk`, so the fallback never triggers in practice.
But removing the fallback would make a missing week field crash loudly instead of silently
writing with the wrong week.

## Hashtag Football Integration

Deferred to hashtag-research.md (research agent). Pipeline recommendation: nflverse covers
target_share, snap_share, carries, rushing workload, air_yards. Only slot_vs_perimeter,
cornerback coverage matchups, and consistency scores would be novel. Check robots.txt first.

## Refresh Integrity Proof

```sql
SELECT season, week, COUNT(*) as cnt, SUM(COALESCE(points, 0)) as pts
FROM sleeper_matchups GROUP BY season, week ORDER BY season, week;
```

Result (2026-09-15):
- 2026|wk1: 12 rows, pts=1692.98 (real Week 1 scores)
- 2026|wk2-18: 12 rows each, pts=0.00 (future games, correct)

No past week was clobbered. Week 1 retains its own scores.

```sql
SELECT season, week, COUNT(*) FROM player_stats GROUP BY season, week;
```

Result: 2025|wk0: 1 row, 2026|wk0: 1 row, 2026|wk1: 1 row.
player_stats uses single-blob design (one JSON row per (season, week)).
