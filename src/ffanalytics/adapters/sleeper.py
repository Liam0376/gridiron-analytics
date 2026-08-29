import time
import requests

BASE_URL = "https://api.sleeper.app/v1"

def _session_or_default(session):
    return session or requests

def _get_with_retry(http, url: str, timeout: int = 10, max_retries: int = 3) -> requests.Response:
    last_resp = None
    for attempt in range(max_retries):
        try:
            resp = http.get(url, timeout=timeout)
            last_resp = resp
            status = getattr(resp, "status_code", 200)
            if status == 429:
                retry_after_hdr = getattr(resp, "headers", {}).get("Retry-After") if hasattr(resp, "headers") else None
                retry_after = float(retry_after_hdr or (1.5 * (attempt + 1)))
                time.sleep(retry_after)
                continue
            if isinstance(status, int) and status >= 500 and attempt < max_retries - 1:
                time.sleep(1.0 * (attempt + 1))
                continue
            if hasattr(resp, "raise_for_status"):
                resp.raise_for_status()
            return resp
        except (requests.ConnectionError, requests.Timeout):
            if attempt == max_retries - 1:
                raise
            time.sleep(1.0 * (attempt + 1))
    if last_resp is not None and hasattr(last_resp, "raise_for_status"):
        last_resp.raise_for_status()
    return last_resp

def get_league_settings(league_id: str, session=None) -> dict:
    http = _session_or_default(session)
    resp = _get_with_retry(http, f"{BASE_URL}/league/{league_id}", timeout=10)
    data = resp.json()
    return {
        "scoring_settings": data["scoring_settings"],
        "roster_positions": data["roster_positions"],
    }

def get_rosters(league_id: str, session=None) -> list[dict]:
    http = _session_or_default(session)
    resp = _get_with_retry(http, f"{BASE_URL}/league/{league_id}/rosters", timeout=10)
    return resp.json()

def get_injury_statuses(session=None) -> dict[str, str | None]:
    """Fetch full player DB and extract injury_status. Sleeper docs say
    fetch this at most once/day — caller (refresh job) is responsible for
    that cadence, this function just does one call."""
    http = _session_or_default(session)
    resp = _get_with_retry(http, f"{BASE_URL}/players/nfl", timeout=30)
    players = resp.json()
    return {pid: p.get("injury_status") for pid, p in players.items()}

def get_league_matchups(league_id: str, week: int, session=None) -> list[dict]:
    """Fetch matchups for a specific week. Returns roster-level matchup data."""
    http = _session_or_default(session)
    resp = _get_with_retry(http, f"{BASE_URL}/league/{league_id}/matchups/{week}", timeout=10)
    return resp.json()