# Plan: FantasyPros market source (spec 2026-09-24-fp-market-source-spec.md)

Branch: `feat/trade-slot-uplift` (in place, solo mode). Stop for Liam's
confirm before Task 1. Task 3 additionally needs Liam to confirm the CSV
export exists on a free/non-premium fantasypros.com account before it starts.

- [x] Task 0: Reconciliation backtest — **not a single-number resolution,
  found a real sample-definition difference instead.**
  - `scripts/backtest_fpp_wide.py` reruns `backtest_market_blend.py`'s exact
    protocol (0.05 grid, per-position + pooled `wp` fit) on the wider
    2020-2025 sample, one direction (train 2020-2022, test 2023-2025,
    matching `backtest_fp_projections.py`'s split, pre-registered, no
    fold-shopping). Result: per-position w={QB:0.15, RB:0.0, WR:0.05,
    TE:0.1}, pooled w=0.05. MAE 4.2669-4.2684 vs BASE 4.5037 (n=15,441).
    This is close to the ORIGINAL 2-season finding (~0.10, MAE gain
    ~0.245) — reconciled at more data, under this methodology.
  - It does NOT reconcile with `backtest_fp_projections.py`'s w=1.00 /
    MAE 3.386 (n=18,698). Root cause found: **the two scripts measure
    different universes, not the same question at different scales.**
    `backtest_market_blend.py`'s `build_rows()` iterates
    `stats_{season}.json` rows directly — only players nflverse recorded a
    stat line for that week ("played" universe). `backtest_fp_projections.py`
    explicitly documents (its own header, line 21-22) "all-universe (DNPs
    included, matches `backtest_ecr.py`)" — it projects every rostered
    player on a team that played, including inactives/DNPs, same as
    `backtest_ecr.py`'s `_model_week`. Row counts confirm it: 15,441
    (played-only) vs 18,698 (all-universe) for the same seasons/positions/
    weeks, ~17% more rows in the all-universe version.
  - **Implication, not yet settled**: if most of FP's edge in the
    all-universe measurement comes from correctly pricing in inactive/
    injured players a trailing-stats model can't see pre-kickoff (the
    same mechanism this repo's own out-zero rule already targets for
    confirmed-Out players, per `backtest_opportunity.py`'s header), then
    the real production question isn't "what blend weight" — it's
    "does `stat_projector`'s existing out-zero/injury-status handling
    already capture most of this, and is the residual played-only edge
    (~0.24 MAE, matches both samples at that definition) the only genuinely
    new information FP buys us." That's un-tested — needs a same-universe,
    apples-to-apples rerun (e.g. add all-universe rows to
    `backtest_market_blend.py`'s pipeline, or restrict
    `backtest_fp_projections.py` to played-only rows) before locking
    `FP_BLEND_W_MODEL` to either 0.05 or 1.00. **Not locking a number
    yet — flagging for Liam's call**, since production has to project the
    full roster weekly (all-universe is the real shape of the problem),
    which argues for taking the w=1.00 number seriously rather than
    splitting toward the played-only 0.05, but that's Liam's/the parent's
    decision, not mine to make unilaterally on a fork.
  - Verify: `PYTHONHASHSEED=0 .venv/bin/python scripts/backtest_fpp_wide.py`
    prints both forms' fit + holdout numbers, written to
    `data/ml/backtest_market_blend_results.json` under key
    `FPP_2020_2025` (existing SLP/ECR/FPP 2-season arms untouched).
