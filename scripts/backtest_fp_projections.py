#!/usr/bin/env python3
"""FantasyPros market-projection accuracy backtest (fp-projection-backtest spec).

Measures point-level accuracy of FantasyPros' own weekly market projection
(data/fantasypros_dump/fp.sqlite, proj_weekly table) against stat_projector.py
on the same production gate. backtest_ecr.py already measured rank agreement;
this measures point accuracy with FP's projected stat line scored under OUR
scoring rules (not FP's own points/points_ppr fields, which may use a
different convention).

PRE-REGISTERED GATE (read before touching, no changes after seeing results):
  Production freeze baseline (true scoring, 2024-2025 weeks 4-18, n=10,351):
  MAE=4.563, Corr=0.648, Pairwise=74.1% (stat_projector.py header).
  PASS requires fp-alone OR the locked ensemble to beat ALL THREE numbers on
  HOLDOUT (2023-2025 pooled), not combined/in-sample. Ensemble weight w
  (w*fp + (1-w)*stat) is grid-searched 0.0->1.0 step 0.05 on TRAIN-ONLY
  (2020-2022 pooled), then locked and evaluated once on holdout — same
  nested protocol as backtest_ml.py.

Scope: seasons 2020-2025 (stats_{season} + stats_{season-1} both cached
locally), REG weeks 4-18, all-universe (DNPs included, matches
backtest_ecr.py). 2026 partial season is diagnostic only, never gate-eligible.
QB/RB/WR/TE only — the dump has no K/DST weekly rows for 2020-2025 (only
week-0 preseason K rows exist; quota ran out before K/DST weekly in most
years). Pre-2020 seasons excluded: nflverse box stats to feed stat_projector
for those years aren't cached (separate task if ever wanted).

Scoring parity: FantasyPros proj_weekly.stats JSON is key-mapped to
scoring.py's canonical keys and scored via calculate_fantasy_points with
DEFAULT_SCORING — identical scoring path as stat_projector's output and the
nflverse actual. Known approximation: FP's "fumbles" is total fumbles, not
fumbles LOST; mapped to fum_lost as a documented upward-biased proxy (a real
fumble-lost signal doesn't exist in this feed). A sanity check compares the
mapped score against FP's own points_ppr for a sample before trusting results.

Writes data/ml/backtest_fp_projections_results.json.
"""
import json
import math
import os
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

os.environ.setdefault("SLEEPER_LEAGUE_ID", "test")

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from ffanalytics.stat_projector import project_player_stats, build_game_context  # noqa: E402
from ffanalytics.scoring import calculate_fantasy_points, DEFAULT_SCORING  # noqa: E402

CACHE = REPO_ROOT / "data" / "nfl_cache"
FP_DB = REPO_ROOT / "data" / "fantasypros_dump" / "fp.sqlite"
OUT_JSON = REPO_ROOT / "data" / "ml" / "backtest_fp_projections_results.json"
BASELINE = {"mae": 4.563, "corr": 0.648, "pairwise": 0.741}
POSITIONS = ("QB", "RB", "WR", "TE")  # no K/DST weekly rows in the dump for 2020-2025
TRAIN_SEASONS = (2020, 2021, 2022)
HOLDOUT_SEASONS = (2023, 2024, 2025)

# FantasyPros proj_weekly.stats keys -> scoring.py canonical keys.
# "fumbles" is FP's total-fumbles field, not fumbles LOST — mapped to
# fum_lost as a documented upward-biased proxy (no lost-fumble signal in
# this feed); everything else is a direct rename.
FP_STAT_MAP = {
    "pass_yds": "pass_yd", "pass_tds": "pass_td", "pass_ints": "pass_int",
    "rush_yds": "rush_yd", "rush_tds": "rush_td",
    "rec_rec": "rec", "rec_yds": "rec_yd", "rec_tds": "rec_td",
    "fumbles": "fum_lost",
}


