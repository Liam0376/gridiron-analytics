# AGENTS.md

## Project
- Personal, single-user tool for one Sleeper league — **Fantasy Bahamas `1397736035240173568`**, 12-team full-PPR auction ($250 budget), 2 FLEX (roster `['QB','RB','RB','WR','WR','TE','FLEX','FLEX','K','DEF','BN','BN','BN','BN']` + `reserve_slots=2` IR, not in `roster_positions`). Reglamento 2026 at `~/Downloads/Reglas Fantasy Bahamas.md`. **Never hardcode scoring/roster settings** — `sleeper.get_league_settings()` is the source of truth; league scoring can be edited mid-season.
- `$0 cost forever`, fully local. FastAPI and Vite bind `127.0.0.1` only — never `--host 0.0.0.0`, no tunnels, no deploy. Outbound calls only to free APIs (Sleeper, nflreadpy/nflverse, Open-Meteo).
- Two independent products in one repo: **model** (`src/ffanalytics`, root `pyproject.toml`) and **hub** (`hub/`, its own `package.json`). See Hub isolation below — this is enforced by a script, not just convention.
- Primary interface is direct DB/API queries, not a CLI — for "who should I start" style questions, query `data/fantasy.db` or `http://127.0.0.1:8000` directly via Bash rather than telling the user to run curl themselves (`CLAUDE.md`).

## Stack & Env
- Python >=3.12, `src` layout, `pyproject.toml` sets `pythonpath = ["src"]`. Use `.venv/bin/python` (bare `python`/`python3` may resolve to system 3.14 without deps installed).
- **Required:** `SLEEPER_LEAGUE_ID` env var or `config.py` raises `RuntimeError` at import time — every test run and script needs it. Use the real ID `1397736035240173568` for anything touching live league data/integration tests; `test` works for unit tests that don't assert real values.
- **Optional:** `FFANALYTICS_DB_PATH` overrides `data/fantasy.db` (SQLite, WAL mode). `data/*.db*` is gitignored — DB doesn't exist on fresh clone, `db.get_connection()` creates it.
- No lint/format/typecheck tooling and no CI configured in this repo (no ruff/black/mypy/eslint, no `.github/workflows`) — don't hunt for one.

## Commands
- Tests: `SLEEPER_LEAGUE_ID=1397736035240173568 .venv/bin/pytest -q` — 68 pass, 4 skipped (skips need `RUN_INTEGRATION=1`, hits real Sleeper API).
- Single test: `SLEEPER_LEAGUE_ID=1397736035240173568 .venv/bin/pytest tests/test_rating.py::test_update_winner_rating_increases -v`
- Live integration (hits network, asserts real PPR/FLEX/league values): `SLEEPER_LEAGUE_ID=1397736035240173568 RUN_INTEGRATION=1 .venv/bin/pytest tests/test_integration.py -v`
- Model dev server: `.venv/bin/uvicorn ffanalytics.api:app --reload`. All `/recommendations/*` and `/news` return `503` until warmed via `POST /refresh`.
- Hub isolation check (run after touching anything in `hub/`): `bash hub/verify-isolation.sh` — fails the check (not just a lint warning) if hub imports `ffanalytics`, writes to the DB, or binds `0.0.0.0`.
- One-click launch (starts model `:8000` + read-only proxy `:8002` + Vite hub `:8001`, opens browser): `bash hub/start.sh [--auto] [--no-refresh] [--force] [--no-browser]`, or double-click `StartFantasyHub.command` (root) / `hub/FantasyHub.command`. `--auto` refreshes if stale without prompting; refresh is skipped if last run was <60min ago (Sleeper rate-limit courtesy) unless `--force`. In preseason (empty `player_stats`), `start.sh` auto-runs `scripts/seed_demo.py` so the hub always shows a populated board.
- Backtests / ML dataset builds (`scripts/backtest_ml.py`, `scripts/build_ml_dataset.py`): read from `data/nfl_cache/` first, with a hardcoded fallback to a `/private/tmp/claude-501/.../scratchpad/nfl_cache/` path from a prior session — that scratch path is machine/session-specific and will not exist for a new agent; if a script errors on missing cache, regenerate into `data/nfl_cache/` rather than trying to recreate the scratch dir.

