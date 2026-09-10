# Plan: QB snap-share scaling

> Status (2026-09-10): DRAFT — stop for confirm, do not implement yet.
> Spec: `docs/superpowers/specs/2026-09-10-qb-snap-share-spec.md`.

## Tasks

- [x] **1. Derive the curve (research, no prod code).** DONE 2026-09-10
  via `nflreadpy.load_snap_counts(2025)` REG QBs (687 rows, 32 teams;
  PFR codes already match schedule convention incl. LA). Rank = week-1
  snap order (documented proxy for preseason depth; traded QBs deduped
  to primary team; DNP weeks zero-filled; byes excluded via played
  team-weeks). E[weekly share]:
  - QB1 playing: **0.946** (cap 1.0)
  - QB2, QB1 in (mop-up, n=421): **0.043**, p50 0.0
  - QB2, QB1 out (takeover, n=106): **0.82**, p50 1.0
  - QB3+, QB1 in (n=199): **0.028** / QB1 out (n=137): 0.25
  Design read: healthy starter ahead → scale ≈ **0.05** (round up from
  0.043; backtest compares {0.03, 0.05, 0.10}); confirmed-out starter →
  next-up **1.0** (matches hub rule + 0.82 takeover mean). Jones 161.9 ×
  0.043 ≈ 7 yds; Lock keeps full via override. 4/31 teams lost the
  week-1 snap crown (churn is IN the means — expectation, not
  conditional-on-health).
- [x] **2. Backtest harness.** SHIPPED as scripts/backtest_snap_share.py
  (fully offline: stats/schedule cache + one-time snaps/injuries fetch
  cached gitignored). Arms: BASE vs scales {0.03,0.05,0.10} x
  {depth-only, +recent-max, +sustained-takeover}. Depth-only craters
  (corr 0.64→0.60 — mid-season takeovers); sustained-takeover loses to
  plain recent-max (relief spikes are rarer than feared). Best: V1_0.05.
  VERDICT: **REJECTED** — MAE -0.028 / QB MAE -0.28 / bias fixed /
  pairwise flat, but paired-t t=1.66 (p~0.10) overall AND QB-only,
  corr -0.003 = noise (Fisher z=0.33). Same bar that rejected XGB.
  Evidence: data/ml/backtest_snap_share_results.json + header note in
  stat_projector.py. Scales {0.03,0.05,0.10} were statistically tied;
  0.05 had been principle-picked (nearest empirical 0.043) — moot.
- [ ] **3. Implement (only if gates pass).** CANCELLED — gates did not
  pass. No production code changed.
- [ ] **4. Full gates + coverage re-run note.** Suite untouched by this
  task (no prod diff); sequel recorded in the header note: re-run the
  variant comparison on real 2026 weeks once n suffices.

## Explicitly not doing (v1)

- RB/WR/TE shares, ECR-as-primary (fallback only), hub display changes,
  touching the frozen conformal widths.
