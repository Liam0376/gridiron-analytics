#!/usr/bin/env python3
"""Weekly accuracy scorecard. Computes MAE, ME (bias), Spearman rho,
pairwise %, PICP, and CRPS per position for completed weeks.

Usage:
    # Grade 2026 week 1 from market_consensus (once actual_points populated):
    .venv/bin/python scripts/scorecard.py --season 2026 --week 1

    # Grade from backtest JSONL (has projected + actual already):
    .venv/bin/python scripts/scorecard.py --jsonl data/ml/backtest_results.jsonl

    # Grade 2025 holdout by scoring raw stats from player_stats blob:
    .venv/bin/python scripts/scorecard.py --season 2025 --all-weeks

Data sources:
    - market_consensus: model_points, market_points, actual_points per player-week
    - player_stats week=0 blob: per-player-per-week nflverse stat lines (2025)
    - projection_snapshots (future): frozen per-week projections for live grading
    - JSONL file: rows with projected_points/actual_points fields

Output: data/models/scorecard_<label>.json + stdout summary table.
"""

import argparse
import json
import math
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from ffanalytics.scoring import calculate_fantasy_points, DEFAULT_SCORING
from ffanalytics.config import DB_PATH


POSITIONS = ("QB", "RB", "WR", "TE", "K")
MIN_POINTS_THRESHOLD = 0.5


def _spearman(x: list[float], y: list[float]) -> float | None:
    n = len(x)
    if n < 3:
        return None

    def _rank(vals):
        indexed = sorted(range(n), key=lambda i: vals[i])
        ranks = [0.0] * n
        i = 0
        while i < n:
            j = i
            while j < n - 1 and vals[indexed[j]] == vals[indexed[j + 1]]:
                j += 1
            avg_rank = (i + j) / 2.0 + 1
            for k in range(i, j + 1):
                ranks[indexed[k]] = avg_rank
            i = j + 1
        return ranks

    rx, ry = _rank(x), _rank(y)
    d2 = sum((a - b) ** 2 for a, b in zip(rx, ry))
    return 1 - (6 * d2) / (n * (n * n - 1))


def _pairwise(projected: list[float], actual: list[float]) -> float | None:
    n = len(projected)
    if n < 2:
        return None
    correct = total = 0
    for i in range(n):
        for j in range(i + 1, n):
            if actual[i] == actual[j]:
                continue
            total += 1
            if (projected[i] > projected[j]) == (actual[i] > actual[j]):
                correct += 1
            elif projected[i] == projected[j]:
                correct += 0.5
    return correct / total if total > 0 else None


def _crps_gaussian(mean: float, sigma: float, actual: float) -> float:
    if sigma <= 0:
        return abs(mean - actual)
    z = (actual - mean) / sigma
    phi_z = 0.5 * (1 + math.erf(z / math.sqrt(2)))
    pdf_z = math.exp(-0.5 * z * z) / math.sqrt(2 * math.pi)
    return sigma * (z * (2 * phi_z - 1) + 2 * pdf_z - 1 / math.sqrt(math.pi))


def _picp(projected: list[float], actual: list[float],
          widths: list[float]) -> float | None:
    if not projected:
        return None
    hits = sum(1 for p, a, w in zip(projected, actual, widths) if p - w <= a <= p + w)
    return hits / len(projected)


def compute_metrics(pairs: list[tuple[float, float]],
                    widths: list[float] | None = None) -> dict:
    if not pairs:
        return {"n": 0}
    projected = [p for p, _ in pairs]
    actual = [a for _, a in pairs]
    n = len(pairs)
    errors = [p - a for p, a in pairs]
    abs_errors = [abs(e) for e in errors]

    result = {
        "n": n,
        "mae": round(sum(abs_errors) / n, 3),
        "me": round(sum(errors) / n, 3),
        "spearman": None,
        "pairwise": None,
    }

    sp = _spearman(projected, actual)
    if sp is not None:
        result["spearman"] = round(sp, 3)
    pw = _pairwise(projected, actual)
    if pw is not None:
        result["pairwise"] = round(pw, 3)

    if widths and len(widths) == n:
        picp = _picp(projected, actual, widths)
        if picp is not None:
            result["picp"] = round(picp, 3)
        crps_vals = [_crps_gaussian(p, w / 1.28, a) for p, a, w in zip(projected, actual, widths)]
        result["crps"] = round(sum(crps_vals) / len(crps_vals), 3)
    else:
        result["crps"] = round(sum(abs_errors) / n, 3)

    return result


