"""FantasyPros v2 API: ECR, ADP, news, injuries. Requires FANTASYPROS_API_KEY."""

import logging
import os
import requests
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

try:
    from ffanalytics.adapters.sleeper import _get_with_retry
except Exception:  # pragma: no cover - optional retry helper, not required
    _get_with_retry = None

BASE_URL = "https://api.fantasypros.com/public/v2/json/nfl"


def _is_auth_error(exc: Exception) -> bool:
    """True when the failure looks like a bad/missing API key (401/403).

    why: callers get [] either way (no behavior change), but a revoked key
    needs error-level visibility + a key-rotation fix, while a transient
    5xx/timeout only needs a warning + next-refresh retry.
    """
    status = getattr(exc, "status_code", None)
    resp = getattr(exc, "response", None)
    if resp is not None and getattr(resp, "status_code", None) is not None:
        status = resp.status_code
    try:
        if status is not None and int(status) in (401, 403):
            return True
    except (TypeError, ValueError):
        pass
    msg = str(exc).lower()
    return (
        "401" in msg
        or "403" in msg
        or "unauthorized" in msg
        or "forbidden" in msg
        or "api key" in msg
        or "apikey" in msg
    )


def _log_fetch_error(which: str, exc: Exception) -> None:
    # why: same [] return to callers, distinct severity for operators.
    if _is_auth_error(exc):
        logger.error("fantasypros %s: auth/key error (%s); returning []", which, exc)
    else:
        logger.warning("fantasypros %s: transient error (%s); returning []", which, exc)


def _get_api_key(api_key: str | None = None) -> str:
    if api_key is not None and str(api_key).strip():
        return str(api_key).strip()

    key = os.environ.get("FANTASYPROS_API_KEY")
    if not key:
        load_dotenv()
        key = os.environ.get("FANTASYPROS_API_KEY")

    if not key or not str(key).strip():
        raise RuntimeError(
            "FANTASYPROS_API_KEY is not set — provide it via the environment "
            "or a .env file at the project root."
        )
    return str(key).strip()


def get_fantasypros_players(api_key: str | None = None, session=None) -> list[dict]:
    key = _get_api_key(api_key)

    http = session or requests
    headers = {"x-api-key": key}

    try:
        url = f"{BASE_URL}/players?show=pos_rank"
        resp = http.get(url, headers=headers, timeout=15)
        if hasattr(resp, "raise_for_status"):
            resp.raise_for_status()
        data = resp.json()
        return data.get("players", [])
    except Exception as exc:
        _log_fetch_error("players", exc)
        return []


def get_fantasypros_news(limit: int = 25, api_key: str | None = None, session=None) -> list[dict]:
    key = _get_api_key(api_key)

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
    except Exception as exc:
        _log_fetch_error("news", exc)
        return []


def get_fantasypros_injuries(api_key: str | None = None, session=None) -> list[dict]:
    key = _get_api_key(api_key)

    http = session or requests
    headers = {"x-api-key": key}

    try:
        url = f"{BASE_URL}/injuries"
        resp = http.get(url, headers=headers, timeout=10)
        if hasattr(resp, "raise_for_status"):
            resp.raise_for_status()
        data = resp.json()
        return data.get("injuries", [])
    except Exception as exc:
        _log_fetch_error("injuries", exc)
        return []
