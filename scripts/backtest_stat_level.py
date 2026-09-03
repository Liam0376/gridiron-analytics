#!/usr/bin/env python3
"""Head-to-head backtest for stat-level XGB vs stat projector.

Mirrors scripts/backtest_ml.py but for stat-level:
For each val row, predict each stat via its booster (or fallback to stat_projector's *_proj if booster missing),
build predicted stats dict, score via calculate_fantasy_points(..., SCORING) to get predicted points,
compare to actual target. Compute MAE/corr/pairwise/bias overall and per-position (QB/RB/WR/TE/K) weeks 4-18.
NESTED PROTOCOL: gate on HOLDOUT (2025 val) only — combined 2024-2025 incl.
train is diagnostic (in-sample leakage for per-stat boosters trained on
2023-2024). Compare holdout to production freeze 4.563/0.648/0.741 and to
point-level ensemble legacy w=0.40 (val-tuned, leaky — documented, NOT
re-tuned). Write data/ml/backtest_stat_level_results.json with gates.

No network, no opponent defense/home/away/rest/EWMA — same disciplined feature set.
"""
import json
import os
import sys
from pathlib import Path
from collections import defaultdict

os.environ.setdefault("SLEEPER_LEAGUE_ID", "test")

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

# Production freeze baseline (true scoring, 2024-2025 weeks 4-18, n=10351):
# MAE 4.563 / Corr 0.648 / Pairwise 0.741. Early scratch 4.163/0.6918/0.777
# was K-zeroed (old_map ignored fg_* → K MAE 0.001, -0.416 bias) — SUPERSEDED.
BASELINE = {"mae": 4.563, "corr": 0.648, "pairwise": 0.741}
POINT_LEVEL_ENSEMBLE_MAE = 4.45  # from rejected point-level legacy w=0.40 (val-tuned, leaky — documented, NOT re-tuned)

# Feature list must match train_stat_level.py.
# Canonical training code reference (REJECTED, no behavior change):
#   src/ffanalytics/ml/ is intentionally empty (XGBoost stat-level rejected).
#   Canonical training code lives at docs/rejected-ml-evidence/ml_train_stat_level.py
#   (verbatim from src/ffanalytics/ml/train_stat_level.py) + ml_features.py.
#   Explicit commented import path (do NOT resurrect training, no new deps):
#   # from docs.rejected_ml_evidence.ml_train_stat_level import FEATURE_COLS, STAT_LIST, KICKER_STATS_SET  # REJECTED — evidence: data/models/stat_level/meta.json val 4.463 narrow win not worth risk, combined 4.307 in-sample overfit gap 0.316
#   tested and REJECTED — evidence: data/models/stat_level/meta.json (val 4.463 vs freeze 4.563 narrow win, combined 4.307 in-sample overfit gap 0.316).
#   Backtests below use hardcoded FEATURE_COLS fallback only.
try:
    from ffanalytics.ml.train_stat_level import FEATURE_COLS, STAT_LIST, KICKER_STATS_SET
except Exception:
    FEATURE_COLS = [
        "games_played","implied_total","spread","wind","temp","is_dome",
        "target_share_wavg","rush_share_wavg","air_yards_wavg","air_yards_share_wavg",
        "redzone_targets_wavg","redzone_carries_wavg","snap_share_wavg","route_share_wavg",
        "recent_trend","trend_slope","recent_trend_slope",
        "passing_yards_proj","passing_tds_proj","passing_interceptions_proj","rushing_yards_proj","rushing_tds_proj",
        "receiving_yards_proj","receiving_tds_proj","receptions_proj","fumbles_lost_total_proj",
        "fg_made_0_19_proj","fg_made_20_29_proj","fg_made_30_39_proj","fg_made_40_49_proj","fg_made_50_59_proj","fg_missed_proj","pat_made_proj",
        "position_QB","position_RB","position_WR","position_TE","position_K",
    ]
    STAT_LIST = ["passing_yards","passing_tds","rushing_yards","rushing_tds","receiving_yards","receiving_tds","receptions","passing_interceptions","fumbles_lost_total","fg_made_0_19","fg_made_20_29","fg_made_30_39","fg_made_40_49","fg_made_50_59","fg_missed","pat_made"]
    KICKER_STATS_SET = set(["fg_made_0_19","fg_made_20_29","fg_made_30_39","fg_made_40_49","fg_made_50_59","fg_missed","pat_made"])

