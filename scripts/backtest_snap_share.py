#!/usr/bin/env python3
"""Snap-share scaling backtest (qb-snap-share plan, Task 2).

Compares production project_player_stats (share=1.0) against snap-scaled
QB variants on honest OOS 2025 holdout (REG weeks 4-18, QB/RB/WR/TE/K),
same nested-protocol discipline as scripts/backtest_stat_level.py: gate on
holdout vs the production freeze MAE 4.563 / Corr 0.648 / Pairwise 74.1%.

Depth proxy (documented skew): 2025 preseason depth charts don't exist
in-repo, so backtest ranks QBs by week-1 snap order; production will use
the depth CSV. Proxy noise mislabels roles against the variant, so this
backtest is conservative for the depth signal, not generous.

Fully offline after first fetch: data/nfl_cache/stats_{2024,2025}.json +
schedule_2025.json (present). Snaps/injuries 2025 are fetched once via
nflreadpy and cached under data/nfl_cache/ (gitignored) if absent.

Arms: BASE (share 1.0 everywhere) vs scales {0.03, 0.05, 0.10} x rules
{depth-only, depth + recent-max}. Non-QB rows are identical across arms
(scale applies to QB only, v1 scope). Injury override (rank-0 out ->
next-up 1.0) uses weekly report_status; same unavailable set as
src/ffanalytics/api.py:_UNAVAILABLE_STATUSES (mirrored, isolation: scripts
may read model code but the set will be canonicalized in config.py at
implementation time).
"""
import json
import os
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

os.environ.setdefault("SLEEPER_LEAGUE_ID", "test")

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from ffanalytics.stat_projector import project_player_stats, build_game_context
from ffanalytics.scoring import calculate_fantasy_points, DEFAULT_SCORING

FREEZE = {"mae": 4.563, "corr": 0.648, "pairwise": 0.741}
POSITIONS = ("QB", "RB", "WR", "TE", "K")
WEEKS = range(4, 19)
SCALES = (0.03, 0.05, 0.10)
# why mirror (not import): canonical home will be config.py at implementation
# time (Task 3); backtest must run against unmodified production code.
_UNAVAILABLE = {"out", "ir", "injured reserve", "pup", "nfi", "suspended", "na"}

CACHE = REPO_ROOT / "data" / "nfl_cache"
OUT_JSON = REPO_ROOT / "data" / "ml" / "backtest_snap_share_results.json"


def _load(name):
    with open(CACHE / name, encoding="utf-8") as f:
        return json.load(f)


def _ensure(name, fetch):
    path = CACHE / name
    if path.exists():
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    import nflreadpy as nfl
    rows = fetch(nfl)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(rows, f)
    print(f"[backtest_snap] cached {name} ({len(rows)} rows)")
    return rows


def _metrics(y_true, y_pred, rows):
    n = len(y_true)
    if n == 0:
        return {"mae": None, "corr": None, "pairwise": None, "bias": None, "n": 0}
    yt = np.array(y_true, dtype=float)
    yp = np.array(y_pred, dtype=float)
    mae = float(np.mean(np.abs(yp - yt)))
    bias = float(np.mean(yp - yt))
    ps, ast = float(np.std(yp)), float(np.std(yt))
    corr = float(np.mean((yp - np.mean(yp)) * (yt - np.mean(yt))) / (ps * ast)) if ps > 0 and ast > 0 else 0.0
    by_week = defaultdict(list)
    for r, p, a in zip(rows, yp, yt):
        by_week[(r.get("season"), r.get("week"))].append((float(p), float(a)))
    correct = total = 0
    for wr in by_week.values():
        for i in range(len(wr)):
            for j in range(i + 1, len(wr)):
                if wr[i][0] == wr[j][0]:
                    continue
                if (wr[i][0] > wr[j][0]) == (wr[i][1] > wr[j][1]):
                    correct += 1
                total += 1
    return {"mae": mae, "corr": corr,
            "pairwise": float(correct / total) if total else 0.0,
            "bias": bias, "n": n}


