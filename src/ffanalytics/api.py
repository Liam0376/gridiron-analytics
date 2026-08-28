"""FastAPI app, run locally only (uvicorn on localhost — no public
hosting, see design spec's hosting decision). In-memory cache pattern
follows the reference repo's api.py: refresh populates a module-level
cache, request handlers read from it, never touching disk per-request."""

from fastapi import FastAPI, HTTPException
import datetime
import json
from datetime import timedelta
from typing import Dict, List, Optional, Any

from ffanalytics import db
from ffanalytics.refresh import run_refresh_with_data
from ffanalytics.decision import (
    get_start_sit_recommendations,
    get_waiver_priority,
    evaluate_trade,
    calculate_roster_value
)
from ffanalytics import shadow

app = FastAPI(title="Fantasy Football Analytics Engine")

def _compute_nfl_week(now: datetime.datetime | None = None) -> int:
    """Compute approximate NFL week number (1-18) given a date.
    Season starts on the weekend after Labor Day (first Monday in September).
    This is a simplification; for logging only."""
    if now is None:
        now = datetime.datetime.now()
    # Labor Day: first Monday in September
    september_first = datetime.datetime(now.year, 9, 1)
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

# In-memory cache for data fetched by refresh job
_CACHE: dict = {
    "league_settings": None,  # scoring_settings, roster_positions
    "rosters": None,          # list of roster dicts from Sleeper
    "player_stats": None,     # list of player stat dicts from nflverse
    "injury_status": None,    # dict mapping player_id to injury status
    "last_updated": None,     # timestamp of last cache update
    "season": None,           # NFL season year
    "week": None,             # approximate NFL week (1-18)
}


def update_cache(
    league_settings: dict,
    rosters: list[dict],
    player_stats: list[dict],
    injury_status: dict[str, str | None],
    season: int | None = None,
    week: int | None = None
) -> None:
    """Update the in-memory cache with fresh data from refresh job."""
    _CACHE["league_settings"] = league_settings
    _CACHE["rosters"] = rosters
    _CACHE["player_stats"] = player_stats
    _CACHE["injury_status"] = injury_status
    _CACHE["last_updated"] = datetime.datetime.now().isoformat()
    if season is not None:
        _CACHE["season"] = season
    if week is not None:
        _CACHE["week"] = week


def _create_player_lookup(player_stats: list[dict]) -> dict[str, dict]:
    """Create a dictionary mapping player_id to player stats for quick lookup."""
    return {str(p.get("player_id")): p for p in player_stats}


