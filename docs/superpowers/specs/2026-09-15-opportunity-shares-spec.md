# Spec: opportunity shares (xFP pull + TD expectation arms)

> Status (2026-09-15): DRAFT, awaiting user confirm on the plan.
> Proposal B from the 2026-09-15 external-inspiration research. Builds on A
> (gsis identity — shares join by gsis, never names). C (ECR) follows.

## Problem

Production projects receiving stats from history averages of outcomes
(yards, receptions) plus a flat 30% TD regression to the position mean.
It never looks at opportunity: same yards from 12 targets + 200 air yards
vs 5 targets + 40 air yards project identically, and every receiver's TDs
regress to the same mean regardless of red-zone role. Experts value the
reverse: volume (targets, air yards, WOPR) is sticky, efficiency (RACR,
catch rate) regresses, and expected-points models beat raw averages.

## Evidence (verified live 2026-09-15, nflreadpy, $0)

- `load_ff_opportunity`: 2024 (6,005 rows), 2025 (6,054), 2026 Week 1 (317),
  gsis-keyed, with team totals per row (`rec_attempt_team`,
  `rec_air_yards_team`) and nflverse-modeled expectations + diffs
  (`receptions_exp`, `rec_yards_gained_exp`, `rec_touchdown_exp`,
  `rec_fantasy_points_exp`). Exact target share, air share, WOPR
  (`1.5*target + 0.7*air`), and xFP gaps fall out with zero PBP parsing.
  Filter `week <= 18` (feed includes playoffs weeks 19-22, no season_type).
- `load_nextgen_stats(stat_type='receiving')`: 2025 (1,402 rows), 2026 Week 1
  (136 rows, min-targets threshold) with `percent_share_of_intended_air_yards`
  and `avg_intended_air_yards` (aDOT). Duplicates opportunity air share —
  reserved for display/role flags, not projection arms.
- Current PBP proxy shares (`src/ffanalytics/adapters/pbp.py:52`) stay as
  the research fallback; nothing is deleted until an arm passes.

## Expert judgment (the mechanism, not vibes)

- Primary arm X1 (xFP pull): trailing actual-vs-expected gaps mean-revert.
  Pull projected receiving yards/receptions a fraction k toward the
  trailing-xFP-implied level, capped. This subsumes "unrealized air yards"
  (a noisier subset of the same gap) — one arm, not two.
- Arm X2 (individualized TD pull): replace part of the flat 30%-to-mean TD
  regression (`stat_projector.py:249`) with a pull toward the player's own
  trailing xFP-implied TD rate. Distinct mechanism from X1 (role vs volume).
- Deliberately excluded: RACR/efficiency as inputs (less sticky than volume
  — display-only), aDOT shifts (role-change flags for manual review, not
  auto-adjustment at this sample), QB passing (isolate skill effects first;
  QB already moves under snap scaling).

## Design (proposed)

- B-1 ingestion (production-safe, no math change): `get_opportunity(season)`
  + `get_ngs_receiving(season)` in `adapters/nflverse.py` (same `_retry` +
  plain-dict pattern); pure `opportunity_features(rows)` builder in
  `refresh.py` returning per-(gsis, week) target_share/air_share/wopr/xfp
  gaps (zero-division safe, never raises); refresh caches
  `opportunity_<season>.json` + `ngs_<season>.json` with last-good fallback
  + `refresh_log` entry. Unit tests with fake `nfl_module=`.
- B-2 arms (research, new backtest script): X1 k-grid {0.15, 0.30} +
  X2 TD-pull grid, WR/TE/RB-receiving only, trailing-weighted opportunity
  history (same-season weeks<w, else prior season — the production history
  rule). Tested on the 2025 holdout (2024 priors, weeks 4-18) AND the 2026
  cumulative sample. Honest OOS, no tuning on the test window.
- B-3 verdict: pass -> production-flag spec (separate); fail ->
  `# REJECTED — evidence` inline in `stat_projector.py`, PBP proxy stays.

## Gates (frozen)

- Production freeze MAE 4.563 / Corr 0.648 / Pairwise 74.1% on the 2025
  holdout, variant-vs-BASE paired-t (p<0.05) with corr non-negative, 2026
  cumulative agreement in the same direction, full suite green.
- One week never promotes (same rule as the snap work). No retuning between
  weekly re-runs.

## Non-goals

- C (ECR), QB passing arms, efficiency inputs, aDOT auto-adjustment, hub
  display (until an arm passes), new deps, paid data, touching the frozen
  conformal widths or the snap-share verdicts.
