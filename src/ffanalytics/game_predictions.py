"""Game-level win probability + predicted score, from REAL market lines —
not a home-rolled model. `adapters/schedule.py` wraps nflreadpy's
load_schedules(), which already carries `spread_line`/`total_line`/
`home_moneyline`/`away_moneyline` for every game (including upcoming,
not-yet-played ones) — a free market-consensus feed we already call and
weren't reading. This is NOT the player-props odds feed that was rejected
as paid ($99/mo theoddsapi.com Business tier, see props spec) — that was a
different product (player props). Game-level lines are a standard, free
column on the schedule dataset.

Because this relays real market data rather than fitting our own
parameters, there is nothing to "gate" the way stat_projector/props
backtests do — there's no free parameter to overfit. What we DO owe: the
conversion math (devig, spread->score) must be correct and the source must
be labeled honestly as market consensus, never presented as our own
prediction. Games whose books haven't posted lines yet are still emitted
(nulls, source "schedule") so schedule browsing never drops teams.
See scripts/validate_game_predictions.py for the historical
accuracy/calibration report (informational, not a ship/reject gate)."""

import math

from ffanalytics.props import american_to_prob


def devig_two_way(price_a: float, price_b: float) -> tuple[float, float]:
    """Fair (no-vig) win probabilities for a two-sided moneyline.

    Each side's raw implied probability (american_to_prob) includes the
    book's vig, so the two raw probabilities sum to > 1.0; dividing each by
    the sum removes it proportionally (standard no-vig normalization).
    """
    p_a = american_to_prob(price_a)
    p_b = american_to_prob(price_b)
    total = p_a + p_b
    # why math.isnan, not `total <= 0`: NaN <= 0 is False in Python — a NaN
    # total would fall through to the real division below and leak NaN into
    # the response (code-review finding). american_to_prob rejects NaN
    # prices today, but this stays correct if that ever changes upstream.
    if total <= 0 or math.isnan(total):
        return 0.5, 0.5
    return p_a / total, p_b / total


def predicted_score(spread_line: float, total_line: float) -> tuple[float, float]:
    """(home, away) predicted score from spread + total.

    nflverse convention (confirmed against real games): spread_line is the
    home team's market margin — positive means the home team is favored by
    that many points. home = (total + spread) / 2, away = (total - spread) / 2.
    """
    home = (total_line + spread_line) / 2.0
    away = (total_line - spread_line) / 2.0
    return home, away


def game_prediction(game: dict) -> dict | None:
    """One row of market-derived prediction for a schedule game dict (as
    returned by adapters/schedule.get_schedule). Returns None only when the
    matchup itself is unusable (missing teams) — games whose books haven't
    posted lines yet are returned with null win probs/scores and source
    "schedule" so every scheduled game stays browsable (user-caught live
    bug, 2026-09-10: books only post ~1-2 weeks out, so from week 8 nearly
    every game was dropped and whole teams vanished from the Props tab).
    Nulls are JSON-safe by construction (never NaN) and must render as
    "pending", never 0% — see hub props.js guards.
    """
    home = game.get("home_team")
    away = game.get("away_team")
    if not home or not away:
        return None
    spread = game.get("spread_line")
    total = game.get("total_line")
    home_ml = game.get("home_moneyline")
    away_ml = game.get("away_moneyline")
    # why isfinite (code-review finding): nflreadpy/Polars can hand back NaN
    # for a line that's technically "present" (not None) — a NaN spread/total
    # would propagate through predicted_score() into the JSON response and
    # raise on serialize. Treat NaN as missing (never guess a score).
    lines_ok = (
        spread is not None and total is not None
        and home_ml is not None and away_ml is not None
        and all(math.isfinite(v) for v in (spread, total, home_ml, away_ml))
    )
    if lines_ok:
        p_home, p_away = devig_two_way(home_ml, away_ml)
        home_score, away_score = predicted_score(spread, total)
        probs = {
            "home_win_prob": round(p_home, 4),
            "away_win_prob": round(p_away, 4),
            "predicted_home_score": round(home_score, 1),
            "predicted_away_score": round(away_score, 1),
            "spread_line": spread,
            "total_line": total,
            "source": "market_consensus",
        }
    else:
        probs = {
            "home_win_prob": None,
            "away_win_prob": None,
            "predicted_home_score": None,
            "predicted_away_score": None,
            "spread_line": spread if isinstance(spread, (int, float)) and math.isfinite(spread) else None,
            "total_line": total if isinstance(total, (int, float)) and math.isfinite(total) else None,
            "source": "schedule",
        }

    return {
        "game_id": game.get("game_id"),
        "season": game.get("season"),
        "week": game.get("week"),
        "home_team": home,
        "away_team": away,
        **probs,
        "final": game.get("home_score") is not None and game.get("away_score") is not None,
        "actual_home_score": game.get("home_score"),
        "actual_away_score": game.get("away_score"),
    }
