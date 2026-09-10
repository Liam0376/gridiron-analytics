"""StatsGuy Fantasy — free keyless market values from real trades.
Values 0-10000 scale; mapped Sleeper ID -> gsis_id via Sleeper players DB."""

from ffanalytics.adapters._retry import get_with_retry as _get_with_retry
import requests

BASE = "https://api.statsguyfantasy.com/api/v1"


def get_statsguy_rankings(format: str = "non_sf_redraft", limit: int = 500, offset: int = 0, session=None) -> dict:
    http = session or requests
    url = f"{BASE}/rankings?format={format}&limit={limit}&offset={offset}"
    resp = _get_with_retry(http, url, timeout=15)
    return resp.json()


def get_statsguy_all(format: str = "non_sf_redraft", limit: int = 500, session=None) -> list[dict]:
    data = get_statsguy_rankings(format=format, limit=limit, session=session)
    # Rankings endpoint returns {rankings: [{rank, id, name, team, position, value, positionRank, ...}]}
    rankings = data.get("rankings") or data.get("players") or []
    if isinstance(rankings, dict):
        # some responses wrap differently
        rankings = list(rankings.values())
    return rankings if isinstance(rankings, list) else []
