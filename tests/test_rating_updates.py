import tempfile
from pathlib import Path
from unittest.mock import Mock

from ffanalytics import db
from ffanalytics.rating_updates import update_team_ratings_from_results


class _FakePolarsFrame:
    def __init__(self, rows):
        self._rows = rows
    def to_dicts(self):
        return self._rows


def _fresh_conn():
    tmp = tempfile.TemporaryDirectory()
    path = Path(tmp.name) / "test.db"
    conn = db.get_connection(path)
    db.init_schema(conn)
    return conn, tmp


def test_update_ratings_from_game_results():
    conn, tmp = _fresh_conn()
    fake_nfl = Mock()
    fake_nfl.load_schedules.return_value = _FakePolarsFrame([
        {"game_id": "1", "season": 2026, "week": 1, "home_team": "KC", "away_team": "BAL",
         "home_score": 27, "away_score": 24, "game_type": "REG"},
    ])
    ratings = update_team_ratings_from_results(conn, 2026, 1, nfl_module=fake_nfl)
    assert "KC" in ratings
    assert "BAL" in ratings
    # Winner rating should increase
    assert ratings["KC"]["overall"].value > 1500.0
    # Loser rating should decrease
    assert ratings["BAL"]["overall"].value < 1500.0
    # Verify persisted to DB
    row = conn.execute(
        "SELECT rating FROM team_ratings WHERE team = 'KC' AND position_group = 'overall' AND season = 2026"
    ).fetchone()
    assert row is not None
    assert row["rating"] > 1500.0
    conn.close()


def test_update_ratings_skips_incomplete_games():
    conn, tmp = _fresh_conn()
    fake_nfl = Mock()
    fake_nfl.load_schedules.return_value = _FakePolarsFrame([
        {"game_id": "1", "season": 2026, "week": 1, "home_team": "KC", "away_team": "BAL",
         "home_score": None, "away_score": None, "game_type": "REG"},
    ])
    ratings = update_team_ratings_from_results(conn, 2026, 1, nfl_module=fake_nfl)
    # No ratings should be created for incomplete games
    rows = conn.execute("SELECT COUNT(*) as n FROM team_ratings").fetchone()
    assert rows["n"] == 0
    conn.close()
