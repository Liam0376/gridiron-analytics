# Spec: FantasyPros consensus as the weekly market source

> Status (2026-09-24): research done, committed (`scripts/backtest_fp_projections.py`,
> `scripts/backtest_fp_ml.py`, `data/ml/backtest_fp_projections_results.json`,
> `data/ml/backtest_fp_ml_results.json`, commits `99b97ca`, `58884e5`). No production
> change yet. This spec proposes wiring it in; needs Liam's confirm before Task 1
> (per market-blend precedent below) AND needs one open question answered first
> (see "Blocking open question").

## Problem

`2026-09-23-market-blend-spec.md` already blends the model with Sleeper
market projections (`MARKET_BLEND_ENABLED = False`, shadow capture live)
and separately found FantasyPros's dump-based projections (FPP arm) beat
Sleeper's blend gain on 2024/2025 (MAE -0.248/-0.245 vs Sleeper's
-0.185/-0.218) — but flagged FPP as a "ceiling reference only," not
deployable, because the trial was ending that same day (2026-09-23).

This session ran two bigger, independent backtests on the full 2020-2025
FantasyPros dump (`data/fantasypros_dump/fp.sqlite`, gsis-mapped
`proj_weekly`, box-score stats rescored through `calculate_fantasy_points`
— not FP's own `points` field, so scoring is apples-to-apples with the
model and the actual):

- `backtest_fp_projections.py`: FP alone vs `stat_projector` on holdout
  2023-2025 (n=18,698, QB/RB/WR/TE). FP: MAE 3.386 / Corr 0.758 /
  Pairwise 0.798. Model: MAE 4.200 / Corr 0.676 / Pairwise 0.729.
  Linear ensemble grid on train (2020-2022) picked **w=1.00** (100% FP,
  0% model) — model added zero linear lift on top of FP. Paired-t=42.05,
  p<0.0001.
- `backtest_fp_ml.py`: does XGBoost combining box-score features + FP
  projection beat FP alone? No. Both arms (features+FP, FP-only-ablation)
  lost to plain FP-alone on all three metrics, decisively (t=16.63 in
  FP's favor). `fp_proj_pts` dominated feature importance 3x over the
  next feature; box-score features carried no real OOS weight.

Conclusion from both: the model's box-score features don't carry
information FP's consensus hasn't already priced in. FP's raw number,
unmodified, is the best available weekly point estimate we have evidence
for — better than the model alone, better than blending with the model,
better than an ML layer on top of it.

## Blocking open question: is w=1.00 real, or a bigger-sample artifact?

`backtest_market_blend.py`'s existing FPP arm (2024/2025 only, per-position
0.05 grid, cross-season fit) found optimal model weight **0.10**, not 0.00
— i.e., FPP arm already found market dominant, but kept a small nonzero
model weight. That doc already notes FPP's surface is close to Sleeper's
("flat MAE surface" language used for SLP's per-position folds), and used
half the season-count and a finer per-position grid vs this session's
single pooled train/holdout split. The two results agree on direction
(market dominates hard) but disagree on magnitude (10% vs 0% residual
model weight) — not necessarily a contradiction, but not yet reconciled
either.

**Task 1 before anything else**: extend `backtest_market_blend.py`'s FPP
arm to the full 2020-2025 sample (same seasons as `backtest_fp_projections.py`)
and re-fit the w-grid there, so both analyses are answering the same
question on the same data. Lock whichever number survives — do not
average the two or split the difference.

## The bigger blocker: FP's API access

FantasyPros's premium trial ended 2026-09-23 (this repo's own $0-forever
rule). `FANTASYPROS_API_KEY` is removed from `.env`. There is no automated,
$0, live path to weekly FantasyPros projections going forward. The
existing season-only `adapters/fantasypros_projections.py` already
establishes the accepted pattern for this: **Liam manually exports a CSV
from fantasypros.com and drops it at a known repo path**; no API key, no
scraping, no ToS gray zone (matches [[project_opensource_scope]] — this
repo already treats FantasyPros market data as something not to
automate/scrape past what a logged-in human already does themselves).

