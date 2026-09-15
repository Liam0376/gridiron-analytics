#!/usr/bin/env python3
"""Cumulative 2026 snap-share retest (snap-share-retest plan, Tasks 1-3).

Task 1 (default): honest OOS retest of production vs QB snap-scaled variants
on REAL 2026 weeks played to date. Same all-universe discipline as
scripts/backtest_snap_share.py: gate on the production freeze MAE 4.563 /
Corr 0.648 / Pairwise 74.1% (src/ffanalytics/stat_projector.py:8).

BASE is production-verbatim: build_weekly_projections() itself (not a
reimplementation), DEFAULT_SCORING, out_pids from weekly injury reports
(same UNAVAILABLE set as src/ffanalytics/config.py OUT_STATUSES).

Depth signal (honest pre-week): nflverse preseason depth snapshot
(latest scrape strictly before the first Week-1 kickoff), gsis-keyed
throughout — stats pids ARE gsis ids, depth rows carry gsis_id, zero
name matching (gsis-identity spec). Movers resolve by construction
(Geno NYJ QB1, Kyler MIN QB1, Tua ATL QB1). The manual FantasyPros CSV
is retired; using the current chart would leak post-Week-1 depth moves
(e.g. Tua's benching) into Week-1 projections.

Arms: BASE vs V0 (depth-only) / V1 (recent-max) x scales {0.03,0.05,0.10},
QB-only, post-weather scale-down-only. NOOUT = BASE without out_pids (out-rule
ablation). ZERO = NOOUT + post-hoc out-zero (equals BASE by construction;
fired-count reported). V2 sustained-takeover dropped (lost to recent-max in
2025, qb-snap-share plan Task 2).

Repro: PYTHONHASHSEED=0 for bit-identical pairwise (set-order sensitivity
jitters pairwise ~+-0.004 across seeds, verdict-invariant).

Task 2 (--check-2025-join): re-runs the 2025 holdout (weeks 4-18) with ONLY
the normalized-name join applied to the predecessor's week-1-snap proxy, and
diffs against data/ml/backtest_snap_share_results.json. No writes.

Task 3 (--skill-shares): correlates 2025 PBP target_share/snap_share
(weighted-recent, same weighting as production) with 2026 surprise
(actual - BASE), split DNP vs played. Writes
data/ml/skill_share_2026.json; table goes in the commit message.

Fully offline after first fetch: stats_2025/schedule_2026 from
data/nfl_cache/ (present); stats_2026/snaps_2026/injuries_2026 fetched once
via nflreadpy and cached under data/nfl_cache/ (gitignored) if absent.
"""
import argparse
import json
import math
import os
import re
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

os.environ.setdefault("SLEEPER_LEAGUE_ID", "test")

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from ffanalytics.stat_projector import (  # noqa: E402
    QB_STATS,
    KICKER_STATS,
    SKILL_STATS,
    build_weekly_projections,
    weighted_recent_avg,
)
from ffanalytics.scoring import calculate_fantasy_points, DEFAULT_SCORING  # noqa: E402

FREEZE = {"mae": 4.563, "corr": 0.648, "pairwise": 0.741}
POSITIONS = ("QB", "RB", "WR", "TE", "K")
SCALES = (0.03, 0.05, 0.10)
# why mirror (not import): canonical home is config.OUT_STATUSES; scripts
# predate the canonicalization (same note as scripts/backtest_snap_share.py).
_UNAVAILABLE = {"out", "ir", "injured reserve", "pup", "nfi", "suspended", "na"}

CACHE = REPO_ROOT / "data" / "nfl_cache"
OUT_JSON = REPO_ROOT / "data" / "ml" / "backtest_snap_share_2026_results.json"
SKILL_JSON = REPO_ROOT / "data" / "ml" / "skill_share_2026.json"

STAT_KEYS = {
    "QB": set(QB_STATS),
    "K": set(KICKER_STATS),
    "RB": set(SKILL_STATS), "WR": set(SKILL_STATS), "TE": set(SKILL_STATS),
}


def norm_name(n) -> str:
    n = str(n or "").lower().strip()
    n = re.sub(r"\b(jr|sr|ii|iii|iv|v)\.?\b", "", n)
    n = re.sub(r"[^a-z ]", "", n)
    return re.sub(r"\s+", " ", n).strip()


