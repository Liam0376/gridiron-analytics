"""Consumes game results from nflreadpy schedule data and updates team_ratings
in SQLite using the Glicko-2 rating engine."""

import json
import sqlite3

from ffanalytics.rating import Rating, DEFAULT_RATING, update


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


def update_team_ratings_from_results(
    conn: sqlite3.Connection,
    season: int,
    week: int,
    nfl_module=None,
) -> dict[str, dict[str, Rating]]:
    """Fetch completed game results for the given week, update team ratings.
    Returns the updated ratings dict."""
    from ffanalytics.adapters.schedule import get_schedule

    games = get_schedule(season, week=week, nfl_module=nfl_module)
    ratings = _load_ratings(conn, season)

    for game in games:
        home = game.get("home_team", "")
        away = game.get("away_team", "")
        home_score = game.get("home_score")
        away_score = game.get("away_score")

        if not home or not away or home_score is None or away_score is None:
            continue

        # Determine game outcome
        if home_score > away_score:
            home_result, away_result = 1.0, 0.0
        elif away_score > home_score:
            home_result, away_result = 0.0, 1.0
        else:
            home_result, away_result = 0.5, 0.5

        # Get or create ratings for both teams
        if home not in ratings:
            ratings[home] = {}
        if away not in ratings:
            ratings[away] = {}

        for pg in ("overall",):
            home_r = ratings[home].get(pg, DEFAULT_RATING)
            away_r = ratings[away].get(pg, DEFAULT_RATING)

            k_factor = max(16.0, 32.0 - week)  # K decreases as season progresses

            ratings[home][pg] = update(home_r, away_r, home_result, k_factor)
            ratings[away][pg] = update(away_r, home_r, away_result, k_factor)

    _save_ratings(conn, ratings, season, week)
    return ratings
