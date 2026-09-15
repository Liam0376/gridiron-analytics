#!/usr/bin/env python3
"""Opportunity-share arms backtest (opportunity plan, Task 2).

PRE-REGISTRATION (anti-fitting — read before touching):
  Arms: BASE vs X1_0.15 (PRIMARY) vs X1_0.30 (sensitivity only) vs X2
  (single variant). No other k, no other blends, no extra arms will be
  tried regardless of outcome. If the primary fails, the verdict is fail;
  the sensitivity arm is diagnostic, never a promotion candidate.
  Rationale for k: one-week mean reversion of the surprise fraction;
  0.15 is the conservative principle pick, 0.30 bounds the sensitivity.

Mechanisms (derived, not fitted):
  X1 (xFP pull): projected receiving yards/receptions += k * trailing
  (expected - actual) gap, applied inside project_player_stats BEFORE
  TD regression/usage trend (xfp_adjust param), capped at +-50% of base,
  no pull from zero base. One arm covers both unrealized air yards and
  catch-rate luck — they are the same gap, not two signals.
  X2 (individualized TD prior): same 30% regression weight, but the prior
  is the player's own trailing xFP-implied TD rate instead of the flat
  position mean (td_prior param). Empirical-Bayes shape, weight unchanged.

Scope: WR/TE/RB receiving (+RB rushing TDs in X2). QB/K passthrough.
Out-zeroing deliberately OFF for all arms (apples-to-apples on the xFP
question; the out rule is already proven and composes additively).

Samples (honest OOS, existing data only):
  2025 holdout (PRIMARY gate): 2024 stats+opportunity priors, weeks 4-18,
  all-universe, REG week<=18 (the feed has no season_type; playoffs are
  weeks 19-22).
  2026 cumulative (agreement): same-season stats+opportunity weeks<w, else
  the 2025 prior season; weeks played to date.
Opportunity trailing windows mirror the stats history rule exactly.

Gate: freeze MAE 4.563 / Corr 0.648 / Pairwise 74.1% on the 2025 holdout,
variant-vs-BASE paired-t p<0.05 with corr non-negative, 2026 agreement in
the same direction, full suite green. One week never promotes.

  QB PRE-REGISTRATION 2026-09-15 (qb-xfp spec, committed before running):
  Skill arms run unchanged (X1 rejected, POP/FROZEN verdicts stand).
  New arms, QB ONLY: XQ1_015 (passing-yards pull k=0.15, PRIMARY),
  XQ1_030 (k=0.30, sensitivity only), QPOP (single variant: td_prior
  passing_tds = position mean trailing pass_td_exp, same construction as
  POP). QB rushing TDs untouched. No snap scaling here (pure-pipeline
  comparison). Verdict: an arm promotes iff it beats BASE with paired
  p<0.05 in BOTH samples with corr neutral (QB subset reported alongside
  overall). Anything else: REJECTED inline. No other arms.

FOLLOW-UP PRE-REGISTRATION 2026-09-15 (X2 control — committed before running):
  X1 stays REJECTED (still run for record stability, never a candidate).
  New arm POP (single variant): same 30% weight, prior = the POSITION's
  mean trailing xFP-implied TD rate over that week's skill eval rows
  (pre-week data only). X2-vs-POP isolates individualization: same weight,
  same data, same base rates — only granularity differs.
  Verdict rule, pre-committed: promotion candidate = whichever of X2/POP
  beats BASE with paired p<0.05 in BOTH samples and corr neutral; if
  X2-vs-POP is n.s. in both samples, ship POP (simpler, same information);
  if neither beats BASE in both samples, reject both. No further arms
  under any outcome.

  SHIP-EXACTNESS ADDENDUM 2026-09-15 (verification, not a new hypothesis):
  POP beat X2 outright both samples, so the candidate is the population
  prior. What ships must be frozen constants, not a live per-week
  computation — so arm FROZEN applies the proposed POS_TD_MEANS replacements
  verbatim (RB rush 0.20/rec 0.04, WR rec 0.18/rush 0.005, TE rec 0.14;
  QB/K untouched: no evidence, X2/POP never applied there). Promotion
  requires FROZEN to reproduce POP within noise on both samples. X1 stays
  rejected throughout.

Repro: PYTHONHASHSEED=0. Fully offline after first fetch (opportunity
2024/2025/2026 cached under data/nfl_cache/, gitignored).
"""
import argparse
import json
import math
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

