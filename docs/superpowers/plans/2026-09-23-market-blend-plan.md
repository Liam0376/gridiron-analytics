# Plan: market blend (spec 2026-09-23-market-blend-spec.md)

Branch: `market-blend`. Stop for Liam's confirm before Task 1.

- [x] Task 0: Research backtest.
  - `scripts/backtest_market_blend.py`, results JSON committed.
  - Verify: `PYTHONHASHSEED=0 .venv/bin/python scripts/backtest_market_blend.py` prints `SLP/wp PASS both holdouts`.
- [ ] Task 1: `market_snapshots` table plus a refresh write.
  - `schema.sql` and `db.py` migration.
  - In refresh, after `market_by_gsis`, write scored points (live league scoring) for the target week.
  - Test: fake market dict to rows, idempotent upsert, K and DEF skipped.
  - Verify: run a refresh, then `SELECT count(*) FROM market_snapshots WHERE season=2026 AND week=<cur>` returns more than 300.
- [ ] Task 2: `blend_with_market()` and config constants.
  - `MARKET_BLEND_W_MODEL=0.25` and `MARKET_BLEND_ENABLED=False`, with the `why` citing the results JSON.
  - Tests:
    - QB/RB/WR/TE blend.
    - K passthrough.
    - Missing or zero market falls back to the model.
    - Out stays 0.
    - Weight 1.0 is an identity.
- [ ] Task 3: Shadow write.
  - Add a `projection_snapshots.shadow_points` column, filled with the blend while the flag is off.
  - Test: the flag off leaves `projected_points` byte-identical to today.
- [ ] Task 4: Live grader.
  - `scripts/validate_market_blend_2026.py` joins pre-kickoff snapshots to actuals.
  - It prints n, both MAEs and the paired-t against the live gate.
  - Verify on 2026 week 1: n=307, model 5.074, blend 4.901.
- [ ] Task 5 (after the live gate passes and Liam confirms): flip `MARKET_BLEND_ENABLED`.
  - The comparison keeps the raw model.
  - Update the `docs/ACCURACY.md` production row.
  - Full suite.
