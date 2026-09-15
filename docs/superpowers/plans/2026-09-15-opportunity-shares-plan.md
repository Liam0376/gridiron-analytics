# Plan: opportunity shares (xFP pull + TD expectation arms)

> Status (2026-09-15): VERDICTED — X1 REJECTED, X2 PENDING confirmation.
> Do not implement production wiring without a new confirm.
> Spec: `docs/superpowers/specs/2026-09-15-opportunity-shares-spec.md`.

## Tasks

- [ ] **1. Ingestion (no math change).** `get_opportunity(season,
  nfl_module=None)` + `get_ngs_receiving(season, nfl_module=None)` in
  `src/ffanalytics/adapters/nflverse.py`; pure `opportunity_features(rows)`
  in `src/ffanalytics/refresh.py` (per-(gsis, week): target_share,
  air_share, wopr, rec_xfp_gap, rush_xfp_gap, td_xfp_gap; zero-division
  safe). Refresh caches both files with last-good fallback + log entry.
  Unit tests (fake module, builder edge cases, cache fallback).
  Verify: `SLEEPER_LEAGUE_ID=test .venv/bin/pytest tests/adapters/ tests/test_refresh.py -q`.
- [x] **2. Arms backtest (research, no prod code).** New
  `scripts/backtest_opportunity.py`: X1 k-grid {0.15, 0.30} + X2 TD-pull
  grid vs BASE on the 2025 holdout (2024 priors + 2024 opportunity,
  weeks 4-18, REG week<=18) and the 2026 cumulative sample. Reports
  MAE/corr/pairwise/bias overall + WR/TE/RB splits, paired-t, Fisher z,
  fired-counts. Writes `data/ml/backtest_opportunity_results.json`.
  DONE 2026-09-15, pre-registration honored (no extra arms tried):
  X1 FAILS (2025 paired-t t=-4.36, significantly worse; 2026 t=+0.99 n.s.,
  inconsistent — trailing xFP gaps are weekly noise or double-count form).
  X2 consistent both samples (2025 t=26.3 diff +0.112; 2026 t=11.0 diff
  +0.154; corr neutral both; bias +1.76->+1.57) but pre-registered
  secondary, so no promotion on this evidence.
  Verify: `SLEEPER_LEAGUE_ID=test PYTHONHASHSEED=0 .venv/bin/python
  scripts/backtest_opportunity.py`.
- [x] **3. Verdict + full gates.** Pass -> write the production-flag spec
  (new task, new confirm). Fail -> `# REJECTED — evidence` inline in
  `stat_projector.py` + plan marked REJECTED, PBP proxy stays.
  `SLEEPER_LEAGUE_ID=test .venv/bin/pytest -q` green either way.
  DONE 2026-09-15, split verdict: X1 REJECTED inline in
  `stat_projector.py` header (PBP proxy stays untouched); X2 PENDING —
  held for a confirmatory follow-up with a flat-lower-mean control
  (individualized vs merely lower prior) + accumulated 2026, new spec +
  new confirm before any production wiring. Suite 245 passed, 4 skipped.
  Note: 2025 BASE pairwise here (0.676) differs from the published 0.6925
  by traversal order under tied DNP actuals (documented in the snap plan);
  MAE/corr and all paired-ts are order-invariant and match.

## Explicitly not doing (v1)

- ECR ingestion, QB passing arms, RACR/efficiency inputs, aDOT automation,
  hub display, PBP adapter deletion, new dependencies, width retuning.

## Verify (whole plan)

- `SLEEPER_LEAGUE_ID=test .venv/bin/pytest -q`
- `SLEEPER_LEAGUE_ID=test PYTHONHASHSEED=0 .venv/bin/python scripts/backtest_opportunity.py`
