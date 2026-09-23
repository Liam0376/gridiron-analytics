#!/usr/bin/env python3
"""Market blend backtest: production projection blended with market signals.

Question: ECR out-ranks the model at every position (backtest_ecr.py:
RB Spearman 0.78 vs 0.66). Does pulling the point projection toward the
market lower weekly error on the production-freeze scope?

Scope (mirrors the freeze): 2024 + 2025 REG weeks 4-18, box-score rows
(player played), QB/RB/WR/TE/K, true scoring (DEFAULT_SCORING). Model =
production-verbatim build_weekly_projections (no reimplementation).

Arms (market applies to QB/RB/WR/TE; K and rows without market keep BASE):
  BASE   production projection.
  ECR    blend with free weekly ECR (nflverse load_ff_rankings archive,
         Friday scrape — exactly what production can read live, $0).
         ECR -> points per position: pts = a + b*log(ecr), fit on train.
  FPP    blend with FantasyPros consensus projections (paid-API dump,
         data/fantasypros_dump/fp.sqlite) rescored with DEFAULT_SCORING.
         NOT deployable after the 2026-09-23 trial ends; this is the
         ceiling for "what would a real projection source buy us".
  FPP+ECR  three-way stack.
  SLP    blend with Sleeper projections (public api.sleeper.com, company
         rotowire, weekly history back to 2021, $0, same API production
         already calls). Scored natively: Sleeper stat keys == scoring keys.
  ECRSUN diagnostic, not a candidate: dump OP-list ECR (Sunday version).
         ECRSUN minus ECR gain ~= what Sunday-morning timing buys.
For each market arm two forms, fit per position on the train season only:
  w     convex blend  pred = w*model + (1-w)*market, w on a 0.05 grid.
  ols   stack         pred = a + b*model + c*market (least squares).
  wp    pooled convex   one w shared by QB/RB/WR/TE (per-position w
        swings fold to fold, e.g. SLP RB 0.05 vs 0.50: flat MAE surface).

Protocol: cross-season. Fit on 2024 -> score 2025, fit on 2025 -> score
2024. Gate per arm on both holdouts: MAE below BASE with paired-t on
|err| >= 2.0 (the bar that rejected snap-share at t=1.66), corr and
pairwise not worse than BASE.

Leakage guards: market is used only for teams whose game is on/after the
snapshot (ECR: Friday scrape, backtest_ecr._ecr_for_week early_teams;
FPP dump snapshots are Sunday versions, so any team playing before that
week's Sunday falls back to BASE). FPP Sunday versions still know
same-day inactives of teammates; the model does not. Treat FPP gains as
an upper bound, not a deployable number.

Repro: PYTHONHASHSEED=0 .venv/bin/python scripts/backtest_market_blend.py
Writes data/ml/backtest_market_blend_results.json.
"""
import json
import math
import os
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

os.environ.setdefault("SLEEPER_LEAGUE_ID", "test")

