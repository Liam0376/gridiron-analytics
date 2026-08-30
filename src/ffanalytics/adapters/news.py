"""News and detailed injury adapter. Aggregates trending player adds from
Sleeper and practice participation from nflreadpy injuries."""

import time
import requests
from ffanalytics.adapters.sleeper import _get_with_retry


SLEEPER_TRENDING_URL = "https://api.sleeper.app/v1/players/nfl/trending/add"


def _call_with_retry(fn, max_retries=3, backoff_base=1.5):
    for attempt in range(max_retries):
        try:
            return fn()
        except Exception:
            if attempt == max_retries - 1:
                raise
            time.sleep(backoff_base * (attempt + 1))


def get_trending_adds(limit: int = 25, session=None) -> list[dict]:
    """Fetch trending player adds from Sleeper. Free, no auth needed.
    Returns [{"player_id": str, "player_name": str, "count": int}, ...]"""
    http = session or requests
    url = f"{SLEEPER_TRENDING_URL}?limit={limit}"
    resp = _get_with_retry(http, url, timeout=10)
    raw = resp.json()
    try:
        players_resp = _get_with_retry(http, "https://api.sleeper.app/v1/players/nfl", timeout=15)
        if hasattr(players_resp, "ok") and players_resp.ok:
            players_db = players_resp.json()
            for r in raw:
                pid = str(r.get("player_id") or "")
                p = players_db.get(pid, {})
                nm = p.get("full_name") or f"{p.get('first_name', '')} {p.get('last_name', '')}".strip()
                pos = (p.get("position") or ("DEF" if pid.isalpha() else "")).upper()
                if nm:
                    r["player_name"] = f"{nm} ({pos})" if pos else nm
    except Exception:
        pass
    return raw


def get_injury_with_practice(season: int, nfl_module=None) -> list[dict]:
    """Fetch injuries with practice participation from nflreadpy.
    Returns [{player_id, full_name, team, injury_status, practice_status,
              report_status, date_modified}, ...]

    practice_status values: Full, Limited, DNP (Did Not Practice), None"""
    nfl = nfl_module if nfl_module is not None else __import__("nflreadpy")
    frame = _call_with_retry(lambda: nfl.load_injuries(seasons=[season]))
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