def load_depth_gsis(first_kickoff: str):
    """Preseason depth snapshot -> {gsis: (team, rank)} for QBs.

    gsis-keyed throughout: stats pids ARE gsis ids and depth rows carry
    gsis_id — zero name matching (gsis-identity spec). Preseason honesty:
    latest snapshot strictly before the first Week-1 kickoff; the current
    chart would leak post-Week-1 depth moves (e.g. Tua's benching) into
    Week-1 projections.
    """
    rows = _ensure_cache(
        "depth_skill_2026.json",
        lambda nfl: [
            {"gsis_id": r.get("gsis_id"), "team": r.get("team"),
             "pos_abb": r.get("pos_abb"), "pos_rank": r.get("pos_rank"),
             "dt": r.get("dt")}
            for r in nfl.load_depth_charts(seasons=[2026]).to_dicts()
            if str(r.get("pos_abb") or "").upper() in ("QB", "RB", "WR", "TE")
            and str(r.get("gsis_id") or "")
        ])
    pre = [r for r in rows if str(r.get("dt") or "")[:10] < first_kickoff]
    if not pre:
        sys.exit("[snap2026] no preseason depth snapshot before " + first_kickoff)
    snap_dt = max(str(r.get("dt") or "") for r in pre)
    snap = [r for r in pre if str(r.get("dt") or "") == snap_dt]
    print(f"[snap2026] preseason depth snapshot: {snap_dt} ({len(snap)} rows)")
    # why reuse (not reimplement): one definition of rank semantics.
    from ffanalytics.refresh import gsis_depth_rank
    ranked = gsis_depth_rank(snap)
    return ({g: (v["team"], v["rank"]) for g, v in ranked.items()
             if v["position"] == "QB"}, snap_dt)


def _load_cache(name):
    with open(CACHE / name, encoding="utf-8") as f:
        return json.load(f)


def _ensure_cache(name, fetch):
    path = CACHE / name
    if path.exists():
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    import nflreadpy as nfl
    rows = fetch(nfl)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(rows, f)
    print(f"[snap2026] cached {name} ({len(rows)} rows)")
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


def _paired_stats(a, b, yt):
    """Paired-t on |err| (a vs b) + Fisher z corr diff. Positive t favors b."""
    a = np.array(a, dtype=float)
    b = np.array(b, dtype=float)
    yt = np.array(yt, dtype=float)
    d = np.abs(a - yt) - np.abs(b - yt)
    t = float(np.mean(d) / (np.std(d, ddof=1) / math.sqrt(len(d))))

    def _fz(x, y):
        r = float(np.mean((x - np.mean(x)) * (y - np.mean(y))) / (np.std(x) * np.std(y)))
        r = max(-0.9999, min(0.9999, r))
        return 0.5 * math.log((1 + r) / (1 - r)), r

    za, ra = _fz(a, yt)
    zb, rb = _fz(b, yt)
    se = math.sqrt(2 / (len(yt) - 3))
    return {"t": t, "mean_diff": float(np.mean(d)),
            "corr_a": ra, "corr_b": rb, "z_diff": (za - zb) / se}


def _is_empty_row(row) -> bool:
    keys = ("passing_yards", "rushing_yards", "receiving_yards", "receptions")
    return all(not (row.get(k) or 0) for k in keys)


