"""Consumes game results from nflreadpy schedule data and updates team_ratings
in SQLite using the Elo rating engine — both overall (win/loss) and positional
(fantasy points allowed to opposing QB/RB/WR/TE)."""

import json
import sqlite3

from ffanalytics.rating import Rating, DEFAULT_RATING, update
from ffanalytics.scoring import calculate_fantasy_points

POSITION_GROUPS = ("QB", "RB", "WR", "TE")

# League-wide mean fantasy points per position per game (2023-2025 averages).
# Used to convert raw points-allowed into a 0-1 "score" for the Elo update:
# score = 1 - clamp(pts_allowed / (2 * mean), 0, 1)
# Allowing 0 pts → score 1.0 (dominant), allowing 2× mean → score 0.0 (torched).
_POS_MEAN_PTS = {"QB": 17.5, "RB": 12.0, "WR": 12.5, "TE": 8.5}


def _load_ratings(conn: sqlite3.Connection, season: int) -> dict[str, dict[str, Rating]]:
    """Load existing ratings from DB. Returns {team: {position_group: Rating}}."""
    rows = conn.execute(
        "SELECT team, position_group, rating, rating_deviation FROM team_ratings WHERE season = ?",
        (season,),
    ).fetchall()
    ratings: dict[str, dict[str, Rating]] = {}
    for r in rows:
        team = r["team"]
        if team not in ratings:
            ratings[team] = {}
        ratings[team][r["position_group"]] = Rating(r["rating"], r["rating_deviation"])
    return ratings


def _save_ratings(conn: sqlite3.Connection, ratings: dict[str, dict[str, Rating]], season: int, week: int) -> None:
    """Upsert ratings into team_ratings table."""
    for team, groups in ratings.items():
        for pg, rating in groups.items():
            conn.execute(
                """INSERT INTO team_ratings (team, position_group, rating, rating_deviation, last_updated_week, season)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(team, position_group, season) DO UPDATE SET
                   rating = excluded.rating,
                   rating_deviation = excluded.rating_deviation,
                   last_updated_week = excluded.last_updated_week""",
                (team, pg, rating.value, rating.deviation, week, season),
            )
    conn.commit()


def _compute_positional_points_allowed(
    player_stats: list[dict],
    week: int,
    scoring_settings: dict | None = None,
) -> dict[str, dict[str, float]]:
    """From player-level weekly stats, compute total fantasy points each
    defense allowed to each opposing position group.

    Returns {defending_team: {position_group: total_fantasy_pts_allowed}}.
    """
    pts_allowed: dict[str, dict[str, float]] = {}

    for p in player_stats:
        if p.get("week") != week:
            continue
        pos = (p.get("position_group") or p.get("position") or "").upper()
        if pos not in POSITION_GROUPS:
            continue
        opp = p.get("opponent_team") or ""
        if not opp:
            continue

        scoring_stats = {
            "passing_yards": p.get("passing_yards", 0) or 0,
            "passing_tds": p.get("passing_tds", 0) or 0,
            "interceptions": p.get("passing_interceptions", 0) or p.get("interceptions", 0) or 0,
            "rushing_yards": p.get("rushing_yards", 0) or 0,
            "rushing_tds": p.get("rushing_tds", 0) or 0,
            "receiving_yards": p.get("receiving_yards", 0) or 0,
            "receiving_tds": p.get("receiving_tds", 0) or 0,
            "receptions": p.get("receptions", 0) or 0,
            "fumbles_lost": p.get("fumbles_lost", 0) or p.get("fumbles_lost_total", 0) or 0,
        }
        fpts = calculate_fantasy_points(scoring_stats, scoring_settings)

        if opp not in pts_allowed:
            pts_allowed[opp] = {pg: 0.0 for pg in POSITION_GROUPS}
        pts_allowed[opp][pos] = pts_allowed[opp].get(pos, 0.0) + fpts

    return pts_allowed


def update_team_ratings_from_results(
    conn: sqlite3.Connection,
    season: int,
    week: int,
    nfl_module=None,
    scoring_settings: dict | None = None,
) -> dict[str, dict[str, Rating]]:
    """Fetch completed game results for the given week, update team ratings.

    Updates two tracks:
      1. "overall" — win/loss Elo from game scores
      2. "vs_QB", "vs_RB", "vs_WR", "vs_TE" — defensive positional Elo from
         fantasy points allowed to each opposing position group

    Returns the updated ratings dict."""
    from ffanalytics.adapters.schedule import get_schedule
    from ffanalytics.adapters.nflverse import get_weekly_player_stats

    games = get_schedule(season, week=week, nfl_module=nfl_module)
    ratings = _load_ratings(conn, season)

    # --- Overall ratings from win/loss ---
    for game in games:
        home = game.get("home_team", "")
        away = game.get("away_team", "")
        home_score = game.get("home_score")
        away_score = game.get("away_score")

        if not home or not away or home_score is None or away_score is None:
            continue

        if home_score > away_score:
            home_result, away_result = 1.0, 0.0
        elif away_score > home_score:
            home_result, away_result = 0.0, 1.0
        else:
            home_result, away_result = 0.5, 0.5

        if home not in ratings:
            ratings[home] = {}
        if away not in ratings:
            ratings[away] = {}

        home_r = ratings[home].get("overall", DEFAULT_RATING)
        away_r = ratings[away].get("overall", DEFAULT_RATING)
        k_factor = max(16.0, 32.0 - week)

        ratings[home]["overall"] = update(home_r, away_r, home_result, k_factor)
        ratings[away]["overall"] = update(away_r, home_r, away_result, k_factor)

    # --- Positional ratings from fantasy points allowed ---
    try:
        all_stats = get_weekly_player_stats(season, nfl_module=nfl_module)
    except Exception:
        # If player stats unavailable, skip positional updates
        _save_ratings(conn, ratings, season, week)
        return ratings

    pts_allowed = _compute_positional_points_allowed(all_stats, week, scoring_settings)

    # League-average opponent as the "opponent" in the Elo update — each
    # defense is rated against a 1500-baseline opponent. The "score" is how
    # well the defense performed (1.0 = shut them down, 0.0 = torched).
    league_avg = DEFAULT_RATING

    for team, pos_pts in pts_allowed.items():
        if team not in ratings:
            ratings[team] = {}

        for pos in POSITION_GROUPS:
            pg_key = f"vs_{pos}"
            current = ratings[team].get(pg_key, DEFAULT_RATING)
            allowed = pos_pts.get(pos, 0.0)
            mean = _POS_MEAN_PTS.get(pos, 12.0)

            # score: 1.0 = allowed 0 pts (shutdown), 0.0 = allowed 2× league average
            score = max(0.0, min(1.0, 1.0 - allowed / (2.0 * mean)))

            k_pos = max(12.0, 24.0 - week)
            ratings[team][pg_key] = update(current, league_avg, score, k_pos)

    _save_ratings(conn, ratings, season, week)
    return ratings
