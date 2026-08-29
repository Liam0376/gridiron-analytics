from ffanalytics.decision import (
    calculate_roster_value,
    get_start_sit_recommendations,
    get_waiver_priority,
    evaluate_trade,
    get_decision_layer_recommendations
)


def test_calculate_roster_value():
    players = [
        {"player_id": "1", "position_group": "QB", "projected_points": 20.0},
        {"player_id": "2", "position_group": "RB", "projected_points": 15.0},
        {"player_id": "3", "position_group": "WR", "projected_points": 10.0},
    ]
    scoring_settings = {"pass_td": 4, "pass_yd": 0.04}
    roster_positions = ["QB", "RB", "WR"]

    value = calculate_roster_value(players, scoring_settings, roster_positions)
    # VBD: each player is only one at their position, replacement = themselves → VBD ≥ 0
    assert isinstance(value, (int, float))
    assert value >= 0

    # More players than slots → only starters count
    players.append({"player_id": "4", "position_group": "RB", "projected_points": 5.0})
    value2 = calculate_roster_value(players, scoring_settings, roster_positions)
    assert value2 >= 0


def test_get_start_sit_recommendations():
    roster_players = [
        {"player_id": "1", "player_name": "QB1", "position_group": "QB", "projected_points": 20.0},
        {"player_id": "2", "player_name": "RB1", "position_group": "RB", "projected_points": 15.0},
        {"player_id": "5", "player_name": "RB3", "position_group": "RB", "projected_points": 5.0},
    ]
    bench_players = [
        {"player_id": "3", "player_name": "RB2", "position_group": "RB", "projected_points": 18.0},
        {"player_id": "4", "player_name": "WR1", "position_group": "WR", "projected_points": 12.0},
    ]
    scoring_settings = {"pass_td": 4, "pass_yd": 0.04}
    roster_positions = ["QB", "RB", "RB", "WR"]

    recommendations = get_start_sit_recommendations(
        roster_players, bench_players, scoring_settings, roster_positions
    )

    # 5 players, 4 slots → at least 1 SIT
    assert len(recommendations) == 5

    decisions = [r["recommendation"] for r in recommendations]
    has_start = any("START" in d for d in decisions)
    has_sit = any("SIT" in d for d in decisions)
    assert has_start
    assert has_sit

    # RB2 (18pts) should start over RB3 (5pts)
    started_ids = {r["player_id"] for r in recommendations if "START" in r["recommendation"]}
    assert "3" in started_ids  # RB2 should start


def test_get_start_sit_no_five_qb_problem():
    """Position constraints prevent starting 5 QBs even if they project highest."""
    players_roster = [
        {"player_id": f"qb{i}", "player_name": f"QB{i}", "position_group": "QB", "projected_points": 25.0 - i}
        for i in range(4)
    ]
    players_bench = [
        {"player_id": "rb1", "player_name": "RB1", "position_group": "RB", "projected_points": 10.0},
        {"player_id": "wr1", "player_name": "WR1", "position_group": "WR", "projected_points": 8.0},
    ]
    roster_positions = ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "FLEX", "K", "DEF"]

    recs = get_start_sit_recommendations(
        players_roster, players_bench, {}, roster_positions
    )
    started_qbs = [r for r in recs if "START" in r["recommendation"] and r.get("slot") == "QB"]
    assert len(started_qbs) <= 1


def test_get_waiver_priority():
    roster_players = [
        {"player_id": "1", "player_name": "RB1", "position_group": "RB", "projected_points": 10.0},
        {"player_id": "2", "player_name": "WR1", "position_group": "WR", "projected_points": 15.0},
    ]
    free_agents = [
        {"player_id": "3", "player_name": "RB2", "position_group": "RB", "projected_points": 20.0},
        {"player_id": "4", "player_name": "WR2", "position_group": "WR", "projected_points": 12.0},
    ]
    scoring_settings = {"pass_td": 4, "pass_yd": 0.04}
    roster_positions = ["QB", "RB", "RB", "WR"]

    waiver = get_waiver_priority(
        roster_players, free_agents, scoring_settings, roster_positions
    )

    # RB2 (20pts) should be recommended — better than RB1 (10pts)
    assert len(waiver) >= 1
    assert waiver[0]["player_id"] == "3"
    assert waiver[0]["improvement_over_roster"] > 0


def test_evaluate_trade():
    team_a_players = [
        {"player_id": "a1", "position_group": "RB", "projected_points": 20.0},
        {"player_id": "a2", "position_group": "WR", "projected_points": 15.0},
    ]
    team_b_players = [
        {"player_id": "b1", "position_group": "RB", "projected_points": 18.0},
        {"player_id": "b2", "position_group": "WR", "projected_points": 12.0},
    ]
    scoring_settings = {"pass_td": 4, "pass_yd": 0.04}
    roster_positions = ["QB", "RB", "WR", "TE"]

    result = evaluate_trade(
        team_a_players, team_b_players, scoring_settings, roster_positions
    )

    assert "winner" in result
    assert "value_difference" in result
    assert "recommendation" in result
    # Team A has more VBD value
    assert result["winner"] in ("Team A", "Fair")


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
    assert len(recommendations["start_sit"]) > 0
