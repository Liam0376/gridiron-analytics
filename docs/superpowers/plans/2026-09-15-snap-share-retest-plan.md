# Plan: Snap/target-share retest on live 2026 (flag-gated)

> Status (2026-09-15): DRAFT — stop for confirm, do not implement yet.
> Spec: `docs/superpowers/specs/2026-09-15-snap-share-retest-spec.md`.
> Predecessor: `docs/superpowers/plans/2026-09-10-qb-snap-share-plan.md` (REJECTED,
> kept as record).

## Tasks

- [ ] **1. Cumulative 2026 retest script (research, no prod code).**
  New `scripts/backtest_snap_share_2026.py`: all-universe, all weeks played in
  2026 to date (starts at Week 1, grows weekly). History rule mirrors production
  (`week<target`, cross-season bypass + prior-season fallback per
  `src/ffanalytics/stat_projector.py:559`). Depth join with normalized names +
  current-team resolution (spec). Arms: BASE vs V1 scales {0.03,0.05,0.10} x
  {depth-only, recent-max} + ZERO. Reports MAE/corr/pairwise/bias overall +
  QB-only, paired-t BASE vs principle-picked V1_0.05 (0.05 = nearest empirical
  mop-up 0.043, same pick as predecessor), Fisher z for corr, fired-counts.
  Caches 2026 snaps/injuries under `data/nfl_cache/` (gitignored). Handles
  missing-team snap weeks (DEN/KC Week 1) by reporting coverage, not by
  dropping silently.
  Verify: `SLEEPER_LEAGUE_ID=test .venv/bin/python scripts/backtest_snap_share_2026.py`
  reproduces the spec's Week-1 numbers within seed noise (BASE ~4.64 / V1_0.05
  ~4.19 / QB 8.12->4.49 / overall t~4.9 / QB t~5.7), writes
  `data/ml/backtest_snap_share_2026_results.json` (gitignored or committed? —
  predecessor committed its JSON; confirm in review).
- [ ] **2. 2025-holdout join-fix check (research, no prod code).**
  Re-run `scripts/backtest_snap_share.py` with ONLY the join/identity fix
  (normalized names + depth-team where available, else same week-1-snap proxy)
  and confirm no sign flip vs the published REJECTED direction. If the join fix
  alone overturns 2025, the predecessor verdict gets an addendum, not a rewrite.
  Verify: diff of results JSON vs `data/ml/backtest_snap_share_results.json`
  reviewed in the task commit.
- [ ] **3. Skill-share measurement (research, no prod code).**
  Correlate 2025 PBP `target_share_wavg` / `snap_share_wavg`
  (`src/ffanalytics/adapters/pbp.py:214`) with 2026 Week-1+ surprise
  (actual minus BASE), split by DNP vs played. Ships as a table in the task
  commit message, not as code. Go/no-go for a skill-position v2 spec only if
  played-week surprise shows stable signal. Default: stays measurement-only.
- [ ] **4. Flag-gated implementation (only if cumulative gates pass).**
  `expected_snap_share` param + caller wiring + `config.OUT_STATUSES`
  canonicalization + identity/current-team helpers with unit tests (movers,
  suffix names, missing CSV, QB1-out override, scale-down-only, non-QB
  passthrough). Flag default OFF; flip is a separate explicit task after the
  gate review. Production freeze header in `stat_projector.py` gets the outcome
  line either way (`# REJECTED` or gate-pass + flag name).
  Verify: `SLEEPER_LEAGUE_ID=test .venv/bin/pytest -q` full suite green +
  `bash hub/verify-isolation.sh` (touches shared status set surface).
- [ ] **5. Weekly re-run note.**
  Until promotion, re-run Task 1 each week as 2026 games complete and append to
  `data/models/coverage_2026_history.json`-style tracking (same pattern as
  `scripts/validate_2026_coverage.py`). No retuning between runs.

## Explicitly not doing (v1)

- RB/WR/TE production scaling, `projection.py` retro-weight changes, hub display
  changes, conformal-width retuning, new deps/paid data, committing
  `data/nfl_cache/schedule_2026.json` churn (leave the working-tree mod alone).

## Verify (whole plan)

- `SLEEPER_LEAGUE_ID=test .venv/bin/python scripts/backtest_snap_share_2026.py`
- `SLEEPER_LEAGUE_ID=test .venv/bin/pytest -q`
- `bash hub/verify-isolation.sh` (only if Task 4 runs)