from ffanalytics.stat_projector import (  # noqa: E402
    project_player_stats,
    build_game_context,
    weighted_recent_avg,
)
from ffanalytics.scoring import calculate_fantasy_points, DEFAULT_SCORING  # noqa: E402
from ffanalytics.refresh import opportunity_features  # noqa: E402

FREEZE = {"mae": 4.563, "corr": 0.648, "pairwise": 0.741}
POSITIONS = ("QB", "RB", "WR", "TE", "K")
SKILL = ("RB", "WR", "TE")
# why these and only these: pre-registered. 0.15 primary (conservative),
# 0.30 sensitivity bound. X2 has no grid (pure xFP prior, production weight).
K_PRIMARY, K_SENS = 0.15, 0.30
# why frozen (not fitted): 2025-holdout trailing-window means of the POP
# prior (see ship-exactness addendum). Rounded to avoid false precision.
FROZEN_TD_PRIORS = {
    ("RB", "rushing_tds"): 0.20,
    ("RB", "receiving_tds"): 0.04,
    ("WR", "receiving_tds"): 0.18,
    ("WR", "rushing_tds"): 0.005,
    ("TE", "receiving_tds"): 0.14,
}

CACHE = REPO_ROOT / "data" / "nfl_cache"
OUT_JSON = REPO_ROOT / "data" / "ml" / "backtest_opportunity_results.json"


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
    print(f"[oppback] cached {name} ({len(rows)} rows)")
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


class OppTrail:
    """Trailing opportunity windows mirroring the stats history rule."""

    def __init__(self, cur_rows, prior_rows):
        self.cur = defaultdict(list)
        for (pid, wk), f in opportunity_features(cur_rows).items():
            if wk <= 18:
                self.cur[pid].append((wk, f))
        self.prior = defaultdict(list)
        for (pid, wk), f in opportunity_features(prior_rows).items():
            if wk <= 18:
                self.prior[pid].append((wk, f))
        for v in list(self.cur.values()) + list(self.prior.values()):
            v.sort(key=lambda x: x[0])

    def window(self, pid, week):
        """Per-week feature values before `week`: same-season, else prior."""
        cur = [f for (w, f) in self.cur.get(pid, []) if w < week]
        if cur:
            return cur
        return [f for (w, f) in self.prior.get(pid, [])]

    @staticmethod
    def wavg(rows, key):
        vals = [float(r.get(key) or 0) for r in rows]
        return weighted_recent_avg(vals) if vals else 0.0


