from ffanalytics.comparison import (
    _normalize_name,
    build_gsis_map,
    map_market_to_gsis,
    build_comparison,
)


def test_normalize_name():
    assert _normalize_name("Patrick Mahomes II") == "patrick mahomes"
    assert _normalize_name("Marvin Harrison Jr.") == "marvin harrison"
    assert _normalize_name(" Odell Beckham Jr. ") == "odell beckham"
    assert _normalize_name("") == ""


def test_build_gsis_map():
    sleeper_players = {
        "123": {"gsis_id": "00-0036945"},
        "456": {"gsis_id": " 00-0034796 "},
        "789": {},
    }
    gsis_map = build_gsis_map(sleeper_players)
    assert gsis_map == {
        "123": "00-0036945",
        "456": "00-0034796",
    }


def test_map_market_to_gsis():
    sleeper_players = {
        "123": {"gsis_id": "00-0036945"},
    }
    market = {
        "123": {"pts_ppr": 18.5, "stats": {"pass_yd": 250}},
        "999": {"pts_ppr": 10.0},
    }
    result = map_market_to_gsis(market, sleeper_players)
    assert "00-0036945" in result
    assert result["00-0036945"]["pts_ppr"] == 18.5
    assert "999" not in result


def test_build_comparison_empty():
    res = build_comparison([], {}, [])
    assert res == []


def test_build_comparison_with_data():
    model_projs = [
        {
            "player_id": "00-0036945",
            "player_name": "Patrick Mahomes",
            "position": "QB",
            "recent_team": "KC",
            "projected_points": 20.5,
            "passing_yards": 280,
            "passing_tds": 2,
        }
    ]
    market_by_gsis = {
        "00-0036945": {
            "pts_ppr": 19.0,
            "stats": {"pass_yd": 260, "pass_td": 2},
        }
    }
    fpros = [
        {"player_name": "Patrick Mahomes", "team": "KC", "position": "QB", "ecr": 1, "adp": 15}
    ]
    res = build_comparison(model_projs, market_by_gsis, fpros)
    assert len(res) == 1
    row = res[0]
    assert row["player_name"] == "Patrick Mahomes"
    assert row["model_points"] == 20.5
    assert row["market_points"] == 19.0
    assert row["delta_points"] == 1.5


def test_qb_scoring_alignment():
    # Audit: FP 4pt vs Sleeper 5pt — market 294 + 34*1.15 = ~333
    from ffanalytics.adapters.fantasypros_projections import get_fantasypros_projections_map

    # Simulate model proj for QB
    model_projs = [
        {
            "player_id": "00-0026498",
            "player_display_name": "Matthew Stafford",
            "position": "QB",
            "team": "LA",
            "projected_points": 20.0,
            "passing_yards": 300,
            "passing_tds": 2,
            "_neutral_points": 19.0,
            "_neutral_stats": {"passing_yards": 280, "passing_tds": 1.7},
        }
    ]
    fp_map = {("matthew stafford", "LA", "QB"): {"fpts": 294.0, "passing_yards": 4190.5, "passing_tds": 34.0, "passing_interceptions": 8.6, "rushing_yards": 33.1, "rushing_tds": 0.2, "fumbles_lost_total": 2.8}}
    res = build_comparison(model_projs, {}, [], None, fp_map, [])
    row = res[0]
    # 294 + 34*1 + 34*0.15 = 333.1
    assert row["market_season_points"] == 333.1


def test_neutral_points_and_shrinkage():
    model_projs = [
        {
            "player_id": "p1",
            "player_display_name": "Test WR",
            "position": "WR",
            "team": "KC",
            "projected_points": 25.0,
            "receiving_yards": 100,
            "_neutral_points": 20.0,
            "_neutral_stats": {"receiving_yards": 80, "receptions": 5},
        }
    ]
    fp_map = {("test wr", "KC", "WR"): {"fpts": 150.0, "receiving_yards": 800, "receptions": 60}}
    res = build_comparison(model_projs, {}, [], None, fp_map, [])
    row = res[0]
    # Raw neutral 340 vs market 150 delta 190 → shrink 20% → 0.8*340+0.2*150=302
    assert row["model_season_points"] == 302.0
    # Stats also shrunk proportionally
    assert row["model_season_stats"]["receiving_yards"] < 1360.0


def test_season_panel_shrink_parity():
    # why (correctness batch 2026-09-12): header shrank but panel was raw.
    # neutral 20.0 x 17 = 340 vs market 200 delta 140 shrinks to 312.0.
    # Panel model for passing_yards 300 x 17 x factor must match.
    model_projs = [
        {
            "player_id": "p9",
            "player_display_name": "Parity QB",
            "position": "QB",
            "team": "KC",
            "projected_points": 20.0,
            "passing_yards": 300,
            "_neutral_points": 20.0,
            "_neutral_stats": {"passing_yards": 300},
        }
    ]
    fp_map = {("parity qb", "KC", "QB"): {"fpts": 200.0, "passing_yards": 4000.0}}
    res = build_comparison(model_projs, {}, [], None, fp_map, [])
    row = res[0]
    assert row["model_season_points"] == 312.0
    panel = {d["key"]: d for d in row["season_stat_deltas"]}
    assert "passing_yards" in panel
    assert panel["passing_yards"]["model"] == round(300 * 17 * (312.0 / 340.0), 1)


