# Spec: QB passing xFP arms

> Status (2026-09-15): DRAFT — blanket-approved with points list 2026-09-15,
> implementing with pre-registration below. Production wiring needs a
> separate confirm on a pass verdict.

## Verdict (2026-09-15, both samples run, pre-registration honored)

- XQ1 REJECTED: 2025 paired-t t=+1.6 (n.s.), 2026 t=+2.6 — inconsistent,
  fails the both-samples rule. Same lesson as skill X1: trailing xFP yard
  gaps are weekly noise.
- QPOP/QFROZEN PASS: BASE-QFROZEN paired-t t=14.5 (diff +0.071, QB subset
  t=16.1 diff +0.60) on 2025 n=8049 and t=4.7 (diff +0.084, QB t=5.4 diff
  +0.68) on 2026wk1 n=652; correlation IMPROVED both samples (z=-0.41,
  -0.18); frozen 0.83 reproduces live QPOP within noise. Evidence:
  `data/ml/backtest_opportunity_results.json`.
- Proposed production change (pending user confirm): QB `passing_tds`
  1.7 -> 0.83 in `POS_TD_MEANS` (rushing untouched). Pinning test +
  bit-identical proof (only QB rows move) required in the same commit.

## Problem

Proposal B deliberately excluded QB passing (isolate skill effects first).
The opportunity feed carries passing expectations (`pass_yards_gained_exp`,
`pass_touchdown_exp`, `pass_completions_exp`) that have never been tested
against the QB pipeline. QB is also the position where the model trails ECR
most (calibration: Spearman .562 vs .706) — the most headroom, if the signal
is real.

## Design (pre-registered)

Builder extension (production-safe): `pass_yd_gap`, `pass_td_gap`,
`pass_yd_exp`, `pass_td_exp` in `opportunity_features` (same zero-division
discipline). Unit tests extended.

Two arms in `scripts/backtest_opportunity.py` (no other variants):

- XQ1 (passing-yards pull, PRIMARY): `xfp_adjust={"passing_yards":
  k * trailing(pass_yards_exp - actual)}`, k=0.15 primary, k=0.30
  sensitivity-only. Same cap/no-zero-base pipeline semantics as X1.
- QPOP (population pass-TD prior): `td_prior={"passing_tds": <position
  mean trailing pass_td_exp>}` per week (same construction as POP).
  QB rushing TDs untouched (no evidence sought there).

Scope: QB only (skill arms run unchanged for record stability; X1 stays
rejected, POP/FROZEN/HIER verdicts stand). No snap scaling in this script
(pure-pipeline comparison, same isolation rationale as before).

## Gates (frozen)

An arm promotes iff it beats BASE with paired p<0.05 in BOTH samples
(2025 holdout weeks 4-18 + 2026 cumulative) with corr neutral. Anything
else: REJECTED inline. Full suite green.

## Non-goals

INT modeling, QB rushing xFP, X1/X2 revival, weight changes, production
wiring on anything short of the gate, hub display.
