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

def test_get_player_ids_converts_to_plain_dicts():
    # why (user-caught live bug, 2026-09-10): the sleeper_id<->gsis_id
    # name+pos xwalk fallback only matched players with a stat line THIS
    # week — a real starter who didn't play (bye/injury/backup) couldn't
    # resolve even though their gsis_id is a stable identity. load_players()
    # is nflverse's full player-identity master list, not week-filtered.
    from ffanalytics.adapters import nflverse
    fake_nfl = Mock()
    fake_nfl.load_players.return_value = _FakePolarsFrame(
        [{"gsis_id": "00-0037834", "display_name": "Brock Purdy", "position": "QB"}]
    )
    result = nflverse.get_player_ids(nfl_module=fake_nfl)
    assert result == [{"gsis_id": "00-0037834", "display_name": "Brock Purdy", "position": "QB"}]
    fake_nfl.load_players.assert_called_once_with()
def test_get_ecr_weekly_converts_to_plain_dicts():
    from ffanalytics.adapters import nflverse
    fake_nfl = Mock()
    fake_nfl.load_ff_rankings.return_value = _FakePolarsFrame(
        [{"player_name": "Josh Allen", "pos": "QB", "team": "BUF",
          "ecr": 1.0, "pos_rank": 1, "fantasypros_id": "12345"}]
    )
    result = nflverse.get_ecr_weekly(nfl_module=fake_nfl)
    assert result[0]["ecr"] == 1.0
    assert isinstance(result[0], dict)
    fake_nfl.load_ff_rankings.assert_called_once_with(type="week")

def test_get_ff_playerids_converts_to_plain_dicts():
    from ffanalytics.adapters import nflverse
    fake_nfl = Mock()
    fake_nfl.load_ff_playerids.return_value = _FakePolarsFrame(
        [{"fantasypros_id": "12345", "gsis_id": "00-0034857",
          "sleeper_id": "4046"}]
    )
    result = nflverse.get_ff_playerids(nfl_module=fake_nfl)
    assert result == [{"fantasypros_id": "12345", "gsis_id": "00-0034857",
                       "sleeper_id": "4046"}]
    fake_nfl.load_ff_playerids.assert_called_once_with()
