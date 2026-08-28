from ffanalytics.scoring import (
    calculate_fantasy_points,
    apply_flex_adjustment,
    count_flex_slots,
    DEFAULT_SCORING,
)


def test_calculate_fantasy_points_default_ppr():
    stats = {
        "receptions": 5,
        "receiving_yards": 80,
        "receiving_tds": 1,
    }
    points = calculate_fantasy_points(stats)
    # 5 * 1.0 + 80 * 0.1 + 1 * 6.0 = 5 + 8 + 6 = 19.0
    assert points == 19.0


def test_calculate_fantasy_points_custom_scoring():
    stats = {"receptions": 5, "receiving_yards": 80}
    custom = {"rec": 0.5, "rec_yd": 0.1}  # half-PPR
    points = calculate_fantasy_points(stats, scoring_settings=custom)
    # 5 * 0.5 + 80 * 0.1 = 2.5 + 8 = 10.5
    assert points == 10.5


def test_flex_adjustment_applied_to_eligible():
    points = apply_flex_adjustment(10.0, "RB", num_flex_slots=2)
    assert points > 10.0  # should get scarcity bonus


def test_flex_adjustment_not_applied_to_qb():
    points = apply_flex_adjustment(10.0, "QB", num_flex_slots=2)
    assert points == 10.0  # QB not flex-eligible


def test_flex_adjustment_not_applied_single_flex():
    points = apply_flex_adjustment(10.0, "RB", num_flex_slots=1)
    assert points == 10.0  # standard league, no bonus


def test_count_flex_slots():
    roster = ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "FLEX", "K", "DEF"]
    assert count_flex_slots(roster) == 2
