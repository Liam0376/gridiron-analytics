# Reliability Audit — Final Report

Date: 2026-09-15
Branch: reliability-audit-2026
Commits: ca754c0 (matchup clobber fix, pre-audit) → fe29cf5 (audit + fixes)

## What shipped

| Fix | File(s) | Test(s) | Finding |
|-----|---------|---------|---------|
| Accuracy scorecard | scripts/scorecard.py | tests/test_scorecard.py (13 tests) | SC1 |
| Projection snapshots table | schema.sql, db.py (migration v10), refresh.py | test_projection_snapshots_written | DB1 |
| Matchup write hardening | refresh.py:1104 | test_matchup_missing_week_key_raises | P6 |
| Interval factor parity test | tests/test_interval_parity.py (2 tests) | self | B8 |
| Refresh integrity assertion | refresh.py:1327-1345 | test_integrity_assertion_logs_on_wrong_count | Pipeline |
| 7 audit reports + SUMMARY | docs/audits/2026-reliability/*.md | n/a (documentation) | All |

## Before/after

| Metric | Before | After |
|--------|--------|-------|
| Tests | 256 pass, 4 skip | 274 pass, 4 skip |
| Matchup write safety | Fallback m.get("week", week) | Crash-loud m["week"] |
| Projection history | None (blob overwrites) | projection_snapshots table per player per week |
| Accuracy tracking | Ad-hoc backtest scripts only | Structured scorecard (MAE/ME/Spearman/PW%/PICP/CRPS) |
| Matchup clobber detection | Test only | Test + runtime integrity assertion |
| Interval factor divergence risk | No guard | Parity test asserts projection.py == decision.py |

## Scorecard baseline (2025 holdout)

No projected_points stored in 2025 blob (historical data fetched as actuals only).
Production freeze gate numbers (stat_projector.py header):
- MAE: 4.563, Corr: 0.648, Pairwise: 74.1% (n=10,351, weeks 4-18, 2024-2025)

Scorecard will produce live numbers once 2026 weeks complete and actual_points
populate in market_consensus, or via projection_snapshots.

## Refresh integrity proof

```sql
SELECT week, COUNT(*), SUM(COALESCE(points, 0))
FROM sleeper_matchups WHERE season=2026 GROUP BY week;
-- week 1: 12 rows, 1692.98 pts (real scores retained)
-- weeks 2-18: 12 rows each, 0 pts (future, correct)
```

## What's deferred

| Item | Why | When |
|------|-----|------|
| Hub vendored scoring dedup (H4/D5) | Architecture says "no flag day" | Separate refactor |
| Refresh failure notification (P4) | Needs system integration (macOS notification or email) | When daily refresh stabilizes |
| Boom/bust consistency score | Needs multi-week data | After week 4 |
| Beat-consensus metric | Needs actual_points in market_consensus | After week 1 resolves |
| Calibration slope metric | Needs projection_snapshots data | After week 2+ |

## Review commands

```bash
# View diff from main
git diff main...reliability-audit-2026

# Run full test suite
SLEEPER_LEAGUE_ID=test .venv/bin/pytest -q

# Run scorecard (2026 week N, once actuals populated)
.venv/bin/python scripts/scorecard.py --season 2026 --week 1

# Check DB integrity
sqlite3 data/fantasy.db "SELECT week, COUNT(*), SUM(COALESCE(points,0)) FROM sleeper_matchups WHERE season=2026 GROUP BY week"

# Verify projection_snapshots table exists
sqlite3 data/fantasy.db ".schema projection_snapshots"
```

## Decisions

10 autonomous decisions logged in DECISIONS.md (D1-D10). Key calls:
- D1: Matchup clobber already fixed (evidence: DB query + test)
- D2: Add snapshot table, not normalize player_stats
- D3/D3b: No Hashtag Football scraping (robots.txt blocks all)
- D7: No new dependencies ($0 forever)
- D8: Crash-loud on missing week (defense in depth)
