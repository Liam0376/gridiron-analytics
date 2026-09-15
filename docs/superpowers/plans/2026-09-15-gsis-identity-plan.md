# Plan: gsis-keyed identity (depth charts + weekly rosters)

> Status (2026-09-15): DRAFT — stop for confirm, do not implement yet.
> Spec: `docs/superpowers/specs/2026-09-15-gsis-identity-spec.md`.

## Tasks

- [ ] **1. Adapters (no prod wiring yet).** Add `get_depth_charts(season,
  nfl_module=None)` and `get_weekly_rosters(season, nfl_module=None)` to
  `src/ffanalytics/adapters/nflverse.py`, same `_retry` + plain-list[dict]
  pattern as `get_player_ids`. Depth returns latest-`dt` snapshot rows only.
  Unit tests with a fake `nfl_module=` (no network): snapshot selection,
  Polars never leaks (assert plain dicts).
  Verify: `SLEEPER_LEAGUE_ID=test .venv/bin/pytest tests/adapters/ -q`.
- [ ] **2. Refresh wiring (gsis-first, name fallback).** Add
  `build_gsis_team_map` + gsis rank lookup in `src/ffanalytics/refresh.py`;
  extend `patch_proj_teams` to try `{gsis}` before `{name, pos}`.
  Cache snapshots to `data/nfl_cache/depth_<season>.json` /
  `rosters_weekly_<season>.json` with last-good fallback + `refresh_log`
  entry on fetch failure. Regression tests per the spec's gate list
  (movers, collision, DNP-without-box-score, None-gsis fallback).
  Verify: `SLEEPER_LEAGUE_ID=test .venv/bin/pytest tests/test_refresh.py -q`.
- [ ] **3. Backtest cutover.** `scripts/backtest_snap_share_2026.py` reads
  the cached depth snapshot instead of the FantasyPros CSV; remove CSV
  support from the script. Re-run default mode + `--check-2025-join`
  (2025 path keeps its week-1-snap proxy — no depth history exists there —
  and must still reproduce published numbers exactly).
  Verify: `SLEEPER_LEAGUE_ID=test PYTHONHASHSEED=0 .venv/bin/python
  scripts/backtest_snap_share_2026.py` (expect gsis-only run at or better
  than MAE 4.163 / QB 4.470) plus the `--check-2025-join` PASS line.
- [ ] **4. Full gates.** `SLEEPER_LEAGUE_ID=test .venv/bin/pytest -q`
  (231 pass / 4 skipped baseline) green. No hub changes, so no isolation
  script run needed (and the gate is gone anyway).

## Explicitly not doing

- Opportunity shares, ECR ingestion, scoring/projection math, hub display,
  new dependencies, schema migrations, deleting the name-map fallback.

## Verify (whole plan)

- `SLEEPER_LEAGUE_ID=test .venv/bin/pytest -q`
- `SLEEPER_LEAGUE_ID=test PYTHONHASHSEED=0 .venv/bin/python scripts/backtest_snap_share_2026.py`
- `SLEEPER_LEAGUE_ID=test PYTHONHASHSEED=0 .venv/bin/python scripts/backtest_snap_share_2026.py --check-2025-join`
