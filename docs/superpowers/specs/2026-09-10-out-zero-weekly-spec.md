# Spec: zero weekly projections for confirmed-Out players

> Status (2026-09-10): DRAFT, approved for spec+backtest; implement only
> on gate pass. Sibling of the REJECTED snap-share scale-down (that one
> shrank healthy backups and failed paired-t; this one zeroes only
> confirmed outs — near-tautological, gated anyway).

## Problem

The projector is injury-blind (stat_projector.py contains zero injury
references — verified). Simulated week 2 (league-avg game): Darnold
projects **163.1 pass yds while Out** (17 games of 2025 history drown one
13-yard week); Lock projects **65.7** (week-1's 187 blended 1/3 with thin
2025 mop-up history). So next week an Out player tops Seattle's sorts
while the actual starter sits at a third of starter volume. Lock's 65 is
the blend working as designed (converges with starts); Darnold's 163 is
stale output with no mechanism behind it. Exhibits measured 2026-09-10,
warm cache, week=1 rows.

## Design (proposed)

- `project_player_stats(..., is_out=False)`: when true, zero all counting
  stats post-weather, leave `is_empty_projection` as computed (Out is
  known, not unknown) and leave all other behavior identical.
- Threading: `build_weekly_projections(..., injury_by_pid=None)` —
  `{model_pid: report_status}` → boolean at the weekly call only. The
  `_neutral_points` season computation never receives it (a 1-week Out
  must not nuke season/ROS/auction values — explicit scope guard).
- `refresh.py` builds the map by inverting the Sleeper xwalk
  (`{gsis: status}` from `{sleeper_id: status}` cache); missing map or
  missing entry → `is_out=False` (today's behavior, never fail-closed).
- Out-set: the backend's existing 7-status set; canonical home becomes
  `config.py` (api.py keeps working untouched — no consumer changes).
- Scope: weekly model projections + derived fair lines only. Season/ROS,
  VBD, auction $, hub ordering untouched. `/projections`-tab rescoring
  is a separate discovery (it rescores history rows, not model output —
  not this task).

## Gates

- Extend scripts/backtest_snap_share.py with a ZERO arm (Out player-week
  → 0.0, everything else identical): must beat BASE on MAE paired-t
  (p<0.05) with no corr/pairwise regression beyond noise, on the same
  2025 holdout. Near-certain but gated anyway — same discipline.
- Unit tests: zeroing keeps flags; map threading; absent-map fallback.
- Suite 208/4 green; hub untouched (display already badges Out).
