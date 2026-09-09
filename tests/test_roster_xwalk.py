"""Roster crosswalk tests: Sleeper roster ids -> GSIS stat ids.

Production finding (verified live: 169 rostered Sleeper ids vs 2025 GSIS
universe, 0 overlap): direct dict joins match NOTHING, silently emptying
start/sit, waiver and trade teams. The crosswalk fixes the join; direct
matches keep working (rookies, fixtures).
"""
import tempfile
from pathlib import Path

from ffanalytics import db
from ffanalytics import refresh
from ffanalytics.api import _process_roster_data

LEAGUE_SETTINGS = {
    "scoring_settings": {"rec": 1.0},
    "roster_positions": ["QB", "RB", "RB", "WR", "WR", "TE",
                         "FLEX", "FLEX", "K", "DEF", "BN", "BN", "BN", "BN"],
}

VET_STATS = {
    "player_id": "gsis-vet1",
    "player_display_name": "Test Veteran",
    "position": "WR",
    "position_group": "WR",
    "team": "BUF",
    "projected_points": 12.0,
    "fantasy_points": 12.0,
}


def _rosters(pid):
    return [{"owner_id": "1", "roster_id": 1, "players": [pid]}]


def test_build_sleeper_xwalk_filters():
    m = refresh.build_sleeper_xwalk({
        "99": {"gsis_id": "gsis-vet1"},
        "100": {"gsis_id": None},
        "101": {},
        "102": {"gsis_id": ""},
    })
    assert m == {"99": "gsis-vet1"}
    assert refresh.build_sleeper_xwalk(None) == {}
    assert refresh.build_sleeper_xwalk({}) == {}


def test_resolve_prefers_direct_then_xwalk():
    from ffanalytics.api import _resolve_base_stats

    lookup = {"gsis-vet1": VET_STATS, "rookie1": {"player_id": "rookie1"}}
    xwalk = {"99": "gsis-vet1"}
    # Direct hit wins even when xwalk has another mapping.
    assert _resolve_base_stats(lookup, xwalk, "rookie1") == {"player_id": "rookie1"}
    # Crosswalk fallback resolves the veteran.
    assert _resolve_base_stats(lookup, xwalk, "99") == VET_STATS
    # Missing everywhere stays missing (caller skips, as before).
    assert _resolve_base_stats(lookup, xwalk, "0000") == {}
    assert _resolve_base_stats(lookup, None, "99") == {}


def test_process_roster_data_crosswalk_end_to_end():
    rosters = _rosters("99")
    # Without the crosswalk the veteran silently vanishes (old behavior).
    empty = _process_roster_data(rosters, [VET_STATS], {}, LEAGUE_SETTINGS, owner_id="1")
    assert empty[0] == [] and empty[1] == []
    # With it, the rostered veteran resolves (identity stays the Sleeper id).
    roster, bench, _free = _process_roster_data(
        rosters, [VET_STATS], {}, LEAGUE_SETTINGS, owner_id="1",
        sleeper_xwalk={"99": "gsis-vet1"},
    )
    assert len(roster) + len(bench) == 1
    assert (roster + bench)[0]["player_id"] == "99"


def test_v7_table_exists_after_init():
    tmp = tempfile.TemporaryDirectory()
    conn = db.get_connection(Path(tmp.name) / "test.db")
    db.init_schema(conn)
    tables = {r["name"] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert "sleeper_xwalk" in tables
    ver = conn.execute("PRAGMA user_version").fetchone()[0]
    assert ver >= 7
    conn.close()


def test_xwalk_loader_coerces_int_ids_to_str():
    # why (code-reviewer sign-off): SQLite TEXT columns accept INTEGER
    # values; an int-typed legacy row would silently miss the join (both
    # sides must share one type contract) and drop players.
    from unittest.mock import patch

    from ffanalytics.api import _sleeper_xwalk_for

    tmp = tempfile.TemporaryDirectory()
    conn = db.get_connection(Path(tmp.name) / "test.db")
    db.init_schema(conn)
    conn.execute(
        "INSERT INTO sleeper_xwalk (sleeper_id, gsis_id) VALUES (?, ?)", (99, "gsis-vet1")
    )
    conn.commit()
    with patch("ffanalytics.db._get_conn", return_value=conn):
        xw = _sleeper_xwalk_for({}, None)
    assert xw == {"99": "gsis-vet1"}
    assert all(isinstance(k, str) and isinstance(v, str) for k, v in xw.items())
    conn.close()
