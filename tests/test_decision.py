from ffanalytics.decision import (
    calculate_roster_value,
    get_start_sit_recommendations,
    get_waiver_priority,
    evaluate_trade,
    get_decision_layer_recommendations,
    calculate_rest_of_season_value,
    slot_uplift_value,
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


def test_evaluate_trade_small_fallback_reports_points_not_dollars():
    # why (correctness batch 2026-09-12): 2-for-1 fallback comp_list yielded
    # dollar_per_vor 11.43 and reported 59.4 VOR as $678.7. Gate on use_market.
    team_a = [
        {"player_id": "a1", "position_group": "RB", "projected_points": 20.0},
        {"player_id": "a2", "position_group": "WR", "projected_points": 15.0},
    ]
    team_b = [
        {"player_id": "b1", "position_group": "RB", "projected_points": 10.0},
    ]
    res = evaluate_trade(team_a, team_b, {}, ["QB", "RB", "WR", "TE"])
    assert res["ros_dollars_are_real_dollars"] is False
    assert "pts (no market data" in res["recommendation"]
    assert "$" not in res["recommendation"]


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


def test_ensure_intervals_floors_negative_lower():
    # why floor at 0 (data-viz sign-off): a 2-pt projection with width 5
    # rendered [-3, 7] — negative points are impossible; src and hub floor.
    from ffanalytics.decision import _ensure_intervals
    out = _ensure_intervals({"projected_points": 2.0, "position": "K"})
    assert out["projection_lower"] == 0.0
    assert out["projection_upper"] > 2.0
    assert out["projection_lower"] <= 2.0 <= out["projection_upper"]


# ---------------------------------------------------------------- slot uplift
# why these tests (trade slot plan, Phase 1): unequal trades (2-for-1, 3-for-2)
# hand the receiver an open roster slot. slot_uplift_value prices it as the
# marginal _optimal_lineup gain from the best waiver fill — net by
# construction, exactly 0.0 when the pickup rides the bench. Phase 1 keeps the
# verdict byte-identical (slot fields informational); Phase 3 gates the fold.

def _slot_p(pos, pid, pts, name=None):
    d = {"player_id": pid, "position": pos, "position_group": pos,
         "projected_points": pts,
         "player_name": name or f"Player {pid}"}
    return d


def test_slot_uplift_bench_rider_is_zero():
    # FLEX already held by WR12; waiver best is WR5 (plus a NaN-points decoy
    # that must neither crash sorting nor be selected) → uplift exactly 0.0.
    post = [_slot_p("QB", "qb", 20.0), _slot_p("RB", "rb", 15.0),
            _slot_p("WR", "wr", 14.0), _slot_p("WR", "wr2", 12.0),
            _slot_p("TE", "te", 9.0)]
    pool = [_slot_p("WR", "w1", 5.0), _slot_p("RB", "w2", 4.0),
            {"player_id": "wn", "position": "WR", "position_group": "WR",
             "projected_points": float("nan"), "player_name": "NaN WR"}]
    up, names = slot_uplift_value(
        post, pool, ["QB", "RB", "WR", "TE", "FLEX"],
        current_week=1, total_weeks=18)
    assert up == 0.0
    assert names == []


def test_slot_uplift_flex_upgrade_positive():
    # FLEX empty (no remaining RB/WR/TE) → WR7 fills it: 7/wk x 9 wk = 63.0.
    post = [_slot_p("QB", "qb", 20.0), _slot_p("RB", "rb", 10.0),
            _slot_p("WR", "wr", 10.0), _slot_p("TE", "te", 5.0)]
    pool = [_slot_p("WR", "w1", 7.0, "Waiver WR1")]
    up, names = slot_uplift_value(
        post, pool, ["QB", "RB", "WR", "TE", "FLEX"],
        current_week=10, total_weeks=18)
    assert up == 63.0
    assert names == ["Waiver WR1"]


def test_evaluate_trade_equal_count_no_slot():
    # 1v1 and 2v2 → zero slot delta → uplift dust-free zero (epsilon, since
    # the value flows through float ROS scaling).
    rp = ["QB", "RB", "WR", "TE"]
    a1 = [_slot_p("RB", "a1", 20.0)]
    b1 = [_slot_p("RB", "b1", 18.0)]
    r = evaluate_trade(a1, b1, {}, rp, traded_a_ids=["a1"], traded_b_ids=["b1"],
                       rostered_ids=["a1", "b1"],
                       all_league_players=a1 + b1)
    assert r["slots_gained_a"] == 0 and r["slots_gained_b"] == 0
    assert abs(r["slot_uplift_a"]) < 1e-9 and abs(r["slot_uplift_b"]) < 1e-9
    assert r["slot_waiver_a"] == [] and r["slot_waiver_b"] == []
    assert r["slot_rule"] == "baseline"
    a2 = a1 + [_slot_p("WR", "a2", 15.0)]
    b2 = b1 + [_slot_p("WR", "b2", 12.0)]
    r2 = evaluate_trade(a2, b2, {}, rp, traded_a_ids=["a1", "a2"],
                        traded_b_ids=["b1", "b2"],
                        rostered_ids=["a1", "a2", "b1", "b2"],
                        all_league_players=a2 + b2)
    assert r2["slots_gained_a"] == 0 and r2["slots_gained_b"] == 0
    assert abs(r2["slot_uplift_a"]) < 1e-9 and abs(r2["slot_uplift_b"]) < 1e-9


def test_evaluate_trade_2for1_package_params():
    # A sends RB18+WR11, receives RB17 → A gains 1 slot. Post-A WR2 is a_b2
    # (5); waiver WR13 takes that slot: (13-5)/wk x 18 wk = 144.0.
    # (Not the FLEX swap: FLEX stays RB6 either way.)
    rp = ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "K", "DEF"]
    team_a = [_slot_p("QB", "a_qb", 20.0), _slot_p("RB", "a_rb1", 18.0),
              _slot_p("RB", "a_rb2", 12.0), _slot_p("WR", "a_wr1", 16.0),
              _slot_p("WR", "a_wr2", 11.0), _slot_p("TE", "a_te", 9.0),
              _slot_p("K", "a_k", 8.0), _slot_p("DEF", "a_def", 7.0),
              _slot_p("RB", "a_b1", 6.0), _slot_p("WR", "a_b2", 5.0)]
    team_b = [_slot_p("QB", "b_qb", 19.0), _slot_p("RB", "b_rb1", 17.0),
              _slot_p("RB", "b_rb2", 10.0), _slot_p("WR", "b_wr1", 15.0),
              _slot_p("WR", "b_wr2", 9.0), _slot_p("TE", "b_te", 8.0),
              _slot_p("K", "b_k", 7.0), _slot_p("DEF", "b_def", 6.0),
              _slot_p("RB", "b_b1", 5.0), _slot_p("WR", "b_b2", 4.0)]
    fa = [_slot_p("WR", "w_wr1", 13.0, "Waiver WR1"),
          _slot_p("RB", "w_rb1", 8.0, "Waiver RB1"),
          _slot_p("TE", "w_te1", 7.0, "Waiver TE1")]
    league = team_a + team_b + fa
    rostered = [p["player_id"] for p in team_a + team_b]
    r = evaluate_trade(team_a, team_b, {}, rp, current_week=1,
                       traded_a_ids=["a_rb1", "a_wr2"], traded_b_ids=["b_rb1"],
                       rostered_ids=rostered, all_league_players=league)
    assert r["slots_gained_a"] == 1
    assert r["slots_gained_b"] == 0
    assert r["slot_uplift_a"] == 144.0
    assert r["slot_waiver_a"] == ["Waiver WR1"]
    assert r["slot_uplift_b"] == 0.0
    assert r["slot_rule"] == "baseline"
    # Phase 1: verdict untouched by slot fields (fold gated to Phase 3).
    r_nopkg = evaluate_trade(team_a, team_b, {}, rp, current_week=1)
    assert r["winner"] == r_nopkg["winner"]
    assert r["value_difference"] == r_nopkg["value_difference"]
    assert r["recommendation"] == r_nopkg["recommendation"]


