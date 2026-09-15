# Plan: gsis-keyed identity (depth charts + weekly rosters)

> Status (2026-09-15): DONE — all four tasks green, see evidence notes inline.
> Spec: `docs/superpowers/specs/2026-09-15-gsis-identity-spec.md`.

## Tasks

- [x] **1. Adapters (no prod wiring yet).** Add `get_depth_charts(season,
  nfl_module=None)` and `get_weekly_rosters(season, nfl_module=None)` to
  `src/ffanalytics/adapters/nflverse.py`, same `_retry` + plain-list[dict]
  pattern as `get_player_ids`. Depth returns latest-`dt` snapshot rows only.
  Unit tests with a fake `nfl_module=` (no network): snapshot selection,
  Polars never leaks (assert plain dicts).
  Verify: `SLEEPER_LEAGUE_ID=test .venv/bin/pytest tests/adapters/ -q`.
  DONE 2026-09-15: 25 passed (3 new depth/roster tests).
- [x] **2. Refresh wiring (gsis-first, name fallback).** Add
  `build_gsis_team_map` + gsis rank lookup in `src/ffanalytics/refresh.py`;
  extend `patch_proj_teams` to try `{gsis}` before `{name, pos}`.
  Cache snapshots to `data/nfl_cache/depth_<season>.json` /
  `rosters_weekly_<season>.json` with last-good fallback + `refresh_log`
  entry on fetch failure. Regression tests per the spec's gate list
  (movers, collision, DNP-without-box-score, None-gsis fallback).
  Verify: `SLEEPER_LEAGUE_ID=test .venv/bin/pytest tests/test_refresh.py -q`.
  DONE 2026-09-15: 19 passed (3 new gsis tests). Caught-by-test follow-up:
  nflverse pos_rank is 1-based; `gsis_depth_rank` normalizes to repo 0-based
  convention at the boundary (uncut, Week-1 V1 regressed 4.163 -> 4.567).
- [x] **3. Backtest cutover.** `scripts/backtest_snap_share_2026.py` reads
  the cached depth snapshot instead of the FantasyPros CSV; remove CSV
  support from the script. Re-run default mode + `--check-2025-join`
  (2025 path keeps its week-1-snap proxy — no depth history exists there —
  and must still reproduce published numbers exactly).
  Verify: `SLEEPER_LEAGUE_ID=test PYTHONHASHSEED=0 .venv/bin/python
  scripts/backtest_snap_share_2026.py` (expect gsis-only run at or better
  than MAE 4.163 / QB 4.470) plus the `--check-2025-join` PASS line.
  DONE 2026-09-15: gsis-only Week-1 V1_0.05 MAE 4.126 / QB 4.168 (beats
  name-join 4.163 / 4.470), paired t=3.61 (QB t=5.19); `--check-2025-join`
  still PASS (BASE/ZERO reproduce published exactly).
- [x] **4. Full gates.** `SLEEPER_LEAGUE_ID=test .venv/bin/pytest -q`
  (231 pass / 4 skipped baseline) green. No hub changes, so no isolation
  script run needed (and the gate is gone anyway).
  DONE 2026-09-15: 237 passed (231 + 6 new), 4 skipped.

## Explicitly not doing

- Opportunity shares, ECR ingestion, scoring/projection math, hub display,
  new dependencies, schema migrations, deleting the name-map fallback.

## Verify (whole plan)

- `SLEEPER_LEAGUE_ID=test .venv/bin/pytest -q`
- `SLEEPER_LEAGUE_ID=test PYTHONHASHSEED=0 .venv/bin/python scripts/backtest_snap_share_2026.py`
- `SLEEPER_LEAGUE_ID=test PYTHONHASHSEED=0 .venv/bin/python scripts/backtest_snap_share_2026.py --check-2025-join`
