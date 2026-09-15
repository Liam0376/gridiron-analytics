# Spec: gsis-keyed identity (depth charts + weekly rosters)

> Status (2026-09-15): DRAFT, awaiting user confirm on the plan.
> Proposal A from the 2026-09-15 external-inspiration research. Foundational:
> B (opportunity shares) and C (ECR cross-check) both need correct
> current-team identity first.

## Problem

Every identity join in the pipeline is name-keyed, and names lie:

- `refresh.py:89` `build_sleeper_team_map` is `(norm name, POS) -> team` with
  first-seen-wins on collisions (documented limit) plus suffix normalization
  that must be maintained by hand.
- Weekly history rows carry last season's team, so any consumer that reads
  history teams directly (my 2026-09-15 backtest did) mis-teams every
  offseason mover until something patches it.
- The snap-share work depends on a hand-downloaded FantasyPros depth CSV
  (gitignored, name-keyed, preseason-frozen: it still says Tua is ATL QB1;
  live depth says Penix rank 1, Tua rank 2, status INA).

This is the same bug class as Purdy-unresolvable (2026-09-10, no box-score
row), the Kenneth Walker gsis_id gap, the A.J. Brown leading-space gsis_id,
and LAR/LA canonicalization. Four incidents, one cause: no gsis-keyed
source of current team and depth rank.

## Evidence (verified live 2026-09-15, nflreadpy, $0)

- `load_depth_charts(seasons=[2026])`: gsis_id + team + pos_abb + pos_rank,
  latest snapshot 2026-09-14T13:53:31Z (fresh). ARI: Brissett 1 / Minshew 2 /
  Beck 3. Replaces the manual CSV with keys, not names.
- `load_rosters_weekly(seasons=[2026])`: 2,963 rows, 32 teams, full identity
  spine per player — gsis_id + sleeper_id + pfr/pff/espn/yahoo IDs + team +
  week + status (ACT/INA/RES/DEV/CUT/RET/EXE) + headshot_url. Tua shows
  `ATL/INA`, matching live depth. This is the current-team source of truth;
  history teams become history only.
- `docs/research/2026-data-sources.md:24` already blesses nflverse as the
  stats source; both loaders are the same dependency, no new outbound.

## Design (proposed)

- Two new adapter functions in `src/ffanalytics/adapters/nflverse.py` (the
  only file allowed to touch nflreadpy/Polars — header contract):
  `get_depth_charts(season)` returns latest-snapshot rows only (keep `dt`
  column for audit); `get_weekly_rosters(season)` returns the roster rows.
  Both return plain list[dict], injectable `nfl_module=` like the rest.
- `refresh.py`: `build_gsis_team_map(weekly_rosters) -> {gsis: team}` and
  `gsis_depth_rank(depth_charts) -> {(gsis): rank}`. `patch_proj_teams`
  tries the gsis join first, falls back to the existing name map (kept, not
  deleted — Sleeper rookies without GSIS still need it;
  `build_rookie_rows` is unchanged).
- Caching: `data/nfl_cache/depth_<season>.json` + `rosters_weekly_<season>.json`
  (gitignored, same precedent as snaps/injuries). No schema change — patched
  teams are already what gets stored; refresh-time data stays refresh-time.
- Snap-share backtest (`scripts/backtest_snap_share_2026.py`) switches its
  depth source from the CSV to the cached depth snapshot; CSV support is
  removed from the script. The CSV file itself is user-local and gitignored —
  nothing to delete in-repo.
- Failure policy mirrors existing adapters: fetch fails -> refresh_log entry,
  keep last-good cache, never abort refresh, never crash on missing gsis.

## Gates (frozen)

- Full suite green (`SLEEPER_LEAGUE_ID=test .venv/bin/pytest -q`).
- New regression tests in the same commit: mover resolves to current team by
  gsis with zero name matching (Geno NYJ, Kyler MIN, Tua ATL, Fields KC);
  same-name collision disambiguated by gsis where the name map cannot;
  DNP-with-no-box-score resolves via rosters (Purdy case shape);
  missing/None gsis degrades to the name-map fallback, never raises.
- Measurable outcome: 2026 Week-1 backtest re-run with gsis-only identity
  (name join disabled) matches or beats the name-join V1_0.05 numbers
  (MAE 4.163 / QB 4.470); mover subset error must not regress.
- Loser -> `# REJECTED — evidence` inline, no merge (standard discipline).

## Non-goals

- B (opportunity shares/WOPR) and C (ECR) — separate specs, in that order.
- No scoring, projection-math, interval, or hub-display changes. No new deps,
  no paid data, no outbound beyond nflverse (already allowed).
