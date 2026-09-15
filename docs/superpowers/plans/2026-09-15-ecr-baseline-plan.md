# Plan: free weekly ECR baseline + divergence calibration

> Status (2026-09-15): DRAFT — stop for confirm, do not implement yet.
> Spec: `docs/superpowers/specs/2026-09-15-ecr-baseline-spec.md`.

## Tasks

- [ ] **1. Ingestion + exact join (no math change).** Adapter fns,
  refresh mappers + cache + refresh-order change (free weekly first, CSV
  second, paid API last), `_model.py` exact-first/fuzzy-fallback join.
  Unit tests (fake module, mapper shapes incl. zero-ecr handling,
  id-map skips, join precedence).
  Verify: `SLEEPER_LEAGUE_ID=test .venv/bin/pytest tests/adapters/ tests/test_refresh.py tests/test_comparison.py -q`.
- [ ] **2. Calibration script (research, no prod code).** New
  `scripts/backtest_ecr.py` (first step: confirm 2025 weekly pages in the
  `type='all'` archive, else draft-ECR fallback documented): agreement
  rate, per-position Spearman, disagreement outcomes at the ±12 edge
  threshold, 2025 + 2026-to-date. Writes
  `data/ml/backtest_ecr_results.json`.
  Verify: `SLEEPER_LEAGUE_ID=test PYTHONHASHSEED=0 .venv/bin/python scripts/backtest_ecr.py`.
- [ ] **3. Verdict + full gates.** Coverage ≥95% exact on the live week
  (report the number either way), calibration JSON committed, full suite
  green. Projection math untouched.
  Verify: `SLEEPER_LEAGUE_ID=test .venv/bin/pytest -q`.

## Explicitly not doing

- Projection/scoring math, hub display, paid API, FP scraping, width
  retuning, deleting the CSV/fuzzy fallbacks.

## Verify (whole plan)

- `SLEEPER_LEAGUE_ID=test .venv/bin/pytest -q`
- `SLEEPER_LEAGUE_ID=test PYTHONHASHSEED=0 .venv/bin/python scripts/backtest_ecr.py`
