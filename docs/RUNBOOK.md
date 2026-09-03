# Runbook

Local-first operations for Gridiron Analytics. All services bind `127.0.0.1`
only — never `--host 0.0.0.0`, no tunnels, no port-forwards. `$0 forever`:
no paid services in any step below.

## Env setup

```bash
cp .env.example .env
chmod 600 .env
ls -l .env   # verify: -rw------- (owner-only; secrets stay local)
# Edit .env: set SLEEPER_LEAGUE_ID to your league ID (never commit .env).
```

Secrets hygiene: `.env` is gitignored and must stay `600`. CI runs a
non-blocking secrets-scan (gitleaks if present, else grep for api-key
patterns with `continue-on-error`) — see `.github/workflows/ci.yml`. Never
paste key values into issues, logs, or PRs; see `DATA_NOTICE.md` for
third-party data rules.

Each user runs their own single league via `SLEEPER_LEAGUE_ID` (OSS v1 is
single-league only; multi-league is an explicit non-goal).

## Start the API locally

```bash
source .venv/bin/activate
uvicorn ffanalytics.api:app --reload   # dev
uvicorn ffanalytics.api:app            # daily use
```

Or one-click (model `:8000` + read-only proxy `:8002` + Vite hub `:8001`):

```bash
bash hub/start.sh [--auto] [--no-refresh] [--force] [--no-browser]
```

**Never** add `--host 0.0.0.0` or any tunnel/port-forward — uvicorn's default
`127.0.0.1` binding is what keeps this off the internet entirely.
`hub/start.sh` stays local-only by default; LAN display requires explicit
`--lan` opt-in and prints a warning (services still bind `127.0.0.1`).

Note on process cleanup: `hub/start.sh` reclaims ports via `lsof -ti :PORT`
rather than PID files. This is deliberate — PID files go stale when a shell
is killed or the app is double-clicked twice, leaving orphaned servers on
`:8000/:8001/:8002`. `lsof` reclaim covers those cases. (OSS TODO: switch to
PID files under `logs/` plus `lsof` fallback if a contributor wants to.)
Blast-radius guard: reclaim only kills PIDs whose command matches
`python/uvicorn/vite/node/npm` (checked via `ps -o comm=`); anything else
prints a warn-and-skip line and is never killed.

## Scope (one-line reconciliation)

Personal local tool with two components: statistical model (`src/ffanalytics`)
+ read-only hub (`hub/` + proxy). (Reconciles `CLAUDE.md` "not a product"
with `AGENTS.md` "two products" — one personal tool, two components.)

## North Star + activation

- **North Star:** a warm, trustworthy draft/in-season board for your single
  private league — local-only, `$0`, NFL-only, no betting logic.
- **Activation event:** fresh clone → warm board in <10min
  (`cp .env.example .env`, set `SLEEPER_LEAGUE_ID`, `bash hub/start.sh`,
  one refresh). No instrumentation beyond the local `refresh_log` table and
  `logs/` files — no analytics, no telemetry, ever.

## Health vs ready

- `GET /health` (model `:8000`) and `GET /health` (proxy `:8002`) report
  **process liveness** — the server is up and bound to `127.0.0.1`.
- **Readiness** (data is warm) is separate: query
  `GET http://127.0.0.1:8002/hub-api/meta` and check `lastUpdated` is recent
  (≤24h) and `counts.player_stats > 0`. A `200` on `/health` with
  `player_stats: 0` means the server is alive but cold (preseason or fresh
  clone) — run a refresh before trusting the UI.

## Install the daily refresh job

`scripts/com.ffanalytics.refresh.plist` ships with a
`REPLACE_WITH_ABSOLUTE_PATH` template (4 occurrences: 1 script path + 2 log
paths + 1 `WorkingDirectory`) plus a `REPLACE_WITH_SLEEPER_LEAGUE_ID`
placeholder in `EnvironmentVariables` (with a safe `PATH`). Fill both with
this repo's absolute path and your league ID — never commit a hardcoded
`/Users/...` path or a real league ID:

```bash
REPO_ABS="$(cd "$(dirname "$0")" && pwd)"   # run from the repo root: REPO_ABS="$(pwd)"
sed -i '' "s|REPLACE_WITH_ABSOLUTE_PATH|$REPO_ABS|g" scripts/com.ffanalytics.refresh.plist
sed -i '' "s|REPLACE_WITH_SLEEPER_LEAGUE_ID|YOUR_LEAGUE_ID|g" scripts/com.ffanalytics.refresh.plist
mkdir -p logs
cp scripts/com.ffanalytics.refresh.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.ffanalytics.refresh.plist
```

