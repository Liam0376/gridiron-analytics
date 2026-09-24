#!/usr/bin/env python3
"""XGBoost(box-score features + FP projection) vs FP-alone (fp-ml-ensemble spec).

Open question: the linear ensemble in backtest_fp_projections.py locked
w=1.00 (stat_projector's own point output adds zero LINEAR lift on top of
FantasyPros' consensus projection, holdout paired-t=42.05 p<0.0001 in favor
of FP — see data/ml/backtest_fp_projections_results.json, committed 99b97ca).
This script asks a different question: does a NONLINEAR model (XGBoost) that
sees the raw box-score-derived features (stat_projector's prior methodology,
FEATURE_COLS from docs/rejected-ml-evidence/ml_train.py) *and* the FP
projection together find structure the FP number alone misses?

PRE-REGISTERED GATE (written before running, not moved after seeing results):
  Baseline to beat is FP-ALONE on the 2023-2025 holdout (n=18,698 from the
  prior backtest): MAE=3.386, Corr=0.758, Pairwise=0.798. Beating the old
  production stat_projector baseline (4.563/0.648/0.741) is NOT sufficient —
  FP-alone already clears that trivially, so that comparison is meaningless
  now. XGBoost(features+FP) must beat FP-alone on ALL THREE metrics on
  HOLDOUT to count as a real win. Tie or loss is a valid REJECTED result,
  reported as such, no post-hoc retuning to rescue it.

Protocol (nested, anti-leakage, mirrors backtest_ml.py):
  - Fit fold: 2020-2021 (weeks 4-18, all-universe, QB/RB/WR/TE only — the FP
    dump has no K/DST weekly rows 2020-2025).
  - Early-stop fold: 2022 (used ONLY to pick best_iteration via XGBoost's
    eval_set early stopping; never touches the holdout).
  - Holdout (evaluated ONCE, locked model from the fit+early-stop folds):
    2023-2025 — same seasons/weeks as backtest_fp_projections.py's holdout,
    for apples-to-apples comparison.
  - Same XGBoost hyperparams as ml_train.py's PARAMS (n_estimators=500,
    max_depth=5, lr=0.03, subsample=0.8, colsample=0.8, reg_lambda=1.0) — no
    new hyperparameter search, that's a fresh p-hacking surface.
  - Second arm (ablation): XGBoost trained on fp_proj_pts as the ONLY
    feature — sanity check that wrapping FP's number in a tree model doesn't
    itself hurt vs using the linear number directly.

Data joins: reuses scripts/backtest_fp_projections.py's _season_rows (now
returns player_id) for stat_pts/fp_pts/actual_pts, and
docs/rejected-ml-evidence/ml_features.py's build_training_rows for the
box-score FEATURE_COLS. Rows require both a build_training_rows feature row
AND an FP projection to exist for the same (player_id, season, week) —
common-players discipline, same as the prior two backtests.

Known scope limits (documented, not hidden):
  - PBP-derived features (target_share_wavg, air_yards_wavg, snap_share_wavg,
    redzone_*) are only cached for 2023-2025 (data/nfl_cache/pbp_*.json).
    2020-2022 rows get zero for those ~8 columns — degrades gracefully (a
    zero-variance column earns no XGBoost splits) but is a real gap, not a
    free lunch. Fetching PBP back to 2020 is a separate task if ever wanted.
  - fg_*_proj / position_K columns are always zero (K excluded from scope).

Writes data/ml/backtest_fp_ml_results.json.
"""
import importlib.util
import json
import math
import os
import sys
from pathlib import Path

import numpy as np

os.environ.setdefault("SLEEPER_LEAGUE_ID", "test")

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))
REJECTED_DIR = REPO_ROOT / "docs" / "rejected-ml-evidence"
if str(REJECTED_DIR) not in sys.path:
    sys.path.insert(0, str(REJECTED_DIR))

from ml_features import build_training_rows  # noqa: E402
from ml_train import FEATURE_COLS, PARAMS  # noqa: E402


def _load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


fpback = _load_module("backtest_fp_projections", REPO_ROOT / "scripts" / "backtest_fp_projections.py")

CACHE = REPO_ROOT / "data" / "nfl_cache"
OUT_JSON = REPO_ROOT / "data" / "ml" / "backtest_fp_ml_results.json"
FP_BASELINE = {"mae": 3.386, "corr": 0.758, "pairwise": 0.798}  # FP-alone holdout, from 99b97ca
POSITIONS = fpback.POSITIONS  # ("QB", "RB", "WR", "TE")
FIT_SEASONS = (2020, 2021)
EARLYSTOP_SEASON = (2022,)
HOLDOUT_SEASONS = (2023, 2024, 2025)
ALL_SEASONS = (2020, 2021, 2022, 2023, 2024, 2025)
ML_FEATURE_COLS = FEATURE_COLS + ["fp_proj_pts"]


