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


def test_build_sleeper_team_map_canonicalizes_rams():
    # why (user-caught live bug, 2026-09-10): Sleeper's LAR vs the
    # schedule/hub LA convention — the map must emit canonical codes or
    # every downstream team filter quietly drops Rams rows.
    m = refresh.build_sleeper_team_map({
        "1": {"full_name": "Test Ram", "position": "WR", "team": "LAR"},
    })
    assert m == {("test ram", "WR"): "LA"}


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


def test_build_sleeper_xwalk_direct_gsis_id():
    xwalk = refresh.build_sleeper_xwalk({
        "4046": {"gsis_id": "00-0033873", "full_name": "Patrick Mahomes", "position": "QB"},
    })
    assert xwalk == {"4046": "00-0033873"}


def test_build_sleeper_xwalk_name_fallback_when_gsis_missing():
    # why (user-caught, live bug): real player, real Sleeper record, but
    # Sleeper's own gsis_id field is None (data gap, not a code bug) —
    # Kenneth Walker III confirmed live. Name+pos fallback (same
    # normalization as patch_proj_teams) closes it without depending on
    # Sleeper's field being populated.
    xwalk = refresh.build_sleeper_xwalk(
        {"8151": {"gsis_id": None, "full_name": "Kenneth Walker", "position": "RB"}},
        name_pos_to_gsis={("kenneth walker", "RB"): "00-0038134"},
    )
    assert xwalk == {"8151": "00-0038134"}


def test_build_sleeper_xwalk_no_fallback_stays_unmapped():
    # no name_pos_to_gsis supplied, and no direct gsis_id -> skipped, not crashed
    xwalk = refresh.build_sleeper_xwalk({
        "8151": {"gsis_id": None, "full_name": "Kenneth Walker", "position": "RB"},
    })
    assert xwalk == {}


def test_patch_proj_teams_matches_across_name_suffix_mismatch():
    # why (user-caught, live bug): Sleeper stores "Kenneth Walker" (no
    # suffix), nflverse stores "Kenneth Walker III" — pre-fix, the raw
    # lowercase key never matched and a real trade (SEA -> KC) never
    # patched, leaving the stale prior-season team standing. Generic fix
    # (_norm_name_pos strips Jr./Sr./II-V both sides), verified here with a
    # suffix on one side only, matching the real-world asymmetry.
    projs = [
        {"player_id": "8151", "player_display_name": "Kenneth Walker III",
         "position": "RB", "team": "SEA", "recent_team": "SEA", "opponent_team": ""},
    ]
    team_map = refresh.build_sleeper_team_map({
        "8151": {"full_name": "Kenneth Walker", "position": "RB", "team": "KC"},
    })
    assert refresh.patch_proj_teams(projs, team_map, {"KC": "DEN"}) == 1
    assert projs[0]["team"] == "KC"
    assert projs[0]["recent_team"] == "KC"
    assert projs[0]["opponent_team"] == "DEN"


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


def test_build_rookie_rows_canonicalizes_rams_and_remaps_opponent():    # why (user-caught live bug, 2026-09-10): Sleeper LAR rookie rows kept
    # LAR while opp_map is schedule-keyed (LA) — opponent remap missed and
    # team filters dropped them. Canonical code fixes both at once.
    rows = refresh.build_rookie_rows(
        {"200": {"full_name": "Ram Rookie", "position": "WR", "team": "LAR",
                 "years_exp": 0, "active": True}},
        set(), {"LA": "SF"}, week=1,
    )
    assert len(rows) == 1
    assert rows[0]["team"] == "LA" and rows[0]["recent_team"] == "LA"
    assert rows[0]["opponent_team"] == "SF"


def test_build_out_gsis_set_statuses_and_gaps():
    # why (backtested zero-Out-weekly, 2026-09-10): only confirmed outs
    # zero; Questionable stays (backend convention), None gsis_id gaps
    # (cf. build_sleeper_xwalk) degrade to absent, unknown sids skipped.
    sp = {
        "10": {"gsis_id": "00-001", "full_name": "Out Vet", "position": "QB"},
        "11": {"gsis_id": None, "full_name": "Gap Man", "position": "RB"},
        "12": {"gsis_id": "00-003", "full_name": "Question Mark", "position": "WR"},
    }
    inj = {"10": "Out", "11": "IR", "12": "Questionable", "13": "Out", "14": None}
    assert refresh.build_out_gsis_set(sp, inj) == {"00-001"}
    assert refresh.build_out_gsis_set({}, {"10": "Out"}) == set()
    assert refresh.build_out_gsis_set(sp, {}) == set()
    assert refresh.build_out_gsis_set(sp, None) == set()


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
               "years_exp": 5, "active": True, "gsis_id": "gsis-vet1"},
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
    # why back up/restore, not just delete after (user-caught live bug,
    # 2026-09-10): this test writes to the REAL repo path (refresh.py
    # resolves it relative to its own file location, not injectable) — the
    # same path hub/server.py reads live for weather/NFL-slate display.
    # Leaving fake KC-vs-BUF test data there after the suite runs would
    # break that display for real; leaving nothing would re-introduce the
    # exact bug this test is guarding against (file never refreshed).
    sched_cache_path = (
        Path(__file__).resolve().parent.parent / "data" / "nfl_cache" / "schedule_2026.json"
    )
    sched_backup = sched_cache_path.read_text() if sched_cache_path.exists() else None
    try:
        _, data = refresh.run_refresh_with_data(
            conn, season=2026, sleeper_session=_mock_sleeper_session(players_map),
            nfl_module=fake_nfl, ran_at_iso="2026-09-09T12:00:00",
            stats_season=2025, league_id="123",
        )
        # hub/server.py reads this exact path for weather/NFL-slate display
        # (isolation contract: hub can't fetch schedule data itself) — only
        # scripts/seed_demo.py ever wrote it before this fix, once, at
        # initial bootstrap, never refreshed again.
        assert sched_cache_path.exists()
        import json as _json
        written = _json.loads(sched_cache_path.read_text())
        assert any(g.get("home_team") == "KC" and g.get("away_team") == "BUF" for g in written)
    finally:
        if sched_backup is not None:
            sched_cache_path.write_text(sched_backup)
        elif sched_cache_path.exists():
            sched_cache_path.unlink()
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
    # Crosswalk: stored to DB + returned for cache (roster joins need it).
    # "100": "100" is the rookie's own row — no real gsis_id exists yet, so
    # build_rookie_rows uses the sleeper_id as a placeholder player_id; the
    # name-fallback (Task: Kenneth Walker III fix) correctly maps it to
    # itself. Harmless — _resolve_base_stats already direct-matches "100"
    # either way.
    assert data["sleeper_xwalk"] == {"99": "gsis-vet1", "100": "100"}
    db_rows = {r["sleeper_id"]: r["gsis_id"] for r in conn.execute(
        "SELECT sleeper_id, gsis_id FROM sleeper_xwalk").fetchall()}
    assert db_rows == {"99": "gsis-vet1", "100": "100"}
    conn.close()


