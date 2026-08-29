# AGENTS.md

## Project
- Sleeper league **Fantasy Bahamas `1397736035240173568`** — 12-team full-PPR auction ($250 budget), 2 FLEX (roster: 1 QB / 2 RB / 2 WR / 1 TE / 2 FLEX / 1 K / 1 DEF, 4 BN + 2 IR via `settings.reserve_slots=2`, not in `roster_positions`; Sleeper returns `['QB','RB','RB','WR','WR','TE','FLEX','FLEX','K','DEF','BN','BN','BN','BN']`). Official Reglamento 2026 at `~/Downloads/Reglas Fantasy Bahamas.md` ($750 MXN entry, prizes $5,500/$2,500/$1,000, trade deadline week 11, vote 6 needed). Verify via API, never hardcode — `sleeper.get_league_settings()` is source of truth.
- `$0 cost forever`, fully local, FastAPI binds `127.0.0.1` only (`docs/RUNBOOK.md:6`). No paid deps, no cloud, no public exposure. Only outbound to free APIs: Sleeper, nflverse/nflreadpy, Open-Meteo.

## Stack & Env
- Python >=3.12, `src` layout. `pyproject.toml:14` sets `pythonpath = ["src"]`. Interpreter `.venv/bin/python` (also `venv/` exists; `python` bare fails on this host). `/opt/homebrew/bin/python3` (3.14) is system fallback per backtest scripts.
- **Required:** `SLEEPER_LEAGUE_ID=1397736035240173568` — `src/ffanalytics/config.py:4` raises `RuntimeError` if unset. All tests need it (even `test_api.py` transitively imports `config`).
- **Optional:** `FFANALYTICS_DB_PATH` overrides `data/fantasy.db` (`config.py:11`). DB is `SQLite WAL` (`db.py:14`); `data/*.db` gitignored.
- No lint/typecheck/formatter/CI/opencode.json in repo — don't look for it.

## Commands
- Tests (unit): `SLEEPER_LEAGUE_ID=1397736035240173568 .venv/bin/pytest -q` — 68 pass, 4 skipped without `RUN_INTEGRATION`.
- Single test: `SLEEPER_LEAGUE_ID=1397736035240173568 .venv/bin/pytest tests/test_rating.py::test_update_winner_rating_increases -v`
- Adapter suite: `SLEEPER_LEAGUE_ID=1397736035240173568 .venv/bin/pytest tests/adapters/test_sleeper.py -v`
- Live integration (hits Sleeper, asserts PPR/FLEX): `SLEEPER_LEAGUE_ID=1397736035240173568 RUN_INTEGRATION=1 .venv/bin/pytest tests/test_integration.py -v` (`tests/test_integration.py:7`).
- Dev server: `.venv/bin/uvicorn ffanalytics.api:app --reload` — **never** `--host 0.0.0.0`. Manual refresh: `curl -X POST http://127.0.0.1:8000/refresh`.
- Hub (isolated product in `hub/`): one-click `bash hub/start.sh` → model `:8000` + proxy `:8002` (mode=ro) + Vite `:8001`, opens browser. `Ctrl+C` kills all. Verify isolation: `bash hub/verify-isolation.sh`. See `hub/README.md`.
- Backtests: `SLEEPER_LEAGUE_ID=1397736035240173568 /opt/homebrew/bin/python3 /private/tmp/claude-501/-Users-liam/88d4447f-857f-4e47-88fe-c423d3893260/scratchpad/backtest_final.py` — requires `sys.path.insert(0,"src")` (already in scripts). Stats come from cached `nfl_cache/` (see below), no network.