def test_evaluate_trade_k_slot_fill_priced_honestly():
    # K slot empties (K10 sent, backup K6 remains) → waiver K9 upgrades it:
    # (9-6)/wk x 18 wk = 54.0. Streaming value priced as points, not zeroed.
    rp = ["QB", "RB", "WR", "TE", "FLEX", "K", "DEF"]
    team_a = [_slot_p("QB", "a_qb", 20.0), _slot_p("RB", "a_rb", 15.0),
              _slot_p("WR", "a_wr", 14.0), _slot_p("TE", "a_te", 9.0),
              _slot_p("K", "a_k", 10.0), _slot_p("K", "a_k2", 6.0),
              _slot_p("DEF", "a_def", 7.0)]
    team_b = [_slot_p("QB", "b_qb", 19.0), _slot_p("RB", "b_rb", 16.0),
              _slot_p("WR", "b_wr", 13.0), _slot_p("TE", "b_te", 8.0),
              _slot_p("K", "b_k", 8.0), _slot_p("DEF", "b_def", 6.0)]
    fa = [_slot_p("K", "w_k", 9.0, "Waiver K")]
    league = team_a + team_b + fa
    rostered = [p["player_id"] for p in team_a + team_b]
    r = evaluate_trade(team_a, team_b, {}, rp, current_week=1,
                       traded_a_ids=["a_k", "a_wr"], traded_b_ids=["b_wr"],
                       rostered_ids=rostered, all_league_players=league)
    assert r["slots_gained_a"] == 1
    assert r["slot_uplift_a"] == 54.0
    assert r["slot_waiver_a"] == ["Waiver K"]


