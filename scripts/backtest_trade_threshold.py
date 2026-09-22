#!/usr/bin/env python3
"""Threshold recalibration for the trade slot-uplift fold (slot plan, Phase 4).

Synthetic trades on the 2025 holdout: projections as-of week W via
production-verbatim build_weekly_projections (no reimplementation), actual
ROS from fantasy_points_ppr sums weeks W..18. A simulated 12-team snake
league (rank-drafted by projection, seeded) splits the pool into rostered
vs free agents — mirroring the replacement-level boundary. Synthetic
packages (1v1/2v1/2v2/3v2) from random roster pairs grade two variants:

  baseline : evaluate_trade winner/diff (slot fields informational only)
  fold     : diff_fold = base_diff + uplift_a - uplift_b, same thresholds

Actual outcome uses model-pick waiver fill (the actual ROS of the waiver
player the MODEL named at week W, not the hindsight-best free agent —
scoring hindsight-best would be an unfillable upper bound inflating fold
accuracy). The calibration section compares predicted uplift against this
model-pick actual directly.

Report-only: never flips production behavior (the shadow gate owns
promotion). Promote iff fold ternary accuracy beats baseline by >2 SE.

Sweep thresholds {3, 5, 8, 10} on ternary verdicts (A wins / Fair / B wins)
plus threshold-independent MAE(pred_diff, actual_diff) and uplift
calibration. Writes data/ml/backtest_trade_threshold_results.json.

Fully offline: stats_2025/schedule_2025 (+stats_2024 prior) from
data/nfl_cache/ (present). Seeded throughout (random.Random(seed);
PYTHONHASHSEED=0 for set-order determinism).
"""
import argparse
import json
import math
import os
import random
import sys
from pathlib import Path

os.environ.setdefault("SLEEPER_LEAGUE_ID", "test")

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from ffanalytics.stat_projector import build_weekly_projections  # noqa: E402
from ffanalytics.scoring import DEFAULT_SCORING  # noqa: E402
from ffanalytics.decision import evaluate_trade  # noqa: E402
from ffanalytics.adapters.schedule import get_schedule  # noqa: E402
from ffanalytics.adapters.nflverse import (  # noqa: E402
    get_weekly_player_stats as _get_weekly_player_stats,
)

ROSTER_POSITIONS = ["QB", "RB", "RB", "WR", "WR", "WR", "TE", "FLEX", "K",
                    "BN", "BN", "BN", "BN", "BN"]
SKILL_POS = {"QB", "RB", "WR", "TE", "K"}
FLEX_OK = {"RB", "WR", "TE"}
THRESHOLDS = (3.0, 5.0, 8.0, 10.0)
SHAPES = ((1, 1), (2, 1), (2, 2), (3, 2))


def _load_stats(cache_name, season):
    import json as _json
    path = REPO_ROOT / "data" / "nfl_cache" / cache_name
    rows = _json.loads(path.read_text())
    return [r for r in rows if r.get("season") == season]


def _actual_ros(actual_by_pid_week, pid, week_lo, week_hi=18):
    return round(sum(
        float(actual_by_pid_week.get((pid, w), 0.0))
        for w in range(week_lo, week_hi + 1)), 2)


