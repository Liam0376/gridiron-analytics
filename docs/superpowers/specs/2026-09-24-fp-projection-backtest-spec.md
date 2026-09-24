# Spec: FantasyPros market-projection accuracy backtest

## Why

The FantasyPros historical dump (data/fantasypros_dump/, flattened into
fp.sqlite by scripts/fp_build_db.py) gives 2012-2026 weekly market
projections with full box-score detail (pass/rush/rec stat lines), not just
ECR ranks. backtest_ecr.py (this session, commit 829b143) already measured
rank agreement; this spec measures point-level accuracy — does FantasyPros'
own market projection, scored under our exact league rules, beat, tie, or
lose to stat_projector.py on the same production gate.

## Gate (pre-registered, no changes after seeing results)

Production freeze baseline (true scoring, 2024-2025 weeks 4-18, n=10,351):
MAE=4.563, Corr=0.648, Pairwise=74.1% (stat_projector.py header).

PASS requires: fp-alone OR the locked ensemble beats ALL THREE baseline
numbers on the HOLDOUT split (2023-2025 pooled), not combined/in-sample.
Ensemble weight w is grid-searched 0.0->1.0 step 0.05 on TRAIN-ONLY
(2020-2022 pooled), then locked and evaluated once on holdout — same
nested protocol as backtest_ml.py (anti-leakage). One-shot: no re-tuning
after seeing the holdout number.

## Scope

Seasons 2020-2025 (both stats_{season} and stats_{season-1} cached
locally), REG weeks 4-18, all-universe (DNPs included, matching
backtest_ecr.py discipline). 2026 partial season reported as diagnostic
only, never gate-eligible (in-progress, small n).

## Scoring parity (the one thing that can silently break this)

FantasyPros' own "points"/"points_ppr" fields are NOT used directly — they
may reflect FantasyPros' own scoring convention, not ours. Instead the raw
projected stat line (proj_weekly.stats JSON) is key-mapped to
scoring.py's canonical keys and run through calculate_fantasy_points with
DEFAULT_SCORING — identical to how stat_projector's output and the nflverse
actual are scored. Known approximation: FP's "fumbles" field is total
fumbles, not fumbles LOST; mapped to fum_lost as an upward-biased proxy
(documented, not hidden). A sanity check compares the derived score against
FP's own points_ppr for a sample to catch a bad mapping before trusting
results.

## Not in scope

- Pre-2020 seasons (FP has ECR/proj back to 2012, but nflverse box stats to
  feed stat_projector for those years aren't cached and weren't fetched —
  separate task if ever wanted).
- Any production/model change. Measurement only, same framing as
  backtest_ecr.py.

## Output

data/ml/backtest_fp_projections_results.json: per-season, per-position,
and pooled MAE/corr/pairwise for stat and fp, the ensemble grid search
result, and the OOS gate verdict.
