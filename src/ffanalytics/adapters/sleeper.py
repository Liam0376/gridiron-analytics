import requests

BASE_URL = "https://api.sleeper.app/v1"

def _session_or_default(session):
    return session or requests

def get_league_settings(league_id: str, session=None) -> dict:
    http = _session_or_default(session)
    resp = http.get(f"{BASE_URL}/league/{league_id}", timeout=10)
    resp.raise_for_status()
    data = resp.json()
    return {
        "scoring_settings": data["scoring_settings"],
        "roster_positions": data["roster_positions"],
    }

def get_rosters(league_id: str, session=None) -> list[dict]:
    http = _session_or_default(session)
    resp = http.get(f"{BASE_URL}/league/{league_id}/rosters", timeout=10)
    resp.raise_for_status()
    return resp.json()

def get_injury_statuses(session=None) -> dict[str, str | None]:
    """Fetch full player DB and extract injury_status. Sleeper docs say
    fetch this at most once/day — caller (refresh job) is responsible for
    that cadence, this function just does one call."""
    http = _session_or_default(session)
    resp = http.get(f"{BASE_URL}/players/nfl", timeout=30)
    resp.raise_for_status()
    players = resp.json()
    return {pid: p.get("injury_status") for pid, p in players.items()}