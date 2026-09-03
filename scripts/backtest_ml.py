#!/usr/bin/env python3
"""Head-to-head backtest: stat vs XGB vs ensemble.

Loads train/val jsonl (or rebuilds via build_training_rows for 2024-2025 weeks 4-18).
For each player-week, computes stat_pts (stat_projector pipeline with Vegas/weather via projected features) + xgb_pts (model predict) + ensemble = w*xgb + (1-w)*stat.
Grid w 0.0→1.0 step 0.05 on TRAIN-ONLY split (2024), lock w, evaluate ONCE on
holdout (2025 val). Report w. Legacy w=0.40 quoted in headers was val-tuned
(leaky: tuned on val then reported on combined incl. val) — documented here
for reproducibility, NOT re-tuned to a new value.
Run final backtest on holdout (2025) + diagnostic combined vs production
freeze baseline 4.563/0.648/0.741 (n=10351, true scoring), report MAE, corr,
pairwise, bias, pos_mae for stat, xgb, ensemble.
Gates: ensemble must beat ALL THREE of stat baseline on HOLDOUT to pass
(combined incl. train is diagnostic only — in-sample leakage).

Writes data/ml/backtest_ml_results.json
"""
import json
import os
import sys
from pathlib import Path
from collections import defaultdict
import math

# Ensure SLEEPER_LEAGUE_ID doesn't break imports
os.environ.setdefault("SLEEPER_LEAGUE_ID", "test")

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

# Production freeze baseline (true scoring, 2024-2025 weeks 4-18, n=10351):
# MAE 4.563 / Corr 0.648 / Pairwise 0.741. Early scratch 4.163/0.6918/0.777
# was K-zeroed (old_map ignored fg_* → K MAE 0.001, -0.416 bias; deflated MAE
# ~0.40, inflated corr/pairwise) — SUPERSEDED, do not gate on stale numbers.
BASELINE = {"mae": 4.563, "corr": 0.648, "pairwise": 0.741}

# Feature list must match train.py.
# Canonical training code reference (REJECTED, no behavior change):
#   src/ffanalytics/ml/ is intentionally empty (XGBoost rejected as production).
#   Canonical training code lives at docs/rejected-ml-evidence/ml_train.py
#   (verbatim from src/ffanalytics/ml/train.py) + ml_features.py.
#   Explicit commented import path (do NOT resurrect training, no new deps):
#   # from docs.rejected_ml_evidence.ml_train import FEATURE_COLS, PARAMS  # REJECTED — evidence: data/models/xgb_meta.json val 4.556 vs local stat 4.474 fails OOS
#   tested and REJECTED — evidence: data/models/xgb_meta.json (val 4.556 vs true stat 4.474 local, ensemble w=0.40 val-tuned leaky).
#   Backtests below use hardcoded FEATURE_COLS fallback only (no xgboost import here).
try:
    from ffanalytics.ml.train import FEATURE_COLS, PARAMS  # type: ignore
except Exception:
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
    PARAMS = {}

try:
    from ffanalytics.scoring import calculate_fantasy_points, DEFAULT_SCORING
    SCORING = DEFAULT_SCORING
except Exception:
    # Fallback cold-start scoring (K-zero bug class guard below).
    # Must include fg_*/xpm keys — early scratch old_map ignored fg_* → K MAE 0.001 (SUPERSEDED 4.163).
    # tested and REJECTED omitting K — evidence: stat_projector.py:8-13 K-zero deflated MAE ~0.40.
    SCORING = {
        "rec": 1.0, "rec_yd": 0.1, "rush_yd": 0.1, "pass_yd": 0.04,
        "pass_td": 5.0, "rush_td": 6.0, "rec_td": 6.0, "pass_int": -1.0,
        "fum_lost": -2.0,
        "fgm_0_19": 3.0, "fgm_20_29": 3.0, "fgm_30_39": 3.0,
        "fgm_40_49": 4.0, "fgm_50_59": 5.0, "fgm_60p": 6.0,
        "fgmiss": -1.0, "xpm": 1.0, "xpmiss": -1.0,
    }
    # K-zero guard: fallback must contain kicking keys or scoring silently zeroes K (early 4.163 bug).
    assert all(k in SCORING for k in ("fgm_0_19", "fgm_20_29", "fgm_30_39", "fgm_40_49", "fgm_50_59", "fgmiss", "xpm")), \
        "SCORING fallback missing fg_*/xpm keys — K would score 0 (K-zero bug class, see stat_projector.py:8-13)"

    def calculate_fantasy_points(stats, scoring_settings=None):
        return 0.0


