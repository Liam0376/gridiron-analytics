#!/usr/bin/env python3
"""Does stat_projector's existing out-zero rule close the FP all-universe gap?

backtest_fp_projections.py (this session, commit 99b97ca) measured a large
FP edge on the all-universe holdout: stat MAE=4.200 vs FP MAE=3.386
(2023-2025, n=18,698). But its model call reuses backtest_ecr.py's
_model_week-style pipeline, which is explicitly documented "no-out, no
flags" (backtest_ecr.py:24) — it never zeroes confirmed-Out/IR players.
Production stat_projector DOES have this (api.py:1559, is_out=
_is_unavailable(injury_status)). FP's projection reflects real-world
outcomes for injured players inherently (a human wrote the consensus
knowing who's out); an uncorrected model doesn't. That's a plausible
apples-to-oranges source for most of the measured gap.

PRE-REGISTERED (before running, no goalpost-moving after seeing results):
  Take backtest_fp_projections.py's exact all-universe holdout rows
  (2023-2025, weeks 4-18, QB/RB/WR/TE), pass is_out=True into
  project_player_stats for any player-week whose nflverse weekly injury
  report_status is in _UNAVAILABLE (mirrors api.py's
  _UNAVAILABLE_STATUSES exactly, per this repo's isolation convention of
  mirroring rather than importing across module boundaries — see
  backtest_snap_share.py's docstring). Leave FP's projection and the
  actual/ground-truth untouched. Report MAE/Corr/Pairwise for out-zero-
  corrected stat vs the original no-out stat vs FP, overall and per
  position, plus a paired-t (out-zero-corrected stat AE vs FP AE).
  This is a measurement, not a decision: report whatever comes out,
  don't retune anything afterward to make it look better.

Data: nflverse weekly injury reports via nflreadpy (free), cached at
data/nfl_cache/injuries_{season}.json (2020-2022 fetched this run,
2023-2026 pre-existing). player_id in stats_{season}.json already IS the
gsis_id format injuries use (confirmed: both "00-00xxxxx"), so the join
is direct, no crosswalk needed.

Writes data/ml/backtest_fp_outzero_results.json.
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
OUT_JSON = REPO_ROOT / "data" / "ml" / "backtest_fp_outzero_results.json"
# mirrors api.py's _UNAVAILABLE_STATUSES verbatim (isolation convention, not imported)
_UNAVAILABLE = {"out", "ir", "injured reserve", "pup", "nfi", "suspended", "na"}
BASELINE = {"mae": 4.563, "corr": 0.648, "pairwise": 0.741}
FP_BASELINE = {"mae": 3.386, "corr": 0.758, "pairwise": 0.798}  # backtest_fp_projections.py holdout, no-out stat
POSITIONS = ("QB", "RB", "WR", "TE")
HOLDOUT_SEASONS = (2023, 2024, 2025)

FP_STAT_MAP = {
    "pass_yds": "pass_yd", "pass_tds": "pass_td", "pass_ints": "pass_int",
    "rush_yds": "rush_yd", "rush_tds": "rush_td",
    "rec_rec": "rec", "rec_yds": "rec_yd", "rec_tds": "rec_td",
    "fumbles": "fum_lost",
}


def _load_cache(name):
    with open(CACHE / name, encoding="utf-8") as f:
        return json.load(f)


def _map_fp_stats(stats):
    return {FP_STAT_MAP[k]: v for k, v in (stats or {}).items() if k in FP_STAT_MAP}


def _load_fp_proj(season):
    con = sqlite3.connect(FP_DB)
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    cur.execute(
        "select week, gsis_id, pos, stats from proj_weekly "
        "where season=? and week between 4 and 18 and pos in (?,?,?,?) "
        "and gsis_id is not null",
        (season, *POSITIONS),
    )
    out = {}
    for r in cur.fetchall():
        stats = json.loads(r["stats"]) if r["stats"] else {}
        out[(r["gsis_id"], r["week"])] = _map_fp_stats(stats)
    con.close()
    return out


def _load_injury_out(season):
    """{(gsis_id, week): True} for confirmed-unavailable player-weeks."""
    rows = _load_cache(f"injuries_{season}.json")
    out = set()
    for r in rows:
        gid = str(r.get("gsis_id") or "")
        status = str(r.get("report_status") or "").strip().lower()
        if gid and status in _UNAVAILABLE:
            out.add((gid, r.get("week")))
    return out


def _season_rows(season):
    stats_cur = [r for r in _load_cache(f"stats_{season}.json")
                 if r.get("season_type", "REG") == "REG"]
    stats_prior = [r for r in _load_cache(f"stats_{season - 1}.json")
                   if r.get("season_type", "REG") == "REG"]
    sched = _load_cache(f"schedule_{season}.json")
    fp_proj = _load_fp_proj(season)
    inj_out = _load_injury_out(season)

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
    for week in range(4, 19):
        cur_pids = {pid for pid, hr in hist.items()
                    if any(x.get("week", 0) < week for x in hr)}
        for pid in sorted(cur_pids if cur_pids else prior_pids):
            if (team_of.get(pid), week) not in played_tw:
                continue
            fp_stats = fp_proj.get((pid, week))
            if fp_stats is None:
                continue  # common-players rule, matches backtest_fp_projections.py
            pos = pos_of.get(pid)
            h = [x for x in hist.get(pid, []) if x.get("week", 0) < week]
            ctx = game_ctx.get((team_of.get(pid), week)) or {}
            is_out = (pid, week) in inj_out
            try:
                proj_noout = project_player_stats(
                    player_history=h, position=pos,
                    prior_season_stats=prior.get(pid, []),
                    implied_total=ctx.get("implied_total", 0) or 0,
                    wind_mph=ctx.get("wind", 0) or 0, temp_f=ctx.get("temp"))
                stat_noout = float(calculate_fantasy_points(proj_noout, DEFAULT_SCORING))
                proj_oz = project_player_stats(
                    player_history=h, position=pos,
                    prior_season_stats=prior.get(pid, []),
                    implied_total=ctx.get("implied_total", 0) or 0,
                    wind_mph=ctx.get("wind", 0) or 0, temp_f=ctx.get("temp"),
                    is_out=is_out)
                stat_oz = float(calculate_fantasy_points(proj_oz, DEFAULT_SCORING))
            except Exception:
                stat_noout = stat_oz = 0.0
            fp_pts = float(calculate_fantasy_points(fp_stats, DEFAULT_SCORING))
            real = by_pw.get((pid, week))
            try:
                actual_pts = float(calculate_fantasy_points(real, DEFAULT_SCORING)) if real else 0.0
            except Exception:
                actual_pts = 0.0
            rows.append({"season": season, "week": week, "position": pos,
                         "player_id": pid, "is_out": is_out,
                         "stat_noout": stat_noout, "stat_outzero": stat_oz,
                         "fp_pts": fp_pts, "actual_pts": actual_pts})
    return rows


def _evaluate(rows, pred_key):
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
    all_rows = []
    for season in HOLDOUT_SEASONS:
        all_rows.extend(_season_rows(season))

    n_out = sum(1 for r in all_rows if r["is_out"])
    print(f"[fpoz] holdout rows n={len(all_rows)}, is_out flagged={n_out} "
          f"({100 * n_out / len(all_rows):.1f}%)")

    noout_m = _evaluate(all_rows, "stat_noout")
    oz_m = _evaluate(all_rows, "stat_outzero")
    fp_m = _evaluate(all_rows, "fp_pts")

    gap_noout = noout_m["mae"] - fp_m["mae"]
    gap_oz = oz_m["mae"] - fp_m["mae"]
    closed_pct = 100 * (1 - gap_oz / gap_noout) if gap_noout else None

    t_stat, p_val = _paired_t(
        [abs(r["stat_outzero"] - r["actual_pts"]) for r in all_rows],
        [abs(r["fp_pts"] - r["actual_pts"]) for r in all_rows],
    )

    print(f"[fpoz] no-out   stat: mae={noout_m['mae']:.3f} corr={noout_m['corr']:.3f} pw={noout_m['pairwise']:.3f}")
    print(f"[fpoz] out-zero stat: mae={oz_m['mae']:.3f} corr={oz_m['corr']:.3f} pw={oz_m['pairwise']:.3f}")
    print(f"[fpoz] fp:            mae={fp_m['mae']:.3f} corr={fp_m['corr']:.3f} pw={fp_m['pairwise']:.3f}")
    print(f"[fpoz] MAE gap: no-out {gap_noout:.3f} -> out-zero {gap_oz:.3f} "
          f"({closed_pct:.1f}% of gap closed)" if closed_pct is not None else "[fpoz] gap calc skipped (zero baseline gap)")
    print(f"[fpoz] paired-t (out-zero stat AE vs fp AE) t={t_stat:.3f} p={p_val:.4f}")
    print("[fpoz] per-position MAE (no-out / out-zero / fp):")
    for pos in POSITIONS:
        no_p = noout_m["pos_mae"].get(pos)
        oz_p = oz_m["pos_mae"].get(pos)
        fp_p = fp_m["pos_mae"].get(pos)
        if no_p is None:
            continue
        print(f"  {pos}: {no_p:.3f} / {oz_p:.3f} / {fp_p:.3f}")

    results = {
        "baseline_production": BASELINE,
        "fp_alone_reference_no_out_pipeline": FP_BASELINE,
        "n": len(all_rows), "n_flagged_out": n_out,
        "stat_no_out": noout_m, "stat_out_zero": oz_m, "fp": fp_m,
        "mae_gap_no_out": gap_noout, "mae_gap_out_zero": gap_oz,
        "pct_gap_closed": closed_pct,
        "paired_t_outzero_vs_fp": {"t": t_stat, "p": p_val},
    }
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=1)
    print(f"[fpoz] wrote {OUT_JSON}")


if __name__ == "__main__":
    main()