def test_xwalk_resolves_player_absent_from_this_weeks_stats():
    # why (user-caught live bug, 2026-09-10): the name+pos xwalk fallback
    # only matched players with a row in THIS week's player_stats — a real
    # starter who didn't play (bye/injury/backup) had no row to match
    # against, even though their gsis_id is a stable identity unrelated to
    # weekly participation. Confirmed live: Brock Purdy (real SF starter,
    # simply hadn't posted a week-1 stat line) failed to resolve for
    # exactly this reason. load_players() (nflverse's full ~25k player
    # identity list, not week-filtered) closes the gap — this player
    # appears ONLY there, not in player_stats, and must still resolve.
    conn, tmp = _fresh_conn()
    players_map = {
        "501": {"full_name": "Bench Starter", "position": "QB", "team": "SF",
                "years_exp": 3, "active": True, "status": "Active"},
    }
    fake_nfl = Mock()

    class _Frame:
        def __init__(self, rows):
            self._rows = rows

        def to_dicts(self):
            return self._rows

    # deliberately NO player_stats row for "Bench Starter" — only in load_players()
    fake_nfl.load_player_stats.return_value = _Frame(_vet_rows())
    fake_nfl.load_players.return_value = _Frame([
        {"gsis_id": "gsis-bench1", "display_name": "Bench Starter", "position": "QB"},
    ])
    fake_nfl.load_schedules.return_value = _Frame([
        {"week": 1, "game_type": "REG", "season": 2026, "home_team": "KC", "away_team": "BUF"},
    ])
    sched_cache_path = (
        Path(__file__).resolve().parent.parent / "data" / "nfl_cache" / "schedule_2026.json"
    )
    sched_backup = sched_cache_path.read_text() if sched_cache_path.exists() else None
    try:
        _, data = refresh.run_refresh_with_data(
            conn, season=2026, sleeper_session=_mock_sleeper_session(players_map),
            nfl_module=fake_nfl, ran_at_iso="2026-09-09T12:00:00",
            stats_season=2025, league_id="123",
        )
        assert data["sleeper_xwalk"].get("501") == "gsis-bench1"
    finally:
        if sched_backup is not None:
            sched_cache_path.write_text(sched_backup)
        elif sched_cache_path.exists():
            sched_cache_path.unlink()
        conn.close()


def test_prune_props_tables_keeps_pending():
    from ffanalytics import shadow

    conn, tmp = _fresh_conn()
    try:
        conn.execute(
            "INSERT INTO prop_lines (player_id, season, week, market, side,"
            " line, price, book, created_at) VALUES "
            "('1', 2025, 4, 'passing_yards', 'over', 250.5, -110, 'manual', '2025-01-01T00:00:00'),"
            "('2', 2026, 5, 'passing_yards', 'over', 250.5, -110, 'manual', '2026-09-01T00:00:00')"
        )
        conn.commit()
        old_res = shadow.log_recommendation(
            conn, kind="prop:passing_yards", season=2025, week=4, player_id="1",
            recommendation={"a": 1}, logged_at_iso="2025-01-01T00:00:00")
        shadow.record_outcome(conn, old_res, {"hit": True})
        old_unres = shadow.log_recommendation(
            conn, kind="prop:passing_yards", season=2025, week=4, player_id="3",
            recommendation={"a": 2}, logged_at_iso="2025-01-01T00:00:00")
        out = refresh.prune_props_tables(conn, "2026-09-09T00:00:00", ttl_days=180)
        assert out == {"prop_lines": 1, "shadow_resolved": 1}
        remaining_lines = {r["player_id"] for r in
                           conn.execute("SELECT player_id FROM prop_lines").fetchall()}
        assert remaining_lines == {"2"}
        remaining_shadow = {r["id"] for r in conn.execute(
            "SELECT id FROM shadow_recommendations").fetchall()}
        # resolved-old gone; unresolved-old stays pending.
        assert old_unres in remaining_shadow and old_res not in remaining_shadow
    finally:
        conn.close()