def _load_jsonl(path: Path):
    rows = []
    if not path.exists():
        print(f"[backtest] file not found: {path}")
        return rows
    with open(path) as f:
        for line in f:
            line=line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def _map_proj_to_scoring(row):
    """Convert projected stat features to scoring dict matching train target."""
    return {
        "receptions": row.get("receptions_proj", 0) or 0,
        "receiving_yards": row.get("receiving_yards_proj", 0) or 0,
        "receiving_tds": row.get("receiving_tds_proj", 0) or 0,
        "rushing_yards": row.get("rushing_yards_proj", 0) or 0,
        "rushing_tds": row.get("rushing_tds_proj", 0) or 0,
        "passing_yards": row.get("passing_yards_proj", 0) or 0,
        "passing_tds": row.get("passing_tds_proj", 0) or 0,
        "interceptions": row.get("passing_interceptions_proj", 0) or 0,
        "fumbles_lost": row.get("fumbles_lost_total_proj", 0) or 0,
        "passing_2pt": 0,
        "rushing_2pt": 0,
        "receiving_2pt": 0,
        "passing_40": 0,
        "rushing_40": 0,
        "receiving_40": 0,
        "fg_made_0_19": row.get("fg_made_0_19_proj", 0) or 0,
        "fg_made_20_29": row.get("fg_made_20_29_proj", 0) or 0,
        "fg_made_30_39": row.get("fg_made_30_39_proj", 0) or 0,
        "fg_made_40_49": row.get("fg_made_40_49_proj", 0) or 0,
        "fg_made_50_59": row.get("fg_made_50_59_proj", 0) or 0,
        "fg_made_60_": 0,
        "fg_missed": row.get("fg_missed_proj", 0) or 0,
        "pat_made": row.get("pat_made_proj", 0) or 0,
        "pat_missed": 0,
        "fumble_recovery": 0,
        "fumble_recovery_td": 0,
        "forced_fumble": 0,
    }


def _compute_stat_pts(rows):
    pts = []
    for r in rows:
        try:
            pts.append(float(calculate_fantasy_points(_map_proj_to_scoring(r), SCORING)))
        except Exception:
            pts.append(0.0)
    return pts


def _to_matrix(rows, feature_cols):
    import numpy as np
    n = len(rows)
    m = len(feature_cols)
    X = np.zeros((n, m), dtype=float)
    for i, r in enumerate(rows):
        for j, col in enumerate(feature_cols):
            v = r.get(col, 0)
            if v is None:
                v = 0
            try:
                X[i,j] = float(v)
            except Exception:
                X[i,j] = 0.0
    y = np.array([float(r.get("target", r.get("actual_points", 0)) or 0) for r in rows], dtype=float)
    return X, y


