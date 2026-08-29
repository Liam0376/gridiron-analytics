import pytest
from ffanalytics.stat_projector import (
    project_player_stats,
    build_weekly_projections,
    weighted_recent_avg,
)

def test_weighted_recent_avg():
    vals = [10.0, 10.0, 10.0, 10.0, 10.0, 20.0, 20.0]
    avg = weighted_recent_avg(vals, recent_n=2, recent_weight=2.0)
    # 5 old @ 10 = 50. 2 recent @ 20*2 = 80. total = 130 / (5 + 4) = 130 / 9 = 14.44
    assert round(avg, 2) == 14.44

def test_project_player_stats_qb():
    history = [
        {"passing_yards": 250, "passing_tds": 2, "passing_interceptions": 1, "rushing_yards": 20, "rushing_tds": 0},
        {"passing_yards": 300, "passing_tds": 3, "passing_interceptions": 0, "rushing_yards": 15, "rushing_tds": 0},
        {"passing_yards": 200, "passing_tds": 1, "passing_interceptions": 2, "rushing_yards": 30, "rushing_tds": 1},
    ]
    proj = project_player_stats(history, "QB")
    assert "passing_yards" in proj
    assert "passing_tds" in proj
    assert proj["passing_yards"] > 0
    assert proj["passing_tds"] > 0

def test_build_weekly_projections():
    season_stats = [
        {"player_id": "p1", "player_display_name": "Test QB", "position": "QB", "team": "KC", "week": 1, "season_type": "REG", "passing_yards": 250, "passing_tds": 2},
        {"player_id": "p1", "player_display_name": "Test QB", "position": "QB", "team": "KC", "week": 2, "season_type": "REG", "passing_yards": 300, "passing_tds": 3},
        {"player_id": "p1", "player_display_name": "Test QB", "position": "QB", "team": "KC", "week": 3, "season_type": "REG", "passing_yards": 200, "passing_tds": 1},
    ]
    schedule = [
        {"game_type": "REG", "week": 4, "home_team": "KC", "away_team": "LV", "total_line": 48.0, "spread_line": -7.0, "roof": "outdoors", "temp": 65, "wind": 5}
    ]
    scoring = {"pass_yd": 0.04, "pass_td": 4, "pass_int": -2}

    projs = build_weekly_projections(season_stats, schedule, target_week=4, scoring_settings=scoring)
    assert len(projs) == 1
    p = projs[0]
    assert p["player_id"] == "p1"
    assert p["position"] == "QB"
    assert p["team"] == "KC"
    assert p["opponent_team"] == "LV"
    assert "projection_lower" in p
    assert "projection_upper" in p
    assert p["projection_lower"] <= p["projected_points"] <= p["projection_upper"]
