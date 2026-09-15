#!/usr/bin/env python3
"""ECR divergence calibration (ecr-baseline plan, Task 2).

Measures model rank vs ECR rank vs ACTUAL finish rank — agreement rate,
per-position Spearman, and disagreement outcomes at the edge-rule ±12
threshold (who was right when model and ECR differ). No model change, no
tuning: measurement that sets the "beat ECR" bar future challengers clear.

ECR sources (all $0, existing data only):
  2025: type='all' archive, weekly Friday scrapes (PPR rb/wr/te, qb, k,
  dst). Week w uses max scrape <= first-kickoff+3d (i.e. the Friday ECR
  for that weekend). Thursday-game players are EXCLUDED for their week
  (their game kicked off before the Friday scrape = outcome contamination).
  2026: same from the archive when present, else skipped with a note
  (type='week' live gives current week only, never history).

Model ranks: BASE pipeline (project_player_stats, no-out, no flags) under
the standard all-universe discipline; per-week positional ranks by
projected points. Actual ranks: same universe, fantasy points via
scoring.DEFAULT_SCORING. Common-players only per comparison.

Spearman = Pearson-on-average-ranks (vanilla numpy, no scipy).

Repro: PYTHONHASHSEED=0. Archive fetch is large (filtered to weekly skill
pages before caching); everything else reuses data/nfl_cache/.
"""
import argparse
import json
import math
import os
import sys
from collections import defaultdict
from datetime import date, timedelta
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
)
from ffanalytics.scoring import calculate_fantasy_points, DEFAULT_SCORING  # noqa: E402

CACHE = REPO_ROOT / "data" / "nfl_cache"
OUT_JSON = REPO_ROOT / "data" / "ml" / "backtest_ecr_results.json"
# why v2 (2026-09-15): v1 filtered out the weekly-op (overall) page, which
# the overall-rank threshold sweep needs. Delete v1 to refetch.
ARCH_CACHE = "ecr_archive_weekly_v2.json"
POSITIONS = ("QB", "RB", "WR", "TE", "K")
WEEKLY_TYPES = {"weekly-qb", "weekly-rb", "weekly-wr", "weekly-te",
                "weekly-k", "weekly-dst", "weekly-op"}
EDGE_THRESHOLD = 12  # status-quo flat threshold (comparison/_edge.py)
THRESHOLD_GRID = (6, 8, 10, 12)


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
    print(f"[ecrback] cached {name} ({len(rows)} rows)")
    return rows


def _ranks(x):
    """Average ranks (1-based) for Spearman."""
    x = np.asarray(x, dtype=float)
    order = np.argsort(x, kind="stable")
    ranks = np.empty(len(x))
    i = 0
    while i < len(x):
        j = i
        while j + 1 < len(x) and x[order[j + 1]] == x[order[i]]:
            j += 1
        ranks[order[i:j + 1]] = (i + j) / 2 + 1
        i = j + 1
    return ranks


def _spearman(a, b):
    if len(a) < 5:
        return None
    ra, rb = _ranks(a), _ranks(b)
    sa, sb = float(np.std(ra)), float(np.std(rb))
    if sa == 0 or sb == 0:
        return None
    return float(np.mean((ra - np.mean(ra)) * (rb - np.mean(rb))) / (sa * sb))


def _load_archive_weekly():
    def _fetch(nfl):
        rows = nfl.load_ff_rankings(type="all").to_dicts()
        keep = []
        for r in rows:
            if str(r.get("page_type")) not in WEEKLY_TYPES:
                continue
            keep.append({
                "scrape_date": str(r.get("scrape_date") or ""),
                "page_type": str(r.get("page_type") or ""),
                "fpid": str(r.get("id") or ""),
                "name": r.get("player") or "",
                "pos": str(r.get("pos") or "").upper(),
                "team": str(r.get("team") or r.get("tm") or "").upper(),
                "ecr": r.get("ecr"),
            })
        return keep
    return _ensure_cache(ARCH_CACHE, _fetch)


def _thursday_teams(sched, week, cutoff_iso):
    """Teams whose week-game kicked off strictly before the ECR scrape."""
    out = set()
    for g in sched:
        if g.get("game_type") != "REG" or g.get("week") != week:
            continue
        gd = str(g.get("gameday") or "")
        if gd and gd < cutoff_iso:
            if g.get("home_team"):
                out.add(g.get("home_team"))
            if g.get("away_team"):
                out.add(g.get("away_team"))
    return out


