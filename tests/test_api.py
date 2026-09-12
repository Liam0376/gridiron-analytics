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


def test_projections_rescore_stale_nonzero():
    # why (backend sign-off): stored points could come from an older scoring
    # table — rescore whenever raw stat keys exist; keep stored only when the
    # rescore is 0 (stat-less rows would otherwise zero out).
    snap = _snapshot_cache()
    try:
        _clear_cache()
        _CACHE.update({
            "league_settings": {"scoring_settings": {"rec": 1.0, "rec_yd": 0.1},
                                "roster_positions": [], "users": []},
            "rosters": [],
            "player_stats": [
                {"player_id": "1", "short_name": "Stale WR",
                 "position": "WR", "position_group": "WR",
                 "projected_points": 999.0,
                 "receptions": 10, "receiving_yards": 100},
                {"player_id": "2", "short_name": "Statless",
                 "position": "WR", "position_group": "WR",
                 "projected_points": 7.5},
            ],
            "injury_status": {},
            "season": 2025,
            "week": 5,
        })
        resp = client.get("/projections")
        assert resp.status_code == 200
        players = {p["player_id"]: p for p in resp.json()["players"]}
        assert players["1"]["projected_points"] == 20.0
        assert players["2"]["projected_points"] == 7.5
    finally:
        _restore_cache(snap)


def test_game_predictions_falls_back_to_schedule_file_when_cache_cold():
    # why (user-caught live bug, 2026-09-11): the model's in-memory schedule
    # cache is process-local — every restart/reload (dev --reload, a crash,
    # a manual bounce) wipes it, and start.sh's staleness check skips
    # POST /refresh whenever the DB data still looks fresh, leaving
    # /games/predictions hard-503ing even though the underlying data is
    # current. refresh.py already writes data/nfl_cache/schedule_<season>.json
    # for the hub's own read (refresh.py:389-410); this endpoint now falls
    # back to that same file instead of requiring a fresh /refresh call.
    from pathlib import Path
    import json as _json

    season = 2099  # unused elsewhere, avoids colliding with real cache data
    sched_path = (
        Path(__file__).resolve().parents[1]
        / "data" / "nfl_cache" / f"schedule_{season}.json"
    )
    snap = _snapshot_cache()
    try:
        _clear_cache()
        _CACHE.update({
            "league_settings": {"scoring_settings": {}, "roster_positions": [], "users": []},
            "rosters": [],
            "player_stats": [],
            "injury_status": {},
            # no "schedule" key — simulates a cold process
        })
        sched_path.parent.mkdir(parents=True, exist_ok=True)
        sched_path.write_text(_json.dumps([
            {"season": season, "week": 1, "home_team": "SEA", "away_team": "NE"},
        ]))
        resp = client.get(f"/games/predictions?week=1&season={season}")
        assert resp.status_code == 200
        games = resp.json()["games"]
        assert len(games) == 1
        assert games[0]["home_team"] == "SEA"
    finally:
        sched_path.unlink(missing_ok=True)
        _restore_cache(snap)


def test_projections_attaches_sleeper_id_for_headshots():
    # why (user-caught live bug, 2026-09-11): /projections never attached
    # sleeper_id, unlike /props/board which already resolves it via the same
    # xwalk (api.py:1335) — hub's playerAvatar() needs sleeper_id/espn_id to
    # build a CDN headshot URL, so every row silently fell back to initials
    # regardless of xwalk health.
    snap = _snapshot_cache()
    try:
        _clear_cache()
        _CACHE.update({
            "league_settings": {"scoring_settings": {}, "roster_positions": [], "users": []},
            "rosters": [],
            "sleeper_xwalk": {"999": "00-1234567"},  # {sleeper_id: gsis_id}
            "player_stats": [
                {"player_id": "00-1234567", "short_name": "Has Xwalk",
                 "position": "WR", "position_group": "WR", "projected_points": 10.0},
                {"player_id": "00-9999999", "short_name": "No Xwalk",
                 "position": "WR", "position_group": "WR", "projected_points": 5.0},
            ],
            "injury_status": {},
            "season": 2025,
            "week": 5,
        })
        resp = client.get("/projections")
        assert resp.status_code == 200
        players = {p["player_id"]: p for p in resp.json()["players"]}
        assert players["00-1234567"]["sleeper_id"] == "999"
        assert players["00-9999999"]["sleeper_id"] is None
    finally:
        _restore_cache(snap)


def test_start_sit_survives_position_fields_present_but_none():
    # why (user-caught live bug, 2026-09-10): dict.get(key, default) only
    # applies default when key is MISSING, not when its value is explicitly
    # None. A real player_stats row had both position_group and position
    # present but set to None, which crashed _build_player_dict's .upper()
    # call with a 500 before shadow_recommendations logging was ever
    # reached — the actual reason start_sit/waiver/trade recs never fired.
    snap = _snapshot_cache()
    try:
        _CACHE.update({
            "league_settings": {"scoring_settings": {}, "roster_positions": [], "users": []},
            "rosters": [{"owner_id": "1", "roster_id": 1, "players": ["1"]}],
            "player_stats": [{"player_id": "1", "short_name": "No Position Data",
                              "position": None, "position_group": None,
                              "projected_points": 5.0}],
            "injury_status": {},
            "season": 2025,
            "week": 1,
        })
        resp = client.get("/recommendations/start-sit", params={"owner_id": "1"})
        assert resp.status_code == 200
    finally:
        _restore_cache(snap)