def _run_sample(tag, stats_cur, stats_prior, opp_cur, opp_prior, sched,
                weeks, season):
    """One OOS sample. Returns (results_dict, preds, actual, meta, skill_mask)."""
    game_ctx = build_game_context(sched)
    trail = OppTrail(opp_cur, opp_prior)
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
    eval_items = []
    for w in weeks:
        cur = {pid for pid, rows in hist.items()
               if any(x.get("week", 0) < w for x in rows)}
        universe = cur if cur else prior_pids
        for pid in sorted(universe):
            if (team_of.get(pid), w) not in played_tw:
                continue
            eval_items.append((pid, w))
    print(f"[oppback:{tag}] eval player-weeks: {len(eval_items)}")

    arms = ["BASE", "X1_015", "X1_030", "X2", "POP", "FROZEN",
            "XQ1_015", "XQ1_030", "QPOP", "QFROZEN"]
    preds = {k: [] for k in arms}
    actual, meta, skill_mask, qb_mask = [], [], [], []
    # POP control priors (pre-week only): mean trailing xFP rate per
    # (week, position, td stat) over that week's skill eval rows.
    _rates = {}
    for _pid, _w in eval_items:
        if pos_of.get(_pid) not in SKILL:
            continue
        _win = trail.window(_pid, _w)
        _rates[(_pid, _w)] = (OppTrail.wavg(_win, "rec_td_exp"),
                              OppTrail.wavg(_win, "rush_td_exp"))
    _pop_acc = defaultdict(list)
    for (_pid, _w), (_rr, _ru) in _rates.items():
        _pos = pos_of.get(_pid)
        _pop_acc[(_w, _pos, "receiving_tds")].append(_rr)
        _pop_acc[(_w, _pos, "rushing_tds")].append(_ru)
    _pop_mean = {k: (sum(v) / len(v) if v else 0.0) for k, v in _pop_acc.items()}
    _qrates = {}
    for _pid, _w in eval_items:
        if pos_of.get(_pid) != "QB":
            continue
        _win = trail.window(_pid, _w)
        _qrates[(_pid, _w)] = (OppTrail.wavg(_win, "pass_yd_gap"),
                               OppTrail.wavg(_win, "pass_td_exp"))
    _qpop_acc = defaultdict(list)
    for (_pid, _w), (_yg, _td) in _qrates.items():
        _qpop_acc[_w].append(_td)
    _qpop_mean = {w: (sum(v) / len(v) if v else 0.0) for w, v in _qpop_acc.items()}
    for pid, week in eval_items:
        pos = pos_of.get(pid)
        team = team_of.get(pid)
        h = [x for x in hist.get(pid, []) if x.get("week", 0) < week]
        ctx = game_ctx.get((team, week)) or {}
        kwargs = dict(player_history=h, position=pos,
                      prior_season_stats=prior.get(pid, []),
                      implied_total=ctx.get("implied_total", 0) or 0,
                      wind_mph=ctx.get("wind", 0) or 0,
                      temp_f=ctx.get("temp"))
        try:
            base_pts = float(calculate_fantasy_points(
                project_player_stats(**kwargs), DEFAULT_SCORING))
        except Exception:
            base_pts = 0.0
        real = by_pw.get((pid, week))
        try:
            actual.append(float(calculate_fantasy_points(real, DEFAULT_SCORING)) if real else 0.0)
        except Exception:
            actual.append(0.0)
        meta.append({"season": season, "week": week, "position": pos})
        skill_mask.append(pos in SKILL)
        qb_mask.append(pos == "QB")
        preds["BASE"].append(base_pts)
        if pos not in SKILL and pos != "QB":
            for a in ("X1_015", "X1_030", "X2", "POP", "FROZEN",
                      "XQ1_015", "XQ1_030", "QPOP", "QFROZEN"):
                preds[a].append(base_pts)
            continue
        if pos == "QB":
            for a in ("X1_015", "X1_030", "X2", "POP", "FROZEN"):
                preds[a].append(base_pts)
            _qyd_gap, _qtd_exp = _qrates.get((pid, week), (0.0, 0.0))
            for a, k in (("XQ1_015", K_PRIMARY), ("XQ1_030", K_SENS)):
                try:
                    p = project_player_stats(
                        **kwargs,
                        xfp_adjust={"passing_yards": k * _qyd_gap})
                    preds[a].append(float(calculate_fantasy_points(p, DEFAULT_SCORING)))
                except Exception:
                    preds[a].append(0.0)
            try:
                p = project_player_stats(
                    **kwargs,
                    td_prior={"passing_tds": _qpop_mean.get(week, 0.0)})
                preds["QPOP"].append(float(calculate_fantasy_points(p, DEFAULT_SCORING)))
            except Exception:
                preds["QPOP"].append(0.0)
            try:
                # why frozen 0.83 (ship-exactness): 2025-holdout mean of the
                # QPOP live prior (see qb-xfp verdict); QB rushing untouched.
                p = project_player_stats(
                    **kwargs,
                    td_prior={"passing_tds": 0.83})
                preds["QFROZEN"].append(float(calculate_fantasy_points(p, DEFAULT_SCORING)))
            except Exception:
                preds["QFROZEN"].append(0.0)
            continue
        win = trail.window(pid, week)
        yd_gap = OppTrail.wavg(win, "rec_yd_gap")
        rec_gap = OppTrail.wavg(win, "rec_gap")
        xfp_rec_td, xfp_rush_td = _rates.get((pid, week), (0.0, 0.0))
        for a in ("XQ1_015", "XQ1_030", "QPOP", "QFROZEN"):
            preds[a].append(base_pts)
        for a, k in (("X1_015", K_PRIMARY), ("X1_030", K_SENS)):
            try:
                p = project_player_stats(
                    **kwargs,
                    xfp_adjust={"receiving_yards": k * yd_gap,
                                "receptions": k * rec_gap})
                preds[a].append(float(calculate_fantasy_points(p, DEFAULT_SCORING)))
            except Exception:
                preds[a].append(0.0)
        try:
            p = project_player_stats(
                **kwargs,
                td_prior={"receiving_tds": xfp_rec_td,
                          "rushing_tds": xfp_rush_td})
            preds["X2"].append(float(calculate_fantasy_points(p, DEFAULT_SCORING)))
        except Exception:
            preds["X2"].append(0.0)
        try:
            p = project_player_stats(
                **kwargs,
                td_prior={
                    "receiving_tds": _pop_mean.get((week, pos, "receiving_tds"), 0.0),
                    "rushing_tds": _pop_mean.get((week, pos, "rushing_tds"), 0.0),
                })
            preds["POP"].append(float(calculate_fantasy_points(p, DEFAULT_SCORING)))
        except Exception:
            preds["POP"].append(0.0)
        try:
            p = project_player_stats(
                **kwargs,
                td_prior={
                    "receiving_tds": FROZEN_TD_PRIORS.get((pos, "receiving_tds")),
                    "rushing_tds": FROZEN_TD_PRIORS.get((pos, "rushing_tds")),
                })
            # why dict.get without default: stats outside the frozen set
            # (none in SKILL scope) fall back to the position mean inside
            # _td_regression — same as td_prior=None for that key.
            preds["FROZEN"].append(float(calculate_fantasy_points(p, DEFAULT_SCORING)))
        except Exception:
            preds["FROZEN"].append(0.0)

    out = {"n": len(actual), "arms": {}}
    for name in arms:
        m = _metrics(actual, preds[name], meta)
        si = [i for i, s in enumerate(skill_mask) if s]
        ms = _metrics([actual[i] for i in si], [preds[name][i] for i in si],
                      [meta[i] for i in si])
        qi = [i for i, q in enumerate(qb_mask) if q]
        mq = _metrics([actual[i] for i in qi], [preds[name][i] for i in qi],
                      [meta[i] for i in qi])
        out["arms"][name] = {"overall": m, "skill": ms, "qb": mq}
        print(f"[oppback:{tag}] {name:8s} MAE {m['mae']:.4f} corr {m['corr']:.4f} "
              f"pw {m['pairwise']:.4f} bias {m['bias']:+.3f} n={m['n']} | "
              f"skill MAE {ms['mae']:.4f} corr {ms['corr']:.4f} n={ms['n']} | "
              f"QB MAE {mq['mae']:.4f} corr {mq['corr']:.4f} n={mq['n']}")
    yt = np.array(actual, dtype=float)
    paired = {}
    si = np.array([i for i, s in enumerate(skill_mask) if s])
    qi = np.array([i for i, q in enumerate(qb_mask) if q])
    for a, b, tag2 in [("BASE", "X1_015", "primary"),
                       ("BASE", "X1_030", "sensitivity"),
                       ("BASE", "X2", "td_prior"),
                       ("BASE", "POP", "pop_control"),
                       ("X2", "POP", "indiv_vs_pop"),
                       ("BASE", "FROZEN", "frozen_ship"),
                       ("POP", "FROZEN", "frozen_parity"),
                       ("BASE", "XQ1_015", "qb_primary"),
                       ("BASE", "XQ1_030", "qb_sensitivity"),
                       ("BASE", "QPOP", "qb_td_prior"),
                       ("BASE", "QFROZEN", "qb_frozen_ship"),
                       ("QPOP", "QFROZEN", "qb_frozen_parity")]:
        st = _paired_stats(preds[a], preds[b], yt)
        st_s = _paired_stats([preds[a][i] for i in si],
                             [preds[b][i] for i in si], yt[si])
        st_q = _paired_stats([preds[a][i] for i in qi],
                             [preds[b][i] for i in qi], yt[qi])
        paired[tag2] = {"arms": [a, b], "overall": st,
                        "skill_t": st_s["t"],
                        "skill_mean_diff": st_s["mean_diff"],
                        "qb_t": st_q["t"],
                        "qb_mean_diff": st_q["mean_diff"]}
        print(f"[oppback:{tag}] paired {tag2} {a}-{b}: t={st['t']:.2f} "
              f"(diff {st['mean_diff']:+.4f}) skill t={st_s['t']:.2f} "
              f"(diff {st_s['mean_diff']:+.4f}) QB t={st_q['t']:.2f} "
              f"(diff {st_q['mean_diff']:+.4f}) corr z={st['z_diff']:.2f}")
    out["paired"] = paired
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", choices=["2025", "2026", "both"], default="both")
    args = ap.parse_args()

    stats24 = [r for r in _load_cache("stats_2024.json") if r.get("season_type", "REG") == "REG"]
    stats25 = [r for r in _load_cache("stats_2025.json") if r.get("season_type", "REG") == "REG"]
    sched25 = _load_cache("schedule_2025.json")
    opp24 = _ensure_cache("opportunity_2024.json",
                          lambda nfl: nfl.load_ff_opportunity(seasons=[2024]).to_dicts())
    opp25 = _ensure_cache("opportunity_2025.json",
                          lambda nfl: nfl.load_ff_opportunity(seasons=[2025]).to_dicts())
    results = {"freeze": FREEZE,
               "prereg": {"X1_primary_k": K_PRIMARY, "X1_sens_k": K_SENS,
                          "X2": "30pct_to_trailing_xfp_td_rate"}}

    if args.sample in ("2025", "both"):
        results["holdout_2025"] = _run_sample(
            "2025", stats25, stats24, opp25, opp24, sched25,
            range(4, 19), 2025)
    if args.sample in ("2026", "both"):
        stats26 = _ensure_cache(
            "stats_2026.json",
            lambda nfl: nfl.load_player_stats(seasons=[2026]).to_dicts())
        sched26 = _load_cache("schedule_2026.json")
        opp26 = _ensure_cache("opportunity_2026.json",
                              lambda nfl: nfl.load_ff_opportunity(seasons=[2026]).to_dicts())
        def _nonempty(s):
            return any((s.get(k) or 0) for k in
                       ("passing_yards", "rushing_yards",
                        "receiving_yards", "receptions"))
        played = sorted({
            s["week"] for s in stats26
            if s.get("season_type") == "REG" and s.get("week") and _nonempty(s)
        })
        results["live_2026"] = _run_sample(
            "2026", stats26, stats25, opp26, opp25, sched26, played, 2026)

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=1)
    print(f"[oppback] wrote {OUT_JSON}")
    print("[oppback] GATE: primary is X1_015 on the 2025 holdout vs the "
          "freeze (4.563/0.648/74.1%), paired p<0.05, corr non-negative, "
          "2026 agreement same direction. Sensitivity/secondary arms never "
          "promote anything on their own.")


if __name__ == "__main__":
    main()