def _process_roster_data(
    rosters: list[dict],
    player_stats: list[dict],
    injury_status: dict[str, str | None],
    league_settings: dict
) -> tuple[list[dict], list[dict], list[dict]]:
    """
    Process raw Sleeper rosters and nflverse stats into roster_players,
    bench_players, and free_agents for decision layer functions.

    Returns:
        tuple of (roster_players, bench_players, free_agents)
    """
    if not player_stats:
        return [], [], []

    # Create lookup for player stats
    stats_lookup = _create_player_lookup(player_stats)

    # Get scoring settings and roster positions
    scoring_settings = league_settings.get("scoring_settings", {})
    roster_positions = league_settings.get("roster_positions", [])

    # Count how many starters we need for each position
    position_counts = {}
    for pos in roster_positions:
        position_counts[pos] = position_counts.get(pos, 0) + 1

    # Process each roster to collect all players with their stats
    all_players = []  # List of (player_dict, owner_id)

    for roster in rosters:
        owner_id = str(roster.get("owner_id")) if roster.get("owner_id") is not None else None
        if owner_id is None:
            continue  # Skip unowned rosters

        player_ids = roster.get("players", [])
        for player_id in player_ids:
            player_id_str = str(player_id)
            base_stats = stats_lookup.get(player_id_str, {})

            if not base_stats:
                continue  # Skip players we don't have stats for

            player = {
                "player_id": player_id_str,
                "player_name": base_stats.get("short_name", f"Player {player_id_str}"),
                "position_group": base_stats.get("position", "UNK"),
                "projected_points": float(base_stats.get("fantasy_points", 0) or 0),
                "injury_status": injury_status.get(player_id_str),
                "team": base_stats.get("recent_team", ""),
                "opponent_team": base_stats.get("opponent_team", ""),
            }

            all_players.append((player, owner_id))

    # Sort all players by projected points descending (simple approximation)
    all_players.sort(key=lambda x: x[0]["projected_points"], reverse=True)

    # Assign players to roster slots based on position needs
    # This is a simplified approach - in reality would be more sophisticated
    roster_players = []
    bench_players = []

    # Track how many of each position we've assigned to starters
    assigned_counts = {pos: 0 for pos in position_counts}

    for player, owner_id in all_players:
        position = player["position_group"]

        # Check if we still need more of this position for starters
        needed = position_counts.get(position, 0)
        currently_assigned = assigned_counts.get(position, 0)

        if currently_assigned < needed:
            # Assign as starter
            roster_players.append(player)
            assigned_counts[position] = currently_assigned + 1
        else:
            # Assign to bench
            bench_players.append(player)

    # Free agents: players with stats but not on any roster
    rostered_player_ids = set()
    for roster in rosters:
        player_ids = roster.get("players", [])
        for player_id in player_ids:
            rostered_player_ids.add(str(player_id))

    free_agents = []
    for player_id_str, base_stats in stats_lookup.items():
        if player_id_str not in rostered_player_ids:
            player = {
                "player_id": player_id_str,
                "player_name": base_stats.get("short_name", f"Player {player_id_str}"),
                "position_group": base_stats.get("position", "UNK"),
                "projected_points": float(base_stats.get("fantasy_points", 0) or 0),
                "injury_status": injury_status.get(player_id_str),
                "team": base_stats.get("recent_team", ""),
                "opponent_team": base_stats.get("opponent_team", ""),
            }
            free_agents.append(player)

    return roster_players, bench_players, free_agents


def _log_recommendation(kind: str, recommendation: dict) -> None:
    """Log a recommendation to the shadow table (best-effort)."""
    try:
        conn = db.get_connection()
        logged_at = datetime.datetime.now().isoformat()
        season = _CACHE.get("season")
        week = _CACHE.get("week")
        player_id = recommendation.get("player_id")
        shadow.log_recommendation(
            conn=conn,
            kind=kind,
            season=season if season is not None else 0,
            week=week if week is not None else 0,
            player_id=player_id,
            recommendation=recommendation,
            logged_at_iso=logged_at,
        )
        conn.close()
    except Exception:
        # Best-effort logging; do not let logging errors break the API
        pass


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/refresh")
def refresh() -> dict:
    """Refresh data from all sources and update the internal cache."""
    conn = db.get_connection()
    try:
        # Run refresh and get both status and data
        now = datetime.datetime.now()
        season = now.year
        week = _compute_nfl_week(now)
        status, data = run_refresh_with_data(
            conn,
            season=season,
            ran_at_iso=now.isoformat()
        )

        # Update cache with the fetched data
        update_cache(
            league_settings=data["league_settings"],
            rosters=data["rosters"],
            player_stats=data["player_stats"],
            injury_status=data["injury_status"],
            season=season,
            week=week
        )

        conn.close()
        return {"status": "accepted", "sources": status}
    except Exception as e:
        conn.close()
        raise HTTPException(status_code=500, detail=f"Refresh failed: {str(e)}")