def _load_cache(name):
    with open(CACHE / name, encoding="utf-8") as f:
        return json.load(f)


def _map_fp_stats(stats: dict) -> dict:
    return {FP_STAT_MAP[k]: v for k, v in (stats or {}).items() if k in FP_STAT_MAP}


def _load_fp_proj(season):
    con = sqlite3.connect(FP_DB)
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    cur.execute(
        "select week, gsis_id, pos, points_ppr, stats from proj_weekly "
        "where season=? and week between 4 and 18 and pos in (?,?,?,?) "
        "and gsis_id is not null",
        (season, *POSITIONS),
    )
    out = {}
    for r in cur.fetchall():
        stats = json.loads(r["stats"]) if r["stats"] else {}
        out[(r["gsis_id"], r["week"])] = {
            "points_ppr": r["points_ppr"], "mapped_stats": _map_fp_stats(stats),
        }
    con.close()
    return out


def _season_rows(season):
    """Per player-week: stat_pts, fp_pts, actual_pts, position. All-universe."""
    stats_cur = [r for r in _load_cache(f"stats_{season}.json")
                 if r.get("season_type", "REG") == "REG"]
    stats_prior = [r for r in _load_cache(f"stats_{season - 1}.json")
                   if r.get("season_type", "REG") == "REG"]
    sched = _load_cache(f"schedule_{season}.json")
    fp_proj = _load_fp_proj(season)

    game_ctx = build_game_context(sched)
    hist = defaultdict(list)
    for r in stats_cur:
        if r.get("position") in POSITIONS:
            hist[str(r.get("player_id"))].append(r)
    for v in hist.values():
        v.sort(key=lambda x: x.get("week", 0))
    prior = defaultdict(list)
    for r in stats_prior:
        if r.get("position") in POSITIONS:
            prior[str(r.get("player_id"))].append(r)
    team_of, pos_of = {}, {}
    for pid, rows in hist.items():
        teams = [x.get("team") for x in rows if x.get("team")]
        if teams:
            team_of[pid] = max(sorted(set(teams)), key=teams.count)
        pos_of[pid] = rows[0].get("position")
    for r in stats_prior:
        pid = str(r.get("player_id"))
        if r.get("position") in POSITIONS:
            pos_of.setdefault(pid, r.get("position"))
            if pid not in team_of and r.get("team"):
                team_of[pid] = r.get("team")
    played_tw = set()
    for g in sched:
        if g.get("game_type") != "REG" or not g.get("week"):
            continue
        played_tw.add((g.get("home_team"), g.get("week")))
        played_tw.add((g.get("away_team"), g.get("week")))
    by_pw = {(str(r.get("player_id")), r.get("week")): r for r in stats_cur
             if r.get("position") in POSITIONS}
    prior_pids = {str(r.get("player_id")) for r in stats_prior
                  if r.get("position") in POSITIONS}

    rows = []
    sanity = []  # (mapped_fp_score, fp_points_ppr) for validity check
    for week in range(4, 19):
        cur_pids = {pid for pid, hr in hist.items()
                    if any(x.get("week", 0) < week for x in hr)}
        for pid in sorted(cur_pids if cur_pids else prior_pids):
            if (team_of.get(pid), week) not in played_tw:
                continue
            fp = fp_proj.get((pid, week))
            if fp is None:
                continue  # common-players rule: only score where FP has a projection
            pos = pos_of.get(pid)
            h = [x for x in hist.get(pid, []) if x.get("week", 0) < week]
            ctx = game_ctx.get((team_of.get(pid), week)) or {}
            try:
                proj = project_player_stats(
                    player_history=h, position=pos,
                    prior_season_stats=prior.get(pid, []),
                    implied_total=ctx.get("implied_total", 0) or 0,
                    wind_mph=ctx.get("wind", 0) or 0, temp_f=ctx.get("temp"))
                stat_pts = float(calculate_fantasy_points(proj, DEFAULT_SCORING))
            except Exception:
                stat_pts = 0.0
            fp_pts = float(calculate_fantasy_points(fp["mapped_stats"], DEFAULT_SCORING))
            real = by_pw.get((pid, week))
            try:
                actual_pts = float(calculate_fantasy_points(real, DEFAULT_SCORING)) if real else 0.0
            except Exception:
                actual_pts = 0.0
            rows.append({"season": season, "week": week, "position": pos,
                         "stat_pts": stat_pts, "fp_pts": fp_pts, "actual_pts": actual_pts})
            if fp["points_ppr"] is not None:
                sanity.append((fp_pts, fp["points_ppr"]))
    return rows, sanity


