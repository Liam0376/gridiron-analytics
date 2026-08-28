"""NFL schedule adapter. Wraps nflreadpy.load_schedules() behind the same
plain-dict boundary as nflverse.py — no Polars objects escape this module."""


def get_schedule(season: int, week: int | None = None, nfl_module=None) -> list[dict]:
    """Returns list of games for a season (optionally filtered to one week).
    Each dict has: game_id, season, week, home_team, away_team, home_score, away_score,
    game_type, gameday, gametime, stadium."""
    nfl = nfl_module if nfl_module is not None else __import__("nflreadpy")
    frame = nfl.load_schedules(seasons=[season])
    rows = frame.to_dicts()
    if week is not None:
        rows = [r for r in rows if r.get("week") == week]
    return rows


def get_team_for_player(rosters: list[dict], player_id: str) -> str | None:
    """Given Sleeper rosters, find which team a player belongs to.
    Returns roster's owner display name or roster_id as fallback."""
    for roster in rosters:
        if player_id in (roster.get("players") or []):
            return roster.get("owner_id") or str(roster.get("roster_id", ""))
    return None


def get_nfl_team_matchups(schedule: list[dict], week: int) -> dict[str, str]:
    """Returns {team: opponent_team} for all teams playing in given week."""
    matchups = {}
    for game in schedule:
        if game.get("week") == week:
            home = game.get("home_team", "")
            away = game.get("away_team", "")
            if home and away:
                matchups[home] = away
                matchups[away] = home
    return matchups
