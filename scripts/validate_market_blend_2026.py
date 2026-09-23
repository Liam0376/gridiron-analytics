#!/usr/bin/env python3
"""Live gate for the market blend (spec 2026-09-23-market-blend, plan Task 4).

Grades market_snapshots (model, Sleeper market and blend points, all frozen
BEFORE each player's kickoff by refresh) against real 2026 box scores.
Same scope as the backtest: box-score rows (player played), QB/RB/WR/TE,
true scoring via calculate_fantasy_points + DEFAULT_SCORING.

Gate (config.py): weeks >= 4, n >= MARKET_BLEND_GATE_MIN_ROWS, blend MAE
below model with paired-t on |err| >= MARKET_BLEND_GATE_T, corr and
pairwise not worse. Passing the gate does NOT flip MARKET_BLEND_ENABLED;
that needs Liam's confirm (plan Task 5).

Usage: .venv/bin/python scripts/validate_market_blend_2026.py [--season 2026]
Writes data/models/market_blend_2026.json.
"""
import argparse
import json
import math
import os
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from ffanalytics.config import MARKET_BLEND_GATE_MIN_ROWS, MARKET_BLEND_GATE_T  # noqa: E402
from ffanalytics.scoring import calculate_fantasy_points, DEFAULT_SCORING  # noqa: E402

OUT = REPO_ROOT / "data" / "models" / "market_blend_2026.json"
GATE_MIN_WEEK = 4


def _metrics(rows, key):
    y = [r["actual"] for r in rows]
    p = [r[key] for r in rows]
    n = len(y)
    mae = sum(abs(a - b) for a, b in zip(p, y)) / n
    mp, my = sum(p) / n, sum(y) / n
    sp = math.sqrt(sum((v - mp) ** 2 for v in p))
    sy = math.sqrt(sum((v - my) ** 2 for v in y))
    corr = sum((a - mp) * (b - my) for a, b in zip(p, y)) / (sp * sy) if sp and sy else 0.0
    by_week = defaultdict(list)
    for r in rows:
        by_week[r["week"]].append((r[key], r["actual"]))
    ok = tot = 0
    for wr in by_week.values():
        for i in range(len(wr)):
            for j in range(i + 1, len(wr)):
                if wr[i][0] == wr[j][0]:
                    continue
                ok += (wr[i][0] > wr[j][0]) == (wr[i][1] > wr[j][1])
                tot += 1
    return {"mae": mae, "corr": corr, "pairwise": ok / tot if tot else 0.0, "n": n}


def _paired_t(rows):
    d = [abs(r["model"] - r["actual"]) - abs(r["blend"] - r["actual"]) for r in rows]  # >0: blend better
    n = len(d)
    if n < 2:
        return 0.0
    m = sum(d) / n
    sd = math.sqrt(sum((x - m) ** 2 for x in d) / (n - 1))
    return m / (sd / math.sqrt(n)) if sd else 0.0


def grade(snapshots, actual_pts, min_rows=MARKET_BLEND_GATE_MIN_ROWS, t_gate=MARKET_BLEND_GATE_T):
    """snapshots: dicts with week/player_id/model_points/blend_points/market_points.
    actual_pts: {(week, player_id): points} for players who played.
    -> {"weeks": {...}, "gate_scope": {...}, "gate": {...}}"""
    rows = [{"week": s["week"], "model": s["model_points"], "blend": s["blend_points"],
             "market": s["market_points"], "actual": actual_pts[(s["week"], s["player_id"])]}
            for s in snapshots if (s["week"], s["player_id"]) in actual_pts]
    weeks = {}
    for w in sorted({r["week"] for r in rows}):
        wr = [r for r in rows if r["week"] == w]
        weeks[w] = {"model": _metrics(wr, "model"), "blend": _metrics(wr, "blend"), "paired_t": _paired_t(wr)}
    scope = [r for r in rows if r["week"] >= GATE_MIN_WEEK]
    out = {"weeks": weeks, "gate_scope": None,
           "gate": {"min_week": GATE_MIN_WEEK, "min_rows": min_rows, "t": t_gate, "n": len(scope),
                    "status": "WAITING", "reason": f"n={len(scope)} < {min_rows}"}}
    if len(scope) >= 2:
        mm, mb, t = _metrics(scope, "model"), _metrics(scope, "blend"), _paired_t(scope)
        out["gate_scope"] = {"model": mm, "blend": mb, "paired_t": t}
        if len(scope) >= min_rows:
            passed = (mb["mae"] < mm["mae"] and t >= t_gate
                      and mb["corr"] >= mm["corr"] and mb["pairwise"] >= mm["pairwise"])
            out["gate"]["status"] = "PASS" if passed else "FAIL"
            out["gate"]["reason"] = (f"MAE {mb['mae']:.3f} vs {mm['mae']:.3f}, t={t:.2f}, corr {mb['corr']:.3f} "
                                     f"vs {mm['corr']:.3f}, pw {mb['pairwise']:.3f} vs {mm['pairwise']:.3f}")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", type=int, default=2026)
    a = ap.parse_args()
    db_path = os.environ.get("FFANALYTICS_DB_PATH") or str(REPO_ROOT / "data" / "fantasy.db")
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    snaps = [dict(r) for r in conn.execute(
        "SELECT week, player_id, model_points, market_points, blend_points FROM market_snapshots "
        "WHERE season = ?", (a.season,))]
    print(f"[mblend] {len(snaps)} pre-kickoff snapshot rows, weeks {sorted({s['week'] for s in snaps})}")
    import nflreadpy as nfl
    stats = [s for s in nfl.load_player_stats(seasons=[a.season]).to_dicts()
             if s.get("season_type", "REG") == "REG" and s.get("position") in ("QB", "RB", "WR", "TE")]
    actual = {(s["week"], str(s["player_id"])): float(calculate_fantasy_points(s, DEFAULT_SCORING)) for s in stats}
    res = grade(snaps, actual)
    for w, m in res["weeks"].items():
        print(f"[mblend] wk{w:>2} n={m['model']['n']:>4} model {m['model']['mae']:.3f} "
              f"blend {m['blend']['mae']:.3f} t={m['paired_t']:.2f}")
    g = res["gate"]
    print(f"[mblend] gate (weeks>={g['min_week']}): {g['status']} n={g['n']}/{g['min_rows']} {g['reason']}")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(res, indent=1, default=str))
    print(f"[mblend] wrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
