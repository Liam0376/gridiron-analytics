# Plan: Snap/target-share retest on live 2026 (flag-gated)

> Status (2026-09-15): DRAFT — stop for confirm, do not implement yet.
> Spec: `docs/superpowers/specs/2026-09-15-snap-share-retest-spec.md`.
> Predecessor: `docs/superpowers/plans/2026-09-10-qb-snap-share-plan.md` (REJECTED,
> kept as record).

## Tasks

- [x] **1. Cumulative 2026 retest script (research, no prod code).** DONE 2026-09-15
  as `scripts/backtest_snap_share_2026.py` (default mode). Week 1 (n=652, QB
  n=81): BASE 4.485/corr 0.670/QB 7.613 vs V1_0.05 4.163/corr 0.682/QB 4.470;
  paired primary t=3.23 (QB t=4.61), corr z=-0.41 (variant better, noise band).
  Scales tied; V0==V1 in Week 1 (no trailing snaps yet). ZERO==BASE by
  construction (wiring check); out-rule ablation (BASE-NOOUT) t=-2.51, fired 7.
  Depth-name hit 72/81; snap coverage 30/32 teams (DEN/KC Week 1 missing,
  reported). Results: `data/ml/backtest_snap_share_2026_results.json`
  (committed). Suite 231 pass / 4 skipped stays green.
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
- [x] **2. 2025-holdout join-fix check (research, no prod code).** DONE 2026-09-15
  as `scripts/backtest_snap_share_2026.py --check-2025-join`. BASE and ZERO
  reproduce published to all decimals (4.6380/0.5949/0.6925,
  4.3000/0.6300/0.7115); V1_0.05 moves only by the join fix itself (4.3758 vs
  4.3680, pw 0.7054 vs 0.7060). Paired-t 13.97 vs published 13.70 (both on the
  all-universe n=8049 sample; the header's t=1.66 is the paired n=5425 sample,
  different cut, same REJECTED verdict). PASS: no sign flip.
  Incidental finding: `_metrics` pairwise is traversal-order dependent under
  tied actuals (DNP 0.0 pairs count correct iff the earlier row predicts
  lower), so the check reuses the predecessor's set-order traversal; the 2026
  mode uses sorted order and documents the caveat.
  Verify: `SLEEPER_LEAGUE_ID=test PYTHONHASHSEED=0 .venv/bin/python
  scripts/backtest_snap_share_2026.py --check-2025-join`.
- [x] **3. Skill-share measurement (research, no prod code).** DONE 2026-09-15
  as `scripts/backtest_snap_share_2026.py --skill-shares`, results committed
  at `data/ml/skill_share_2026.json` (Week 1 only, n small — direction read,
  not verdict). Played weeks: shares predict actual (RB target +0.61, WR
  +0.38, TE +0.42) but not surprise (RB +0.13, WR -0.17, TE ~0.0; QB n=35
  noise). DNP weeks: shares strongly negative vs surprise (RB -0.90, WR
  -0.80, TE -0.91) — that is the playing-time signal (they did not play),
  fixable by snap/out, not by target share. Full table in the task commit
  message. Default stays measurement-only; no v2 spec.
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