**Open question only Liam can answer**: does fantasypros.com's free
(non-premium) account tier expose a weekly consensus *projections* export
(not just rankings/ECR, which nflreadpy already gets for free) as a CSV
download? If yes, this is buildable exactly like the season adapter. If
weekly point projections are premium-gated, this whole path is blocked
and FP's edge stays research-only (interesting, unshippable) until/unless
that changes. **This blocks Task 3 below — confirm before starting it.**

## Design (proposed, mirrors the Sleeper market-blend pattern already live)

The existing infra generalizes cleanly — market source is already just
`market_by_gsis: dict[gsis_id -> points]` fed into
`blend_with_market()` (`stat_projector.py:627`) and
`build_market_snapshot_rows()` (`refresh.py:448`). Swapping or stacking
sources doesn't need new architecture, just a second market_by_gsis
builder and a source-priority rule.

1. **CSV adapter (new).** `adapters/fantasypros_weekly_projections.py`,
   same column-index parsing style as `fantasypros_projections.py`
   (headers have duplicate names, parse by position not DictReader).
   Weekly file(s) dropped at a known path (e.g.
   `FantasyPros_Weekly_Projections_{POS}.csv` at repo root, gitignored,
   same as the season files). Output: `{gsis_id: raw_stats_dict}`, scored
   through `calculate_fantasy_points` + `DEFAULT_SCORING` — same mapping
   `backtest_fp_projections.py` already validated (corr 0.998 vs FP's own
   `points_ppr` field) — reuse that mapping function, don't rewrite it.
2. **Source priority in `refresh.py`.** When building `market_by_gsis`:
   prefer the FP weekly import for the current week if the file exists
   and is fresh (this week's date), else fall back to Sleeper
   (`map_market_to_gsis`, already live), else no market (BASE). This is
   an `if/elif`, not a blend of two markets — the backtests only tested
   FP-alone and Sleeper-alone as separate arms, never a same-week
   FP+Sleeper combination, so stacking them has no evidence behind it yet.
3. **Shadow first.** New `FP_MARKET_BLEND_ENABLED` flag, defaults False.
   Reuses `market_snapshots` (same table, tag the `source` column — check
   schema.sql, `market_snapshots` already has no `source` column per
   grep of `schema.sql:90-95`; add one, migration needed, matches
   `projection_snapshots`'s versioned-migration pattern per
   `docs/references/architecture.md`'s migration note, v10 -> v11).
4. **Live gate before flip**: mirror the Sleeper gate exactly
   (`config.py:101-105`) — >=1500 pre-kickoff QB/RB/WR/TE player-weeks,
   weeks >=4, paired-t >= 2.0 vs BASE, corr/pairwise not worse. Given the
   research-gate paired-t here is 42 (vs Sleeper's live 1.52,
   underpowered), the live gate is far more likely to clear fast once
   shadow capture starts, but no live number exists yet — capture it
   before flipping regardless.
5. **K/DST stay BASE.** No backtested evidence for either position (the
   API dump ran out of quota before reaching K/DST most years 2020-2025).
   Don't extend without evidence, matching the Sleeper spec's same
   K-exclusion for the same reason.

## Gates (frozen)

- Research gate: passed emphatically (t=42, not the borderline t~1.6-1.7
  that killed prior challengers). Reconciliation (Task 1 above) still owed.
- CSV-export feasibility: unconfirmed, blocks Task 3.
- Live gate before flag flip: >=1500 pre-kickoff player-weeks, weeks>=4,
  paired-t>=2.0, corr/pairwise not worse. Full suite green.

## Non-goals

- Automating FantasyPros access (scraping, reviving the API key). Manual
  CSV only, matching the existing season-adapter precedent.
- K/DST. No evidence either direction.
- Stacking FP+Sleeper in the same week. No backtested arm for this;
  priority fallback only (FP fresh > Sleeper > BASE).
- Retroactively re-litigating the Sleeper market-blend flag flip — that's
  a separate, already-scoped decision (`2026-09-23-market-blend-spec.md`).
