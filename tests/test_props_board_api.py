"""GET /props/board tests: fair-line browsing, no book line required.

Renamed/trimmed from test_props_api.py 2026-09-10 — the manual book-line/
edge system (POST /props/lines, GET /props/edges, _evaluate_prop_edge) was
deleted: no free player-prop odds feed exists (game-level spread/total/
moneyline is free via nflverse's schedule dataset — player props are a
separate, paid product; theoddsapi.com's Business tier was evaluated and
rejected in the original props spec), and its UI (edge board, "Add a book
line" form) was removed per user request, leaving it unreachable. These
6 tests (the only ones actually exercising /props/board) carried over
unchanged; the other ~18 tested the deleted endpoints.

DB isolation: patch ffanalytics.db._get_conn to a tmp-DB conn (init_schema'd).
Cache isolation: snapshot/restore _CACHE.
"""
import tempfile
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from ffanalytics import db
from ffanalytics.api import _CACHE, _fair_board_rows, app

client = TestClient(app)

SEASON, WEEK = 2025, 5

_MAHOMES_PROJ = {
    "player_id": "2544", "player_display_name": "Patrick Mahomes",
    "position": "QB", "position_group": "QB", "team": "KC",
    "passing_yards": 270.0, "passing_tds": 2.1, "rushing_yards": 18.0,
    "rushing_tds": 0.1, "is_empty_projection": False, "week": WEEK,
}
_MAHOMES_HIST = [
    {"player_id": "2544", "player_display_name": "Patrick Mahomes", "position": "QB", "team": "KC", "week": w,
     "season_type": "REG", "passing_yards": y, "passing_tds": 2}
    for w, y in [(1, 250.0), (2, 260.0), (3, 240.0), (4, 270.0)]
]
_WR_PROJ = {
    "player_id": "7500", "player_display_name": "Test WR",
    "position": "WR", "position_group": "WR", "team": "BUF",
    "receiving_yards": 65.0, "receiving_tds": 0.5, "receptions": 5.0,
    "rushing_yards": 0.0, "rushing_tds": 0.0, "is_empty_projection": False,
    "week": WEEK,
}
_WR_HIST = [
    {"player_id": "7500", "player_display_name": "Test WR", "position": "WR", "team": "BUF", "week": w,
     "season_type": "REG", "receiving_yards": 60.0 + w, "receptions": r}
    for w, r in [(1, 4), (2, 5), (3, 4), (4, 6)]
]
_EMPTY_PROJ = {
    "player_id": "9999", "player_display_name": "Rookie Unknown",
    "position": "WR", "position_group": "WR", "team": "NYJ",
    "receiving_yards": 0.0, "receptions": 0.0, "is_empty_projection": True,
    "week": WEEK,
}
_NEG_QB_PROJ = {
    "player_id": "5555", "player_display_name": "Third String",
    "position": "QB", "position_group": "QB", "team": "KC",
    "passing_yards": -2.9, "passing_tds": 0.0, "rushing_yards": 0.0,
    "rushing_tds": 0.0, "is_empty_projection": False, "week": WEEK,
}


def _fresh_db():
    tmp = tempfile.TemporaryDirectory()
    conn = db.get_connection(Path(tmp.name) / "test.db")
    db.init_schema(conn)
    return conn, tmp


def _snap():
    return dict(_CACHE)


def _restore(snap):
    _CACHE.clear()
    _CACHE.update(snap)


def _warm():
    _CACHE.update({
        "league_settings": {"scoring_settings": {}, "roster_positions": []},
        "rosters": [],
        "player_stats": _MAHOMES_HIST + _WR_HIST,
        "model_projections": [_MAHOMES_PROJ, _WR_PROJ, _EMPTY_PROJ],
        "injury_status": {},
        "season": SEASON,
        "week": WEEK,
        "last_updated": "2026-09-09T00:00:00",
    })