def _load_cache(name):
    with open(CACHE / name, encoding="utf-8") as f:
        return json.load(f)


def _pbp_for(season):
    path = CACHE / f"pbp_{season}.json"
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _season_feature_rows(season):
    """build_training_rows output for `season`, QB/RB/WR/TE only, keyed by
    (player_id, week). Passes season-1 into the seasons filter too so prior-
    season blending isn't starved, then drops the season-1 target rows."""
    stats = ([r for r in _load_cache(f"stats_{season}.json") if r.get("season_type", "REG") == "REG"]
             + [r for r in _load_cache(f"stats_{season - 1}.json") if r.get("season_type", "REG") == "REG"])
    sched = _load_cache(f"schedule_{season}.json")
    pbp = _pbp_for(season)
    rows = build_training_rows(all_stats=stats, all_schedules=sched, pbp_features=pbp,
                                seasons=[season, season - 1], min_week=4, max_week=18)
    out = {}
    for r in rows:
        if r["season"] != season or r["position"] not in POSITIONS:
            continue
        out[(str(r["player_id"]), int(r["week"]))] = r
    return out


def _merged_rows(season):
    """Join build_training_rows features with fp/stat backtest rows on
    (player_id, week). Only rows present in both (common-players + FP has a
    projection) survive."""
    feat_by_pw = _season_feature_rows(season)
    base_rows, _ = fpback._season_rows(season)
    merged = []
    for b in base_rows:
        feat = feat_by_pw.get((str(b["player_id"]), int(b["week"])))
        if feat is None:
            continue
        row = dict(feat)
        row["stat_pts"] = b["stat_pts"]
        row["fp_pts"] = b["fp_pts"]
        row["fp_proj_pts"] = b["fp_pts"]
        row["actual_pts"] = b["actual_pts"]
        merged.append(row)
    return merged


def _matrix(rows, cols):
    X = np.zeros((len(rows), len(cols)), dtype=float)
    for i, r in enumerate(rows):
        for j, c in enumerate(cols):
            v = r.get(c, 0)
            try:
                X[i, j] = float(v) if v is not None else 0.0
            except Exception:
                X[i, j] = 0.0
    y = np.array([float(r["actual_pts"]) for r in rows], dtype=float)
    return X, y


def _evaluate(rows, y_pred):
    """MAE / corr / pairwise — same definitions as backtest_fp_projections.py."""
    y_true = np.array([r["actual_pts"] for r in rows], dtype=float)
    y_pred = np.asarray(y_pred, dtype=float)
    if len(rows) == 0:
        return {"mae": None, "corr": None, "pairwise": None, "n": 0}
    mae = float(np.mean(np.abs(y_pred - y_true)))
    pm, am = float(np.mean(y_pred)), float(np.mean(y_true))
    ps, ast = float(np.std(y_pred)), float(np.std(y_true))
    cov = float(np.mean((y_pred - pm) * (y_true - am)))
    corr = float(cov / (ps * ast)) if ps > 0 and ast > 0 else 0.0
    from collections import defaultdict
    by_week = defaultdict(list)
    for r, p, a in zip(rows, y_pred, y_true):
        by_week[(r["season"], r["week"])].append((float(p), float(a)))
    correct = total = 0
    for wr in by_week.values():
        for i in range(len(wr)):
            for j in range(i + 1, len(wr)):
                if wr[i][0] == wr[j][0]:
                    continue
                if (wr[i][0] > wr[j][0]) == (wr[i][1] > wr[j][1]):
                    correct += 1
                total += 1
    pairwise = float(correct / total) if total > 0 else 0.0
    return {"mae": mae, "corr": corr, "pairwise": pairwise, "n": len(rows)}


def _fit_xgb(fit_rows, es_rows, cols):
    from xgboost import XGBRegressor
    X_fit, y_fit = _matrix(fit_rows, cols)
    X_es, y_es = _matrix(es_rows, cols)
    model = XGBRegressor(**PARAMS, early_stopping_rounds=30)
    try:
        model.fit(X_fit, y_fit, eval_set=[(X_es, y_es)], verbose=False)
    except TypeError:
        # older xgboost/sklearn API: early_stopping_rounds as fit kwarg
        model = XGBRegressor(**PARAMS)
        model.fit(X_fit, y_fit, eval_set=[(X_es, y_es)], verbose=False, early_stopping_rounds=30)
    return model


def _passes(m, gate):
    return (m["mae"] is not None and m["mae"] < gate["mae"]
            and m["corr"] > gate["corr"] and m["pairwise"] > gate["pairwise"])


def _paired_t(a, b):
    d = np.array(a) - np.array(b)
    n = len(d)
    if n < 2:
        return None, None
    mean_d, sd_d = float(np.mean(d)), float(np.std(d, ddof=1))
    if sd_d == 0:
        return 0.0, 1.0
    t = mean_d / (sd_d / math.sqrt(n))
    p = 2 * (1 - 0.5 * (1 + math.erf(abs(t) / math.sqrt(2))))
    return float(t), float(p)