## Architecture
- `api.py` — FastAPI, in-memory `_CACHE`, `POST /refresh` populates it via `run_refresh_with_data()`.
- `config.py` — single source of truth for tunable constants (`FEATURES`, `MIN_SHADOW_SAMPLES`, `FLEX_SCARCITY_MULTIPLIER`, weather penalties). Every entry has an inline `why`; rejected heuristics are kept as `# tested and REJECTED — evidence: ...` comments, not deleted. Follow this convention for any new constant.
- `db.py` + `schema.sql` — `get_connection()` auto-creates parent dirs, WAL mode, `row_factory=sqlite3.Row`. Tables: `team_ratings`, `refresh_log`, `shadow_recommendations`, `league_settings`, `rosters`, `player_stats`, `injury_status`, `sleeper_matchups`, `news_data`, `weather`.
- `refresh.py` — each data source (`sleeper` / `nflverse` / `news` / `ratings`) is isolated: failures are logged to `refresh_log` and don't abort the others.
- `adapters/{sleeper,nflverse,news,schedule,weather,pbp}.py` — all take injectable deps (`session=` for requests, `nfl_module=` for nflreadpy) so `tests/adapters/*` can mock without network. `nflverse.py` is the only file that touches Polars; everything else works with `list[dict]`. nflverse field quirk: use `team` (not `recent_team`) for team abbreviation.
- `scoring.py` — `DEFAULT_SCORING` is only a cold-start fallback; live truth is always `sleeper.get_league_settings()` since league scoring can be edited season to season.
- `projection.py` — `calculate_projection(..., use_features=True)` is for retroactive scoring of actual stats (near-perfect, MAE≈0.98). `use_features=False` is for real predictions on projected stats — feature adjustments (target_share, snap_pct, opponent rating) are deliberately **off** in this mode because they were tested and add bias when applied to projected (not actual) stats. Don't flip this without re-reading `stat_projector.py`'s rejected-methods notes.
- `stat_projector.py` — the projection model. Weighted-recent avg (last 5 games ×2) → TD regression to position mean → usage trend blend → Vegas-implied-total damping → weather penalty → prior-season blend if `<3` games played. Header comment + `data/models/*/meta.json` document ~18 rejected alternatives (opponent defense factors, full Vegas scaling, home/away, rest days, etc.) with the evidence that killed each — read before re-testing any of them.
- `src/ffanalytics/ml/` (`features.py`, `train.py`, `train_stat_level.py`) — XGBoost point-level and stat-level models were built and backtested but **rejected as production**: gains were within noise (~0.01–0.05 MAE) and not worth the new dependency. `stat_projector.py` remains the production path; `data/models/xgb_meta.json` and `data/models/stat_level/meta.json` record the REJECTED verdict and evidence.
- `decision.py` / `shadow.py` — start/sit, waiver, trade recommendation logic. New rules gate on `shadow.py` accumulating `MIN_SHADOW_SAMPLES` before being trusted live.
- Scheduled refresh: `scripts/refresh_job.sh` (`curl -X POST http://localhost:8000/refresh`) via `launchd` + `com.ffanalytics.refresh.plist`, daily. Manual fallback documented in `docs/RUNBOOK.md`.

## Hub (`hub/`) — isolation is enforced, not optional
- `hub/server.py` is a **read-only** proxy: opens `fantasy.db` with `mode=ro`, never writes, never calls `POST /refresh`, binds `127.0.0.1:8002`.
- `hub/` must never `import ffanalytics` and must not add deps to root `pyproject.toml` — it owns `hub/package.json` (Vite) independently. `rm -rf hub/` must leave the model's test suite green.
- Any change under `hub/` should be followed by `bash hub/verify-isolation.sh` — it's a real gate (grep-based checks for imports, DB writes, `0.0.0.0` binds), not a suggestion. See `hub/DESIGN.md` and `hub/README.md` for the full contract.
- `scripts/seed_demo.py` (moved out of `hub/` specifically to satisfy the isolation check — it imports `ffanalytics` and writes to the DB) seeds demo projections for the preseason/empty-DB case; it's invoked by `hub/start.sh`, not meant to be hub-owned code.

## Hard Constraints
- `$0 forever` — no paid tiers, trials, hosting, or DB. Call out free-tier limits (rate limits, quotas) explicitly instead of assuming they're fine.
- Fully local — never `0.0.0.0`, no tunnels, no deploy step.
- NFL/fantasy only, no real-money betting logic. Single private league — don't add multi-league support, public site, auth, or monetization without being asked.
- Ask before installing new heavy deps (e.g. `pip install xgboost scikit-learn numpy --break-system-packages`) — flag/version tradeoffs first; user has denied ad hoc installs before.

## Gotchas
- `git status` before committing — don't `git commit -a` blindly; this repo has had large uncommitted working sets across sessions.
- `data/ml/full_2023_2025.jsonl` is ~74MB and already committed — pushing exceeds GitHub's 50MB soft warning threshold (not a hard block, but flag it if adding more large data files; consider Git LFS for anything bigger).
- Active branch is `implement-fantasy-football-analytics` (not `master`); repo is pushed to a public GitHub remote (`origin`, `Liam0376/gridiron-analytics`) on this branch.
- Sleeper trending/waiver player IDs are opaque numeric strings — resolve via `https://api.sleeper.app/v1/players/nfl` (full player dict keyed by ID) before displaying to the user; `hub/server.py`'s `get_sleeper_player_name()` and `adapters/news.py`'s `get_trending_adds()` both do this now, cached in-process.
</content>
