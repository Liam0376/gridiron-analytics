#!/usr/bin/env python3
"""Historical accuracy report for game_predictions.py's market-derived
win probability + predicted score, over real completed REG-season games.

Not a ship/reject gate (see game_predictions.py docstring) — there's no
free parameter we fit, so nothing to overfit. This just proves the devig
math is sane: report win-call accuracy, Brier score, and score MAE against
real outcomes for 2023-2025.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import nflreadpy as nfl
from ffanalytics.game_predictions import game_prediction


def main():
    seasons = [2023, 2024, 2025]
    n = 0
    correct = 0
    brier_sum = 0.0
    score_err_sum = 0.0

    for season in seasons:
        df = nfl.load_schedules(seasons=[season])
        rows = df.to_dicts()
        for r in rows:
            if r.get("game_type") != "REG":
                continue
            if r.get("home_score") is None or r.get("away_score") is None:
                continue
            pred = game_prediction(r)
            if pred is None:
                continue
            n += 1
            home_won = 1.0 if r["home_score"] > r["away_score"] else 0.0
            picked_home = pred["home_win_prob"] >= 0.5
            actual_home_won = r["home_score"] > r["away_score"]
            if picked_home == actual_home_won:
                correct += 1
            brier_sum += (pred["home_win_prob"] - home_won) ** 2
            score_err_sum += (
                abs(pred["predicted_home_score"] - r["home_score"])
                + abs(pred["predicted_away_score"] - r["away_score"])
            ) / 2.0

    naive_home_favorite_baseline = 0.57  # documented NFL home-favorite base rate
    print(f"seasons: {seasons}")
    print(f"n games: {n}")
    print(f"win-call accuracy: {correct / n:.4f}  (naive home-favorite baseline ~{naive_home_favorite_baseline})")
    print(f"brier score: {brier_sum / n:.4f}  (naive p=0.5 baseline: 0.2500)")
    print(f"avg per-team score MAE: {score_err_sum / n:.2f} points")


if __name__ == "__main__":
    main()
