# Rejected ML evidence

This directory preserves the XGBoost point-level and stat-level model code
that was built, backtested, and **rejected for production** use.

See `../architecture-decisions/0004-ml-rejected.md` for the full decision
record. Short version: both XGBoost variants lost to `stat_projector.py`
on the 2025 holdout (point-level MAE 4.5562 vs. baseline 4.163), and the
stat-level per-stat gains were within noise (~0.01–0.05 MAE).

## What's here

- `ml_features.py`, `ml_train.py`, `ml_train_stat_level.py`,
  `ml___init__.py` — the model code, moved verbatim from
  `src/ffanalytics/ml/`.
- `test_ml_features.py`, `test_ml_stat_level.py`, `test_ml_train.py` —
  the matching tests, moved from `tests/`.

These files import `xgboost`, `scikit-learn`, and `numpy`. They are kept
in-tree so anyone revisiting the ML question has the exact code that
produced the rejection — not just the `meta.json` numbers.

## What's *not* here

- `data/models/xgb_meta.json` — the structured backtest record for the
  point-level model. **Stays in `data/models/`** because the model
  artifacts and meta belong together.
- `data/models/stat_level/meta.json` — same, for the stat-level model.
- `data/models/xgb_fantasy_v1.json`, `xgb_noK.json`, and the
  `stat_level/*.json` weight files — kept alongside the meta as the
  trained model artifacts. If you re-train, replace these in place; if
  you conclude the rejection holds, delete them.

## How to revisit

Read ADR 0004 first. Then run the backtests in this directory against a
**fresh** holdout — not the 2025 holdout that killed the original
attempts, since a year of new data doesn't change the verdict. The
bar to ship is: outperform `stat_projector.py` on per-position MAE and
pairwise accuracy, on a current-season validation slice, with the
features documented in the matching `meta.json`.