def _ecr_for_week(arch, sched, week):
    """(ecr_by_fpid, pos_of, scrape) for REG week, or (None, None, None)."""
    first = min((str(g.get("gameday") or "") for g in sched
                 if g.get("game_type") == "REG" and g.get("week") == week
                 and g.get("gameday")), default="")
    if not first:
        return None, None, None
    # why +3d via date math: Friday scrapes fall within
    # (first_thursday, first_sunday]; max scrape <= first+3d is that weekend.
    y, m, d = int(first[:4]), int(first[5:7]), int(first[8:10])
    limit = (date(y, m, d) + timedelta(days=3)).isoformat()
    cand = sorted({r["scrape_date"] for r in arch
                   if r["scrape_date"] and r["scrape_date"] <= limit})
    if not cand:
        return None, None, None
    scrape = cand[-1]
    rows = [r for r in arch if r["scrape_date"] == scrape]
    by_fpid, pos_of = {}, {}
    order = defaultdict(list)
    overall = []
    for r in rows:
        try:
            e = float(r["ecr"]) if r["ecr"] is not None else None
        except Exception:
            e = None
        if e is None or not r["fpid"]:
            continue
        if r.get("page_type") == "weekly-op":
            overall.append((e, r["fpid"]))
            continue
        by_fpid[r["fpid"]] = e
        pos_of[r["fpid"]] = r["pos"]
        order[r["pos"]].append((e, r["fpid"]))
    pos_rank = {}
    for pos, lst in order.items():
        lst.sort()
        for i, (_, fpid) in enumerate(lst, start=1):
            pos_rank[fpid] = i
    overall.sort()
    overall_rank = {fpid: i for i, (_, fpid) in enumerate(overall, start=1)}
    early = _thursday_teams(sched, week, scrape)
    return {"ecr": by_fpid, "pos_rank": pos_rank, "pos": pos_of,
            "overall_rank": overall_rank,
            "scrape": scrape, "early_teams": sorted(early)}, None, None


def _model_week(stats_cur, stats_prior, sched, week, fpid_by_gsis):
    """BASE projections + actuals for one week. Returns {gsis: dict}."""
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
    cur = {pid for pid, rows in hist.items()
           if any(x.get("week", 0) < week for x in rows)}
    out = {}
    for pid in sorted(cur if cur else prior_pids):
        if (team_of.get(pid), week) not in played_tw:
            continue
        pos = pos_of.get(pid)
        h = [x for x in hist.get(pid, []) if x.get("week", 0) < week]
        ctx = game_ctx.get((team_of.get(pid), week)) or {}
        try:
            proj = project_player_stats(
                player_history=h, position=pos,
                prior_season_stats=prior.get(pid, []),
                implied_total=ctx.get("implied_total", 0) or 0,
                wind_mph=ctx.get("wind", 0) or 0, temp_f=ctx.get("temp"))
            pts = float(calculate_fantasy_points(proj, DEFAULT_SCORING))
        except Exception:
            pts = 0.0
        real = by_pw.get((pid, week))
        try:
            pa = float(calculate_fantasy_points(real, DEFAULT_SCORING)) if real else 0.0
        except Exception:
            pa = 0.0
        out[pid] = {"pos": pos, "team": team_of.get(pid), "proj": pts,
                    "actual": pa,
                    "fpid": (fpid_by_gsis or {}).get(pid)}
    return out


def _calibrate_week(model, ecr, early_teams):
    """Rank-level comparison on common players. Returns per-pos dicts."""
    by_pos = defaultdict(list)
    for pid, m in model.items():
        if not m["fpid"] or m["fpid"] not in ecr["ecr"]:
            continue
        if m["team"] in (early_teams or set()):
            continue
        by_pos[m["pos"]].append({
            "proj": m["proj"], "actual": m["actual"],
            "ecr_rank": ecr["pos_rank"][m["fpid"]],
        })
    res = {}
    for pos, rows in by_pos.items():
        if len(rows) < 5:
            continue
        # positional ranks within this week's common set
        order_m = np.argsort([-r["proj"] for r in rows], kind="stable")
        order_a = np.argsort([-r["actual"] for r in rows], kind="stable")
        mr = np.empty(len(rows))
        ar = np.empty(len(rows))
        mr[order_m] = np.arange(1, len(rows) + 1)
        ar[order_a] = np.arange(1, len(rows) + 1)
        er = np.array([r["ecr_rank"] for r in rows], dtype=float)
        sp_m = _spearman(mr, ar)
        sp_e = _spearman(er, ar)
        # disagreements at the edge threshold: who was closer to actual?
        mw = ew = ties = 0
        for i in range(len(rows)):
            if abs(float(mr[i]) - float(er[i])) < EDGE_THRESHOLD:
                continue
            dm, de = abs(float(mr[i]) - float(ar[i])), abs(float(er[i]) - float(ar[i]))
            if dm < de:
                mw += 1
            elif de < dm:
                ew += 1
            else:
                ties += 1
        res[pos] = {"n": len(rows), "spearman_model": sp_m,
                    "spearman_ecr": sp_e,
                    "disagree_n": mw + ew + ties,
                    "model_wins": mw, "ecr_wins": ew, "ties": ties}
    return res


