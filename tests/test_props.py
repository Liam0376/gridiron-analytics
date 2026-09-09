import math

import pytest
from ffanalytics.props import (
    american_to_prob,
    apply_prop_edge_rule,
    ev_per_unit,
    normal_over_prob,
    poisson_anytime_td,
    prob_to_american,
)


def test_american_known_values():
    assert american_to_prob(-110) == pytest.approx(110 / 210)
    assert american_to_prob(100) == pytest.approx(0.5)
    assert american_to_prob(-150) == pytest.approx(0.6)
    assert american_to_prob(200) == pytest.approx(100 / 300)


def test_american_zero_price_raises():
    with pytest.raises(ValueError, match="price"):
        american_to_prob(0)


def test_prob_to_american_known_values():
    assert prob_to_american(0.5) == 100
    assert prob_to_american(0.6) == pytest.approx(-150)
    assert prob_to_american(0.75) == pytest.approx(-300)
    assert prob_to_american(1 / 3) == pytest.approx(200)
    assert prob_to_american(0.25) == 300


def test_prob_to_american_bounds_raise():
    for bad in (0.0, 1.0, -0.1, 1.1, float("nan")):
        with pytest.raises(ValueError, match="[Pp]rob"):
            prob_to_american(bad)


def test_fair_odds_round_trip():
    # american -> prob -> american must be identity (no vig either side).
    for price in (-10000, -500, -150, -110, -100, 100, 110, 150, 500, 10000):
        # +-100 are the same price (even money) — normalize before comparing.
        expected = 100 if abs(price) == 100 else price
        assert prob_to_american(american_to_prob(price)) == pytest.approx(expected, rel=1e-9)
    for p in (0.05, 0.2, 0.4, 0.5001, 0.6, 0.8, 0.95):
        assert american_to_prob(prob_to_american(p)) == pytest.approx(p, rel=1e-9)


def test_ev_negative_vig_both_sides():
    # -110 both sides at true p=0.5 loses the vig: EV = 0.5*(100/110) - 0.5 < 0.
    ev = ev_per_unit(0.5, -110)
    assert ev == pytest.approx(0.5 * (100 / 110) - 0.5)
    assert ev < 0


def test_ev_positive_edge_case():
    # p=0.6 model vs -110 book over: EV = 0.6*0.9091 - 0.4 > 0.
    assert ev_per_unit(0.6, -110) == pytest.approx(0.6 * (100 / 110) - 0.4)
    assert ev_per_unit(0.6, -110) > 0
    # Plus-money: p=0.4 at +150 pays 1.5.
    assert ev_per_unit(0.4, 150) == pytest.approx(0.4 * 1.5 - 0.6)


def test_ev_bad_inputs_raise():
    with pytest.raises(ValueError, match="[Pp]rob"):
        ev_per_unit(1.5, -110)
    with pytest.raises(ValueError, match="price"):
        ev_per_unit(0.5, 0)


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


def test_edge_rule_value_at_boundary():
    # Exactly 5pp edge + EV>=4%: book -110 (implied 0.5238), model 0.5738.
    res = apply_prop_edge_rule(p_model=110 / 210 + 0.05, book_price=-110)
    assert res["decision"] == "VALUE"
    assert res["edge_pp"] == pytest.approx(0.05)
    assert res["ev_per_unit"] >= 0.04


def test_edge_rule_no_edge_below_threshold():
    # 2pp edge only -> NO EDGE even though EV>0.
    res = apply_prop_edge_rule(p_model=110 / 210 + 0.02, book_price=-110)
    assert res["decision"] == "NO EDGE"
    # EV floor vetoes independently: same 7.6pp edge, but ev_min raised above
    # actual EV (0.6*0.9091-0.4 = 0.145) -> NO EDGE.
    res = apply_prop_edge_rule(p_model=0.60, book_price=-110, ev_min=0.20)
    assert res["edge_pp"] == pytest.approx(0.60 - 110 / 210)
    assert res["ev_per_unit"] == pytest.approx(0.145, abs=1e-3)
    assert res["decision"] == "NO EDGE"


def test_edge_rule_empty_projection_veto():
    # Unknown (rookie/no history) can never be VALUE, however big the gap.
    res = apply_prop_edge_rule(p_model=0.80, book_price=-110, is_empty=True)
    assert res["decision"] == "NO EDGE (unknown)"
    assert res["edge_pp"] == pytest.approx(0.80 - 110 / 210)