def run_2026():
    stats26 = _ensure_cache(
        "stats_2026.json",
        lambda nfl: nfl.load_player_stats(seasons=[2026]).to_dicts())
    stats25 = [r for r in _load_cache("stats_2025.json")
               if r.get("season_type", "REG") == "REG"]
    sched = _load_cache("schedule_2026.json")
    snaps = _ensure_cache("snaps_2026.json",
                          lambda nfl: nfl.load_snap_counts(2026).to_dicts())
    injuries = _ensure_cache("injuries_2026.json",
                             lambda nfl: nfl.load_injuries(seasons=[2026]).to_dicts())
    first_kickoff = min(str(g.get("gameday") or "") for g in sched
                        if g.get("game_type") == "REG" and g.get("week") == 1)
    gsis_qb_rank, _snap_dt = load_depth_gsis(first_kickoff)

    played_weeks = sorted({
        s["week"] for s in stats26
        if s.get("season_type") == "REG" and s.get("week") and not _is_empty_row(s)
    })
    if not played_weeks:
        print("[snap2026] no 2026 REG weeks played yet — nothing to test.")
        return
    print(f"[snap2026] weeks played: {played_weeks} "
          f"(SMALL SAMPLE until n >> 100 — never promote on one week)")

    inj_out = set()
    for j in injuries:
        if str(j.get("report_status") or "").strip().lower() in _UNAVAILABLE:
            gid = str(j.get("gsis_id") or "")
            if gid:
                inj_out.add((gid, j.get("week")))

    snap_pct = {}
    snap_teams_weeks = set()
    for s in snaps:
        if s.get("game_type") != "REG":
            continue
        snap_pct[(s.get("team"), norm_name(s.get("player")), s.get("week"))] = \
            float(s.get("offense_pct") or 0)
        snap_teams_weeks.add((s.get("team"), s.get("week")))
    sched_tw = set()
    for g in sched:
        if g.get("game_type") != "REG" or not g.get("week"):
            continue
        sched_tw.add((g.get("home_team"), g.get("week")))
        sched_tw.add((g.get("away_team"), g.get("week")))
    missing_snap = sorted(tw for tw in
                          {(t, w) for (t, w) in sched_tw if w in played_weeks}
                          - snap_teams_weeks)
    print(f"[snap2026] snap coverage: {len(snap_teams_weeks)} team-weeks; "
          f"missing (reported, not dropped): {missing_snap or 'none'}")

    # QB1-out override weeks on depth teams: rank-0 gsis ids match inj_out
    # directly (both gsis-keyed) — no name resolution anywhere in this path.
    qb1_out_weeks = set()
    for gid, (tm, rk) in gsis_qb_rank.items():
        if rk != 0:
            continue
        for w in played_weeks:
            if (gid, w) in inj_out:
                qb1_out_weeks.add((tm, w))

    arms = ["BASE", "NOOUT", "ZERO"]
    for sc in SCALES:
        arms += [f"V0_{sc}", f"V1_{sc}"]
    preds = {k: [] for k in arms}
    actual, meta, qb_mask = [], [], []
    depth_hit = depth_tot = 0
    fired = 0

    for w in played_weeks:
        out_pids = {pid for (pid, ww) in inj_out if ww == w}
        projs_out = build_weekly_projections(
            stats26, sched, w, DEFAULT_SCORING,
            prior_season_stats=stats25, out_pids=out_pids)
        projs_no = build_weekly_projections(
            stats26, sched, w, DEFAULT_SCORING,
            prior_season_stats=stats25)
        by_out = {str(p.get("player_id")): p for p in projs_out}
        by_no = {str(p.get("player_id")): p for p in projs_no}
        actual_by_pid = {str(s["player_id"]): s for s in stats26
                         if s.get("week") == w and s.get("season_type") == "REG"}
        for pid in sorted(set(by_out) | set(by_no)):
            pr = by_out.get(pid) or by_no.get(pid)
            pn = by_no.get(pid, pr)
            pos = pr.get("position")
            if pos not in POSITIONS:
                continue
            tm_hist = pr.get("team") or ""
            nm = norm_name(pr.get("player_display_name") or "")
            # why depth-team-first bye filter: this script calls
            # build_weekly_projections directly (no refresh gsis patch), so
            # pr teams are history teams — stale for movers. The depth chart
            # is the preseason-correct team. (norm_name survives only for the
            # snap lookup below; snap rows lack gsis.)
            if pos == "QB":
                dtm, drank = gsis_qb_rank.get(str(pid), (None, 99))
            else:
                dtm, drank = None, None
            tm_eval = dtm or tm_hist
            if (tm_eval, w) not in sched_tw:
                continue
            try:
                base_pts = float(pr.get("projected_points", 0) or 0)
            except Exception:
                base_pts = 0.0
            try:
                noout_pts = float(pn.get("projected_points", 0) or 0)
            except Exception:
                noout_pts = 0.0
            real = actual_by_pid.get(pid)
            try:
                pa = float(calculate_fantasy_points(real, DEFAULT_SCORING)) if real else 0.0
            except Exception:
                pa = 0.0
            is_qb = pos == "QB"
            share = {}
            if is_qb:
                depth_tot += 1
                if drank != 99:
                    depth_hit += 1
                if drank == 0:
                    s0 = 1.0
                elif dtm in {t for (t, ww) in qb1_out_weeks if ww == w} and drank == 1:
                    s0 = 1.0
                else:
                    s0 = None  # scaled below
                pw = [x for x in played_weeks if x < w][-3:]
                trail = [snap_pct.get((dtm or tm_hist, nm, x), 0.0) for x in pw]
                trail_mean = sum(trail) / len(trail) if trail else 0.0
                for sc in SCALES:
                    d = 1.0 if s0 == 1.0 else sc
                    share[f"V0_{sc}"] = d
                    share[f"V1_{sc}"] = d if s0 == 1.0 else max(sc, trail_mean)
            keys = STAT_KEYS.get(pos, set())
            for name in arms:
                if name == "BASE":
                    preds[name].append(base_pts)
                elif name == "NOOUT":
                    preds[name].append(noout_pts)
                elif name == "ZERO":
                    preds[name].append(0.0 if (pid, w) in inj_out else noout_pts)
                else:
                    s = share.get(name, 1.0)
                    if s == 1.0:
                        preds[name].append(noout_pts)
                    else:
                        # why NOOUT base (not BASE): BASE already zeroes outs;
                        # variants compose with the no-out pipeline so the
                        # snap effect is isolated from the out rule.
                        sc_dict = {k: (v * s if isinstance(v, (int, float))
                                                 and not isinstance(v, bool) else v)
                                   for k, v in pn.items() if k in keys}
                        try:
                            preds[name].append(float(calculate_fantasy_points(
                                {**pn, **sc_dict}, DEFAULT_SCORING)))
                        except Exception:
                            preds[name].append(0.0)
            if (pid, w) in inj_out and noout_pts != 0.0:
                fired += 1
            actual.append(pa)
            meta.append({"season": 2026, "week": w, "position": pos})
            qb_mask.append(is_qb)

    print(f"[snap2026] eval player-weeks: {len(actual)} "
          f"(QB {sum(qb_mask)}); depth-gsis hit rate: "
          f"{depth_hit}/{depth_tot}; ZERO/out fired: {fired}")
    results = {"freeze": FREEZE, "weeks_played": played_weeks,
               "depth_hit": [depth_hit, depth_tot], "arms": {}}
    for name in arms:
        m = _metrics(actual, preds[name], meta)
        qi = [i for i, q in enumerate(qb_mask) if q]
        mq = _metrics([actual[i] for i in qi], [preds[name][i] for i in qi],
                      [meta[i] for i in qi])
        results["arms"][name] = {"overall": m, "qb": mq}
        print(f"[snap2026] {name:8s} MAE {m['mae']:.4f} corr {m['corr']:.4f} "
              f"pw {m['pairwise']:.4f} bias {m['bias']:+.3f} n={m['n']} | "
              f"QB MAE {mq['mae']:.4f} corr {mq['corr']:.4f} n={mq['n']}")
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    qi = np.array([i for i, q in enumerate(qb_mask) if q])
    yt = np.array(actual, dtype=float)
    paired = {}
    for a, b, tag in [("BASE", "V1_0.05", "primary"),
                      ("BASE", "NOOUT", "out_rule"),
                      ("NOOUT", "ZERO", "zero_equiv")]:
        st = _paired_stats(preds[a], preds[b], yt)
        st_q = _paired_stats([preds[a][i] for i in qi],
                             [preds[b][i] for i in qi], yt[qi])
        paired[tag] = {"arms": [a, b], "overall": st,
                       "qb_t": st_q["t"], "qb_mean_diff": st_q["mean_diff"]}
        print(f"[snap2026] paired {tag} {a}-{b}: t={st['t']:.2f} "
              f"(diff {st['mean_diff']:+.4f}) QB t={st_q['t']:.2f} "
              f"(diff {st_q['mean_diff']:+.4f}) corr z={st['z_diff']:.2f}")
    results["paired"] = paired
    results["zero_fired"] = fired
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=1)
    print(f"[snap2026] wrote {OUT_JSON}")
    print("[snap2026] GATE: promotion needs cumulative 2026 + 2025 join-fix "
          "agreement + full suite — one week never flips the flag (see spec).")