def grade_from_consensus(conn: sqlite3.Connection, season: int,
                         week: int) -> dict:
    """Grade from market_consensus table."""
    row = conn.execute(
        "SELECT data FROM market_consensus WHERE season=? AND week=?",
        (season, week),
    ).fetchone()
    if not row:
        return {}
    data = json.loads(row[0])

    pairs_by_pos = defaultdict(list)
    pairs_overall = []
    model_errs = []
    market_errs = []

    for p in data:
        model_pts = p.get("model_points")
        actual_pts = p.get("actual_points")
        pos = (p.get("position") or "").upper()
        if model_pts is None or actual_pts is None or pos not in POSITIONS:
            continue

        pair = (float(model_pts), float(actual_pts))
        pairs_by_pos[pos].append(pair)
        pairs_overall.append(pair)

        model_errs.append(abs(model_pts - actual_pts))
        market_pts = p.get("market_points")
        if market_pts is not None:
            market_errs.append(abs(market_pts - actual_pts))

    results = {"overall": compute_metrics(pairs_overall)}
    for pos in POSITIONS:
        if pairs_by_pos[pos]:
            results[pos] = compute_metrics(pairs_by_pos[pos])

    if model_errs and market_errs and len(model_errs) == len(market_errs):
        m_mae = sum(model_errs) / len(model_errs)
        c_mae = sum(market_errs) / len(market_errs)
        results["beat_consensus"] = {
            "model_mae": round(m_mae, 3),
            "market_mae": round(c_mae, 3),
            "beats": m_mae < c_mae,
            "n": len(market_errs),
        }

    return results


def grade_from_stats(conn: sqlite3.Connection, season: int,
                     target_weeks: list[int] | None = None) -> dict:
    """Grade 2025 holdout: score raw nflverse stats as actuals, use
    projected_points from the blob as projections.

    NOTE: projected_points in the blob reflects the LAST refresh projection,
    not a frozen pre-week snapshot. For 2025 (full-season historical data),
    this is a post-hoc projection using all available data — it's leaky for
    per-week grading but valid for checking the scoring pipeline end-to-end.
    True per-week grading needs projection_snapshots (DB1 fix)."""
    row = conn.execute(
        "SELECT data FROM player_stats WHERE season=? AND week=0", (season,)
    ).fetchone()
    if not row:
        return {}
    players = json.loads(row[0])

    pairs_by_pos = defaultdict(list)
    pairs_overall = []

    for p in players:
        pos = (p.get("position") or "").upper()
        if pos not in POSITIONS:
            continue
        wk = p.get("week")
        if wk is None:
            continue
        if target_weeks and wk not in target_weeks:
            continue
        if not target_weeks and wk < 4:
            continue

        projected = p.get("projected_points")
        if projected is None:
            continue

        actual = calculate_fantasy_points(p, DEFAULT_SCORING)
        if actual < MIN_POINTS_THRESHOLD and pos != "K":
            continue

        pair = (float(projected), float(actual))
        pairs_by_pos[pos].append(pair)
        pairs_overall.append(pair)

    results = {"overall": compute_metrics(pairs_overall)}
    for pos in POSITIONS:
        if pairs_by_pos[pos]:
            results[pos] = compute_metrics(pairs_by_pos[pos])
    return results


