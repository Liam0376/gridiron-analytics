from ffanalytics.decision import (
    calculate_roster_value,
    get_start_sit_recommendations,
    get_waiver_priority,
    evaluate_trade,
    get_decision_layer_recommendations
)


def test_calculate_roster_value():
    players = [
        {"projected_points": 20.0},
        {"projected_points": 15.0},
        {"projected_points": 10.0}
    ]
    scoring_settings = {"pass_td": 4, "pass_yd": 0.04}  # Not used in simple version
    roster_positions = ["QB", "RB", "WR"]

    value = calculate_roster_value(players, scoring_settings, roster_positions)
    assert value == 45.0  # 20 + 15 + 10

    # Test with fewer players than positions
    players = [
        {"projected_points": 20.0},
        {"projected_points": 15.0}
    ]
    value = calculate_roster_value(players, scoring_settings, roster_positions)
    assert value == 35.0  # Only 2 players available


def test_get_start_sit_recommendations():
    roster_players = [
        {"player_id": "1", "player_name": "QB1", "position_group": "QB", "projected_points": 20.0},
        {"player_id": "2", "player_name": "RB1", "position_group": "RB", "projected_points": 15.0}
    ]
    bench_players = [
        {"player_id": "3", "player_name": "RB2", "position_group": "RB", "projected_points": 18.0},
        {"player_id": "4", "player_name": "WR1", "position_group": "WR", "projected_points": 12.0}
    ]
    scoring_settings = {"pass_td": 4, "pass_yd": 0.04}
    roster_positions = ["QB", "RB", "RB", "WR"]  # Standard lineup

    recommendations = get_start_sit_recommendations(
        roster_players, bench_players, scoring_settings, roster_positions
    )

    # Should have 4 recommendations (roster size)
    assert len(recommendations) == 4

    # Check that recommendations are sorted by projected points
    points = [r["projected_points"] for r in recommendations]
    assert points == sorted(points, reverse=True)

    # Check that we have START and SIT recommendations
    decisions = [r["recommendation"] for r in recommendations]
    assert "START" in decisions
    assert "SIT" in decisions


def test_get_waiver_priority():
    roster_players = [
        {"player_id": "1", "player_name": "RB1", "position_group": "RB", "projected_points": 10.0},
        {"player_id": "2", "player_name": "WR1", "position_group": "WR", "projected_points": 15.0}
    ]
    free_agents = [
        {"player_id": "3", "player_name": "RB2", "position_group": "RB", "projected_points": 20.0},  # Better RB
        {"player_id": "4", "player_name": "WR2", "position_group": "WR", "projected_points": 12.0}   # Worse WR
    ]
    scoring_settings = {"pass_td": 4, "pass_yd": 0.04}
    roster_positions = ["QB", "RB", "RB", "WR"]

    waiver = get_waiver_priority(
        roster_players, free_agents, scoring_settings, roster_positions
    )

    # Should only recommend the better RB (player_id: 3) since it improves the roster
    assert len(waiver) == 1
    assert waiver[0]["player_id"] == "3"
    assert waiver[0]["improvement_over_roster"] > 0
    assert waiver[0]["waiver_priority"] == 1


def test_evaluate_trade():
    team_a_players = [
        {"projected_points": 20.0},
        {"projected_points": 15.0}
    ]
    team_b_players = [
        {"projected_points": 18.0},
        {"projected_points": 12.0}
    ]
    scoring_settings = {"pass_td": 4, "pass_yd": 0.04}
    roster_positions = ["QB", "RB", "WR", "TE"]

    result = evaluate_trade(
        team_a_players, team_b_players, scoring_settings, roster_positions
    )

    # Team A: 20 + 15 = 35
    # Team B: 18 + 12 = 30
    # Team A should win
    assert result["winner"] == "Team A"
    assert result["value_difference"] == 5.0
    assert result["team_a_weeks_value"] > result["team_b_weeks_value"]


def test_get_decision_layer_recommendations():
    roster_players = [
        {"player_id": "1", "player_name": "QB1", "position_group": "QB", "projected_points": 20.0}
    ]
    bench_players = [
        {"player_id": "2", "player_name": "RB1", "position_group": "RB", "projected_points": 15.0}
    ]
    free_agents = [
        {"player_id": "3", "player_name": "WR1", "position_group": "WR", "projected_points": 18.0}
    ]
    scoring_settings = {"pass_td": 4, "pass_yd": 0.04}
    roster_positions = ["QB", "RB", "WR", "TE"]

    recommendations = get_decision_layer_recommendations(
        roster_players, bench_players, free_agents, scoring_settings, roster_positions
    )

    assert "start_sit" in recommendations
    assert "waiver_priority" in recommendations
    assert "trade_evaluation" in recommendations
    assert "timestamp" in recommendations

    # Check start/sit has recommendations
    assert len(recommendations["start_sit"]) > 0

    # Check waiver has recommendations
    assert len(recommendations["waiver_priority"]) > 0