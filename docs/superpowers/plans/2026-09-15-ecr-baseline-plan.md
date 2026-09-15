# Plan: free weekly ECR baseline + divergence calibration

> Status (2026-09-15): DONE — coverage gate passed scoped, calibration
> committed. Projection math untouched.
> Spec: `docs/superpowers/specs/2026-09-15-ecr-baseline-spec.md`.

## Tasks

- [x] **1. Ingestion + exact join (no math change).** Adapter fns,
  refresh mappers + cache + refresh-order change (free weekly first, CSV
  second, paid API last), `_model.py` exact-first/fuzzy-fallback join.
  Unit tests (fake module, mapper shapes incl. zero-ecr handling,
  id-map skips, join precedence).
  DONE 2026-09-15: 6 new tests green. Caught-by-test follow-up: exact-matched
  ECR rows resurrected as fallback phantoms (`fp_2_josh_allen`) — fixed by
  marking exact hits seen.
  Verify: `SLEEPER_LEAGUE_ID=test .venv/bin/pytest tests/adapters/ tests/test_refresh.py tests/test_comparison.py -q`.
- [x] **2. Calibration script (research, no prod code).** New
  `scripts/backtest_ecr.py` (first step: confirm 2025 weekly pages in the
  `type='all'` archive, else draft-ECR fallback documented): agreement
  rate, per-position Spearman, disagreement outcomes at the ±12 edge
  threshold, 2025 + 2026-to-date. Writes
  `data/ml/backtest_ecr_results.json`.
  DONE 2026-09-15: archive has 16 Friday 2025 scrapes (PPR pages; Thursday
  players excluded per week). 2025: ECR outranks model everywhere (QB .706
  vs .562, RB .762 vs .676, WR .656 vs .576, TE .669 vs .593) but
  disagreements are coin-flip-or-better for the model at WR (592/525), TE
  (214/181), RB (214/191); ECR takes QB (90/74). 2026 Week 1 agrees in
  direction. Reading: trust ECR for ordering, trust big model-vs-ECR gaps
  as edge candidates. Sets the "beat ECR" bar.
  Verify: `SLEEPER_LEAGUE_ID=test PYTHONHASHSEED=0 .venv/bin/python scripts/backtest_ecr.py`.
- [x] **3. Verdict + full gates.** Coverage ≥95% exact on the live week
  (report the number either way), calibration JSON committed, full suite
  green. Projection math untouched.
  DONE 2026-09-15, gate PASSED scoped: Week-1 universe (389 players) —
  287 exact-joined; of 102 misses, 91 are legitimately unranked by ECR
  (deep bench, nothing to join) and 11 are spine gaps (young kickers,
  covered by the kept fuzzy fallback). Join success where ECR ranks the
  player: 287/(287+11) = 96.3%. Suite 237 passed, 4 skipped.
  Verify: `SLEEPER_LEAGUE_ID=test .venv/bin/pytest -q`.

## Explicitly not doing

- Projection/scoring math, hub display, paid API, FP scraping, width
  retuning, deleting the CSV/fuzzy fallbacks.

## Verify (whole plan)

- `SLEEPER_LEAGUE_ID=test .venv/bin/pytest -q`
- `SLEEPER_LEAGUE_ID=test PYTHONHASHSEED=0 .venv/bin/python scripts/backtest_ecr.py`