def _sweep_overall_thresholds(model, ecr, early_teams):
    """Overall-rank disagreement sweep per player position.

    Same quantity comparison/_edge.py rules on (overall ECR rank vs model
    overall rank): for T in THRESHOLD_GRID, players with |model - ecr| >= T
    count a win for whichever rank was closer to the actual overall rank.
    Returns {pos: {T: [mw, ew]}}.
    """
    common = []
    for pid, m in model.items():
        if not m["fpid"] or m["fpid"] not in ecr["overall_rank"]:
            continue
        if m["team"] in (early_teams or set()):
            continue
        common.append((pid, m["pos"], m["proj"], m["actual"],
                       ecr["overall_rank"][m["fpid"]]))
    if len(common) < 5:
        return {}
    order_m = np.argsort([-c[2] for c in common], kind="stable")
    order_a = np.argsort([-c[3] for c in common], kind="stable")
    mr = np.empty(len(common))
    ar = np.empty(len(common))
    mr[order_m] = np.arange(1, len(common) + 1)
    ar[order_a] = np.arange(1, len(common) + 1)
    out = defaultdict(lambda: defaultdict(lambda: [0, 0]))
    for i, (_, pos, _, _, er) in enumerate(common):
        for t in THRESHOLD_GRID:
            if abs(float(mr[i]) - float(er)) < t:
                continue
            if abs(float(mr[i]) - float(ar[i])) < abs(float(er) - float(ar[i])):
                out[pos][t][0] += 1
            else:
                out[pos][t][1] += 1
    return {p: {t: v for t, v in sorted(d.items())} for p, d in out.items()}


