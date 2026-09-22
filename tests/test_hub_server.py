import sys
import json
import socket
import threading
import urllib.request
from pathlib import Path
from http.server import HTTPServer
import pytest

# Ensure repo root and hub/ directory are importable
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(REPO_ROOT / "hub") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "hub"))

import importlib.util
spec = importlib.util.spec_from_file_location("hubserver", REPO_ROOT / "hub" / "server.py")
hubserver = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hubserver)


def get_free_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture(scope="module")
def hub_server_url(tmp_path_factory):
    # Set up a test DB
    db_dir = tmp_path_factory.mktemp("db")
    db_path = db_dir / "fantasy.db"

    # Create dummy tables
    import sqlite3
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE IF NOT EXISTS refresh_log (source TEXT, ran_at TEXT, success INT, error_message TEXT)")
    conn.execute("INSERT INTO refresh_log VALUES ('nflreadpy', '2026-08-30T10:00:00', 1, '')")
    conn.execute("CREATE TABLE IF NOT EXISTS rosters (season INT, week INT, data TEXT)")
    conn.execute("INSERT INTO rosters VALUES (2026, 1, '[{\"roster_id\":1, \"owner_id\":\"owner1\", \"players\":[\"1234\"]}]')")
    conn.execute("CREATE TABLE IF NOT EXISTS player_stats (season INT, week INT, data TEXT)")
    conn.execute("INSERT INTO player_stats VALUES (2026, 1, '[{\"player_id\":\"1234\", \"short_name\":\"Patrick Mahomes\", \"position\":\"QB\", \"recent_team\":\"KC\", \"fantasy_points\":24.5}]')")
    conn.execute("CREATE TABLE IF NOT EXISTS injury_status (data TEXT)")
    conn.execute("INSERT INTO injury_status VALUES ('{}')")
    conn.execute("CREATE TABLE IF NOT EXISTS sleeper_matchups (season INT, week INT, data TEXT)")
    conn.execute("INSERT INTO sleeper_matchups VALUES (2026, 1, '[]')")
    conn.execute("CREATE TABLE IF NOT EXISTS news_data (kind TEXT, fetched_at TEXT, data TEXT)")
    conn.execute("INSERT INTO news_data VALUES ('trending', '2026-08-30T10:00:00', '[]')")
    conn.execute("CREATE TABLE IF NOT EXISTS team_ratings (team TEXT, position_group TEXT, rating REAL, rating_deviation REAL, last_updated_week INT, season INT)")
    conn.execute("INSERT INTO team_ratings VALUES ('KC', 'QB', 1500.0, 50.0, 1, 2026)")
    conn.execute("CREATE TABLE IF NOT EXISTS league_settings (season INT, data TEXT)")
    conn.execute('INSERT INTO league_settings VALUES (2026, \'{"users": [{"user_id":"owner1", "display_name":"Alice", "team_name":"Alice Team", "avatar":"av1"}]}\')')
    conn.execute("CREATE TABLE IF NOT EXISTS market_consensus (season INT, week INT, data TEXT, fetched_at TEXT)")
    conn.execute('INSERT INTO market_consensus VALUES (2026, 1, \'[{"player_id":"1234", "player_name":"Patrick Mahomes", "position":"QB", "market_season_points":300.0, "model_points":18.5, "auction":45, "marketAuction":40, "deltaAuction":5, "edge":"BUY", "fp_ecr":1, "fp_ecr_pos":1, "fp_adp":1, "fp_tier":1, "statsguy_rank":1, "statsguy_value":9000, "season_stat_deltas":[], "market_season_stats":{}}]\', "2026-08-30T10:00:00")')
    conn.commit()
    conn.close()

    port = get_free_port()
    hubserver.Handler.db_path = db_path

    httpd = HTTPServer(('127.0.0.1', port), hubserver.Handler)
    server_thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    server_thread.start()

    yield f"http://127.0.0.1:{port}"

    httpd.shutdown()


def test_handler_has_all_methods():
    expected_methods = [
        "handle_meta", "handle_projections", "handle_matchups",
        "handle_roster", "handle_news", "handle_refresh_log",
        "handle_ratings", "handle_waiver", "handle_rosters_raw"
    ]
    for method_name in expected_methods:
        assert hasattr(hubserver.Handler, method_name), f"Handler missing method: {method_name}"


def test_get_sleeper_player_name_fallback():
    name = hubserver.get_sleeper_player_name("UNKNOWN_ID_99999")
    assert name == "UNKNOWN_ID_99999"


