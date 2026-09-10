# Plan: projection relevance (demote backups, starters first)

> Status (2026-09-10): DRAFT — stop for confirm, do not implement yet.
> Spec: `docs/superpowers/specs/2026-09-10-projection-relevance-spec.md`.
> Baseline restored: `src/ffanalytics/api.py` reverted, model+proxy
> restarted, `/projections` back to 220 rows.

## Ops note (learned 2026-09-10, do not repeat)

- `bash hub/start.sh` hangs in agent shells: foreground `npm run dev`
  (`:304`) / `wait` (`:285`), plus an interactive `[Y/n]` prompt
  (`:212`). It killed the running model+proxy when my timed-out run was
  terminated. Agent restarts: kill port, then
  `export $(cat .env | xargs) && .venv/bin/uvicorn ffanalytics.api:app
  --host 127.0.0.1 --port 8000 --reload --reload-dir src/ffanalytics`
  and `../.venv/bin/python server.py` from `hub/`. Never `cd`+chain;
  use `workdir`.

## Tasks

- [x] **1. Quantify weirdness (research, no code).** Measured 2026-09-10
  on `GET /projections`: **220 rows = 196 with 0 pts + 24 nonzero**
  (K 2, QB 3, RB 7, TE 4, WR 8). Zero-pt by pos: WR 67, TE 36, RB 29,
  QB 18, LB 13, CB 7, DT 6, + C/G/OT/DE/SAF/FS/P/UNK stragglers.
  Nonzero QBs: Drew Lock 14.78, Drake Maye 13.82, Sam Darnold 0.52
  (Lock > Maye is model output — demotion keeps both, order by pts).
  Props `/props/board` rows carry no slot field (confirmed keys:
  player_id/sleeper_id/injury_status/available/player_name/position/
  team/market/fair_line/sigma/actual) — starter status must be inferred.
  NOTE: board returned 0 rows right after a model restart (in-memory
  cache cold → 503 until POST /refresh); rewarm via refresh, not code.
  Verify: counts pasted here, no code touched.
- [x] **2. Depth-chart loader (hub-only).** SHIPPED as
  `hub/src/lib/depthChart.js` + `hub/src/lib/depthChart.json`
  (32 teams, 679 entries, snapshot of the gitignored root CSV —
  `FantasyPros_*.csv` is gitignored by convention, so the JSON is the
  committed artifact). Team map mirrored from
  `adapters/fantasypros_projections.py:42`; suffix-stripping norm
  mirrors `projections.js` `normName`. Smoke: Maye rank 0,
  Morton rank 2 → irrelevant, Penix Jr. matches, K untouched.
- [x] **3. Relevance sort helper.** SHIPPED as
  `hub/src/lib/relevance.js` (`sortByRelevance`, tier-then-score,
  stable, missing chart → identity). Fixture: QB1(1.0) > QB3(9.9),
  unknown-WR(50.0) demoted but kept.
- [x] **4. Projections view.** Tier applies to the default view only;
  any explicit column/dir click sets `userSorted` and stays pure.
  `/projections` shape unchanged (220 rows, same keys).
- [x] **5. Props modal.** `groupBoardPlayers` sorts by depth tier, then
  totalFair. Live NE/SEA: Maye/Darnold/JSN/Stevenson/A.J. Brown/
  Henderson on top; Russell/Ouzts/Latu/Kallerup at the tail.
- [x] **6. Full gates.** pytest 204 pass / 4 skipped, hub `npm run
  check` + `build` clean, `verify-isolation.sh` passed, curl shape
  check green. (Ops: `start.sh` hangs in agent shells — foreground
  vite/`wait` + `[Y/n]` prompt; agent restarts = per-port kill +
  direct launches with `.env`.)

## Explicitly not doing

- Hard-filtering any API response; `stat_projector` math; rescoring;
  `start.sh` rework; K/DEF handling.

## Follow-up: project-wide ordering + next-man-up (user-confirmed, SHIPPED)

- Ordering is generic (all 32 teams, every surface) — verified live on
  SF@LA and SEA@NE, not scoped to one game.
- Within-tier QB-backup demotion: healthy QB2+ sinks below relevant
  starters (Mac Jones 3rd → 23rd on SF@LA) while elevated Lock ranks
  with starters. RB/WR/TE committees untouched (their depth genuinely
  plays). Applied to: projections default sort, all props modals,
  auction default money board (explicit ?sort= stays pure), tier member
  display order (tier cuts untouched).
- Next-man-up elevation: QB1 confirmed Out (backend's own unavailable
  set, mirrored) elevates the healthy backup room — Lock starts,
  Darnold's Out badge stays. Questionable/Doubtful never trigger it.
- Deliberately skipped: waiver (API advice-ranked, reordering would
  diverge from the engine), team/matchups/roster/trade (slot- or
  selection-ordered, relevance N/A).
- Finals sort by actual (SHIPPED, user-caught 2026-09-10 evening): a
  final game's modal sorted by preseason fair buried who played —
  Darnold's 233.8 projection outranked Lock's card after a 13-vs-187
  game. `sortGameCards` orders finals by actual volume (nulls last),
  upcoming games keep relevance order. Project-wide (all game modals).
  Verified live: NE@SEA final opens Maye → Lock → JSN, Darnold 14/40.

## Follow-up bugs found while verifying (2026-09-10 evening)

- [x] **A. Rams invisible on props board (SHIPPED).** Root cause: Sleeper
  uses LAR, everything else (nflverse schedule, game predictions, hub)
  uses LA. `patch_proj_teams` rewrote matched model rows to LAR, so
  `teams=SF,LA` dropped all Rams except Garoppolo (patch-miss, kept LA).
  Same split broke rookie opponent remaps. Fix: `config.TEAM_CANONICAL`
  + `canonical_team()`, applied in `build_sleeper_team_map` and
  `build_rookie_rows`; hub snapshot regenerated with LA. Verified:
  SF,LA board 74→134 rows (LA 66 + SF 68), LAR gone from `/projections`.
  Side note: FP depth chart lists LAR QB order Stafford/Simpson/
  Garoppolo — Garoppolo is tier-1 (demoted) by the agreed top-2 rule.
- [x] **B. Negative fair lines (SHIPPED).** History-less third QBs
  projected negative yardage (Garoppolo -2.9) without tripping
  `is_empty_projection`. `_fair_board_rows` now skips `fair < 0`
  (no book posts negative lines). Verified: 0 negative lines on SF,LA.
- [ ] **C. Backup QBs project as starters (PROPOSED, not confirmed).**
  Drew Lock 14.78 weekly / Mac Jones 161.9 pass-yd fair: the projector
  has no playing-time prior — any backup with prior starts projects as
  a full starter. Proper fix is snap-share scaling in the projector
  (depth-chart-driven), which is a model-math change needing
  shadow/backtest gates per architecture.md. Needs its own spec —
  awaiting user go-ahead.
