"""FastAPI app, run locally only (uvicorn on localhost — no public
hosting, see design spec's hosting decision). In-memory cache pattern
follows the reference repo's api.py: refresh populates a module-level
cache, request handlers read from it, never touching disk per-request."""

from fastapi import FastAPI, HTTPException
import datetime
import json
from datetime import timedelta
from typing import Dict, List, Optional, Any

import threading

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

# Audit C3: guard concurrent refresh (launchd + hub/start.sh + manual)
_REFRESH_LOCK = threading.Lock()

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
    "matchups": None,         # list of matchup dicts from Sleeper
    "trending": None,         # trending waiver adds
    "detailed_injuries": None, # practice participation status
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
    week: int | None = None,
    matchups: list[dict] | None = None,
    trending: list[dict] | None = None,
    detailed_injuries: list[dict] | None = None,
) -> None:
    """Update the in-memory cache with fresh data from refresh job (preserving prior cache on empty refresh)."""
    if league_settings:
        _CACHE["league_settings"] = league_settings
    if rosters:
        _CACHE["rosters"] = rosters
    if player_stats:
        _CACHE["player_stats"] = player_stats
    if injury_status:
        _CACHE["injury_status"] = injury_status
    if matchups:
        _CACHE["matchups"] = matchups
    if trending:
        _CACHE["trending"] = trending
    if detailed_injuries:
        _CACHE["detailed_injuries"] = detailed_injuries
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
    league_settings: dict,
    owner_id: str | None = None
) -> tuple[list[dict], list[dict], list[dict]]:
    """
    Process raw Sleeper rosters and nflverse stats into roster_players,
    bench_players, and free_agents for decision layer functions.

    Returns:
        tuple of (roster_players, bench_players, free_agents)
    """
    if not player_stats:
        return [], [], []

    stats_lookup = _create_player_lookup(player_stats)
    scoring_settings = league_settings.get("scoring_settings", {})
    roster_positions = league_settings.get("roster_positions", [])

    from ffanalytics.decision import _optimal_lineup

    target_rosters = rosters
    if owner_id is not None:
        target_rosters = [r for r in rosters if str(r.get("owner_id")) == str(owner_id)]
        if not target_rosters and rosters:
            target_rosters = [rosters[0]]

    roster_players = []
    bench_players = []

    for roster in target_rosters:
        current_owner = str(roster.get("owner_id")) if roster.get("owner_id") is not None else None
        player_ids = roster.get("players", [])
        team_players = []
        for player_id in player_ids:
            player_id_str = str(player_id)
            base_stats = stats_lookup.get(player_id_str, {})
            if not base_stats:
                continue

            pts = float(base_stats.get("projected_points") or base_stats.get("fantasy_points", 0) or 0)
            player = {
                "player_id": player_id_str,
                "player_name": base_stats.get("short_name", f"Player {player_id_str}"),
                "position_group": (base_stats.get("position_group") or base_stats.get("position", "UNK")).upper(),
                "position": (base_stats.get("position") or base_stats.get("position_group", "UNK")).upper(),
                "projected_points": pts,
                "projection_lower": base_stats.get("projection_lower"),
                "projection_upper": base_stats.get("projection_upper"),
                "width": base_stats.get("width"),
                "injury_status": injury_status.get(player_id_str),
                "team": base_stats.get("recent_team", ""),
                "opponent_team": base_stats.get("opponent_team", ""),
                "owner_id": current_owner,
            }
            team_players.append(player)

        starters, bench = _optimal_lineup(team_players, roster_positions)
        roster_players.extend(starters)
        bench_players.extend(bench)

    # Free agents: players with stats but not on any roster
    rostered_player_ids = set()
    for roster in rosters:
        for player_id in roster.get("players", []):
            rostered_player_ids.add(str(player_id))

    free_agents = []
    for player_id_str, base_stats in stats_lookup.items():
        if player_id_str not in rostered_player_ids:
            pts = float(base_stats.get("projected_points") or base_stats.get("fantasy_points", 0) or 0)
            player = {
                "player_id": player_id_str,
                "player_name": base_stats.get("short_name", f"Player {player_id_str}"),
                "position_group": (base_stats.get("position_group") or base_stats.get("position", "UNK")).upper(),
                "position": (base_stats.get("position") or base_stats.get("position_group", "UNK")).upper(),
                "projected_points": pts,
                "projection_lower": base_stats.get("projection_lower"),
                "projection_upper": base_stats.get("projection_upper"),
                "width": base_stats.get("width"),
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
    if not _REFRESH_LOCK.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="Refresh already in progress")
    conn = db.get_connection()
    try:
        # Run refresh and get both status and data
        from ffanalytics.config import get_current_nfl_season, get_stats_season
        now = datetime.datetime.now()
        season = get_current_nfl_season()
        stats_season = get_stats_season()
        week = _compute_nfl_week(now)
        status, data = run_refresh_with_data(
            conn,
            season=season,
            stats_season=stats_season,
            ran_at_iso=now.isoformat()
        )

        # Update cache atomically (copy-on-write to avoid torn reads, audit C3)
        # Snapshot current cache and atomically replace global reference
        new_cache = dict(_CACHE)
        if data.get("league_settings"):
            new_cache["league_settings"] = data["league_settings"]
        if data.get("rosters"):
            new_cache["rosters"] = data["rosters"]
        if data.get("player_stats"):
            new_cache["player_stats"] = data["player_stats"]
        if data.get("injury_status"):
            new_cache["injury_status"] = data["injury_status"]
        if data.get("matchups"):
            new_cache["matchups"] = data["matchups"]
        if data.get("trending"):
            new_cache["trending"] = data["trending"]
        if data.get("detailed_injuries"):
            new_cache["detailed_injuries"] = data["detailed_injuries"]
        new_cache["last_updated"] = datetime.datetime.now().isoformat()
        if season is not None:
            new_cache["season"] = season
        if week is not None:
            new_cache["week"] = week
        # Atomic swap
        _CACHE.clear()
        _CACHE.update(new_cache)

        conn.close()
        return {"status": "accepted", "sources": status}
    except HTTPException:
        raise
    except Exception as e:
        conn.close()
        raise HTTPException(status_code=500, detail=f"Refresh failed: {str(e)}")
    finally:
        try:
            _REFRESH_LOCK.release()
        except Exception:
            pass