def test_hub_server_meta_and_roster_enrichment(hub_server_url):
    # Test meta endpoint returns teams list
    meta_url = f"{hub_server_url}/hub-api/meta"
    with urllib.request.urlopen(meta_url, timeout=5) as response:
        body = json.loads(response.read().decode('utf-8'))
        assert "teams" in body
        assert len(body["teams"]) >= 1
        team0 = body["teams"][0]
        assert "roster_id" in team0
        assert "user_id" in team0
        assert "owner_name" in team0

    # Test roster endpoint with query param
    roster_url = f"{hub_server_url}/hub-api/roster?roster_id=1"
    with urllib.request.urlopen(roster_url, timeout=5) as response:
        body = json.loads(response.read().decode('utf-8'))
        assert "team_info" in body
        assert "allTeams" in body
        assert "starters" in body
        team_info = body["team_info"]
        assert team_info["roster_id"] == 1 or team_info["roster_id"] == "1"
        assert "owner_name" in team_info
        assert "team_name" in team_info
        if body["starters"]:
            p = body["starters"][0]
            for field in [
                "market_season_points", "model_points", "auction", "marketAuction",
                "deltaAuction", "edge", "fp_ecr", "fp_ecr_pos", "fp_adp", "fp_tier",
                "statsguy_rank", "statsguy_value", "season_stat_deltas", "market_season_stats",
                "pass_yds", "pass_tds", "rush_yds", "rush_tds", "receptions", "rec_yds", "rec_tds", "touches", "targets"
            ]:
                assert field in p

        # Test new team_analytics & league_leaderboard
        assert "team_analytics" in body
        ta = body["team_analytics"]
        for key in ["gridiron_value", "market_value", "projected_weekly_starter_pts", "total_season_projected_pts", "position_group_scores", "bye_week_matrix", "weakest_position", "start_sit_tossups"]:
            assert key in ta

        assert "league_leaderboard" in body
        ll = body["league_leaderboard"]
        assert isinstance(ll, list)
        assert len(ll) >= 1


@pytest.mark.parametrize("endpoint,expected_key", [
    ("health", "status"),
    ("hub-api/meta", "lastUpdated"),
    ("hub-api/projections", "players"),
    ("hub-api/matchups", "nflSlate"),
    ("hub-api/roster", "starters"),
    ("hub-api/news", "trending_adds"),
    ("hub-api/refresh-log", "entries"),
    ("hub-api/team-ratings", "ratings"),
    ("hub-api/waiver", "recommendations"),
    ("hub-api/rosters", "rosters"),
])
def test_hub_server_endpoints(hub_server_url, endpoint, expected_key):
    url = f"{hub_server_url}/{endpoint}"
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=5) as response:
        assert response.status == 200
        body = json.loads(response.read().decode('utf-8'))
        assert expected_key in body


def test_hub_readonly_attempt_write_fails(hub_server_url):
    # Non-GET must not succeed (read-only proxy: only GET/OPTIONS).
    import urllib.error
    post_req = urllib.request.Request(
        f"{hub_server_url}/hub-api/meta", data=b"{}", method="POST"
    )
    try:
        with urllib.request.urlopen(post_req, timeout=5) as response:
            assert response.status != 200, "POST should not return 200 on read-only proxy"
    except urllib.error.HTTPError as e:
        assert e.code in (400, 403, 404, 405, 501), f"unexpected POST status {e.code}"
    # DB itself is opened mode=ro by the handler — direct write must fail.
    import sqlite3
    ro_uri = f"file:{hubserver.Handler.db_path}?mode=ro"
    ro_conn = sqlite3.connect(ro_uri, uri=True)
    try:
        with pytest.raises(sqlite3.OperationalError):
            ro_conn.execute("INSERT INTO refresh_log VALUES ('x', '2026-01-01', 1, '')")
    finally:
        ro_conn.close()


