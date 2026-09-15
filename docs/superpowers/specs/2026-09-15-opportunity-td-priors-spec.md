# Spec: promote population xFP TD priors to POS_TD_MEANS

> Status (2026-09-15): DRAFT, awaiting user confirm. Follows the opportunity
> plan Task 3 follow-up clause (X2 control verdict reached: POP wins).

## Problem

Production TD regression pulls 30% toward `POS_TD_MEANS` whose level is
stale: every mean sits far above xFP-implied scoring rates, injecting a
systematic over-projection (all-universe bias +1.76 on the 2025 holdout).
The weight (30%) is not the problem; the LEVEL is.

## Evidence (pre-registered follow-up, no new arms beyond the committed design)

`data/ml/backtest_opportunity_results.json` (script header holds the
pre-registration and ship-exactness addendum):

- POP (30% toward live per-week population xFP rate): BASE-POP paired-t
  t=42.8 (diff +0.093) on 2025 n=8049, t=16.3 (diff +0.121) on 2026wk1
  n=652, corr neutral both, bias +1.76->+1.57.
- X2 (individualized) loses to POP both samples (t=-5.05, t=-2.65):
  trailing individual TD rates are too noisy — shrink all the way.
- FROZEN (ship-exact constants below) reproduces POP within noise
  (parity diff +0.006/+0.003, same direction, corr identical).
- X1 stays REJECTED (2025 t=-4.36; 2026 n.s.).

## Design (proposed — constants only, mechanism untouched)

Replace five `POS_TD_MEANS` values in `src/ffanalytics/stat_projector.py`,
provenance comment updated to "2024-2025 trailing-xFP means":

- RB: rushing_tds 0.35 -> 0.20, receiving_tds 0.08 -> 0.04
- WR: receiving_tds 0.30 -> 0.18, rushing_tds 0.02 -> 0.005
- TE: receiving_tds 0.22 -> 0.14
- QB, K: UNCHANGED (arms never applied there — no evidence either way).

Weight stays `TD_REGRESSION_WEIGHT = 0.30`. `td_prior`/`xfp_adjust` params
stay default-off as instruments. Regression test in the same commit pins
the new constants on a fixed history (hand-computed values, not
backtest-derived).

## Gates (frozen)

- Full suite green. New constants test passes. Production output on the
  2026 Week-1 universe must equal the backtest FROZEN arm to machine
  precision (same code path — assert on a sample of pids, not faith).
- No other numbers move: QB/K projections bit-identical (prove by diffing
  full-week projections before/after on 2026 Week 1 — only RB/WR/TE rows
  may change).

## Non-goals

- X1 revival, X2 individualization, weight changes, new arms, hub display,
  touching frozen widths or any other REJECTED verdict.