def main():
    all_rows = {s: _merged_rows(s) for s in ALL_SEASONS}
    for s in ALL_SEASONS:
        print(f"[fpml:{s}] n={len(all_rows[s])}")

    fit_rows = [r for s in FIT_SEASONS for r in all_rows[s]]
    es_rows = [r for s in EARLYSTOP_SEASON for r in all_rows[s]]
    holdout_rows = [r for s in HOLDOUT_SEASONS for r in all_rows[s]]
    print(f"[fpml] fit n={len(fit_rows)} early-stop n={len(es_rows)} holdout n={len(holdout_rows)}")

    results = {"fp_baseline_holdout": FP_BASELINE, "positions": list(POSITIONS)}

    # Reference columns already computed by the FP-projection backtest.
    stat_hold = _evaluate(holdout_rows, [r["stat_pts"] for r in holdout_rows])
    fp_hold = _evaluate(holdout_rows, [r["fp_pts"] for r in holdout_rows])
    results["reference_holdout"] = {"stat_projector": stat_hold, "fp_alone": fp_hold}
    print(f"[fpml] reference holdout: stat(mae={stat_hold['mae']:.3f}) fp(mae={fp_hold['mae']:.3f})")

    # Arm A: XGBoost(box-score features + fp_proj_pts)
    model_a = _fit_xgb(fit_rows, es_rows, ML_FEATURE_COLS)
    X_hold_a, _ = _matrix(holdout_rows, ML_FEATURE_COLS)
    pred_a = model_a.predict(X_hold_a)
    ml_hold = _evaluate(holdout_rows, pred_a)
    ml_pass = _passes(ml_hold, FP_BASELINE)
    print(f"[fpml] Arm A XGBoost(features+FP) holdout: "
          f"mae={ml_hold['mae']:.3f} corr={ml_hold['corr']:.3f} pw={ml_hold['pairwise']:.3f} "
          f"-> {'PASS' if ml_pass else 'FAIL'} vs FP-alone {FP_BASELINE}")

    importances = model_a.get_booster().get_score(importance_type="gain")
    named_importance = []
    for fid, gain in importances.items():
        idx = int(fid[1:])
        name = ML_FEATURE_COLS[idx] if idx < len(ML_FEATURE_COLS) else fid
        named_importance.append((name, float(gain)))
    named_importance.sort(key=lambda x: x[1], reverse=True)
    print("[fpml] Arm A top-10 feature importance (gain): " +
          ", ".join(f"{n}={g:.1f}" for n, g in named_importance[:10]))

    # Arm B: XGBoost(fp_proj_pts alone) — ablation / sanity check
    model_b = _fit_xgb(fit_rows, es_rows, ["fp_proj_pts"])
    X_hold_b, _ = _matrix(holdout_rows, ["fp_proj_pts"])
    pred_b = model_b.predict(X_hold_b)
    ml_fponly_hold = _evaluate(holdout_rows, pred_b)
    ml_fponly_pass = _passes(ml_fponly_hold, FP_BASELINE)
    print(f"[fpml] Arm B XGBoost(fp_proj_pts only) holdout: "
          f"mae={ml_fponly_hold['mae']:.3f} corr={ml_fponly_hold['corr']:.3f} pw={ml_fponly_hold['pairwise']:.3f} "
          f"-> {'PASS' if ml_fponly_pass else 'FAIL'} vs FP-alone {FP_BASELINE}")

    t_a, p_a = _paired_t([abs(p - r["actual_pts"]) for p, r in zip(pred_a, holdout_rows)],
                          [abs(r["fp_pts"] - r["actual_pts"]) for r in holdout_rows])
    print(f"[fpml] paired-t (Arm A AE vs FP-alone AE) t={t_a:.3f} p={p_a:.4f}")

    results["arm_a_features_plus_fp"] = {
        "holdout": ml_hold, "pass_vs_fp_alone": ml_pass,
        "paired_t_vs_fp_alone": {"t": t_a, "p": p_a},
        "top_feature_importance": named_importance[:15],
        "feature_cols": ML_FEATURE_COLS,
        "params": PARAMS,
    }
    results["arm_b_fp_only_ablation"] = {
        "holdout": ml_fponly_hold, "pass_vs_fp_alone": ml_fponly_pass,
    }
    results["gate"] = {
        "criterion": "must beat FP-alone on holdout on MAE, Corr, AND Pairwise",
        "fp_alone_baseline": FP_BASELINE,
        "arm_a_pass": ml_pass,
        "arm_b_pass": ml_fponly_pass,
    }

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=1)
    print(f"[fpml] wrote {OUT_JSON}")


if __name__ == "__main__":
    main()
