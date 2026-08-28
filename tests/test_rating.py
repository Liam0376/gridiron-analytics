from ffanalytics.rating import Rating, DEFAULT_RATING, update, decay_for_inactivity

def test_default_rating_values():
    assert DEFAULT_RATING.value == 1500.0
    assert DEFAULT_RATING.deviation == 350.0

def test_update_winner_rating_increases():
    r = update(DEFAULT_RATING, DEFAULT_RATING, score=1.0, k_factor=32.0)
    assert r.value > DEFAULT_RATING.value

def test_update_loser_rating_decreases():
    r = update(DEFAULT_RATING, DEFAULT_RATING, score=0.0, k_factor=32.0)
    assert r.value < DEFAULT_RATING.value

def test_update_shrinks_deviation():
    r = update(DEFAULT_RATING, DEFAULT_RATING, score=1.0, k_factor=32.0)
    assert r.deviation < DEFAULT_RATING.deviation

def test_decay_for_inactivity_grows_deviation_with_weeks():
    settled = update(DEFAULT_RATING, DEFAULT_RATING, score=1.0, k_factor=32.0)
    decayed_1wk = decay_for_inactivity(settled, weeks_since_last_game=1)
    decayed_4wk = decay_for_inactivity(settled, weeks_since_last_game=4)
    assert decayed_1wk.deviation > settled.deviation
    assert decayed_4wk.deviation > decayed_1wk.deviation

def test_decay_never_exceeds_default_deviation():
    settled = update(DEFAULT_RATING, DEFAULT_RATING, score=1.0, k_factor=32.0)
    decayed = decay_for_inactivity(settled, weeks_since_last_game=100)
    assert decayed.deviation <= DEFAULT_RATING.deviation