# Plan: NFL Week Board — game predictions + restyled props + results

> For agentic workers: execute task-by-task, checkbox discipline. **Stop for
> user confirmation before starting Task 1** (this plan hasn't been approved
> yet). Task 4 (hub UI) additionally gated on Task 1's backtest passing its
> own gate — see spec. Commit at each checkpoint task.

**Goal:** Add a game-level win-probability/predicted-score board (new model,
backtested and gated) above a restyled player-props board, both grouped by
week with an Upcoming/settled toggle — forebet's layout, our data.

**Spec:** `docs/superpowers/specs/2026-09-10-week-board-spec.md`

**Constraints:** $0 forever, no odds/Vegas feed (still rejected per props
spec); local-only `127.0.0.1`; outbound only Sleeper/nflverse/Open-Meteo;
NFL only; `stat_projector.py`/`scoring.py`/`decision.py` untouched; hub
`mode=ro`, `bash hub/verify-isolation.sh` green after any `hub/` change; RG
copy mandatory (no "LOCK", entertainment-only banner); positional Elo track
stays untouched/unused (already correctly REJECTED for player work).

---

### Task 1: Game predictions from real market lines (PIVOTED from Elo backtest)

> **Pivot (2026-09-10):** while starting Task 1, found `adapters/schedule.py`
> (nflreadpy `load_schedules`, already in use) carries real `spread_line`/
> `total_line`/`home_moneyline`/`away_moneyline` for every game, upcoming
> included — a free market feed we already call and weren't reading. This
> is NOT the player-props feed rejected as paid (different product). No
> need to fit-and-gate our own Elo model when real market consensus is
> free — same honesty rule applies differently: label it "market
> consensus," never present it as our own prediction. Spec updated
> (`2026-09-10-week-board-spec.md`) to match. Elo `overall` track stays
> unused for this feature (still real, still updating, just not needed
> here).

**Files:** `src/ffanalytics/game_predictions.py` (pure functions, no I/O),
`scripts/validate_game_predictions.py`, `tests/test_game_predictions.py`

- [x] **Step 1:** `game_predictions.py`: `devig_two_way(price_a, price_b)`
  (two-sided no-vig moneyline → fair probabilities, reuses
  `props.american_to_prob`), `predicted_score(spread_line, total_line)`
  (confirmed convention against real rows: positive `spread_line` = home
  favored by that many points), `game_prediction(game_dict)` assembling
  both + `final`/actual-score passthrough from the schedule row, `None` if
  lines are missing (never guesses).
- [x] **Step 2:** `validate_game_predictions.py` — informational historical
  report (not a gate, no free params to overfit): 2023-2025 REG games,
  win-call accuracy, Brier score, per-team score MAE vs naive baselines.
- [x] **Step 3:** Result: 816 games, **68.26% win-call accuracy** (naive
  home-favorite baseline ~57%), **Brier 0.2102** (naive p=0.5: 0.25), **7.21
  pt avg score MAE**. Confirms the conversion math is sane — market lines
  are, unsurprisingly, well-calibrated.
- [x] **Step 4:** `tests/test_game_predictions.py` — devig math (symmetric
  -110/-110, real favorite/underdog row, degenerate-price no-crash),
  predicted-score arithmetic, `game_prediction` missing-lines/full-row/
  not-final cases. 7/7 pass.
- [x] **Step 5:** No REJECTED path needed (not a fit-model gate) — proceed
  to Task 2 unconditionally. Task 4 (hub UI) no longer conditionally
  skipped; ships alongside Task 5.

---

### Task 2: API — game predictions endpoint + shadow resolution

**Files:** `src/ffanalytics/api.py`, `src/ffanalytics/shadow.py`,
`src/ffanalytics/refresh.py`, `tests/test_game_predictions_api.py`

- [ ] **Step 1:** `GET /games/predictions?season=&week=`: for each scheduled
  game, `game_predictions.game_prediction()` on the schedule row (market
  lines → devig prob + predicted score). Labeled `source: market_consensus`
  in every response — never framed as this app's own prediction.