@app.get("/news")
def get_news() -> dict:
    """Return trending adds and detailed injury/practice status from last refresh."""
    conn = db.get_connection()
    try:
        trending_row = conn.execute(
            "SELECT data FROM news_data WHERE kind='trending' ORDER BY fetched_at DESC LIMIT 1"
        ).fetchone()
        injuries_row = conn.execute(
            "SELECT data FROM news_data WHERE kind='injuries' ORDER BY fetched_at DESC LIMIT 1"
        ).fetchone()
        conn.close()
        return {
            "trending_adds": json.loads(trending_row["data"]) if trending_row else [],
            "detailed_injuries": json.loads(injuries_row["data"]) if injuries_row else [],
        }
    except Exception as e:
        conn.close()
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/projections")
def get_projections() -> dict:
    """Return current projections from cache or DB."""
    if _CACHE["player_stats"]:
        players = _CACHE["player_stats"]
    else:
        conn = db.get_connection()
        row = conn.execute(
            "SELECT data FROM player_stats WHERE data IS NOT NULL AND length(data) > 1000 ORDER BY rowid DESC LIMIT 1"
        ).fetchone()
        players = json.loads(row["data"]) if row else []
        # Load scoring settings from DB
        srow = conn.execute(
            "SELECT data FROM league_settings ORDER BY season DESC LIMIT 1"
        ).fetchone()
        conn.close()
        scoring = json.loads(srow["data"]).get("scoring_settings", {}) if srow else {}

    out = []
    for p in players[:800]:
        pid = str(p.get("player_id") or p.get("id") or "")
        pos = (p.get("position") or p.get("position_group") or "UNK").upper()
        pts = float(p.get("projected_points") or p.get("fantasy_points") or 0)
        if pts == 0 and scoring:
            from ffanalytics.scoring import calculate_fantasy_points
            try:
                pts = calculate_fantasy_points(p, scoring)
            except Exception:
                pass
        injury = (_CACHE.get("injury_status") or {}).get(pid)
        out.append({
            "player_id": pid,
            "player_name": p.get("player_display_name") or p.get("short_name") or p.get("player_name") or pid,
            "position": pos,
            "position_group": pos,
            "team": p.get("recent_team") or p.get("team") or "",
            "opponent_team": p.get("opponent_team") or "",
            "projected_points": round(pts, 2),
            "injury_status": injury,
        })
    out.sort(key=lambda x: x["projected_points"], reverse=True)
    return {"players": out, "count": len(out), "meta": {"cached": bool(_CACHE["player_stats"])}}


@app.get("/recommendations/start-sit")
def get_start_sit(owner_id: Optional[str] = None) -> dict:
    """Get start/sit recommendations for rostered players."""
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
            rosters, player_stats, injury_status, league_settings, owner_id=owner_id
        )

        recommendations = get_start_sit_recommendations(
            roster_players, bench_players, scoring_settings, roster_positions
        )

        for rec in recommendations:
            _log_recommendation("start_sit", rec)

        return {
            "recommendations": recommendations,
            "count": len(recommendations),
            "timestamp": _CACHE["last_updated"]
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error generating recommendations: {str(e)}")


@app.get("/recommendations/waiver")
def get_waiver(owner_id: Optional[str] = None) -> dict:
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
        roster_players, _, free_agents = _process_roster_data(
            rosters, player_stats, injury_status, league_settings, owner_id=owner_id
        )

        recommendations = get_waiver_priority(
            roster_players, free_agents, scoring_settings, roster_positions
        )

        for rec in recommendations:
            _log_recommendation("waiver", rec)

        return {
            "recommendations": recommendations,
            "count": len(recommendations),
            "timestamp": _CACHE["last_updated"]
        }
    except HTTPException:
        raise
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
        stats_lookup = _create_player_lookup(player_stats)
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
                    "position_group": (base_stats.get("position_group") or base_stats.get("position", "UNK")).upper(),
                    "position": (base_stats.get("position") or base_stats.get("position_group", "UNK")).upper(),
                    "projected_points": float(base_stats.get("projected_points") or base_stats.get("fantasy_points", 0) or 0),
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

        result = evaluate_trade(
            team_a_players, team_b_players, scoring_settings, roster_positions
        )

        _log_recommendation("trade", result)

        return {
            "trade_evaluation": result,
            "team_a_id": team_a_id,
            "team_b_id": team_b_id,
            "timestamp": _CACHE["last_updated"]
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error evaluating trade: {str(e)}")