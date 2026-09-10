# Spec: projection relevance — demote backups, sort starters first

> Status (2026-09-10): DRAFT, awaiting user confirm on the plan. User
> reports: (a) props game-modal cards show bench/reserve players before
> starters; (b) "weird projections" for backup QBs and end-of-bench
> players. User supplied `FantasyPros_Fantasy_Football_2026_Depth_Charts.csv`
> (repo root, 347 lines, QB/RB/WR/TE ECR depth per team).
> User decisions (2026-09-10): **demote, don't remove** · **top-N per
> position** · revert-broken-filter-now (done, baseline restored).

## Evidence (measured 2026-09-10, before any new change)

- `GET /projections?limit=500` returns **220 rows**: 196 with
  `projected_points == 0`, plus non-skill positions (LB 13, CB 7, DT 6,
  …). Only 24 rows have points > 0.
- Props `/props/board` rows carry no roster slot — starter status cannot
  be read from the payload, only inferred.
- Hub `groupBoardPlayers` (props.js) sorts by summed `fair_line`, which
  structurally favors QBs (passing yards ~250 vs receiving ~50) and says
  nothing about starter vs bench.

## Relevance definition (proposed)

- Parse the depth-chart CSV into ordered lists per (team, position) by
  ECR row order. `depth_rank` = 0-based index.
- Top-N cutoffs (defaults, tunable in one place): **QB 2, RB 4, WR 6,
  TE 3**. K/DEF untouched (different tabs, no depth data).
- Required mappings (bugs that sank the first attempt):
  - Team full name → abbr: reuse the map at
    `adapters/fantasypros_projections.py:42`, do not hand-roll another.
  - Name norm must strip suffixes (Jr/Sr/II/III/IV/V) — mirror hub
    `projections.js` `normName`, plus remove non-alphanumerics.
- CSV is a snapshot: if missing/unparseable, loader returns empty and
  **all sorting falls back to current behavior** (never fail-closed).

## Non-goals

- No removal of any player from any API response (user chose demote).
- No change to `stat_projector.py` math, no rescoring changes.
- No `/projections` response-shape change beyond additive fields (and
  preferably none — see plan, hub-only approach).
- No `start.sh` rework in this task (documented as ops note in plan).

## Open points for plan confirm

- Exact top-N values (proposal above).
- Sort key within relevance tier: keep `projected_points` desc (projections)
  and `fair_line`-based (props), or unify.