def main():
    stats24 = [r for r in _load("stats_2024.json") if r.get("season_type", "REG") == "REG"]
    stats25 = [r for r in _load("stats_2025.json") if r.get("season_type", "REG") == "REG"]
    sched = _load("schedule_2025.json")
    snaps = _ensure("snaps_2025.json",
                    lambda nfl: nfl.load_snap_counts(2025).to_dicts())
    injuries = _ensure("injuries_2025.json",
                       lambda nfl: nfl.load_injuries(seasons=[2025]).to_dicts())
    print(f"[backtest_snap] stats24={len(stats24)} stats25={len(stats25)} "
          f"sched={len(sched)} snaps={len(snaps)} injuries={len(injuries)}")

    teams = sorted({g.get("home_team") for g in sched} | {g.get("away_team") for g in sched})
    stat_teams = {r.get("team") for r in stats25}
    print(f"[backtest_snap] schedule teams sample: {teams[:6]}")
    print(f"[backtest_snap] stats teams missing from schedule: {sorted(stat_teams - set(teams)) or 'none'}")
    game_ctx = build_game_context(sched)

    # histories + priors per player
    hist = defaultdict(list)
    for r in stats25:
        if r.get("position") in POSITIONS:
            hist[str(r.get("player_id"))].append(r)
    for v in hist.values():
        v.sort(key=lambda x: x.get("week", 0))
    prior = defaultdict(list)
    for r in stats24:
        if r.get("position") in POSITIONS:
            prior[str(r.get("player_id"))].append(r)

    # depth proxy: week-1 snap order per team (REG QBs only)
    qsnaps = [s for s in snaps if s.get("game_type") == "REG" and s.get("position") == "QB"]
    w1 = defaultdict(list)
    for s in qsnaps:
        if s.get("week") == 1 and (s.get("offense_snaps") or 0) > 0:
            w1[s.get("team")].append((s.get("player"), s.get("offense_snaps")))
    rank_of = {}  # (team, normname) -> rank; name-matched (snap rows lack gsis)
    for t, lst in w1.items():
        lst.sort(key=lambda x: (-x[1], x[0]))
        for i, (nm, _) in enumerate(lst):
            rank_of[(t, str(nm).lower())] = i
    print(f"[backtest_snap] week-1 QB ranks for {len(w1)} teams")

    # injury map (gsis, week) -> out?
    inj_out = set()
    inj_pids = set()
    for j in injuries:
        gid = str(j.get("gsis_id") or "")
        if gid:
            inj_pids.add(gid)
        if str(j.get("report_status") or "").strip().lower() in _UNAVAILABLE:
            inj_out.add((gid, j.get("week")))
    stat_pids = {str(r.get("player_id")) for r in stats25}
    print(f"[backtest_snap] injury gsis overlap with stats pids: "
          f"{len(inj_pids & stat_pids)}/{len(inj_pids)}")

    # snap lookup for recent-max: (team, player-norm, week) -> pct
    snap_pct = {}
    played_weeks = defaultdict(set)
    for s in qsnaps:
        snap_pct[(s.get("team"), str(s.get("player")).lower(), s.get("week"))] = float(s.get("offense_pct") or 0)
        played_weeks[s.get("team")].add(s.get("week"))

    # QB1 name per team (week-1 leader) for the override
    qb1_name = {t: lst[0][0] for t, lst in
                ((t, sorted(v, key=lambda x: (-x[1], x[0]))) for t, v in w1.items())}

    def share(pid, row, week, scale, rule):
        if row.get("position") != "QB":
            return 1.0
        team = row.get("team") or ""
        nm = str(row.get("player_display_name") or row.get("player_name") or "").lower()
        rank = rank_of.get((team, nm), 99)
        if rank == 0:
            return 1.0
        # injury override: rank-0 out this week -> next healthy rank up
        qb1 = qb1_name.get(team)
        if qb1 is not None:
            # find rank-0 rows: name match on leader
            if str(qb1).lower() != nm:
                # is the leader out? check any leader-matching injury row
                # (match leader gsis via stats pid lookup below is costly;
                # instead check override map precomputed per team-week)
                if (team, week) in override_weeks:
                    # next-up = min rank among non-out QBs; approximate by
                    # granting 1.0 only to rank 1 (documented simplification;
                    # deeper takeovers are rare: qb3+ takeover mean 0.25)
                    if rank == 1:
                        return 1.0
        s = scale
        if rule != "depth":
            pw = sorted(w for w in played_weeks.get(team, ()) if w < week)[-3:]
            prior3 = [snap_pct.get((team, nm, w), 0.0) for w in pw]
            if rule == "recentmax":
                if pw:
                    s = max(s, sum(prior3) / len(prior3))
            elif rule == "sustained":
                # why sustained (not mean): a single relief spike (1.0,0,0)
                # is mop-up, not a takeover — lifting on it burned corr in
                # the first run. Takeover needs 2 of last 3 above
                # half-snaps (started); 0.5 is structural, not fitted.
                if sum(1 for v in prior3 if v > 0.5) >= 2:
                    s = max(s, sum(prior3) / len(prior3))
        return s

    # precompute override weeks: (team, week) where week-1 leader is out.
    # leader gsis: resolve via stats rows matching leader name+team in 2025.
    leader_pid = {}
    for r in stats25:
        key = (r.get("team"), str(r.get("player_display_name") or r.get("player_name") or "").lower())
        for t, ldr in qb1_name.items():
            if key == (t, str(ldr).lower()):
                leader_pid.setdefault(t, str(r.get("player_id")))
    override_weeks = {(t, w) for t, pid in leader_pid.items() for w in WEEKS
                      if (pid, w) in inj_out}
    print(f"[backtest_snap] override team-weeks: {len(override_weeks)} "
          f"(leaders resolved {len(leader_pid)}/{len(qb1_name)})")

    eval_rows = [r for r in stats25
                 if r.get("week") in WEEKS and r.get("position") in POSITIONS]
    print(f"[backtest_snap] eval rows: {len(eval_rows)} "
          f"(QB: {sum(1 for r in eval_rows if r.get('position') == 'QB')})")

    ctx_miss = 0
    arms = {"BASE": (1.0, "depth")}
    for sc in SCALES:
        arms[f"V0_{sc}"] = (sc, "depth")
        arms[f"V1_{sc}"] = (sc, "recentmax")
        arms[f"V2_{sc}"] = (sc, "sustained")
    preds = {k: [] for k in arms}
    actual = []
    qb_mask = []
    for r in eval_rows:
        pid = str(r.get("player_id"))
        week = r.get("week")
        h = [x for x in hist.get(pid, []) if x.get("week", 0) < week]
        ctx = game_ctx.get((r.get("team"), week)) or {}
        base_kwargs = dict(player_history=h, position=r.get("position"),
                           prior_season_stats=prior.get(pid, []),
                           implied_total=ctx.get("implied_total", 0) or 0,
                           wind_mph=ctx.get("wind", 0) or 0,
                           temp_f=ctx.get("temp"))
        if not ctx:
            ctx_miss += 1
        try:
            actual.append(float(calculate_fantasy_points(r, DEFAULT_SCORING)))
        except Exception:
            actual.append(0.0)
        qb_mask.append(r.get("position") == "QB")
        proj0 = project_player_stats(**base_kwargs)
        for name, (scale, rule) in arms.items():
            if name == "BASE" or r.get("position") != "QB":
                p = proj0
            else:
                s = share(pid, r, week, scale, rule)
                p = {k: (v * s if isinstance(v, (int, float)) and not isinstance(v, bool) else v)
                     for k, v in proj0.items() if k != "is_empty_projection"}
                p["is_empty_projection"] = proj0.get("is_empty_projection", False)
            try:
                preds[name].append(float(calculate_fantasy_points(p, DEFAULT_SCORING)))
            except Exception:
                preds[name].append(0.0)
    print(f"[backtest_snap] ctx miss rate: {ctx_miss}/{len(eval_rows)}")

    results = {"freeze": FREEZE, "arms": {}}
    base_pred = preds["BASE"]
    for name in arms:
        m = _metrics(actual, preds[name], eval_rows)
        qb_idx = [i for i, q in enumerate(qb_mask) if q]
        mq = _metrics([actual[i] for i in qb_idx], [preds[name][i] for i in qb_idx],
                      [eval_rows[i] for i in qb_idx])
        results["arms"][name] = {"overall": m, "qb": mq}
        print(f"[backtest_snap] {name:8s} MAE {m['mae']:.4f} corr {m['corr']:.4f} "
              f"pw {m['pairwise']:.4f} bias {m['bias']:+.3f} n={m['n']} | "
              f"QB MAE {mq['mae']:.4f} corr {mq['corr']:.4f} n={mq['n']}")
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=1)
    print(f"[backtest_snap] wrote {OUT_JSON}")

    # why paired stats (not just point estimates): overall corr moves -0.003
    # while 90% of rows are identical across arms — point diffs alone can't
    # tell noise from signal. Paired t on |err| for MAE, Fisher z for corr,
    # both BASE vs best variant (V1_0.05, principle-picked in plan).
    import math
    yt = np.array(actual, dtype=float)
    b = np.array(base_pred, dtype=float)
    v = np.array(preds["V1_0.05"], dtype=float)
    d = np.abs(b - yt) - np.abs(v - yt)
    t = float(np.mean(d) / (np.std(d, ddof=1) / math.sqrt(len(d))))
    print(f"[backtest_snap] paired-t BASE-V1_0.05 |err|: t={t:.2f} "
          f"(mean diff {np.mean(d):+.4f}, n={len(d)})")

    def fisher_z(x, y):
        r = float(np.mean((x - np.mean(x)) * (y - np.mean(y))) / (np.std(x) * np.std(y)))
        return 0.5 * math.log((1 + r) / (1 - r)), r

    zb, rb = fisher_z(b, yt)
    zv, rv = fisher_z(v, yt)
    se = math.sqrt(2 / (len(yt) - 3))
    z = (zb - zv) / se
    print(f"[backtest_snap] corr BASE {rb:.4f} vs V1_0.05 {rv:.4f}: "
          f"Fisher z-diff={z:.2f} (SE={se:.4f}, |z|<2 ~= noise)")

    # why QB-only paired test: the variant touches ~10% of rows, so the
    # overall test is underpowered for the actual claim (backup-QB error).
    # PASS requires QB-significant AND no overall regression.
    qi = np.array([i for i, q in enumerate(qb_mask) if q])
    dq = np.abs(b[qi] - yt[qi]) - np.abs(v[qi] - yt[qi])
    tq = float(np.mean(dq) / (np.std(dq, ddof=1) / math.sqrt(len(dq))))
    print(f"[backtest_snap] QB-only paired-t: t={tq:.2f} "
          f"(mean diff {np.mean(dq):+.4f}, n={len(dq)})")
    results["paired"] = {"overall_t": t, "overall_mean_diff": float(np.mean(d)),
                         "qb_t": tq, "qb_mean_diff": float(np.mean(dq)),
                         "corr_z_diff": z}
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=1)


if __name__ == "__main__":
    main()
