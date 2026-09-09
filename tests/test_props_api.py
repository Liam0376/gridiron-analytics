"""Props API tests: validation, store/upsert, edges math, shadow gating.

DB isolation: patch ffanalytics.db._get_conn to a tmp-DB conn (init_schema'd).
Cache isolation: snapshot/restore _CACHE (incl. the new model_projections key).
"""
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from ffanalytics import db, shadow
from ffanalytics.api import _CACHE, app

client = TestClient(app)

SEASON, WEEK = 2025, 5

_MAHOMES_PROJ = {
    "player_id": "2544", "player_display_name": "Patrick Mahomes",
    "position": "QB", "position_group": "QB", "team": "KC",
    "passing_yards": 270.0, "passing_tds": 2.1, "rushing_yards": 18.0,
    "rushing_tds": 0.1, "is_empty_projection": False, "week": WEEK,
}
_MAHOMES_HIST = [
    {"player_id": "2544", "position": "QB", "team": "KC", "week": w,
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
    {"player_id": "7500", "position": "WR", "team": "BUF", "week": w,
     "season_type": "REG", "receiving_yards": 60.0 + w, "receptions": r}
    for w, r in [(1, 4), (2, 5), (3, 4), (4, 6)]
]
_EMPTY_PROJ = {
    "player_id": "9999", "player_display_name": "Rookie Unknown",
    "position": "WR", "position_group": "WR", "team": "NYJ",
    "receiving_yards": 0.0, "receptions": 0.0, "is_empty_projection": True,
    "week": WEEK,
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


def _line(player_id="2544", market="passing_yards", side="over",
          line=240.5, price=-110, book="manual"):
    body = {"player_id": player_id, "season": SEASON, "week": WEEK,
            "market": market, "side": side, "price": price, "book": book}
    if line is not None:
        body["line"] = line
    return body


def test_props_migration_creates_table():
    conn, tmp = _fresh_db()
    tables = {r["name"] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert "prop_lines" in tables
    ver = conn.execute("PRAGMA user_version").fetchone()[0]
    assert ver >= 5
    idx = [r["sql"] for r in conn.execute(
        "SELECT sql FROM sqlite_master WHERE name LIKE '%prop_lines%'")]
    assert any("UNIQUE" in (s or "") for s in idx)
    conn.close()


def test_post_validation_422s():
    conn, tmp = _fresh_db()
    snap = _snap()
    try:
        _warm()
        cases = [
            _line(market="coin_flip"),                       # unknown market
            _line(price=0),                                  # zero price
            _line(market="anytime_td", side="over"),         # poisson+over
            {**_line(), "line": None},                       # over w/o line
            _line(market="anytime_td", side="yes", line=0.5),  # yes/no w/ line
            {**_line(), "week": 19},                         # Pydantic range
            _line(side="maybe"),                             # unknown side
        ]
        with patch("ffanalytics.db._get_conn", return_value=conn):
            for body in cases:
                resp = client.post("/props/lines", json=body)
                assert resp.status_code == 422, body
            # why strip-then-check: Pydantic min_length=1 passes "   " —
            # caught live by the api-tester sign-off; must 422, not store "".
            resp = client.post("/props/lines", json={**_line(), "player_id": "   "})
            assert resp.status_code == 422
            n = conn.execute("SELECT COUNT(*) AS n FROM prop_lines").fetchone()["n"]
            assert n == 0
    finally:
        _restore(snap)
        conn.close()


def test_post_stores_and_previews_value():
    conn, tmp = _fresh_db()
    snap = _snap()
    try:
        _warm()
        with patch("ffanalytics.db._get_conn", return_value=conn):
            resp = client.post("/props/lines", json=_line())
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["stored"]["market"] == "passing_yards"
        edge = data["edge"]
        # fair 270, sigma floored 30, over 240.5 @ -110 => VALUE.
        assert edge["decision"] == "VALUE"
        assert edge["fair_line"] == 270.0
        assert edge["sigma"] == 30.0
        assert edge["p_model"] > 0.8
        assert edge["calibration_verdict"] in ("edges_on", "tracking", "unknown")
        n = conn.execute("SELECT COUNT(*) AS n FROM prop_lines").fetchone()["n"]
        assert n == 1
        # why 0 here: POST only previews — shadow rows are written when the
        # edge is SERVED via GET (same as start-sit logging on serve).
        assert shadow.count_logged(conn, "prop:passing_yards") == 0
    finally:
        _restore(snap)
        conn.close()


def test_post_upsert_same_key_updates():
    conn, tmp = _fresh_db()
    snap = _snap()
    try:
        _warm()
        with patch("ffanalytics.db._get_conn", return_value=conn):
            r1 = client.post("/props/lines", json=_line(price=-110))
            assert r1.status_code == 200
            r2 = client.post("/props/lines", json=_line(price=-120))
            assert r2.status_code == 200
            rows = conn.execute("SELECT id, price FROM prop_lines").fetchall()
        assert len(rows) == 1
        assert rows[0]["price"] == -120
        # why RETURNING id: last_insert_rowid() goes stale on CONFLICT DO
        # UPDATE — both responses must carry the real row id.
        assert r1.json()["stored"]["id"] == rows[0]["id"] == r2.json()["stored"]["id"]
    finally:
        _restore(snap)
        conn.close()


def test_get_edges_multi_decisions_and_tracking():
    conn, tmp = _fresh_db()
    snap = _snap()
    try:
        _warm()
        with patch("ffanalytics.db._get_conn", return_value=conn):
            client.post("/props/lines", json=_line())  # Mahomes over VALUE
            client.post("/props/lines", json=_line(
                player_id="7500", market="receptions", side="under",
                line=6.5, price=-110))  # fair 5.0 => VALUE under
            client.post("/props/lines", json=_line(
                player_id="9999", market="receiving_yards", side="over",
                line=40.5, price=-110))  # empty => unknown veto
            client.post("/props/lines", json=_line(
                player_id="0000", market="rushing_yards", side="over",
                line=50.5, price=-110))  # unknown player => unknown veto
            resp = client.get(f"/props/edges?season={SEASON}&week={WEEK}")
        assert resp.status_code == 200, resp.text
        edges = {e["player_id"]: e for e in resp.json()["edges"]}
        assert resp.json()["count"] == 4
        assert edges["2544"]["decision"] == "VALUE"
        assert edges["7500"]["decision"] == "VALUE"
        assert edges["9999"]["decision"] == "NO EDGE (unknown)"
        assert edges["0000"]["decision"] == "NO EDGE (unknown)"
        assert edges["0000"]["fair_line"] is None
        # 0 resolved => tracking everywhere (resolved-not-logged semantics).
        assert {e["shadow_status"] for e in edges.values()} == {"tracking"}
        # only VALUE rows logged (2 markets).
        assert shadow.count_logged(conn, "prop:passing_yards") == 1
        assert shadow.count_logged(conn, "prop:receptions") == 1
    finally:
        _restore(snap)
        conn.close()


def test_shadow_trust_flips_after_20_resolved():
    conn, tmp = _fresh_db()
    snap = _snap()
    try:
        _warm()
        for i in range(20):
            rid = shadow.log_recommendation(
                conn, kind="prop:passing_yards", season=SEASON, week=WEEK,
                player_id="2544",
                recommendation={"market": "passing_yards", "side": "over"},
                logged_at_iso="2026-09-09T00:00:00",
            )
            shadow.record_outcome(conn, rid, {"actual_stat": 260.0, "hit": True})
        assert shadow.is_trusted(conn, "prop:passing_yards") is True
        assert shadow.is_trusted(conn, "prop:receptions") is False
        with patch("ffanalytics.db._get_conn", return_value=conn):
            client.post("/props/lines", json=_line())
            resp = client.get(f"/props/edges?season={SEASON}&week={WEEK}")
        edge = resp.json()["edges"][0]
        assert edge["shadow_status"] == "trusted"
    finally:
        _restore(snap)
        conn.close()


def test_prop_resolve_records_hit_and_push():
    conn, tmp = _fresh_db()
    try:
        over_id = shadow.log_recommendation(
            conn, kind="prop:passing_yards", season=SEASON, week=WEEK,
            player_id="2544",
            recommendation={"market": "passing_yards", "side": "over",
                            "book_line": 240.5},
            logged_at_iso="2026-09-09T00:00:00",
        )
        push_id = shadow.log_recommendation(
            conn, kind="prop:passing_yards", season=SEASON, week=WEEK,
            player_id="2544",
            recommendation={"market": "passing_yards", "side": "under",
                            "book_line": 270.0},
            logged_at_iso="2026-09-09T00:00:00",
        )
        yes_id = shadow.log_recommendation(
            conn, kind="prop:anytime_td", season=SEASON, week=WEEK,
            player_id="7500",
            recommendation={"market": "anytime_td", "side": "yes"},
            logged_at_iso="2026-09-09T00:00:00",
        )
        stats = [
            {"player_id": "2544", "week": WEEK, "passing_yards": 270.0,
             "rushing_tds": 0, "receiving_tds": 0},
            {"player_id": "7500", "week": WEEK, "rushing_tds": 0,
             "receiving_tds": 1},
        ]
        n = shadow.evaluate_unresolved_prop_recommendations(conn, stats)
        assert n == 3
        rows = {r["id"]: json.loads(r["actual_outcome"]) for r in conn.execute(
            "SELECT id, actual_outcome FROM shadow_recommendations")}
        assert rows[over_id]["hit"] is True
        assert rows[over_id]["actual_stat"] == 270.0
        assert rows[push_id]["hit"] == "push"
        assert rows[yes_id]["hit"] is True
    finally:
        conn.close()


def test_cold_cache_behaviors():
    conn, tmp = _fresh_db()
    snap = _snap()
    try:
        for k in ("league_settings", "rosters", "player_stats",
                  "model_projections", "injury_status", "season", "week"):
            _CACHE[k] = None
        with patch("ffanalytics.db._get_conn", return_value=conn):
            resp = client.get(f"/props/edges?season={SEASON}&week={WEEK}")
            assert resp.status_code == 503
            post = client.post("/props/lines", json=_line())
            assert post.status_code == 200
            assert post.json()["edge"] is None
            assert "refresh" in (post.json()["note"] or "").lower()
    finally:
        _restore(snap)
        conn.close()


_KICKER_PROJ = {
    "player_id": "8100", "player_display_name": "Test K",
    "position": "K", "position_group": "K", "team": "DAL",
    "passing_yards": 0.0, "is_empty_projection": False, "week": WEEK,
}


def test_week1_and_position_gates_veto():
    # why serving-layer gates: build_prop_fair_lines excludes week<2 and K,
    # but the API reads stored fair lines and never calls the builder —
    # without these vetoes a week-1 or kicker edge surfaces live.
    conn, tmp = _fresh_db()
    snap = _snap()
    try:
        _warm()
        _CACHE["model_projections"] = _CACHE["model_projections"] + [_KICKER_PROJ]
        with patch("ffanalytics.db._get_conn", return_value=conn):
            w1 = client.post("/props/lines", json={**_line(), "week": 1})
            assert w1.status_code == 200
            assert w1.json()["edge"]["decision"] == "NO EDGE (unknown)"
            assert "week 1" in (w1.json()["edge"].get("note") or "").lower()
            kb = client.post("/props/lines", json={**_line(), "player_id": "8100"})
            assert kb.status_code == 200
            assert kb.json()["edge"]["decision"] == "NO EDGE (unknown)"
            assert "out of scope" in (kb.json()["edge"].get("note") or "").lower()
    finally:
        _restore(snap)
        conn.close()


def test_nan_fair_line_quarantines_row_not_board():
    # why per-row quarantine: one NaN projection must veto its own row, not
    # 500 the whole GET /props/edges board (AI-remediation sign-off FAIL).
    conn, tmp = _fresh_db()
    snap = _snap()
    try:
        _warm()
        poisoned = dict(_MAHOMES_PROJ, passing_yards=float("nan"))
        _CACHE["model_projections"] = [poisoned, _WR_PROJ]
        with patch("ffanalytics.db._get_conn", return_value=conn):
            client.post("/props/lines", json=_line())
            client.post("/props/lines", json=_line(
                player_id="7500", market="receptions", side="under",
                line=6.5, price=-110))
            resp = client.get(f"/props/edges?season={SEASON}&week={WEEK}")
        assert resp.status_code == 200, resp.text
        edges = {e["player_id"]: e for e in resp.json()["edges"]}
        assert edges["2544"]["decision"] == "NO EDGE (unknown)"
        assert "non-finite" in (edges["2544"].get("note") or "").lower()
        assert edges["7500"]["decision"] == "VALUE"
    finally:
        _restore(snap)
        conn.close()
