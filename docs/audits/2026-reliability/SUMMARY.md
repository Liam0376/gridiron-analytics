# Reliability Audit Summary

Date: 2026-09-15
Branch: reliability-audit-2026

## Ranked Findings

### Critical

| ID | Finding | Agent | Measurable Outcome |
|----|---------|-------|--------------------|
| DB1 | No projection snapshot table for accuracy grading | Database | Enables weekly scorecard computation |
| SC1 | No accuracy scorecard script exists | Researcher | Weekly MAE/bias/Spearman/pairwise/CRPS tracked |

### High

| ID | Finding | Agent | Measurable Outcome |
|----|---------|-------|--------------------|
| P6 | Matchup write uses fallback m.get("week", week) | Pipeline | Remove fallback, crash loud on missing week |
| B8 | No parity test for interval factors | Backend | Prevents silent divergence between projection.py and decision.py |
| P2 | player_stats blob overwrites, no per-player snapshot | Pipeline | Projection history preserved for grading |

### Medium

| ID | Finding | Agent | Measurable Outcome |
|----|---------|-------|--------------------|
| S1 | QB interval coverage 33% at n=3 (2026 live) | Stats | Tracked via scorecard, improves as n grows |
| H4 | Hub vendored scoring duplication | Frontend | Tech debt, no current divergence |
| B5 | 40+ bonus stats not projected | Backend | Systematic underestimate (~0.5 pts/game for boom players) |
| P5 | Silent fallback on identity step failure | Pipeline | Add structured warning |

### Low

| ID | Finding | Agent | Measurable Outcome |
|----|---------|-------|--------------------|
| P3 | Schedule cache stale between refreshes | Pipeline | Documented, staleness dot exists |
| P4 | No refresh failure notification | Pipeline | Deferred (needs system integration) |
| S7 | Variance model is position-only | Stats | Future: per-player residuals |
| H6 | Weather badges placeholder | Frontend | Known, documented |

## Accuracy Scorecard Proposal

Built from researcher findings. Metrics, baselines, computation method:

| Metric | Baseline | How |
|--------|----------|-----|
| MAE (per-position) | QB 5.5-7.0, RB 5.0-5.2, WR 4.8-5.0, TE 3.5-4.0 | \|proj - actual\| |
| ME (Bias) | 0.0 | mean(proj - actual) |
| Spearman rho | 0.5-0.7 | Rank correlation per position |
| Pairwise % | 65-75% | Concordant pairs / total |
| PICP | 80% target | in-interval / n |
| CRPS | Lower is better | Empirical CDF method |
| Beat-consensus | Model MAE < Consensus MAE | Paired t-test |
| n | Report alongside all | Sample size |

Script: scripts/scorecard.py, no new dependencies (stdlib math + existing deps).

## Hashtag Football Integration Table

| Tool | Feature | nflverse Overlap | Leakage Risk | Value | Go/No-Go |
|------|---------|-----------------|--------------|-------|----------|
| Target Shares | target_share % | Full | None | Low | No-Go (blocked + have it) |
| Snap Shares | snap_pct | Full | None | Low | No-Go |
| CB Coverage | matchup adjust | None | Low (pre-game data) | High | No-Go (robots.txt blocks) |
| Slot/Perimeter | route split | Partial | Low | High | No-Go (robots.txt blocks) |
| Consistency | boom/bust | Derivable internally | None | Medium | Compute internally |
| All others | Various | Full/partial | N/A | Low | No-Go |

Decision (DECISIONS.md D3b): All Hashtag Football scraping blocked by robots.txt
(ClaudeBot: Disallow: /). Manual cross-checks only. Compute boom/bust internally.

## Agent Conflicts

**Expert vs Stats on QB intervals:** Expert says QB intervals too narrow (manager would
question Allen at 22.5 +/- 7.0). Stats confirms QB coverage is low (33% at n=3, 79% at
n=850 on 2025 holdout). Resolution: both agree. The 1.45x QB factor improves raw 58% to
displayed 79% but still undercoverages. Widths are frozen (correct decision for stability).
Track via scorecard PICP as more 2026 weeks complete. No width change warranted at n=3.

## Refresh Integrity Proof

```
SELECT season, week, COUNT(*), SUM(COALESCE(points, 0))
FROM sleeper_matchups GROUP BY season, week ORDER BY season, week;

2026|wk 1:  12 rows, pts_sum=1692.98  (real Week 1 scores, RETAINED)
2026|wk 2:  12 rows, pts_sum=0.00     (future, correct)
2026|wk 3:  12 rows, pts_sum=0.00     (future, correct)
...
2026|wk18:  12 rows, pts_sum=0.00     (future, correct)
```

No past week clobbered. Week 1 retains its own 12 rows and real scores.
Matchup clobber fix verified in commit ca754c0 with regression test
test_matchups_stored_per_week_not_clobbered (tests/test_refresh.py:575).

## Prioritized Fix List

1. **scripts/scorecard.py** - Accuracy scorecard script (SC1, Critical)
   Outcome: Weekly MAE/bias/Spearman/pairwise/PICP/CRPS tracked per position

2. **projection_snapshots table** - Schema + populate at refresh (DB1, Critical)
   Outcome: Per-player per-week projection history for grading

3. **Matchup write hardening** - Remove m.get fallback (P6, High)
   Outcome: Missing week field crashes loud instead of silent wrong-week write

4. **Interval factor parity test** - Assert projection.py == decision.py (B8, High)
   Outcome: Prevents silent factor divergence

5. **Refresh integrity assertion** - Post-refresh per-week row check (Pipeline, High)
   Outcome: Any clobber detected and reported as Critical at runtime
