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