def grade_from_jsonl(path: Path) -> dict:
    """Grade from backtest JSONL file (rows with projected_points, actual_points, position)."""
    rows = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))

    pairs_by_pos = defaultdict(list)
    pairs_overall = []

    for r in rows:
        proj = r.get("projected_points", r.get("model_points"))
        actual = r.get("actual_points", r.get("target"))
        pos = (r.get("position") or "").upper()
        if proj is None or actual is None:
            continue
        if pos not in POSITIONS:
            continue
        pair = (float(proj), float(actual))
        pairs_by_pos[pos].append(pair)
        pairs_overall.append(pair)

    results = {"overall": compute_metrics(pairs_overall)}
    for pos in POSITIONS:
        if pairs_by_pos[pos]:
            results[pos] = compute_metrics(pairs_by_pos[pos])
    return results


def print_table(results: dict, title: str):
    print(f"\n{'=' * 62}")
    print(f"  {title}")
    print(f"{'=' * 62}")
    header = f"{'Pos':<6} {'n':>6} {'MAE':>7} {'ME':>7} {'Spear':>7} {'PW%':>7} {'PICP':>6} {'CRPS':>7}"
    print(header)
    print("-" * 62)

    def _fmt(v):
        return f"{v:7.3f}" if v is not None else "      -"

    def _pct(v):
        return f"{v * 100:5.1f}%" if v is not None else "     -"

    for key in ["overall"] + list(POSITIONS):
        if key not in results:
            continue
        m = results[key]
        label = "ALL" if key == "overall" else key
        print(
            f"{label:<6} {m.get('n', 0):>6} {_fmt(m.get('mae'))} {_fmt(m.get('me'))} "
            f"{_fmt(m.get('spearman'))} {_pct(m.get('pairwise'))} {_pct(m.get('picp'))} {_fmt(m.get('crps'))}"
        )

    if "beat_consensus" in results:
        bc = results["beat_consensus"]
        verdict = "YES" if bc["beats"] else "no"
        print(f"\nBeat consensus: {verdict} (model {bc['model_mae']:.3f} vs market {bc['market_mae']:.3f}, n={bc['n']})")

    print()


def main():
    parser = argparse.ArgumentParser(description="Fantasy projection accuracy scorecard")
    parser.add_argument("--season", type=int, default=2025)
    parser.add_argument("--week", type=int, default=None)
    parser.add_argument("--all-weeks", action="store_true", help="Grade weeks 4+ (default for 2025)")
    parser.add_argument("--jsonl", type=str, default=None, help="Grade from JSONL file")
    parser.add_argument("--db", type=str, default=None)
    parser.add_argument("--output", type=str, default=None)
    args = parser.parse_args()

    if args.jsonl:
        results = grade_from_jsonl(Path(args.jsonl))
        title = f"Scorecard from {args.jsonl}"
        label = Path(args.jsonl).stem
    else:
        db_path = Path(args.db) if args.db else DB_PATH
        conn = sqlite3.connect(str(db_path))

        if args.season >= 2026:
            if not args.week:
                print("--week required for 2026+ (need completed week)")
                sys.exit(1)
            results = grade_from_consensus(conn, args.season, args.week)
            title = f"{args.season} Week {args.week} Scorecard"
            label = f"{args.season}_wk{args.week}"
        else:
            if not args.week and not args.all_weeks:
                args.all_weeks = True
            target_weeks = None
            if args.week and not args.all_weeks:
                target_weeks = [args.week]
            results = grade_from_stats(conn, args.season, target_weeks)
            title = f"{args.season} Holdout Scorecard (weeks {'4-18' if args.all_weeks else args.week})"
            label = f"{args.season}_{'all' if args.all_weeks else f'wk{args.week}'}"
        conn.close()

    if not results:
        print("No data to grade.")
        sys.exit(1)

    print_table(results, title)

    out_path = Path(args.output) if args.output else Path(f"data/models/scorecard_{label}.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"Saved: {out_path}")


if __name__ == "__main__":
    main()