def _evaluate(rows, pred_key):
    """MAE / corr / pairwise, methodology mirrors backtest_ml.py's _evaluate."""
    if not rows:
        return {"mae": None, "corr": None, "pairwise": None, "n": 0, "pos_mae": {}}
    y_pred = np.array([r[pred_key] for r in rows], dtype=float)
    y_true = np.array([r["actual_pts"] for r in rows], dtype=float)
    mae = float(np.mean(np.abs(y_pred - y_true)))
    pm, am = float(np.mean(y_pred)), float(np.mean(y_true))
    ps, ast = float(np.std(y_pred)), float(np.std(y_true))
    cov = float(np.mean((y_pred - pm) * (y_true - am)))
    corr = float(cov / (ps * ast)) if ps > 0 and ast > 0 else 0.0
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
    pos_errors = defaultdict(list)
    for r, p, a in zip(rows, y_pred, y_true):
        pos_errors[r["position"]].append(abs(float(p) - float(a)))
    pos_mae = {p: float(np.mean(e)) for p, e in pos_errors.items()}
    return {"mae": mae, "corr": corr, "pairwise": pairwise, "n": len(rows), "pos_mae": pos_mae}


def _paired_t(a, b):
    """Paired t-test on two equal-length error arrays (a - b)."""
    d = np.array(a) - np.array(b)
    n = len(d)
    if n < 2:
        return None, None
    mean_d, sd_d = float(np.mean(d)), float(np.std(d, ddof=1))
    if sd_d == 0:
        return 0.0, 1.0
    t = mean_d / (sd_d / math.sqrt(n))
    # two-sided p-value via normal approx (n is large in every sample here)
    p = 2 * (1 - 0.5 * (1 + math.erf(abs(t) / math.sqrt(2))))
    return float(t), float(p)


