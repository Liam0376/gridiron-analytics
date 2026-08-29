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
    fake_nfl.load_player_stats.return_value = _FakePolarsFrame([
        {"week": 1, "position_group": "QB", "opponent_team": "BAL", "recent_team": "KC",
         "passing_yards": 280, "passing_tds": 3, "receptions": 0, "rushing_yards": 15,
         "rushing_tds": 0, "receiving_yards": 0, "receiving_tds": 0,
         "passing_interceptions": 0, "fumbles_lost": 0},
        {"week": 1, "position_group": "WR", "opponent_team": "BAL", "recent_team": "KC",
         "passing_yards": 0, "passing_tds": 0, "receptions": 6, "rushing_yards": 0,
         "rushing_tds": 0, "receiving_yards": 95, "receiving_tds": 1,
         "passing_interceptions": 0, "fumbles_lost": 0},
        {"week": 1, "position_group": "QB", "opponent_team": "KC", "recent_team": "BAL",
         "passing_yards": 310, "passing_tds": 2, "receptions": 0, "rushing_yards": 40,
         "rushing_tds": 1, "receiving_yards": 0, "receiving_tds": 0,
         "passing_interceptions": 1, "fumbles_lost": 0},
    ])
    ratings = update_team_ratings_from_results(conn, 2026, 1, nfl_module=fake_nfl)
    assert "KC" in ratings
    assert "BAL" in ratings
    assert ratings["KC"]["overall"].value > 1500.0
    assert ratings["BAL"]["overall"].value < 1500.0
    # Positional ratings should now exist
    assert "vs_QB" in ratings["BAL"]
    assert "vs_WR" in ratings["BAL"]
    assert "vs_QB" in ratings["KC"]
    # Verify persisted to DB
    row = conn.execute(
        "SELECT rating FROM team_ratings WHERE team = 'KC' AND position_group = 'overall' AND season = 2026"
    ).fetchone()
    assert row is not None
    assert row["rating"] > 1500.0
    pos_row = conn.execute(
        "SELECT rating FROM team_ratings WHERE team = 'BAL' AND position_group = 'vs_QB' AND season = 2026"
    ).fetchone()
    assert pos_row is not None
    conn.close()


def test_update_ratings_skips_incomplete_games():
    conn, tmp = _fresh_conn()
    fake_nfl = Mock()
    fake_nfl.load_schedules.return_value = _FakePolarsFrame([
        {"game_id": "1", "season": 2026, "week": 1, "home_team": "KC", "away_team": "BAL",
         "home_score": None, "away_score": None, "game_type": "REG"},
    ])
    fake_nfl.load_player_stats.return_value = _FakePolarsFrame([])
    ratings = update_team_ratings_from_results(conn, 2026, 1, nfl_module=fake_nfl)
    # No ratings should be created for incomplete games
    rows = conn.execute("SELECT COUNT(*) as n FROM team_ratings").fetchone()
    assert rows["n"] == 0
    conn.close()
