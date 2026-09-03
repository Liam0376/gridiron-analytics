# ADR 0003 — Rejected methods, kept as evidence in `stat_projector.py`

- Status: Accepted
- Date: 2024 (projection-model iteration)
- Deciders: repo owner
- Scope: `src/ffanalytics/stat_projector.py` and its `data/models/*/meta.json` siblings

## Context

The projection model went through ~18 feature and weighting experiments
before settling on the current weighted-recent-average + TD regression +
usage-trend blend + Vegas-implied-total damping + weather-penalty +
prior-season blend. Each rejected experiment cost real backtest time. Some
are tempting enough that anyone new to the code will re-propose them. The user's explicit instruction: **"a rejected feature/heuristic
gets `# tested and REJECTED — evidence: ...` inline, not silent deletion."**

## Decision

Reject-methods are preserved in two places:

1. **Inline in `stat_projector.py`** — short comment blocks at the point
   each heuristic *would* have lived, documenting the backtest evidence
   that killed it (e.g. opponent defense factors, full Vegas scaling,
   home/away splits, rest-day adjustments).
2. **`data/models/<model>/meta.json`** — the structured record: feature
   list, train/val seasons, MAE, correlation, pairwise accuracy, bias,
   per-position MAE, and the explicit `status: "REJECTED"` with a `reason`
   string. The ML experiments at `data/models/xgb_meta.json` and
   `data/models/stat_level/meta.json` are the canonical evidence of the
   XGBoost / stat-level rejections.

Anyone proposing to re-add a rejected heuristic reads the inline evidence
first, then re-runs the backtest that has to **outperform** the production
model on a current-season holdout — not just match it.

## Consequences

Positive:
- New contributors (human or AI) see the rejection reason next to the
  code they would change. Avoids re-litigating the same debates.
- `meta.json` files give concrete numbers to argue against — not vibes.
- Comment-as-evidence matches the engineering-discipline reference repo
  pattern.

Negative:
- `stat_projector.py` carries ~18 dead-code-shaped comments. Acceptable
  cost; they're terse and load-bearing.
- The ML code (`src/ffanalytics/ml/`) was *not* preserved in-tree the same
  way — it was moved to `docs/rejected-ml-evidence/` after rejection. This
  is a deliberate split: production heuristic rejections stay inline;
  experimental-model rejections get a full evidence directory because the
  models themselves are large.

## Alternatives considered

- **Delete everything rejected:** Rejected — guaranteed to be re-proposed.
- **Keep rejected heuristics behind a feature flag:** Rejected — the
  flag would never be turned on without re-validation, and the code
  would still be a maintenance burden.
- **External wiki page only:** Rejected — out of tree, out of mind,
  rarely read.

## When to revisit

When a new data source becomes free (e.g. PFF stats, injury reports with
return probability, snap counts) that wasn't available for the original
backtests, a previously-rejected heuristic might deserve another look —
but only if the new data demonstrably moves the holdout MAE in a
direction the old evidence didn't cover.