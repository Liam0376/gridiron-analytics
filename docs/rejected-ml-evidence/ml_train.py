"""XGBoost training CLI for fantasy points — time-series clean, conservative.

Usage:
  python -m ffanalytics.ml.train --train data/ml/train_2023_2024.jsonl --val data/ml/val_2025.jsonl --out data/models/xgb_fantasy_v1.json

Conservative params per spec: n_estimators=500, max_depth=5, lr 0.03, subsample 0.8, colsample 0.8, reg_lambda 1.0
Early stopping 30 on val MAE. Handles both sklearn 1.9 XGB APIs (early_stopping_rounds param vs callback).

Gate: if val MAE > 4.163 (baseline), status REJECTED with evidence; still writes booster+meta but not winning.
"""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from collections import defaultdict
import math

# Baseline per spec / stat_projector.py header
BASELINE_MAE = 4.163
BASELINE_CORR = 0.6918
BASELINE_PAIRWISE = 0.777

# Corresponding per-position baselines from spec (for logging, not gate)
BASELINE_POS_MAE = {"QB": 7.08, "RB": 4.43, "WR": 4.42, "TE": 3.63, "K": 0.01}

# Canonical feature list — single-model, one-hot position already in features.
# Excludes short aliases (pass_yd_proj etc) to avoid duplicate collinearity.
FEATURE_COLS = [
    "games_played",
    "implied_total",
    "spread",
    "wind",
    "temp",
    "is_dome",
    "target_share_wavg",
    "rush_share_wavg",
    "air_yards_wavg",
    "air_yards_share_wavg",
    "redzone_targets_wavg",
    "redzone_carries_wavg",
    "snap_share_wavg",
    "route_share_wavg",
    "recent_trend",
    "trend_slope",
    "recent_trend_slope",
    "passing_yards_proj",
    "passing_tds_proj",
    "passing_interceptions_proj",
    "rushing_yards_proj",
    "rushing_tds_proj",
    "receiving_yards_proj",
    "receiving_tds_proj",
    "receptions_proj",
    "fumbles_lost_total_proj",
    "fg_made_0_19_proj",
    "fg_made_20_29_proj",
    "fg_made_30_39_proj",
    "fg_made_40_49_proj",
    "fg_made_50_59_proj",
    "fg_missed_proj",
    "pat_made_proj",
    "position_QB",
    "position_RB",
    "position_WR",
    "position_TE",
    "position_K",
]

PARAMS = {
    "n_estimators": 500,
    "max_depth": 5,
    "learning_rate": 0.03,
    "subsample": 0.8,
    "colsample_bytree": 0.8,
    "reg_lambda": 1.0,
    "objective": "reg:squarederror",
    "random_state": 42,
    # n_jobs left default (spec says use default)
}


