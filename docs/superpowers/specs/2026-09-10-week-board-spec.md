# Spec: NFL Week Board — game predictions + props + results (forebet-style layout)

> Status (2026-09-10): DRAFT — not implemented. Written after live review of
> forebet.com's American Football section (Chrome MCP) at user's request.

## Context

User asked to restyle the Props tab to look like forebet.com's weekly board.
Forebet's American Football section (checked live, `all-predictions` +
one match detail page) is **game-level only** — no player props anywhere on
the site. What it actually shows, per game, grouped by week with an
Upcoming/Recent toggle:

- Win probability % (home/away), a predicted-winner chip, correct-score pick
- A "coefficient" column (implied odds-style number, Forebet's own, not a
  bookmaker feed)
- Head-to-head history table, team form (last-6 W/L strip), standings,
  next-matches list
- Once a game is played: actual score replaces the placeholder, chip goes
  green/red implicitly by having been right or wrong

So "make Props look like forebet" doesn't transplant content — it borrows
the *shape*: a dense per-week board, a real prediction (not just a stat
line), and a settled-result state once the game's over. User picked the
full-scope option: build a **game-level win-probability/score board** (new)
that sits above the existing (restyled) player-props board, both grouped by
week, both resolving to actual results once games finish.

## What already exists (reuse, don't rebuild)

- **`rating.py` + `rating_updates.py`: a live Elo "overall" track.**
  `update_team_ratings_from_results()` already runs every refresh
  (`refresh.py:228,510`), updates `team_ratings` `position_group='overall'`
  Elo per NFL team from real game win/loss, K-factor `max(16, 32-week)`.
  This is exactly the power-rating a win-probability model needs — it is
  NOT the positional (`vs_QB/RB/WR/TE`) track that was tested and REJECTED
  for player projections (`rating.py:8-9`, `stat_projector.py:22-24`).
  Whole-team win/loss Elo was never evaluated for *game* prediction and is
  not tainted by that rejection — it needs its own honest backtest, not a
  free pass, but it is not starting from zero.
- **`adapters/schedule.py:get_schedule()`** already returns `home_score`/
  `away_score` once a game is final (used today by `rating_updates.py` to
  detect completed games) — the actual-result feed for grading predictions
  is already wired, no new adapter needed.
- **Props architecture is the template**: `props.py` (fair line math),
  `shadow.py` (log prediction → resolve against actual → trust gate),
  `POST/GET /props/lines` + `/props/edges` (API shape), `hub/src/views/
  props.js` (RG-safe copy: never "LOCK", chips read VALUE/TRACKING/NO EDGE).
  The game board reuses this pattern wholesale rather than inventing a
  parallel one.

## Goals

1. **`src/ffanalytics/game_predictions.py`** — from two teams' `overall`
   Elo ratings: win probability (`rating._expected_score`, + a fitted home-
   field constant — NFL literature range is ~48-65 Elo pts, we fit our own
   via backtest, not import theirs uncritically), and a predicted-margin →
   score via a fitted (not eyeballed) `rating_diff → point_margin`
   regression over real historical games. Same honesty rule as props: if
   the fitted model doesn't beat a naive baseline (home-team-always-wins,
   ~57% historically), it ships TRACKING, never VALUE.
2. **Backtest** (`scripts/backtest_games.py`, mirrors `backtest_props.py`):
   multi-season OOS test (train ratings through week N-1, predict week N),
   report win-call accuracy, Brier score vs the naive-home baseline, and
   margin MAE vs "predict the mean historical margin" baseline. This is the
   gate — written and run BEFORE any UI work, per this repo's process.
3. **API**: `GET /games/predictions?season=&week=` (mirrors `/props/edges`)
   — one row per scheduled game: teams, win%, predicted score, status
   (`VALUE`/`TRACKING`), and once final: actual score, whether the pick
   was right. Shadow-logged the same way props are (`shadow.py`, new kind
   `"game:<season>:<week>"`), resolved on refresh once `home_score` is not
   null.
4. **Hub**: restyle `hub/src/views/props.js` into a week board — game
   predictions section (new, dense table: matchup / win% / predicted score
   / status) above the existing player-props section (same data, tighter
   forebet-style table instead of the current card grid), with a week
   selector and an Upcoming/Recent-style toggle (in-progress vs settled).
   RG copy rules carry over unchanged (no "LOCK", entertainment-only
   banner stays).

## Non-goals

- No player props on forebet's side to copy — the props board is a restyle
  of what already ships, not new content.
- No live in-game score ticking — resolution happens on the existing
  refresh cadence (`hub/start.sh` refresh), not a live feed. $0 constraint,
  no websocket/live-odds vendor.
- No Vegas spread/total ingestion — still no paid odds API (see props spec's
  `theoddsapi.com` REJECTED note); "coefficient"-style column, if kept, is
  our own model's implied number, clearly labeled as such, never presented
  as a market price.
- Positional Elo (`vs_QB/RB/WR/TE`) stays untouched/unused — already
  correctly rejected for player-level work; out of scope here too.

## Gate (must pass before Task 4/UI starts)

- Win-call accuracy over the backtest window beats naive home-favorite
  baseline (~57%), or the whole game-board feature ships TRACKING-only
  (numbers shown, chips amber, spec updated with the honest result — same
  discipline as props' `passing_yards`-only VALUE gate).
- Brier score beats the naive baseline's Brier score.
- If gates fail: document `# REJECTED — evidence: <backtest file>` inline
  per this repo's process, ship the props restyle alone, skip the game
  board.

## Open questions (resolve in the plan, not here)

- Home-field Elo constant: fit from backtest, not asserted.
- Margin regression: linear rating-diff→margin vs a shrunk/capped version —
  backtest decides.
- Whether "coefficient" column ships at all if it reads too much like a
  bookmaker price (RG risk) — default to omitting it; win% + predicted
  score covers forebet's information content without inviting the same
  read.