REPO_ROOT = Path(__file__).resolve().parents[1]
for p in (REPO_ROOT / "src", REPO_ROOT / "scripts"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from ffanalytics.stat_projector import build_weekly_projections  # noqa: E402
from ffanalytics.scoring import calculate_fantasy_points, DEFAULT_SCORING  # noqa: E402
from backtest_ecr import _load_archive_weekly, _ecr_for_week  # noqa: E402

CACHE = REPO_ROOT / "data" / "nfl_cache"
FP_DB = REPO_ROOT / "data" / "fantasypros_dump" / "fp.sqlite"
OUT_JSON = REPO_ROOT / "data" / "ml" / "backtest_market_blend_results.json"
FREEZE = {"mae": 4.563, "corr": 0.648, "pairwise": 0.741}
POSITIONS = ("QB", "RB", "WR", "TE", "K")
MARKET_POS = ("QB", "RB", "WR", "TE")
WEEKS = range(4, 19)
SEASONS = (2024, 2025)
T_GATE = 2.0
W_GRID = [round(i * 0.05, 2) for i in range(21)]

# FantasyPros projection stat -> scoring.py stat key. FP "fumbles" is
# fumbles lost (weekly means ~0.1-0.2); "2pt_tds" is any 2-pt conversion,
# all worth 2.0 in DEFAULT_SCORING so the rushing bucket is exact.
FP_TO_SCORING = {
    "pass_yds": "passing_yards", "pass_tds": "passing_tds", "pass_ints": "interceptions",
    "rush_yds": "rushing_yards", "rush_tds": "rushing_tds",
    "rec_rec": "receptions", "rec_yds": "receiving_yards", "rec_tds": "receiving_tds",
    "fumbles": "fumbles_lost", "2pt_tds": "rushing_2pt",
}


def _load(name):
    with open(CACHE / name, encoding="utf-8") as f:
        return json.load(f)


def fp_points(stats: dict) -> float:
    return float(calculate_fantasy_points(
        {FP_TO_SCORING[k]: v for k, v in stats.items() if k in FP_TO_SCORING}, DEFAULT_SCORING))


def early_teams_before_sunday(sched, week):
    """Teams whose REG game is before the week's modal gameday (Sunday)."""
    games = [g for g in sched if g.get("game_type") == "REG" and g.get("week") == week]
    days = Counter(str(g.get("gameday") or "") for g in games)
    if not days:
        return set()
    sunday = days.most_common(1)[0][0]
    return {t for g in games if str(g.get("gameday") or "") < sunday
            for t in (g.get("home_team"), g.get("away_team")) if t}


def build_rows(season, arch, fpid_to_gsis, fpp, slp, ecrsun):
    stats = [r for r in _load(f"stats_{season}.json") if r.get("season_type", "REG") == "REG"]
    prior = [r for r in _load(f"stats_{season - 1}.json") if r.get("season_type", "REG") == "REG"]
    sched = _load(f"schedule_{season}.json")
    rows, no_proj = [], 0
    for w in WEEKS:
        hist = [r for r in stats if (r.get("week") or 0) < w]
        projs = build_weekly_projections(hist, sched, w, DEFAULT_SCORING, prior_season_stats=prior)
        model = {str(p["player_id"]): float(p["projected_points"]) for p in projs}
        ecr_wk, _, _ = _ecr_for_week(arch, sched, w)
        ecr_by_gsis, ecr_early = {}, set()
        if ecr_wk:
            ecr_early = set(ecr_wk["early_teams"])
            for fpid, e in ecr_wk["ecr"].items():
                g = fpid_to_gsis.get(fpid)
                if g and ecr_wk["pos"].get(fpid) in MARKET_POS:
                    ecr_by_gsis[g] = e
        fp_early = early_teams_before_sunday(sched, w)
        for r in stats:
            if r.get("week") != w or r.get("position") not in POSITIONS:
                continue
            gsis = str(r.get("player_id"))
            if gsis not in model:
                no_proj += 1
                continue
            team, pos = r.get("team"), r.get("position")
            mk = pos in MARKET_POS
            rows.append({
                "season": season, "week": w, "gsis": gsis, "position": pos,
                "actual": float(calculate_fantasy_points(r, DEFAULT_SCORING)),
                "model": model[gsis],
                "ecr": ecr_by_gsis.get(gsis) if mk and team not in ecr_early else None,
                "fpp": fpp.get((season, w, gsis)) if mk and team not in fp_early else None,
                "slp": slp.get((season, w, gsis)) if mk and team not in fp_early else None,
                "ecrsun": ecrsun.get((season, w, gsis)) if mk and team not in fp_early else None,
            })
    print(f"[blend] {season}: rows={len(rows)} no-model-projection skipped={no_proj}", flush=True)
    return rows


def load_sleeper(season):
    """{(season, week, gsis): points} from the public Sleeper projections API.
    Cached raw to data/nfl_cache/sleeper_proj_<season>.json (gitignored)."""
    path = CACHE / f"sleeper_proj_{season}.json"
    if not path.exists():
        import requests
        raw = {}
        for w in WEEKS:
            r = requests.get(f"https://api.sleeper.com/projections/nfl/{season}/{w}",
                             params={"season_type": "regular",
                                     "position[]": list(POSITIONS)}, timeout=30)
            r.raise_for_status()
            raw[str(w)] = [{"player_id": x["player_id"], "stats": x.get("stats") or {},
                            "updated_at": x.get("updated_at"), "date": x.get("date")}
                           for x in r.json()]
        path.write_text(json.dumps(raw))
    raw = json.loads(path.read_text())
    sl_to_gsis = {str(r["sleeper_id"]).split(".")[0]: r["gsis_id"]
                  for r in _load("ff_playerids.json") if r.get("sleeper_id") and r.get("gsis_id")}
    out = {}
    for w, lst in raw.items():
        for x in lst:
            g = sl_to_gsis.get(str(x["player_id"]))
            if g:
                # Sleeper stat keys are the scoring keys themselves.
                out[(season, int(w), g)] = float(sum(float(v or 0) * DEFAULT_SCORING[k]
                                                     for k, v in x["stats"].items() if k in DEFAULT_SCORING))
    return out


def load_ecr_sunday():
    """{(season, week, gsis): positional ECR rank value} from the dump's OP lists."""
    db = sqlite3.connect(FP_DB)
    return {(s, w, g): float(r) for s, w, g, r in db.execute(
        "SELECT season, week, gsis_id, rank_ecr FROM ecr_weekly WHERE list='OP' "
        "AND season IN (2024, 2025) AND gsis_id IS NOT NULL")}


def load_fpp():
    db = sqlite3.connect(FP_DB)
    out = {}
    for season, week, gsis, stats in db.execute(
            "SELECT season, week, gsis_id, stats FROM proj_weekly "
            "WHERE week BETWEEN 4 AND 18 AND season IN (2024, 2025) AND gsis_id IS NOT NULL"):
        out[(season, week, gsis)] = fp_points(json.loads(stats))
    return out


def metrics(y, p, rows):
    y, p = np.asarray(y, float), np.asarray(p, float)
    corr = float(np.corrcoef(p, y)[0, 1]) if p.std() > 0 and y.std() > 0 else 0.0
    by_week = defaultdict(list)
    for r, pi, yi in zip(rows, p, y):
        by_week[(r["season"], r["week"])].append((pi, yi))
    ok = tot = 0
    for wr in by_week.values():
        a = np.array(wr)
        dp = np.sign(a[:, 0][:, None] - a[:, 0][None, :])
        dy = np.sign(a[:, 1][:, None] - a[:, 1][None, :])
        iu = np.triu_indices(len(a), 1)
        dp, dy = dp[iu], dy[iu]
        m = dp != 0
        ok += int(np.sum((dp[m] > 0) == (dy[m] > 0)))
        tot += int(np.sum(m))
    return {"mae": float(np.mean(np.abs(p - y))), "corr": corr,
            "pairwise": ok / tot if tot else 0.0, "bias": float(np.mean(p - y)), "n": int(len(y))}


def paired_t(y, base, arm):
    d = np.abs(np.asarray(base) - y) - np.abs(np.asarray(arm) - y)  # >0 = arm better
    sd = d.std(ddof=1)
    return float(d.mean() / (sd / math.sqrt(len(d)))) if sd > 0 else 0.0, float(d.mean())


def ecr_to_points(train, key="ecr"):
    """Per-position pts = a + b*log(ecr) least squares on train rows."""
    fit = {}
    for pos in MARKET_POS:
        tr = [r for r in train if r["position"] == pos and r[key]]
        X = np.column_stack([np.ones(len(tr)), np.log([r[key] for r in tr])])
        coef, *_ = np.linalg.lstsq(X, np.array([r["actual"] for r in tr]), rcond=None)
        fit[pos] = coef.tolist()
    return fit


def market_value(r, arm, ecr_fit):
    ecr_pts = (ecr_fit[r["position"]][0] + ecr_fit[r["position"]][1] * math.log(r["ecr"])
               if r["ecr"] else None)
    if arm == "ECR":
        return [ecr_pts] if ecr_pts is not None else None
    if arm == "FPP":
        return [r["fpp"]] if r["fpp"] is not None else None
    if arm == "SLP":
        return [r["slp"]] if r["slp"] is not None else None
    if arm == "ECRSUN":
        f = ecr_fit["_sun"][r["position"]]
        return [f[0] + f[1] * math.log(r["ecrsun"])] if r["ecrsun"] else None
    if arm == "FPP+ECR":
        return [r["fpp"], ecr_pts] if r["fpp"] is not None and ecr_pts is not None else None
    raise ValueError(arm)


def fit_arm(train, arm, form, ecr_fit):
    if form == "wp":
        tr = [(r, market_value(r, arm, ecr_fit)) for r in train if r["position"] in MARKET_POS]
        tr = [(r, mv) for r, mv in tr if mv is not None]
        y = np.array([r["actual"] for r, _ in tr])
        model = np.array([r["model"] for r, _ in tr])
        mkt = np.array([np.mean(mv) for _, mv in tr])
        w = W_GRID[int(np.argmin([np.mean(np.abs(w * model + (1 - w) * mkt - y)) for w in W_GRID]))]
        return {pos: w for pos in MARKET_POS}
    params = {}
    for pos in MARKET_POS:
        tr = [(r, market_value(r, arm, ecr_fit)) for r in train if r["position"] == pos]
        tr = [(r, mv) for r, mv in tr if mv is not None]
        y = np.array([r["actual"] for r, _ in tr])
        model = np.array([r["model"] for r, _ in tr])
        mkt = np.array([mv for _, mv in tr])
        if form == "w":
            mkt_mean = mkt.mean(axis=1)  # FPP+ECR convex: equal-weight market average
            maes = [np.mean(np.abs(w * model + (1 - w) * mkt_mean - y)) for w in W_GRID]
            params[pos] = W_GRID[int(np.argmin(maes))]
        else:
            X = np.column_stack([np.ones(len(y)), model, mkt])
            params[pos] = np.linalg.lstsq(X, y, rcond=None)[0].tolist()
    return params


def apply_arm(rows, arm, form, params, ecr_fit):
    out, used = [], 0
    for r in rows:
        mv = market_value(r, arm, ecr_fit) if r["position"] in MARKET_POS else None
        if mv is None:
            out.append(r["model"])
            continue
        used += 1
        p = params[r["position"]]
        if form in ("w", "wp"):
            out.append(p * r["model"] + (1 - p) * float(np.mean(mv)))
        else:
            out.append(p[0] + p[1] * r["model"] + sum(c * v for c, v in zip(p[2:], mv)))
    return out, used


def main():
    arch = _load_archive_weekly()
    fpid_to_gsis = {str(r["fantasypros_id"]).split(".")[0]: r["gsis_id"]
                    for r in _load("ff_playerids.json") if r.get("fantasypros_id") and r.get("gsis_id")}
    fpp = load_fpp()
    slp = {k: v for s in SEASONS for k, v in load_sleeper(s).items()}
    ecrsun = load_ecr_sunday()
    print(f"[blend] loaded fpp={len(fpp)} slp={len(slp)} ecrsun={len(ecrsun)}", flush=True)
    rows = {s: build_rows(s, arch, fpid_to_gsis, fpp, slp, ecrsun) for s in SEASONS}

    allrows = rows[2024] + rows[2025]
    base_all = metrics([r["actual"] for r in allrows], [r["model"] for r in allrows], allrows)
    print(f"[blend] BASE 2024-25 wk4-18: MAE {base_all['mae']:.4f} corr {base_all['corr']:.4f} "
          f"pw {base_all['pairwise']:.4f} n={base_all['n']} (freeze {FREEZE})", flush=True)
    cov = {s: {k: sum(1 for r in rows[s] if r["position"] in MARKET_POS and r[k] is not None) /
                  max(1, sum(1 for r in rows[s] if r["position"] in MARKET_POS)) for k in ("ecr", "ecrsun", "slp", "fpp")}
           for s in SEASONS}
    print(f"[blend] market coverage of QB/RB/WR/TE rows: {cov}", flush=True)

    # Leak check: a market source re-written after kickoff would correlate
    # with actuals far above any honest projection (~0.6-0.7). Common rows only.
    common = [r for r in allrows if r["slp"] is not None and r["fpp"] is not None]
    yc = [r["actual"] for r in common]
    leak = {k: float(np.corrcoef([r[k] for r in common], yc)[0, 1]) for k in ("model", "slp", "fpp")}
    print(f"[blend] raw corr vs actual on {len(common)} common rows: {leak}", flush=True)

    results = {"freeze": FREEZE, "base_2024_2025": base_all, "coverage": cov,
               "raw_corr_common_rows": leak, "folds": {}}
    verdict = defaultdict(list)
    for train_s, test_s in ((2024, 2025), (2025, 2024)):
        train, test = rows[train_s], rows[test_s]
        ecr_fit = {**ecr_to_points(train), "_sun": ecr_to_points(train, "ecrsun")}
        y = np.array([r["actual"] for r in test])
        base = [r["model"] for r in test]
        fold = {"ecr_fit": ecr_fit, "BASE": metrics(y, base, test), "arms": {}}
        mb = fold["BASE"]
        print(f"\n[blend] fit {train_s} -> test {test_s}: BASE MAE {mb['mae']:.4f} "
              f"corr {mb['corr']:.4f} pw {mb['pairwise']:.4f} n={mb['n']}", flush=True)
        for arm in ("ECR", "ECRSUN", "SLP", "FPP", "FPP+ECR"):
            for form in ("w", "wp", "ols"):
                params = fit_arm(train, arm, form, ecr_fit)
                pred, used = apply_arm(test, arm, form, params, ecr_fit)
                m = metrics(y, pred, test)
                t, dmean = paired_t(y, base, pred)
                pos_mae = {pos: [float(np.mean(np.abs(np.array([pr for pr, r in zip(pred, test) if r["position"] == pos]) -
                                                     np.array([r["actual"] for r in test if r["position"] == pos])))),
                                 float(np.mean(np.abs(np.array([r["model"] for r in test if r["position"] == pos]) -
                                                      np.array([r["actual"] for r in test if r["position"] == pos]))))]
                           for pos in POSITIONS}
                passed = (m["mae"] < mb["mae"] and t >= T_GATE and m["corr"] >= mb["corr"]
                          and m["pairwise"] >= mb["pairwise"])
                verdict[f"{arm}/{form}"].append(passed)
                fold["arms"][f"{arm}/{form}"] = {**m, "paired_t": t, "mean_abs_err_gain": dmean,
                                                 "rows_blended": used, "params": params,
                                                 "pos_mae_arm_vs_base": pos_mae, "pass": passed}
                print(f"[blend]   {arm:8s}/{form:3s} MAE {m['mae']:.4f} ({m['mae'] - mb['mae']:+.4f}) "
                      f"corr {m['corr']:.4f} pw {m['pairwise']:.4f} bias {m['bias']:+.3f} "
                      f"t={t:.2f} blended={used} {'PASS' if passed else 'fail'}", flush=True)
        results["folds"][f"{train_s}->{test_s}"] = fold
    results["verdict"] = {k: ("PASS both holdouts" if all(v) else "FAIL") for k, v in verdict.items()}
    print("\n[blend] verdict:", json.dumps(results["verdict"], indent=1))
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(results, indent=1))
    print(f"[blend] wrote {OUT_JSON}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
