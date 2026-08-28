from ffanalytics.projection import (
    calculate_target_share_feature,
    calculate_snap_pct_feature,
    calculate_opponent_positional_rating_feature,
    calculate_projection,
    calculate_projection,
    calculate_weekly_projections
)
from ffanalytics.rating import Rating


def test_calculate_target_share_feature():
    # Test normal case
    stats = {"targets": 10, "receptions": 5}
    assert calculate_target_share_feature(stats) == 0.5

    # Test edge cases
    stats = {"targets": 0, "receptions": 0}
    assert calculate_target_share_feature(stats) == 0.0

    stats = {"targets": 5, "receptions": 5}
    assert calculate_target_share_feature(stats) == 1.0


def test_calculate_snap_pct_feature():
    # Test normal case
    stats = {"snaps": 50}
    result = calculate_snap_pct_feature(stats)
    assert 0.0 <= result <= 1.0
    assert result == 0.5  # 50/100

    # Test edge cases
    stats = {"snaps": 0}
    assert calculate_snap_pct_feature(stats) == 0.0

    stats = {"snaps": 200}
    assert calculate_snap_pct_feature(stats) == 1.0  # Capped at 1.0


def test_calculate_opponent_positional_rating_feature():
    team_ratings = {
        "DAL": {
            "overall": Rating(1600.0, 50.0),
            "vs_rb": Rating(1550.0, 40.0),
            "vs_wr_slot": Rating(1450.0, 40.0)
        }
    }

    # Test position-specific rating
    rating = calculate_opponent_positional_rating_feature(
        team_ratings, "DAL", "rb"
    )
    assert rating == 1550.0

    # Test fallback to overall
    rating = calculate_opponent_positional_rating_feature(
        team_ratings, "DAL", "te"  # No specific TE rating
    )
    assert rating == 1600.0

    # Test unknown team
    rating = calculate_opponent_positional_rating_feature(
        team_ratings, "UNK", "rb"
    )
    assert rating == 1500.0  # Default


def test_calculate_projection():
    player_stats = {
        "pass_td": 2,
        "pass_yd": 200,
        "pass_int": 0,
        "rush_td": 1,
        "rush_yd": 50,
        "rec_td": 1,
        "rec_yd": 60,
        "fum_lost": 0,
        "targets": 8,
        "receptions": 5,
        "snaps": 60
    }

    team_ratings = {
        "opponent_team": {
            "overall": Rating(1500.0, 50.0),
            "vs_rb": Rating(1550.0, 40.0)
        }
    }

    historical_residuals = [1.0, -2.0, 3.0, -1.0, 2.0]

    result = calculate_projection(
        player_stats=player_stats,
        team_ratings={"opponent_team": team_ratings["opponent_team"]},
        historical_residuals=historical_residuals
    )

    # Check that we get reasonable values
    assert "point_estimate" in result
    assert "lower_bound" in result
    assert "upper_bound" in result
    assert "width" in result
    assert result["lower_bound"] <= result["point_estimate"] <= result["upper_bound"]
    assert result["width"] > 0


def test_calculate_weekly_projections():
    weekly_stats = [
        {
            "player_id": "1",
            "team": "DAL",
            "position_group": "rb",
            "pass_td": 1,
            "pass_yd": 100,
            "rush_td": 2,
            "rush_yd": 80,
            "rec_td": 0,
            "rec_yd": 0,
            "targets": 0,
            "receptions": 0,
            "snaps": 50
        }
    ]

    team_ratings = {
        "PHI": {  # Opponent
            "overall": Rating(1500.0, 50.0),
            "vs_rb": Rating(1550.0, 40.0)
        }
    }

    historical_data = [
        {
            "week": 1,
            "players": [
                {
                    "player_id": "1",
                    "actual_points": 25.0,
                    "projected_points": 20.0
                }
            ]
        }
    ]

    projections = calculate_weekly_projections(
        weekly_stats=weekly_stats,
        team_ratings=team_ratings,
        historical_data=historical_data
    )

    assert len(projections) == 1
    player = projections[0]
    assert "projected_points" in player
    assert "projection_lower" in player
    assert "projection_upper" in player
    assert "projection_width" in player