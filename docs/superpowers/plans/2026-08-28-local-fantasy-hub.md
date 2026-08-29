# Local Fantasy Football Hub — Information Architecture Plan

> **ISOLATION CONTRACT — READ FIRST**
> This hub is a **completely separate read-only consumer**. It does not import, modify, or depend on `src/ffanalytics/*` at build time.
> It reads only what the model already publishes:
> - `GET` endpoints on `http://127.0.0.1:8000` (`/health`, `/news`, `/recommendations/*`, `/refresh` is POST — hub never calls it automatically)
> - `data/fantasy.db` via **read-only SQLite** (`mode=ro`, `immutable` flag or `sqlite3` with `uri=True` and no writes)
>
> **Forbidden for the hub:** adding deps to root `pyproject.toml`/`requirements.txt`, editing `src/ffanalytics/*`, adding tables to `schema.sql`, writing to `fantasy.db`, binding `0.0.0.0`, calling any LLM/token API at runtime. Violation = plan fails review.
>
> Location: **top-level `hub/` directory** with its own `package.json` / `pyproject.toml` (if Python) and isolated `README.md`. Root repo's `AGENTS.md` and `CLAUDE.md` constraints (`$0`, `127.0.0.1` only) apply equally to the hub.

**Goal:** A token-free, $0, fully-local fantasy hub that lets you — without a single LLM call — see everything the model already knows: weekly projections (with calibrated intervals), matchups, weather-impacts, tierlists, roster start/sit with confidence, waiver priorities, and trade evaluations, plus a fast search over all of it. Data freshness comes from the existing daily `launchd` → `refresh_job.sh` → `SQLite WAL` pipeline, not from the hub.

**Non-goals (v1):** No model retraining, no new projection features, no schema migrations, no auth/multi-user, no public hosting, no phone tunnel, no LLM narrative (that remains an *optional* out-of-band `muse -p` you invoke manually, not part of the hub).

**Spec dependency:** `docs/superpowers/specs/2026-08-26-fantasy-football-analytics-design.md` + current implementation (`src/ffanalytics/api.py:52` `_CACHE`, `schema.sql`, `projection.py`, `conformal.py`, `decision.py`, `scoring.py`, `adapters/schedule.py`, `adapters/weather.py`).

---

## 1. Why zero-token is trivial here

The model already does the expensive work on a schedule. The hub is just a lens:

```
launchd (07:00) → POST /refresh → adapters → SQLite + _CACHE → projections/ratings/shadow
                                                        ↑
                                                        |  read-only (GET or sqlite3 mode=ro)
                                                        |
                                              hub/ (localhost:8001) → browser
```

No per-request LLM, no embeddings needed. Tierlists and search are deterministic sorts/filters on `projected_points`, `interval`, `team_ratings`, and `FLEX_SCARCITY_MULTIPLIER`. If you ever want a sentence like "why start X", you run `muse -p "explain ..."` against the same DB snapshot — the hub itself stays at 0 tokens.

## 2. Technology decision

| Option | Process | Zero-token? | $0? | Why not / why |
|---|---|---|---|---|
| **A. Static frontend (Vite + vanilla JS or React) served by tiny local server on :8001** | `hub/server.py` (stdlib `http.server` or 20-line FastAPI) or `npx vite --host 127.0.0.1 --port 8001` | Yes — fetches `localhost:8000` | Yes | **Recommended.** Zero coupling to model. One `npm run dev` or `python -m http.server`. Works offline after `npm install`. No Rust, no 200MB Streamlit. |
| B. Extend `src/ffanalytics/api.py` with `StaticFiles` on :8000 | Modifies model file — **rejected** per isolation contract | Yes | Yes | Would violate "DO NOT INTERFERE". |
| C. Streamlit/Dash | Single Python process reading DB | Yes | Yes | Heavy deps, not bookmarkable, duplicates server you already run on :8000. |
| D. Tauri/Electron wrapper | Native window | Yes | Yes | Overkill for one user; still needs A underneath. Defer. |

**Recommendation: A** — `hub/` owns its `package.json` (and optional `hub/server.py` 30-line read-only API proxy for DB fallback). Frontend is plain HTML/CSS/JS, no build-time model imports. At runtime it tries `fetch('http://127.0.0.1:8000/...')` first; if `503` (cache cold), it falls back to a **read-only SQLite fetch via `hub/server.py:/hub/api/*`** that reads the same `fantasy.db` directly. That fallback is the only Python in the hub and it opens DB with `uri=file:data/fantasy.db?mode=ro`.

**Isolation filesystem contract:**

