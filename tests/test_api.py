from fastapi.testclient import TestClient
from unittest.mock import patch
from ffanalytics.api import app, _CACHE, _REFRESH_LOCK

client = TestClient(app)

def test_health_endpoint():
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}

def test_refresh_endpoint_accepted():
    # why mocked: an unmocked POST /refresh runs a live multi-source refresh
    # (Sleeper/nflverse) and writes the real DB — unit-test runs with
    # SLEEPER_LEAGUE_ID=test must never do that (it also logged sleeper 404s).
    # why release: production releases _REFRESH_LOCK inside _do_refresh_job's
    # finally — the mock skips that, so the test releases to avoid leaking a
    # held lock into test_concurrent_refresh_409.
    with patch("ffanalytics.api._do_refresh_job"):
        resp = client.post("/refresh")
    try:
        _REFRESH_LOCK.release()
    except Exception:
        pass
    assert resp.status_code in (200, 202)  # 202 canonical, 200 legacy compat
    assert resp.json()["status"] == "accepted"


# Audit 6.0 additions below (add-only; existing tests above untouched).
import re

# why helpers: _CACHE is module-global — each test snapshots + restores in
# finally so file order never leaks warmed/cold state between tests.


def _snapshot_cache() -> dict:
    return dict(_CACHE)


def _restore_cache(snap: dict) -> None:
    _CACHE.update(snap)


def _clear_cache() -> None:
    for k in ("league_settings", "rosters", "player_stats", "injury_status",
              "matchups", "trending", "detailed_injuries", "last_updated",
              "season", "week"):
        _CACHE[k] = None


def _warm_minimal_cache() -> None:
    # why minimal: enough to pass the warmed predicate + owner lookup without
    # network; roster "1" owns no matching players so unknown owners still 404.
    _CACHE.update({
        "league_settings": {"scoring_settings": {}, "roster_positions": [], "users": []},
        "rosters": [{"owner_id": "1", "roster_id": 1, "players": []}],
        "player_stats": [{"player_id": "1", "short_name": "Test QB",
                          "position": "QB", "position_group": "QB", "fantasy_points": 10}],
        "injury_status": {},
        "season": 2025,
        "week": 1,
    })


def test_recommendations_503_when_cold():
    snap = _snapshot_cache()
    try:
        _clear_cache()
        resp = client.get("/recommendations/start-sit", params={"owner_id": "123"})
        assert resp.status_code == 503
    finally:
        _restore_cache(snap)


def test_unknown_owner_404():
    snap = _snapshot_cache()
    try:
        _warm_minimal_cache()
        resp = client.get("/recommendations/start-sit", params={"owner_id": "99999999"})
        assert resp.status_code == 404
    finally:
        _restore_cache(snap)


def test_concurrent_refresh_409():
    # why: hold the real _REFRESH_LOCK so POST must take the 409 path without
    # running the multi-minute background job.
    acquired = _REFRESH_LOCK.acquire(blocking=False)
    assert acquired, "test setup: could not hold _REFRESH_LOCK"
    try:
        resp = client.post("/refresh")
        assert resp.status_code == 409
    finally:
        _REFRESH_LOCK.release()


def test_ready_parity_with_health():
    snap = _snapshot_cache()
    try:
        _clear_cache()
        assert client.get("/health").status_code == 200
        assert client.get("/ready").status_code == 503
        _warm_minimal_cache()
        assert client.get("/ready").status_code == 200
        assert client.get("/health").status_code == 200
    finally:
        _restore_cache(snap)


def test_v1_alias_200():
    # why: version alias must serve identical routes without removing
    # unversioned paths — check both shapes stay 200.
    assert client.get("/health").status_code == 200
    resp = client.get("/v1/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_invalid_request_id_replaced():
    # why: raw x-request-id must never be reflected (log/header injection);
    # invalid values get a server uuid4 hex instead.
    raw = "bad!!id\r\ninjected"
    resp = client.get("/health", headers={"x-request-id": raw})
    assert resp.status_code == 200
    echoed = resp.headers.get("x-request-id", "")
    assert echoed != raw
    assert re.fullmatch(r"[0-9a-f]{32}", echoed), f"not a server uuid4 hex: {echoed!r}"

# Multi-league additions (append-only; existing tests above untouched).


def test_cache_for_isolates_leagues():
    from ffanalytics import api as api_module
    # why: switching leagues must never serve another league's numbers —
    # separate dicts, default still _CACHE by identity.
    a = api_module._cache_for(None)
    assert a is api_module._CACHE
    b = api_module._cache_for("99999")
    assert b is not api_module._CACHE
    b["rosters"] = [{"owner_id": "7"}]
    assert api_module._CACHE.get("rosters") != [{"owner_id": "7"}]
    assert api_module._cache_for("99999") is b
    # cleanup so file order never leaks state
    api_module._LEAGUE_CACHES.pop("99999", None)


def test_league_query_rejects_nonnumeric():
    resp = client.get("/ready", params={"league_id": "../evil"})
    assert resp.status_code == 422


def test_ready_cold_unknown_league_503():
    # why: unknown league (no DB file) degrades to cold-503, never 500,
    # and never creates a stray DB file.
    import pathlib
    resp = client.get("/ready", params={"league_id": "424242"})
    assert resp.status_code == 503
    assert not pathlib.Path("data/fantasy_424242.db").exists()


def test_league_draft_endpoint_mocked():
    # patch the adapter function directly (no network in unit tests)
    import ffanalytics.adapters.sleeper as sleeper_mod
    fake = {"league_id": "424242", "league_name": "Test League",
            "season": "2026", "total_rosters": 10, "draft_id": "d1",
            "draft_type": "snake", "auction_budget": None, "draft_settings": {}}
    with patch.object(sleeper_mod, "get_draft_info", return_value=fake):
        resp = client.get("/league/draft", params={"league_id": "424242"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["league_name"] == "Test League"
    assert body["draft_type"] == "snake"


def test_league_draft_requires_id_or_env(monkeypatch):
    import ffanalytics.config as config_module
    monkeypatch.setenv("SLEEPER_LEAGUE_ID", "")
    import importlib
    importlib.reload(config_module)
    try:
        resp = client.get("/league/draft")
        assert resp.status_code == 400
    finally:
        monkeypatch.setenv("SLEEPER_LEAGUE_ID", "test")
        importlib.reload(config_module)
