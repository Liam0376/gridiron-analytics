"""Elo/Glicko-style rating with explicit uncertainty (deviation) and
time-decay — adapted from the DISCIPLINE of ~/projects/sports-analytics'
core/elo.py, not its code (that file's math is tennis-serve-specific).
Used for both whole-team strength and per-(team, position_group) matchup
strength — same math, different granularity of what "a game" means for
the position-group track (see design spec).

NOTE: positional ratings (vs_QB/RB/WR/TE) are maintained for research but
are NOT wired into the production stat projection path.
tested and REJECTED — evidence: stat_projector.py:22-24 opponent defense
factors hurt correlation even with shrinkage. Constants below are frozen;
do not tune without an honest OOS backtest."""

from dataclasses import dataclass

@dataclass(frozen=True)
class Rating:
    value: float
    deviation: float

DEFAULT_RATING = Rating(1500.0, 350.0)

_Q = 0.0057565  # ln(10)/400, standard Glicko constant
_MIN_DEVIATION = 50.0
_MAX_DEVIATION = 350.0
_INACTIVITY_GROWTH_PER_WEEK = 15.0  # tuned in shadow mode once real data exists


def _expected_score(a: Rating, b: Rating) -> float:
    return 1.0 / (1.0 + 10 ** ((b.value - a.value) / 400.0))


def update(current: Rating, opponent: Rating, score: float, k_factor: float) -> Rating:
    expected = _expected_score(current, opponent)
    new_value = current.value + k_factor * (score - expected)
    # deviation shrinks toward the floor as more games accumulate
    new_deviation = max(_MIN_DEVIATION, current.deviation * 0.9)
    return Rating(new_value, new_deviation)


def decay_for_inactivity(current: Rating, weeks_since_last_game: int) -> Rating:
    grown = current.deviation + _INACTIVITY_GROWTH_PER_WEEK * weeks_since_last_game
    return Rating(current.value, min(_MAX_DEVIATION, grown))