@app.get("/recommendations/start-sit")
def get_start_sit() -> dict:
    """Get start/sit recommendations for all rostered players."""
    if not _CACHE["league_settings"] or not _CACHE["rosters"] or not _CACHE["player_stats"]:
        raise HTTPException(
            status_code=503,
            detail="Data not available. Run /refresh first to load data."
        )

    league_settings = _CACHE["league_settings"]
    rosters = _CACHE["rosters"]
    player_stats = _CACHE["player_stats"]
    injury_status = _CACHE["injury_status"] or {}

    scoring_settings = league_settings.get("scoring_settings", {})
    roster_positions = league_settings.get("roster_positions", [])

    try:
        roster_players, bench_players, _ = _process_roster_data(
            rosters, player_stats, injury_status, league_settings
        )

        recommendations = get_start_sit_recommendations(
            roster_players, bench_players, scoring_settings, roster_positions
        )

        # Log each recommendation
        for rec in recommendations:
            _log_recommendation("start_sit", rec)

        return {
            "recommendations": recommendations,
            "count": len(recommendations),
            "timestamp": _CACHE["last_updated"]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error generating recommendations: {str(e)}")


@app.get("/recommendations/waiver")
def get_waiver() -> dict:
    """Get waiver priority recommendations for free agents."""
    if not _CACHE["league_settings"] or not _CACHE["rosters"] or not _CACHE["player_stats"]:
        raise HTTPException(
            status_code=503,
            detail="Data not available. Run /refresh first to load data."
        )

    league_settings = _CACHE["league_settings"]
    rosters = _CACHE["rosters"]
    player_stats = _CACHE["player_stats"]
    injury_status = _CACHE["injury_status"] or {}

    scoring_settings = league_settings.get("scoring_settings", {})
    roster_positions = league_settings.get("roster_positions", [])

    try:
        _, _, free_agents = _process_roster_data(
            rosters, player_stats, injury_status, league_settings
        )

        # We need roster_players for the waiver function (players currently on rosters)
        roster_players, _, _ = _process_roster_data(
            rosters, player_stats, injury_status, league_settings
        )

        recommendations = get_waiver_priority(
            roster_players, free_agents, scoring_settings, roster_positions
        )

        # Log each recommendation
        for rec in recommendations:
            _log_recommendation("waiver", rec)

        return {
            "recommendations": recommendations,
            "count": len(recommendations),
            "timestamp": _CACHE["last_updated"]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error generating waiver recommendations: {str(e)}")


@app.get("/recommendations/trade")
def get_trade_evaluation(
    team_a_id: str,
    team_b_id: str
) -> dict:
    """Evaluate a trade between two teams.

    Args:
        team_a_id: Owner ID of team A
        team_b_id: Owner ID of team B
    """
    if not _CACHE["league_settings"] or not _CACHE["rosters"] or not _CACHE["player_stats"]:
        raise HTTPException(
            status_code=503,
            detail="Data not available. Run /refresh first to load data."
        )

    league_settings = _CACHE["league_settings"]
    rosters = _CACHE["rosters"]
    player_stats = _CACHE["player_stats"]
    injury_status = _CACHE["injury_status"] or {}

    scoring_settings = league_settings.get("scoring_settings", {})
    roster_positions = league_settings.get("roster_positions", [])

    try:
        # Create player stats lookup
        stats_lookup = _create_player_lookup(player_stats)

        # Extract players for each team
        team_a_players = []
        team_b_players = []

        for roster in rosters:
            owner_id = str(roster.get("owner_id")) if roster.get("owner_id") is not None else None
            if owner_id is None:
                continue

            player_ids = roster.get("players", [])

            for player_id in player_ids:
                player_id_str = str(player_id)
                base_stats = stats_lookup.get(player_id_str, {})

                if not base_stats:
                    continue

                player = {
                    "player_id": player_id_str,
                    "player_name": base_stats.get("short_name", f"Player {player_id_str}"),
                    "position_group": base_stats.get("position", "UNK"),
                    "projected_points": float(base_stats.get("fantasy_points", 0) or 0),
                    "injury_status": injury_status.get(player_id_str),
                    "team": base_stats.get("recent_team", ""),
                    "opponent_team": base_stats.get("opponent_team", ""),
                }

                if owner_id == team_a_id:
                    team_a_players.append(player)
                elif owner_id == team_b_id:
                    team_b_players.append(player)

        if not team_a_players:
            raise HTTPException(status_code=404, detail=f"Team A (owner_id={team_a_id}) not found or has no players")
        if not team_b_players:
            raise HTTPException(status_code=404, detail=f"Team B (owner_id={team_b_id}) not found or has no players")

        # For trade evaluation, we might want to use current week/season
        # For simplicity, using defaults from decision layer function
        result = evaluate_trade(
            team_a_players, team_b_players, scoring_settings, roster_positions
        )

        # Log the trade evaluation
        _log_recommendation("trade", result)

        return {
            "trade_evaluation": result,
            "team_a_id": team_a_id,
            "team_b_id": team_b_id,
            "timestamp": _CACHE["last_updated"]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error evaluating trade: {str(e)}")