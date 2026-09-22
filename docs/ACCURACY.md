# Accuracy provenance

Every accuracy number in this repo lives here with its scope. Read the Scope
column before comparing numbers — same-metric figures from different scopes
are not comparable (see the K-zero lesson in stat_projector.py:8-13).

## Production freeze (unchanged)

| Metric | Value | Scope |
|---|---|---|
| MAE | 4.563 | stat projector, 2024-2025 weeks 4-18, n=10,351, true scoring |
| Corr | 0.648 | same |
| Pairwise | 74.1% | same |
| Coverage | 82.1% | split-conformal intervals, 80% target, same scope |

Source: `src/ffanalytics/stat_projector.py:8`. Gate all model comparisons on
these three, not on local/val numbers quoted elsewhere.

## Trade slot uplift (new, 2026-09-21)

Method: `scripts/backtest_trade_threshold.py` on the 2025 holdout at week 8.
Projections as-of-week via production-verbatim `build_weekly_projections`
(no reimplementation). Actuals: `fantasy_points_ppr` sums weeks 8-18.
Simulated 12-team snake league (rank-drafted by projection, seed 0;
seed 1 rerun for stability) splits pool into rostered vs free agents.
Synthetic packages 1v1/2v1/2v2/3v2 (n=100/shape) from random roster pairs.
Waiver fill for gained slots: actual ROS of the MODEL-picked waiver player
(not hindsight-best — that would be an unfillable upper bound).

| Shape | Base acc | Fold acc | SE | Thresholds | Verdict |
|---|---|---|---|---|---|
| 1v1 | 0.45–0.63 | same (no slots) | 0.05 | 3/5/8/10 | n/a |
| 2v1 | 0.62–0.66 | 0.79–0.85 | 0.048 | 3/5/8/10 | PROMOTE |
| 2v2 | 0.53–0.61 | same (no slots) | 0.05 | 3/5/8/10 | n/a |
| 3v2 | 0.57–0.64 | 0.69–0.77 | 0.048 | 3/5/8/10 | PROMOTE |

Accuracy = ternary verdict agreement (A wins / Fair / B wins) with actual
ROS-diff sign at the same threshold. Ranges span seed 0/seed 1.

Slot calibration: predicted uplift vs actual model-pick waiver edge —
MAE ~60–90, bias +37–52 (predictions overshoot pickup actuals by ~4/wk,
about one weekly MAE; directionally correct, magnitude optimistic).

Known limits (do not use these numbers beyond them):
- Equal-count package verdicts (1v1/2v2) sit near chance on this holdout —
  evenly-matched synthetic packages are noise-dominated. The ±5 threshold
  was never calibrated for tiny-package VOR; slot work does not fix that.
- Synthetic snake rosters are evenly matched by construction; real leagues
  have stacked/weak teams, which shifts base accuracy unpredictably.
- Model-pick waiver fill assumes the manager adds the optimizer's choice;
  humans add worse (or better) players.
- Results: `data/ml/backtest_trade_threshold_results.json` (seed 0).

Status: backtest PROMOTEs the fold, but production stays on baseline until
the shadow gate opens (>=20 resolved trade rows via a trade outcome
resolver, which does not exist yet). The gate, not this table, owns
promotion. See `evaluate_trade_gated` in `src/ffanalytics/decision.py`.
