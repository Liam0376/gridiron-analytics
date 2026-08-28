"""News and detailed injury adapter. Aggregates trending player adds from
Sleeper and practice participation from nflreadpy injuries."""

import requests


SLEEPER_TRENDING_URL = "https://api.sleeper.app/v1/players/nfl/trending/add"


def get_trending_adds(limit: int = 25, session=None) -> list[dict]:
    """Fetch trending player adds from Sleeper. Free, no auth needed.
    Returns [{"player_id": str, "count": int}, ...]"""
    http = session or requests
    resp = http.get(SLEEPER_TRENDING_URL, params={"limit": limit}, timeout=10)
    resp.raise_for_status()
    return resp.json()


def get_injury_with_practice(season: int, nfl_module=None) -> list[dict]:
    """Fetch injuries with practice participation from nflreadpy.
    Returns [{player_id, full_name, team, injury_status, practice_status,
              report_status, date_modified}, ...]

    practice_status values: Full, Limited, DNP (Did Not Practice), None"""
    nfl = nfl_module if nfl_module is not None else __import__("nflreadpy")
    frame = nfl.load_injuries(seasons=[season])
    rows = frame.to_dicts()
    return [
        {
            "player_id": r.get("gsis_id", r.get("player_id", "")),
            "full_name": r.get("full_name", ""),
            "team": r.get("team", ""),
            "injury_status": r.get("report_status", ""),
            "practice_status": r.get("practice_status", ""),
            "date_modified": r.get("date_modified", ""),
        }
        for r in rows
    ]
