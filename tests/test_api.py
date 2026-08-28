import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient
from ffanalytics.api import app
from ffanalytics import db

client = TestClient(app)

def test_health_endpoint():
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}

def test_refresh_endpoint_accepted():
    # Set up a temporary database for the test
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "test.db"

        # Patch the config to use the test database
        with patch('ffanalytics.config.DB_PATH', db_path):
            # Initialize the database schema
            conn = db.get_connection(db_path)
            db.init_schema(conn)
            conn.close()

            # Mock the network calls to avoid actual API calls
            with patch('ffanalytics.adapters.sleeper.get_league_settings', return_value={"scoring_settings": {}, "roster_positions": []}):
                with patch('ffanalytics.adapters.sleeper.get_rosters', return_value=[]):
                    with patch('ffanalytics.adapters.sleeper.get_injury_statuses', return_value={}):
                        with patch('ffanalytics.adapters.nflverse.get_weekly_player_stats', return_value=[]):
                            with patch('ffanalytics.adapters.news.get_trending_adds', return_value=[]):
                                with patch('ffanalytics.adapters.news.get_injury_with_practice', return_value=[]):
                                    resp = client.post("/refresh")
                                    assert resp.status_code == 200
                                    assert resp.json()["status"] == "accepted"