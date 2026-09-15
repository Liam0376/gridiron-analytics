# Architecture — Gridiron Analytics

Moves engineering discipline + architecture from CLAUDE.md/AGENTS.md. Read before touching model/hub.

## Engineering discipline (tennis-ml reference)

Ref: `.claude/worktrees/tennis-analytics-web/backend/` — sport math NOT reusable, architecture is:
- `core/elo.py` — Elo/Glicko w/ time-decay, K-decay, RD uncertainty → team/pos ratings.
- `config.py` — every feature `why` inline; rejected kept as `# REJECTED — evidence: ...`
- `core/math.py:conformal_qhat` — calibrated confidence.
- `shadow.py`/`evaluacion.py` — shadow + backtest before live (`MIN_MUESTRA_SHADOW`).
- `api.py` — in-memory `_CACHE`, `/refresh`, health endpoint.
- Config single source of truth, no magic numbers.

Follow: rejected → inline `# REJECTED` comment, not deletion.

## Stack layout

- `api.py` — in-memory `_CACHE`, `POST /refresh` via `run_refresh_with_data()`
- `config.py` — `FEATURES`, `MIN_SHADOW_SAMPLES`, `FLEX_SCARCITY_MULTIPLIER`, weather. Inline `why`.
- `db.py` + `schema.sql` — WAL, `row_factory=sqlite3.Row`, tables: `team_ratings`, `refresh_log`, `shadow_recommendations`, `league_settings`, `rosters`, `player_stats`, `injury_status`, `sleeper_matchups`, `news_data`, `weather`, `market_consensus`, `draft_picks`, `league_transactions`, `prop_lines`, `sleeper_xwalk`
- `refresh.py` — isolated sources, failures → `refresh_log` not abort
- `adapters/{sleeper,nflverse,news,schedule,weather,pbp,fantasypros,fantasypros_csv,fantasypros_projections,statsguy}.py` — injectable `session=`/`nfl_module=`, mockable. `nflverse.py` only Polars. Quirk: `team` not `recent_team`.
- `scoring.py` — `DEFAULT_SCORING` cold fallback; live = `sleeper.get_league_settings()`
- `projection.py` — `use_features=True` retro (MAE≈0.98), `False` for predictions (tested bias).
- `stat_projector.py` — 5-game ×2 → TD regression → usage blend → Vegas damping → weather → prior blend if <3 games. 18 rejected in header + `data/models/*/meta.json`.
- `ml/` — XGBoost REJECTED (0.01–0.05 MAE noise). Production = `stat_projector.py`.
- `decision.py`/`shadow.py` — gate on `MIN_SHADOW_SAMPLES`
- Scheduled: `scripts/refresh_job.sh` via `launchd` + `RUNBOOK.md`

## Hub — isolation dropped

- `hub/` may import `ffanalytics` and share deps with the root `pyproject.toml`
  going forward (Liam lifted the isolation rule 2026-09-15; the CI isolation
  job is gone). Existing vendored mirrors stay until refactored — no flag day.
- `hub/verify-isolation.sh` is kept for optional use, not enforced.
- Still true: `hub/server.py` runs `mode=ro`, never `POST /refresh`;
  `scripts/seed_demo.py` seeds empty preseason, invoked by `hub/start.sh`.
