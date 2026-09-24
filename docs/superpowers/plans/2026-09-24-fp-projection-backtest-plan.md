# Plan: FantasyPros market-projection accuracy backtest

See spec: docs/superpowers/specs/2026-09-24-fp-projection-backtest-spec.md

- [x] Task 1: scripts/backtest_fp_projections.py — load fp.sqlite proj_weekly
  per season/week, map stats JSON to scoring.py keys, compute stat_pts (reuse
  backtest_ecr.py's history/prior/game-context construction),
  fp_pts, actual_pts per player-week for 2020-2025 weeks 4-18 all-universe.
  Verify: sanity check (mapped-fp-score vs FP's own points_ppr) printed and
  sane (expect high correlation; big divergence means a mapping bug).
- [x] Task 2: metrics (MAE/corr/pairwise, mirrored from backtest_ml.py's
  `_evaluate`) per season, per position, pooled, for stat vs fp. Paired-t
  on per-player-week absolute errors (stat vs fp).
  Verify: numbers print per season, no NaN/inf, n matches expected order of
  magnitude (~similar to backtest_ecr.py's per-season n).
- [x] Task 3: ensemble grid (w*fp + (1-w)*stat) on TRAIN 2020-2022, lock w,
  evaluate once on HOLDOUT 2023-2025, gate against production freeze
  (4.563/0.648/0.741) on all three metrics.
  Verify: gate verdict printed explicitly (PASS/FAIL per metric).
- [x] Task 4: write data/ml/backtest_fp_projections_results.json.
- [x] Task 5: full test suite (`SLEEPER_LEAGUE_ID=test .venv/bin/pytest -q`)
  — confirm no regression (script-only change, no src/ edits expected).
- [x] Task 6: commit (script + spec + plan + results JSON only — do not
  touch data/nfl_cache/schedule_2026.json, pre-existing unrelated dirty
  file from an autonomous refresh job).
