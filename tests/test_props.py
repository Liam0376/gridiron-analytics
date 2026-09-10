import math

import pytest
from ffanalytics.props import (
    american_to_prob,
    band_coverage,
    base_rate_brier,
    bins_monotonic,
    brier_score,
    build_prop_fair_lines,
    fair_mae,
    normal_over_prob,
    pit_deciles,
    pit_value,
    poisson_anytime_td,
    reliability_bins,
    verdict_normal_market,
    verdict_td_market,
)


def _qb_history(n=5, base_yards=250.0):
    return [
        {"passing_yards": base_yards + (i % 2) * 20.0, "passing_tds": 2,
         "rushing_yards": 15.0 + i, "rushing_tds": 0, "season_type": "REG"}
        for i in range(n)
    ]


def _wr_history(n=5):
    return [
        {"receiving_yards": 60.0 + (i % 3) * 15.0, "receiving_tds": i % 2,
         "receptions": 4 + (i % 2), "rushing_yards": 0.0, "rushing_tds": 0,
         "season_type": "REG"}
        for i in range(n)
    ]


def test_american_known_values():
    assert american_to_prob(-110) == pytest.approx(110 / 210)
    assert american_to_prob(100) == pytest.approx(0.5)
    assert american_to_prob(-150) == pytest.approx(0.6)
    assert american_to_prob(200) == pytest.approx(100 / 300)


def test_american_zero_price_raises():
    with pytest.raises(ValueError, match="price"):
        american_to_prob(0)


def test_poisson_anytime_td():
    assert poisson_anytime_td(0.0) == pytest.approx(0.0)
    assert poisson_anytime_td(1.0) == pytest.approx(1 - math.exp(-1))
    assert poisson_anytime_td(0.5) == pytest.approx(1 - math.exp(-0.5))
    # TD means can't be negative — clamp to 0, don't blow up exp().
    assert poisson_anytime_td(-0.3) == pytest.approx(0.0)
    with pytest.raises(ValueError, match="[Ll]ambda|mean"):
        poisson_anytime_td(float("nan"))


def test_normal_over_prob_at_line_is_half():
    assert normal_over_prob(250.5, 30.0, 250.5) == pytest.approx(0.5)


def test_normal_over_prob_monotonic_and_sane():
    mean, sigma = 250.5, 30.0
    assert normal_over_prob(mean, sigma, mean - sigma) > 0.8
    assert normal_over_prob(mean, sigma, mean + sigma) < 0.2
    assert normal_over_prob(mean, sigma, mean - 100) > normal_over_prob(mean, sigma, mean)
    # Huge sigma -> coin flip.
    assert normal_over_prob(mean, 1e6, mean + 10) == pytest.approx(0.5, abs=1e-3)


def test_normal_over_prob_degenerate_sigma_is_step():
    assert normal_over_prob(100.0, 0.0, 90.0) == pytest.approx(1.0)
    assert normal_over_prob(100.0, 0.0, 110.0) == pytest.approx(0.0)
    assert normal_over_prob(100.0, 0.0, 100.0) == pytest.approx(0.5)
    with pytest.raises(ValueError, match="sigma|mean|line"):
        normal_over_prob(float("nan"), 10.0, 100.0)


def test_fair_lines_qb_markets_match_projector():
    from ffanalytics.stat_projector import project_player_stats

    hist = _qb_history()
    out = build_prop_fair_lines(hist, "QB", {"implied_total": 24.0}, week=5)
    assert out["excluded"] is False
    assert out["is_empty_projection"] is False
    assert {"passing_yards", "passing_tds", "rushing_yards", "anytime_td"} <= set(out["markets"])
    # Fair line must equal the projector's own output for that stat key.
    proj = project_player_stats(hist, "QB", implied_total=24.0)
    assert out["markets"]["passing_yards"]["fair_line"] == pytest.approx(proj["passing_yards"])
    assert out["markets"]["passing_tds"]["fair_line"] == pytest.approx(proj["passing_tds"])


def test_fair_lines_wr_markets():
    out = build_prop_fair_lines(_wr_history(), "WR", {"implied_total": 22.0}, week=5)
    assert out["excluded"] is False
    assert {"receiving_yards", "receptions", "anytime_td"} <= set(out["markets"])
    assert out["markets"]["receiving_yards"]["fair_line"] > 0
    assert out["markets"]["anytime_td"]["p_yes"] == pytest.approx(
        1 - math.exp(-out["markets"]["anytime_td"]["fair_line"])
    )


def test_fair_lines_sigma_floor_and_dispersion():
    stable = build_prop_fair_lines(_qb_history(base_yards=250.0), "QB", {}, week=5)
    volatile_hist = [dict(g, passing_yards=150.0 + (i % 2) * 200.0) for i, g in enumerate(_qb_history())]
    volatile = build_prop_fair_lines(volatile_hist, "QB", {}, week=5)
    s_stable = stable["markets"]["passing_yards"]["sigma"]
    s_vol = volatile["markets"]["passing_yards"]["sigma"]
    assert s_stable > 0 and s_vol > 0
    assert s_vol > s_stable  # dispersion must flow into sigma
    # Floor: zero-variance history still yields a usable (non-degenerate) sigma.
    flat_hist_zero_var = [dict(g, passing_yards=200.0) for g in _qb_history()]
    flat = build_prop_fair_lines(flat_hist_zero_var, "QB", {}, week=5)
    assert flat["markets"]["passing_yards"]["sigma"] > 0