def test_props_board_returns_fair_lines_without_stored_book_line():
    conn, tmp = _fresh_db()
    snap = _snap()
    try:
        _warm()
        with patch("ffanalytics.db._get_conn", return_value=conn):
            resp = client.get("/props/board", params={"teams": "KC", "season": SEASON, "week": WEEK})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["teams"] == ["KC"]
        markets = {r["market"] for r in body["players"] if r["player_id"] == "2544"}
        assert "passing_yards" in markets
        assert "anytime_td" in markets
        row = next(r for r in body["players"] if r["player_id"] == "2544" and r["market"] == "passing_yards")
        # on-demand recompute from weeks<5 history (no prior pool seeded):
        # weighted recent of [250,260,240,270] with last-2 doubled (no trend:
        # <3 prior games; no Vegas/weather: no schedule seeded)
        assert row["fair_line"] == 255.0
        assert row["sigma"] is not None
        assert row["player_name"] == "Patrick Mahomes"
        # WR is BUF, not KC — excluded from a KC-only board
        assert all(r["player_id"] != "7500" for r in body["players"])
    finally:
        _restore(snap)
        conn.close()


def test_props_board_two_teams_and_empty_projection_excluded():
    conn, tmp = _fresh_db()
    snap = _snap()
    try:
        _warm()
        with patch("ffanalytics.db._get_conn", return_value=conn):
            resp = client.get("/props/board", params={"teams": "KC,BUF", "season": SEASON, "week": WEEK})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        ids = {r["player_id"] for r in body["players"]}
        assert "2544" in ids  # KC
        assert "7500" in ids  # BUF
        assert "9999" not in ids  # NYJ rookie, is_empty_projection=True, wrong team anyway
    finally:
        _restore(snap)
        conn.close()


def test_props_board_skips_negative_fair_lines():
    # why (user-caught live bug, 2026-09-10): history-less third QBs can
    # project negative yardage (Garoppolo -2.9) without tripping
    # is_empty_projection. No book posts a negative line — skip the market,
    # keep the player's other (non-negative) markets. Unit-level: board
    # universes come from stats pools, which can't produce negatives.
    proj = {
        "player_id": "5555", "player_display_name": "Third String",
        "position": "QB", "position_group": "QB", "team": "KC",
        "passing_yards": -2.9, "passing_tds": 0.0, "rushing_yards": 0.0,
        "rushing_tds": 0.0, "is_empty_projection": False,
    }
    rows = _fair_board_rows(proj, [], None)
    assert rows, "player should still appear via non-negative markets"
    assert all(r["fair_line"] >= 0 for r in rows)
    assert "passing_yards" not in {r["market"] for r in rows}


def test_props_board_flags_unavailable_player_never_hides_them():
    # why: user-caught bug — an OUT/IR player's stale projection rendered
    # exactly like an active player's, no status shown. Board must fetch
    # real injury status (sleeper-keyed) via the gsis<->sleeper xwalk and
    # flag it, never hardcode a specific player, never silently drop them
    # (dropping is its own dishonesty — hiding the model's blind spot).
    conn, tmp = _fresh_db()
    snap = _snap()
    try:
        _warm()
        _CACHE.update({
            "sleeper_xwalk": {"9001": "2544", "9002": "7500"},  # {sleeper_id: gsis_id}
            "injury_status": {"9001": "Out", "9002": None},
        })
        with patch("ffanalytics.db._get_conn", return_value=conn):
            resp = client.get("/props/board", params={"teams": "KC,BUF", "season": SEASON, "week": WEEK})
        assert resp.status_code == 200, resp.text
        rows = resp.json()["players"]
        mahomes_rows = [r for r in rows if r["player_id"] == "2544"]
        wr_rows = [r for r in rows if r["player_id"] == "7500"]
        assert mahomes_rows and all(r["sleeper_id"] == "9001" for r in mahomes_rows)
        assert all(r["injury_status"] == "Out" for r in mahomes_rows)
        assert all(r["available"] is False for r in mahomes_rows)
        # still present and flagged — but zeroed, not stale: the backtested
        # zero-Out-weekly rule zeroes confirmed outs (was: "real fair line").
        assert any(r["market"] == "passing_yards" and r["fair_line"] == 0.0 for r in mahomes_rows)
        assert wr_rows and all(r["available"] is True for r in wr_rows)
    finally:
        _restore(snap)
        conn.close()


