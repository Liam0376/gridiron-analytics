"""League-specific scoring calculator. Applies the actual Sleeper scoring
settings (fetched by refresh job) instead of hardcoded PPR assumptions."""

# Default scoring mirrors Sleeper "Fantasy Bahamas" (1397736035240173568) as of 2026-08-28.
# PPR rec=1.0, yardage 0.1/0.04, TD 5/6, plus Sleeper 40+ bonuses at 1.0 (not 2.0 as in early backtests).
# Full live truth is fetched via sleeper.get_league_settings() — this fallback is only for cold starts/tests.
DEFAULT_SCORING = {
    "rec": 1.0, "rec_yd": 0.1, "rush_yd": 0.1, "pass_yd": 0.04,
    "pass_td": 5.0, "rush_td": 6.0, "rec_td": 6.0, "pass_int": -1.0,
    # 40+ yard play bonuses (Sleeper = 1.0 each; early backtests used 2.0)
    "pass_cmp_40p": 1.0, "rush_40p": 1.0, "rec_40p": 1.0,
    "pass_td_40p": 1.0, "rush_td_40p": 1.0, "rec_td_40p": 1.0,
    # Kicking / misc (subset of Sleeper — DEF/ST scoring handled separately by Sleeper)
    "fgm_0_19": 3.0, "fgm_20_29": 3.0, "fgm_30_39": 3.0, "fgm_40_49": 4.0, "fgm_50_59": 5.0, "fgm_60p": 6.0,
    "fgmiss": -1.0, "fgmiss_0_19": -1.0, "fgmiss_20_29": -1.0,
    "xpm": 1.0, "xpmiss": -1.0,
    "fum_lost": -2.0, "fum_rec": 2.0, "fum_rec_td": 6.0, "ff": 1.0,
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
        # Core scoring
        "receptions": "rec",
        "receiving_yards": "rec_yd",
        "rushing_yards": "rush_yd",
        "passing_yards": "pass_yd",
        "passing_tds": "pass_td",
        "rushing_tds": "rush_td",
        "receiving_tds": "rec_td",
        "interceptions": "pass_int",
        "fumbles_lost": "fum_lost",
        # 2pt conversions
        "passing_2pt": "pass_2pt",
        "rushing_2pt": "rush_2pt",
        "receiving_2pt": "rec_2pt",
        # 40+ yard play bonuses (Sleeper: pass_cmp_40p, rush_40p, rec_40p at 1.0)
        "passing_40": "pass_cmp_40p",
        "rushing_40": "rush_40p",
        "receiving_40": "rec_40p",
        # 40+ TD bonuses (if source stats provide them; 0 if missing — settings.get defaults to 0)
        "passing_td_40": "pass_td_40p",
        "rushing_td_40": "rush_td_40p",
        "receiving_td_40": "rec_td_40p",
        # Kicking
        "fg_made_0_19": "fgm_0_19",
        "fg_made_20_29": "fgm_20_29",
        "fg_made_30_39": "fgm_30_39",
        "fg_made_40_49": "fgm_40_49",
        "fg_made_50_59": "fgm_50_59",
        "fg_made_60_": "fgm_60p",
        "fg_missed": "fgmiss",
        "pat_made": "xpm",
        "pat_missed": "xpmiss",
        "fumble_recovery": "fum_rec",
        "fumble_recovery_td": "fum_rec_td",
        "forced_fumble": "ff",
    }

    points = 0.0
    for stat_key, scoring_key in stat_to_scoring_key.items():
        stat_value = stats.get(stat_key, 0) or 0
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


# Alias for backwards compat / spec reference: SCORING == DEFAULT_SCORING
SCORING = DEFAULT_SCORING
