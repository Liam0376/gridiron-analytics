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

### Task 1: Backtest the game-outcome model (gate — must pass before Task 4)

**Files:** `scripts/backtest_games.py`, `data/games/backtest_games_results.json`,
`src/ffanalytics/game_predictions.py` (pure functions only, no I/O)

- [ ] **Step 1:** `game_predictions.py`: `win_probability(home_rating, away_rating,
  home_field_elo=X)` wrapping `rating._expected_score`, and
  `predicted_margin(home_rating, away_rating, coef)` — a plain linear map, `coef`
  and `home_field_elo` as parameters, not hardcoded, so the backtest fits them.
- [ ] **Step 2:** Write `backtest_games.py` mirroring `backtest_props.py`'s
  discipline: multi-season OOS (train `team_ratings` overall-track through
  week N-1 using real results via `rating_updates.py`'s existing update logic,
  predict week N, compare to `get_schedule()`'s actual `home_score`/
  `away_score`). Grid-search `home_field_elo` and margin `coef` on a
  train split; evaluate untouched on a held-out split (same train/val season
  split style as `backtest_ml.py`).
- [ ] **Step 3:** Report: win-call accuracy vs naive home-favorite baseline
  (~57%), Brier score vs naive-baseline Brier, margin MAE vs "predict mean
  historical margin" baseline. Write `data/games/backtest_games_results.json`
  with the fitted constants + all four numbers, win and lose cases both.
- [ ] **Step 4:** Gate check: accuracy beats baseline AND Brier beats
  baseline → VALUE eligible, keep fitted constants, proceed to Task 2. Either
  gate fails → REJECTED, write the honest result into the spec's Gate
  section, **skip Task 2-4's game-board work**, keep only Task 5 (props
  restyle, no new game predictions) and Task 6 (docs).
- [ ] **Step 5:** STOP — report Task 1 result (pass or REJECTED) before
  continuing. This is the plan's real decision point, not a formality.

---

### Task 2: API — game predictions endpoint + shadow resolution

*(Skip entirely if Task 1 gate failed.)*

**Files:** `src/ffanalytics/api.py`, `src/ffanalytics/shadow.py`,
`src/ffanalytics/refresh.py`, `tests/test_game_predictions_api.py`

- [ ] **Step 1:** `GET /games/predictions?season=&week=`: for each scheduled
  game, current `overall` ratings → `win_probability`/`predicted_margin` →
  predicted score (round margin onto a plausible total, same honesty rule as
  props' fair line — no invented precision). Status `VALUE` (Task 1 gate
  passed) — this endpoint doesn't ship at all if the gate failed.
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

*(Skip if Task 1 gate failed.)*

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

*(Only if Task 1 gate passed. If it failed, this task is just "restyle
props," see Task 5 — no game section.)*

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
