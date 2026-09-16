# Fix-all Spec — 2026-09-15 (branch fix/oss-limitations)

## 1. Trade hub fallback (real gap)

`hub/src/api.js:253` falls back to `GET /hub-api/trade`, but `hub/server.py:1313-1343`
has no `/trade` branch, so it 404s and the tab shows "no result" when `:8000`
is down. All other tabs degrade to DB. Fix: add `handle_trade` in
`hub/server.py` that resolves `team_a_id/team_b_id` (roster_id or owner_id)
via the `rosters` blob, joins `sleeper_xwalk` to `ros_projections.ros_points`
for per-player ROS value, sums per side, applies the model fair threshold
`abs(diff) < 5` (`decision.py:670`), and returns `{winner, value_difference,
recommendation}` so `trade.js:352-363` works unchanged. Response carries
`meta.source: hub-fallback:ros-points` so it never claims VBD dollars.
Missing tables or unknown teams return 503 JSON (matches model cold
behavior), not 500. Regression test in `tests/test_hub_server.py` seeds
rosters + xwalk + ros rows and asserts winner shape.

## 2. Weather slate shows live forecasts (stale placeholder path)

`handle_matchups` (`hub/server.py:1986`) reads `wind` from the schedule cache,
but schedule wind/temp are observed post-game values, null preseason — so the
slate shows wind 0 even though `weather` holds live Open-Meteo rows per
stadium (verified 2026-09-15: real coords, temps, wind). Fix: vendor
`STADIUM_COORDS` team map in `hub/server.py` (mirror of
`adapters/weather.py`, comment points at source; hub never imports
ffanalytics), join latest `weather` row per home-team coords in
`handle_matchups`, fall back to schedule wind when no row. Keep
`weather_status` meta as-is. Update `hub/README.md:57,87` weather lines that
claim every badge is placeholder. Regression test seeds weather rows and
asserts slate wind comes from the table.

## 3. QB/K interval calibration (measured, not guessed)

`data/models/coverage_2025.json`: displayed coverage QB 0.79, K 0.59 vs 0.80
target. QB factor 1.45 is near `WIDTH_MAX` headroom; K factor 0.55 overshoots
narrow. Fix: script recomputes 2025 holdout displayed coverage (weeks 4-18,
true OOS via `build_weekly_projections`, actuals via `scoring.py`) at current
then candidate factors; ship the smallest QB increase / K increase that lands
both within 0.77-0.83 without dropping overall below 0.80. Change factors in
`projection.py:15`, `decision.py:28-29`, hub mirror, bump interval version
together (`test_interval_parity.py:13-18` gates this). Append measurement to
`coverage_2025.json` note or new artifact, never retune silently.

## 4. Preseason seed path (verify only)

`scripts/seed_demo.py` + `hub/start.sh --auto` cover empty boards. Verify the
seed runs green with `SLEEPER_LEAGUE_ID=test` into a temp DB. No code change
expected.

## Non-goals

No scoring changes, no new endpoints on `:8000`, no `api.py`/`server.py`
structural changes beyond the two handlers above, no lockfile, no deploy
targets (local-only stands).
