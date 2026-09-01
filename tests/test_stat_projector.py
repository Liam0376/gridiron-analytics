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

def test_project_player_stats_small_sample_prior_blend():
    # Less than 3 games played: should blend with prior season if available
    history = [
        {"passing_yards": 300, "passing_tds": 3, "passing_interceptions": 0, "rushing_yards": 15, "rushing_tds": 0},
    ]
    prior = [
        {"season_type": "REG", "passing_yards": 200, "passing_tds": 1, "passing_interceptions": 1, "rushing_yards": 10, "rushing_tds": 0},
    ]
    proj = project_player_stats(history, "QB", prior_season_stats=prior)
    assert proj["passing_yards"] > 0
    # Because history (300 yds) is blended with prior (200 yds), result should be between 200 and 300
    assert 200 < proj["passing_yards"] < 300


def test_project_player_stats_empty_history():
    prior = [
        {"season_type": "REG", "rushing_yards": 80, "rushing_tds": 1, "receptions": 3, "receiving_yards": 20},
    ]
    proj = project_player_stats([], "RB", prior_season_stats=prior)
    assert proj["rushing_yards"] > 0
    assert proj["rushing_yards"] == 80.0


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


def test_cross_season_week_filter_bypass():
    # Audit C2: 2025 stats (weeks 1-18) vs 2026 schedule week 1-5 should use full history, not truncated
    season_stats = [
        {"player_id": "p2", "player_display_name": "Test RB", "position": "RB", "team": "DET", "season": 2025, "week": i+1, "season_type": "REG", "rushing_yards": 80, "rushing_tds": 1}
        for i in range(17)
    ]
    # Provide schedule for target_week=5 to avoid fallback implied 21.0 (neutral 22.2)
    schedule = [
        {"game_type": "REG", "week": 5, "season": 2026, "home_team": "DET", "away_team": "CHI", "total_line": 44.4, "spread_line": 0, "roof": "dome", "temp": 72, "wind": 0}
    ]
    scoring = {"rush_yd": 0.1, "rush_td": 6}
    projs = build_weekly_projections(season_stats, schedule, target_week=5, scoring_settings=scoring)
    assert len(projs) == 1
    # Full 17-game history should be used, not just weeks<5 (4 games)
    # So projected rushing yards should be ~80 (dome neutral, no Vegas scale)
    assert projs[0]["rushing_yards"] == 80.0


def test_neutral_points_avoids_vegas_extrapolation():
    season_stats = [
        {"player_id": "p3", "player_display_name": "Test WR", "position": "WR", "team": "KC", "week": 1, "season_type": "REG", "receiving_yards": 80, "receptions": 5},
    ] * 5
    schedule_high = [
        {"game_type": "REG", "week": 10, "home_team": "KC", "away_team": "LV", "total_line": 55, "spread_line": 10, "roof": "dome", "temp": 72, "wind": 0}
    ]
    scoring = {"rec": 1, "rec_yd": 0.1}
    projs = build_weekly_projections(season_stats, schedule_high, target_week=10, scoring_settings=scoring)
    p = projs[0]
    assert "_neutral_points" in p
    assert "_neutral_stats" in p
    # Neutral at 22.2 should be lower than high-total Vegas game (32.5 implied)
    assert p["_neutral_points"] < p["projected_points"]


def test_usage_trend_prior_only():
    from ffanalytics.stat_projector import _usage_trend_adjustment
    # 3 old 60, 3 recent 120 → trend vs prior only = 1.0 → +15% → 60*1.15=69? Wait base 90 → 103.5
    # With dilution old impl gave +5% (94.5). New should be higher.
    history = [{"rushing_yards": 60} for _ in range(3)] + [{"rushing_yards": 120} for _ in range(3)]
    base = 90
    adjusted = _usage_trend_adjustment(base, history, "rushing_yards")
    # Prior-only avg 60, recent 120 → trend 1.0 → 90*1.15=103.5
    assert adjusted == pytest.approx(103.5)


def test_vegas_safe_float_string():
    from ffanalytics.stat_projector import build_game_context
    schedule = [{"game_type": "REG", "week": 1, "home_team": "KC", "away_team": "LV", "total_line": "48.0", "spread_line": "-7.0", "roof": "outdoors", "temp": "65", "wind": "5"}]
    ctx = build_game_context(schedule)
    assert ctx[("KC", 1)]["implied_total"] == 20.5
    assert ctx[("LV", 1)]["implied_total"] == 27.5