def test_hub_rosters_full_shape(hub_server_url):
    url = f"{hub_server_url}/hub-api/rosters-full"
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=5) as response:
        assert response.status == 200
        # 60s server-side cache contract: Last-Modified + Cache-Control max-age=60.
        assert response.headers.get("Last-Modified"), "rosters-full must send Last-Modified"
        cc = (response.headers.get("Cache-Control") or "")
        assert "max-age=60" in cc, f"rosters-full Cache-Control should contain max-age=60, got {cc!r}"
        body = json.loads(response.read().decode("utf-8"))
    assert "rosters" in body
    assert "league_leaderboard" in body
    assert "leagueRosters" in body or "allTeams" in body
    assert "meta" in body
    rosters = body["rosters"]
    assert isinstance(rosters, dict) and len(rosters) >= 1
    first = rosters.get("1") or rosters.get(1) or next(iter(rosters.values()))
    for key in ("starters", "bench", "reserve", "team_info"):
        assert key in first, f"rosters-full entry missing {key}"
    # Second fetch should hit the 60s server cache (same Last-Modified).
    with urllib.request.urlopen(urllib.request.Request(url), timeout=5) as r2:
        assert r2.headers.get("Last-Modified") == response.headers.get("Last-Modified")


def test_hub_json_cache_control_no_store(hub_server_url):
    # JSON endpoints consistently send Cache-Control (no-store except rosters-full).
    with urllib.request.urlopen(f"{hub_server_url}/hub-api/meta", timeout=5) as response:
        cc = response.headers.get("Cache-Control") or ""
        assert "no-store" in cc, f"/meta Cache-Control should be no-store, got {cc!r}"


def test_hub_scoring_parity_smoke():
    # No ffanalytics import per isolation — duplicate expected value as fixture.
    # 300 pass yds @0.04 (=12.0) + 2 pass TD @5.0 (=10.0) => 22.0.
    scoring_fixture = {"pass_yd": 0.04, "pass_td": 5.0}
    player = {"passing_yards": 300, "passing_tds": 2}
    pts = hubserver._calc_points_from_raw(player, scoring_fixture)
    assert pts == pytest.approx(22.0)
    # Full default scoring still prices the same stat line at 22.0 (no other stats).
    pts_default = hubserver._calc_points_from_raw(player, hubserver.DEFAULT_SCORING)
    assert pts_default == pytest.approx(22.0)


def test_hub_qhat_matches_conformal_py():
    # why cross-import here, unlike the scoring-parity test above (which
    # hand-duplicates its fixture "per isolation"): a hardcoded expected
    # number doesn't catch drift if conformal.py's real formula ever
    # changes — only re-running the real implementation does. verify-
    # isolation.sh's grep only scans hub/, not tests/, so this doesn't
    # violate the runtime isolation contract (hub/server.py itself still
    # never imports ffanalytics — only this test file, at test time, does).
    # graphify-audit finding (2026-09-10): hub/server.py:169 vendors qhat()
    # (isolation forces this — hub can't import ffanalytics at runtime) but
    # nothing pinned the two copies together, so a future change to the
    # real formula could silently diverge from hub's copy with no test to
    # catch it.
    from ffanalytics.conformal import qhat as real_qhat

    cases = [
        [0.7, 1.8, 3.0, 4.4, 5.8, 7.2, 8.8, 10.2, 11.9],  # hub's own WR fallback set
        [1.0, 2.0, 3.0],
        [5.0],
        [-4.0, 4.0, -4.0, 4.0, -4.0, -4.0, 4.0, 4.0, -4.0, 4.0],
        list(range(1, 101)),
    ]
    for residuals in cases:
        assert hubserver.qhat(residuals) == pytest.approx(real_qhat(residuals)), residuals
    # hub's defensive extras (NaN/Inf filtering) are its own behavior.
    # why explicit 5.0 on empty (correctness batch 2026-09-12): src raises
    # ValueError on empty and projection.py falls back to 5.0. Hub mirrors
    # that contract now, not the WR 10.2 fallback. None still uses WR.
    assert hubserver.qhat([]) == 5.0
    assert hubserver.qhat(None) == pytest.approx(real_qhat(
        [0.7, 1.8, 3.0, 4.4, 5.8, 7.2, 8.8, 10.2, 11.9]
    ))
    assert hubserver.qhat([float("nan"), float("inf"), 2.0, 4.0, 6.0]) == pytest.approx(
        real_qhat([2.0, 4.0, 6.0])
    )
    assert hubserver.qhat([float("nan")]) == 5.0


def test_hub_rosters_full_ims_304(hub_server_url):
    import urllib.error
    url = f"{hub_server_url}/hub-api/rosters-full"
    with urllib.request.urlopen(urllib.request.Request(url), timeout=5) as r:
        assert r.status == 200
        lm = r.headers.get("Last-Modified")
        assert lm, "rosters-full must send Last-Modified"
    req = urllib.request.Request(url, headers={"If-Modified-Since": lm})
    try:
        with urllib.request.urlopen(req, timeout=5) as r2:
            assert r2.status == 304, f"expected 304 for IMS, got {r2.status}"
    except urllib.error.HTTPError as e:
        assert e.code == 304, f"expected 304 for IMS, got {e.code}"


