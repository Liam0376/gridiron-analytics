# Plan: market blend (spec 2026-09-23-market-blend-spec.md)

Branch: `market-blend`. Stop for Liam's confirm before Task 1.

- [x] Task 0: Research backtest.
  - `scripts/backtest_market_blend.py`, results JSON committed.
  - Verify: `PYTHONHASHSEED=0 .venv/bin/python scripts/backtest_market_blend.py` prints `SLP/wp PASS both holdouts`.
- [x] Task 1: `market_snapshots` table (migration v13) plus a pre-kickoff refresh write.
  - `refresh.build_market_snapshot_rows` scores Sleeper stat lines with live league scoring (`scoring.score_sleeper_stats`).
  - A row is (re)written only while its team's kickoff (schedule gameday + gametime, US/Eastern) is still ahead, so Monday's refresh can't overwrite Sunday players with post-game values.
  - Fixed on the way: `map_market_to_gsis` gained an ff_playerids fallback. Sleeper's own gsis_id covered 233 of 1,043 projected players. Coverage of week-3 skill rows went from about 10% to 76% (RB 13 to 97 of 125). The BUY/SELL comparison gets the same join fix, with 445 of 833 rows now carrying market points.
  - Verified: refresh against a copy of the live DB wrote 516 week-3 rows, kickoffs from TNF to MNF.
- [x] Task 2: `blend_with_market()` plus `MARKET_BLEND_*` constants in `config.py`, with tests.
- [x] Task 3: Shadow write. Design change: it lives in `market_snapshots` (model, market and blend frozen together pre-kickoff), not a `projection_snapshots` column. That table is overwritten on every refresh including post-game Mondays, so it can't hold the guarantee. `projected_points` is untouched; the flag ships False (test pins it).
- [x] Task 4: `scripts/validate_market_blend_2026.py` with a pure `grade()`.
  - Tests: waiting, pass, week-4 scope and DNP rows.
  - Gate numbers come from config.
- Verification: `tests/test_market_blend.py` has 18 tests. The full suite shows 313 passed, 4 skipped. The backtest reruns identical on the rebased live code.
- [ ] Task 5 (after the live gate passes and Liam confirms): flip `MARKET_BLEND_ENABLED`.
  - The comparison keeps the raw model.
  - Update the `docs/ACCURACY.md` production row.
  - Full suite.
