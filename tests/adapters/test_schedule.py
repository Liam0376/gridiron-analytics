from unittest.mock import Mock


class _FakePolarsFrame:
    def __init__(self, rows):
        self._rows = rows
    def to_dicts(self):
        return self._rows


def test_get_schedule_filters_by_week():
    from ffanalytics.adapters import schedule
    fake_nfl = Mock()
    fake_nfl.load_schedules.return_value = _FakePolarsFrame([
        {"game_id": "1", "season": 2026, "week": 1, "home_team": "KC", "away_team": "BAL", "home_score": 27, "away_score": 24},
        {"game_id": "2", "season": 2026, "week": 2, "home_team": "SF", "away_team": "DAL", "home_score": 31, "away_score": 17},
    ])
    result = schedule.get_schedule(2026, week=1, nfl_module=fake_nfl)
    assert len(result) == 1
    assert result[0]["home_team"] == "KC"


def test_get_schedule_returns_all_without_week_filter():
    from ffanalytics.adapters import schedule
    fake_nfl = Mock()
    fake_nfl.load_schedules.return_value = _FakePolarsFrame([
        {"game_id": "1", "season": 2026, "week": 1, "home_team": "KC", "away_team": "BAL"},
        {"game_id": "2", "season": 2026, "week": 2, "home_team": "SF", "away_team": "DAL"},
    ])
    result = schedule.get_schedule(2026, nfl_module=fake_nfl)
    assert len(result) == 2


def test_get_nfl_team_matchups():
    from ffanalytics.adapters.schedule import get_nfl_team_matchups
    games = [
        {"week": 1, "home_team": "KC", "away_team": "BAL"},
        {"week": 1, "home_team": "SF", "away_team": "DAL"},
    ]
    matchups = get_nfl_team_matchups(games, week=1)
    assert matchups["KC"] == "BAL"
    assert matchups["BAL"] == "KC"
    assert matchups["SF"] == "DAL"
    assert matchups["DAL"] == "SF"