def _run_sample(tag, stats_cur, stats_prior, sched, weeks, season,
                arch, fpid_by_gsis):
    per_week, agg = {}, defaultdict(lambda: {"n": 0, "sm": [], "se": [],
                                             "mw": 0, "ew": 0, "ties": 0,
                                             "dn": 0})
    sweep_agg = defaultdict(lambda: [0, 0])
    for w in weeks:
        ecr, _, _ = _ecr_for_week(arch, sched, w)
        if ecr is None:
            print(f"[ecrback:{tag}] week {w}: no ECR scrape — skipped")
            continue
        model = _model_week(stats_cur, stats_prior, sched, w, fpid_by_gsis)
        early = set(ecr["early_teams"])
        cal = _calibrate_week(model, ecr, early)
        sweep = _sweep_overall_thresholds(model, ecr, early)
        per_week[str(w)] = {"scrape": ecr["scrape"], "early_teams": ecr["early_teams"],
                            "pos": cal}
        for p, dd in sweep.items():
            for t, (mw, ew) in dd.items():
                sweep_agg[(p, t)][0] += mw
                sweep_agg[(p, t)][1] += ew
        line = " ".join(
            f"{p}:n={c['n']} spM={c['spearman_model']:+.3f} spE={c['spearman_ecr']:+.3f} "
            f"d={c['disagree_n']}(M{c['model_wins']}/E{c['ecr_wins']})"
            for p, c in sorted(cal.items()))
        print(f"[ecrback:{tag}] wk{w} scrape={ecr['scrape']} early-out={len(early)} {line}")
        for p, c in cal.items():
            a = agg[p]
            a["n"] += c["n"]
            if c["spearman_model"] is not None:
                a["sm"].append(c["spearman_model"])
            if c["spearman_ecr"] is not None:
                a["se"].append(c["spearman_ecr"])
            a["mw"] += c["model_wins"]
            a["ew"] += c["ecr_wins"]
            a["ties"] += c["ties"]
            a["dn"] += c["disagree_n"]
    summary = {}
    for p, a in sorted(agg.items()):
        summary[p] = {
            "weeks": len([w for w in per_week if p in per_week[w]["pos"]]),
            "n": a["n"],
            "spearman_model_mean": round(float(np.mean(a["sm"])), 4) if a["sm"] else None,
            "spearman_ecr_mean": round(float(np.mean(a["se"])), 4) if a["se"] else None,
            "disagree_n": a["dn"], "model_wins": a["mw"],
            "ecr_wins": a["ew"], "ties": a["ties"],
        }
    print(f"[ecrback:{tag}] SUMMARY " + " ".join(
        f"{p}:spM={s['spearman_model_mean']} spE={s['spearman_ecr_mean']} "
        f"d={s['disagree_n']}(M{s['model_wins']}/E{s['ecr_wins']})"
        for p, s in sorted(summary.items())))
    # why pre-registered rule (point 4): per position, among thresholds with
    # n>=30 pick max model win-rate, tie-break toward 12 (status quo); best
    # <=50% keeps 12; K forced 12 (tiny n, documented). Frozen after this.
    recommended = {}
    for pos in sorted({p for (p, t) in sweep_agg}):
        cells = {t: sweep_agg[(pos, t)] for t in THRESHOLD_GRID
                 if sum(sweep_agg[(pos, t)]) >= 30}
        if pos == "K" or not cells:
            recommended[pos] = EDGE_THRESHOLD
            continue
        scored = sorted(
            ((mw / (mw + ew) if (mw + ew) else 0.0, -abs(t - EDGE_THRESHOLD), t)
             for t, (mw, ew) in cells.items()),
            reverse=True)
        best_rate, _, best_t = scored[0]
        recommended[pos] = best_t if best_rate > 0.50 else EDGE_THRESHOLD
    print(f"[ecrback:{tag}] THRESHOLDS " + " ".join(
        f"{p}={recommended[p]}"
        f"({';'.join(f'T{t}:{mw}/{ew}' for t, (mw, ew) in sorted(((t, sweep_agg[(p, t)]) for t in THRESHOLD_GRID), key=lambda x: x[0]))})"
        for p in sorted({p for (p, t) in sweep_agg})))
    return {"weeks": per_week, "summary": summary,
            "threshold_sweep": {f"{p}/T{t}": {"mw": mw, "ew": ew}
                                for (p, t), (mw, ew) in sorted(sweep_agg.items())},
            "recommended_thresholds": recommended}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", choices=["2025", "2026", "both"], default="both")
    args = ap.parse_args()

    arch = _load_archive_weekly()
    scrapes25 = sorted({r["scrape_date"] for r in arch if r["scrape_date"].startswith("2025-")})
    print(f"[ecrback] archive weekly rows: {len(arch)}; 2025 scrapes: {len(scrapes25)}")
    try:
        import nflreadpy as nfl
        pid_rows = nfl.load_ff_playerids().to_dicts()
    except Exception as exc:
        print(f"[ecrback] playerids fetch failed: {exc}")
        pid_rows = []
    fpid_by_gsis = {}
    for r in pid_rows or []:
        f, g = str(r.get("fantasypros_id") or "").strip(), str(r.get("gsis_id") or "").strip()
        if f and g and g not in fpid_by_gsis:
            fpid_by_gsis[g] = f
    print(f"[ecrback] fpid spine: {len(fpid_by_gsis)} gsis ids")

    stats24 = [r for r in _load_cache("stats_2024.json") if r.get("season_type", "REG") == "REG"]
    stats25 = [r for r in _load_cache("stats_2025.json") if r.get("season_type", "REG") == "REG"]
    sched25 = _load_cache("schedule_2025.json")
    results = {"edge_threshold": EDGE_THRESHOLD}

    if args.sample in ("2025", "both"):
        results["cal_2025"] = _run_sample(
            "2025", stats25, stats24, sched25, range(4, 19), 2025, arch, fpid_by_gsis)
    if args.sample in ("2026", "both"):
        try:
            stats26 = _ensure_cache(
                "stats_2026.json",
                lambda nfl: nfl.load_player_stats(seasons=[2026]).to_dicts())
        except Exception as exc:
            print(f"[ecrback] 2026 stats unavailable: {exc}")
            stats26 = []
        sched26 = _load_cache("schedule_2026.json")
        played = sorted({
            s["week"] for s in stats26
            if s.get("season_type") == "REG" and s.get("week")
            and any((s.get(k) or 0) for k in
                    ("passing_yards", "rushing_yards", "receiving_yards", "receptions"))
        }) if stats26 else []
        if played:
            results["cal_2026"] = _run_sample(
                "2026", stats26, stats25, sched26, played, 2026, arch, fpid_by_gsis)
        else:
            print("[ecrback] no 2026 weeks played — skipped")

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=1)
    print(f"[ecrback] wrote {OUT_JSON}")
    print("[ecrback] READ: measurement only — sets the 'beat ECR' bar; "
          "changes nothing regardless of outcome (spec).")


if __name__ == "__main__":
    main()