def main():
    all_rows = []
    all_sanity = []
    results = {"baseline": BASELINE, "positions": list(POSITIONS)}
    for season in (2020, 2021, 2022, 2023, 2024, 2025):
        rows, sanity = _season_rows(season)
        all_rows.extend(rows)
        all_sanity.extend(sanity)
        stat_m = _evaluate(rows, "stat_pts")
        fp_m = _evaluate(rows, "fp_pts")
        results[f"season_{season}"] = {"stat": stat_m, "fp": fp_m}
        print(f"[fpback:{season}] n={stat_m['n']} "
              f"stat(mae={stat_m['mae']:.3f} corr={stat_m['corr']:.3f} pw={stat_m['pairwise']:.3f}) "
              f"fp(mae={fp_m['mae']:.3f} corr={fp_m['corr']:.3f} pw={fp_m['pairwise']:.3f})")

    # sanity check: does the mapped-stats FP score track FP's own points_ppr?
    if all_sanity:
        a = np.array([s[0] for s in all_sanity])
        b = np.array([s[1] for s in all_sanity])
        sanity_corr = float(np.corrcoef(a, b)[0, 1]) if len(a) > 1 else None
        sanity_mad = float(np.mean(np.abs(a - b)))
        results["sanity_check"] = {"n": len(all_sanity), "corr_vs_points_ppr": sanity_corr,
                                    "mean_abs_diff": sanity_mad}
        print(f"[fpback] sanity: mapped-score vs FP points_ppr corr={sanity_corr:.4f} "
              f"mean|diff|={sanity_mad:.3f} (n={len(all_sanity)})")

    train_rows = [r for r in all_rows if r["season"] in TRAIN_SEASONS]
    holdout_rows = [r for r in all_rows if r["season"] in HOLDOUT_SEASONS]

    # grid w on TRAIN only, lock, evaluate once on HOLDOUT
    best_w, best_mae = 0.0, float("inf")
    for w in np.arange(0.0, 1.01, 0.05):
        pred = [w * r["fp_pts"] + (1 - w) * r["stat_pts"] for r in train_rows]
        actual = [r["actual_pts"] for r in train_rows]
        mae = float(np.mean(np.abs(np.array(pred) - np.array(actual)))) if train_rows else float("inf")
        if mae < best_mae:
            best_mae, best_w = mae, float(w)
    print(f"[fpback] locked ensemble weight w={best_w:.2f} (train MAE {best_mae:.4f})")

    for r in holdout_rows:
        r["ens_pts"] = best_w * r["fp_pts"] + (1 - best_w) * r["stat_pts"]
    stat_hold = _evaluate(holdout_rows, "stat_pts")
    fp_hold = _evaluate(holdout_rows, "fp_pts")
    ens_hold = _evaluate(holdout_rows, "ens_pts")

    def _passes(m):
        return (m["mae"] is not None and m["mae"] < BASELINE["mae"]
                and m["corr"] > BASELINE["corr"] and m["pairwise"] > BASELINE["pairwise"])

    fp_pass, ens_pass = _passes(fp_hold), _passes(ens_hold)
    t_stat, p_val = _paired_t(
        [abs(r["stat_pts"] - r["actual_pts"]) for r in holdout_rows],
        [abs(r["fp_pts"] - r["actual_pts"]) for r in holdout_rows],
    )
    print(f"[fpback] HOLDOUT (2023-2025) n={stat_hold['n']} "
          f"stat(mae={stat_hold['mae']:.3f} corr={stat_hold['corr']:.3f} pw={stat_hold['pairwise']:.3f}) "
          f"fp(mae={fp_hold['mae']:.3f} corr={fp_hold['corr']:.3f} pw={fp_hold['pairwise']:.3f}) "
          f"ens_w{best_w:.2f}(mae={ens_hold['mae']:.3f} corr={ens_hold['corr']:.3f} pw={ens_hold['pairwise']:.3f})")
    print(f"[fpback] paired-t (stat AE vs fp AE) t={t_stat:.3f} p={p_val:.4f}")
    print(f"[fpback] GATE: fp-alone {'PASS' if fp_pass else 'FAIL'}, "
          f"ensemble(w={best_w:.2f}) {'PASS' if ens_pass else 'FAIL'} vs baseline {BASELINE}")

    results["holdout"] = {"stat": stat_hold, "fp": fp_hold,
                          "ensemble": {"w": best_w, **ens_hold},
                          "paired_t": {"t": t_stat, "p": p_val},
                          "gate": {"fp_alone_pass": fp_pass, "ensemble_pass": ens_pass}}

    # 2026 partial season, diagnostic only
    try:
        rows26, _ = _season_rows(2026)
    except FileNotFoundError:
        rows26 = []
    if rows26:
        stat26 = _evaluate(rows26, "stat_pts")
        fp26 = _evaluate(rows26, "fp_pts")
        results["season_2026_diagnostic"] = {"stat": stat26, "fp": fp26}
        print(f"[fpback:2026-diag] n={stat26['n']} "
              f"stat(mae={stat26['mae']:.3f}) fp(mae={fp26['mae']:.3f}) — diagnostic only, not gate-eligible")

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=1)
    print(f"[fpback] wrote {OUT_JSON}")


if __name__ == "__main__":
    main()
