# Spec: blend weekly projections with Sleeper market projections

> Status (2026-09-23): DRAFT, awaiting Liam's confirm. Research done and
> committed (`scripts/backtest_market_blend.py`,
> `data/ml/backtest_market_blend_results.json`). No production change yet.

## Problem

The weekly model loses to the market at every position. `backtest_ecr.py`
showed ECR out-ranking it on Spearman (RB 0.78 vs 0.66, QB 0.68-0.77 vs
0.49-0.66). Nothing in the repo tests whether the point projection itself
should move toward the market. Every prior challenger (XGB, stat-level,
snap-share, HIER) tried to beat the market from our own features alone and
landed inside noise.

## Evidence

Freeze scope, production-verbatim `build_weekly_projections`: 2024+2025
REG weeks 4-18, box-score rows, true scoring. BASE reproduces n=10,356
(freeze 10,351), MAE 4.520. Cross-season: fit the model weight on one
season, score the other. Pooled convex blend
`pred = w*model + (1-w)*market` on QB/RB/WR/TE; K and rows without a
market value keep BASE.

| Arm | fit 2024, test 2025 | fit 2025, test 2024 | $0 after 2026-09-23 |
|---|---|---|---|
| SLP (Sleeper, rotowire) | MAE -0.185, t=6.81, w=0.15 | MAE -0.218, t=10.61, w=0.30 | yes |
| FPP (FantasyPros API dump) | MAE -0.248, t=10.06, w=0.10 | MAE -0.245, t=9.97, w=0.10 | no |
| ECR (nflverse, Friday) | MAE -0.035, t=3.44 | MAE -0.056, t=3.65 | yes |

Corr and pairwise go up in every passing arm (SLP: corr 0.637 -> 0.681,
pairwise 0.740 -> 0.759 on the 2025 holdout). Per position on 2025 (SLP,
per-position w): QB 7.45 -> 6.41, WR 4.29 -> 4.13, TE 3.57 -> 3.52,
RB 4.40 -> 4.36.

Both seasons pooled, blended rows only: model 4.541, Sleeper alone 4.311,
blend 4.286 at w=0.25 (the curve is flat from 0.20 to 0.25). Sleeper
alone beats the model; the blend adds about 0.025 on top.

Live 2026 week 1 (pre-kickoff model snapshots from `projection_snapshots`,
n=307): model 5.074, Sleeper 4.928, blend 4.901, paired-t 1.52. Same
direction, underpowered.

### Leakage checks

- Raw correlation with actuals on common rows: model 0.654, SLP 0.696,
  FPP 0.702. That's the honest-projection range. A post-game rewrite would
  sit far above it.
- About 5,400 Sleeper rows per season carry `updated_at` more than 24 hours
  after kickoff. On exactly those rows, SLP trails FPP (MAE 4.51 vs 4.44).
  A rewrite from actuals would beat everything. Reads as a bulk re-save.
- Snapshot timing is still worth something: Sunday ECR beats Friday ECR by
  about 0.04 MAE. The historical Sleeper values are final versions. The
  live path must snapshot before kickoff and gate on those snapshots, not
  on anything re-fetched later (Task 1).

## Design (proposed)

1. **Snapshot (instrumentation, no math change).** Every refresh already
   fetches Sleeper projections (`refresh.py:806`, `market_by_gsis`). Score
   them with the live league scoring and persist them to a new
   `market_snapshots` table (season, week, player_id, source, points,
   snapped_at). Same keying as `projection_snapshots`, so grading is a join.
2. **Blend function.** Add a pure `blend_with_market(model_pts, market_pts, w)`
   in `stat_projector.py`, with `MARKET_BLEND_W_MODEL = 0.25` in `config.py`
   and an inline `why`. QB/RB/WR/TE only, and only when market points exist
   and are greater than 0. Otherwise BASE. Out players stay 0 (out-zero wins).
3. **Shadow first.** A `MARKET_BLEND_ENABLED` flag defaults to False. While
   off, refresh writes the blended value to `projection_snapshots` under a
   `shadow` column, and nothing user-facing changes. Promotion follows the
   repo's existing shadow gate: at least N resolved 2026 player-weeks from
   pre-kickoff snapshots, with the blend beating BASE at paired-t of 2.0 or
   more on those.
4. **When promoted.** `projected_points` becomes the blend for weekly
   consumers (start/sit, lineup, trade weekly view, props fair lines). The
   model-vs-market comparison keeps the raw model. Blending both sides
   would make every edge shrink toward zero by construction.

## Gates (frozen)

- Research gate: passed (table above, both holdouts, t >= 2.0, corr and
  pairwise not worse).
- Live gate before the flag flips: 2026 pre-kickoff snapshots only, weeks
  4 and later, at least 1,500 QB/RB/WR/TE player-weeks (about 4 weeks),
  blend MAE below BASE with paired-t >= 2.0.
- Full suite green. Frozen conformal widths untouched. Interval recalibration
  on the blended center is a follow-up. Widths fitted on model residuals are
  conservative for a lower-error center, so this can't make coverage worse.

## Non-goals

- The paid FantasyPros API. The trial ends 2026-09-23; FPP is the ceiling
  reference only.
- Season/ROS projections. Weekly only here. Sleeper ROS is a separate
  question.
- K and DST. There are no market K projections in the scoped data. K stays
  BASE.
- Retiring the model. It still carries weight 0.25, it's the fallback when
  Sleeper has no row, and it drives stat-level props.