try:
    from ffanalytics.scoring import calculate_fantasy_points, DEFAULT_SCORING
    SCORING = DEFAULT_SCORING
except Exception:
    # Fallback includes fg_*/xpm (K-zero bug class already fixed here; guard below prevents regression).
    SCORING = {
        "rec": 1.0, "rec_yd": 0.1, "rush_yd": 0.1, "pass_yd": 0.04,
        "pass_td": 5.0, "rush_td": 6.0, "rec_td": 6.0, "pass_int": -1.0,
        "fum_lost": -2.0, "fgm_0_19": 3.0, "fgm_20_29": 3.0, "fgm_30_39": 3.0,
        "fgm_40_49": 4.0, "fgm_50_59": 5.0, "fgmiss": -1.0, "xpm": 1.0,
    }
    # K-zero guard: fallback must contain kicking keys or scoring silently zeroes K (early 4.163 bug).
    assert all(k in SCORING for k in ("fgm_0_19", "fgm_20_29", "fgm_30_39", "fgm_40_49", "fgm_50_59", "fgmiss", "xpm")), \
        "SCORING fallback missing fg_*/xpm keys — K would score 0 (K-zero bug class, see stat_projector.py:8-13)"
    def calculate_fantasy_points(stats, scoring_settings=None):
        return 0.0


def _load_jsonl(path: Path):
    rows = []
    if not path.exists():
        print(f"[backtest_stat] file not found: {path}")
        return rows
    with open(path) as f:
        for line in f:
            line=line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def _pred_dict_to_scoring(pred_stats_dict):
    return {
        "receptions": pred_stats_dict.get("receptions", 0) or 0,
        "receiving_yards": pred_stats_dict.get("receiving_yards", 0) or 0,
        "receiving_tds": pred_stats_dict.get("receiving_tds", 0) or 0,
        "rushing_yards": pred_stats_dict.get("rushing_yards", 0) or 0,
        "rushing_tds": pred_stats_dict.get("rushing_tds", 0) or 0,
        "passing_yards": pred_stats_dict.get("passing_yards", 0) or 0,
        "passing_tds": pred_stats_dict.get("passing_tds", 0) or 0,
        "interceptions": pred_stats_dict.get("passing_interceptions", 0) or 0,
        "fumbles_lost": pred_stats_dict.get("fumbles_lost_total", 0) or 0,
        "passing_2pt": 0, "rushing_2pt": 0, "receiving_2pt": 0,
        "passing_40": 0, "rushing_40": 0, "receiving_40": 0,
        "fg_made_0_19": pred_stats_dict.get("fg_made_0_19", 0) or 0,
        "fg_made_20_29": pred_stats_dict.get("fg_made_20_29", 0) or 0,
        "fg_made_30_39": pred_stats_dict.get("fg_made_30_39", 0) or 0,
        "fg_made_40_49": pred_stats_dict.get("fg_made_40_49", 0) or 0,
        "fg_made_50_59": pred_stats_dict.get("fg_made_50_59", 0) or 0,
        "fg_made_60_": pred_stats_dict.get("fg_made_60_", 0) or 0,
        "fg_missed": pred_stats_dict.get("fg_missed", 0) or 0,
        "pat_made": pred_stats_dict.get("pat_made", 0) or 0,
        "pat_missed": 0, "fumble_recovery": 0, "fumble_recovery_td": 0, "forced_fumble": 0,
    }


