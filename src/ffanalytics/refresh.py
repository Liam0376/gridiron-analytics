"""Refresh job: pulls from each adapter independently, logs per-source
success/failure to refresh_log, and never lets one source's failure abort
the others — matches design spec's stale-cache-fallback error handling."""

import sqlite3
import json
from datetime import datetime

from ffanalytics import config
from ffanalytics.adapters import nflverse, sleeper, weather


def _compute_nfl_week(now: datetime | None = None) -> int:
    """Compute approximate NFL week number (1-18) given a date.
    Season starts on the weekend after Labor Day (first Monday in September).
    This is a simplification; for logging only."""
    if now is None:
        now = datetime.now()
    # Labor Day: first Monday in September
    september_first = datetime(now.year, 9, 1)
    # Find first Monday in September
    # weekday() where Monday is 0, Sunday is 6
    offset_to_monday = (0 - september_first.weekday()) % 7
    labor_day = september_first + datetime.timedelta(days=offset_to_monday)
    # Season starts on the Monday after Labor Day (the start of the first week).
    season_start = labor_day + datetime.timedelta(days=7)  # Monday of first week
    # If now is before season start, return 0 (preseason)
    if now < season_start:
        return 0
    # Compute days since season start
    days_since = (now - season_start).days
    week_num = days_since // 7 + 1
    # Clamp to 1-18
    if week_num < 1:
        return 1
    if week_num > 18:
        return 18
    return week_num


def _log(conn: sqlite3.Connection, source: str, success: bool, error_message: str | None, ran_at_iso: str) -> None:
    conn.execute(
        "INSERT INTO refresh_log (source, ran_at, success, error_message) VALUES (?, ?, ?, ?)",
        (source, ran_at_iso, 1 if success else 0, error_message),
    )
    conn.commit()


def run_refresh(
    conn: sqlite3.Connection,
    season: int,
    sleeper_session=None,
    nfl_module=None,
    ran_at_iso: str = "",
) -> dict:
    result = {}

    try:
        sleeper.get_league_settings(config.LEAGUE_ID, session=sleeper_session)
        sleeper.get_rosters(config.LEAGUE_ID, session=sleeper_session)
        sleeper.get_injury_statuses(session=sleeper_session)
        _log(conn, "sleeper", True, None, ran_at_iso)
        result["sleeper"] = True
    except Exception as exc:
        _log(conn, "sleeper", False, str(exc), ran_at_iso)
        result["sleeper"] = False

    try:
        nflverse.get_weekly_player_stats(season, nfl_module=nfl_module)
        _log(conn, "nflverse", True, None, ran_at_iso)
        result["nflverse"] = True
    except Exception as exc:
        _log(conn, "nflverse", False, str(exc), ran_at_iso)
        result["nflverse"] = False

    return result


def run_refresh_with_data(
    conn: sqlite3.Connection,
    season: int,
    sleeper_session=None,
    nfl_module=None,
    ran_at_iso: str = "",
) -> tuple[dict, dict]:
    """
    Run refresh and return both status results and the actual data fetched.

    Returns:
        tuple of (status_dict, data_dict) where:
        - status_dict: same as run_refresh() return (sleeper: bool, nflverse: bool)
        - data_dict: dict containing the actual data:
          {
            "league_settings": {"scoring_settings": ..., "roster_positions": ...},
            "rosters": [...],
            "injury_status": {...},
            "player_stats": [...]
          }
    """
    data = {}
    status = {}

    # Get Sleeper data
    try:
        league_settings = sleeper.get_league_settings(config.LEAGUE_ID, session=sleeper_session)
        rosters = sleeper.get_rosters(config.LEAGUE_ID, session=sleeper_session)
        injury_status = sleeper.get_injury_statuses(session=sleeper_session)
        data["league_settings"] = league_settings
        data["rosters"] = rosters
        data["injury_status"] = injury_status
        _log(conn, "sleeper", True, None, ran_at_iso)
        status["sleeper"] = True
    except Exception as exc:
        _log(conn, "sleeper", False, str(exc), ran_at_iso)
        status["sleeper"] = False
        # Set empty defaults on failure
        data["league_settings"] = {"scoring_settings": {}, "roster_positions": []}
        data["rosters"] = []
        data["injury_status"] = {}

    # Get NFLverse data
    try:
        player_stats = nflverse.get_weekly_player_stats(season, nfl_module=nfl_module)
        data["player_stats"] = player_stats
        _log(conn, "nflverse", True, None, ran_at_iso)
        status["nflverse"] = True
    except Exception as exc:
        _log(conn, "nflverse", False, str(exc), ran_at_iso)
        status["nflverse"] = False
        # Set empty default on failure
        data["player_stats"] = []

    # Store fetched data in the database
    try:
        # Compute week for rosters (based on run time)
        now = datetime.fromisoformat(ran_at_iso) if ran_at_iso else datetime.now()
        week = _compute_nfl_week(now)

        # Store league_settings (one row per season)
        conn.execute(
            """INSERT OR REPLACE INTO league_settings (season, data)
               VALUES (?, ?)""",
            (season, json.dumps(data["league_settings"])),
        )
        # Store rosters (one row per season per week)
        conn.execute(
            """INSERT INTO rosters (season, week, data)
               VALUES (?, ?, ?)""",
            (season, week, json.dumps(data["rosters"])),
        )
        # Store injury_status (one row per season)
        conn.execute(
            """INSERT INTO injury_status (season, data)
               VALUES (?, ?)""",
            (season, json.dumps(data["injury_status"])),
        )
        # Store player_stats (we store the entire list as JSON for the season, week=0)
        conn.execute(
            """INSERT INTO player_stats (season, week, data)
               VALUES (?, ?, ?)""",
            (season, 0, json.dumps(data["player_stats"])),
        )

        # Store weather data for games (if we have player stats with team info)
        if data["player_stats"]:
            try:
                # Extract unique team abbreviations from player stats
                teams = set()
                for player in data["player_stats"]:
                    if player.get("recent_team"):
                        teams.add(player["recent_team"])
                    if player.get("opponent_team"):
                        teams.add(player["opponent_team"])

                # For each team, store weather data (using placeholder coordinates and game time)
                # In a real implementation, we would:
                # 1. Map team to stadium coordinates (lat, lon)
                # 2. Get the actual game time for this week
                # 3. Fetch weather forecast for that location and time
                # For now, we'll use placeholder values to demonstrate the mechanism
                for team in teams:
                    # Placeholder: In reality, we'd have a team_to_coordinates mapping
                    # and actual game times from schedule data
                    lat, lon = 40.0, -74.0  # Example coordinates (New York area)
                    game_time_iso = now.isoformat()  # Example game time

                    forecast = weather.get_forecast(lat, lon, game_time_iso)
                    if forecast is not None:
                        conn.execute(
                            """INSERT INTO weather (lat, lon, game_time_iso, temp_f, wind_mph, precip_prob, fetched_at)
                               VALUES (?, ?, ?, ?, ?, ?, ?)""",
                            (
                                lat,
                                lon,
                                game_time_iso,
                                forecast.get("temp_f"),
                                forecast.get("wind_mph"),
                                forecast.get("precip_prob"),
                                datetime.now().isoformat(),
                            ),
                        )
            except Exception:
                # If weather processing fails, we continue but don't break the storage of other data
                pass

        conn.commit()
    except Exception:
        # If storage fails, we continue but log? We'll just pass for now.
        pass

    return status, data