import pytest
from ffanalytics.stat_projector import (
    project_player_stats,
    build_weekly_projections,
    compute_conformal_bounds,
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
    # 3 old 60, 3 recent 120 → trend = (120/60)-1 = 1.0, capped to ±0.5 → 0.5
    # base 90 * (1 + 0.5 * 0.15) = 90 * 1.075 = 96.75
    history = [{"rushing_yards": 60} for _ in range(3)] + [{"rushing_yards": 120} for _ in range(3)]
    base = 90
    adjusted = _usage_trend_adjustment(base, history, "rushing_yards")
    assert adjusted == pytest.approx(96.75)


def test_vegas_safe_float_string():
    from ffanalytics.stat_projector import build_game_context
    schedule = [{"game_type": "REG", "week": 1, "home_team": "KC", "away_team": "LV", "total_line": "48.0", "spread_line": "-7.0", "roof": "outdoors", "temp": "65", "wind": "5"}]
    ctx = build_game_context(schedule)
    assert ctx[("KC", 1)]["implied_total"] == 20.5
    assert ctx[("LV", 1)]["implied_total"] == 27.5


def test_default_implied_total_21_provenance():
    # Default 21.0 frozen (conservative below league avg 22.2 for BYE/missing; no value change).
    # Empty schedule → BYE fallback with 21.0 implied (documents provenance, guards against retune).
    season_stats = [
        {"player_id": "p9", "player_display_name": "Test RB", "position": "RB", "team": "DET", "week": 1, "season_type": "REG", "rushing_yards": 80, "rushing_tds": 1},
    ]
    scoring = {"rush_yd": 0.1, "rush_td": 6}
    projs = build_weekly_projections(season_stats, [], target_week=5, scoring_settings=scoring)
    assert len(projs) == 1
    assert projs[0]["opponent_team"] == "BYE"
    # Implied fallback is 21.0 (checked via source, not recomputed value to avoid coupling to weights)
    import inspect
    from ffanalytics import stat_projector
    src = inspect.getsource(stat_projector.build_weekly_projections)
    assert "21.0" in src


def test_build_game_context_observed_weather_limitation():
    # Documents pre-game-forecast limitation: schedule temp/wind are observed post-game,
    # not forecasts (see build_game_context docstring). No value change.
    import inspect
    from ffanalytics import stat_projector
    doc = (stat_projector.build_game_context.__doc__ or "")
    assert "OBSERVED" in doc or "observed" in doc
    assert "forecast" in doc.lower()


def test_conformal_bounds_width_is_half_width():
    # Canonical width semantics (pinned 2026-09-09, unified across src/hub):
    # width IS the half-width (qhat scale, same as projection.py) —
    # lower = max(0, point - width), upper = point + width.
    # Guards the 2026-09 regression where compute_conformal_bounds returned
    # full-span (high - low) while projection.py returned half-width, and the
    # hub halved one but not the other.
    b = compute_conformal_bounds(14.2, "WR", residuals=[1.0, 2.0, 3.0, 4.0])
    assert b["lower_bound"] == pytest.approx(max(0.0, 14.2 - b["width"]))
    assert b["upper_bound"] == pytest.approx(14.2 + b["width"])
    assert b["width"] == pytest.approx(b["projection_width"])
    assert b["upper_bound"] - b["lower_bound"] == pytest.approx(2 * b["width"])
    # Floor parity with projection.py: near-zero points clamp at 0, never negative.
    tiny = compute_conformal_bounds(1.0, "K", residuals=[5.0, 6.0, 7.0, 8.0])
    assert tiny["lower_bound"] == pytest.approx(0.0)
    assert tiny["lower_bound"] <= 1.0 <= tiny["upper_bound"]


def test_same_season_week1_uses_no_future_history():
    # why fail-closed: same-season target_week=1 with only weeks>=1 rows
    # present must yield NO players (empty history, nothing to project from),
    # never the old full-reg fallback that silently averaged future weeks as
    # "history". Production preseason never hits this shape (prior season
    # arrives via cross-season/prior params — see next test).
    current = [
        {"player_id": "QB1", "position": "QB", "team": "KC", "week": w,
         "season": 2026, "season_type": "REG",
         "passing_yards": 400.0, "passing_tds": 4, "passing_interceptions": 0,
         "rushing_yards": 10.0, "rushing_tds": 0, "fumbles_lost_total": 0}
        for w in (1, 2, 3)
    ]
    schedule = [{"week": 1, "game_type": "REG", "season": 2026,
                 "home_team": "KC", "away_team": "BUF"}]
    projs = build_weekly_projections(
        current, schedule, target_week=1, scoring_settings={},
    )
    assert projs == []


def test_same_season_week1_falls_back_to_prior_season_stats_param():
    # why (user-caught live bug, 2026-09-10): once MAX_STATS_SEASON tracks
    # the live season (so /props/board's "actual" stat isn't last year's
    # box score), stats_season == schedule season at week 1 — cross_season
    # is False, filtered_prior is empty (no same-season history exists
    # yet), and the OLD code produced zero projections league-wide. This is
    # the real production shape: current == season_stats param (empty at
    # week 1) AND a genuine prior_season_stats param is supplied — must
    # still project, using the prior season as history, not silently empty.
    current = []  # no same-season rows yet — this IS week 1
    prior = [
        {"player_id": "QB1", "position": "QB", "team": "KC", "week": w,
         "season": 2025, "season_type": "REG",
         "passing_yards": 220.0, "passing_tds": 1, "passing_interceptions": 1,
         "rushing_yards": 10.0, "rushing_tds": 0, "fumbles_lost_total": 0}
        for w in range(1, 18)
    ]
    schedule = [{"week": 1, "game_type": "REG", "season": 2026,
                 "home_team": "KC", "away_team": "BUF"}]
    projs = build_weekly_projections(
        current, schedule, target_week=1, scoring_settings={},
        prior_season_stats=prior,
    )
    assert len(projs) == 1
    assert projs[0]["passing_yards"] == pytest.approx(220.0)


def test_preseason_week1_uses_full_prior_season():
    # Production preseason shape: prior-season stats + new-season schedule
    # (disjoint seasons) → full prior REG as history (documented baseline).
    prior = [
        {"player_id": "QB1", "position": "QB", "team": "KC", "week": w,
         "season": 2025, "season_type": "REG",
         "passing_yards": 200.0, "passing_tds": 1, "passing_interceptions": 1,
         "rushing_yards": 10.0, "rushing_tds": 0, "fumbles_lost_total": 0}
        for w in range(1, 18)
    ]
    schedule = [{"week": 1, "game_type": "REG", "season": 2026,
                 "home_team": "KC", "away_team": "BUF"}]
    projs = build_weekly_projections(
        prior, schedule, target_week=1, scoring_settings={},
    )
    assert len(projs) == 1
    # Full-prior baseline: constant 200/yd history, no Vegas/weather in the
    # minimal fixture → fair equals the prior average, not a leak artifact.
    assert projs[0]["passing_yards"] == pytest.approx(200.0)


def test_project_player_stats_is_out_zeroes_but_keeps_flag():
    # why (backtested zero-Out-weekly, 2026-09-10): an Out player's
    # prior-starter average is pure staleness (Darnold 163 yds while Out).
    history = [
        {"passing_yards": 250, "passing_tds": 2, "passing_interceptions": 1, "rushing_yards": 20, "rushing_tds": 0},
        {"passing_yards": 300, "passing_tds": 3, "passing_interceptions": 0, "rushing_yards": 15, "rushing_tds": 0},
        {"passing_yards": 200, "passing_tds": 1, "passing_interceptions": 2, "rushing_yards": 30, "rushing_tds": 1},
    ]
    proj = project_player_stats(history, "QB", is_out=True)
    assert proj["passing_yards"] == 0.0
    assert proj["passing_tds"] == 0.0
    assert proj["rushing_yards"] == 0.0
    # Out is known, not unknown — flag stays False so callers keep showing
    # the row (with its injury badge), just zeroed.
    assert proj["is_empty_projection"] is False
    base = project_player_stats(history, "QB")
    assert base["passing_yards"] > 0  # default off, today's behavior


def test_build_weekly_projections_out_pids_zero_weekly_keep_neutral():
    season_stats = [
        {"player_id": "p1", "player_display_name": "Test QB", "position": "QB", "team": "KC", "week": 1, "season_type": "REG", "passing_yards": 250, "passing_tds": 2},
        {"player_id": "p1", "player_display_name": "Test QB", "position": "QB", "team": "KC", "week": 2, "season_type": "REG", "passing_yards": 300, "passing_tds": 3},
        {"player_id": "p1", "player_display_name": "Test QB", "position": "QB", "team": "KC", "week": 3, "season_type": "REG", "passing_yards": 200, "passing_tds": 1},
    ]
    schedule = [
        {"game_type": "REG", "week": 4, "home_team": "KC", "away_team": "LV", "total_line": 48.0, "spread_line": -7.0, "roof": "outdoors", "temp": 65, "wind": 5}
    ]
    scoring = {"pass_yd": 0.04, "pass_td": 4, "pass_int": -2}
    projs = build_weekly_projections(season_stats, schedule, target_week=4, scoring_settings=scoring, out_pids={"p1"})
    assert len(projs) == 1
    assert projs[0]["projected_points"] == 0.0
    assert projs[0]["passing_yards"] == 0.0
    # season path untouched: a 1-week Out must not nuke ROS/auction value
    assert projs[0]["_neutral_points"] > 0
    projs2 = build_weekly_projections(season_stats, schedule, target_week=4, scoring_settings=scoring)
    assert projs2[0]["projected_points"] > 0  # absent map = today's behavior


def test_xfp_params_off_is_legacy_exact():
    # why: the arms must measure the mechanism, not an approximation — and
    # production callers (which never pass these) must see zero change.
    history = [
        {"receiving_yards": 80, "receptions": 6, "receiving_tds": 1},
        {"receiving_yards": 100, "receptions": 7, "receiving_tds": 0},
        {"receiving_yards": 90, "receptions": 5, "receiving_tds": 1},
    ]
    base = project_player_stats(history, "WR")
    assert project_player_stats(history, "WR", xfp_adjust=None, td_prior=None) == base
    assert project_player_stats(history, "WR", xfp_adjust={}, td_prior={}) == base


def test_xfp_adjust_pulls_base_with_cap():
    history = [
        {"receiving_yards": 100, "receptions": 8, "receiving_tds": 0},
        {"receiving_yards": 100, "receptions": 8, "receiving_tds": 0},
        {"receiving_yards": 100, "receptions": 8, "receiving_tds": 0},
    ]
    # 3 games: no usage trend (>=4 needed), no Vegas/weather by default.
    proj = project_player_stats(history, "WR", xfp_adjust={"receiving_yards": 20.0})
    assert proj["receiving_yards"] == 120.0
    # cap: +-50% of base.
    proj = project_player_stats(history, "WR", xfp_adjust={"receiving_yards": 200.0})
    assert proj["receiving_yards"] == 150.0
    proj = project_player_stats(history, "WR", xfp_adjust={"receiving_yards": -200.0})
    assert proj["receiving_yards"] == 50.0


def test_xfp_adjust_no_pull_from_zero_base():
    history = [
        {"receiving_yards": 0, "receptions": 0, "receiving_tds": 0},
        {"receiving_yards": 0, "receptions": 0, "receiving_tds": 0},
        {"receiving_yards": 0, "receptions": 0, "receiving_tds": 0},
    ]
    proj = project_player_stats(history, "WR", xfp_adjust={"receiving_yards": 50.0})
    assert proj["receiving_yards"] == 0.0


def test_td_prior_replaces_position_mean_at_same_weight():
    # TE receiving_tds mean 0.14 (xFP-recalibrated 2026-09-15): all-zero
    # history -> 0*0.7 + 0.14*0.3. Override swaps the prior, weight stays.
    history = [
        {"receiving_yards": 40, "receptions": 4, "receiving_tds": 0},
        {"receiving_yards": 40, "receptions": 4, "receiving_tds": 0},
        {"receiving_yards": 40, "receptions": 4, "receiving_tds": 0},
    ]
    base = project_player_stats(history, "TE")
    assert abs(base["receiving_tds"] - 0.14 * 0.30) < 1e-9
    prior = project_player_stats(history, "TE", td_prior={"receiving_tds": 0.5})
    assert abs(prior["receiving_tds"] - 0.5 * 0.30) < 1e-9


def test_td_priors_recalibrated_to_xfp_levels():
    # why (opportunity-td-priors spec, user-confirmed 2026-09-15): the old
    # flat means sat far above xFP-implied scoring rates (systematic
    # over-projection). Hand-computed pins — not backtest-derived.
    # TE all-zero receiving_tds: 0*0.7 + 0.14*0.3.
    hist_te = [
        {"receiving_yards": 40, "receptions": 4, "receiving_tds": 0},
        {"receiving_yards": 40, "receptions": 4, "receiving_tds": 0},
        {"receiving_yards": 40, "receptions": 4, "receiving_tds": 0},
    ]
    assert abs(project_player_stats(hist_te, "TE")["receiving_tds"] - 0.042) < 1e-9
    # RB rushing_tds [1,0,0]: avg 1/3, 0.3333*0.7 + 0.20*0.3.
    hist_rb = [
        {"carries": 10, "rushing_yards": 50, "rushing_tds": 1, "receiving_yards": 10, "receptions": 1, "receiving_tds": 0},
        {"carries": 10, "rushing_yards": 50, "rushing_tds": 0, "receiving_yards": 10, "receptions": 1, "receiving_tds": 0},
        {"carries": 10, "rushing_yards": 50, "rushing_tds": 0, "receiving_yards": 10, "receptions": 1, "receiving_tds": 0},
    ]
    assert abs(project_player_stats(hist_rb, "RB")["rushing_tds"] - (1 / 3 * 0.7 + 0.20 * 0.3)) < 1e-9
    # WR all-zero receiving_tds: 0*0.7 + 0.18*0.3.
    hist_wr = [
        {"receiving_yards": 60, "receptions": 5, "receiving_tds": 0},
        {"receiving_yards": 60, "receptions": 5, "receiving_tds": 0},
        {"receiving_yards": 60, "receptions": 5, "receiving_tds": 0},
    ]
    assert abs(project_player_stats(hist_wr, "WR")["receiving_tds"] - 0.054) < 1e-9
    # QB untouched: all-zero passing_tds still regresses to the old 1.7.
    hist_qb = [
        {"passing_yards": 200, "passing_tds": 0, "passing_interceptions": 0, "rushing_yards": 10, "rushing_tds": 0},
        {"passing_yards": 200, "passing_tds": 0, "passing_interceptions": 0, "rushing_yards": 10, "rushing_tds": 0},
        {"passing_yards": 200, "passing_tds": 0, "passing_interceptions": 0, "rushing_yards": 10, "rushing_tds": 0},
    ]
    assert abs(project_player_stats(hist_qb, "QB")["passing_tds"] - 1.7 * 0.3) < 1e-9