def test_draft_aware_auction_preserved():
    model_projs = [
        {
            "player_id": "00-001",
            "player_display_name": "Test RB",
            "position": "RB",
            "team": "DET",
            "projected_points": 20.0,
            "rushing_yards": 100,
            "_neutral_points": 18.0,
            "_neutral_stats": {"rushing_yards": 90},
        }
    ]
    draft_prices = {"00-001": 42.0}
    res = build_comparison(model_projs, {}, [], None, {}, [], draft_prices=draft_prices)
    row = res[0]
    assert row["auction_price_paid"] == 42.0
    # auction should be VOR-derived, not 42
    assert row["auction"] != 42.0
    # delta should be vs paid
    assert row["deltaAuction"] == row["auction"] - 42


def test_k_csv_parsing():
    from ffanalytics.adapters.fantasypros_projections import get_fantasypros_projections_map

    m = get_fantasypros_projections_map()
    # K Aubrey should be 153.0 (FPTS) not 47.6 (XPT)
    assert m[("brandon aubrey", "DAL", "K")]["fpts"] == 153.0
    assert m[("kaimi fairbairn", "HOU", "K")]["fpts"] == 144.1


def test_budget_pool_and_positional_weights():
    # Build many players to test budget math
    model_projs = [
        {"player_id": f"p{i}", "player_display_name": f"Player{i}", "position": pos, "team": "KC", "projected_points": 10 + i % 10, "_neutral_points": 10 + i % 10, "_neutral_stats": {}}
        for i, pos in enumerate(["QB"] * 12 + ["RB"] * 28 + ["WR"] * 32 + ["TE"] * 12)
    ]
    res = build_comparison(model_projs, {}, [], None, {}, [])
    total = sum(r["auction"] for r in res if r["auction"] > 0)
    # Should be near 2352 (bench $1 each) within 300 tolerance for synthetic data
    assert 2000 < total < 3000


def test_streamer_vor_weight_zero_for_k_def_dst():
    # why (correctness batch 2026-09-12): DST missed the 0 clamp and minted
    # unweighted VOR via .get default 1.0. K/DEF/DST all weight 0.
    from ffanalytics.comparison._auction import _weighted_vor
    assert _weighted_vor(300.0, "DST", {"DST": 100.0}, {}) == 0.0
    assert _weighted_vor(300.0, "K", {"K": 100.0}, {}) == 0.0
    assert _weighted_vor(300.0, "DEF", {"DEF": 100.0}, {}) == 0.0
    assert _weighted_vor(300.0, "RB", {"RB": 100.0}, {"RB": 1.1}) > 0


def test_exact_fpid_join_beats_fuzzy_mismatch():
    # why (ecr-baseline spec): fuzzy name matching mis-joins movers and
    # suffix variants; fantasypros_id->gsis is exact. The model name here
    # ("Nobody Knows") matches NOTHING fuzzy, yet ECR attaches by id.
    from ffanalytics.comparison import build_comparison
    model_projs = [{
        "player_id": "00-0034857",
        "player_display_name": "Nobody Knows",
        "position": "QB",
        "team": "BUF",
        "projected_points": 20.0,
    }]
    fpros = [{
        "player_name": "Josh Allen", "team_id": "BUF", "position_id": "QB",
        "rank_ecr_ppr": 1.0, "rank_ecr_pos": 1, "fantasypros_id": "12345",
    }]
    res = build_comparison(model_projs, {}, fpros,
                           gsis_to_fpid={"00-0034857": "12345"})
    assert len(res) == 1
    assert res[0]["fp_ecr"] == 1
    assert res[0]["fp_ecr_pos"] == 1


def test_fuzzy_fallback_survives_without_ids():
    # why: CSV legacy rows and rookies carry no fantasypros_id — the old
    # path must keep working when the id maps are absent.
    from ffanalytics.comparison import build_comparison
    model_projs = [{
        "player_id": "00-0034857",
        "player_display_name": "Josh Allen",
        "position": "QB",
        "team": "BUF",
        "projected_points": 20.0,
    }]
    fpros = [{
        "player_name": "Josh Allen", "team_id": "BUF", "position_id": "QB",
        "rank_ecr_ppr": 2.0, "rank_ecr_pos": 2,
    }]
    res = build_comparison(model_projs, {}, fpros)
    assert len(res) == 1
    assert res[0]["fp_ecr"] == 2