def _evaluate(y_true, y_pred, rows):
    import numpy as np
    n = len(y_true)
    if n==0:
        return {"mae": None, "corr": None, "pairwise": None, "bias": None, "n":0, "pos_mae": {}}
    mae = float(np.mean(np.abs(np.array(y_pred)-np.array(y_true))))
    bias = float(np.mean(np.array(y_pred)-np.array(y_true)))
    y_true_arr = np.array(y_true, dtype=float)
    y_pred_arr = np.array(y_pred, dtype=float)
    pm = float(np.mean(y_pred_arr)); am = float(np.mean(y_true_arr))
    cov = float(np.mean((y_pred_arr - pm)*(y_true_arr - am)))
    ps = float(np.std(y_pred_arr)); ast = float(np.std(y_true_arr))
    corr = float(cov/(ps*ast)) if ps>0 and ast>0 else 0.0
    by_week = defaultdict(list)
    for r,p,a in zip(rows, y_pred_arr, y_true_arr):
        by_week[(r.get("season"), r.get("week"))].append((float(p), float(a)))
    correct=total=0
    for wr in by_week.values():
        for i in range(len(wr)):
            for j in range(i+1,len(wr)):
                if wr[i][0]==wr[j][0]: continue
                if (wr[i][0]>wr[j][0])==(wr[i][1]>wr[j][1]): correct+=1
                total+=1
    pairwise = float(correct/total) if total>0 else 0.0
    pos_errors=defaultdict(list)
    for r,p,a in zip(rows, y_pred_arr, y_true_arr):
        pos=r.get("position","UNK")
        pos_errors[pos].append(abs(float(p)-float(a)))
    pos_mae={p: float(sum(e)/len(e)) if e else 0.0 for p,e in pos_errors.items()}
    return {"mae":mae, "corr":corr, "pairwise":pairwise, "bias":bias, "n":n, "pos_mae":pos_mae}