- [x] Task 0b: does stat_projector's existing out-zero rule (already free,
  already production, `api.py:1559`) explain the all-universe gap?
  **No — it barely moves it.** `scripts/backtest_fp_outzero.py` reruns
  `backtest_fp_projections.py`'s exact all-universe holdout (2023-2025,
  n=18,698, same row count confirms same universe) with `is_out=True`
  passed into `project_player_stats` for any player-week flagged in
  nflverse's weekly injury report (`report_status` in the mirrored
  `_UNAVAILABLE` set — same source `backtest_snap_share.py` already uses,
  fetched free via `nflreadpy.load_injuries`, cached
  `data/nfl_cache/injuries_{2020..2024}.json` this run, 2025/2026 already
  present).
  - Only 93/18,698 rows (0.5%) were flagged Out. Root cause checked and
    confirmed real, not a join bug: thousands of "out" designations exist
    per season league-wide (996-1,382/season in the raw injury feed), but
    almost none land in this specific sample — FP's own `proj_weekly`
    table mostly doesn't project players who are actually out (the
    common-players join already excludes them upstream), so the
    intersection of "flagged out" AND "FP still gave them a row" is
    naturally tiny.
  - MAE: no-out stat 4.200 -> out-zero stat 4.178 (2.8% of the 0.814 MAE
    gap to FP closed). Corr 0.676->0.678, pairwise 0.729->0.731. Paired-t
    (out-zero stat AE vs FP AE) = 41.3, p<0.0001 — essentially unchanged
    from the original t=42.05.
  - **Verdict: the injury-handling hypothesis is rejected.** FP's edge is
    not primarily about correctly zeroing inactive players — that
    mechanism was already nearly irrelevant to this sample. The real gap
    (corr 0.676 vs 0.758, MAE 4.18 vs 3.39, worst at QB: 6.93 vs 4.20)
    survives fully intact. FP's advantage lives somewhere else — most
    likely genuine judgment on active-but-uncertain-role players
    (committee backfields, emerging roles, game-script calls) that a
    trailing-box-score model structurally can't see, consistent with
    this session's earlier ML-ablation finding (XGBoost + box features
    couldn't find anything beyond FP's raw number either). **The
    all-universe w=1.00 finding stands** — not an out-zero artifact.
  - Verify: `PYTHONHASHSEED=0 .venv/bin/python scripts/backtest_fp_outzero.py`
    prints the no-out/out-zero/FP comparison, written to
    `data/ml/backtest_fp_outzero_results.json`. Full suite: 313 passed,
    4 skipped.
- [ ] Task 1 (blocked on Liam confirming CSV export access): weekly CSV
  adapter.
  - `adapters/fantasypros_weekly_projections.py`, column-index parsing
    matching `fantasypros_projections.py`'s style. Reuse
    `backtest_fp_projections.py`'s stat-key-to-scoring-key mapping
    function directly (don't reimplement — it's already validated,
    corr 0.998 vs FP's own `points_ppr`).
  - Output: `{gsis_id: points}` scored via `calculate_fantasy_points` +
    live league scoring (same pattern as `score_sleeper_stats`).
  - Tests: malformed/missing CSV, position coverage, gsis join rate on a
    fixture file.
- [ ] Task 2: `market_snapshots` schema migration (source column).
  - `schema.sql` migration v11 (check current version first —
    `projection_snapshots` was v10 per architecture.md).
  - Backfill: existing Sleeper-only rows get `source='sleeper'`.
- [ ] Task 3: source-priority wiring in `refresh.py`.
  - `market_by_gsis` build order: FP weekly file (if present and dated
    this week) -> Sleeper (`map_market_to_gsis`, already live) -> none.
  - `build_market_snapshot_rows` tags `source` per the row's actual origin.
  - No same-week FP+Sleeper stacking — no backtested arm supports it
    (spec non-goals).
- [ ] Task 4: `FP_MARKET_BLEND_ENABLED` flag (defaults False) +
  `blend_with_market()` reuse (source-agnostic already, just needs the
  right `market_pts` fed in — check whether `w_model` should differ from
  Sleeper's `MARKET_BLEND_W_MODEL` per Task 0's locked number).
  - Tests: mirror `test_market_blend.py`'s structure for the new source.
- [ ] Task 5: `scripts/validate_fp_market_2026.py`, a `grade()` mirroring
  `validate_market_blend_2026.py` — live gate: >=1500 pre-kickoff
  QB/RB/WR/TE player-weeks, weeks>=4, paired-t>=2.0 vs BASE, corr/pairwise
  not worse than BASE.
  - Tests: waiting, pass, week-4 scope, DNP rows (copy the existing
    suite's cases, swap the source).
- Verification: full suite green after each task. Re-run
  `backtest_fp_projections.py` unchanged (regression check the refactor
  didn't touch its numbers).
- [ ] Task 6 (after live gate passes and Liam confirms): flip
  `FP_MARKET_BLEND_ENABLED`.
  - Update `docs/ACCURACY.md` production row.
  - Full suite.