def _load_jsonl(path: Path):
    rows = []
    with open(path, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except Exception as e:
                print(f"WARNING: skipping bad json line in {path}: {e}", file=sys.stderr)
    return rows


def _get_git_sha():
    try:
        out = subprocess.check_output(["git", "rev-parse", "HEAD"], stderr=subprocess.DEVNULL, text=True)
        return out.strip()
    except Exception:
        return "unknown"


def _to_matrix(rows, feature_cols):
    import numpy as np
    n = len(rows)
    m = len(feature_cols)
    X = np.zeros((n, m), dtype=float)
    y = np.zeros(n, dtype=float)
    for i, r in enumerate(rows):
        for j, col in enumerate(feature_cols):
            v = r.get(col, 0)
            if v is None:
                v = 0
            try:
                X[i, j] = float(v)
            except Exception:
                X[i, j] = 0.0
        # target is actual fantasy points via scoring (consistent with features.py)
        targ = r.get("target", r.get("actual_points", 0))
        if targ is None:
            targ = 0
        try:
            y[i] = float(targ)
        except Exception:
            y[i] = 0.0
    return X, y


def _evaluate_metrics(y_true, y_pred, rows):
    import numpy as np
    n = len(y_true)
    if n == 0:
        return {"mae": float("nan"), "corr": 0.0, "pairwise": 0.0, "bias": 0.0, "n": 0, "pos_mae": {}}
    mae = float(np.mean(np.abs(np.array(y_pred) - np.array(y_true))))
    bias = float(np.mean(np.array(y_pred) - np.array(y_true)))
    # corr
    y_true_arr = np.array(y_true, dtype=float)
    y_pred_arr = np.array(y_pred, dtype=float)
    pm = float(np.mean(y_pred_arr))
    am = float(np.mean(y_true_arr))
    cov = float(np.mean((y_pred_arr - pm) * (y_true_arr - am)))
    ps = float(np.std(y_pred_arr))
    ast = float(np.std(y_true_arr))
    corr = float(cov / (ps * ast)) if ps > 0 and ast > 0 else 0.0
    # pairwise within same (season, week)
    by_week = defaultdict(list)
    for r, p, a in zip(rows, y_pred_arr, y_true_arr):
        season = r.get("season", 0)
        week = r.get("week", 0)
        by_week[(season, week)].append((float(p), float(a)))
    correct = 0
    total = 0
    for wr in by_week.values():
        for i in range(len(wr)):
            for j in range(i + 1, len(wr)):
                if wr[i][0] == wr[j][0]:
                    continue
                if (wr[i][0] > wr[j][0]) == (wr[i][1] > wr[j][1]):
                    correct += 1
                total += 1
    pairwise = float(correct / total) if total > 0 else 0.0
    # per-position MAE
    pos_errors = defaultdict(list)
    for r, p, a in zip(rows, y_pred_arr, y_true_arr):
        pos = r.get("position", "UNK")
        pos_errors[pos].append(abs(float(p) - float(a)))
    pos_mae = {p: float(sum(e) / len(e)) if e else 0.0 for p, e in pos_errors.items()}
    return {"mae": mae, "corr": corr, "pairwise": pairwise, "bias": bias, "n": n, "pos_mae": pos_mae}


def train_model(train_path: Path, val_path: Path, out_path: Path):
    # gracefully handle missing xgboost
    try:
        import xgboost  # noqa: F401
        from xgboost import XGBRegressor
        import sklearn  # noqa: F401
        from sklearn.model_selection import TimeSeriesSplit
        from sklearn.metrics import mean_absolute_error
    except ImportError as e:
        print(f"[train] xgboost/sklearn not available: {e} — ML disabled, fallback to stat model. No booster written.", file=sys.stderr)
        # still need to write meta with REJECTED due to missing dep? per spec, log and exit
        # write a minimal meta if out_path parent exists
        meta_path = out_path.parent / "xgb_meta.json"
        meta = {
            "features": FEATURE_COLS,
            "train_seasons": [2023, 2024],
            "val_season": 2025,
            "val_mae": None,
            "val_corr": None,
            "pairwise": None,
            "params": PARAMS,
            "w": None,
            "git_sha": _get_git_sha(),
            "status": "REJECTED",
            "reason": f"missing_dependency: {e}",
            "baseline_mae": BASELINE_MAE,
            "baseline_corr": BASELINE_CORR,
            "baseline_pairwise": BASELINE_PAIRWISE,
        }
        try:
            meta_path.parent.mkdir(parents=True, exist_ok=True)
            with open(meta_path, "w") as f:
                json.dump(meta, f, indent=2)
            print(f"[train] wrote {meta_path} with REJECTED due to missing dep")
        except Exception as me:
            print(f"[train] failed to write meta: {me}", file=sys.stderr)
        sys.exit(0)

    # load data
    if not train_path.exists():
        print(f"[train] train file not found: {train_path}", file=sys.stderr)
        sys.exit(1)
    if not val_path.exists():
        print(f"[train] val file not found: {val_path}", file=sys.stderr)
        sys.exit(1)

    train_rows = _load_jsonl(train_path)
    val_rows = _load_jsonl(val_path)
    print(f"[train] loaded train {len(train_rows)} rows from {train_path}")
    print(f"[train] loaded val {len(val_rows)} rows from {val_path}")

    if not train_rows or not val_rows:
        print("[train] empty train or val", file=sys.stderr)
        sys.exit(1)

    # time-series clean check: max train season*100+week < min val
    try:
        max_train = max(r["season"] * 100 + r["week"] for r in train_rows)
        min_val = min(r["season"] * 100 + r["week"] for r in val_rows)
        print(f"[train] time-series check: max_train {max_train} < min_val {min_val} ? {max_train < min_val}")
        if max_train >= min_val:
            print("[train] WARNING: leakage detected — train max >= val min", file=sys.stderr)
    except Exception as e:
        print(f"[train] time-series check failed: {e}", file=sys.stderr)

    # Build matrices
    import numpy as np
    # ensure feature cols exist; if missing, fallback to intersection but keep canonical order
    # For rows where PBP all-zero (no cache), those cols will be 0 but still included
    feature_cols = FEATURE_COLS
    # Verify at least some rows have these keys; if key missing entirely, still keep but will be 0
    X_train, y_train = _to_matrix(train_rows, feature_cols)
    X_val, y_val = _to_matrix(val_rows, feature_cols)
    print(f"[train] feature cols {len(feature_cols)}: {feature_cols}")
    print(f"[train] X_train {X_train.shape} X_val {X_val.shape} y_train mean {np.mean(y_train):.2f} y_val mean {np.mean(y_val):.2f}")

    # Optional TimeSeriesSplit CV on train (3 splits) — log but not gate
    try:
        from sklearn.model_selection import TimeSeriesSplit
        tscv = TimeSeriesSplit(n_splits=3)
        cv_maes = []
        for fold, (tr_idx, va_idx) in enumerate(tscv.split(X_train)):
            X_tr, X_va = X_train[tr_idx], X_train[va_idx]
            y_tr, y_va = y_train[tr_idx], y_train[va_idx]
            # use same params but smaller n_estimators for speed? keep same but early stopping not needed for CV fold
            # For CV, we do not use val set; just fit without early stopping to estimate generalization
            fold_model = XGBRegressor(
                n_estimators=200,
                max_depth=PARAMS["max_depth"],
                learning_rate=PARAMS["learning_rate"],
                subsample=PARAMS["subsample"],
                colsample_bytree=PARAMS["colsample_bytree"],
                reg_lambda=PARAMS["reg_lambda"],
                objective=PARAMS["objective"],
                random_state=PARAMS["random_state"],
            )
            fold_model.fit(X_tr, y_tr, verbose=False)
            pred_va = fold_model.predict(X_va)
            mae = float(np.mean(np.abs(pred_va - y_va)))
            cv_maes.append(mae)
            print(f"[train] CV fold {fold} n_train {len(tr_idx)} n_val {len(va_idx)} MAE {mae:.4f}")
        if cv_maes:
            print(f"[train] CV mean MAE {np.mean(cv_maes):.4f} +- {np.std(cv_maes):.4f}")
    except Exception as e:
        print(f"[train] TimeSeriesSplit CV failed: {e}", file=sys.stderr)

    # Train primary model with early stopping on val MAE
    from xgboost import XGBRegressor

    fitted = False
    best_iteration = None
    model = None
    # Try API 0: early_stopping_rounds via constructor (xgboost 3.x with sklearn 1.9)
    try:
        model = XGBRegressor(
            n_estimators=PARAMS["n_estimators"],
            max_depth=PARAMS["max_depth"],
            learning_rate=PARAMS["learning_rate"],
            subsample=PARAMS["subsample"],
            colsample_bytree=PARAMS["colsample_bytree"],
            reg_lambda=PARAMS["reg_lambda"],
            objective=PARAMS["objective"],
            random_state=PARAMS["random_state"],
            early_stopping_rounds=30,
        )
        model.fit(X_train, y_train, eval_set=[(X_val, y_val)], verbose=False)
        fitted = True
        try:
            best_iteration = getattr(model, "best_iteration", None)
        except Exception:
            best_iteration = None
        print(f"[train] fit with constructor early_stopping_rounds=30 succeeded, best_iteration={best_iteration}")
    except TypeError as e:
        print(f"[train] constructor early_stopping_rounds not supported ({e}), trying fit param", file=sys.stderr)
        model = None
    except Exception as e:
        print(f"[train] constructor fit failed: {e}", file=sys.stderr)
        model = None

    if not fitted:
        # Try API 1: early_stopping_rounds as fit param (xgboost 2.x)
        try:
            model = XGBRegressor(
                n_estimators=PARAMS["n_estimators"],
                max_depth=PARAMS["max_depth"],
                learning_rate=PARAMS["learning_rate"],
                subsample=PARAMS["subsample"],
                colsample_bytree=PARAMS["colsample_bytree"],
                reg_lambda=PARAMS["reg_lambda"],
                objective=PARAMS["objective"],
                random_state=PARAMS["random_state"],
            )
            model.fit(X_train, y_train, eval_set=[(X_val, y_val)], verbose=False, early_stopping_rounds=30)
            fitted = True
            try:
                best_iteration = getattr(model, "best_iteration", None)
            except Exception:
                best_iteration = None
            print(f"[train] fit with early_stopping_rounds=30 (fit param) succeeded, best_iteration={best_iteration}")
        except TypeError as e:
            print(f"[train] early_stopping_rounds fit param not supported ({e}), trying callback API", file=sys.stderr)
        except Exception as e:
            print(f"[train] fit with early_stopping_rounds failed: {e}", file=sys.stderr)

    if not fitted:
        # Try callback API (xgboost >=2.0 callback)
        try:
            from xgboost.callback import EarlyStopping
            # Recreate model to ensure clean state
            model = XGBRegressor(
                n_estimators=PARAMS["n_estimators"],
                max_depth=PARAMS["max_depth"],
                learning_rate=PARAMS["learning_rate"],
                subsample=PARAMS["subsample"],
                colsample_bytree=PARAMS["colsample_bytree"],
                reg_lambda=PARAMS["reg_lambda"],
                objective=PARAMS["objective"],
                random_state=PARAMS["random_state"],
            )
            model.fit(
                X_train,
                y_train,
                eval_set=[(X_val, y_val)],
                verbose=False,
                callbacks=[EarlyStopping(rounds=30, save_best=True)],
            )
            fitted = True
            best_iteration = getattr(model, "best_iteration", None)
            print(f"[train] fit with callback EarlyStopping succeeded, best_iteration={best_iteration}")
        except Exception as e:
            print(f"[train] callback fit failed: {e}, falling back to no early stopping", file=sys.stderr)
            # final fallback: no early stopping
            model = XGBRegressor(
                n_estimators=PARAMS["n_estimators"],
                max_depth=PARAMS["max_depth"],
                learning_rate=PARAMS["learning_rate"],
                subsample=PARAMS["subsample"],
                colsample_bytree=PARAMS["colsample_bytree"],
                reg_lambda=PARAMS["reg_lambda"],
                objective=PARAMS["objective"],
                random_state=PARAMS["random_state"],
            )
            model.fit(X_train, y_train, verbose=False)
            fitted = True
            print("[train] fit without early stopping succeeded")

    # Predict and evaluate
    import numpy as np
    y_pred_val = model.predict(X_val)
    metrics = _evaluate_metrics(y_val, y_pred_val, val_rows)
    print(f"[train] val MAE {metrics['mae']:.4f} corr {metrics['corr']:.4f} pairwise {metrics['pairwise']:.4%} bias {metrics['bias']:.4f} n {metrics['n']}")
    for pos in sorted(metrics["pos_mae"]):
        baseline = BASELINE_POS_MAE.get(pos, None)
        if baseline is not None:
            print(f"[train]   pos {pos} MAE {metrics['pos_mae'][pos]:.4f} vs baseline {baseline:.2f} diff {metrics['pos_mae'][pos]-baseline:+.3f}")
        else:
            print(f"[train]   pos {pos} MAE {metrics['pos_mae'][pos]:.4f}")

    # Feature importance (gain)
    try:
        booster = model.get_booster()
        importance = booster.get_score(importance_type="gain")
        # map f0 -> feature name
        sorted_imp = sorted(importance.items(), key=lambda x: x[1], reverse=True)
        print("[train] top 10 feature importance (gain):")
        for fid, gain in sorted_imp[:10]:
            # fid like f0, f12 etc
            try:
                idx = int(fid[1:])
                fname = feature_cols[idx] if idx < len(feature_cols) else fid
            except Exception:
                fname = fid
            print(f"  {fname} ({fid}): {gain:.2f}")
        # also log if any PBP features have zero gain (expected when no cache)
        pbp_features = [c for c in feature_cols if "share_wavg" in c or "air_yards" in c or "redzone" in c or "snap_share" in c]
        for pf in pbp_features:
            if pf not in [feature_cols[int(k[1:])] if k.startswith("f") and k[1:].isdigit() and int(k[1:]) < len(feature_cols) else k for k,_ in sorted_imp]:
                # check if not in top at all
                pass
    except Exception as e:
        print(f"[train] feature importance failed: {e}", file=sys.stderr)

    # Determine status vs baseline
    val_mae = metrics["mae"]
    val_corr = metrics["corr"]
    val_pairwise = metrics["pairwise"]
    if val_mae > BASELINE_MAE:
        status = "REJECTED"
        reason = f"val MAE {val_mae:.4f} > baseline {BASELINE_MAE} — XGB does not beat stat model; ensemble not winning per spec Task 5."
        print(f"[train] {status}: {reason}", file=sys.stderr)
    else:
        # Need also check corr and pairwise? Spec Task 5 only mentions MAE gate, but spec Gate 1 says ensemble must beat all three.
        # For XGB alone, we gate on MAE first; if MAE passes but corr/pairwise fail, still note.
        if val_corr < BASELINE_CORR or val_pairwise < BASELINE_PAIRWISE:
            # still accept for now but log warning; final gate is ensemble
            status = "ACCEPTED_WARNING"
            reason = f"val MAE {val_mae:.4f} beats baseline {BASELINE_MAE} but corr {val_corr:.4f} vs {BASELINE_CORR} or pairwise {val_pairwise:.4%} vs {BASELINE_PAIRWISE:.1%} not beating all three"
            print(f"[train] {status}: {reason}", file=sys.stderr)
        else:
            status = "ACCEPTED"
            reason = f"val MAE {val_mae:.4f} <= {BASELINE_MAE} and corr {val_corr:.4f} >= {BASELINE_CORR} and pairwise {val_pairwise:.4%} >= {BASELINE_PAIRWISE:.1%}"
            print(f"[train] {status}: {reason}")

    # Write booster
    out_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        # save as json
        model.get_booster().save_model(str(out_path))
        print(f"[train] wrote booster to {out_path} (best_iteration={best_iteration})")
    except Exception as e:
        print(f"[train] failed to save booster: {e}", file=sys.stderr)
        # fallback try model.save_model
        try:
            model.save_model(str(out_path))
            print(f"[train] wrote model via save_model to {out_path}")
        except Exception as e2:
            print(f"[train] second save failed: {e2}", file=sys.stderr)
            sys.exit(1)

    # Write meta
    meta_path = out_path.parent / "xgb_meta.json"
    meta = {
        "features": feature_cols,
        "train_seasons": [2023, 2024],
        "val_season": 2025,
        "train_rows": len(train_rows),
        "val_rows": len(val_rows),
        "val_mae": val_mae,
        "val_corr": val_corr,
        "pairwise": val_pairwise,
        "bias": metrics["bias"],
        "pos_mae": metrics["pos_mae"],
        "baseline_mae": BASELINE_MAE,
        "baseline_corr": BASELINE_CORR,
        "baseline_pairwise": BASELINE_PAIRWISE,
        "baseline_pos_mae": BASELINE_POS_MAE,
        "params": PARAMS,
        "best_iteration": int(best_iteration) if best_iteration is not None else None,
        "w": None,  # TBD by backtest grid
        "git_sha": _get_git_sha(),
        "status": status,
        "reason": reason,
    }
    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=2)
    print(f"[train] wrote meta to {meta_path} with status {status}")

    # If REJECTED, still exit 0 but caller can check meta; spec says stop before ensemble
    # We do not error out; backtest will still run but will show REJECTED
    return status, metrics, meta


def main():
    parser = argparse.ArgumentParser(description="Train XGB fantasy points model")
    parser.add_argument("--train", required=True, help="path to train jsonl (2023-2024)")
    parser.add_argument("--val", required=True, help="path to val jsonl (2025)")
    parser.add_argument("--out", required=True, help="output booster json path")
    args = parser.parse_args()
    train_path = Path(args.train)
    val_path = Path(args.val)
    out_path = Path(args.out)
    train_model(train_path, val_path, out_path)


if __name__ == "__main__":
    main()