def test_fair_lines_empty_history_flagged_not_silent():
    out = build_prop_fair_lines([], "WR", {}, week=5)
    assert out["excluded"] is False
    assert out["is_empty_projection"] is True
    assert out["markets"]["receiving_yards"]["fair_line"] == pytest.approx(0.0)


def test_fair_lines_week1_supported_via_prior():
    # why no exclusion: week 1 runs on the prior-season baseline by
    # construction (preseason refresh loads the prior season; same-season
    # history filter is fail-closed). Vetoing it blocked the legitimate case.
    prior = [
        {"passing_yards": 250.0, "passing_tds": 2, "season_type": "REG"}
        for _ in range(5)
    ]
    out = build_prop_fair_lines([], "QB", {}, prior_season_stats=prior, week=1)
    assert out["excluded"] is False
    assert out["markets"]["passing_yards"]["fair_line"] == pytest.approx(250.0)


def test_fair_lines_kicker_excluded_v1():
    out = build_prop_fair_lines(_qb_history(), "K", {}, week=5)
    assert out["excluded"] is True
    assert out["markets"] == {}


def test_fair_lines_deterministic():
    a = build_prop_fair_lines(_wr_history(), "WR", {"implied_total": 22.0}, week=5)
    b = build_prop_fair_lines(_wr_history(), "WR", {"implied_total": 22.0}, week=5)
    assert a == b


def test_pit_value_symmetric_and_ordered():
    assert pit_value(100.0, 100.0, 15.0) == pytest.approx(0.5)
    assert pit_value(115.0, 100.0, 15.0) == pytest.approx(1 - pit_value(85.0, 100.0, 15.0))
    assert pit_value(200.0, 100.0, 15.0) > 0.99
    assert pit_value(0.0, 100.0, 15.0) < 0.01
    with pytest.raises(ValueError, match="sigma"):
        pit_value(100.0, 100.0, 0.0)
    with pytest.raises(ValueError, match="finite|number"):
        pit_value(float("nan"), 100.0, 15.0)


def test_band_coverage_constructed():
    # 3 of 4 inside the 80% band (band half-width 12.816 at sigma=10).
    obs = [(100.0, 10.0, 105.0), (100.0, 10.0, 95.0), (100.0, 10.0, 100.0),
           (100.0, 10.0, 200.0)]
    assert band_coverage(obs) == pytest.approx(0.75)
    assert band_coverage([]) is None
    assert fair_mae(obs) == pytest.approx((5 + 5 + 0 + 100) / 4)


def test_pit_deciles_seeded_gaussian_near_uniform():
    import random

    rng = random.Random(0)
    obs = [(100.0, 15.0, rng.gauss(100.0, 15.0)) for _ in range(5000)]
    res = pit_deciles(obs)
    assert res["max_dev"] < 0.03
    assert abs(band_coverage(obs) - 0.80) < 0.03


def test_brier_known_values():
    assert brier_score([(1.0, 1), (0.0, 0)]) == pytest.approx(0.0)
    assert brier_score([(0.5, 1), (0.5, 0)]) == pytest.approx(0.25)
    assert brier_score([]) is None
    # Base rate 0.5 naive => 0.25; a perfect model beats it.
    assert base_rate_brier([1, 0, 1, 0]) == pytest.approx(0.25)
    assert brier_score([(0.9, 1), (0.1, 0), (0.8, 1), (0.2, 0)]) < base_rate_brier([1, 0, 1, 0])


def test_reliability_bins_shape_and_monotonic():
    pairs = [(0.1, 0), (0.2, 0), (0.3, 0), (0.4, 1), (0.5, 0),
             (0.6, 1), (0.7, 1), (0.8, 1), (0.9, 1), (0.95, 1)]
    bins = reliability_bins(pairs, k=5)
    assert len(bins) == 5
    assert all(b["n"] == 2 for b in bins)
    assert bins_monotonic(bins) is True
    assert bins_monotonic(list(reversed(bins))) is False
    assert reliability_bins([], k=5) == []
    assert bins_monotonic([]) is False


def test_verdict_normal_market_gates():
    assert verdict_normal_market(600, 0.81, 0.03) == "edges_on"
    assert verdict_normal_market(499, 0.81, 0.03) == "tracking"   # small n
    assert verdict_normal_market(600, 0.70, 0.03) == "tracking"   # bad coverage
    assert verdict_normal_market(600, 0.81, 0.06) == "tracking"   # bad PIT
    assert verdict_normal_market(600, None, 0.03) == "tracking"   # missing


def test_verdict_td_market_gates():
    assert verdict_td_market(600, 0.18, 0.23, True) == "edges_on"
    assert verdict_td_market(499, 0.18, 0.23, True) == "tracking"
    assert verdict_td_market(600, 0.24, 0.23, True) == "tracking"  # loses to naive
    assert verdict_td_market(600, 0.18, 0.23, False) == "tracking"  # non-monotonic
