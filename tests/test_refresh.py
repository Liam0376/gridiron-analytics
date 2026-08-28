import tempfile
from pathlib import Path
from unittest.mock import Mock

from ffanalytics import db, refresh

def _fresh_conn():
    tmp = tempfile.TemporaryDirectory()
    path = Path(tmp.name) / "test.db"
    conn = db.get_connection(path)
    db.init_schema(conn)
    return conn, tmp


def test_run_refresh_all_sources_succeed():
    conn, tmp = _fresh_conn()
    sleeper_session = Mock()
    league_resp = Mock()
    league_resp.json.return_value = {
        "scoring_settings": {"rec": 1.0}, "roster_positions": ["QB"]
    }
    league_resp.raise_for_status.return_value = None
    rosters_resp = Mock()
    rosters_resp.json.return_value = [{"roster_id": 1}]
    rosters_resp.raise_for_status.return_value = None
    players_resp = Mock()
    players_resp.json.return_value = {}
    players_resp.raise_for_status.return_value = None
    sleeper_session.get.side_effect = [league_resp, rosters_resp, players_resp]

    fake_nfl = Mock()
    class _Frame:
        def to_dicts(self):
            return [{"player_id": "4046", "target_share": 0.3}]
    fake_nfl.load_player_stats.return_value = _Frame()
    fake_nfl.load_schedules.return_value = _Frame()

    result = refresh.run_refresh(
        conn, season=2026, sleeper_session=sleeper_session, nfl_module=fake_nfl,
        ran_at_iso="2026-09-10T09:00:00",
    )
    assert result["sleeper"] is True
    assert result["nflverse"] is True
    rows = conn.execute("SELECT source, success FROM refresh_log WHERE source IN ('sleeper', 'nflverse')").fetchall()
    assert {(r["source"], r["success"]) for r in rows} == {
        ("sleeper", 1), ("nflverse", 1)
    }
    conn.close()


def test_run_refresh_nflverse_failure_logs_and_continues():
    conn, tmp = _fresh_conn()
    sleeper_session = Mock()
    league_resp = Mock()
    league_resp.json.return_value = {"scoring_settings": {}, "roster_positions": []}
    league_resp.raise_for_status.return_value = None
    rosters_resp = Mock()
    rosters_resp.json.return_value = []
    rosters_resp.raise_for_status.return_value = None
    players_resp = Mock()
    players_resp.json.return_value = {}
    players_resp.raise_for_status.return_value = None
    sleeper_session.get.side_effect = [league_resp, rosters_resp, players_resp]

    fake_nfl = Mock()
    fake_nfl.load_player_stats.side_effect = ConnectionError("boom")
    class _EmptyFrame:
        def to_dicts(self):
            return []
    fake_nfl.load_schedules.return_value = _EmptyFrame()

    result = refresh.run_refresh(
        conn, season=2026, sleeper_session=sleeper_session, nfl_module=fake_nfl,
        ran_at_iso="2026-09-10T09:00:00",
    )
    assert result["sleeper"] is True
    assert result["nflverse"] is False
    row = conn.execute(
        "SELECT success, error_message FROM refresh_log WHERE source = 'nflverse'"
    ).fetchone()
    assert row["success"] == 0
    assert "boom" in row["error_message"]
    conn.close()