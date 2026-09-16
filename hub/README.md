# Gridiron Hub — Local Command Center

**Zero tokens. $0. Read-only.**

A local fantasy football hub that turns your updated model (`data/fantasy.db` + `127.0.0.1:8000`) into a searchable, sortable UI: projections with heuristic 80%-target intervals (measured 82% overall; QB/K deviate — see `data/models/coverage_2025.json`), matchups with wind badges, tierlists for your 2-FLEX board, roster start/sit with overlap confidence, waiver priority, and trade lab.

This is a **completely separate product** that lives alongside `src/ffanalytics` in one repo but shares no code, no deps, and no writes.

## Sharing contract

- **May share:** `hub/` is allowed to import `ffanalytics` and share root deps
  going forward (isolation rule lifted 2026-09-15). Existing vendored mirrors
  stay until refactored — no flag day.
- **No writes:** Hub opens `fantasy.db` with `mode=ro` (SQLite rejects writes). Never `POST /refresh` — it only `GET`s.
- **Local default:** Model `:8000`, hub `:8001`, proxy `:8002`. Other binds and
  deploys allowed — confirm the destination with Liam first.
- **Deletable:** `rm -rf hub/` leaves `SLEEPER_LEAGUE_ID=test pytest` green.

`hub/verify-isolation.sh` is kept for optional use (`npm run verify`); CI no longer gates on it.

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
- **Matchups** — week picker (1–18), league matchups + NFL slate, wind badges. Slate wind comes from live Open-Meteo forecasts per stadium (`weather` table via `STADIUM_COORDS` in `hub/server.py`); `weather_source: forecast` vs `schedule` is exposed per game. Falls back to schedule observed wind when no forecast row exists.
- **Projections** — searchable table (all numbers mono). Interval bar shows `low — point — high` (model range, half-width scale; overlap ≈ toss-up, not a statistical test). Search chips: `pos:WR wind>15 healthy:true trending:true interval<3`
- **Tierlists** — deterministic tiers by gap > `max(2.0, 0.7×medianWidth)` or cap=6. Tabs: QB/RB/WR/TE/FLEX
- **My Roster** — starters vs bench with overlap confidence (bench ceiling ≥ starter point ⇒ TOSS-UP, LOW confidence; otherwise HIGH if projected > 12 else MEDIUM)
- **Waiver** — ranked by `improvement_over_roster`, not raw points; includes trending from `news_data`
- **Trade** — two `owner_id` inputs → `GET /recommendations/trade` or hub-proxy fallback
- **Props** — forebet-style week board (spec `2026-09-10-week-board-spec.md`).
  Week picker (1–18) drives three sections together:
  - **Game predictions** (`GET /games/predictions`) — win%/predicted score
    from real market lines (spread/total/moneyline off the schedule feed,
    devigged), labeled `market_consensus` — never this app's own model.
  - **Edge board** — model fair lines per market (`GET /props/edges`);
    hub never writes. Edge copy never reads "LOCK".
  - **Game props** (click a game row) — player-card grid (`GET
    /props/board`) showing every market's fair line for that game's
    players, no book line required; a colored edge chip overlays when one
    exists.
  Entertainment-only RG notice on every view; only `passing_yards` earned
  edge labels in 2025 calibration.

## Search

Zero-token, client-side, <5ms. Press `/` to focus. Examples:
- `mahomes`
- `pos:WR wind>15`
- `pos:RB healthy:true interval<3`
- `team:BUF opp:MIA proj>12`

## Weather

Wind penalty is `−(wind−15)×WEATHER_WIND_PENALTY_PER_MPH` for QB/WR/K only (`projection.py:148`, `config.py:48`). Refresh stores real per-stadium forecasts in `weather`; slate badges use them when present and show `⚠ placeholder` only when the table is empty. Penalty math is still visible for audit.

## Troubleshooting

- **Empty tables:** Fresh clone has `player_stats: 0` — run `POST /refresh` in-season. Hub shows warm empty states naming the missing data plus the refresh step.
- **API down:** Hub degrades to DB snapshot — staleness dot turns `cold`, tables show last DB state.
- **Verify isolation failed:** See `hub/verify-isolation.sh` output — fix the flagged line (usually a `0.0.0.0` or stray `import`).

## Tech

- Vite + vanilla JS (no React) + CSS variables (see `hub/DESIGN.md` — Scoreboard Command Center, L2)
- Fonts: system stack, zero webfonts (see `hub/DESIGN.md` typography plus `hub/src/styles/tokens.css`)
- No WebGL, no Lenis; `prefers-reduced-motion` respected
