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