def test_evaluate_trade_season_end_no_uplift():
    # current_week=19 → weeks_remaining 0 → uplift 0 even with open slot.
    # current_week=18 → exactly 1 week of uplift.
    rp = ["QB", "RB", "WR", "TE", "FLEX"]
    post = [_slot_p("QB", "qb", 20.0), _slot_p("RB", "rb", 10.0),
            _slot_p("WR", "wr", 10.0), _slot_p("TE", "te", 5.0)]
    pool = [_slot_p("WR", "w1", 7.0, "Waiver WR1")]
    up19, n19 = slot_uplift_value(post, pool, rp, current_week=19)
    assert up19 == 0.0 and n19 == []
    up18, n18 = slot_uplift_value(post, pool, rp, current_week=18)
    assert up18 == 7.0 and n18 == ["Waiver WR1"]


def test_slot_uplift_dst_maps_to_def_slot():
    # DST-position waiver fills a DEF slot (parity with side_value's
    # normalization). Without the mapping the optimizer benches it → 0.
    post = [_slot_p("QB", "qb", 20.0), _slot_p("RB", "rb", 15.0),
            _slot_p("WR", "wr", 14.0), _slot_p("TE", "te", 9.0)]
    pool = [_slot_p("DST", "w1", 8.0, "Waiver DST")]
    up, names = slot_uplift_value(
        post, pool, ["QB", "RB", "WR", "TE", "DEF"],
        current_week=1, total_weeks=18)
    assert up == 144.0
    assert names == ["Waiver DST"]


