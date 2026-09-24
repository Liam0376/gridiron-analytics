# Plan: XGBoost(box-score features + FP projection) vs FP-alone

See spec: docs/superpowers/specs/2026-09-24-fp-ml-ensemble-spec.md

- [x] Task 1: scripts/backtest_fp_ml.py — join build_training_rows (box-score
  FEATURE_COLS) with backtest_fp_projections.py's per-player-week stat_pts/
  fp_pts/actual_pts (added `player_id` to that script's row dict, additive,
  non-breaking) on (player_id, season, week). QB/RB/WR/TE only, weeks 4-18.
  Verify: per-season row counts printed, sane (thousands per season).
- [x] Task 2: fit XGBoost (ml_train.py's PARAMS, unchanged) on 2020-2021,
  early-stop via 2022 eval_set, features = FEATURE_COLS + fp_proj_pts.
  Verify: model fits without error, best_iteration found via early stopping.
- [x] Task 3: evaluate once on 2023-2025 holdout — MAE/corr/pairwise vs the
  fixed FP-alone gate (3.386/0.758/0.798). Print PASS/FAIL per metric.
  Also report feature importances (gain) to see whether FP dominates or
  box-score features pull real weight.
  Verify: gate verdict printed explicitly; importances printed top-10.
- [x] Task 4: ablation arm — same XGBoost fit/early-stop/holdout protocol
  with fp_proj_pts as the only feature.
  Verify: separate PASS/FAIL printed.
- [x] Task 5: write data/ml/backtest_fp_ml_results.json.
- [x] Task 6: full test suite (`SLEEPER_LEAGUE_ID=test .venv/bin/pytest -q`)
  — confirm no regression (scripts/ + docs/ + data/ml/ only, no src/ edits
  except the additive player_id field in backtest_fp_projections.py).
- [x] Task 7: commit (scripts + spec + plan + results JSON only — do not
  touch data/nfl_cache/schedule_2026.json, pre-existing unrelated dirty
  file from an autonomous refresh job).
