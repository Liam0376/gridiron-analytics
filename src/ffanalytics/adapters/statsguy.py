"""StatsGuy Fantasy — free keyless market values from real trades.

GET https://api.statsguyfantasy.com/api/v1/rankings?format=non_sf_redraft&limit=500
Returns rankings derived from ~1M real Sleeper trades, recomputed daily.
Free, 60 req/min, CORS, no key. Values are 0-10000 scale (Gibbs 10000 top).
We map Sleeper ID (rankings[].id) -> gsis_id via Sleeper players (gsis_id) for
comparison vs Gridiron Model.

Refs: https://statsguyfantasy.com/developers/docs (free & open)
"""

import time
import requests

BASE = "https://api.statsguyfantasy.com/api/v1"


def _get_with_retry(http, url: str, timeout: int = 10, max_retries: int = 3):
    last = None
    for attempt in range(max_retries):
        try:
            resp = http.get(url, timeout=timeout)
            last = resp
            status = getattr(resp, "status_code", 200)
            if status == 429:
                retry_after = resp.headers.get("Retry-After") if hasattr(resp, "headers") else None
                try:
                    wait = float(retry_after) if retry_after else 1.5 * (attempt + 1)
                except Exception:
                    wait = 1.5 * (attempt + 1)
                time.sleep(wait)
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
    if last is not None and hasattr(last, "raise_for_status"):
        last.raise_for_status()
    return last


def get_statsguy_rankings(format: str = "non_sf_redraft", limit: int = 500, offset: int = 0, session=None) -> dict:
    """Fetch rankings for a format. Returns raw JSON with rankings[] + players map.

    format: non_sf_redraft (12-team PPR single-QB redraft) is our league.
    """
    http = session or requests
    url = f"{BASE}/rankings?format={format}&limit={limit}&offset={offset}"
    resp = _get_with_retry(http, url, timeout=15)
    return resp.json()


def get_statsguy_all(format: str = "non_sf_redraft", limit: int = 500, session=None) -> list[dict]:
    """Fetch up to `limit` rankings as flat list of player cards."""
    data = get_statsguy_rankings(format=format, limit=limit, session=session)
    # Rankings endpoint returns {rankings: [{rank, id, name, team, position, value, positionRank, ...}]}
    rankings = data.get("rankings") or data.get("players") or []
    if isinstance(rankings, dict):
        # some responses wrap differently
        rankings = list(rankings.values())
    return rankings if isinstance(rankings, list) else []
