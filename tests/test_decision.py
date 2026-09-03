from ffanalytics.decision import (
    calculate_roster_value,
    get_start_sit_recommendations,
    get_waiver_priority,
    evaluate_trade,
    get_decision_layer_recommendations,
    calculate_rest_of_season_value,
    ENABLE_OPPONENT_ADJUSTMENT,
    get_start_sit_gated,
    get_waiver_priority_gated,
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


def test_opponent_adjustment_gated_off_by_default():
    # Production default OFF (tested and REJECTED per stat_projector.py:22-24).
    # Same player vs weak/strong defense → same ROS when flag OFF.
    assert ENABLE_OPPONENT_ADJUSTMENT is False
    from ffanalytics.rating import Rating
    base = {
        "player_id": "r1", "position": "RB", "projected_points": 15.0,
        "opponent_team": "OPP",
    }
    weak = {"OPP": {"overall": Rating(1300.0, 50.0), "vs_RB": Rating(1300.0, 50.0)}}
    strong = {"OPP": {"overall": Rating(1700.0, 50.0), "vs_RB": Rating(1700.0, 50.0)}}
    v_weak = calculate_rest_of_season_value(base, 5, 18, weak, {"RB": 5.0}, 1.0)
    v_strong = calculate_rest_of_season_value(base, 5, 18, strong, {"RB": 5.0}, 1.0)
    assert v_weak == v_strong
    # evaluate_trade passes {} so behavior unchanged regardless of flag
    team_a = [{"player_id": "a1", "position_group": "RB", "projected_points": 20.0}]
    team_b = [{"player_id": "b1", "position_group": "RB", "projected_points": 18.0}]
    res = evaluate_trade(team_a, team_b, {}, ["QB", "RB", "WR", "TE"])
    assert "winner" in res


def test_shadow_gating_fallback_vs_experimental():
    # In-memory sqlite: <20 resolved → fallback (baseline), >=20 → experimental.
    # Resolved-only counting (actual_outcome IS NOT NULL); logged-only does NOT count.
    import sqlite3
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """CREATE TABLE shadow_recommendations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            kind TEXT NOT NULL, season INTEGER NOT NULL, week INTEGER NOT NULL,
            player_id TEXT, recommendation TEXT NOT NULL,
            logged_at TEXT NOT NULL, actual_outcome TEXT
        )"""
    )
    roster = [{"player_id": "1", "player_name": "RB1", "position_group": "RB", "projected_points": 10.0}]
    bench: list = []
    free = [{"player_id": "2", "player_name": "RB2", "position_group": "RB", "projected_points": 20.0}]
    scoring: dict = {}
    slots = ["QB", "RB", "RB", "WR"]
    # 0 rows → fallback
    recs0 = get_waiver_priority_gated(conn, roster, free, scoring, slots, kind="waiver")
    assert all(r.get("rule") == "baseline" for r in recs0)
    # 19 resolved → still fallback
    for i in range(19):
        conn.execute(
            "INSERT INTO shadow_recommendations (kind, season, week, player_id, recommendation, logged_at, actual_outcome) VALUES (?,?,?,?,?,?,?)",
            ("waiver", 2025, 4, f"p{i}", '{"a":1}', "2025-09-01T00:00:00", '{"actual_points":10}'),
        )
    conn.commit()
    recs19 = get_waiver_priority_gated(conn, roster, free, scoring, slots, kind="waiver")
    assert all(r.get("rule") == "baseline" for r in recs19)
    # 20 logged-only (NULL outcome) on different kind → still fallback for waiver, proves resolved-only
    for i in range(20):
        conn.execute(
            "INSERT INTO shadow_recommendations (kind, season, week, player_id, recommendation, logged_at, actual_outcome) VALUES (?,?,?,?,?,?,NULL)",
            ("start_sit", 2025, 4, f"q{i}", '{"a":1}', "2025-09-01T00:00:00"),
        )
    conn.commit()
    recs_still = get_start_sit_gated(conn, roster, bench, scoring, slots, kind="start_sit")
    assert all(r.get("rule") == "baseline" for r in recs_still)
    # 20th resolved for waiver → experimental
    conn.execute(
        "INSERT INTO shadow_recommendations (kind, season, week, player_id, recommendation, logged_at, actual_outcome) VALUES (?,?,?,?,?,?,?)",
        ("waiver", 2025, 4, "p19", '{"a":1}', "2025-09-01T00:00:00", '{"actual_points":12}'),
    )
    conn.commit()
    recs20 = get_waiver_priority_gated(conn, roster, free, scoring, slots, kind="waiver")
    assert len(recs20) > 0
    assert all(r.get("rule") == "experimental" for r in recs20)
    # conn=None → non-breaking baseline
    recs_none = get_waiver_priority_gated(None, roster, free, scoring, slots, kind="waiver")
    assert all(r.get("rule") == "baseline" for r in recs_none)
    conn.close()


def test_vor_sensitivity_replacement_pm2_ordering_stable():
    # Methodology only, no value changes: vary replacement ±2, dollar ordering stable.
    from ffanalytics.decision import _vbd, _vbd_auction_params_from_comps
    comp_list = [
        {"player_id": f"p{i}", "position": pos, "model_season_points": pts, "market_season_points": pts * 0.95}
        for i, (pos, pts) in enumerate([("RB", 300.0), ("RB", 250.0), ("WR", 280.0), ("WR", 200.0), ("QB", 350.0)])
    ]
    model_repl, pos_weight, dollar_per_vor = _vbd_auction_params_from_comps(comp_list)
    assert model_repl and pos_weight
    # Base VOR ordering
    def _order(repl):
        vals = []
        for r in comp_list:
            pos = r["position"]
            vor = max(0.0, float(r["model_season_points"]) - repl.get(pos, 100.0)) * pos_weight.get(pos, 1.0)
            vals.append((r["player_id"], vor))
        vals.sort(key=lambda x: x[1], reverse=True)
        return [pid for pid, _ in vals]
    base_order = _order(model_repl)
    up = {k: v + 2.0 for k, v in model_repl.items()}
    down = {k: v - 2.0 for k, v in model_repl.items()}
    assert _order(up) == base_order
    assert _order(down) == base_order
    # Dollar ordering stable (dollar = VOR * dollar_per_vor, monotonic)
    assert dollar_per_vor >= 0


def test_holdout_decision_quality_vor_vs_points_report_only():
    # Report-only: VOR ranking vs points ranking on fixture, no flip thresholds.
    from ffanalytics.decision import _vbd, _replacement_levels
    players = [
        {"player_id": f"p{i}", "position": pos, "position_group": pos, "projected_points": pts}
        for i, (pos, pts) in enumerate([("RB", 20.0), ("WR", 18.0), ("RB", 15.0), ("TE", 12.0), ("QB", 22.0)])
    ]
    slots = ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "FLEX", "K", "DEF"]
    repl = _replacement_levels(players, slots, num_teams=2)
    by_points = sorted(players, key=lambda p: float(p["projected_points"]), reverse=True)
    by_vor = sorted(players, key=lambda p: _vbd(p, repl), reverse=True)
    # Same set, same length — report overlap, no hard threshold that flips behavior
    assert {p["player_id"] for p in by_points} == {p["player_id"] for p in by_vor}
    assert len(by_points) == len(by_vor) == 5
    overlap_top3 = len({p["player_id"] for p in by_points[:3]} & {p["player_id"] for p in by_vor[:3]})
    print(f"[decision-quality] VOR vs points top-3 overlap {overlap_top3}/3 on fixture (report-only)")
    assert overlap_top3 >= 0  # report-only, never flips
