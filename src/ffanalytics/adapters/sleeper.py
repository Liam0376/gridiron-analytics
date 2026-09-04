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

def get_nfl_state(session=None) -> dict:
    http = _session_or_default(session)
    resp = _get_with_retry(http, f"{BASE_URL}/state/nfl", timeout=10)
    return resp.json()


def get_league_settings(league_id: str, session=None) -> dict:
    http = _session_or_default(session)
    resp = _get_with_retry(http, f"{BASE_URL}/league/{league_id}", timeout=10)
    data = resp.json()
    return {
        "league_id": data.get("league_id") or league_id,
        "name": data.get("name") or "Fantasy Bahamas",
        "league_name": data.get("name") or "Fantasy Bahamas",
        "season": data.get("season") or "2026",
        "scoring_settings": data.get("scoring_settings", {}),
        "roster_positions": data.get("roster_positions", []),
        "settings": data.get("settings", {}),
        "avatar": data.get("avatar"),
        "total_rosters": data.get("total_rosters", 12),
    }


def get_draft_info(league_id: str, session=None) -> dict:
    """League identity + draft type, all from Sleeper (setup screen source).

    Returns {league_id, league_name, season, total_rosters, draft_id,
    draft_type: "snake"|"auction"|"unknown", auction_budget, draft_settings}.
    draft_type is "unknown" when the league has no draft yet (pre-draft) or
    the draft payload lacks a type — callers treat unknown as "ask the user".
    why two calls: /league/{id} carries identity + draft_id; only
    /draft/{draft_id} carries type/settings. Both soft-fail to {} (the
    league call raising means the id itself is bad — let it raise).
    """
    http = _session_or_default(session)
    resp = _get_with_retry(http, f"{BASE_URL}/league/{league_id}", timeout=10)
    league = resp.json()
    info: dict = {
        "league_id": league.get("league_id") or league_id,
        "league_name": league.get("name") or "",
        "season": league.get("season") or "",
        "total_rosters": league.get("total_rosters", 12),
        "draft_id": league.get("draft_id"),
        "draft_type": "unknown",
        "auction_budget": None,
        "draft_settings": {},
    }
    draft_id = league.get("draft_id")
    if not draft_id:
        return info
    try:
        dresp = _get_with_retry(http, f"{BASE_URL}/draft/{draft_id}", timeout=10)
        draft = dresp.json()
    except Exception:
        return info
    dtype = str(draft.get("type") or "").lower()
    if dtype in ("snake", "auction"):
        info["draft_type"] = dtype
    settings = draft.get("settings") or {}
    info["draft_settings"] = settings
    # why budget probe: auction draft settings carry varying budget keys
    # across seasons — first numeric hit among known keys wins.
    for key in ("budget", "auction_budget", "salary_cap", "cap"):
        val = settings.get(key)
        if isinstance(val, (int, float)) and val > 0:
            info["auction_budget"] = val
            break
    return info

def get_rosters(league_id: str, session=None) -> list[dict]:
    http = _session_or_default(session)
    resp = _get_with_retry(http, f"{BASE_URL}/league/{league_id}/rosters", timeout=10)
    return resp.json()

def get_injury_statuses(session=None) -> dict[str, str | None]:
    http = _session_or_default(session)
    resp = _get_with_retry(http, f"{BASE_URL}/players/nfl", timeout=30)
    players = resp.json()
    return {pid: p.get("injury_status") for pid, p in players.items()}

def get_league_matchups(league_id: str, week: int, session=None) -> list[dict]:
    http = _session_or_default(session)
    resp = _get_with_retry(http, f"{BASE_URL}/league/{league_id}/matchups/{week}", timeout=10)
    return resp.json()


def get_users(league_id: str, session=None) -> list[dict]:
    http = _session_or_default(session)
    resp = _get_with_retry(http, f"{BASE_URL}/league/{league_id}/users", timeout=10)
    data = resp.json()
    users = []
    for u in data:
        meta = u.get("metadata") or {}
        users.append({
            "user_id": str(u.get("user_id", "")),
            "display_name": u.get("display_name") or u.get("username") or "",
            "team_name": meta.get("team_name") or "",
            "avatar": u.get("avatar"),
        })
    return users


def get_sleeper_players(session=None) -> dict:
    http = _session_or_default(session)
    resp = _get_with_retry(http, f"{BASE_URL}/players/nfl", timeout=30)
    return resp.json()


def get_sleeper_projections(season: int, week: int, season_type: str = "regular", session=None) -> dict:
    # Sleeper path is /projections/nfl/{season_type}/{season}/{week}
    http = _session_or_default(session)
    url = f"{BASE_URL}/projections/nfl/{season_type}/{season}/{week}"
    resp = _get_with_retry(http, url, timeout=15)
    try:
        return resp.json()
    except Exception:
        return {}


def get_sleeper_actual_stats(season: int, week: int, season_type: str = "regular", session=None) -> dict:
    http = _session_or_default(session)
    url = f"{BASE_URL}/stats/nfl/{season_type}/{season}/{week}"
    resp = _get_with_retry(http, url, timeout=15)
    try:
        return resp.json()
    except Exception:
        return {}


def get_auction_draft_picks(league_id: str, session=None) -> list[dict]:
    http = _session_or_default(session)
    try:
        drafts_resp = _get_with_retry(http, f"{BASE_URL}/league/{league_id}/drafts", timeout=10)
        drafts = drafts_resp.json()
        if not drafts or not isinstance(drafts, list):
            return []
        draft_id = drafts[0].get("draft_id")
        if not draft_id:
            return []
        picks_resp = _get_with_retry(http, f"{BASE_URL}/draft/{draft_id}/picks", timeout=15)
        return picks_resp.json()
    except Exception:
        return []


def get_league_transactions(league_id: str, week: int, session=None) -> list[dict]:
    http = _session_or_default(session)
    try:
        resp = _get_with_retry(http, f"{BASE_URL}/league/{league_id}/transactions/{week}", timeout=10)
        return resp.json()
    except Exception:
        return []


def get_traded_picks(league_id: str, session=None) -> list[dict]:
    http = _session_or_default(session)
    try:
        resp = _get_with_retry(http, f"{BASE_URL}/league/{league_id}/traded_picks", timeout=10)
        return resp.json()
    except Exception:
        return []