"""Game predictions API tests: shape, shadow log-once idempotency, resolution.

DB isolation: patch ffanalytics.db._get_conn to a tmp-DB conn (init_schema'd).
Cache isolation: snapshot/restore _CACHE (mirrors tests/test_props_api.py).
"""
import tempfile
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from ffanalytics import db, shadow
from ffanalytics.api import _CACHE, app

client = TestClient(app)

SEASON, WEEK = 2026, 1

_SCHEDULE = [
    {
        "game_id": "2026_01_SF_LA", "season": SEASON, "week": WEEK,
        "game_type": "REG", "home_team": "LA", "away_team": "SF",
        "home_moneyline": -198, "away_moneyline": 164,
        "spread_line": 3.5, "total_line": 48.5,
        "home_score": None, "away_score": None,
    },
    {
        "game_id": "2026_01_BAL_KC", "season": SEASON, "week": WEEK,
        "game_type": "REG", "home_team": "KC", "away_team": "BAL",
        "home_moneyline": -148, "away_moneyline": 124,
        "spread_line": 3.0, "total_line": 46.0,
        "home_score": None, "away_score": None,
    },
]


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


def _warm(schedule=None):
    _CACHE.update({
        "league_settings": {"scoring_settings": {}, "roster_positions": []},
        "rosters": [],
        "schedule": schedule if schedule is not None else _SCHEDULE,
        "season": SEASON,
        "week": WEEK,
        "last_updated": "2026-09-10T00:00:00",
    })


def test_games_predictions_503_without_schedule():
    conn, tmp = _fresh_db()
    snap = _snap()
    try:
        _CACHE.update({"schedule": None})
        with patch("ffanalytics.db._get_conn", return_value=conn):
            resp = client.get("/games/predictions")
        assert resp.status_code == 503
    finally:
        _restore(snap)
        conn.close()


def test_games_predictions_shape():
    conn, tmp = _fresh_db()
    snap = _snap()
    try:
        _warm()
        with patch("ffanalytics.db._get_conn", return_value=conn):
            resp = client.get("/games/predictions", params={"season": SEASON, "week": WEEK})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["count"] == 2
        assert body["season"] == SEASON
        assert body["week"] == WEEK
        game = next(g for g in body["games"] if g["game_id"] == "2026_01_BAL_KC")
        assert game["home_team"] == "KC"
        assert game["source"] == "market_consensus"
        assert round(game["home_win_prob"] + game["away_win_prob"], 6) == 1.0
        assert game["predicted_home_score"] == 24.5
        assert game["final"] is False
    finally:
        _restore(snap)
        conn.close()


def test_games_predictions_shadow_logs_once():
    conn, tmp = _fresh_db()
    snap = _snap()
    try:
        _warm()
        with patch("ffanalytics.db._get_conn", return_value=conn):
            client.get("/games/predictions", params={"season": SEASON, "week": WEEK})
            client.get("/games/predictions", params={"season": SEASON, "week": WEEK})
        n = shadow.count_logged(conn, f"game:{SEASON}:{WEEK}")
        assert n == 2  # 2 games, logged once each despite 2 polls
    finally:
        _restore(snap)
        conn.close()


def test_evaluate_unresolved_game_predictions_resolves_final_games():
    conn, tmp = _fresh_db()
    snap = _snap()
    try:
        _warm()
        with patch("ffanalytics.db._get_conn", return_value=conn):
            client.get("/games/predictions", params={"season": SEASON, "week": WEEK})

        final_schedule = [
            {**_SCHEDULE[1], "home_score": 27, "away_score": 20},  # KC favored, KC wins -> correct
        ]
        resolved = shadow.evaluate_unresolved_game_predictions(conn, final_schedule)
        assert resolved == 1
        row = conn.execute(
            "SELECT actual_outcome FROM shadow_recommendations WHERE player_id = ?",
            ("2026_01_BAL_KC",),
        ).fetchone()
        import json
        outcome = json.loads(row["actual_outcome"])
        assert outcome["actual_home_score"] == 27
        assert outcome["actual_away_score"] == 20
        assert outcome["win_call_correct"] is True
    finally:
        _restore(snap)
        conn.close()


def test_evaluate_unresolved_game_predictions_leaves_unplayed_pending():
    conn, tmp = _fresh_db()
    snap = _snap()
    try:
        _warm()
        with patch("ffanalytics.db._get_conn", return_value=conn):
            client.get("/games/predictions", params={"season": SEASON, "week": WEEK})

        resolved = shadow.evaluate_unresolved_game_predictions(conn, _SCHEDULE)  # still unplayed
        assert resolved == 0
    finally:
        _restore(snap)
        conn.close()