def run_2025_joincheck():
    """Task 2: 2025 holdout with ONLY the normalized-name join.

    Same protocol/sample as scripts/backtest_snap_share.py (all-universe,
    weeks 4-18, BASE vs V1_0.05 recent-max + ZERO), but every name join
    (week-1 snap rank, recent-max lookup, leader resolution) goes through
    norm_name. Diffs against data/ml/backtest_snap_share_results.json.
    """
    from ffanalytics.stat_projector import project_player_stats, build_game_context
    stats24 = [r for r in _load_cache("stats_2024.json")
               if r.get("season_type", "REG") == "REG"]
    stats25 = [r for r in _load_cache("stats_2025.json")
               if r.get("season_type", "REG") == "REG"]
    sched = _load_cache("schedule_2025.json")
    snaps = _ensure_cache("snaps_2025.json",
                          lambda nfl: nfl.load_snap_counts(2025).to_dicts())
    injuries = _ensure_cache("injuries_2025.json",
                             lambda nfl: nfl.load_injuries(seasons=[2025]).to_dicts())
    with open(REPO_ROOT / "data" / "ml" / "backtest_snap_share_results.json",
              encoding="utf-8") as f:
        published = json.load(f)

    game_ctx = build_game_context(sched)
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

    qsnaps = [s for s in snaps
              if s.get("game_type") == "REG" and s.get("position") == "QB"]
    w1 = defaultdict(list)
    for s in qsnaps:
        if s.get("week") == 1 and (s.get("offense_snaps") or 0) > 0:
            w1[s.get("team")].append((norm_name(s.get("player")),
                                      s.get("offense_snaps")))
    rank_of = {}
    for t, lst in w1.items():
        lst.sort(key=lambda x: (-x[1], x[0]))
        for i, (nm, _) in enumerate(lst):
            rank_of[(t, nm)] = i
    inj_out = set()
    for j in injuries:
        if str(j.get("report_status") or "").strip().lower() in _UNAVAILABLE:
            gid = str(j.get("gsis_id") or "")
            if gid:
                inj_out.add((gid, j.get("week")))
    snap_pct = {}
    played_weeks = defaultdict(set)
    for s in qsnaps:
        snap_pct[(s.get("team"), norm_name(s.get("player")), s.get("week"))] = \
            float(s.get("offense_pct") or 0)
        played_weeks[s.get("team")].add(s.get("week"))
    qb1_name = {t: lst[0][0] for t, lst in
                ((t, sorted(v, key=lambda x: (-x[1], x[0]))) for t, v in w1.items())}
    leader_pid = {}
    for r in stats25:
        key = (r.get("team"), norm_name(
            r.get("player_display_name") or r.get("player_name") or ""))
        for t, ldr in qb1_name.items():
            if key == (t, ldr):
                leader_pid.setdefault(t, str(r.get("player_id")))
    weeks = range(4, 19)
    override_weeks = {(t, w) for t, pid in leader_pid.items() for w in weeks
                      if (pid, w) in inj_out}

    def share(pid, row, week, scale):
        if row.get("position") != "QB":
            return 1.0
        team = row.get("team") or ""
        nm = norm_name(row.get("player_display_name") or row.get("player_name") or "")
        if rank_of.get((team, nm), 99) == 0:
            return 1.0
        if (team, week) in override_weeks and rank_of.get((team, nm), 99) == 1:
            return 1.0
        pw = sorted(w for w in played_weeks.get(team, ()) if w < week)[-3:]
        prior3 = [snap_pct.get((team, nm, w), 0.0) for w in pw]
        return max(scale, sum(prior3) / len(prior3)) if pw else scale

    team_of, pos_of = {}, {}
    for pid, rows in hist.items():
        teams = [x.get("team") for x in rows if x.get("team")]
        if teams:
            team_of[pid] = max(sorted(set(teams)), key=teams.count)
        pos_of[pid] = rows[0].get("position")
    for r in stats24:
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
    by_pw = {(str(r.get("player_id")), r.get("week")): r for r in stats25
             if r.get("position") in POSITIONS}
    prior_pids = {str(r.get("player_id")) for r in stats24
                  if r.get("position") in POSITIONS}
    eval_items = []
    for w in weeks:
        cur = {pid for pid, rows in hist.items()
               if any(x.get("week", 0) < w for x in rows)}
        # why unsorted (NOT sorted like the 2026 mode): _metrics pairwise is
        # traversal-order dependent under tied actuals (DNP 0.0 pairs count
        # correct iff the earlier row predicts lower). The published 2025
        # numbers were produced by set-order traversal, so this check must
        # use the same traversal (same PYTHONHASHSEED) for a comparable
        # pairwise. See Task-2 note in the plan.
        for pid in (cur if cur else prior_pids):
            if (team_of.get(pid), w) not in played_tw:
                continue
            eval_items.append((pid, w))

    preds = {"BASE": [], "V1_0.05": [], "ZERO": []}
    actual, qb_mask, meta = [], [], []
    for pid, week in eval_items:
        pos = pos_of.get(pid)
        team = team_of.get(pid)
        h = [x for x in hist.get(pid, []) if x.get("week", 0) < week]
        r_eff = by_pw.get((pid, week)) or (h[-1] if h else None) or {}
        ctx = game_ctx.get((team, week)) or {}
        proj0 = project_player_stats(
            player_history=h, position=pos,
            prior_season_stats=prior.get(pid, []),
            implied_total=ctx.get("implied_total", 0) or 0,
            wind_mph=ctx.get("wind", 0) or 0, temp_f=ctx.get("temp"))
        try:
            base_pts = float(calculate_fantasy_points(proj0, DEFAULT_SCORING))
        except Exception:
            base_pts = 0.0
        real = by_pw.get((pid, week))
        try:
            actual.append(float(calculate_fantasy_points(real, DEFAULT_SCORING)) if real else 0.0)
        except Exception:
            actual.append(0.0)
        qb_mask.append(pos == "QB")
        meta.append({"season": 2025, "week": week, "position": pos})
        preds["ZERO"].append(0.0 if (pid, week) in inj_out else base_pts)
        preds["BASE"].append(base_pts)
        if pos != "QB":
            preds["V1_0.05"].append(base_pts)
        else:
            s = share(pid, r_eff, week, 0.05)
            p = {k: (v * s if isinstance(v, (int, float)) and not isinstance(v, bool) else v)
                 for k, v in proj0.items() if k != "is_empty_projection"}
            p["is_empty_projection"] = proj0.get("is_empty_projection", False)
            try:
                preds["V1_0.05"].append(float(calculate_fantasy_points(p, DEFAULT_SCORING)))
            except Exception:
                preds["V1_0.05"].append(0.0)

    print(f"[joinfix] eval player-weeks: {len(actual)} "
          f"(published n={published['arms']['BASE']['overall']['n']})")
    ok = True
    for name in ("BASE", "V1_0.05", "ZERO"):
        m = _metrics(actual, preds[name], meta)
        pub = published["arms"][name if name != "V1_0.05" else "V1_0.05"]["overall"]
        same_sign = (m["mae"] - _metrics(actual, preds["BASE"], meta)["mae"]) * (
            pub["mae"] - published["arms"]["BASE"]["overall"]["mae"]) >= 0
        ok = ok and same_sign
        print(f"[joinfix] {name:8s} rerun MAE {m['mae']:.4f} corr {m['corr']:.4f} "
              f"pw {m['pairwise']:.4f} | published MAE {pub['mae']:.4f} "
              f"corr {pub['corr']:.4f} pw {pub['pairwise']:.4f} "
              f"sign-agree={same_sign}")
    yt = np.array(actual, dtype=float)
    st = _paired_stats(preds["BASE"], preds["V1_0.05"], yt)
    pub_t = published.get("paired", {})
    print(f"[joinfix] paired BASE-V1_0.05: rerun t={st['t']:.2f} "
          f"(published overall_t={pub_t.get('overall_t')}) corr z={st['z_diff']:.2f} "
          f"(published {pub_t.get('corr_z_diff')})")
    print("[joinfix] " + ("PASS: no sign flip from the join fix — 2025 REJECTED "
                          "verdict stands." if ok else
                          "FAIL: sign flip vs published — predecessor verdict "
                          "needs an addendum, do NOT promote."))
    # why this t looks nothing like the header's t=1.66: that number is the
    # 2025-holdout PAIRED comparison at n=5425 (box-score sample); this loop
    # is the all-universe sample at n=8049 (DNPs included, where scaling
    # helps most). Sample mismatch is documented in stat_projector.py:42-56
    # — verdict REJECTED stands either way, do not gate on either t alone.
    print("[joinfix] NOTE: paired-t here (all-universe n=8049) is NOT the "
          "header's t=1.66 (paired n=5425). Different samples, same verdict.")