def _verdict(diff, threshold):
    if abs(diff) < threshold:
        return "Fair"
    return "A" if diff > 0 else "B"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", type=int, default=2025)
    ap.add_argument("--week", type=int, default=8)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--trades-per-shape", type=int, default=100)
    ap.add_argument("--out", default="data/ml/backtest_trade_threshold_results.json")
    args = ap.parse_args()
    rng = random.Random(args.seed)
    S, W = args.season, args.week

    stats = _load_stats("stats_2025.json", S) if S == 2025 else _get_weekly_player_stats(S)
    prior = _load_stats("stats_2024.json", 2024) if S == 2025 else []
    sched = get_schedule(S)
    hist = [r for r in stats
            if r.get("season_type") == "REG" and (r.get("week") or 0) < W]
    projs = build_weekly_projections(hist, sched, W, DEFAULT_SCORING,
                                     prior_season_stats=prior or None)
    pool = [p for p in projs
            if (p.get("position") or "").upper() in SKILL_POS
            and float(p.get("projected_points") or 0) > 0]
    if len(pool) < 200:
        print(f"ABORT: pool too small ({len(pool)}); need >= 200 for a 12-team draft")
        return 2
    pool.sort(key=lambda p: float(p["projected_points"]), reverse=True)

    # Simulated 12-team snake draft by projection rank (mirrors real drafts).
    teams = [[] for _ in range(12)]
    for i, p in enumerate(pool[:168]):
        teams[i % 12 if (i // 12) % 2 == 0 else 11 - (i % 12)].append(p)
    rostered_ids = {str(p.get("player_id")) for t in teams for p in t}
    fa_pool = [p for p in pool if str(p.get("player_id")) not in rostered_ids]

    # Actual ROS per player (PPR sums, weeks W..18).
    actual_wk = {}
    for r in stats:
        if r.get("season_type") != "REG":
            continue
        w = r.get("week") or 0
        if w < W or w > 18:
            continue
        try:
            v = float(r.get("fantasy_points_ppr") or 0)
        except (TypeError, ValueError):
            continue
        if v:
            actual_wk[(str(r.get("player_id")), w)] = v
    actual_ros = {}
    for p in pool:
        pid = str(p.get("player_id"))
        actual_ros[pid] = _actual_ros(actual_wk, pid, W)

    def as_dict(p):
        pid = str(p.get("player_id"))
        return {"player_id": pid,
                "player_name": p.get("player_display_name") or f"Player {pid}",
                "position": (p.get("position") or "UNK").upper(),
                "position_group": (p.get("position") or "UNK").upper(),
                "projected_points": float(p.get("projected_points") or 0)}

    league_players = [as_dict(p) for p in pool]
    rostered_list = sorted(rostered_ids)
    # why model-pick (not hindsight-best) waiver actuals: scoring the slot
    # with the best ACTUAL free agent is an unfillable upper bound that
    # inflates fold accuracy. The honest grade fills with the waiver player
    # the MODEL picked at week W (slot_waiver names) and scores ITS actuals.
    name_to_pid = {}
    for p in pool:
        nm = p.get("player_display_name") or f"Player {p.get('player_id')}"
        name_to_pid.setdefault(nm, str(p.get("player_id")))

    results = {"season": S, "week": W, "seed": args.seed,
               "n_pool": len(pool), "shapes": {}}
    weeks_left = max(1, 18 - W + 1)
    slot_misses = 0
    for na, nb in SHAPES:
        rows = []
        for _ in range(args.trades_per_shape):
            ia, ib = rng.sample(range(12), 2)
            if len(teams[ia]) < na or len(teams[ib]) < nb:
                continue
            pkg_a = rng.sample(teams[ia], na)
            pkg_b = rng.sample(teams[ib], nb)
            pkg_a_d = [as_dict(p) for p in pkg_a]
            pkg_b_d = [as_dict(p) for p in pkg_b]
            # Base: PACKAGE-scoped VOR diff (coherent with package actuals).
            res_base = evaluate_trade(
                pkg_a_d, pkg_b_d, {}, ROSTER_POSITIONS,
                current_week=W, all_league_players=league_players)
            base_diff = (res_base["team_a_ros_vbd"]
                         - res_base["team_b_ros_vbd"])
            # Slot context: full rosters + traded ids (lineup needs the
            # whole roster; packages alone would fake empty-slot holes).
            res_slot = evaluate_trade(
                [as_dict(p) for p in teams[ia]],
                [as_dict(p) for p in teams[ib]], {}, ROSTER_POSITIONS,
                current_week=W,
                all_league_players=league_players,
                traded_a_ids=[str(p.get("player_id")) for p in pkg_a],
                traded_b_ids=[str(p.get("player_id")) for p in pkg_b],
                rostered_ids=rostered_list)
            uplift = res_slot["slot_uplift_a"] - res_slot["slot_uplift_b"]
            fold_diff = base_diff + uplift
            # Raw-space predicted package diff (diagnostic magnitude metric;
            # VOR-weighted base vs raw actuals is a unit mismatch for MAE).
            raw_pred = (sum(p["projected_points"] for p in pkg_b_d)
                        - sum(p["projected_points"] for p in pkg_a_d)) * weeks_left
            act_pkg_a = sum(actual_ros.get(str(p.get("player_id")), 0.0) for p in pkg_a)
            act_pkg_b = sum(actual_ros.get(str(p.get("player_id")), 0.0) for p in pkg_b)
            act_a, act_b = act_pkg_a, act_pkg_b
            # Model-pick waiver fill: actual ROS of the player(s) the model
            # named in slot_waiver (not the hindsight-best FA). Unmapped
            # names (should not happen) count as misses, reported below.
            waiver_names = (res_slot["slot_waiver_a"] + res_slot["slot_waiver_b"])
            waiver_pids = [name_to_pid[nm] for nm in waiver_names
                           if nm in name_to_pid]
            slot_misses += len(waiver_names) - len(waiver_pids)
            gained_a = max(0, na - nb)
            for pid in waiver_pids[:gained_a]:
                act_a += actual_ros.get(pid, 0.0)
            for pid in waiver_pids[gained_a:gained_a + max(0, nb - na)]:
                act_b += actual_ros.get(pid, 0.0)
            rows.append({"base": base_diff, "fold": fold_diff,
                         "raw": raw_pred,
                         "actual": round(act_a - act_b, 2),
                         "actual_pkg": round(act_pkg_a - act_pkg_b, 2),
                         "uplift_pred": (res_slot["slot_uplift_a"]
                                         - res_slot["slot_uplift_b"])})
        shape_out = {"n": len(rows), "thresholds": {},
                     "mae_base": None, "mae_fold": None,
                     "uplift_mae": None, "uplift_bias": None}
        if rows:
            # why raw-space MAE (not VOR-vs-actual): base/fold diffs live in
            # weighted-VOR space while actuals are raw PPR sums — MAE across
            # those units is meaningless. raw_pred is the same packages in
            # raw points; fold magnitude adds the (raw-space) uplift.
            shape_out["mae_base"] = round(
                sum(abs(r["raw"] - r["actual"]) for r in rows) / len(rows), 3)
            shape_out["mae_fold"] = round(
                sum(abs(r["raw"] + r["uplift_pred"] - r["actual"])
                    for r in rows) / len(rows), 3)
            # Uplift calibration, isolated from base-model error: actual slot
            # edge = (actual with waiver fill) - (actual packages only);
            # the fold predicts edge = uplift_pred.
            errs = [r["uplift_pred"] - (r["actual"] - r["actual_pkg"])
                    for r in rows if abs(r["uplift_pred"]) > 0]
            if errs:
                shape_out["uplift_mae"] = round(
                    sum(abs(e) for e in errs) / len(errs), 3)
                shape_out["uplift_bias"] = round(
                    sum(errs) / len(errs), 3)
                shape_out["uplift_n"] = len(errs)
            for t in THRESHOLDS:
                cb = sum(1 for r in rows
                         if _verdict(r["base"], t) == _verdict(r["actual"], t))
                cf = sum(1 for r in rows
                         if _verdict(r["fold"], t) == _verdict(r["actual"], t))
                n = len(rows)
                pb, pf = cb / n, cf / n
                se = math.sqrt(max(pb * (1 - pb), pf * (1 - pf)) / n)
                shape_out["thresholds"][str(t)] = {
                    "acc_base": round(pb, 4), "acc_fold": round(pf, 4),
                    "se": round(se, 4),
                    "promote": bool((pf - pb) > 2 * se and se > 0),
                }
        results["shapes"][f"{na}v{nb}"] = shape_out

    out_path = REPO_ROOT / args.out
    out_path.parent.mkdir(parents=True, exist_ok=True)
    results["slot_name_misses"] = slot_misses
    out_path.write_text(json.dumps(results, indent=2))
    print(json.dumps(results, indent=2))
    prom = [(s, t, v) for s, sd in results["shapes"].items()
            for t, v in sd["thresholds"].items() if v["promote"]]
    if prom:
        print("PROMOTE:", prom)
    else:
        print("NO PROMOTION: fold does not beat baseline by >2 SE anywhere; "
              "gate stays closed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
