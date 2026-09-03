# Contributing

Thanks for contributing to Gridiron Analytics. OSS v1 stays small on purpose.

## Constraints (non-negotiable)

- **$0 forever:** no paid tiers, hosting, or databases. Call out free-tier
  rate limits instead of assuming they are fine.
- **Local-only:** bind `127.0.0.1` only. Never `--host 0.0.0.0`, no tunnels,
  no deploy steps. `hub/start.sh` stays local-only unless run with explicit
  `--lan` (which warns).
- **NFL-only, no betting logic.** No real-money features.
- **Single-league:** each user runs their own league via `SLEEPER_LEAGUE_ID`.
  Multi-league support is an explicit non-goal for OSS v1.
- **No hardcoded league IDs** in code or docs — use `SLEEPER_LEAGUE_ID` /
  placeholders.

## Ownership boundaries

- `src/ffanalytics/api.py` — backend owner. OSS PRs: document API concerns in
  `docs/RUNBOOK.md`, do not patch.
- `hub/server.py` — hub owner. OSS PRs: document proxy concerns in
  `docs/RUNBOOK.md`, do not patch.
- `FantasyHub.app/*` — macOS-only binary wrapper, left as-is.
- `hub/src/*`, `data/*`, `tests/*` — out of scope for OSS-hardening PRs.
- `pyproject.toml` — ML deps (`xgboost`, `scikit-learn`, `numpy`) stay in
  `[project.optional-dependencies] ml`; core stays
  `fastapi / uvicorn / nflreadpy / requests / pydantic / python-dotenv`.
  `hub/` must never add deps to the root `pyproject.toml`.

## Hub isolation (enforced)

After touching anything under `hub/`, run:

```bash
bash hub/verify-isolation.sh
```

It fails on `ffanalytics` imports, DB writes (`INSERT`/`UPDATE`/`DELETE`/
`DROP`/`CREATE`/`commit`), write-mode `open()`, `sqlite3.connect` without
`mode=ro`, `0.0.0.0` binds, `--host 0.0.0.0`, or runtime `POST /refresh`.

## Hub/proxy recommendations (for hub owner)

- **Log injection:** `hub/server.py` logs request paths and query strings.
  Treat them as untrusted — strip newlines/control chars before logging,
  cap length, and never interpolate raw input into shell or SQL. The proxy
  only issues parameterized read queries against a `mode=ro` connection.
- **CORS:** keep the allow-list tight (`127.0.0.1` origins only); see
  `docs/RUNBOOK.md` known-limitation TODOs for the `null`-origin decision.
- **DB path:** restrict `--db` / `FFANALYTICS_DB_PATH` to the repo `data/`
  dir (see RUNBOOK TODO).

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt        # core only
pip install -e .[ml]                   # only if you run backtests
cp .env.example .env && chmod 600 .env
SLEEPER_LEAGUE_ID=test .venv/bin/pytest -q
```

## Dependencies (pins without lockfile)

Ranges in `pyproject.toml` / `requirements.txt` stay canonical. Both files
carry a `Last-verified resolved versions` comment (6 core deps only, from
`.venv/bin/pip freeze`) — no bumps, no new deps, no hashes/lockfile.
Why no lockfile: `$0` local scope, CI installs fresh each run, so a lockfile
adds churn without benefit.

## Data files

`data/*.db*` is gitignored. Do not commit large datasets without Git LFS —
see README. Never `git rm` history to slim the repo; leave history alone.
Third-party data rules (provenance, no-redistribution, fetch-at-refresh-time;
MIT covers code only): see [DATA_NOTICE.md](../DATA_NOTICE.md).
