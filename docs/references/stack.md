# Stack & Commands

Read before running tests or dev servers. Backpressure: run checks, fix self — don't narrate lint.

- Python >=3.12, `src` layout, `pythonpath=["src"]`. Use `.venv/bin/python`.
- Required: `SLEEPER_LEAGUE_ID` or `config.py` raises. `1397736035240173568` live, `test` for unit.
- Optional: `FFANALYTICS_DB_PATH` overrides `data/fantasy.db` (WAL, auto-creates). `data/*.db*` gitignored.
- No lint/format/CI in repo — don't hunt for ruff/black/eslint.

## Commands

- Tests: `SLEEPER_LEAGUE_ID=1397736035240173568 .venv/bin/pytest -q` (68 pass, 4 skipped; `RUN_INTEGRATION=1` hits Sleeper)
- Single: `.venv/bin/pytest tests/test_rating.py::test_update_winner_rating_increases -v`
- Integration: `RUN_INTEGRATION=1 .venv/bin/pytest tests/test_integration.py -v`
- Dev: `.venv/bin/uvicorn ffanalytics.api:app --reload` — `503` until `POST /refresh`
- Isolation: `bash hub/verify-isolation.sh` (fail if hub imports `ffanalytics`/writes/`0.0.0.0`)
- Launch: `bash hub/start.sh [--auto] [--no-refresh] [--force] [--no-browser]` or `StartFantasyHub.command`; `--auto` skips refresh if <60m, seeds via `scripts/seed_demo.py` when empty. Cache quirk: `data/nfl_cache/` primary, scratch `/private/tmp/...` fallback — regenerate to `data/nfl_cache/` if missing.

## Gotchas

- `git status` before `commit -a` — large uncommitted sets across sessions
- `data/ml/full_2023_2025.jsonl` ~74MB committed — >50MB warning, consider LFS
- Branch `implement-fantasy-football-analytics` (not `master`), remote `Liam0376/gridiron-analytics`
- Sleeper IDs opaque — resolve via `api.sleeper.app/v1/players/nfl` (`hub/server.py:get_sleeper_player_name()` cached)
