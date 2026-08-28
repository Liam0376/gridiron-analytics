"""End-to-end integration test. Hits real Sleeper API with real league ID.
Skipped if SLEEPER_LEAGUE_ID not set or RUN_INTEGRATION not set."""

import os
import pytest

pytestmark = pytest.mark.skipif(
    not os.getenv("RUN_INTEGRATION"),
    reason="Set RUN_INTEGRATION=1 to run live API tests",
)


def test_sleeper_league_settings():
    from ffanalytics.adapters import sleeper
    league_id = os.environ["SLEEPER_LEAGUE_ID"]
    settings = sleeper.get_league_settings(league_id)
    assert "scoring_settings" in settings
    assert "roster_positions" in settings
    assert settings["scoring_settings"]["rec"] == 1.0, "Expected full PPR (1.0 per reception)"
    assert settings["roster_positions"].count("FLEX") == 2, "Expected 2 FLEX slots"


def test_sleeper_rosters():
    from ffanalytics.adapters import sleeper
    league_id = os.environ["SLEEPER_LEAGUE_ID"]
    rosters = sleeper.get_rosters(league_id)
    assert len(rosters) == 12, "Expected 12 teams"
    assert all("players" in r for r in rosters)


def test_sleeper_matchups_current_week():
    from ffanalytics.adapters import sleeper
    from ffanalytics.refresh import _compute_nfl_week
    league_id = os.environ["SLEEPER_LEAGUE_ID"]
    week = _compute_nfl_week()
    if week < 1:
        pytest.skip("Preseason — no matchups yet")
    matchups = sleeper.get_league_matchups(league_id, week)
    assert isinstance(matchups, list)


def test_full_refresh_pipeline():
    """Run the entire refresh pipeline against live APIs."""
    import tempfile
    from pathlib import Path
    from ffanalytics import db
    from ffanalytics.refresh import run_refresh

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "integration.db"
        conn = db.get_connection(path)
        db.init_schema(conn)
        result = run_refresh(conn, season=2025, ran_at_iso="2026-08-28T12:00:00")
        assert result["sleeper"] is True
        # nflverse may fail if 2025 data not available — that's OK
        conn.close()