def test_build_player_dict_falls_back_to_display_name_when_short_name_none():
    # why (user-caught live bug, 2026-09-10): same .get(key, default)
    # anti-pattern as position_group/position — nflverse gives
    # short_name=None for some real players while player_display_name is
    # always filled. Confirmed live: waiver recs showed raw player_id
    # ("00-0038543") instead of "Jaxon Smith-Njigba" because .get("short_name",
    # default) only applies default when the KEY is missing, not when
    # present-but-None.
    from ffanalytics.api import _build_player_dict
    base_stats = {
        "short_name": None,
        "player_display_name": "Jaxon Smith-Njigba",
        "position": "WR",
        "position_group": "WR",
        "projected_points": 12.0,
    }
    player = _build_player_dict("00-0038543", base_stats, {})
    assert player["player_name"] == "Jaxon Smith-Njigba"


def test_player_lookup_prefers_model_projections_over_sparse_box_scores():
    # why (user-caught live bug, 2026-09-10): player_stats is raw box-score
    # data — early in a real NFL week it only covers players whose game has
    # already been played (confirmed live: 220 rows total, one real roster
    # of 14 resolved ZERO players against it). model_projections covers
    # every player the model can project regardless of whether their game
    # has happened yet (805 rows live, same roster resolved 13/14).
    # /recommendations/trade 404'd for every roster in the league because
    # of this; start-sit/waiver hit the same gap but silently degraded to
    # an empty list instead of a hard error.
    from ffanalytics.api import _create_player_lookup
    player_stats = [{"player_id": "00-0031588", "short_name": "Box Score Only"}]
    model_projections = [
        {"player_id": "00-0039738", "player_display_name": "Projected Only", "projected_points": 12.0},
    ]
    lookup = _create_player_lookup(player_stats, model_projections)
    assert "00-0039738" in lookup, "model_projections entry must resolve"
    assert "00-0031588" in lookup, "player_stats-only entry must still resolve as fallback"
    assert lookup["00-0039738"]["player_display_name"] == "Projected Only"


def test_waiver_excludes_rostered_players_across_id_spaces():
    # why (user-caught live bug, 2026-09-11): rosters carry Sleeper ids,
    # stats_lookup keys are mostly GSIS ids (nflverse) — the free-agent
    # exclusion set only checked the raw Sleeper id against stats_lookup
    # keys, so a direct match almost never happened and truly-rostered
    # stars (e.g. CMC) showed up as top "free agent" waiver recs. Fix
    # cross-maps both ways via sleeper_xwalk before excluding.
    snap = _snapshot_cache()
    try:
        _CACHE.update({
            "league_settings": {
                "scoring_settings": {},
                "roster_positions": ["RB", "RB"],
                "users": [],
            },
            "rosters": [{"owner_id": "1", "roster_id": 1, "players": ["111", "114"]}],
            # {sleeper_id: gsis_id}
            "sleeper_xwalk": {"111": "00-1111111", "114": "00-9990003"},
            "player_stats": [
                {"player_id": "00-1111111", "short_name": "Rostered Star",
                 "position": "RB", "position_group": "RB", "projected_points": 20.0},
                {"player_id": "00-9990003", "short_name": "Rostered Weak RB",
                 "position": "RB", "position_group": "RB", "projected_points": 3.0},
                {"player_id": "00-2222222", "short_name": "True Free Agent",
                 "position": "RB", "position_group": "RB", "projected_points": 15.0},
            ],
            "injury_status": {},
            "season": 2025,
            "week": 1,
        })
        resp = client.get("/recommendations/waiver", params={"owner_id": "1"})
        assert resp.status_code == 200
        recs = {r["player_id"]: r for r in resp.json()["recommendations"]}
        assert "00-1111111" not in recs, "rostered player leaked into waiver recs"
        assert "00-9990003" not in recs, "rostered player leaked into waiver recs"
        assert "00-2222222" in recs
        assert recs["00-2222222"]["replaces_player_name"] == "Rostered Weak RB"
        assert recs["00-2222222"]["sleeper_id"] is None  # no xwalk entry for this one
    finally:
        _restore_cache(snap)


def test_waiver_attaches_sleeper_id_for_headshots():
    # why: hub playerAvatar() needs sleeper_id/espn_id to build a CDN
    # headshot URL — /recommendations/waiver never attached it (same gap
    # f7a1b1e fixed for /projections), so waiver rows always fell back to
    # initials regardless of xwalk health.
    snap = _snapshot_cache()
    try:
        _CACHE.update({
            "league_settings": {
                "scoring_settings": {},
                "roster_positions": ["RB", "RB"],
                "users": [],
            },
            "rosters": [{"owner_id": "1", "roster_id": 1, "players": ["114"]}],
            "sleeper_xwalk": {"114": "00-9990003", "222": "00-2222222"},
            "player_stats": [
                {"player_id": "00-9990003", "short_name": "Rostered Weak RB",
                 "position": "RB", "position_group": "RB", "projected_points": 3.0},
                {"player_id": "00-2222222", "short_name": "Has Xwalk",
                 "position": "RB", "position_group": "RB", "projected_points": 15.0},
            ],
            "injury_status": {},
            "season": 2025,
            "week": 1,
        })
        resp = client.get("/recommendations/waiver", params={"owner_id": "1"})
        assert resp.status_code == 200
        recs = {r["player_id"]: r for r in resp.json()["recommendations"]}
        assert recs["00-2222222"]["sleeper_id"] == "222"
    finally:
        _restore_cache(snap)
