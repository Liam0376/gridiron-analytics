# Plan: opportunity shares (xFP pull + TD expectation arms)

> Status (2026-09-15): DRAFT — stop for confirm, do not implement yet.
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
- [ ] **2. Arms backtest (research, no prod code).** New
  `scripts/backtest_opportunity.py`: X1 k-grid {0.15, 0.30} + X2 TD-pull
  grid vs BASE on the 2025 holdout (2024 priors + 2024 opportunity,
  weeks 4-18, REG week<=18) and the 2026 cumulative sample. Reports
  MAE/corr/pairwise/bias overall + WR/TE/RB splits, paired-t, Fisher z,
  fired-counts. Writes `data/ml/backtest_opportunity_results.json`.
  Verify: `SLEEPER_LEAGUE_ID=test PYTHONHASHSEED=0 .venv/bin/python
  scripts/backtest_opportunity.py`.
- [ ] **3. Verdict + full gates.** Pass -> write the production-flag spec
  (new task, new confirm). Fail -> `# REJECTED — evidence` inline in
  `stat_projector.py` + plan marked REJECTED, PBP proxy stays.
  `SLEEPER_LEAGUE_ID=test .venv/bin/pytest -q` green either way.

## Explicitly not doing (v1)

- ECR ingestion, QB passing arms, RACR/efficiency inputs, aDOT automation,
  hub display, PBP adapter deletion, new dependencies, width retuning.

## Verify (whole plan)

- `SLEEPER_LEAGUE_ID=test .venv/bin/pytest -q`
- `SLEEPER_LEAGUE_ID=test PYTHONHASHSEED=0 .venv/bin/python scripts/backtest_opportunity.py`