```
hub/                          # new top-level, git-ignored from model perspective except this plan
  package.json                # own deps (vite, etc.) — never touches root pyproject
  vite.config.js              # server.host = '127.0.0.1', port 8001, strictPort
  index.html
  src/
    main.js                   # fetch + render
    api.js                    # wrappers for 8000 GETs + 8001 fallback
    search.js                 # client-side filter (no backend search)
    tierlist.js               # deterministic tiering
    views/  (dashboard, matchups, projections, roster, waiver, trade, shadow)
  server.py                   # optional 30-line read-only DB proxy (127.0.0.1:8001/api)
  README.md                   # "npm install && npm run dev → http://127.0.0.1:8001"
```

## 3. Data contract — what the hub may read (and how)

Hub is **read-only**. No `POST /refresh` from hub UI (show a manual curl snippet instead).

| Need | Primary (live cache) | Fallback (DB direct, read-only) | Notes |
|---|---|---|---|
| League shape | `GET /news` is not it — use `GET` of league settings via new read-only hub proxy or parse `fantasy.db: league_settings.data` JSON | `SELECT data FROM league_settings ORDER BY season DESC LIMIT 1` | `roster_positions`, `scoring_settings` drive FLEX counting (`scoring.py:88` `count_flex_slots`) |
| Rosters + injuries | `_CACHE` via `/recommendations/*` internals | `rosters.data`, `injury_status.data` | `injury_status` is `dict[player_id → str|None]` |
| Player projections | `/recommendations/start-sit` (has `projected_points`, `confidence`) but not interval | `player_stats.data` + compute `projection.py:49 calculate_projection` client-side or via hub proxy | Preferred: hub proxy re-runs same math with `team_ratings` + `WEATHER_WIND_PENALTY_PER_MPH` so interval is visible |
| Matchups | `sleeper_matchups` table + `GET /news` is separate | `SELECT * FROM sleeper_matchups WHERE season=? AND week=?` + `adapters/schedule.py:26 get_nfl_team_matchups` via proxy | Need week selector (see §4) |
| Weather | `weather` table | `SELECT * FROM weather WHERE game_time_iso LIKE '2026-%'` | **Current data is placeholder** (`refresh.py:256` `40.0,-74.0` + `now` as gametime) — hub must show "⚠ placeholder" badge until real stadium coords wired |
| Trends + detailed injuries | `GET /news` | `news_data` (`kind='trending'|'injuries'`) | Use `fetched_at` for staleness |
| Team positional ratings | No API yet | `SELECT * FROM team_ratings WHERE season=?` | Powers tierlist matchup-adjusted view |
| Shadow logs | No API yet | `SELECT * FROM shadow_recommendations ORDER BY logged_at DESC` | Read-only transparency view |

**Staleness UI (required):** Every page header shows `last_updated` (from `_CACHE` or max `refresh_log.ran_at` / `news_data.fetched_at`) + a badge: `fresh (<24h)` / `stale` / `cache cold — showing DB snapshot`. Matches spec's "visible data stale as of [timestamp]" rule.

## 4. Information architecture

Top nav (persistent, keyboard `1`–`7`):

```
[ Dashboard ] [ Matchups ] [ Projections ] [ Tierlists ] [ My Roster ] [ Waiver ] [ Trade Lab ]   [ search ▸ ]   [ ● fresh 2026-09-14 07:02 ]
```

### 4.1 Dashboard — "are we good to trust this week?"
Purpose: go/no-go before you set a lineup.

- Cards: last refresh (`sources: sleeper/nflverse/news/ratings` booleans from last `POST /refresh` → proxy reads `refresh_log`), next refresh at `07:00`, `week` from `_compute_nfl_week()` (`api.py:24` / `refresh.py:13` — 1–18, 0=preseason), season.
- Alerts: `nflverse` failed → "projections stale", `news` failed → "trending empty", `weather` placeholder → "weather not real yet".
- Quick actions (links, not POSTs): "Manual refresh: `curl -X POST http://127.0.0.1:8000/refresh`" (copy button), "Open API: :8000/docs".

### 4.2 Matchups — "who plays whom, where, and in what weather"
- Week selector (1–18, default = `_compute_nfl_week()`), prev/next.
- Two sections:
  1. **Your league matchups** (`sleeper_matchups`): your `matchup_id` vs opponent `roster_id`, `points`, `starters` expanded to player names (via `player_stats` lookup). Highlight your roster.
  2. **NFL slate** (`adapters/schedule.py:5 get_schedule` via proxy): `away @ home — stadium — gameday gametime`. Each game row shows weather badge from `weather` table: `wind_mph`, `temp_f`, `precip_prob` + warning if `wind > 15 → QB/WR/K penalty` (`projection.py:148`, `config.py:48`). Until stadium mapping is real, each badge carries `⚠ placeholder coords`.
- Filter: team, position.

### 4.3 Projections — "searchable, sortable single source of truth"
The hero view. Replaces needing to ask Muse "who should I start?".