## Architecture
- `api.py:22` — FastAPI, module-level `_CACHE:52`, `POST /refresh:231` populates via `run_refresh_with_data()`; all `/recommendations/*` + `/news` return `503` until warm.
- `config.py` — single source of truth for constants (`FEATURES`, `MIN_SHADOW_SAMPLES=20`, `FLEX_SCARCITY_MULTIPLIER=1.05`, `WEATHER_WIND_PENALTY_PER_MPH`). Every entry needs inline `why`; rejected heuristics stay as `# tested and REJECTED — evidence: ...`.
- `db.py:9` + `schema.sql` — `get_connection()` auto-creates parent dirs, `PRAGMA journal_mode=WAL`, `row_factory=sqlite3.Row`. Tables: `team_ratings`, `refresh_log`, `shadow_recommendations`, `league_settings`, `rosters`, `player_stats`, `sleeper_matchups`, `news_data`, `weather`.
- `refresh.py:49` — per-source isolation (`sleeper` / `nflverse` / `news` / `ratings`); each logs to `refresh_log`, never aborts others. Persists JSON blobs + `weather` (currently placeholder `40.0,-74.0` at `refresh.py:256`).
- `adapters/{sleeper,nflverse,news,schedule,weather}.py` — injectable deps (`session=` for `requests`, `nfl_module=` for nflreadpy) for `tests/adapters/*` mocking without network. `nflverse.py` is the only file allowed to touch Polars — always returns `list[dict]`.
- `rating.py` / `rating_updates.py` — Glicko-style Elo `Rating(value, deviation)`, `DEFAULT_RATING=1500±350`, `decay_for_inactivity`. Adapted from tennis `core/elo.py` discipline.
- `conformal.py` — `qhat`/`interval` for 80% calibrated intervals, not point estimates.
- `scoring.py` — league-aware `calculate_fantasy_points()` via `DEFAULT_SCORING` (now mirrors Sleeper 2026-08-28: `pass_cmp_40p/rush_40p/rec_40p=1.0` + `pass_td_40p/rush_td_40p/rec_td_40p=1.0`, not 2.0 as in early backtests) + `FLEX_SCARCITY_MULTIPLIER`. Full dict includes `fgm_0_19`..`fgm_60p`, `fgmiss`, `xpm/xpmiss`, `fum_lost`/`fum_rec`/`ff`, etc. — but live truth is `sleeper.get_league_settings()` (bonuses `pts_allow_*`, `def_td`, etc. are in settings with 0 default). Cross-check with Sleeper API each season; fallback `DEFAULT_SCORING` only for cold starts.
- `projection.py:49` — `calculate_projection(player_stats, team_ratings, historical_residuals, weather, scoring_settings, use_features=True)`. `use_features=True` = retroactive (actual stats, MAE=0.98); `use_features=False` = prediction (stats from `stat_projector`, feature adjustments **off** — they add bias on projected stats).
- `stat_projector.py` — stat projection engine (the model's core). See Model section below. No commits made yet for ML upgrade; changes uncommitted on this branch.
- `decision.py` / `shadow.py` — start/sit, waiver, trade logic; shadow gates promotion on `MIN_SHADOW_SAMPLES=20`.
- Scheduling: `scripts/refresh_job.sh:6` = `curl -sf -X POST http://localhost:8000/refresh`; `com.ffanalytics.refresh.plist` daily 07:00 via `launchd` (`docs/RUNBOOK.md:11`).

## Scoring & Prediction Model (current best)

- **Scoring engine** (`scoring.py`): essentially perfect retroactive — **MAE=0.98** on actual stats → fantasy points. Don't touch unless Sleeper settings change.
- **Stat projector** (`stat_projector.py:12`): predicts future weekly *stats* per player, then `projection.py` converts to points. Pipeline (each backtested individually, 2024-2025 N=10,356 weeks 4-18):
  1. Weighted-recent avg: last 5 games at 2×
  2. TD regression to position mean (30% pull) — `POS_TD_MEANS` 3-season means (e.g., QB `passing_tds` 1.7, TE `receiving_tds` 0.22)
  3. Usage trend: 15% weight on 3-game vs season for volume stats (`rushing_yards`, `receiving_yards`, `receptions`, `passing_yards`)
  4. Vegas implied total: TDs 50% damped (`VEGAS_TD_DAMPING=0.50`), yards 25% (`VEGAS_YARD_DAMPING=0.25`), league avg 22.2 (`LEAGUE_AVG_IMPLIED_TOTAL`)
  5. Weather: wind >15 mph `1.5%/mph` (`WIND_PENALTY_PER_MPH=0.015`), cold <32°F `0.3%/deg`
  6. Prior-season blend: only if `<3` games played this season (`MIN_GAMES_FOR_SEASON=3`), blend with prior year
- **Current backtest performance (weeks 4-18, true scoring via `scoring.py`, N=10,351):** `MAE=4.563, Corr=0.648, Pairwise=74.1%, K 4.09` — `projection.py:use_features=False`. Early published `4.163/0.692/77.7%` was K-zeroed (`backtest_final.py` ignored `fg_*` → K 0.005, -0.416 bias). Per-position true: QB ~7.3, RB ~4.5, WR ~4.5, TE ~3.6, K 4.09. Expanding-mean floor ~4.4-4.5 → gap ~0.10-0.15, not 0.5 — weekly noise dominates.
- **Important nflverse quirks:** use `team` field (NOT `recent_team`) for abbreviation; keys are `passing_yards`, `passing_tds`, `rushing_yards`, etc. (nflverse naming, not `pass_yd`).
- **ML upgrade tested and REJECTED (honest OOS val 2025, true scoring):** PBP opportunity (5,430/5,365/5,411 via `pbp.py`) → 38-col XGB point-level `val 4.514 vs true stat val 4.474 (+0.04 worse)`, no-K `4.556` also fail; ensemble `w=0.40` `4.45 >4.474` fail OOS (combined 4.448 would pass but is in-sample 2024). Stat-level 16 boosters `val 4.463 vs 4.474 (+0.011 win)` but `corr 0.658 vs 0.692` and `pw 74.5 vs 74.1` narrow, combined `4.307 vs true 4.563` overfit gap 0.316 — not worth dependency for 0.01 MAE. Keep `stat_projector.py` as production; `data/models/xgb_meta.json`+`stat_level/meta.json: REJECTED` with `stat_projector.py:15` evidence.

## Tested and REJECTED — Do NOT Re-Test

18 head-to-head methods, each with measured evidence in `stat_projector.py:1` header and scratchpad JSON:

- **Opponent defense factors:** rho=0.05–0.34 year-to-year, hurts corr 0.690→0.687 even with multi-season shrinkage + 16-game minimums. No signal at this granularity.
- **EWMA (alpha=0.3):** weighted-recent wins on all metrics.
- **Home/away:** <0.1% impact on any metric.
- **Full Vegas scaling (all stats equally):** MAE 4.16→4.24, yards overshoot when scaled to implied total.
- **Rest days:** negligible.
- **Feature adjustments (`target_share`, `snap_pct`, `opponent_positional_rating`) in prediction mode:** designed for actual stats (retroactive 0.98), add systematic bias on projected stats. `projection.py:49` must be called `use_features=False` for predictions.
- **Prior-season blend all weeks:** improves bias but hurts MAE; keep early-season only.

## Cached Data & Backtests (no network needed)

- **Cache location:** `/private/tmp/claude-501/-Users-liam/88d4447f-857f-4e47-88fe-c423d3893260/scratchpad/nfl_cache/` — `stats_2023.json`, `stats_2024.json`, `stats_2025.json` (player-week stats), `schedule_2023.json` etc. (includes Vegas lines, weather, rest).
- **Backtest scripts (scratchpad):** `backtest_5methods.py`, `backtest_extended.py`, `backtest_final.py`, `backtest_vegas_weather.py` + `cache_nfl_data.py`. Results `*.json` in same dir (e.g., `backtest_final_results.json`: final model MAE=4.163). Run with `sys.path.insert(0,"src")` + `SLEEPER_LEAGUE_ID` env (see scripts).
- **Do not re-cache to different path** without updating scripts — they hardcode this temp path.

## Hard Constraints

- `$0 forever` — no paid tiers/trials/hosting/DB. Flag free-tier limits explicitly.
- Fully local — never `0.0.0.0`, no tunnels, no deploy. Only outbound to free APIs.
- NFL/fantasy only, no betting. Single private league — don't add multi-league, public site, auth, or monetization.
- **Ask permission before** `/opt/homebrew/bin/pip3 install xgboost scikit-learn numpy --break-system-packages` — user denied once. Propose flag/version first.

## Gotchas

- "Who should I start?" — query `data/fantasy.db` or `http://127.0.0.1:8000` directly via Bash; don't tell user to `curl`.
- Season scoring can be edited — always fetch via `sleeper.get_league_settings()`.
- Active branch `implement-fantasy-football-analytics`; all changes currently uncommitted — check `git status` before committing, don't `git commit -a` blindly.
- `data/fantasy.db` may not exist on fresh clone — `db.get_connection()` + `init_schema()` creates it; tests use `tempfile` isolation.
- `hub/` is a separate product in same repo — never `import ffanalytics` from hub, never write `fantasy.db` from hub (`mode=ro`), hub owns `hub/package.json` not root `pyproject.toml`. See `hub/DESIGN.md` and `hub/verify-isolation.sh`.
- `SLEEPER_LEAGUE_ID` must be `1397736035240173568` for real-league runs; `test` works for unit tests but fails live integration assertions (expects PPR/FLEX/TFL values).
