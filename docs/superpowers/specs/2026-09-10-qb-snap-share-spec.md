# Spec: QB snap-share scaling (backups project as starters)

> Status (2026-09-10): DRAFT, awaiting user confirm on the plan. Follow-up
> to the projection-relevance work: display ordering now demotes healthy
> backups everywhere, but their raw numbers are still wrong.
>
> Status (2026-09-10, later): **REJECTED by its own gates — do not
> implement.** Backtest (scripts/backtest_snap_share.py,
> data/ml/backtest_snap_share_results.json): directionally positive
> (MAE -0.028, QB MAE -0.28) but paired-t t=1.66 (p~0.10) overall and
> QB-only — not significant. Record kept so nobody re-tries blind.

## Problem

`project_player_stats` (stat_projector.py:332) has no playing-time input.
With no same-season history and prior REG rows, base = full prior-season
average (lines 376-383) — i.e. as-if-starter. A backup with prior starts
projects starter volume. Exhibits (live 2026-09-10): Mac Jones 161.9
pass-yd fair as SF's healthy backup; Drew Lock 14.78 weekly. Early-season
thin blends (n<3) have the same shape. Hub demotion hides these; it does
not correct them — auction $, VOR, waiver improvement all still consume
the inflated numbers.

## Design (proposed)

- New optional param `expected_snap_share` (0..1, default 1.0 = today's
  behavior) on `project_player_stats`, applied to volume + TD counting
  stats after the existing pipeline (post-weather, pre-empty-flag).
  Scale DOWN only — never inflate above 1.0.
- Share source priority at refresh (build_weekly_projections caller):
  1. Depth-chart CSV rank → empirically-derived share curve. Snap data
     exists $0: `nflreadpy.load_snap_counts` (verified installed) — fit
     the QB curve from 2025 (share by depth rank), don't guess it.
  2. Fallback: FantasyPros ECR curve when the CSV is missing/stale
     (CSV is gitignored, absent on fresh clones — must degrade, never crash).
  3. Fallback: 1.0 (current behavior).
- Injury override (mirrors hub next-man-up rule): starter confirmed Out
  (backend unavailable set) → next healthy rank gets 1.0. Canonicalize
  the out-set in `config.py` (single source); `api.py` and the hub
  comment adopt it.
- Scope v1: **QB only**. QB is binary (one starter); RB/WR committees
  genuinely play their depth and scaling them risks under-projecting
  FLEX-relevant RB2/WR3s. Extend only on user confirm + gates.
- All values TBD by backtest — the spec fixes the mechanism and the
  gates, not the numbers.

## Gates (frozen, per stat_projector.py header)

- Honest OOS backtest on the 2025 holdout (nested protocol precedent:
  scripts/backtest_stat_level.py): must beat **MAE 4.563 / Corr 0.648 /
  Pairwise 74.1%** on all three, or at minimum regress none beyond noise
  AND show QB-subgroup improvement. Loser → `# REJECTED — evidence`
  inline, no merge.
- Re-run scripts/validate_2026_coverage.py as 2026 weeks complete.
- Full suite 208 pass / 4 skipped stays green.

## Non-goals

- No RB/WR/TE scaling in v1. No hub changes (display already correct).
- No new paid data, no new deps, no model-server latency change
  (share resolved once per refresh, not per request).