- Table columns: `player | pos | team | opp | opp rating (vs_pos) | proj (pts) | interval [low–high] width | weather Δ | tier | injury | trending`
  - `projection_width` = `qhat` interval width (`conformal.py`) — narrow = confident.
  - `weather Δ` computed as `-(max(0, wind-15) * WEATHER_WIND_PENALTY_PER_MPH)` for QB/WR/K else 0.
  - All numbers show to 1 decimal; interval as `14.2 ±4.1` or `[10.1 – 18.3]`.
- Controls:
  - **Search** (see §5) — instant client-side `filter()`, debounced 150ms.
  - Filters: position (QB/RB/WR/TE/K/DEF multi-select), team, opponent, healthy-only, available-only (free agent vs rostered), trending-only, windy-game-only, confidence (width < threshold).
  - Sort: proj desc (default), interval width asc, opponent rating asc (easier matchup first).
  - Group: flat list vs grouped by position.
- Row click → drawer: feature breakdown (`target_share`, `snap_pct`, `opponent_positional_rating` from `projection.py:105ff`), flex adjustment applied (`scoring.py:77` — show `×1.05` badge when `FLEX_ELIGIBLE && num_flex>=2`), historical residuals spark if available, shadow hits for that player.

### 4.4 Tierlists — "at-a-glance draft/board view"
- Tab per position: `QB | RB | WR | TE | FLEX (RB/WR/TE)` — FLEX tab is the money view for your 2-FLEX league (it runs `apply_flex_adjustment` before tiering).
- Tiering algorithm (deterministic, no LLM):
  1. Take filtered projections (e.g., all WR with `proj >= 5.0`, healthy).
  2. Sort by `point_estimate` desc.
  3. Walk sorted list, start new tier when gap > `tier_gap` (default `2.0` pts or `0.7× median interval width`, whichever is larger) **or** when cumulative tier size hits `tier_cap` (default 6). First tier is Tier 1.
  4. Render tiers as horizontal lanes with player cards (name, team vs opp, proj ± width, injury dot). Drag is visual only in v1 (no persistence).
- Toggle: raw proj vs matchup-adjusted (`opponent_positional_rating` delta shown).
- Export: copy tierlist as markdown.