def test_hub_projections_ims_304(hub_server_url):
    import urllib.error
    url = f"{hub_server_url}/hub-api/projections"
    with urllib.request.urlopen(urllib.request.Request(url), timeout=5) as r:
        assert r.status == 200
        lm = r.headers.get("Last-Modified")
        assert lm, "projections must send Last-Modified"
        cc = (r.headers.get("Cache-Control") or "")
        assert "max-age=60" in cc, f"projections Cache-Control should contain max-age=60, got {cc!r}"
    req = urllib.request.Request(url, headers={"If-Modified-Since": lm})
    try:
        with urllib.request.urlopen(req, timeout=5) as r2:
            assert r2.status == 304, f"expected 304 for IMS, got {r2.status}"
    except urllib.error.HTTPError as e:
        assert e.code == 304, f"expected 304 for IMS, got {e.code}"


def test_hub_projections_prefers_team_over_recent_team(tmp_path):
    import sqlite3
    import time
    from http.server import HTTPServer
    db_path = tmp_path / "team.db"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE player_stats (season INT, week INT, data TEXT)")
    conn.execute(
        "INSERT INTO player_stats VALUES (2026, 1, ?)",
        (json.dumps([{"player_id": "99999", "player_display_name": "Team Test Player", "short_name": "Team Test Player", "position": "WR", "team": "LAR", "recent_team": "JAX", "receiving_yards": 100, "receptions": 5}]),),
    )
    conn.execute("CREATE TABLE league_settings (season INT, data TEXT)")
    conn.execute("INSERT INTO league_settings VALUES (2026, '{}')")
    conn.execute("CREATE TABLE injury_status (data TEXT)")
    conn.execute("INSERT INTO injury_status VALUES ('{}')")
    conn.execute("CREATE TABLE news_data (kind TEXT, fetched_at TEXT, data TEXT)")
    conn.execute("INSERT INTO news_data VALUES ('trending', '2026-08-30T10:00:00', '[]')")
    conn.execute("CREATE TABLE market_consensus (season INT, week INT, data TEXT, fetched_at TEXT)")
    conn.execute("INSERT INTO market_consensus VALUES (2026, 1, '[]', '2026-08-30T10:00:00')")
    conn.execute("CREATE TABLE rosters (season INT, week INT, data TEXT)")
    conn.execute("INSERT INTO rosters VALUES (2026, 1, '[]')")
    conn.commit()
    conn.close()
    orig_db = hubserver.Handler.db_path
    orig_proj = hubserver._PROJECTIONS_CACHE
    orig_sleeper = hubserver.SLEEPER_PLAYERS_CACHE
    orig_sleeper_at = hubserver._SLEEPER_PLAYERS_AT
    hubserver._PROJECTIONS_CACHE = {"at": 0.0, "payload": None, "last_modified": ""}
    hubserver.SLEEPER_PLAYERS_CACHE = {"dummy": {"full_name": "Dummy", "team": "KC", "position": "QB"}}
    hubserver._SLEEPER_PLAYERS_AT = time.time()
    hubserver.Handler.db_path = db_path
    port = get_free_port()
    httpd = HTTPServer(('127.0.0.1', port), hubserver.Handler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    try:
        url = f"http://127.0.0.1:{port}/hub-api/projections?limit=2000"
        with urllib.request.urlopen(url, timeout=10) as r:
            assert r.status == 200
            body = json.loads(r.read().decode("utf-8"))
            assert "players" in body
            match = [p for p in body["players"] if str(p.get("player_id")) == "99999"]
            assert match, "fixture player 99999 missing from projections"
            assert match[0]["team"] == "LAR", f"team must win over recent_team, got {match[0]['team']!r}"
            assert match[0]["team"] != "JAX"
    finally:
        httpd.shutdown()
        try:
            httpd.server_close()
        except Exception:
            pass
        hubserver.Handler.db_path = orig_db
        hubserver._PROJECTIONS_CACHE = orig_proj
        hubserver.SLEEPER_PLAYERS_CACHE = orig_sleeper
        hubserver._SLEEPER_PLAYERS_AT = orig_sleeper_at
        hubserver._PROJECTIONS_CACHE = {"at": 0.0, "payload": None, "last_modified": ""}


def test_hub_stale_sleeper_served_no_500(hub_server_url):
    import time
    stale = {"1234": {"full_name": "Stale Player", "first_name": "Stale", "last_name": "Player", "position": "QB", "team": "KC"}}
    orig_cache = hubserver.SLEEPER_PLAYERS_CACHE
    orig_at = hubserver._SLEEPER_PLAYERS_AT
    orig_fetch = hubserver._fetch_sleeper_players_from_network
    orig_proj = hubserver._PROJECTIONS_CACHE

    def _boom():
        raise RuntimeError("network down")

    hubserver.SLEEPER_PLAYERS_CACHE = dict(stale)
    hubserver._SLEEPER_PLAYERS_AT = time.time() - hubserver._SLEEPER_PLAYERS_TTL - 10
    hubserver._fetch_sleeper_players_from_network = _boom
    hubserver._PROJECTIONS_CACHE = {"at": 0.0, "payload": None, "last_modified": ""}
    try:
        data = hubserver.get_sleeper_players_cached()
        assert isinstance(data, dict) and "1234" in data, "must serve stale on network fail"
        assert data["1234"]["full_name"] == "Stale Player"
        nm = hubserver.get_sleeper_player_name("1234")
        assert "Stale Player" in nm
        with urllib.request.urlopen(f"{hub_server_url}/hub-api/projections?limit=10", timeout=10) as r:
            assert r.status == 200, "projections must not 500 when Sleeper network fails"
            body = json.loads(r.read().decode("utf-8"))
            assert "players" in body
        time.sleep(0.5)
    finally:
        hubserver.SLEEPER_PLAYERS_CACHE = orig_cache
        hubserver._SLEEPER_PLAYERS_AT = orig_at
        hubserver._fetch_sleeper_players_from_network = orig_fetch
        hubserver._PROJECTIONS_CACHE = orig_proj
        hubserver._PROJECTIONS_CACHE = {"at": 0.0, "payload": None, "last_modified": ""}


# Multi-league routing additions (append-only; existing tests above untouched).


def test_resolve_league_id_validation(monkeypatch):
    import os
    monkeypatch.setenv("SLEEPER_LEAGUE_ID", "1397736035240173568")
    # why: ?league_id= becomes a filename — must be numeric, never a path.
    assert hubserver.resolve_league_id({"league_id": ["999"]}) == "999"
    assert hubserver.resolve_league_id({}) == "1397736035240173568"
    for bad in ("../evil", "abc", "1?x", "1#y", "-5", ""):
        try:
            out = hubserver.resolve_league_id({"league_id": [bad]})
        except ValueError:
            continue
        # "" falls back to env default; anything else must raise
        assert bad == "" and out == "1397736035240173568", bad


def test_db_path_for_request_allowlist(monkeypatch):
    import os
    monkeypatch.setenv("SLEEPER_LEAGUE_ID", "1397736035240173568")
    from pathlib import Path
    # default/env league keeps the legacy file
    assert hubserver.db_path_for_request("").name == "fantasy.db"
    assert hubserver.db_path_for_request("1397736035240173568").name == "fantasy.db"
    # other leagues get isolated files inside data/
    p = hubserver.db_path_for_request("999")
    assert p.name == "fantasy_999.db"
    assert "data" in p.parts
    for bad in ("../evil", "abc", "1?x"):
        try:
            hubserver.db_path_for_request(bad)
        except ValueError:
            continue
        raise AssertionError(f"db_path_for_request accepted {bad!r}")


def test_hub_league_id_invalid_400(hub_server_url):
    import urllib.error
    # why: traversal/non-numeric league_id must 400, never touch the FS.
    for bad in ("../evil", "..%2Fevil", "abc"):
        try:
            with urllib.request.urlopen(f"{hub_server_url}/hub-api/meta?league_id={bad}", timeout=10) as r:
                raise AssertionError(f"expected 400 for {bad}, got {r.status}")
        except urllib.error.HTTPError as e:
            assert e.code == 400, (bad, e.code)


def test_hub_unknown_league_db_503(hub_server_url):
    # why: a league with no synced DB degrades to generic 503 (setup-flow
    # signal), never 500/traceback/path disclosure.
    import urllib.error
    try:
        with urllib.request.urlopen(f"{hub_server_url}/hub-api/meta?league_id=424242", timeout=10) as r:
            body = json.loads(r.read().decode("utf-8"))
            assert "error" in body and "424242" not in json.dumps(body)
    except urllib.error.HTTPError as e:
        assert e.code == 503, e.code


def test_hub_draft_endpoint_mocked(hub_server_url, monkeypatch):
    # why: /hub-api/draft is live Sleeper — unit tests pin it, no network.
    fake = {"league_id": "424242", "league_name": "Mock League",
            "season": "2026", "total_rosters": 10, "draft_id": "d1",
            "draft_type": "auction", "auction_budget": 200, "draft_settings": {}}
    monkeypatch.setattr(hubserver, "get_cached_draft_info", lambda lid: dict(fake, league_id=lid))
    with urllib.request.urlopen(f"{hub_server_url}/hub-api/draft?league_id=424242", timeout=10) as r:
        assert r.status == 200
        body = json.loads(r.read().decode("utf-8"))
    assert body["league_name"] == "Mock League"
    assert body["draft_type"] == "auction"


def test_hub_waiver_falls_back_to_display_name_when_short_name_none(tmp_path):
    # why (user-caught live bug, 2026-09-10): handle_waiver is hand-duplicated
    # here (isolation: hub never imports ffanalytics/api.py), so the same
    # short_name-is-None fallback fix in api.py's _build_player_dict never
    # reached this code path. Confirmed live: waiver showed raw player_id
    # ("00-0038543") instead of "Jaxon Smith-Njigba".
    import sqlite3
    from http.server import HTTPServer
    db_path = tmp_path / "waiver.db"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE player_stats (season INT, week INT, data TEXT)")
    conn.execute(
        "INSERT INTO player_stats VALUES (2026, 1, ?)",
        (json.dumps([{
            "player_id": "00-0038543", "short_name": None,
            "player_display_name": "Jaxon Smith-Njigba",
            "position": "WR", "fantasy_points": 18.2,
        }]),),
    )
    conn.execute("CREATE TABLE rosters (season INT, week INT, data TEXT)")
    conn.execute("INSERT INTO rosters VALUES (2026, 1, '[]')")
    conn.commit()
    conn.close()
    orig_db = hubserver.Handler.db_path
    hubserver.Handler.db_path = db_path
    port = get_free_port()
    httpd = HTTPServer(('127.0.0.1', port), hubserver.Handler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    try:
        url = f"http://127.0.0.1:{port}/hub-api/waiver"
        with urllib.request.urlopen(url, timeout=10) as r:
            assert r.status == 200
            body = json.loads(r.read().decode("utf-8"))
            match = [p for p in body["recommendations"] if str(p.get("player_id")) == "00-0038543"]
            assert match, "fixture player missing from waiver recs"
            assert match[0]["player_name"] == "Jaxon Smith-Njigba"
    finally:
        httpd.shutdown()
        try:
            httpd.server_close()
        except Exception:
            pass
        hubserver.Handler.db_path = orig_db


def test_rosters_full_week_override_matches_by_name_when_gsis_id_missing(tmp_path, monkeypatch):
    # why (live bug 2026-09-15): Matchups week picker showed the same points
    # for every week because build_league_analytics ignored `week` entirely.
    # First fix keyed the weekly_projections override by gsis_id, but
    # Sleeper's /players/nfl only backfills gsis_id for ~1/3 of entries
    # (confirmed live: Jalen Hurts' Sleeper entry has gsis_id=None) — the
    # gsis-only lookup silently no-op'd for exactly those players, so the
    # override never had a visible effect for a majority-plausible roster.
    # name+position fallback (mirrors comp_by_name_pos elsewhere in this
    # function) closes that gap.
    import sqlite3
    from http.server import HTTPServer
    db_path = tmp_path / "week_override.db"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE rosters (season INT, week INT, data TEXT)")
    conn.execute(
        "INSERT INTO rosters VALUES (2026, 1, ?)",
        (json.dumps([{"roster_id": 1, "owner_id": "owner1",
                      "players": ["6904"], "starters": ["6904"]}]),),
    )
    conn.execute("CREATE TABLE player_stats (season INT, week INT, data TEXT)")
    conn.execute("INSERT INTO player_stats VALUES (2026, 1, '[]')")
    conn.execute(
        "CREATE TABLE weekly_projections (season INT, week INT, player_id TEXT, "
        "player_name TEXT, position TEXT, team TEXT, opponent_team TEXT, "
        "projected_points REAL, projection_lower REAL, projection_upper REAL, "
        "width REAL, wind_mph REAL, updated_at TEXT)"
    )
    conn.execute(
        "INSERT INTO weekly_projections VALUES "
        "(2026, 8, '00-0036389', 'Jalen Hurts', 'QB', 'PHI', 'WAS', "
        "20.85, 10.35, 31.35, 10.5, 0, '2026-09-15T00:00:00')"
    )
    conn.commit()
    conn.close()

    # Sleeper's own player identity cache — gsis_id=None mirrors the live
    # entry (roster's "6904" is Sleeper's own id for Jalen Hurts, PHI QB).
    monkeypatch.setattr(hubserver, "get_sleeper_players_cached", lambda: {
        "6904": {"full_name": "Jalen Hurts", "position": "QB", "team": "PHI", "gsis_id": None},
    })

    orig_db = hubserver.Handler.db_path
    hubserver.Handler.db_path = db_path
    port = get_free_port()
    httpd = HTTPServer(('127.0.0.1', port), hubserver.Handler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/hub-api/rosters-full?week=8", timeout=10) as r:
            assert r.status == 200
            body = json.loads(r.read().decode("utf-8"))
        assert body["meta"]["week"] == 8
        starters = next(iter(body["rosters"].values()))["starters"]
        hurts = next(p for p in starters if p["player_id"] == "6904")
        assert hurts["projected_points"] == pytest.approx(20.85)
        assert hurts["opponent_team"] == "WAS"
    finally:
        httpd.shutdown()
        try:
            httpd.server_close()
        except Exception:
            pass
        hubserver.Handler.db_path = orig_db


def test_hub_trade_fallback_ros_points_shape(tmp_path):
    # why: /hub-api/trade is the Trade tab fallback when :8000 is down; it
    # 404'd (no route) so the tab showed "no result". Hub sums
    # ros_projections.ros_points per side via sleeper_xwalk and returns the
    # same {winner, value_difference, recommendation} shape trade.js reads.
    import sqlite3
    import urllib.error
    from http.server import HTTPServer
    db_path = tmp_path / "trade.db"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE rosters (season INT, week INT, data TEXT)")
    conn.execute("INSERT INTO rosters VALUES (2026, 1, ?)", (json.dumps([
        {"roster_id": 1, "owner_id": "owner1", "players": ["s1", "s2"]},
        {"roster_id": 2, "owner_id": "owner2", "players": ["s3"]},
    ]),))
    conn.execute("CREATE TABLE sleeper_xwalk (sleeper_id TEXT, gsis_id TEXT)")
    conn.executemany("INSERT INTO sleeper_xwalk VALUES (?, ?)", [("s1", "g1"), ("s2", "g2"), ("s3", "g3")])
    conn.execute("CREATE TABLE ros_projections (season INT, player_id TEXT, player_name TEXT, position TEXT, team TEXT, ros_points REAL, remaining_games INT, per_game_neutral REAL, updated_at TEXT)")
    conn.executemany("INSERT INTO ros_projections VALUES (2026, ?, ?, 'WR', 'KC', ?, 17, 0, '')",
                     [("g1", "Alpha", 20.0), ("g2", "Beta", 10.0), ("g3", "Gamma", 12.0)])
    conn.commit()
    conn.close()
    orig_db = hubserver.Handler.db_path
    hubserver.Handler.db_path = db_path
    port = get_free_port()
    httpd = HTTPServer(('127.0.0.1', port), hubserver.Handler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/hub-api/trade?team_a_id=1&team_b_id=2", timeout=10) as r:
            assert r.status == 200
            body = json.loads(r.read().decode("utf-8"))
        assert body["winner"] == "Team A"
        assert body["value_difference"] == pytest.approx(18.0)
        assert "hub fallback" in body["recommendation"]
        assert body["meta"]["source"] == "hub-fallback:ros-points"
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/hub-api/trade?team_a_id=1&team_b_id=99", timeout=10)
        assert exc.value.code == 404
    finally:
        httpd.shutdown()
        try:
            httpd.server_close()
        except Exception:
            pass
        hubserver.Handler.db_path = orig_db


def test_hub_matchups_slate_uses_live_weather_table(tmp_path):
    # why: slate wind came from the schedule cache, whose wind/temp are
    # observed post-game values (null before kickoff) — preseason slates
    # showed wind 0 despite live Open-Meteo rows in weather. handle_matchups
    # now joins the latest weather row per home-team stadium coords.
    import sqlite3
    from http.server import HTTPServer
    db_path = tmp_path / "wx.db"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE sleeper_matchups (season INT, week INT, roster_id INT, matchup_id INT, points REAL, starters TEXT)")
    conn.execute("""CREATE TABLE weather (lat REAL, lon REAL, game_time_iso TEXT,
                    temp_f REAL, wind_mph REAL, precip_prob REAL, fetched_at TEXT)""")
    conn.execute("INSERT INTO weather VALUES (47.5952, -122.3316, '2026-09-15T12:00:00', 60.0, 25.0, 0.1, '2026-09-15T16:00:00')")
    conn.commit()
    conn.close()
    orig_db = hubserver.Handler.db_path
    hubserver.Handler.db_path = db_path
    port = get_free_port()
    httpd = HTTPServer(('127.0.0.1', port), hubserver.Handler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/hub-api/matchups?week=1", timeout=10) as r:
            assert r.status == 200
            body = json.loads(r.read().decode("utf-8"))
        sea = [g for g in body["nflSlate"] if g.get("home_team") == "SEA"]
        assert sea, "week-1 slate missing SEA home game"
        assert sea[0]["wind_mph"] == pytest.approx(25.0)
        assert sea[0]["weather_source"] == "forecast"
    finally:
        httpd.shutdown()
        try:
            httpd.server_close()
        except Exception:
            pass
        hubserver.Handler.db_path = orig_db


def test_hub_roster_items_carry_remaining_games(tmp_path, monkeypatch):
    # why (trade slot plan, Phase 5): the trade tab's ROS stat table and
    # dollarsFor remaining-games weight need per-player remaining_games.
    # ros_projections is the only store carrying it. Present row → int;
    # absent row → None (unknown, never 0 — 0 means no games left).
    import sqlite3
    from http.server import HTTPServer
    db_path = tmp_path / "rosgames.db"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE rosters (season INT, week INT, data TEXT)")
    conn.execute(
        "INSERT INTO rosters VALUES (2026, 1, ?)",
        (json.dumps([{"roster_id": 1, "owner_id": "owner1",
                      "players": ["6904", "6905"], "starters": ["6904"]}]),),
    )
    conn.execute("CREATE TABLE player_stats (season INT, week INT, data TEXT)")
    conn.execute("INSERT INTO player_stats VALUES (2026, 1, '[]')")
    conn.execute(
        "CREATE TABLE ros_projections (season INT, player_id TEXT, "
        "player_name TEXT, position TEXT, team TEXT, ros_points REAL, "
        "remaining_games INT, per_game_neutral REAL, updated_at TEXT)"
    )
    conn.execute(
        "INSERT INTO ros_projections VALUES "
        "(2026, '00-0036389', 'Jalen Hurts', 'QB', 'PHI', 300.0, 12, 25.0, '')"
    )
    conn.commit()
    conn.close()
    monkeypatch.setattr(hubserver, "get_sleeper_players_cached", lambda: {
        "6904": {"full_name": "Jalen Hurts", "position": "QB", "team": "PHI",
                 "gsis_id": "00-0036389"},
        "6905": {"full_name": "No Ros Row", "position": "WR", "team": "KC",
                 "gsis_id": "00-9999999"},
    })
    orig_db = hubserver.Handler.db_path
    hubserver.Handler.db_path = db_path
    # why reset (module-global 60s rosters-full cache, not keyed by db):
    # earlier rosters-full tests would otherwise serve their payload here.
    # Same save/reset/restore discipline as the projections-cache tests.
    orig_rf = hubserver._ROSTERS_FULL_CACHE
    hubserver._ROSTERS_FULL_CACHE = {"at": 0.0, "payload": None,
                                     "last_modified": ""}
    port = get_free_port()
    httpd = HTTPServer(('127.0.0.1', port), hubserver.Handler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    try:
        with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/hub-api/rosters-full", timeout=10) as r:
            assert r.status == 200
            body = json.loads(r.read().decode("utf-8"))
        all_items = []
        for team in body["rosters"].values():
            all_items += team.get("starters", []) + team.get("bench", [])
        by_pid = {p["player_id"]: p for p in all_items}
        assert by_pid["6904"]["remaining_games"] == 12
        assert isinstance(by_pid["6904"]["remaining_games"], int)
        assert by_pid["6905"]["remaining_games"] is None
    finally:
        httpd.shutdown()
        try:
            httpd.server_close()
        except Exception:
            pass
        hubserver.Handler.db_path = orig_db
        hubserver._ROSTERS_FULL_CACHE = orig_rf