def test_evaluate_trade_no_packages_backward_compat():
    # Omitted package params → slot fields zero AND verdict identical to a
    # call on the same fixture. Guards the Phase 1 no-behavior-change claim.
    team_a = [_slot_p("RB", "a1", 20.0), _slot_p("WR", "a2", 15.0)]
    team_b = [_slot_p("RB", "b1", 18.0), _slot_p("WR", "b2", 12.0)]
    rp = ["QB", "RB", "WR", "TE"]
    r = evaluate_trade(team_a, team_b, {"pass_td": 4}, rp)
    for k in ("slots_gained_a", "slots_gained_b", "slot_uplift_a",
              "slot_uplift_b"):
        assert r[k] == 0
    assert r["slot_waiver_a"] == [] and r["slot_waiver_b"] == []
    assert r["slot_rule"] == "baseline"
    assert r["winner"] in ("Team A", "Fair")
    # Existing points-not-dollars gate fixture still labels honestly.
    r2 = evaluate_trade(
        [_slot_p("RB", "a1", 20.0), _slot_p("WR", "a2", 15.0)],
        [_slot_p("RB", "b1", 10.0)], {}, rp)
    assert r2["ros_dollars_are_real_dollars"] is False
    assert "pts (no market data" in r2["recommendation"]
    assert "$" not in r2["recommendation"]


def test_trade_gated_falls_back_untrusted():
    # why (trade slot plan, Phase 3): the uplift fold must not flip live
    # winners before 20 resolved trade samples. Fixture: A sends RB20+WR15,
    # receives RB19 → A gains 1 slot; post-A WR slot empty → waiver WR10
    # fills it: 10/wk x 18 wk = 180.0. Base diff: (20-19)x18x1.10 = 19.8.
    import sqlite3
    from ffanalytics.decision import evaluate_trade_gated
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
    rp = ["QB", "RB", "WR", "TE", "FLEX"]
    team_a = [_slot_p("RB", "a1", 20.0), _slot_p("WR", "a2", 15.0)]
    team_b = [_slot_p("RB", "b1", 19.0)]
    fa = [_slot_p("WR", "w1", 10.0, "Waiver WR1")]
    kw = dict(scoring_settings={}, roster_positions=rp, current_week=1,
              all_league_players=team_a + team_b + fa,
              traded_a_ids=["a1", "a2"], traded_b_ids=["b1"],
              rostered_ids=["a1", "a2", "b1"], kind="trade")
    # conn=None → baseline, winner from base diff only.
    r_none = evaluate_trade_gated(None, team_a, team_b, **kw)
    assert r_none["slot_rule"] == "baseline"
    assert r_none["winner"] == "Team A"
    assert r_none["value_difference"] == 19.8
    assert r_none["slot_uplift_a"] == 180.0
    # 0 rows → baseline.
    r0 = evaluate_trade_gated(conn, team_a, team_b, **kw)
    assert r0["slot_rule"] == "baseline"
    assert r0["value_difference"] == 19.8
    # 19 resolved → still baseline.
    for i in range(19):
        conn.execute(
            "INSERT INTO shadow_recommendations (kind, season, week, player_id, recommendation, logged_at, actual_outcome) VALUES (?,?,?,?,?,?,?)",
            ("trade", 2025, 4, f"t{i}", '{"a":1}', "2025-09-01T00:00:00", '{"won": true}'),
        )
    conn.commit()
    r19 = evaluate_trade_gated(conn, team_a, team_b, **kw)
    assert r19["slot_rule"] == "baseline"
    assert r19["value_difference"] == 19.8
    # 20th resolved → experimental: uplift folded, fields consistent.
    conn.execute(
        "INSERT INTO shadow_recommendations (kind, season, week, player_id, recommendation, logged_at, actual_outcome) VALUES (?,?,?,?,?,?,?)",
        ("trade", 2025, 4, "t19", '{"a":1}', "2025-09-01T00:00:00", '{"won": true}'),
    )
    conn.commit()
    r20 = evaluate_trade_gated(conn, team_a, team_b, **kw)
    assert r20["slot_rule"] == "experimental"
    assert r20["value_difference"] == 199.8
    assert r20["winner"] == "Team A"
    assert "[slot uplift" in r20["recommendation"]
    # Consistency: folded diff agrees with folded team fields.
    assert r20["team_a_ros_vbd"] == r_none["team_a_ros_vbd"] + 180.0
    assert r20["team_b_ros_vbd"] == r_none["team_b_ros_vbd"]
    conn.close()
