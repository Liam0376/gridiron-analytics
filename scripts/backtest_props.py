#!/usr/bin/env python3
"""Calibration backtest: props fair lines on the 2025 holdout (weeks 4-18).

For each 2025 REG player-week (QB/RB/WR/TE): history = same-player 2025 weeks
< target (true OOS, same discipline as backtest_ml.py), prior = 2024 REG rows,
game ctx from the 2025 schedule via build_game_context. Fair lines come from
build_prop_fair_lines; each pairs with that week's ACTUAL stat.

Metrics per market — no book lines exist ($0 notebooks: manual entry only):
- normal markets: n, fair-line MAE, 80%-band coverage (target 0.80), PIT
  deciles + max_dev. Verdict via verdict_normal_market.
- anytime_td: n, base rate, Brier vs base-rate-naive, reliability bins +
  monotonic flag. Verdict via verdict_td_market.

Empty-history rows (is_empty_projection) are EXCLUDED from calibration (fair
0.0 + floor sigma would distort the sigmas under test) and counted separately.

Known quirks (same as fantasy backtests, not hidden):
- Schedule temp/wind are OBSERVED post-game values, live uses Open-Meteo
  forecast (see build_game_context docstring; measured impact small).
- Week 1 never evaluated (leakage-guard hole); K excluded v1 (no markets).

Downloads via adapters into memory only — writes NO cache files
(data/nfl_cache/ stays as-is). Writes data/props/backtest_props_results.json.
"""

import json
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from ffanalytics.adapters import nflverse, schedule as sched_adapter  # noqa: E402
from ffanalytics.props import (  # noqa: E402
    band_coverage,
    base_rate_brier,
    bins_monotonic,
    brier_score,
    build_prop_fair_lines,
    fair_mae,
    pit_deciles,
    reliability_bins,
    verdict_normal_market,
    verdict_td_market,
)
from ffanalytics.stat_projector import build_game_context  # noqa: E402

HOLDOUT_SEASON = 2025
PRIOR_SEASON = 2024
WEEKS = range(4, 19)
POSITIONS = ("QB", "RB", "WR", "TE")

# market -> positions evaluated (mirrors PROP_MARKETS scoping in props.py).
NORMAL_MARKETS = {
    "passing_yards": ("QB",),
    "passing_tds": ("QB",),
    "rushing_yards": ("QB", "RB", "WR", "TE"),
    "receiving_yards": ("RB", "WR", "TE"),
    "receptions": ("RB", "WR", "TE"),
}


def _f(v):
    try:
        f = float(v or 0)
    except (TypeError, ValueError):
        return 0.0
    return f if f == f and abs(f) != float("inf") else 0.0


def collect(stats_holdout, stats_prior, game_ctx):
    """Return (normal_obs, td_pairs, n_empty, n_total).

    normal_obs: market -> [(fair, sigma, actual)]. td_pairs: [(p_yes, hit)].
    """
    by_player = defaultdict(list)
    for s in stats_holdout:
        if s.get("season_type") != "REG":
            continue
        pid = s.get("player_id")
        if pid:
            by_player[str(pid)].append(s)
    prior_by_player = defaultdict(list)
    for s in stats_prior:
        if s.get("season_type") != "REG":
            continue
        pid = s.get("player_id")
        if pid:
            prior_by_player[str(pid)].append(s)

    normal_obs = defaultdict(list)
    td_pairs = []
    n_empty = 0
    n_total = 0

    for pid, games in by_player.items():
        by_week = {g.get("week"): g for g in games}
        for target in WEEKS:
            actual = by_week.get(target)
            if actual is None:
                continue
            pos = (actual.get("position") or "").upper()
            if pos not in POSITIONS:
                continue
            n_total += 1
            history = sorted(
                (g for g in games if (g.get("week") or 0) < target),
                key=lambda g: g.get("week") or 0,
            )
            team = actual.get("team") or actual.get("recent_team") or ""
            ctx = game_ctx.get((team, target)) or {}
            out = build_prop_fair_lines(
                history,
                pos,
                {
                    "implied_total": ctx.get("implied_total", 0) or 0,
                    "wind_mph": ctx.get("wind", 0) or 0,
                    "temp_f": ctx.get("temp"),
                },
                prior_season_stats=prior_by_player.get(pid),
                week=target,
            )
            if out["excluded"] or out["is_empty_projection"]:
                n_empty += 1
                continue
            for market, entry in out["markets"].items():
                if entry["model"] == "poisson":
                    rush = _f(actual.get("rushing_tds"))
                    recv = _f(actual.get("receiving_tds"))
                    td_pairs.append((entry["p_yes"], 1 if rush + recv > 0 else 0))
                elif market in NORMAL_MARKETS and pos in NORMAL_MARKETS[market]:
                    stat_key = {
                        "passing_yards": "passing_yards",
                        "passing_tds": "passing_tds",
                        "rushing_yards": "rushing_yards",
                        "receiving_yards": "receiving_yards",
                        "receptions": "receptions",
                    }[market]
                    normal_obs[market].append(
                        (entry["fair_line"], entry["sigma"], _f(actual.get(stat_key)))
                    )
    return normal_obs, td_pairs, n_empty, n_total


