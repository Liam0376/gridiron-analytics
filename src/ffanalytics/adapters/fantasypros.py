"""FantasyPros v2 API adapter for NFL data.

Fetches Expert Consensus Rankings (ECR), Average Draft Position (ADP),
breaking player news, and active injury reports.
Requires FANTASYPROS_API_KEY environment variable. Soft-fails gracefully
if no key is provided or on network errors.
"""

import os
import requests
from ffanalytics.adapters.sleeper import _get_with_retry

BASE_URL = "https://api.fantasypros.com/public/v2/json/nfl"


def _get_api_key(api_key: str | None = None) -> str | None:
    if api_key is not None:
        return api_key
    # Check environment variable or fallback to .env file if loaded
    key = os.environ.get("FANTASYPROS_API_KEY")
    if not key and os.path.exists(".env"):
        try:
            with open(".env") as f:
                for line in f:
                    if line.startswith("FANTASYPROS_API_KEY="):
                        key = line.split("=", 1)[1].strip()
                        break
        except Exception:
            pass
    return key


def get_fantasypros_players(api_key: str | None = None, session=None) -> list[dict]:
    """Fetch FantasyPros NFL player directory with ECR and ADP rankings.

    Returns list of dicts containing player metadata, ECR, ADP, PPR ranks.
    """
    key = _get_api_key(api_key)
    if not key:
        return []

    http = session or requests
    headers = {"x-api-key": key}

    try:
        url = f"{BASE_URL}/players?show=pos_rank"
        resp = http.get(url, headers=headers, timeout=15)
        if hasattr(resp, "raise_for_status"):
            resp.raise_for_status()
        data = resp.json()
        return data.get("players", [])
    except Exception:
        return []


def get_fantasypros_news(limit: int = 25, api_key: str | None = None, session=None) -> list[dict]:
    """Fetch breaking FantasyPros NFL player news and fantasy impact.

    Returns list of news dicts with title, player_id, team_id, author, link.
    """
    key = _get_api_key(api_key)
    if not key:
        return []

    http = session or requests
    headers = {"x-api-key": key}

    try:
        url = f"{BASE_URL}/news"
        resp = http.get(url, headers=headers, timeout=10)
        if hasattr(resp, "raise_for_status"):
            resp.raise_for_status()
        data = resp.json()
        items = data.get("items", [])
        return items[:limit]
    except Exception:
        return []


def get_fantasypros_injuries(api_key: str | None = None, session=None) -> list[dict]:
    """Fetch current FantasyPros active NFL injury reports.

    Returns list of injury dicts with player_id, name, status, team_id, position_id.
    """
    key = _get_api_key(api_key)
    if not key:
        return []

    http = session or requests
    headers = {"x-api-key": key}

    try:
        url = f"{BASE_URL}/injuries"
        resp = http.get(url, headers=headers, timeout=10)
        if hasattr(resp, "raise_for_status"):
            resp.raise_for_status()
        data = resp.json()
        return data.get("injuries", [])
    except Exception:
        return []