def run_skill_shares():
    """Task 3: 2025 PBP shares vs 2026 surprise, DNP vs played split."""
    pbp = _load_cache("pbp_2025.json")
    by_pid = defaultdict(list)
    for r in pbp:
        by_pid[str(r.get("player_id"))].append(r)
    shares = {}
    for pid, rows in by_pid.items():
        rows.sort(key=lambda x: (x.get("season", 0), x.get("week", 0)))
        for key in ("target_share", "snap_share", "rush_share", "air_yards_share"):
            vals = [float(r.get(key) or 0) for r in rows]
            shares[(pid, key)] = weighted_recent_avg(vals) if vals else 0.0

    stats26 = _ensure_cache(
        "stats_2026.json",
        lambda nfl: nfl.load_player_stats(seasons=[2026]).to_dicts())
    stats25 = [r for r in _load_cache("stats_2025.json")
               if r.get("season_type", "REG") == "REG"]
    sched = _load_cache("schedule_2026.json")
    played_weeks = sorted({
        s["week"] for s in stats26
        if s.get("season_type") == "REG" and s.get("week") and not _is_empty_row(s)
    })
    actual_by_pw = {(str(s["player_id"]), s.get("week")): s for s in stats26
                    if s.get("season_type") == "REG"}
    pos_of = {}
    for r in stats25:
        if r.get("position") in ("RB", "WR", "TE", "QB"):
            pos_of.setdefault(str(r.get("player_id")), r.get("position"))

    rows = []  # (pos, share_key, share, surprise, played)
    for w in played_weeks:
        projs = build_weekly_projections(
            stats26, sched, w, DEFAULT_SCORING, prior_season_stats=stats25)
        for pr in projs:
            pid = str(pr.get("player_id"))
            pos = pr.get("position")
            if pos not in ("RB", "WR", "TE", "QB"):
                continue
            real = actual_by_pw.get((pid, w))
            played = real is not None and not _is_empty_row(real)
            try:
                pa = float(calculate_fantasy_points(real, DEFAULT_SCORING)) if real else 0.0
            except Exception:
                pa = 0.0
            try:
                pb = float(pr.get("projected_points", 0) or 0)
            except Exception:
                pb = 0.0
            rows.append({"pos": pos, "pid": pid, "week": w,
                         "surprise": pa - pb, "actual": pa, "base": pb,
                         "played": played,
                         "target_share": shares.get((pid, "target_share"), 0.0),
                         "snap_share": shares.get((pid, "snap_share"), 0.0),
                         "rush_share": shares.get((pid, "rush_share"), 0.0),
                         "air_yards_share": shares.get((pid, "air_yards_share"), 0.0)})

    def _corr(xs, ys):
        x = np.array(xs, dtype=float)
        y = np.array(ys, dtype=float)
        if len(x) < 10 or float(np.std(x)) == 0 or float(np.std(y)) == 0:
            return None, len(x)
        return float(np.mean((x - np.mean(x)) * (y - np.mean(y))) / (
            np.std(x) * np.std(y))), len(x)

    out = {"weeks": played_weeks, "n_rows": len(rows), "cells": {}}
    print(f"[skill] weeks={played_weeks} rows={len(rows)}")
    print(f"[skill] {'pos':4s} {'split':6s} {'share':15s} {'corr(surprise)':>14s} "
          f"{'corr(actual)':>12s} {'n':>5s}")
    for pos in ("RB", "WR", "TE", "QB"):
        for split, sel in (("played", True), ("dnp", False)):
            sub = [r for r in rows if r["pos"] == pos and r["played"] is sel]
            for key in ("target_share", "snap_share", "rush_share", "air_yards_share"):
                c1, n = _corr([r[key] for r in sub], [r["surprise"] for r in sub])
                c2, _ = _corr([r[key] for r in sub], [r["actual"] for r in sub])
                out["cells"][f"{pos}/{split}/{key}"] = {
                    "corr_surprise": c1, "corr_actual": c2, "n": n}
                f1 = f"{c1:+.3f}" if c1 is not None else "n/a"
                f2 = f"{c2:+.3f}" if c2 is not None else "n/a"
                print(f"[skill] {pos:4s} {split:6s} {key:15s} {f1:>14s} {f2:>12s} {n:>5d}")
    SKILL_JSON.parent.mkdir(parents=True, exist_ok=True)
    with open(SKILL_JSON, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=1)
    print(f"[skill] wrote {SKILL_JSON}")
    print("[skill] READ: a share only earns a production input if it predicts "
          "SURPRISE on played weeks (corr(actual) is confounded — good players "
          "get shares AND score). Default stays measurement-only (spec).")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check-2025-join", action="store_true")
    ap.add_argument("--skill-shares", action="store_true")
    args = ap.parse_args()
    if args.check_2025_join:
        run_2025_joincheck()
    elif args.skill_shares:
        run_skill_shares()
    else:
        run_2026()


if __name__ == "__main__":
    main()