### 4.5 My Roster — "start/sit with why"
- Reads same inputs as `GET /recommendations/start-sit` + `sleeper` rosters, but hub renders intervals so you see **overlapping intervals = "close"** directly (the spec's core conformal distinction: `design spec: Conformal prediction`).
- Layout: slots as per `roster_positions` (`QB, RB, RB, WR, WR, TE, FLEX, FLEX, K, DEF, BN×4, IR×2`). For each slot: recommended starter (proj + interval) vs best bench alternative (proj + interval) with overlap visualization (bar). Confidence = `HIGH` if intervals don't overlap, `MEDIUM`/`CLOSE` otherwise — mirrors `decision.py:61` `starting_slots` logic but with interval awareness.
- Bench below, sorted by proj, with "swap in" preview (no write — preview recomputes `calculate_roster_value` client-side).
- Injury/trending badges inline.

### 4.6 Waiver Wire — "who actually improves you"
- Sorted by `improvement_over_roster` (same as `decision.py:142 get_waiver_priority`), not raw proj. Columns: `player | pos | proj | replaces | Δ roster value | waiver_priority | rostered% | trending`.
- Filter: pos need (`needed = required - have` from `decision.py:151`), healthy, not on your roster.
- Detail: show `calculate_roster_value` before/after and which `FLEX` slot they'd fill.

### 4.7 Trade Lab — "fair or fleece"
- Two pickers: `Team A (you)` vs `Team B (opponent)` — multi-select from rosters (searchable). Uses same logic as `GET /recommendations/trade?team_a_id=&team_b_id=` and `decision.py:213 evaluate_trade` (weekly + ROS `calculate_rest_of_season_value`).
- Output: `winner`, `value_difference`, `team_a_value` vs `team_b_value`, ROS bars, and a note when intervals overlap heavily ("within margin — basically fair").

### 4.8 Shadow / Research — optional transparency tab
- Table of `shadow_recommendations` (`kind`, `season/week`, `player_id`, `recommendation` JSON, `actual_outcome` or `NULL`, `logged_at`). Filter by kind, unresolved only.
- Stats: `count_logged` per kind vs `MIN_SHADOW_SAMPLES=20` (`config.py:39`) progress bar.

## 5. Search spec — token-free, instant

No backend search, no embeddings. `hub/src/search.js` holds the full player list (from `player_stats.data` or `projections` array) in memory and runs:

- Text: case-insensitive substring on `player_name`, `team`, `opponent_team`, `player_id` (fuzzy via `includes`, not Levenshtein — add later if needed).
- Structured chips: `pos:WR`, `team:BUF`, `opp:vs_MIA`, `proj>12`, `wind>15`, `healthy:true`, `tier:1`, `trending:true`, `interval<3` (tight = confident). Chips parsed from query string so URL is shareable: `?q=pos:WR+wind>15`.
- No LLM query interpretation — the chip syntax *is* the power. A one-line help `?` popover explains chips. This keeps it at 0 tokens and instant (<5ms on 2k players).

## 6. Weather — honest about placeholder

Until `refresh.py:247ff` is fixed to use real stadium coords + `schedule.gametime`:
- Hub shows weather badges with `⚠ placeholder` tooltip: "Coords fixed to 40.0,-74.0 and gametime = refresh time — penalties not yet trustworthy. Fix is stadium map in `adapters/schedule.py` + `team → lat/lon`."
- Penalty math is still displayed (`projection.py:148` — only QB/WR/K, only when `wind > 15`) so you can audit it.
- Once real coords land, badge becomes `12 mph ↗ 62°F 10% precip` with color: green <15, amber 15–20, red >20.

## 7. Visual / interaction notes (no code, just constraints)

- **Local-only feel:** dark/light toggle, persisted in `localStorage`, no external fonts/CDN (bundle Inter or use system font stack) — stays $0 and offline.
- **No external analytics, no telemetry.**
- **Keyboard:** `/` focuses search, `w` week -1, `e` week +1, `1`–`7` tabs.
- **Empty states:** cache cold → "Run `curl -X POST http://127.0.0.1:8000/refresh` or check `refresh_log`" with `SELECT` snippet, not a spinner forever.

## 8. What the hub will never do (isolation guardrails)

- Never `import ffanalytics.*` at build time. If hub needs the same math (`calculate_projection`, `apply_flex_adjustment`, `qhat`), it **vendors a copy** into `hub/src/logic/` with a header comment `// vendored from src/ffanalytics/... at commit <sha> — read-only mirror, do not drift without review` — or calls the hub proxy which reuses the source file at runtime via `importlib` without editing it.
- Never writes to `data/fantasy.db`, never adds tables, never calls `POST /refresh` automatically.
- Never adds a root dependency or edits `pyproject.toml` / `requirements.txt` / `src/*` / `scripts/*`.
- Never binds `0.0.0.0` — `vite.config.js` and `hub/server.py` both set `host='127.0.0.1'`.

## 9. Future fixes hub surfaces but does not own (model backlog)

The hub should surface these as `⚠` badges, not fix them itself:

1. Real stadium `lat/lon` map + `schedule.gametime` wiring for weather (`refresh.py:247`).
2. Optional: single read-only `GET /hub-data` aggregator on the model side (only if model owner approves) to avoid N fetches — not required for v1; hub's client-side join is fine for one league.
3. `APPLE_SILICON` perf irrelevant — hub is static, no model inference.

## 10. Plan verification — how you know this is ready to build

- [ ] New file exists at `hub/README.md` describing `npm install && npm run dev → http://127.0.0.1:8001` and isolation contract.
- [ ] `hub/` contains no `import ffanalytics` (grep fails).
- [ ] `hub/` has its own `package.json` / `hub/server.py` — root `pyproject.toml` unchanged (`git diff -- src/ pyproject.toml` empty).
- [ ] Hub opens DB with `mode=ro` (grep `mode=ro` / `uri=True`).
- [ ] All 7 tabs render with mock JSON first (no live API needed), then with real `fantasy.db` snapshot.
- [ ] Search `pos:WR wind>15` filters correctly; tierlists recompute on filter change.
- [ ] Staleness badge shows `refresh_log` age; weather shows `⚠ placeholder` until model fixes coords.
- [ ] `grep -r "0.0.0.0" hub/` returns nothing; `vite.config.js` asserts `host: '127.0.0.1'`.

---

## 11. Minimal file tree to create (when you say build)

```
hub/
  README.md
  package.json            # vite, (optional) react — no root deps
  vite.config.js          # host 127.0.0.1, port 8001
  index.html
  server.py               # optional 30-line read-only proxy (stdlib only, no new pip deps if possible)
  src/
    main.js
    api.js                # fetch 8000 + fallback to 8001/api
    search.js
    tierlist.js
    views/
      dashboard.js
      matchups.js
      projections.js
      tierlists.js
      roster.js
      waiver.js
      trade.js
      shadow.js
    components/
      stalenessBadge.js
      weatherBadge.js
      intervalBar.js
      playerCard.js
```

No changes to `src/ffanalytics/*`, `pyproject.toml`, `requirements.txt`, `schema.sql`, or `scripts/*`. Hub is deletable by `rm -rf hub/` with zero effect on the model.
