# Fantasy Hub — Local Command Center

**Zero tokens. $0. 127.0.0.1 only. Read-only.**

A local fantasy football hub that turns your updated model (`data/fantasy.db` + `127.0.0.1:8000`) into a searchable, sortable UI: projections with calibrated intervals, matchups with wind badges, tierlists for your 2-FLEX board, roster start/sit with overlap confidence, waiver priority, and trade lab.

This is a **completely separate product** that lives alongside `src/ffanalytics` in one repo but shares no code, no deps, and no writes.

## Isolation contract

- **No imports:** `hub/` never does `import ffanalytics` (grep fails). Math is vendored as read-only mirror or fetched via HTTP.
- **No writes:** Hub opens `fantasy.db` with `mode=ro` (SQLite rejects writes). Never `POST /refresh` — it only `GET`s.
- **No shared deps:** Model deps = `pyproject.toml` / `.venv`. Hub deps = `hub/package.json` / `hub/node_modules`.
- **Local only:** Both servers bind `127.0.0.1` — hub `8001`, model `8000`, proxy `8002`. No `0.0.0.0`, no tunnel.
- **Deletable:** `rm -rf hub/` leaves `SLEEPER_LEAGUE_ID=test pytest` green.

Verify: `bash hub/verify-isolation.sh` (also `npm run verify` inside `hub/`).

## One-click start

```bash
bash hub/start.sh
# → starts model :8000 + proxy :8002 + hub :8001, then opens http://127.0.0.1:8001
# → press Ctrl+C to stop everything — 0 processes after
```

Or double-click **`hub/FantasyHub.command`** in Finder (same script, macOS will ask to allow once).

Only command needed. Installs `hub/node_modules` once if missing, waits for health checks, opens the browser. Idles ~0% CPU when closed. After `Ctrl+C`, `lsof -i :8000 -i :8001 -i :8002` is empty.

Stop: `bash hub/stop.sh`

## Manual start (if you prefer 3 terminals)

### 1. Model
```bash
SLEEPER_LEAGUE_ID=test .venv/bin/uvicorn ffanalytics.api:app --reload
```

### 2. Hub proxy
```bash
.venv/bin/python hub/server.py  # → http://127.0.0.1:8002 (mode=ro)
```

### 3. Hub UI
```bash
cd hub && npm run dev  # → http://127.0.0.1:8001
```

Production build: `npm run build` → `hub/dist/`

## Tabs

- **Dashboard** — season/week, lastUpdated staleness, refresh log, zero-token explainer
- **Matchups** — week picker (1–18), league matchups + NFL slate, wind badges. Weather currently `⚠ placeholder` (coords 40.0,−74.0 in `refresh.py:256` until stadium map lands)
- **Projections** — searchable table (all numbers mono). Interval bar shows `low — point — high` (conformal `α=0.2, 80%`). Search chips: `pos:WR wind>15 healthy:true trending:true interval<3`
- **Tierlists** — deterministic tiers by gap > `max(2.0, 0.7×medianWidth)` or cap=6. Tabs: QB/RB/WR/TE/FLEX
- **My Roster** — starters vs bench with overlap confidence (HIGH if intervals don't overlap)
- **Waiver** — ranked by `improvement_over_roster`, not raw points; includes trending from `news_data`
- **Trade** — two `owner_id` inputs → `GET /recommendations/trade` or hub-proxy fallback

## Search

Zero-token, client-side, <5ms. Press `/` to focus. Examples:
- `mahomes`
- `pos:WR wind>15`
- `pos:RB healthy:true interval<3`
- `team:BUF opp:MIA proj>12`

## Weather

Wind penalty is `−(wind−15)×WEATHER_WIND_PENALTY_PER_MPH` for QB/WR/K only (`projection.py:148`, `config.py:48`). Until the model stores real `lat/lon + gametime`, every badge shows `⚠ placeholder`. Penalty math is still visible for audit.

## Troubleshooting

- **Empty tables:** Fresh clone has `player_stats: 0` — run `POST /refresh` in-season. Hub shows warm empty states with the exact `curl` to run.
- **API down:** Hub degrades to DB snapshot — staleness dot turns `cold`, tables show last DB state.
- **Verify isolation failed:** See `hub/verify-isolation.sh` output — fix the flagged line (usually a `0.0.0.0` or stray `import`).

## Tech

- Vite + vanilla JS (no React) + CSS variables (see `hub/DESIGN.md` — Scoreboard Command Center, L2)
- Fonts: Instrument Sans + JetBrains Mono + Fragment Mono
- No WebGL, no Lenis; `prefers-reduced-motion` respected