def evaluate(normal_obs, td_pairs, n_empty, n_total):
    """Per-market metrics + verdicts. Pure over collected observations."""
    markets = {}
    for market, obs in sorted(normal_obs.items()):
        pit = pit_deciles(obs)
        cov = band_coverage(obs)
        n = len(obs)
        markets[market] = {
            "kind": "normal",
            "n": n,
            "fair_mae": fair_mae(obs),
            "coverage_80": cov,
            "pit_max_dev": pit["max_dev"],
            "pit_deciles": [round(d, 4) for d in pit["deciles"]],
            "verdict": verdict_normal_market(n, cov, pit["max_dev"]),
        }
    if td_pairs:
        ps = [p for p, _ in td_pairs]
        ys = [y for _, y in td_pairs]
        naive = base_rate_brier(ys)
        brier = brier_score(td_pairs)
        bins = reliability_bins(td_pairs, k=5)
        mono = bins_monotonic(bins)
        n = len(td_pairs)
        markets["anytime_td"] = {
            "kind": "poisson",
            "n": n,
            "base_rate": sum(ys) / n,
            "brier": brier,
            "naive_brier": naive,
            "reliability_bins": [
                {"n": b["n"], "mean_pred": round(b["mean_pred"], 4),
                 "hit_rate": round(b["hit_rate"], 4)} for b in bins
            ],
            "bins_monotonic": mono,
            "verdict": verdict_td_market(n, brier, naive, mono),
        }
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "holdout_season": HOLDOUT_SEASON,
        "prior_season": PRIOR_SEASON,
        "weeks": [min(WEEKS), max(WEEKS)],
        "n_player_weeks": n_total,
        "n_empty_excluded": n_empty,
        "markets": markets,
        "notes": [
            "OOS: history = same-player holdout weeks < target; prior = 2024 REG.",
            "Empty-history rows excluded from calibration, counted separately.",
            "Schedule temp/wind are OBSERVED post-game (live uses Open-Meteo forecast).",
            "Week 1 not evaluated (leakage-guard hole stat_projector.py:512-513).",
            "K/DEF have no v1 markets (excluded by design).",
            "verdict edges_on requires n>=500, |coverage-0.80|<=0.05, PIT max_dev<=0.04 "
            "(normal) or beating base-rate Brier + monotonic bins (anytime_td).",
        ],
    }


def main():
    import argparse

    # why args, not constants (research-synthesist sign-off): single-season
    # calibration is one data point — reruns on other holdouts corroborate
    # without touching the 2025 verdicts that gate production.
    parser = argparse.ArgumentParser()
    parser.add_argument("--holdout", type=int, default=HOLDOUT_SEASON)
    parser.add_argument("--prior", type=int, default=PRIOR_SEASON)
    parser.add_argument("--out", default="data/props/backtest_props_results.json")
    args = parser.parse_args()
    holdout, prior = args.holdout, args.prior
    t0 = time.time()
    print(f"downloading {prior} + {holdout} weekly stats + {holdout} schedule (memory only) ...", flush=True)
    stats_holdout = nflverse.get_weekly_player_stats(holdout)
    stats_prior = nflverse.get_weekly_player_stats(prior)
    sched = sched_adapter.get_schedule(holdout)
    print(f"  holdout rows={len(stats_holdout)} prior rows={len(stats_prior)} "
          f"sched rows={len(sched)} ({time.time()-t0:.0f}s)", flush=True)
    game_ctx = build_game_context(sched)
    normal_obs, td_pairs, n_empty, n_total = collect(stats_holdout, stats_prior, game_ctx)
    print(f"  player-weeks={n_total} empty-excluded={n_empty} "
          f"({time.time()-t0:.0f}s)", flush=True)
    results = evaluate(normal_obs, td_pairs, n_empty, n_total)
    results["holdout_season"] = holdout
    results["prior_season"] = prior
    out_path = REPO_ROOT / args.out
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(results, indent=2))
    print(f"wrote {out_path} ({time.time()-t0:.0f}s total)", flush=True)
    for name, m in results["markets"].items():
        if m["kind"] == "normal":
            print(f"  {name:16s} n={m['n']:5d} MAE={m['fair_mae']:.3f} "
                  f"cov={m['coverage_80']:.3f} pitdev={m['pit_max_dev']:.3f} "
                  f"=> {m['verdict']}", flush=True)
        else:
            print(f"  {name:16s} n={m['n']:5d} base={m['base_rate']:.3f} "
                  f"brier={m['brier']:.4f} naive={m['naive_brier']:.4f} "
                  f"mono={m['bins_monotonic']} => {m['verdict']}", flush=True)


if __name__ == "__main__":
    main()
