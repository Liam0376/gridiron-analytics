"""League-specific scoring calculator. Applies the actual Sleeper scoring
settings (fetched by refresh job) instead of hardcoded PPR assumptions."""

# Default standard PPR scoring (fallback if no settings loaded)
DEFAULT_SCORING = {
    "rec": 1.0, "rec_yd": 0.1, "rush_yd": 0.1, "pass_yd": 0.04,
    "pass_td": 5.0, "rush_td": 6.0, "rec_td": 6.0, "pass_int": -1.0,
}

# 2-flex league scarcity adjustment: RB/WR/TE flex-eligible players are
# more valuable because more starters compete for them
FLEX_ELIGIBLE_POSITIONS = {"RB", "WR", "TE"}
FLEX_SCARCITY_MULTIPLIER = 1.05  # 5% uplift for flex-eligible in 2+ flex leagues


def calculate_fantasy_points(stats: dict, scoring_settings: dict | None = None) -> float:
    """Calculate fantasy points from raw stats using league scoring settings.

    stats keys map to Sleeper scoring setting keys:
    - receptions -> rec
    - receiving_yards -> rec_yd
    - rushing_yards -> rush_yd
    - passing_yards -> pass_yd
    - passing_tds -> pass_td
    - rushing_tds -> rush_td
    - receiving_tds -> rec_td
    - interceptions -> pass_int
    """
    settings = scoring_settings or DEFAULT_SCORING

    stat_to_scoring_key = {
        "receptions": "rec",
        "receiving_yards": "rec_yd",
        "rushing_yards": "rush_yd",
        "passing_yards": "pass_yd",
        "passing_tds": "pass_td",
        "rushing_tds": "rush_td",
        "receiving_tds": "rec_td",
        "interceptions": "pass_int",
    }

    points = 0.0
    for stat_key, scoring_key in stat_to_scoring_key.items():
        stat_value = stats.get(stat_key, 0)
        multiplier = settings.get(scoring_key, 0)
        points += stat_value * multiplier

    return points


def apply_flex_adjustment(points: float, position: str, num_flex_slots: int = 2) -> float:
    """Apply scarcity adjustment for leagues with extra flex slots.
    More flex slots = more demand for RB/WR/TE = higher relative value."""
    if position in FLEX_ELIGIBLE_POSITIONS and num_flex_slots >= 2:
        extra_flex = num_flex_slots - 1  # standard is 1 flex
        adjustment = 1.0 + (FLEX_SCARCITY_MULTIPLIER - 1.0) * extra_flex
        return points * adjustment
    return points


def count_flex_slots(roster_positions: list[str]) -> int:
    """Count flex slots from Sleeper roster positions list."""
    return sum(1 for pos in roster_positions if pos == "FLEX")
