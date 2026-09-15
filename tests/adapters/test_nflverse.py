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

def test_get_weekly_rosters_converts_to_plain_dicts():
    from ffanalytics.adapters import nflverse
    fake_nfl = Mock()
    fake_nfl.load_rosters_weekly.return_value = _FakePolarsFrame(
        [{"gsis_id": "00-0036212", "team": "ATL", "week": 1, "status": "INA",
          "sleeper_id": "4046"}]
    )
    result = nflverse.get_weekly_rosters(2026, nfl_module=fake_nfl)
    assert result == [{"gsis_id": "00-0036212", "team": "ATL", "week": 1,
                       "status": "INA", "sleeper_id": "4046"}]
    assert isinstance(result[0], dict)
    fake_nfl.load_rosters_weekly.assert_called_once_with(seasons=[2026])

def test_get_depth_charts_returns_latest_snapshot_only():
    # why: nflverse keeps every scrape (dt); refresh-time consumers want the
    # current chart, not history. Backtests pin older snapshots via cache.
    from ffanalytics.adapters import nflverse
    fake_nfl = Mock()
    fake_nfl.load_depth_charts.return_value = _FakePolarsFrame([
        {"gsis_id": "AA", "team": "ATL", "pos_abb": "QB", "pos_rank": 1,
         "dt": "2026-09-01T00:00:00Z"},
        {"gsis_id": "BB", "team": "ATL", "pos_abb": "QB", "pos_rank": 1,
         "dt": "2026-09-14T13:53:31Z"},
        {"gsis_id": "CC", "team": "ATL", "pos_abb": "QB", "pos_rank": 2,
         "dt": "2026-09-14T13:53:31Z"},
    ])
    result = nflverse.get_depth_charts(2026, nfl_module=fake_nfl)
    assert [r["gsis_id"] for r in result] == ["BB", "CC"]
    assert all(isinstance(r, dict) for r in result)
    fake_nfl.load_depth_charts.assert_called_once_with(seasons=[2026])

def test_get_depth_charts_empty_in_empty_out():
    from ffanalytics.adapters import nflverse
    fake_nfl = Mock()
    fake_nfl.load_depth_charts.return_value = _FakePolarsFrame([])
    assert nflverse.get_depth_charts(2026, nfl_module=fake_nfl) == []

def test_get_opportunity_converts_to_plain_dicts():
    from ffanalytics.adapters import nflverse
    fake_nfl = Mock()
    fake_nfl.load_ff_opportunity.return_value = _FakePolarsFrame(
        [{"player_id": "00-0035676", "rec_attempt": 9.0, "rec_attempt_team": 37.0}]
    )
    result = nflverse.get_opportunity(2026, nfl_module=fake_nfl)
    assert result == [{"player_id": "00-0035676", "rec_attempt": 9.0,
                       "rec_attempt_team": 37.0}]
    assert isinstance(result[0], dict)
    fake_nfl.load_ff_opportunity.assert_called_once_with(seasons=[2026])

def test_get_ngs_receiving_converts_to_plain_dicts():
    from ffanalytics.adapters import nflverse
    fake_nfl = Mock()
    fake_nfl.load_nextgen_stats.return_value = _FakePolarsFrame(
        [{"player_display_name": "Ja'Marr Chase",
          "percent_share_of_intended_air_yards": 0.31}]
    )
    result = nflverse.get_ngs_receiving(2026, nfl_module=fake_nfl)
    assert result[0]["percent_share_of_intended_air_yards"] == 0.31
    fake_nfl.load_nextgen_stats.assert_called_once_with(
        seasons=[2026], stat_type="receiving")

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
