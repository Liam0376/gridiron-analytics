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

- [x] **Step 1:** `GET /games/predictions?season=&week=`: for each scheduled
  game, `game_predictions.game_prediction()` on the schedule row (market
  lines → devig prob + predicted score). Labeled `source: market_consensus`
  in every response — never framed as this app's own prediction. Reads
  `cache["schedule"]` (whole-season, fetched during refresh — no per-request
  network call).
- [x] **Step 2:** `shadow.log_game_prediction_once` — dedupe by
  kind/season/week/game_id, same idempotency shape as `log_prop_edge_once`.
- [x] **Step 3:** `shadow.evaluate_unresolved_game_predictions` resolves
  against real `home_score`/`away_score` from the schedule feed once final.
- [x] **Step 4:** 5 tests in `tests/test_game_predictions_api.py`: 503
  without cache, response shape, log-once across repeated polls, resolution
  on a final game, pending on an unplayed one.
- [x] **Step 5:** `SLEEPER_LEAGUE_ID=test .venv/bin/pytest -q` green (211
  passed at this checkpoint). Committed: `feat: game predictions endpoint +
  shadow resolution (Task 2+3)`.

---

### Task 3: Wire into refresh cadence

**Files:** `src/ffanalytics/refresh.py`

- [x] **Step 1:** Wired into `run_refresh_with_data`, right after the props
  resolver, per-source isolated (try/except, warns not raises).
- [x] **Step 2:** Idempotency covered by the same `log_game_prediction_once`
  dedupe key (kind/season/week/game_id) Task 2 tested — a second refresh
  before a game is final can't double-insert since the row already exists
  and resolution only ever UPDATEs.
- [x] **Step 3:** `pytest -q` green. Bundled into the Task 2+3 commit
  (`feat: game predictions endpoint + shadow resolution (Task 2+3)`) —
  refresh wiring is one function call, not worth a separate commit.

---

### Task 4: Hub — week board UI

**Files:** `hub/src/views/props.js`, `hub/src/api.js`

> Later superseded (2026-09-10, same day): per direct user request, the
> "Edge board" table and "Add a book line" form described below were
> removed from the UI entirely, and the backend they called (`/props/
> edges`, `/props/lines`, `_evaluate_prop_edge`) was deleted outright once
> confirmed unreachable — no free player-prop odds feed exists to compare
> a book line against. `/props/board`'s game-props popup (this task's
> "unplanned addition," see below) is now the *only* props surface;
> everything else this task describes about the edge board is history,
> not current state. Game predictions (win%/predicted score) are
> unaffected — separate system, still live.

> Deviation: kept in `props.js` (not split) — the new sections share the
> `week`/fetch flow tightly enough that splitting added indirection, not
> clarity. Step 4's global toggle wasn't built as specified — see note
> below Step 4. An unplanned addition landed instead: clicking a game row
> opens a per-game player-props section (`GET /props/board`, new — see
> spec addendum), because `/props/edges` only ever showed *manually
> entered* book lines and a game with none showed nothing (user-caught in
> live review). That turned out to be the more useful "browse this game"
> feature than the toggle would have been.

- [x] **Step 1:** Week selector — 18-chip row, same `data-week`/hash
  pattern as `matchups.js`'s week picker (copied, not reinvented).
- [x] **Step 2:** Game predictions section: dense table (matchup w/
  team logos, win% chips, predicted score, status chip) — forebet-style,
  no card grid, matches the existing table styling.
- [x] **Step 3:** Final games show actual score (bold) in place of the
  predicted-score cell; `FINAL`/`UPCOMING` status chip.
- [ ] **Step 4:** Upcoming/settled toggle — NOT built. Each row's own
  FINAL/UPCOMING chip covers the "is this decided" signal per-game; a
  global filter toggle would be a small additional UI change if still
  wanted, but wasn't necessary for what shipped. Left unchecked rather
  than claimed done.
- [x] **Step 5:** `bash hub/verify-isolation.sh` green after every change
  in this task (checked 3 times across the session, not just once).
- [x] **Step 6:** Driven live in Chrome — confirmed week nav, game board
  render, and (once added) the game-props click-through, via a mix of
  screenshots and `document.body.innerText` checks (the screenshot tool
  was flaky mid-session; text-content checks substituted where it hung).
- [x] **Step 7:** Committed: `feat: week board UI + per-game props
  browsing (Task 4+5, forebet-style)` (bundled with Task 5, see below).

---

### Task 5: Restyle the props table itself

*(Runs regardless of Task 1's outcome — this is the part that ships either
way.)*

**Files:** `hub/src/views/props.js`

> Deviation: the original stored-book-line "Edge board" table was left
> as-is (it was already a reasonably dense bordered table, not a card
> grid — the plan's premise was slightly off). What actually needed the
> restyle work was the NEW per-game props section (Task 4's addition),
> which got the player-card treatment per direct user request ("use the
> player cards") — reuses `playerAvatar`/`posBadge`/`teamLogo` and the
> app's existing `.player-card-v2` CSS, same visual language as
> Projections/Team Hub/Auction, instead of another table.

- [x] **Step 1 (revised):** Game-props section built as a player-card grid
  (`propsPlayerCard()` in `props.js`), not a table — per-market fair
  line + sigma as compact chips under each card, edge chip overlaid when
  a book line exists for that stat.
- [x] **Step 2:** Week grouping via the Task 4 week selector (shared
  state — one `?week=` hash param drives games, props edges, and the
  props board together).
- [x] **Step 3:** `bash hub/verify-isolation.sh` green; manually clicked
  through NE @ SEA in Chrome (Hunter Henry, Mack Hollins, Eric Saubert,
  Cooper Kupp, etc. — real fair lines, confirmed by screenshot).
- [x] **Step 4:** Committed together with Task 4:
  `feat: week board UI + per-game props browsing (Task 4+5, forebet-style)`.

---

### Task 6: Docs

**Files:** `docs/superpowers/specs/2026-09-10-week-board-spec.md`,
`hub/README.md`

- [x] **Step 1:** Spec status line updated (multiple times, tracking each
  round of follow-up work — market-line pivot, then the props-popup
  redesign, injury/carries, and the real-data season-mislabel fix).
- [x] **Step 2:** `hub/README.md` Props row rewritten for the three-section
  board (game predictions, edge board [later deleted], game props).
