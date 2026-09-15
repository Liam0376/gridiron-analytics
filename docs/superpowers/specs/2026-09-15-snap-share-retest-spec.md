# Spec: Snap/target-share retest on live 2026 (flag-gated)

> Status (2026-09-15): DRAFT, awaiting user confirm on the plan. Sequel to
> `docs/superpowers/specs/2026-09-10-qb-snap-share-spec.md` (REJECTED by its
> own gates on the 2025 holdout — record stands, this does not rewrite it).

## Problem

Production projections use zero direct snap/target-share weight. Live path is
`src/ffanalytics/stat_projector.py:352` `project_player_stats()`: weighted
recent avg -> TD regression (30%) -> usage trend (15%, capped +-50%) ->
Vegas damped -> weather. The only share-adjacent term is the usage trend on
volume outcomes (`rushing_yards`, `receiving_yards`, `receptions`,
`passing_yards`), which reacts after yards move, not when role changes.

2026 Week 1 (live, n=652 player-weeks, QB n=81) re-exhibits the backup-as-starter
shape: BASE MAE 4.637, bias +2.204, QB MAE 8.124. Top QB over-projections are
backups projected as starters (Mac Jones SF rank1 12.5->0.0, Mariota, Winston,
Mills, Penix, Flacco all 12-15->0.0). Skill over-projections are mostly DNPs
(actual 0.0) where a target-share term alone would not help without a
snap/injury signal. Reception share is an outcome, not a pre-week predictor in
the current pipeline.

## Evidence (research, no prod code changed)

1. 2025 holdout verdict stands: `src/ffanalytics/stat_projector.py:42`,
   `data/ml/backtest_snap_share_results.json`, `scripts/backtest_snap_share.py`.
   Directionally positive (MAE -0.028, QB MAE -0.28) but paired-t 1.66
   (p~0.10), corr -0.003 = noise. REJECTED under the same bar as XGB.
2. 2026 Week 1 live retest (2026-09-15, inline research script, same
   all-universe discipline as `scripts/backtest_snap_share.py`: 2025 history +
   2024 priors, 2026 Week 1 actuals, DEFAULT_SCORING):
   - Depth source: `FantasyPros_Fantasy_Football_2026_Depth_Charts.csv`
     (preseason, honest pre-week signal). Name join normalized (strip
     Jr/Sr/II/III/IV/V, punctuation) and joined on depth-team, NOT history
     team, so offseason movers resolve correctly (Geno NYJ QB1, Kyler MIN QB1,
     Tua ATL QB1, Fields KC QB2; Russell Wilson in no chart).
   - Current-team rule: depth-team when the name is charted, else history
     team. Game context (Vegas/weather/opponent) follows current team.
   - Arms: BASE (share 1.0) vs V1_recentmax equivalents at scales
     {0.03, 0.05, 0.10} applied QB-only post-weather, plus ZERO (confirmed-Out
     -> 0.0 via `nflreadpy.load_injuries(2026)`, same UNAVAILABLE set as
     `src/ffanalytics/config.py:145` OUT_STATUSES).
   - Result Week 1: BASE 4.637 / corr 0.656 / QB 8.124 vs V1_0.05 4.186 /
     corr 0.681 / QB 4.495. Overall paired-t 4.95 (diff +0.451), QB-only 5.74
     (diff +3.63). Scales {0.03,0.05,0.10} tied (same as 2025). ZERO t=2.51,
     fired 7, diff +0.110.
   - Honest misses kept: rank0 starters never scaled, so Stafford LA
     (24.9->6.1 bad game, snap 0.84), Kyler MIN (depth QB1, snap 0.17),
     Darnold SEA (depth QB1, snap 0.10), Shedeur CLE (depth QB1, DNP), Bo Nix
     DEN and Maye NE (bad games, Maye snap 1.0) all stay as misses. Depth is
     expectation, not truth.
3. Caveats (why Week 1 alone promotes nothing): n=1 week (QB n=81); Week 1 is
   chaos week (ATL QB room: Tua rank0 DNP + QB1-out override firing for Penix);
   `nflreadpy.load_snap_counts(2026)` Week 1 covers 30/32 teams (DEN/KC game
   missing at test time); identity join needs the normalization above plus
   current-team resolution or movers mis-rank (naive history-team join left
   29/81 QBs at rank99, including true starters). Any production wiring must
   include all three fixes or it ships the confound, not the signal.

## Design (proposed, v1 = QB only)

- New optional param `expected_snap_share` (0..1, default 1.0 = today's
  behavior) on `project_player_stats`, applied to QB volume + TD counting
  stats post-weather, pre-empty-flag. Scale DOWN only, never inflate.
  Behind a caller-side flag defaulting OFF (production gate decides flip).
- Share source priority at refresh (`build_weekly_projections` caller):
  1. Preseason/weekly depth CSV rank -> empirical curve (mop-up ~0.05 for
     healthy-backup QB2, 1.0 for QB1, 1.0 for next-up when starter confirmed
     Out). CSV is gitignored, absent on fresh clones -> degrade, never crash.
  2. Fallback: recent-max snap smoothing (max of depth scale vs trailing-3
     mean) so mid-season takeovers are not cratered (lesson of the 2025
     depth-only arm, corr 0.64->0.60).
  3. Fallback: 1.0 (current behavior).
- Identity: normalize names (suffix/punctuation strip) and resolve
  current team via depth chart first, Sleeper roster patch second, history
  team last. Unit-tested on movers (Mahomes II, Minshew II, D'Andre Swift).
- Injury override: starter confirmed Out (`config.OUT_STATUSES`, single source;
  `api.py` keeps its mirror with a comment) -> next healthy rank gets 1.0.
- Skill-position target/snap/reception shares: measurement only in v1. PBP
  shares (`src/ffanalytics/adapters/pbp.py:214`) stay research-side; no
  production input until a pre-registered test shows OOS signal. Rationale:
  Week 1 skill misses are DNPs (need snap/injury, not target share) and share
  of receptions is an outcome of the same volume the pipeline already averages.

## Gates (frozen)

- Production freeze stands: MAE 4.563 / Corr 0.648 / Pairwise 74.1%
  (`src/ffanalytics/stat_projector.py:8`). Promotion needs ALL of:
  1. Cumulative 2026 retest (weeks played to date, all-universe, same nested
     discipline as `scripts/backtest_snap_share.py`) beats or ties all three
     with no regression beyond noise, AND QB-subgroup paired-t significant
     (p<0.05) with corr non-negative vs BASE;
  2. 2025-holdout re-run with the FINAL join/identity code still shows the
     published direction (no sign flip from the join fix);
  3. Full suite green (`SLEEPER_LEAGUE_ID=test .venv/bin/pytest -q`).
- Week 1 alone (this spec's evidence) is a trigger for the work, not a pass.
  Re-run the cumulative gate each week; n=1 week never flips the flag.
- Loser -> `# REJECTED — evidence` inline in `stat_projector.py`, no merge.
  Same bar that rejected XGB.

## Non-goals

- No RB/WR/TE scaling in v1. No `projection.py` retro-weight changes (the
  0.4/0.3 `use_features=True` path stays retro-only; real predictions stay
  `use_features=False`).
- No hub display changes (demotion already correct). No paid data, no new
  deps, no frozen conformal-width retuning.
