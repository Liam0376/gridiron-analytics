# Plan: zero weekly projections for confirmed-Out players

> Status (2026-09-10): backtest PASSED — implement on user go-ahead.
> Spec: `docs/superpowers/specs/2026-09-10-out-zero-weekly-spec.md`.

## Tasks

- [x] **1. Backtest (DONE).** ZERO arm on all-universe 2025 sample
  (n=8049; box-score-only samples can't contain Out players — first
  attempt fired 0 rows). Pinned (PYTHONHASHSEED=0): BASE
  4.6380/0.5949/0.6925 → ZERO 4.3000/0.6300/0.7115, paired-t **15.35**,
  corr Fisher z **-3.56**, fired on 362 rows. Passes all three gates.
- [x] **2. Implement.** DONE 2026-09-10: `project_player_stats(...,
  is_out=False)` zeroes counting stats post-weather, flags untouched;
  `build_weekly_projections(..., out_pids=None)` threads it through the
  weekly call only; `refresh.build_out_gsis_set` (direct gsis mapping);
  `config.OUT_STATUSES` + `is_out_status` canonical home.
- [x] **3. Gates + live verify.** DONE: pytest 212/4, hub untouched.
  Live (POST /refresh): Darnold fair 233.81 → **0.0** (Out badge kept),
  Lock unchanged 5.09, Darnold season **274.4** intact, Stafford 386.8.
