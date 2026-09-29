#!/usr/bin/env python3
"""Fit projection-conditional floor/ceiling (P20/P80) per position.

Walk-forward production build_weekly_projections on 2024-2025 weeks 4-18
(same harness as backtest_market_blend.py), bin rows by projection per
position (equal-count bins), take P20/P80 of actual points per bin.

Honest check: fit on 2024, report coverage/width on 2025 (never seen).
Shipped table: fit on 2024+2025 pooled. Paste INTERVAL_TABLE output into
stat_projector.py.

Usage:
  SLEEPER_LEAGUE_ID=test .venv/bin/python scripts/fit_intervals.py [--pairs cache.json]
"""
import argparse
import json
import os
import sys
from pathlib import Path

os.environ.setdefault("SLEEPER_LEAGUE_ID", "test")
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

import numpy as np  # noqa: E402

from ffanalytics.scoring import DEFAULT_SCORING, calculate_fantasy_points  # noqa: E402
from ffanalytics.stat_projector import build_weekly_projections, interval_bounds  # noqa: E402

CACHE = REPO_ROOT / "data" / "nfl_cache"
POSITIONS = ("QB", "RB", "WR", "TE", "K")
Q_LO, Q_HI = 20, 80
N_BINS = {"QB": 6, "RB": 8, "WR": 8, "TE": 7, "K": 4}


def _load(name):
    with open(CACHE / name, encoding="utf-8") as f:
        return json.load(f)


def build_pairs():
    out = []
    for season in (2024, 2025):
        stats = [r for r in _load(f"stats_{season}.json") if r.get("season_type", "REG") == "REG"]
        prior = [r for r in _load(f"stats_{season - 1}.json") if r.get("season_type", "REG") == "REG"]
        sched = _load(f"schedule_{season}.json")
        for w in range(4, 19):
            hist = [r for r in stats if (r.get("week") or 0) < w]
            projs = {str(p["player_id"]): float(p["projected_points"])
                     for p in build_weekly_projections(hist, sched, w, DEFAULT_SCORING, prior_season_stats=prior)}
            for r in stats:
                if r.get("week") != w or r.get("position") not in POSITIONS:
                    continue
                g = str(r.get("player_id"))
                if g in projs:
                    out.append([season, w, r["position"], projs[g],
                                float(calculate_fantasy_points(r, DEFAULT_SCORING))])
        print(f"[fit] {season}: {len(out)} rows", flush=True)
    return out


def fit(rows):
    table = {}
    for pos in POSITIONS:
        pr = np.array([(p, a) for _, _, ps, p, a in rows if ps == pos])
        order = np.argsort(pr[:, 0])
        pts = []
        for chunk in np.array_split(pr[order], N_BINS[pos]):
            c = float(chunk[:, 0].mean())
            lo, hi = np.percentile(chunk[:, 1], [Q_LO, Q_HI])
            pts.append((round(c, 1), round(float(min(lo, c)), 1), round(float(max(hi, c)), 1)))
        table[pos] = pts
    return table


def evaluate(rows, table):
    res = {}
    for pos in POSITIONS:
        sub = [(p, a) for _, _, ps, p, a in rows if ps == pos]
        b = [interval_bounds(p, pos, table) for p, _ in sub]
        cov = np.mean([lo <= a <= hi for (lo, hi), (_, a) in zip(b, sub)])
        below = np.mean([a < lo for (lo, _), (_, a) in zip(b, sub)])
        width = np.mean([hi - lo for lo, hi in b])
        res[pos] = {"n": len(sub), "coverage": round(float(cov), 3),
                    "below_floor": round(float(below), 3), "mean_width": round(float(width), 2)}
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pairs", help="cache file for (season, week, pos, proj, actual) rows")
    args = ap.parse_args()
    if args.pairs and Path(args.pairs).exists():
        rows = json.load(open(args.pairs))
    else:
        rows = build_pairs()
        if args.pairs:
            json.dump(rows, open(args.pairs, "w"))

    r24 = [r for r in rows if r[0] == 2024]
    r25 = [r for r in rows if r[0] == 2025]
    t24 = fit(r24)
    print(f"\nHoldout: fit 2024 -> eval 2025 (target coverage {(Q_HI - Q_LO) / 100:.2f}, below-floor {Q_LO / 100:.2f})")
    for pos, m in evaluate(r25, t24).items():
        print(f"  {pos}: {m}")

    final = fit(rows)
    print("\nINTERVAL_TABLE = {")
    for pos, pts in final.items():
        print(f'    "{pos}": {pts},')
    print("}")


if __name__ == "__main__":
    main()
