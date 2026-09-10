#!/usr/bin/env python3
"""Honest OOS coverage check on REAL 2026 games, as they get played.

why this exists (statistician-audit finding, 2026-09-10): data/models/
coverage_2025.json's 82% coverage number was measured by calibrating
residuals on 2024 train and evaluating once on 2025 holdout — both
seasons, both fully in the past by the time this was written. That's
correct methodology for what it measures (residuals fit on 2024 didn't
leak into the 2025 test), but it says nothing about whether the SAME
frozen widths still hold on data that didn't exist when they were frozen.
This script closes that gap: for each 2026 week that's actually been
played, build the exact same pre-game projection (project_player_stats +
compute_conformal_bounds, the real production functions, not a
backtest-only reimplementation) using only data available before that
week, then check whether the REAL final stat line landed inside the
interval. n starts at whatever one week of a 12-team league's rostered
players gives — small, explicitly flagged as such below, not smoothed
over. Re-run this as more 2026 weeks complete; the n grows and the
number gets more meaningful. This is a measurement script — it never
touches POS_RESIDUALS or retunes anything, same discipline as
coverage_2025.json's own "widths frozen" rule.

Audit 22.0: saves per-week coverage to data/models/coverage_2026_history.json
for time-series tracking across re-runs.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import nflreadpy as nfl
from ffanalytics.stat_projector import build_weekly_projections, compute_conformal_bounds
from ffanalytics.scoring import calculate_fantasy_points
from ffanalytics.adapters import schedule as sched_adapter

HISTORY_PATH = Path(__file__).resolve().parent.parent / "data" / "models" / "coverage_2026_history.json"


def main():
    season = 2026
    prior_season = season - 1

    player_stats_2026 = nfl.load_player_stats(seasons=[season]).to_dicts()
    played_weeks = sorted({
        s["week"] for s in player_stats_2026
        if s.get("season_type") == "REG" and not _is_empty_row(s)
    })
    if not played_weeks:
        print("No 2026 weeks played yet - nothing to validate.")
        return

    prior_stats = nfl.load_player_stats(seasons=[prior_season]).to_dicts()
    sched = sched_adapter.get_schedule(season, week=None)

    hits = 0
    total = 0
    by_pos_hits = {}
    by_pos_total = {}

    for wk in played_weeks:
        # Same-season history strictly before this week - real production
        # rule (stat_projector.py's fail-closed week<target_week filter),
        # not a lookahead.
        same_season_history = [s for s in player_stats_2026 if s.get("week", 0) < wk]
        projs = build_weekly_projections(
            same_season_history, sched, target_week=wk,
            scoring_settings={}, prior_season_stats=prior_stats,
        )
        actual_by_pid = {
            str(s["player_id"]): s for s in player_stats_2026
            if s.get("week") == wk and s.get("season_type") == "REG" and not _is_empty_row(s)
        }
        for pr in projs:
            pid = str(pr.get("player_id", ""))
            actual_row = actual_by_pid.get(pid)
            if actual_row is None or pr.get("is_empty_projection"):
                continue
            fpts_actual = calculate_fantasy_points(actual_row, {})
            fpts_proj = calculate_fantasy_points(pr, {})
            bounds = compute_conformal_bounds(fpts_proj, pr["position"])
            hit = bounds["lower_bound"] <= fpts_actual <= bounds["upper_bound"]
            total += 1
            hits += int(hit)
            pos = pr["position"]
            by_pos_total[pos] = by_pos_total.get(pos, 0) + 1
            by_pos_hits[pos] = by_pos_hits.get(pos, 0) + int(hit)

    print(f"2026 weeks played so far: {played_weeks}")
    print(f"n = {total} player-weeks (SMALL SAMPLE - do not treat as conclusive until n >> 100)")
    if total == 0:
        print("No overlapping player-weeks to score.")
        return
    overall = hits / total
    print(f"overall coverage: {overall:.4f}  (target 0.80, from POS_RESIDUALS - frozen, not retuned here)")
    print("by position:")
    by_pos = {}
    for pos in sorted(by_pos_total):
        n = by_pos_total[pos]
        cov = by_pos_hits[pos] / n
        by_pos[pos] = {"hits": by_pos_hits[pos], "total": n, "coverage": round(cov, 4)}
        print(f"  {pos}: {cov:.4f}  (n={n})")

    # Audit 22.0: save per-week snapshot for time-series tracking
    _save_history(played_weeks, total, hits, overall, by_pos)


def _is_empty_row(row: dict) -> bool:
    keys = ("passing_yards", "rushing_yards", "receiving_yards", "receptions")
    return all(not (row.get(k) or 0) for k in keys)


def _save_history(played_weeks, total, hits, overall, by_pos):
    """Append this run's snapshot to coverage_2026_history.json.

    Each entry: {timestamp, weeks_played, n, hits, coverage, by_pos}.
    The file is a JSON array; we load, append, and write back. If the
    file is corrupted, we start fresh (measurement must never abort).
    """
    import datetime
    HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    history = []
    if HISTORY_PATH.exists():
        try:
            history = json.loads(HISTORY_PATH.read_text())
            if not isinstance(history, list):
                history = []
        except Exception:
            history = []
    history.append({
        "timestamp": datetime.datetime.now().isoformat(),
        "weeks_played": played_weeks,
        "n": total,
        "hits": hits,
        "coverage": round(overall, 4),
        "by_pos": by_pos,
    })
    try:
        HISTORY_PATH.write_text(json.dumps(history, indent=2))
        print(f"\nSaved coverage snapshot to {HISTORY_PATH.name} ({len(history)} entries)")
    except Exception as exc:
        print(f"\nWarning: could not save history: {exc}")


if __name__ == "__main__":
    main()