def test_props_board_no_xwalk_leaves_status_unknown_not_crashed():
    # why: missing/empty crosswalk (fresh DB, no sleeper sync yet) must
    # degrade to injury_status=None/available=True, never 500.
    conn, tmp = _fresh_db()
    snap = _snap()
    try:
        _warm()
        with patch("ffanalytics.db._get_conn", return_value=conn):
            resp = client.get("/props/board", params={"teams": "KC", "season": SEASON, "week": WEEK})
        assert resp.status_code == 200, resp.text
        rows = resp.json()["players"]
        assert all(r["sleeper_id"] is None for r in rows)
        assert all(r["available"] is True for r in rows)
    finally:
        _restore(snap)
        conn.close()


def test_props_board_shows_actual_once_week_is_played():
    conn, tmp = _fresh_db()
    snap = _snap()
    try:
        _warm()
        _CACHE.update({
            "player_stats": _MAHOMES_HIST + _WR_HIST + [
                {"player_id": "2544", "position": "QB", "team": "KC", "week": WEEK,
                 "season_type": "REG", "passing_yards": 301.0, "passing_tds": 3,
                 "is_empty_projection": False},
            ],
        })
        with patch("ffanalytics.db._get_conn", return_value=conn):
            resp = client.get("/props/board", params={"teams": "KC", "season": SEASON, "week": WEEK})
        assert resp.status_code == 200, resp.text
        rows = resp.json()["players"]
        row = next(r for r in rows if r["player_id"] == "2544" and r["market"] == "passing_yards")
        assert row["fair_line"] == 255.0  # recomputed from weeks<5 history, unaffected by the week-5 row
        assert row["actual"] == 301.0     # real box score for this week
    finally:
        _restore(snap)
        conn.close()

def test_props_board_503_without_cache():
    conn, tmp = _fresh_db()
    snap = _snap()
    try:
        _CACHE.update({"model_projections": None, "player_stats": None})
        with patch("ffanalytics.db._get_conn", return_value=conn):
            resp = client.get("/props/board", params={"teams": "KC"})
        assert resp.status_code == 503
    finally:
        _restore(snap)
        conn.close()


def test_props_board_week_changes_fair_lines():
    # why (user-caught live bug, 2026-09-10): the board read a
    # single-target-week cache, so every game modal showed identical lines
    # regardless of week (Purdy 240.65 week 1 and week 5). Fair lines must
    # follow the requested week's history window.
    conn, tmp = _fresh_db()
    snap = _snap()
    try:
        _warm()
        with patch("ffanalytics.db._get_conn", return_value=conn):
            early = client.get("/props/board", params={"teams": "KC", "season": SEASON, "week": 2})
            late = client.get("/props/board", params={"teams": "KC", "season": SEASON, "week": WEEK})
        assert early.status_code == 200 and late.status_code == 200
        def pyards(body):
            return next(r["fair_line"] for r in body.json()["players"]
                        if r["player_id"] == "2544" and r["market"] == "passing_yards")
        # week 2 sees only week 1 ([250], no prior pool seeded)
        assert pyards(early) == 250.0
        # week 5 sees weeks 1-4 -> different number
        assert pyards(late) == 255.0
    finally:
        _restore(snap)
        conn.close()


def test_props_board_prior_pool_covers_preseason_player():
    # why: with no same-season history yet (preseason / week 1), the board
    # must still list veterans via the prior-season pool — otherwise early
    # boards show only box-score teams.
    conn, tmp = _fresh_db()
    snap = _snap()
    try:
        _warm()
        _CACHE["player_stats"] = [r for r in _CACHE["player_stats"]
                                  if not (r["player_id"] == "2544" and r["week"] in (1, 2, 3, 4))]
        _CACHE["prior_season_stats"] = [
            {"player_id": "2544", "position": "QB", "team": "KC", "week": w,
             "season": 2024, "season_type": "REG", "passing_yards": 200.0,
             "passing_tds": 1, "passing_interceptions": 1,
             "rushing_yards": 10.0, "rushing_tds": 0}
            for w in range(1, 18)
        ]
        with patch("ffanalytics.db._get_conn", return_value=conn):
            resp = client.get("/props/board", params={"teams": "KC", "season": SEASON, "week": 2})
        assert resp.status_code == 200, resp.text
        rows = [r for r in resp.json()["players"]
                if r["player_id"] == "2544" and r["market"] == "passing_yards"]
        assert rows and rows[0]["fair_line"] == 200.0
    finally:
        _restore(snap)
        conn.close()