def _map_proj_to_scoring(row):
    """Stat projector baseline: convert *_proj features to scoring dict."""
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
        "passing_2pt": 0, "rushing_2pt": 0, "receiving_2pt": 0,
        "passing_40": 0, "rushing_40": 0, "receiving_40": 0,
        "fg_made_0_19": row.get("fg_made_0_19_proj", 0) or 0,
        "fg_made_20_29": row.get("fg_made_20_29_proj", 0) or 0,
        "fg_made_30_39": row.get("fg_made_30_39_proj", 0) or 0,
        "fg_made_40_49": row.get("fg_made_40_49_proj", 0) or 0,
        "fg_made_50_59": row.get("fg_made_50_59_proj", 0) or 0,
        "fg_made_60_": 0,
        "fg_missed": row.get("fg_missed_proj", 0) or 0,
        "pat_made": row.get("pat_made_proj", 0) or 0,
        "pat_missed": 0, "fumble_recovery": 0, "fumble_recovery_td": 0, "forced_fumble": 0,
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
    parser=argparse.ArgumentParser(description="Backtest stat-level XGB")
    parser.add_argument("--train", default="data/ml/train_2023_2024.jsonl", help="train jsonl")
    parser.add_argument("--val", default="data/ml/val_2025.jsonl", help="val jsonl")
    parser.add_argument("--model-dir", default="data/models/stat_level", help="directory with per-stat boosters")
    parser.add_argument("--out", default="data/ml/backtest_stat_level_results.json", help="output json")
    args=parser.parse_args()

    train_path = (REPO_ROOT / args.train) if not Path(args.train).is_absolute() else Path(args.train)
    val_path = (REPO_ROOT / args.val) if not Path(args.val).is_absolute() else Path(args.val)
    model_dir = (REPO_ROOT / args.model_dir) if not Path(args.model_dir).is_absolute() else Path(args.model_dir)
    out_path = (REPO_ROOT / args.out) if not Path(args.out).is_absolute() else Path(args.out)

    print(f"[backtest_stat] loading train {train_path}")
    train_rows=_load_jsonl(train_path)
    val_rows=_load_jsonl(val_path)
    print(f"[backtest_stat] train rows {len(train_rows)} val rows {len(val_rows)}")

    rows_2425 = [r for r in train_rows if r.get("season")==2024] + val_rows
    rows_2425 = [r for r in rows_2425 if 4 <= int(r.get("week",0)) <= 18]
    val_rows_filt = [r for r in val_rows if 4 <= int(r.get("week",0)) <= 18]
    rows_2024 = [r for r in rows_2425 if r.get("season")==2024]
    rows_2025 = val_rows_filt
    print(f"[backtest_stat] 2024 rows {len(rows_2024)} 2025 rows {len(rows_2025)} combined {len(rows_2425)}")

    # Compute stat baseline points (stat_projector *_proj scoring)
    stat_val = _compute_stat_pts(val_rows_filt)
    stat_2425 = _compute_stat_pts(rows_2425)
    stat_2024 = _compute_stat_pts(rows_2024)

    y_val = [float(r.get("target", r.get("actual_points",0)) or 0) for r in val_rows_filt]
    y_2425 = [float(r.get("target",0) or 0) for r in rows_2425]
    y_2024 = [float(r.get("target",0) or 0) for r in rows_2024]

    # Load per-stat boosters and predict
    feature_cols = FEATURE_COLS
    # try to read meta to get feature list
    meta_path = model_dir / "meta.json"
    if meta_path.exists():
        try:
            with open(meta_path) as f:
                meta=json.load(f)
            if "features" in meta and isinstance(meta["features"], list):
                feature_cols = meta["features"]
                print(f"[backtest_stat] using feature cols from meta ({len(feature_cols)})")
            if "stat_list" in meta:
                # use stat list from meta if present
                meta_stat_list = meta["stat_list"]
                if isinstance(meta_stat_list, list) and meta_stat_list:
                    # keep but ensure we use same
                    pass
        except Exception as e:
            print(f"[backtest_stat] failed to read meta features: {e}", file=sys.stderr)

    # Load models per stat
    models = {}
    model_loaded = {}
    try:
        import xgboost
        from xgboost import XGBRegressor
        import numpy as np
        for stat in STAT_LIST:
            p = model_dir / f"{stat}.json"
            if not p.exists():
                print(f"[backtest_stat] booster missing for {stat}: {p} — will fallback to _proj")
                models[stat] = None
                model_loaded[stat] = False
                continue
            try:
                m = XGBRegressor()
                m.load_model(str(p))
                models[stat] = m
                model_loaded[stat] = True
                print(f"[backtest_stat] loaded {stat} from {p}")
            except Exception as e:
                print(f"[backtest_stat] failed to load {stat}: {e}", file=sys.stderr)
                # try booster direct
                try:
                    import xgboost as xgb
                    bst = xgb.Booster()
                    bst.load_model(str(p))
                    # wrap as booster for predict via DMatrix
                    models[stat] = bst  # mark as booster
                    model_loaded[stat] = True
                except Exception as e2:
                    print(f"[backtest_stat] booster direct load failed for {stat}: {e2}", file=sys.stderr)
                    models[stat] = None
                    model_loaded[stat] = False
    except ImportError as e:
        print(f"[backtest_stat] xgboost not available: {e} — will fallback to stat for all", file=sys.stderr)
        models = {s: None for s in STAT_LIST}
        model_loaded = {s: False for s in STAT_LIST}
    except Exception as e:
        print(f"[backtest_stat] xgboost predict setup failed: {e}", file=sys.stderr)
        models = {s: None for s in STAT_LIST}

    # Helper to predict per set
    def _predict_stat_level(rows):
        import numpy as np
        n = len(rows)
        if n == 0:
            return []
        # For each stat, get predictions vector
        per_stat_preds = {}
        for stat in STAT_LIST:
            m = models.get(stat)
            if m is None:
                # fallback to _proj
                arr = []
                for r in rows:
                    v = r.get(f"{stat}_proj", 0)
                    if v is None:
                        v = 0
                    try:
                        arr.append(max(0.0, float(v)))
                    except Exception:
                        arr.append(0.0)
                per_stat_preds[stat] = np.array(arr, dtype=float)
            else:
                # build matrix
                X,_ = _to_matrix(rows, feature_cols)
                try:
                    # check if m is XGBRegressor or Booster
                    if hasattr(m, "predict") and not isinstance(m, type((lambda:0))):
                        # XGBRegressor
                        preds = m.predict(X)
                    else:
                        preds = m.predict(X)
                except Exception:
                    # fallback to booster DMatrix
                    try:
                        import xgboost as xgb
                        d = xgb.DMatrix(X, feature_names=feature_cols)
                        preds = m.predict(d)
                    except Exception as e:
                        print(f"[backtest_stat] predict failed for {stat}: {e} fallback to proj", file=sys.stderr)
                        preds = np.array([float(r.get(f"{stat}_proj",0) or 0) for r in rows], dtype=float)
                preds = np.maximum(preds, 0)
                # For K stats, zero out non-K rows to fallback proj
                if stat in KICKER_STATS_SET:
                    for idx, r in enumerate(rows):
                        if r.get("position") != "K":
                            v = r.get(f"{stat}_proj", 0)
                            if v is None:
                                v = 0
                            try:
                                preds[idx] = max(0.0, float(v))
                            except Exception:
                                preds[idx] = 0.0
                per_stat_preds[stat] = preds

        # Assemble predicted points per row
        y_pred = []
        for idx, r in enumerate(rows):
            pred_dict = {}
            for stat in STAT_LIST:
                pred_dict[stat] = float(per_stat_preds[stat][idx])
            # For any stats not in STAT_LIST but needed for scoring, ensure fallback via proj (already handled for core)
            # Ensure all keys present for scoring; missing K stats will be via pred_dict but may be 0
            scoring_dict = _pred_dict_to_scoring(pred_dict)
            try:
                pts = float(calculate_fantasy_points(scoring_dict, SCORING))
            except Exception:
                pts = 0.0
            y_pred.append(pts)
        return y_pred

    # Predict
    stat_level_val = _predict_stat_level(val_rows_filt)
    stat_level_2425 = _predict_stat_level(rows_2425)
    stat_level_2024 = _predict_stat_level(rows_2024)
    # If no models loaded, fallback already used

    # If stat_level_val is empty or all fallback, still need to compare
    # Evaluate
    def eval_set(name, y_true, stat_pred, stat_level_pred, rows):
        import numpy as np
        stat_metrics = _evaluate(y_true, stat_pred, rows)
        sl_metrics = _evaluate(y_true, stat_level_pred, rows)
        print(f"[backtest_stat] {name} stat       MAE {stat_metrics['mae']:.4f} corr {stat_metrics['corr']:.4f} pw {stat_metrics['pairwise']:.4%} bias {stat_metrics['bias']:.4f} n {stat_metrics['n']}")
        print(f"[backtest_stat] {name} stat-level MAE {sl_metrics['mae']:.4f} corr {sl_metrics['corr']:.4f} pw {sl_metrics['pairwise']:.4%} bias {sl_metrics['bias']:.4f} n {sl_metrics['n']}")
        for pos in sorted(stat_metrics["pos_mae"]):
            print(f"  {name} pos {pos}: stat {stat_metrics['pos_mae'].get(pos,0):.2f} stat_level {sl_metrics['pos_mae'].get(pos,0):.2f}")
        return stat_metrics, sl_metrics

    stat_2425_m, sl_2425_m = eval_set("2024-2025", y_2425, stat_2425, stat_level_2425, rows_2425)
    stat_2024_m, sl_2024_m = eval_set("2024", y_2024, stat_2024, stat_level_2024, rows_2024)
    stat_2025_m, sl_2025_m = eval_set("2025", y_val, stat_val, stat_level_val, val_rows_filt)

    # Gates (NESTED PROTOCOL): stat-level must beat ALL THREE on HOLDOUT (2025)
    # vs production freeze 4.563/0.648/0.741 => ACCEPTED else REJECTED.
    # Combined 2024-2025 incl. train is diagnostic only (in-sample overfit for
    # boosters trained on 2023-2024; gap reported as overfit_gap below).
    sl_mae = sl_2025_m["mae"]
    sl_corr = sl_2025_m["corr"]
    sl_pw = sl_2025_m["pairwise"]

    absolute_gate = (sl_mae is not None and sl_corr is not None and sl_pw is not None and sl_mae < BASELINE["mae"] and sl_corr > BASELINE["corr"] and sl_pw > BASELINE["pairwise"])
    local_gate = (sl_2025_m["mae"] < stat_2025_m["mae"] and sl_2025_m["corr"] > stat_2025_m["corr"] and sl_2025_m["pairwise"] > stat_2025_m["pairwise"])
    beats_point_level = (sl_mae is not None and sl_mae < POINT_LEVEL_ENSEMBLE_MAE)

    print(f"[backtest_stat] honest absolute gate (holdout 2025 beats freeze 4.563/0.648/74.1%) ? {absolute_gate}")
    print(f"  stat-level holdout MAE {sl_mae:.4f} vs baseline {BASELINE['mae']} {'PASS' if sl_mae<BASELINE['mae'] else 'FAIL'}")
    print(f"  corr {sl_corr:.4f} vs {BASELINE['corr']} {'PASS' if sl_corr>BASELINE['corr'] else 'FAIL'}")
    print(f"  pw {sl_pw:.4%} vs {BASELINE['pairwise']:.1%} {'PASS' if sl_pw>BASELINE['pairwise'] else 'FAIL'}")
    print(f"[backtest_stat] honest local gate (holdout beats local stat, all 3) ? {local_gate}")
    print(f"[backtest_stat] diagnostic combined 2024-2025 (in-sample, NOT for gating): stat-level {sl_2425_m['mae']:.4f} vs stat {stat_2425_m['mae']:.4f}")
    print(f"[backtest_stat] beats point-level legacy ensemble {POINT_LEVEL_ENSEMBLE_MAE} ? {beats_point_level} (stat-level holdout {sl_mae:.4f})")

    # Also check per-position
    try:
        overfit_gap = abs(sl_2024_m["mae"] - sl_2025_m["mae"])
        print(f"[backtest_stat] per-year overfit gap |2024-2025| MAE {overfit_gap:.4f}")
    except Exception:
        overfit_gap=None

    status = "ACCEPTED" if absolute_gate else "REJECTED"
    reason = ""
    if absolute_gate:
        reason = f"stat-level MAE {sl_mae:.4f} < {BASELINE['mae']} and corr {sl_corr:.4f} > {BASELINE['corr']} and pairwise {sl_pw:.4%} > {BASELINE['pairwise']:.1%} — ACCEPTED"
    else:
        fails = []
        if sl_mae is None or sl_mae >= BASELINE["mae"]:
            fails.append(f"MAE {sl_mae:.4f} >= {BASELINE['mae']}")
        if sl_corr is None or sl_corr <= BASELINE["corr"]:
            fails.append(f"corr {sl_corr:.4f} <= {BASELINE['corr']}")
        if sl_pw is None or sl_pw <= BASELINE["pairwise"]:
            fails.append(f"pairwise {sl_pw:.4%} <= {BASELINE['pairwise']:.1%}")
        reason = "REJECTED — " + "; ".join(fails) + f" — stat-level does not beat all three gates vs baseline; vs point-level {POINT_LEVEL_ENSEMBLE_MAE} diff {sl_mae-POINT_LEVEL_ENSEMBLE_MAE:+.4f}"

    print(f"[backtest_stat] final status {status}: {reason}")

    results = {
        "status": status,
        "reason": reason,
        "protocol": "nested: gate on holdout 2025 only; combined 2024-2025 diagnostic (in-sample)",
        "holdout_2025": {
            "stat": stat_2025_m,
            "stat_level": sl_2025_m,
        },
        "baseline": BASELINE,
        "point_level_ensemble_mae": POINT_LEVEL_ENSEMBLE_MAE,
        "absolute_gate_pass": absolute_gate,
        "local_gate_pass": local_gate,
        "beats_point_level": beats_point_level,
        "combined_2024_2025": {
            "stat": stat_2425_m,
            "stat_level": sl_2425_m,
        },
        "per_year": {
            "2024": {"stat": stat_2024_m, "stat_level": sl_2024_m},
            "2025": {"stat": stat_2025_m, "stat_level": sl_2025_m},
        },
        "overfit_gap": overfit_gap,
        "feature_cols": feature_cols,
        "stat_list": STAT_LIST,
        "model_loaded": model_loaded,
        "n_rows": {"val": len(val_rows_filt), "combined": len(rows_2425), "2024": len(rows_2024)},
        "gates": {
            "mae_gate": sl_mae < BASELINE["mae"] if sl_mae is not None else False,
            "corr_gate": sl_corr > BASELINE["corr"] if sl_corr is not None else False,
            "pairwise_gate": sl_pw > BASELINE["pairwise"] if sl_pw is not None else False,
        }
    }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"[backtest_stat] wrote {out_path} with status {status}")

    # Also update meta.json with backtest summary if exists.
    # Nested backtest.* is combined_diagnostic (in-sample, NOT val) — honest holdout
    # top-level val_* remains canonical (see data/models/stat_level/meta.json).
    if meta_path.exists():
        try:
            with open(meta_path) as f:
                meta=json.load(f)
            meta["backtest"] = {
                "status": status,
                "reason": reason,
                "combined_diagnostic_mae": sl_2425_m["mae"],
                "combined_diagnostic_corr": sl_2425_m["corr"],
                "combined_diagnostic_pairwise": sl_2425_m["pairwise"],
                "combined_diagnostic_absolute_gate": (sl_2425_m["mae"] < BASELINE["mae"] and sl_2425_m["corr"] > BASELINE["corr"] and sl_2425_m["pairwise"] > BASELINE["pairwise"]),
                "local_gate": local_gate,
                "overfit_gap": overfit_gap,
                "overfit_gap_note": "overfit_gap = |2024 in-sample MAE - 2025 holdout MAE|; combined win is 2024 overfit, honest OOS gate is holdout top-level val_* only.",
                "protocol_note": "nested: gate on honest holdout 2025 top-level val_* only; combined_diagnostic incl. train is in-sample diagnostic (see nested protocol)",
            }
            with open(meta_path, "w") as out:
                json.dump(meta, out, indent=2)
            print(f"[backtest_stat] updated meta {meta_path} with backtest summary")
        except Exception as e:
            print(f"[backtest_stat] failed to update meta: {e}", file=sys.stderr)

if __name__ == "__main__":
    main()
