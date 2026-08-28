import json
from pathlib import Path
from unittest.mock import Mock

FIXTURES = Path(__file__).parent.parent / "fixtures"

def _mock_session(payload):
    session = Mock()
    response = Mock()
    response.json.return_value = payload
    response.raise_for_status.return_value = None
    session.get.return_value = response
    return session

def test_get_league_settings_returns_scoring_and_roster():
    from ffanalytics.adapters import sleeper
    payload = json.loads((FIXTURES / "sleeper_league.json").read_text())
    session = _mock_session(payload)
    result = sleeper.get_league_settings("123", session=session)
    assert result["scoring_settings"]["rec"] == 1.0
    assert "FLEX" in result["roster_positions"]
    session.get.assert_called_once_with(
        "https://api.sleeper.app/v1/league/123", timeout=10
    )

def test_get_rosters_returns_list():
    from ffanalytics.adapters import sleeper
    payload = json.loads((FIXTURES / "sleeper_rosters.json").read_text())
    session = _mock_session(payload)
    result = sleeper.get_rosters("123", session=session)
    assert result[0]["roster_id"] == 1

def test_get_injury_statuses_filters_to_nonnull():
    from ffanalytics.adapters import sleeper
    payload = {
        "4046": {"player_id": "4046", "injury_status": "Questionable"},
        "5849": {"player_id": "5849", "injury_status": None},
    }
    session = _mock_session(payload)
    result = sleeper.get_injury_statuses(session=session)
    assert result == {"4046": "Questionable", "5849": None}