`scripts/refresh_job.sh` is repo-relative (derives `REPO_ROOT` from its own
location) and creates `logs/` itself, so manual runs need no absolute paths.
`curl` uses `--max-time 300 --retry 2`; successes append
`refresh ok` with a UTC timestamp to `logs/refresh.out.log`:

```bash
bash scripts/refresh_job.sh
```

Locking: `flock -n` (or PID-file fallback on macOS without `flock`)
prevents overlapping runs (launchd + `hub/start.sh` + manual). Exit `0` on
"already in progress" is deliberate — a skipped overlap is not a failure and
must not page `launchd` error handling.

Verify the job:

```bash
launchctl list | grep fanalytics
tail logs/refresh.out.log logs/refresh.err.log
```

## Manual refresh fallback

If the laptop was asleep/closed at 7am and the launchd job didn't fire:

```bash
curl -X POST http://localhost:8000/refresh
```

Then confirm readiness via `/hub-api/meta` (see Health vs ready above).
The job is throttled to ≥60min between runs (Sleeper rate-limit courtesy);
`hub/start.sh --force` overrides the throttle.

## Backup / restore (SQLite)

The DB (`data/fantasy.db`, overridable via `FFANALYTICS_DB_PATH`) is gitignored
and created on first run. Back it up before upgrades:

```bash
# Backup (online-safe, WAL-aware — prefer over cp):
sqlite3 data/fantasy.db ".backup 'data/fantasy.db.bak-$(date +%F)'"
# Restore:
sqlite3 data/fantasy.db.restored ".restore 'data/fantasy.db.bak-YYYY-MM-DD'"
# Compact after heavy refresh cycles:
sqlite3 data/fantasy.db "VACUUM;"
```

Keep backups out of git (`data/*.db*` is ignored). For large datasets
(`data/ml/*.jsonl`, `data/nfl_cache/`), see README (Git LFS recommendation).

## Demo vs live + weather placeholders

- **Demo seed** (`scripts/seed_demo.py`, invoked by `hub/start.sh` when
  `player_stats` is empty in preseason) is clearly labeled demo data for an
  empty board — never mix it with live refresh output when reporting issues.
- **Live data** comes only from `POST /refresh` (per-source isolated;
  one source failing never aborts the others).
- **Weather semantics:** until the server crew exposes them, treat missing
  weather as placeholder — check `GET /hub-api/meta` fields `data_source`
  and `weather_status` (server crew adds) to distinguish live vs placeholder
  before trusting game-day adjustments.

## RPO / RTO (laptop-local)

- **RPO 24h** via daily 7am refresh + pre-upgrade SQLite `.backup`.
- **RTO manual restore** per the Backup/restore section above (minutes when
  the laptop is available; no failover — local-only by design).

Restore-drill checklist (quarterly, ~5min):

```bash
sqlite3 data/fantasy.db ".backup 'data/fantasy.db.bak-$(date +%F)'"
sqlite3 data/fantasy.db.restored ".restore 'data/fantasy.db.bak-$(date +%F)'"
sqlite3 data/fantasy.db.restored "PRAGMA integrity_check;"
rm data/fantasy.db.restored
curl -sf http://127.0.0.1:8002/hub-api/meta | head -c 300
```

## Known-limitation TODOs (backend / hub owners — do NOT fix from OSS side)

These are documented here instead of patched, because `src/ffanalytics/api.py`
(backend owner) and `hub/server.py` (hub owner) are out of scope for OSS
hardening PRs:

- **CORS `null` origin:** if the hub is ever served from a `file://` or
  sandboxed context, browsers send `Origin: null`. Backend owner should decide
  whether to allow-list `null` explicitly or keep rejecting it (rejecting is
  the safe default — do not blanket-allow `*`).
- **`x-request-id` propagation:** API responses should echo a request ID for
  log correlation across model → proxy → hub. Hub owner to forward the header,
  backend owner to emit it. Until then, correlate via timestamps in
  `logs/refresh.*.log` and `/tmp/fantasy-hub-*.log`.
- **`DB_PATH` allowlist:** `FFANALYTICS_DB_PATH` / `--db` currently accept any
  path. Hub owner should restrict to the repo `data/` dir (reject `..` /
  absolute escapes) so a misconfigured env can't point the read-only proxy at
  an unintended SQLite file. Until then, only set it to a path under `data/`.

## Uninstall the job

```bash
launchctl unload ~/Library/LaunchAgents/com.ffanalytics.refresh.plist
```
