#!/usr/bin/env python3
"""Reconcile FPP blend weight: 2-season fit (backtest_market_blend.py) found
model weight ~0.10; backtest_fp_projections.py's 2020-2025 pooled ensemble
grid found 0.00 (FP-alone wins outright). Same question, two different
protocols — this resolves it on ONE consistent protocol at the wider scale.

PRE-REGISTERED protocol (fixed before running, not tuned after seeing
results): train fit on 2020-2022 pooled, evaluate ONCE on 2023-2025
pooled holdout. This exactly mirrors backtest_fp_projections.py's split
(so the two analyses answer the same question on the same data), and is
run in ONE direction only — no cross-season k-fold, no trying multiple
fold schemes and reporting the best one. Gate: MAE < BASE, paired-t >= 2.0,
corr/pairwise not worse than BASE (same bar as backtest_market_blend.py).

Reuses backtest_market_blend.py's build_rows/fp_points/metrics/paired_t/
fit_arm/apply_arm — does not reimplement them. Only new code here is the
season-parameterized FPP loader (the original hardcodes season IN (2024,2025)).

Writes into data/ml/backtest_market_blend_results.json under a new key
"FPP_2020_2025", alongside (not replacing) the existing 2-season arms.

Repro: PYTHONHASHSEED=0 .venv/bin/python scripts/backtest_fpp_wide.py
"""
import json
import os
import sqlite3
import sys
from pathlib import Path

import numpy as np

os.environ.setdefault("SLEEPER_LEAGUE_ID", "test")

REPO_ROOT = Path(__file__).resolve().parents[1]
for p in (REPO_ROOT / "src", REPO_ROOT / "scripts"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from backtest_market_blend import (  # noqa: E402
    build_rows, fp_points, metrics, paired_t, fit_arm, apply_arm, ecr_to_points, FP_DB,
)
from backtest_ecr import _load_archive_weekly  # noqa: E402

CACHE = REPO_ROOT / "data" / "nfl_cache"
OUT_JSON = REPO_ROOT / "data" / "ml" / "backtest_market_blend_results.json"
TRAIN_SEASONS = (2020, 2021, 2022)
TEST_SEASONS = (2023, 2024, 2025)
T_GATE = 2.0


def _load(name):
    with open(CACHE / name, encoding="utf-8") as f:
        return json.load(f)


def load_fpp_wide(seasons):
    db = sqlite3.connect(FP_DB)
    q = ",".join("?" * len(seasons))
    out = {}
    for season, week, gsis, stats in db.execute(
            f"SELECT season, week, gsis_id, stats FROM proj_weekly "
            f"WHERE week BETWEEN 4 AND 18 AND season IN ({q}) AND gsis_id IS NOT NULL",
            seasons):
        out[(season, week, gsis)] = fp_points(json.loads(stats))
    return out


def main():
    arch = _load_archive_weekly()
    fpid_to_gsis = {str(r["fantasypros_id"]).split(".")[0]: r["gsis_id"]
                    for r in _load("ff_playerids.json") if r.get("fantasypros_id") and r.get("gsis_id")}
    all_seasons = TRAIN_SEASONS + TEST_SEASONS
    fpp = load_fpp_wide(all_seasons)
    print(f"[fppwide] fpp rows loaded: {len(fpp)} across seasons {all_seasons}", flush=True)

    rows = {s: build_rows(s, arch, fpid_to_gsis, fpp, {}, {}) for s in all_seasons}
    train = [r for s in TRAIN_SEASONS for r in rows[s]]
    test = [r for s in TEST_SEASONS for r in rows[s]]
    print(f"[fppwide] train(2020-2022) n={len(train)} test(2023-2025) n={len(test)}", flush=True)

    y = np.array([r["actual"] for r in test])
    base = [r["model"] for r in test]
    base_m = metrics(y, base, test)
    print(f"[fppwide] BASE holdout: MAE {base_m['mae']:.4f} corr {base_m['corr']:.4f} "
          f"pw {base_m['pairwise']:.4f} n={base_m['n']}", flush=True)

    fpp_cov_train = sum(1 for r in train if r["position"] in ("QB", "RB", "WR", "TE") and r["fpp"] is not None)
    fpp_cov_test = sum(1 for r in test if r["position"] in ("QB", "RB", "WR", "TE") and r["fpp"] is not None)
    print(f"[fppwide] FPP coverage: train={fpp_cov_train} test={fpp_cov_test}", flush=True)

    # market_value() unconditionally computes an ecr_pts side value even for
    # the FPP branch (it's a shared helper across arms); fit it for real so
    # indexing doesn't KeyError, even though the FPP arm's return ignores it.
    ecr_fit = ecr_to_points(train)
    result = {"train_seasons": list(TRAIN_SEASONS), "test_seasons": list(TEST_SEASONS),
              "BASE": base_m, "fpp_coverage": {"train": fpp_cov_train, "test": fpp_cov_test},
              "forms": {}}
    for form in ("w", "wp"):
        params = fit_arm(train, "FPP", form, ecr_fit)
        pred, used = apply_arm(test, "FPP", form, params, ecr_fit)
        m = metrics(y, pred, test)
        t, dmean = paired_t(y, base, pred)
        passed = (m["mae"] < base_m["mae"] and t >= T_GATE and m["corr"] >= base_m["corr"]
                  and m["pairwise"] >= base_m["pairwise"])
        result["forms"][form] = {**m, "paired_t": t, "mean_abs_err_gain": dmean,
                                  "rows_blended": used, "params": params, "pass": passed}
        label = "pooled" if form == "wp" else "per-position"
        print(f"[fppwide] {label:13s} w={params if form == 'wp' else params} "
              f"MAE {m['mae']:.4f} ({m['mae'] - base_m['mae']:+.4f}) corr {m['corr']:.4f} "
              f"pw {m['pairwise']:.4f} t={t:.2f} blended={used} {'PASS' if passed else 'fail'}",
              flush=True)

    existing = json.loads(OUT_JSON.read_text()) if OUT_JSON.exists() else {}
    existing["FPP_2020_2025"] = result
    OUT_JSON.write_text(json.dumps(existing, indent=1))
    print(f"[fppwide] wrote {OUT_JSON} (key FPP_2020_2025, other keys untouched)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
