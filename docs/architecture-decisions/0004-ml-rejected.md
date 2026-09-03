# ADR 0004 — ML pipeline (XGBoost / stat-level) was rejected for production

- Status: Accepted
- Date: 2024 (after backtest completion)
- Deciders: repo owner
- Scope: `src/ffanalytics/ml/`, `data/models/`

## Context

After the projection model stabilized, two ML experiments were built and
backtested:

1. **Point-level XGBoost** (`src/ffanalytics/ml/train.py`,
   `data/models/xgb_meta.json`) — features = usage trends + Vegas
   + projected stat inputs + position dummies; target = actual fantasy
   points. Trained on 2023–2024, validated on 2025.
2. **Stat-level XGBoost** (`src/ffanalytics/ml/train_stat_level.py`,
   `data/models/stat_level/meta.json`) — one model per stat
   (passing_yards, rushing_tds, receptions, fg_made_*, etc.); fantasy
   points summed at projection time.

Both were tested against the current production model
(`stat_projector.py`) on the same 2025 holdout.

## Decision

**Both ML pipelines were rejected as production models.**

Evidence (recorded in `data/models/xgb_meta.json`):

- Point-level XGB: val MAE 4.5562 vs. baseline MAE 4.163. XGB *lost* to
  the heuristic model on the 2025 holdout. Pairwise accuracy 0.7480 vs.
  baseline 0.777.
- Stat-level XGB: per-stat MAE within ~0.01–0.05 of the heuristic's
  per-stat MAE — within noise.
- `status: "REJECTED"` is recorded in both `meta.json` files with the
  reason string ("val MAE 4.5562 > baseline 4.163 — XGB does not beat
  stat model; ensemble not winning per spec Task 5.").

Dependency cost:
- `xgboost`, `scikit-learn`, `numpy` add ~50 MB of installed weight for
  zero production benefit.
- XGBoost models are non-deterministic across versions, complicating
  reproducibility.

## Consequences

Positive:
- `stat_projector.py` remains the single production projection path —
  one mental model, one backtest surface, one set of constants.
- The `meta.json` records are kept in `data/models/` so anyone who wants
  to revisit ML has the exact feature list, hyperparameters, and
  holdout numbers to beat — not just "XGB didn't work."
- The `.py` files (`features.py`, `train.py`, `train_stat_level.py`)
  are moved to `docs/rejected-ml-evidence/` along with the matching
  test files (`tests/test_ml_*.py`). Out of the runtime import graph but
  kept in-tree for forensic reference.

Negative:
- Anyone who wants to try ML again has to read `docs/rejected-ml-evidence/`
  first to avoid re-doing the same experiments. Worth it.
- The `xgboost`, `scikit-learn`, `numpy` deps are still in
  `pyproject.toml` because the evidence scripts in
  `docs/rejected-ml-evidence/` import them. Dropping the deps requires
  vendoring the evidence dir or moving it to a separate venv.

## Alternatives considered

- **Ship XGB as an ensemble with `stat_projector.py`:** Tested briefly.
  Ensemble MAE was within noise of the heuristic alone. Not worth the
  complexity or extra dep.
- **Ship XGB as a "second opinion" surfaced in the hub:** Tempting —
  shows the work — but a second opinion that doesn't reliably beat the
  primary misleads more than helps. Rejected.
- **Delete the XGB code entirely:** Rejected — same evidence-preservation
  principle as ADR 0003. Code moves to `docs/rejected-ml-evidence/`.

## When to revisit

If a future feature fundamentally rewrites the input space (e.g. real
injury-probability data, route-running grades, or QB-specific WR
separation metrics become free) such that the 2025 holdout is no longer
representative, re-train XGB on the new feature set and beat the
heuristic's current MAE on a fresh holdout. Until then, the heuristic
model is the production path.