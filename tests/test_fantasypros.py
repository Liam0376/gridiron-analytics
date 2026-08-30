import os
from unittest.mock import MagicMock
from ffanalytics.adapters.fantasypros import (
    get_fantasypros_players,
    get_fantasypros_news,
    get_fantasypros_injuries,
)


def test_fantasypros_no_key_returns_empty():
    assert get_fantasypros_players(api_key="") == []
    assert get_fantasypros_news(api_key="") == []
    assert get_fantasypros_injuries(api_key="") == []


def test_fantasypros_mocked_calls():
    mock_session = MagicMock()
    
    # Mock players response
    mock_resp_players = MagicMock()
    mock_resp_players.json.return_value = {
        "players": [
            {"player_id": 101, "player_name": "Test QB", "rank_ecr": 1, "rank_adp": 2}
        ]
    }
    mock_session.get.return_value = mock_resp_players

    players = get_fantasypros_players(api_key="fake_key", session=mock_session)
    assert len(players) == 1
    assert players[0]["player_name"] == "Test QB"
    assert players[0]["rank_ecr"] == 1

    # Mock news response
    mock_resp_news = MagicMock()
    mock_resp_news.json.return_value = {
        "items": [
            {"id": 1, "title": "Test Player on IR", "team_id": "KC"}
        ]
    }
    mock_session.get.return_value = mock_resp_news

    news = get_fantasypros_news(limit=10, api_key="fake_key", session=mock_session)
    assert len(news) == 1
    assert news[0]["title"] == "Test Player on IR"


def test_fantasypros_live_key_if_present():
    key = os.environ.get("FANTASYPROS_API_KEY")
    if not key and os.path.exists(".env"):
        try:
            with open(".env") as f:
                for line in f:
                    if line.startswith("FANTASYPROS_API_KEY="):
                        key = line.split("=", 1)[1].strip()
        except Exception:
            pass

    if key:
        news = get_fantasypros_news(limit=5, api_key=key)
        assert isinstance(news, list)
        if news:
            assert "title" in news[0]