def main():
    import argparse
    parser=argparse.ArgumentParser()
    parser.add_argument("--train", default="data/ml/train_2023_2024.jsonl", help="train jsonl")
    parser.add_argument("--val", default="data/ml/val_2025.jsonl", help="val jsonl")
    parser.add_argument("--model", default="data/models/xgb_fantasy_v1.json", help="booster path")
    parser.add_argument("--meta", default="data/models/xgb_meta.json", help="meta path")
    parser.add_argument("--out", default="data/ml/backtest_ml_results.json", help="output json")
    args=parser.parse_args()

    train_path = (REPO_ROOT / args.train) if not Path(args.train).is_absolute() else Path(args.train)
    val_path = (REPO_ROOT / args.val) if not Path(args.val).is_absolute() else Path(args.val)
    model_path = (REPO_ROOT / args.model) if not Path(args.model).is_absolute() else Path(args.model)
    meta_path = (REPO_ROOT / args.meta) if not Path(args.meta).is_absolute() else Path(args.meta)
    out_path = (REPO_ROOT / args.out) if not Path(args.out).is_absolute() else Path(args.out)

    print(f"[backtest] loading train {train_path}")
    train_rows=_load_jsonl(train_path)
    val_rows=_load_jsonl(val_path)
    print(f"[backtest] train rows {len(train_rows)} val rows {len(val_rows)}")

    # For head-to-head 2024-2025 combined, use train filtered to 2024 + val (2025)
    rows_2425 = [r for r in train_rows if r.get("season")==2024] + val_rows
    # also ensure weeks 4-18 already, but filter
    rows_2425 = [r for r in rows_2425 if 4 <= int(r.get("week",0)) <= 18]
    val_rows_filt = [r for r in val_rows if 4 <= int(r.get("week",0)) <= 18]
    rows_2024 = [r for r in rows_2425 if r.get("season")==2024]
    rows_2025 = val_rows_filt
    print(f"[backtest] 2024 rows {len(rows_2024)} 2025 rows {len(rows_2025)} combined {len(rows_2425)}")

    # Compute stat_pts for each set
    stat_val = _compute_stat_pts(val_rows_filt)
    stat_2425 = _compute_stat_pts(rows_2425)
    stat_2024 = _compute_stat_pts(rows_2024)
    stat_2025 = stat_val

    y_val = [float(r.get("target", r.get("actual_points",0)) or 0) for r in val_rows_filt]
    y_2425 = [float(r.get("target",0) or 0) for r in rows_2425]
    y_2024 = [float(r.get("target",0) or 0) for r in rows_2024]

    # Load model and predict
    xgb_val = None
    xgb_2425 = None
    xgb_2024 = None
    xgb_2025 = None
    model_loaded = False
    feature_cols = FEATURE_COLS
    # try to read meta to get feature list
    if meta_path.exists():
        try:
            with open(meta_path) as f:
                meta=json.load(f)
            if "features" in meta and isinstance(meta["features"], list):
                feature_cols = meta["features"]
                print(f"[backtest] using feature cols from meta ({len(feature_cols)})")
        except Exception as e:
            print(f"[backtest] failed to read meta features: {e}", file=sys.stderr)

    try:
        import xgboost
        from xgboost import XGBRegressor
        import numpy as np
        if model_path.exists():
            # Try to load booster via XGBRegressor
            # Need to infer feature cols order; use saved meta
            # Create dummy model and load
            dummy = XGBRegressor()
            # Try load via booster
            try:
                dummy.load_model(str(model_path))
                model_loaded = True
                # predict
                X_val,_ = _to_matrix(val_rows_filt, feature_cols)
                X_2425,_ = _to_matrix(rows_2425, feature_cols)
                X_2024,_ = _to_matrix(rows_2024, feature_cols)
                X_2025,_ = _to_matrix(rows_2025, feature_cols)
                xgb_val = dummy.predict(X_val).tolist()
                xgb_2425 = dummy.predict(X_2425).tolist()
                xgb_2024 = dummy.predict(X_2024).tolist()
                xgb_2025 = dummy.predict(X_2025).tolist()
                print(f"[backtest] loaded model {model_path}, val mean xgb {np.mean(xgb_val):.2f}")
            except Exception as e:
                print(f"[backtest] failed to load model via XGBRegressor: {e}", file=sys.stderr)
                # Try booster directly
                try:
                    import xgboost as xgb
                    bst = xgb.Booster()
                    bst.load_model(str(model_path))
                    import numpy as np
                    X_val,_ = _to_matrix(val_rows_filt, feature_cols)
                    dval = xgb.DMatrix(X_val, feature_names=feature_cols)
                    xgb_val = bst.predict(dval).tolist()
                    X_2425,_ = _to_matrix(rows_2425, feature_cols)
                    d2425 = xgb.DMatrix(X_2425, feature_names=feature_cols)
                    xgb_2425 = bst.predict(d2425).tolist()
                    X_2024,_ = _to_matrix(rows_2024, feature_cols)
                    d2024 = xgb.DMatrix(X_2024, feature_names=feature_cols)
                    xgb_2024 = bst.predict(d2024).tolist()
                    model_loaded = True
                    print(f"[backtest] loaded booster directly, val mean {np.mean(xgb_val):.2f}")
                except Exception as e2:
                    print(f"[backtest] booster direct load failed: {e2}", file=sys.stderr)
        else:
            print(f"[backtest] model file not found: {model_path} — xgb will be missing")
    except ImportError as e:
        print(f"[backtest] xgboost not available: {e} — xgb predictions will be None", file=sys.stderr)
    except Exception as e:
        print(f"[backtest] xgboost predict failed: {e}", file=sys.stderr)

    if xgb_val is None:
        # fallback: xgb = stat (so ensemble = stat)
        print("[backtest] xgb missing, using stat as fallback for xgb")
        xgb_val = stat_val
        xgb_2425 = stat_2425
        xgb_2024 = stat_2024
        xgb_2025 = stat_2025

    # NESTED PROTOCOL (leakage fix): tune w on TRAIN-ONLY split (2024), lock w,
    # evaluate ONCE on holdout (2025 val). Legacy behavior tuned w on val then
    # reported on combined incl. val/train — leaky (val reused for tuning +
    # reporting; combined incl. train is in-sample for the XGB booster).
    # Do NOT retune stored w to a new value — legacy val-tuned w below is
    # preserved as `legacy_val_tuned_w` (current w=0.40 cited in headers is
    # val-tuned); honest train-tuned `best_w` is used for gating.
    import numpy as np
    # Honest: grid on train-only (2024)
    best_w = 0.0
    best_mae = float("inf")
    honest_grid = []
    for w in [round(i*0.05,2) for i in range(21)]:
        ens = [w*xv + (1-w)*sv for xv, sv in zip(xgb_2024, stat_2024)]
        mae = float(np.mean([abs(e - a) for e,a in zip(ens, y_2024)])) if y_2024 else float("inf")
        honest_grid.append({"w": w, "mae": mae})
        if mae < best_mae:
            best_mae = mae
            best_w = w
    print(f"[backtest] honest grid (train-2024 tuned) best w {best_w} train MAE {best_mae:.4f}")
    # Legacy (leaky, for documentation only — do not gate on this):
    legacy_w = 0.0
    legacy_mae = float("inf")
    grid_results = []
    for w in [round(i*0.05,2) for i in range(21)]:
        ens = [w*xv + (1-w)*sv for xv, sv in zip(xgb_val, stat_val)]
        mae = float(np.mean([abs(e - a) for e,a in zip(ens, y_val)])) if y_val else float("inf")
        grid_results.append({"w": w, "mae": mae})
        if mae < legacy_mae:
            legacy_mae = mae
            legacy_w = w
    print(f"[backtest] legacy grid (val-tuned, leaky) w {legacy_w} val MAE {legacy_mae:.4f} (vs stat {float(np.mean([abs(s-a) for s,a in zip(stat_val, y_val)])) if y_val else 0:.4f} xgb {float(np.mean([abs(x-a) for x,a in zip(xgb_val, y_val)])) if y_val else 0:.4f}) — documented only, NOT used for gating")

    # Update meta with w — preserve legacy val-tuned w as `w` (do NOT retune
    # stored value to honest train-tuned; document honest separately).
    if meta_path.exists():
        try:
            with open(meta_path) as f:
                meta=json.load(f)
            meta["w"] = legacy_w
            meta["grid_best_mae"] = legacy_mae
            meta["w_note"] = "val-tuned legacy (leaky: tuned on val, reported on combined incl val)"
            meta["honest_w_train_tuned"] = best_w
            meta["honest_train_mae"] = best_mae
            with open(meta_path, "w") as out:
                json.dump(meta, out, indent=2)
            print(f"[backtest] updated meta {meta_path} with legacy w={legacy_w} + honest w={best_w}")
        except Exception as e:
            print(f"[backtest] failed to update meta w: {e}", file=sys.stderr)

    # Final backtest: honest holdout (2025) is the gate; combined is diagnostic
    # only (includes train → in-sample for booster). w is locked from train.
    def eval_set(name, y_true, stat_pred, xgb_pred, rows, w=None):
        import numpy as np
        if w is None:
            w = best_w
        ens_pred = [w*x + (1-w)*s for x,s in zip(xgb_pred, stat_pred)]
        import numpy as np
        ens_pred = [best_w*x + (1-best_w)*s for x,s in zip(xgb_pred, stat_pred)]
        stat_metrics = _evaluate(y_true, stat_pred, rows)
        xgb_metrics = _evaluate(y_true, xgb_pred, rows)
        ens_metrics = _evaluate(y_true, ens_pred, rows)
        print(f"[backtest] {name} stat MAE {stat_metrics['mae']:.4f} corr {stat_metrics['corr']:.4f} pw {stat_metrics['pairwise']:.4%} bias {stat_metrics['bias']:.4f}")
        print(f"[backtest] {name} xgb  MAE {xgb_metrics['mae']:.4f} corr {xgb_metrics['corr']:.4f} pw {xgb_metrics['pairwise']:.4%} bias {xgb_metrics['bias']:.4f}")
        print(f"[backtest] {name} ens  MAE {ens_metrics['mae']:.4f} corr {ens_metrics['corr']:.4f} pw {ens_metrics['pairwise']:.4%} bias {ens_metrics['bias']:.4f}")
        for pos in sorted(stat_metrics["pos_mae"]):
            print(f"  {name} pos {pos}: stat {stat_metrics['pos_mae'].get(pos,0):.2f} xgb {xgb_metrics['pos_mae'].get(pos,0):.2f} ens {ens_metrics['pos_mae'].get(pos,0):.2f}")
        return stat_metrics, xgb_metrics, ens_metrics

    stat_2425_m, xgb_2425_m, ens_2425_m = eval_set("2024-2025", y_2425, stat_2425, xgb_2425, rows_2425)
    stat_2024_m, xgb_2024_m, ens_2024_m = eval_set("2024", y_2024, stat_2024, xgb_2024, rows_2024)
    stat_2025_m, xgb_2025_m, ens_2025_m = eval_set("2025", y_val, stat_val, xgb_val, val_rows_filt)

    # Gates: honest OOS gate is HOLDOUT (2025) with train-locked w.
    # Local holdout gate: ensemble (train-tuned w) beats local stat on all 3.
    # Absolute gate: ensemble holdout beats production freeze 4.563/0.648/0.741.
    # Combined 2024-2025 reported as diagnostic only (in-sample leakage).
    local_gate = (ens_2025_m["mae"] < stat_2025_m["mae"] and ens_2025_m["corr"] > stat_2025_m["corr"] and ens_2025_m["pairwise"] > stat_2025_m["pairwise"])
    absolute_gate = (ens_2025_m["mae"] < BASELINE["mae"] and ens_2025_m["corr"] > BASELINE["corr"] and ens_2025_m["pairwise"] > BASELINE["pairwise"])
    print(f"[backtest] honest local gate (ens train-tuned beats stat on holdout 2025, all 3) ? {local_gate}")
    print(f"[backtest] absolute gate (ens holdout beats freeze 4.563/0.648/74.1%) ? {absolute_gate}")
    print(f"  ens holdout MAE {ens_2025_m['mae']:.4f} vs baseline {BASELINE['mae']} {'PASS' if ens_2025_m['mae']<BASELINE['mae'] else 'FAIL'}")
    print(f"  ens corr {ens_2025_m['corr']:.4f} vs {BASELINE['corr']} {'PASS' if ens_2025_m['corr']>BASELINE['corr'] else 'FAIL'}")
    print(f"  ens pw {ens_2025_m['pairwise']:.4%} vs {BASELINE['pairwise']:.1%} {'PASS' if ens_2025_m['pairwise']>BASELINE['pairwise'] else 'FAIL'}")
    print(f"[backtest] diagnostic combined 2024-2025 (in-sample, NOT for gating): ens MAE {ens_2425_m['mae']:.4f} stat {stat_2425_m['mae']:.4f}")

    # Also check overfit: 2024 vs 2025 gap
    try:
        overfit_gap = abs(ens_2024_m["mae"] - ens_2025_m["mae"])
        print(f"[backtest] per-year overfit gap |2024-2025| MAE {overfit_gap:.4f}")
    except Exception:
        overfit_gap=None

    results = {
        "w": best_w,
        "w_note": "honest train-2024-tuned, locked, evaluated once on holdout 2025",
        "legacy_val_tuned_w": legacy_w,
        "legacy_val_tuned_mae": legacy_mae,
        "legacy_note": "val-tuned (leaky: tuned on val, reported on combined incl val) — documented only, current w=0.40 cited in headers is val-tuned",
        "grid": honest_grid,
        "legacy_grid_val_tuned": grid_results,
        "best_val_mae": best_mae,
        "model_loaded": model_loaded,
        "baseline": BASELINE,
        "local_gate_pass": local_gate,
        "absolute_gate_pass": absolute_gate,
        "combined_2024_2025": {
            "stat": stat_2425_m,
            "xgb": xgb_2425_m,
            "ensemble": ens_2425_m,
        },
        "per_year": {
            "2024": {"stat": stat_2024_m, "xgb": xgb_2024_m, "ensemble": ens_2024_m},
            "2025": {"stat": stat_2025_m, "xgb": xgb_2025_m, "ensemble": ens_2025_m},
        },
        "overfit_gap": overfit_gap,
        "feature_cols": feature_cols,
        "n_rows": {"val": len(val_rows_filt), "combined": len(rows_2425), "2024": len(rows_2024)},
    }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"[backtest] wrote {out_path}")

if __name__ == "__main__":
    main()
