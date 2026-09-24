# Spec: XGBoost(box-score features + FP projection) vs FP-alone

## Why

backtest_fp_projections.py (commit 99b97ca) found FantasyPros' own weekly
market projection beats stat_projector.py decisively on the 2023-2025
holdout (MAE 3.386 vs 4.563 baseline, paired-t=42.05 p<0.0001). The linear
ensemble grid locked w=1.00 — stat_projector's point OUTPUT adds zero linear
lift on top of FP. This spec asks a different, still-open question: does a
nonlinear model (XGBoost) that sees the raw box-score-derived FEATURES
(target share, air yards, redzone usage, Vegas/weather, trend — the same
FEATURE_COLS from the already-REJECTED XGBoost attempts in
docs/rejected-ml-evidence/ml_train.py) *alongside* the FP projection find
structure the FP number alone misses? Not a repeat of the prior XGBoost
rejections — those used box-score features only, never FP as an input.

## Gate (pre-registered, no changes after seeing results)

Baseline to beat is FP-ALONE on the 2023-2025 holdout: MAE=3.386,
Corr=0.758, Pairwise=0.798 (from backtest_fp_projections_results.json).
Beating the old stat_projector production baseline (4.563/0.648/0.741) is
NOT sufficient — FP-alone already clears that trivially. XGBoost(features+
FP) must beat FP-alone on ALL THREE metrics on HOLDOUT to count as a real
win. Tie or loss is a valid REJECTED result, reported as such.

## Protocol (nested, anti-leakage, mirrors backtest_ml.py)

- Fit fold: 2020-2021, weeks 4-18, all-universe, QB/RB/WR/TE only (FP dump
  has no K/DST weekly rows 2020-2025).
- Early-stop fold: 2022 — used only to pick XGBoost's best_iteration via
  eval_set early stopping; never touches the holdout.
- Holdout (evaluated once): 2023-2025, same seasons as the FP-projection
  backtest for comparability.
- Hyperparameters: identical to ml_train.py's PARAMS (n_estimators=500,
  max_depth=5, lr=0.03, subsample=0.8, colsample=0.8, reg_lambda=1.0) — no
  new hyperparameter search (a fresh p-hacking surface).
- Second arm (ablation): XGBoost trained on fp_proj_pts as the ONLY
  feature — checks whether wrapping FP's number in a tree model helps or
  hurts vs. using the linear number directly.

## Known scope limits

- PBP-derived features (target/air-yards/snap/redzone shares) are only
  cached 2023-2025 (data/nfl_cache/pbp_*.json). 2020-2022 fit rows get zero
  for those ~8 columns — degrades gracefully (a zero-variance column earns
  no splits) but is a real gap, not fetched here (separate task).
- Joining box-score features (via build_training_rows) on top of the FP
  backtest's rows shrinks the usable sample (~14k vs ~19k on the same
  season range) — team-resolution / feature-availability requirements drop
  some player-weeks. The reference stat/fp numbers on this smaller joined
  sample are reported alongside the fixed external FP-alone gate for
  transparency; they are not the same 18,698-row sample as commit 99b97ca.

## Not in scope

Any production/model change. Measurement only.

## Output

data/ml/backtest_fp_ml_results.json: holdout MAE/corr/pairwise for both
arms, pass/fail vs the FP-alone gate, paired-t, and feature importances.
