# Plan: FantasyPros market source (spec 2026-09-24-fp-market-source-spec.md)

Branch: `feat/trade-slot-uplift` (in place, solo mode). Stop for Liam's
confirm before Task 1. Task 3 additionally needs Liam to confirm the CSV
export exists on a free/non-premium fantasypros.com account before it starts.

- [ ] Task 0: Reconciliation backtest.
  - Extend `backtest_market_blend.py`'s FPP arm from 2024/2025-only to the
    full 2020-2025 sample (same seasons as `backtest_fp_projections.py`).
  - Re-fit the w-grid (both per-position and pooled). Report whether it
    converges toward this session's w=1.00 (model weight 0) or holds near
    the existing 0.10.
  - Lock whichever number survives as `FP_BLEND_W_MODEL` in `config.py`.
    Do not average the two prior results.
  - Verify: script prints the fit + holdout numbers for both seasons,
    written to `data/ml/backtest_market_blend_results.json` (extend, don't
    replace, the existing SLP/ECR arms).
- [ ] Task 1 (blocked on Liam confirming CSV export access): weekly CSV
  adapter.
  - `adapters/fantasypros_weekly_projections.py`, column-index parsing
    matching `fantasypros_projections.py`'s style. Reuse
    `backtest_fp_projections.py`'s stat-key-to-scoring-key mapping
    function directly (don't reimplement — it's already validated,
    corr 0.998 vs FP's own `points_ppr`).
  - Output: `{gsis_id: points}` scored via `calculate_fantasy_points` +
    live league scoring (same pattern as `score_sleeper_stats`).
  - Tests: malformed/missing CSV, position coverage, gsis join rate on a
    fixture file.
- [ ] Task 2: `market_snapshots` schema migration (source column).
  - `schema.sql` migration v11 (check current version first —
    `projection_snapshots` was v10 per architecture.md).
  - Backfill: existing Sleeper-only rows get `source='sleeper'`.
- [ ] Task 3: source-priority wiring in `refresh.py`.
  - `market_by_gsis` build order: FP weekly file (if present and dated
    this week) -> Sleeper (`map_market_to_gsis`, already live) -> none.
  - `build_market_snapshot_rows` tags `source` per the row's actual origin.
  - No same-week FP+Sleeper stacking — no backtested arm supports it
    (spec non-goals).
- [ ] Task 4: `FP_MARKET_BLEND_ENABLED` flag (defaults False) +
  `blend_with_market()` reuse (source-agnostic already, just needs the
  right `market_pts` fed in — check whether `w_model` should differ from
  Sleeper's `MARKET_BLEND_W_MODEL` per Task 0's locked number).
  - Tests: mirror `test_market_blend.py`'s structure for the new source.
- [ ] Task 5: `scripts/validate_fp_market_2026.py`, a `grade()` mirroring
  `validate_market_blend_2026.py` — live gate: >=1500 pre-kickoff
  QB/RB/WR/TE player-weeks, weeks>=4, paired-t>=2.0 vs BASE, corr/pairwise
  not worse than BASE.
  - Tests: waiting, pass, week-4 scope, DNP rows (copy the existing
    suite's cases, swap the source).
- Verification: full suite green after each task. Re-run
  `backtest_fp_projections.py` unchanged (regression check the refactor
  didn't touch its numbers).
- [ ] Task 6 (after live gate passes and Liam confirms): flip
  `FP_MARKET_BLEND_ENABLED`.
  - Update `docs/ACCURACY.md` production row.
  - Full suite.
