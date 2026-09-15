# Spec: free weekly ECR baseline + divergence calibration

> Status (2026-09-15): DRAFT, awaiting user confirm on the plan.
> Proposal C from the 2026-09-15 external-inspiration research. Builds on A
> (gsis identity). Changes no projection math — instrumentation only.

## Problem

The comparison stack (model vs market, BUY/SELL edge rules, auction VOR)
already exists (`comparison/`), but its ECR leg is the weakest:

- Under $0 the paid FP API returns [] (`adapters/fantasypros.py:70`), so ECR
  comes from hand-downloaded preseason CSVs (`adapters/fantasypros_csv.py`)
  that freeze in August and drift all season.
- The ECR join is fuzzy name/team/pos (`comparison/_common.py:86`
  `_best_fpros_match`, substring fallback included) — the same name-fragility
  class proposal A is killing everywhere else.
- Nobody has measured whether the model or ECR is right when they disagree,
  so the edge labels have no calibration behind them.

## Evidence (verified live 2026-09-15, nflreadpy, $0)

- `load_ff_rankings(type='week')`: current-week ECR (today: Week 2, 601 rows,
  scrape 2026-09-15) with ecr/sd/best/worst/pos_rank/opponent/bye/start-sit
  grade. Fresh weekly through the season, no key, no scraping.
- `load_ff_rankings(type='all')`: 1.8M-row archive (weekly history for
  backtesting disagreement outcomes — first step of C-2 confirms 2025
  weekly pages exist there, else falls back to draft ECR with the downgrade
  documented).
- `load_ff_playerids()`: 12,494-row spine with fantasypros_id + gsis_id +
  sleeper_id — the exact ECR join key. No names involved.
- `_model.py:127` `_fpros_fields` reads `rank_ecr_ppr` / `rank_ecr_pos` /
  `tier` — a small shape mapper feeds the free rows into the existing
  pipeline unchanged.

## Design (proposed)

- C-1 ingestion (no math change): `get_ecr_weekly()` + `get_ff_playerids()`
  in `adapters/nflverse.py` (same `_retry` + plain-dict pattern); pure
  `map_fpros_id_to_gsis()` + `nflverse_ecr_to_fpros()` (shape mapper to the
  keys `_fpros_fields` reads, fantasypros_id passed through) in
  `refresh.py`; `comparison/_model.py` tries the exact fantasypros_id join
  first, keeps `_best_fpros_match` as fallback. Refresh order: free weekly
  ECR first, manual CSV second, paid API last (returns [] under $0 anyway).
  Cache `ecr_weekly_<season>.json` + `ff_playerids.json`, last-good
  fallback, log entries. Unit tests (fake module, mapper shapes, id map,
  exact-first/fallback-second model test).
- C-2 calibration (research script `scripts/backtest_ecr.py`): model rank
  vs ECR rank vs actuals — agreement rate, Spearman per position, and
  disagreement outcomes (who was right when model and ECR differ by the
  edge-rule ±12 threshold). 2025 via the archive + 2026 weeks to date.
  Writes `data/ml/backtest_ecr_results.json`. No model change, no tuning —
  measurement that sets the "beat ECR" bar future challengers must clear.
- C-3 verdict: exact-join coverage gate (≥95% of the current-week universe
  matched by id, not fuzzy) + calibration JSON committed. Projection math
  untouched regardless of what calibration says.

## Gates (frozen)

- Full suite green. Coverage ≥95% exact on the live week. Calibration runs
  on existing data only (archive + caches). No frozen numbers change.

## Non-goals

- QB passing or projection-math changes (B follow-up territory), hub display
  changes (edge labels already flow through existing rows), paid FP API key,
  scraping fantayspros.com (ToS exposure the data-sources doc already
  rejected), touching frozen widths or prior REJECTED verdicts.
