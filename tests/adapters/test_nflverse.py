from unittest.mock import Mock

class _FakePolarsFrame:
    """Minimal stand-in for a polars.DataFrame — only needs to_dicts()."""
    def __init__(self, rows):
        self._rows = rows
    def to_dicts(self):
        return self._rows

def test_get_weekly_player_stats_converts_to_plain_dicts():
    from ffanalytics.adapters import nflverse
    fake_nfl = Mock()
    fake_nfl.load_player_stats.return_value = _FakePolarsFrame(
        [{"player_id": "4046", "target_share": 0.28}]
    )
    result = nflverse.get_weekly_player_stats(2026, nfl_module=fake_nfl)
    assert result == [{"player_id": "4046", "target_share": 0.28}]
    assert isinstance(result, list)
    assert isinstance(result[0], dict)
    fake_nfl.load_player_stats.assert_called_once_with(seasons=[2026])

def test_get_injury_history_converts_to_plain_dicts():
    from ffanalytics.adapters import nflverse
    fake_nfl = Mock()
    fake_nfl.load_injuries.return_value = _FakePolarsFrame(
        [{"player_id": "4046", "report_status": "Questionable"}]
    )
    result = nflverse.get_injury_history(2026, nfl_module=fake_nfl)
    assert result == [{"player_id": "4046", "report_status": "Questionable"}]