- [ ] **Step 2:** Shadow log each served prediction once per (season, week,
  game) — new kind `"game:<season>:<week>"`, reuse `shadow.log_recommendation`
  or a thin wrapper, not a parallel table.
- [ ] **Step 3:** Resolution: on refresh, for any unresolved game-kind shadow
  row where `get_schedule()` now reports a final score, `record_outcome`
  with actual score + whether the win-call was right (mirrors
  `evaluate_unresolved_prop_recommendations` in shadow.py — reuse the shape,
  don't fork it).
- [ ] **Step 4:** Tests: prediction shape, shadow log-once idempotency
  (same bug class as the props dedupe fix — POST/GET must not double-log),
  resolution correctness on a fixture completed game.
- [ ] **Step 5:** `SLEEPER_LEAGUE_ID=test .venv/bin/pytest -q` green. Commit:
  `feat: game predictions endpoint + shadow resolution`.

---

### Task 3: Wire into refresh cadence

**Files:** `src/ffanalytics/refresh.py`

- [ ] **Step 1:** Call the Task 2 resolution step from `run_refresh_with_data`
  (same place `evaluate_unresolved_prop_recommendations` is called), per-source
  isolated (a resolution failure must not abort the rest of refresh).
- [ ] **Step 2:** Confirm no double-write: two refreshes in the same week
  before the game is final must not create duplicate shadow rows (same
  idempotency discipline as props `prop_lines` upsert).
- [ ] **Step 3:** `pytest -q` green. Commit: `feat: resolve game predictions
  on refresh`.

---

### Task 4: Hub — week board UI

**Files:** `hub/src/views/props.js` (or split into `hub/src/views/week.js` +
keep `props.js` for the props-only data layer), `hub/src/api.js`

- [ ] **Step 1:** Week selector at the top (reuse whatever week-picker
  pattern `matchups.js`/`projections.js` already use — don't invent a new
  one).
- [ ] **Step 2:** Game predictions section: dense table (matchup / win% /
  predicted score / status chip), forebet-style — no card grid, bordered
  rows, header row like the existing props table's `<thead>`.
- [ ] **Step 3:** Once a game is final (row has actual score from the
  resolved shadow data): replace the predicted-score cell's placeholder
  styling with an actual-score cell, chip reflects right/wrong.
- [ ] **Step 4:** Upcoming/settled toggle (forebet's "Upcoming"/"Recent"),
  filters both the game section and the props section by the same state.
- [ ] **Step 5:** `bash hub/verify-isolation.sh` still green (no `import
  ffanalytics` snuck into hub/, no write, no `0.0.0.0`).
- [ ] **Step 6:** Manually drive it in Chrome (per `run` skill discipline —
  screenshot, don't just typecheck), confirm both sections render, RG banner
  intact, no "LOCK" language anywhere.
- [ ] **Step 7:** Commit: `feat: week board (game predictions + restyled
  props), forebet-style layout`.

---

### Task 5: Restyle the props table itself

*(Runs regardless of Task 1's outcome — this is the part that ships either
way.)*

**Files:** `hub/src/views/props.js`

- [ ] **Step 1:** Replace the current edge-board card/table hybrid with a
  forebet-style dense table: player+market as one cell (like forebet's
  home/away team stack), fair/book/edge as plain columns, status chip
  reused as-is (VALUE/TRACKING/NO EDGE — unchanged, already RG-safe).
- [ ] **Step 2:** Group by week (already filterable by week/season via
  `fetchPropEdges({week, season})` — just surface the selector in the UI,
  the API already supports it).
- [ ] **Step 3:** `bash hub/verify-isolation.sh` green, manual Chrome check.
- [ ] **Step 4:** Commit: `refactor: restyle props table (forebet-style
  dense layout)`.

---

### Task 6: Docs

**Files:** `docs/superpowers/specs/2026-09-10-week-board-spec.md`,
`hub/README.md`

- [ ] **Step 1:** Update spec status line with final gate result (pass or
  REJECTED) and what actually shipped.
- [ ] **Step 2:** `hub/README.md`: add/update the week-board row (mirrors
  the existing Props row).
