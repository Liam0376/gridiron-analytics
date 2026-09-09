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


def test_build_sleeper_team_map_skips_incomplete():
    m = refresh.build_sleeper_team_map({
        "1": {"full_name": "Test Veteran", "position": "WR", "team": "BUF"},
        "2": {"full_name": "No Team", "position": "WR", "team": None},
        "3": {"full_name": None, "position": "WR", "team": "KC"},
        "4": None,
    })
    assert m == {("test veteran", "WR"): "BUF"}


def test_patch_proj_teams_mover_stayer_unknown():
    projs = [
        {"player_id": "a", "player_display_name": "Test Veteran",
         "position": "WR", "team": "KC", "recent_team": "KC", "opponent_team": ""},
        {"player_id": "b", "player_display_name": "Homebody",
         "position": "RB", "team": "KC", "recent_team": "KC", "opponent_team": ""},
        {"player_id": "c", "player_display_name": "Mystery Man",
         "position": "WR", "team": "KC", "recent_team": "KC", "opponent_team": ""},
    ]
    team_map = {("test veteran", "WR"): "BUF", ("homebody", "RB"): "KC"}
    opp_map = {"BUF": "MIA", "KC": "DEN"}
    assert refresh.patch_proj_teams(projs, team_map, opp_map) == 1
    assert projs[0]["team"] == "BUF" and projs[0]["recent_team"] == "BUF"
    assert projs[0]["opponent_team"] == "MIA"
    assert projs[1]["team"] == "KC" and projs[1]["opponent_team"] == ""
    assert projs[2]["team"] == "KC"


def test_build_rookie_rows_filters_and_flags():
    sp_map = {
        "100": {"full_name": "Test Rookie", "position": "WR", "team": "KC",
                "years_exp": 0, "active": True, "status": "Active"},
        "101": {"full_name": "Old Vet", "position": "WR", "team": "KC",
                "years_exp": 5, "active": True},
        "102": {"full_name": "Teamless", "position": "WR", "team": None,
                "years_exp": 0, "active": True},
        "103": {"full_name": "Already There", "position": "RB", "team": "KC",
                "years_exp": 0, "active": True},
        "104": {"full_name": "Kicker Kid", "position": "K", "team": "DAL",
                "years_exp": 0, "active": True},
    }
    rows = refresh.build_rookie_rows(
        sp_map, {("already there", "RB")}, {"KC": "BUF", "DAL": "PHI"}, week=1,
    )
    by_id = {r["player_id"]: r for r in rows}
    assert set(by_id) == {"100", "104"}
    r = by_id["100"]
    assert r["player_display_name"] == "Test Rookie"
    assert r["projected_points"] == 0.0
    assert r["is_empty_projection"] is True and r["is_rookie_unknown"] is True
    assert r["opponent_team"] == "BUF" and r["week"] == 1


def _mock_sleeper_session(players_map):
    session = Mock()

    def _resp(payload):
        r = Mock()
        r.json.return_value = payload
        r.raise_for_status.return_value = None
        return r

    def _get(url, **kwargs):
        if "players/nfl" in url:
            return _resp(players_map)
        if "/rosters" in url:
            return _resp([])
        if "/users" in url:
            return _resp([])
        if "/draft" in url:
            return _resp({})
        if "matchups" in url:
            return _resp([])
        if "projections" in url:
            return _resp({})
        return _resp({"scoring_settings": {"rec": 1.0}, "roster_positions": []})

    session.get.side_effect = _get
    return session


def _vet_rows():
    rows = []
    for w in range(1, 18):
        rows.append({
            "player_id": "gsis-vet1", "position": "WR", "team": "KC",
            "week": w, "season": 2025, "season_type": "REG",
            "player_display_name": "Test Veteran",
            "receiving_yards": 60.0, "receiving_tds": 0, "receptions": 5,
            "rushing_yards": 0.0, "rushing_tds": 0, "fumbles_lost_total": 0,
        })
    return rows


def test_preseason_refresh_patches_teams_and_adds_rookies():
    # why URL-router mock, not side_effect list: the hoisted Sleeper-players
    # fetch added a GET — positional lists would silently misroute.
    conn, tmp = _fresh_conn()
    players_map = {
        "99": {"full_name": "Test Veteran", "position": "WR", "team": "BUF",
               "years_exp": 5, "active": True},
        "100": {"full_name": "Test Rookie", "position": "WR", "team": "KC",
                "years_exp": 0, "active": True, "status": "Active"},
    }
    fake_nfl = Mock()

    class _Frame:
        def __init__(self, rows):
            self._rows = rows

        def to_dicts(self):
            return self._rows

    fake_nfl.load_player_stats.return_value = _Frame(_vet_rows())
    fake_nfl.load_schedules.return_value = _Frame([
        {"week": 1, "game_type": "REG", "season": 2026,
         "home_team": "KC", "away_team": "BUF"},
        {"week": 1, "game_type": "REG", "season": 2026,
         "home_team": "MIA", "away_team": "NYJ"},
    ])
    _, data = refresh.run_refresh_with_data(
        conn, season=2026, sleeper_session=_mock_sleeper_session(players_map),
        nfl_module=fake_nfl, ran_at_iso="2026-09-09T12:00:00",
        stats_season=2025, league_id="123",
    )
    projs = {p["player_id"]: p for p in data["model_projections"]}
    # Mover patched KC -> BUF with remapped opponent (BUF hosts MIA? no:
    # week-1 fixture has BUF away at KC, so BUF's opponent is KC).
    assert projs["gsis-vet1"]["team"] == "BUF"
    assert projs["gsis-vet1"]["opponent_team"] == "KC"
    # Rookie present, identified, flagged — not invisible, not imputed.
    assert projs["100"]["player_display_name"] == "Test Rookie"
    assert projs["100"]["team"] == "KC"
    assert projs["100"]["is_empty_projection"] is True
    blob_ids = {str(p.get("player_id")) for p in data["player_stats"]}
    assert {"gsis-vet1", "100"} <= blob_ids
    conn.close()