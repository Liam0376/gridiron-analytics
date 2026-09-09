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
- `db.py` + `schema.sql` — WAL, `row_factory=sqlite3.Row`, tables: `team_ratings`, `refresh_log`, `shadow_recommendations`, `league_settings`, `rosters`, `player_stats`, `injury_status`, `sleeper_matchups`, `news_data`, `weather`
- `refresh.py` — isolated sources, failures → `refresh_log` not abort
- `adapters/{sleeper,nflverse,news,schedule,weather,pbp}.py` — injectable `session=`/`nfl_module=`, mockable. `nflverse.py` only Polars. Quirk: `team` not `recent_team`.
- `scoring.py` — `DEFAULT_SCORING` cold fallback; live = `sleeper.get_league_settings()`
- `projection.py` — `use_features=True` retro (MAE≈0.98), `False` for predictions (tested bias).
- `stat_projector.py` — 5-game ×2 → TD regression → usage blend → Vegas damping → weather → prior blend if <3 games. 18 rejected in header + `data/models/*/meta.json`.
- `ml/` — XGBoost REJECTED (0.01–0.05 MAE noise). Production = `stat_projector.py`.
- `decision.py`/`shadow.py` — gate on `MIN_SHADOW_SAMPLES`
- Scheduled: `scripts/refresh_job.sh` via `launchd` + `RUNBOOK.md`

## Hub isolation — enforced, not optional

- `hub/server.py` — `mode=ro`, never write, never `POST /refresh`, `127.0.0.1:8002`
- `hub/` never `import ffanalytics`, never deps to root `pyproject.toml`, owns `hub/package.json`. `rm -rf hub/` must keep model tests green.
- `bash hub/verify-isolation.sh` after any `hub/` change — grep gate for imports/DB/`0.0.0.0` (`hub/DESIGN.md`, `hub/README.md`)
- `scripts/seed_demo.py` seeds empty preseason, invoked by `hub/start.sh`
