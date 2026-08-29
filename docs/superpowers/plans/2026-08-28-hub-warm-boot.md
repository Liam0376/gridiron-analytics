# Hub Warm-Boot — Link Hub Start to Fully-Ready Model (Plan Only, No Build)

> **Status:** PLAN — do not implement until user says `build`. This doc graphs the dependency chain for "hub up = model warm, not just listening".

## Goal

When the user runs `bash hub/start.sh` (or double-clicks `hub/FantasyHub.command`), the whole system — not just the HTTP listeners — is **verified warm** before the browser opens. Warm = SQLite WAL has this week's data, `_CACHE` is populated, and the hub's staleness badge will show `fresh`.

Today `hub/start.sh` only waits for `GET /health = 200`. That proves the processes are alive, not that the *data* is usable. In preseason/sleep-wake, the user otherwise sees empty tables until they remember `curl -X POST /refresh`.

## Isolation Contract (unchanged)

- Hub never writes `fantasy.db`; model remains the only writer (via `src/ffanalytics/refresh.py:49` per-source isolation).
- Hub only triggers the model's *existing* `POST /refresh` endpoint — no direct adapter calls, no new tables, no `import ffanalytics` in hub code.
- All 3 processes stay `127.0.0.1` (`:8000`, `:8002`, `:8001`). No `0.0.0.0`, no cloud, no tokens.

## Current vs. Planned Flow (to be graphed)

```
Current (process-warm only):
  hub/start.sh → uvicorn :8000 (health) → hub/server.py :8002 (mode=ro) → vite :8001 → open browser
                                          ↓
                                  if cache cold: hub shows "cache cold — run curl"

Planned (data-warm):
  hub/start.sh
    ├─ 1. ensure DB + schema (data/fantasy.db exists else db.get_connection + init_schema)
    ├─ 2. check staleness (hub-api/meta.lastUpdated + refresh_log + _compute_nfl_week)
    ├─ 3. decide: fresh (<24h) → skip | stale/cold → prompt/auto POST /refresh
    ├─ 4. stream refresh (sleeper/nflverse/news/ratings parallel, never abort on one failure)
    ├─ 5. wait until (health=ok AND (cache warm OR DB snapshot has player_stats>0))
    └─ 6. open browser — Dashboard already shows "fresh"
```

## Staleness Decision (mirrors spec's "visible stale as of [timestamp]")

- **Fresh:** `lastUpdated` within 24h AND `week == _compute_nfl_week()` → no refresh.
- **Stale:** `lastUpdated` 24–72h ago OR `week` mismatch (e.g., DB has week 2, now week 3) → prompt `Refresh now? [Y/n]` (default Y). With `bash hub/start.sh --auto` it auto-confirms.
- **Cold:** no `league_settings` / `player_stats` rows, or `_CACHE` empty and `player_stats.count == 0` → prompt `No data for week X — fetch now? [Y/n]`.

Prompt respects rate limits: check `refresh_log` — if last attempt < 1h ago, show `Last refresh 23m ago (sleeper=ok) — skip?` and default to N. Sleeper `players/nfl` is once/day per `adapters/sleeper.py:24`.

Failure never blocks the hub: if `POST /refresh` returns `{"sleeper": true, "nflverse": false}`, hub still opens and Dashboard shows `⚠ stale — nflverse failed 2026-08-28 07:00` with `retry` button. This matches `refresh.py:49` isolation.

## UX

- Terminal progress (the only visible orchestrator):
  ```
  → Fantasy Hub — one-click start (Ctrl+C to stop)
    Model: http://127.0.0.1:8000  Hub: http://127.0.0.1:8001
  → checking data freshness… last 2026-08-27 07:00 (stale, week 0→1)
  → refresh now? [Y/n] Y
  → refreshing: sleeper ✓  rosters 12 · nflverse ✗  weather skipped · ratings ok (3.2s)
  → hub ready — http://127.0.0.1:8001 (fresh)
  ```
- With `--auto`, the prompt is skipped: `→ stale — auto-refreshing…`
- With `--no-refresh`, skip step 3 entirely (for offline demo).

Browser open is **gated** on step 5 — never open a cold hub that flashes empty then populates.

## Flags (planned)

- `bash hub/start.sh` — prompt if stale (current default, now explicit)
- `bash hub/start.sh --auto` — auto-refresh if stale, no prompt
- `bash hub/start.sh --no-refresh` — never POST, open even if cold (offline)
- `bash hub/start.sh --force` — refresh even if fresh (for testing)

All flags leave `hub/FantasyHub.command` as prompt-mode (safe default for double-click).

## Files Touched (when built)

- Modify: `hub/start.sh` — add steps 1–5, flags, progress log, gated `open`
- Modify: `hub/server.py` — ensure `/hub-api/meta` returns `lastUpdated` + `week` + `stale` boolean so `start.sh` can decide without extra DB open (already does)
- No change: `src/ffanalytics/*`, `pyproject.toml`, `schema.sql`, `scripts/`, `data/fantasy.db` writer remains `refresh.py`
- Add: this plan doc (already added), graph nodes/edges for warm-boot dependency chain (added by `/graphify --update`)

## Verification (when built)

- [ ] Cold DB (delete `data/fantasy.db`) → `bash hub/start.sh` → prompt → Y → creates DB, populates, opens `fresh`
- [ ] Fresh DB (just refreshed) → `bash hub/start.sh` → no prompt, opens in <3s
- [ ] `bash hub/start.sh --auto` on stale DB → no prompt, auto-refreshes
- [ ] `nflverse` down (mock `ConnectionError`) → still opens, Dashboard shows `⚠ stale — nflverse failed`, Projections fallback to Sleeper-only
- [ ] `Ctrl+C` kills all 3 ports: `lsof -i :8000 -i :8001 -i :8002` → empty (trap EXIT covers warm-boot's extra wait loop)
- [ ] `bash hub/verify-isolation.sh` still 9/9 pass (hub still never writes DB, still `mode=ro`, still `127.0.0.1`)

## Graph Nodes to be Added (for `/graphify`)

- `hub/start.sh — warm-boot orchestrator` (depends on `api.py:_CACHE`, `refresh.py:run_refresh_with_data`, `db.py:get_connection`, `server.py:/hub-api/meta`)
- `data staleness check` (reads `refresh_log`, `league_settings`, `_compute_nfl_week`)
- `POST /refresh — gated` (triggers `adapters/sleeper`, `adapters/nflverse`, `adapters/weather`, `rating_updates`)
- `browser gate` (depends on `health=ok` AND `cache warm OR player_stats>0`)

Edges are directed: `warm-boot → POST /refresh → SQLite WAL → _CACHE → hub UI`
