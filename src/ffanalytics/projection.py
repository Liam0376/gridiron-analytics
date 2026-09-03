"""Projection engine: converts raw player stats into point projections
using features, ratings, and heuristic intervals (conformal-informed)."""

import warnings
from typing import Dict, List, Optional
from ffanalytics import config
from ffanalytics.rating import Rating, update, decay_for_inactivity
from ffanalytics.conformal import interval, qhat
from ffanalytics.scoring import calculate_fantasy_points, apply_flex_adjustment, count_flex_slots
import math

# Opponent-rating adjustment gate — default OFF.
# tested and REJECTED — evidence: stat_projector.py:22-24 opponent defense
# factors hurt correlation (0.690→0.687) even with multi-season shrinkage;
# defense rankings don't persist year-to-year (Spearman rho=0.05-0.34).
# Kept behind this flag for research only; production path leaves it OFF.
ENABLE_OPPONENT_RATING = False


def calculate_target_share_feature(stats: Dict) -> float:
    targets = stats.get("targets", 0)
    receptions = stats.get("receptions", 0)
    # Simple approximation - in reality would need more sophisticated calculation
    if targets > 0:
        return receptions / targets
    return 0.0


def calculate_snap_pct_feature(stats: Dict) -> float:
    snaps = stats.get("snaps", 0)
    return min(snaps / 100.0, 1.0)


def calculate_opponent_positional_rating_feature(
    team_ratings: Dict[str, Dict[str, Rating]],
    opponent_team: str,
    position_group: str
) -> float:
    if not opponent_team or opponent_team not in team_ratings:
        return 1500.0

    position_key = f"vs_{position_group}"
    if position_key in team_ratings[opponent_team]:
        return team_ratings[opponent_team][position_key].value
    elif "overall" in team_ratings[opponent_team]:
        return team_ratings[opponent_team]["overall"].value
    else:
        return 1500.0


def calculate_projection(
    player_stats: Dict,
    team_ratings: Dict[str, Dict[str, Rating]],
    historical_residuals: List[float] = None,
    feature_weights: Dict[str, float] = None,
    weather: Dict = None,
    scoring_settings: Dict = None,
    use_features: bool = True,
) -> Dict[str, float]:
    """Score stats into projected points.

    use_features=True is for retroactive scoring of ACTUAL game stats only
    (targets/snaps/opponent from the same game just played; MAE≈0.98 on
    actuals). use_features=False is for real predictions on PROJECTED stats
    (stat_projector output) — feature adjustments are off because they were
    tested and add bias when applied to projected (not actual) stats.

    LEAKAGE GUARD: do not call with use_features=True on projected stats.
    Projected inputs lack actuals (targets/snaps/attempts); if detected below
    a warning is emitted and adjustments should be treated as invalid.
    """
    # use_features=True → retroactive scoring of actual stats (MAE≈0.98).
    # use_features=False → real predictions on projected stats; feature
    # adjustments are off (tested and REJECTED — add bias on projected stats).
    # assert: use_features=True requires actual-game keys (targets/snaps/etc.);
    # projected-stat dicts (stat_projector output) must use use_features=False.
    if use_features and (
        "targets" not in player_stats
        and "snaps" not in player_stats
        and "attempts" not in player_stats
        and "pass_attempts" not in player_stats
    ):
        warnings.warn(
            "use_features=True called without actual-game keys "
            "(targets/snaps/attempts missing) — likely projected stats; "
            "feature adjustments add bias on projected inputs, "
            "use use_features=False for predictions",
            UserWarning,
            stacklevel=2,
        )
    if feature_weights is None:
        feature_weights = {
            "target_share": 0.4,
            "snap_pct": 0.3,
            "opponent_positional_rating": 0.3
        }

    def _s(short, nflverse):
        return player_stats.get(short, 0) or player_stats.get(nflverse, 0) or 0

    scoring_stats = {
        "passing_yards": _s("pass_yd", "passing_yards"),
        "passing_tds": _s("pass_td", "passing_tds"),
        "interceptions": _s("pass_int", "passing_interceptions"),
        "rushing_yards": _s("rush_yd", "rushing_yards"),
        "rushing_tds": _s("rush_td", "rushing_tds"),
        "receiving_yards": _s("rec_yd", "receiving_yards"),
        "receiving_tds": _s("rec_td", "receiving_tds"),
        "receptions": player_stats.get("receptions", 0) or 0,
        "fumbles_lost": _s("fum_lost", "fumbles_lost_total"),
        "passing_2pt": _s("pass_2pt", "passing_2pt_conversions"),
        "rushing_2pt": _s("rush_2pt", "rushing_2pt_conversions"),
        "receiving_2pt": _s("rec_2pt", "receiving_2pt_conversions"),
        "passing_40": _s("pass_40", "passing_40"),
        "rushing_40": _s("rush_40", "rushing_40"),
        "receiving_40": _s("rec_40", "receiving_40"),
        "fg_made_0_19": player_stats.get("fg_made_0_19", 0) or 0,
        "fg_made_20_29": player_stats.get("fg_made_20_29", 0) or 0,
        "fg_made_30_39": player_stats.get("fg_made_30_39", 0) or 0,
        "fg_made_40_49": player_stats.get("fg_made_40_49", 0) or 0,
        "fg_made_50_59": player_stats.get("fg_made_50_59", 0) or 0,
        "fg_made_60_": player_stats.get("fg_made_60_", 0) or 0,
        "fg_missed": player_stats.get("fg_missed", 0) or 0,
        "pat_made": player_stats.get("pat_made", 0) or 0,
        "pat_missed": player_stats.get("pat_missed", 0) or 0,
        "fumble_recovery": (player_stats.get("fumble_recovery_opp", 0) or 0)
                         + (player_stats.get("fumble_recovery_own", 0) or 0),
        "fumble_recovery_td": player_stats.get("fumble_recovery_tds", 0) or 0,
        "forced_fumble": player_stats.get("def_fumbles_forced", 0) or 0,
    }
    base_points = calculate_fantasy_points(scoring_stats, scoring_settings)

    feature_adjustment = 0.0

    if use_features:
        target_share = calculate_target_share_feature(player_stats)
        snap_pct = calculate_snap_pct_feature(player_stats)
        opponent_team = player_stats.get("opponent_team")
        position_group = player_stats.get("position_group", "rb")
        opponent_rating = calculate_opponent_positional_rating_feature(
            team_ratings, opponent_team or "", position_group
        )
        pos_upper = position_group.upper()

        if pos_upper == "QB":
            attempts = player_stats.get("attempts", 0) or player_stats.get("pass_attempts", 0) or 0
            completions = player_stats.get("completions", 0) or 0
            sacks = player_stats.get("sacks_suffered", 0) or player_stats.get("sacks", 0) or 0
            pass_yards = player_stats.get("pass_yd", 0) or player_stats.get("passing_yards", 0) or 0
            if attempts and attempts > 0:
                cmp_pct = completions / attempts
                ypa = pass_yards / attempts
                dropbacks = attempts + (sacks or 0)
                sack_rate = (sacks or 0) / dropbacks if dropbacks > 0 else 0
                feature_adjustment += 0.3 * (cmp_pct - 0.646) * 15
                feature_adjustment += 0.4 * (ypa - 7.09) * 2
                feature_adjustment += 0.3 * (0.070 - sack_rate) * 20
        else:
            cr_center = {"RB": 0.827, "WR": 0.668, "TE": 0.749}.get(pos_upper, 0.700)
            feature_adjustment += feature_weights["target_share"] * (target_share - cr_center) * 10
            if snap_pct > 0:
                feature_adjustment += feature_weights["snap_pct"] * (snap_pct - 0.6) * 8

        # Opponent-rating term gated OFF by default (see ENABLE_OPPONENT_RATING).
        # tested and REJECTED — evidence: stat_projector.py:22-24, opponent
        # defense factors hurt correlation even with shrinkage; do not enable
        # in production without re-running honest OOS backtest.
        if ENABLE_OPPONENT_RATING:
            feature_adjustment += feature_weights["opponent_positional_rating"] * ((opponent_rating - 1500) / 100)

    point_estimate = base_points + feature_adjustment

    # Weather adjustment: high wind penalizes passing/kicking positions (audit I6: include TE)
    if weather and position_group.upper() in ("QB", "WR", "TE", "K"):
        wind_mph = weather.get("wind_mph", 0)
        if wind_mph and wind_mph > 15:
            point_estimate -= (wind_mph - 15) * config.WEATHER_WIND_PENALTY_PER_MPH

    # Flex scarcity: 2+ flex slots make RB/WR/TE more valuable
    roster_positions = (scoring_settings or {}).get("_roster_positions")
    if roster_positions:
        num_flex = count_flex_slots(roster_positions)
        point_estimate = apply_flex_adjustment(point_estimate, position_group.upper(), num_flex)

    # Interval width: conformal qhat base scaled by position and point magnitude.
    # Scaling breaks the formal coverage guarantee from Vovk et al. — these are
    # heuristic intervals informed by conformal prediction, not calibrated ones.
    # Position factors derived from per-pos MAE / overall 4.16 (QB 1.45, RB/WR 1.07, TE 0.87, K 0.55)
    # Point factor captures blow-up tail: stars projected 25-30 pts have fat tails (MAE top5 8.53 vs 4.16)
    def _pos_width_factor(pos: str) -> float:
        m = {"QB": 1.45, "RB": 1.07, "WR": 1.12, "TE": 0.88, "K": 0.55, "DEF": 0.75}
        return m.get((pos or "UNK").upper(), 1.0)

    def _point_factor(pts: float) -> float:
        if pts <= 12:
            return 1.0
        return min(1.60, 1.0 + (pts - 12) * 0.022)

    # Base width from conformal residuals or default 5.0
    if historical_residuals and len(historical_residuals) > 0:
        try:
            base_width = qhat(historical_residuals, alpha=0.2)  # 80% confidence interval
        except ValueError:
            base_width = 5.0
    else:
        base_width = 5.0

    # Heuristic scaling (no effect on MAE — only interval display)
    pos = (player_stats.get("position_group") or player_stats.get("position") or "").upper()
    # fallback if position_group missing but player_stats has position via team context: use that
    if not pos:
        pos = str(player_stats.get("position_group", "UNK")).upper()
    width = base_width * _pos_width_factor(pos) * _point_factor(point_estimate)
    # Clamp to avoid degenerate intervals: min 3.0 (K still readable), max 14.0 (QB ceiling)
    width = max(3.0, min(14.0, width))
    lower_bound = max(0.0, point_estimate - width)
    upper_bound = point_estimate + width

    return {
        "point_estimate": point_estimate,
        "lower_bound": lower_bound,
        "upper_bound": upper_bound,
        "width": width,
    }


def calculate_weekly_projections(
    weekly_stats: List[Dict],
    team_ratings: Dict[str, Dict[str, Rating]],
    historical_data: List[Dict] = None,
    use_features: bool = True,
) -> List[Dict]:
    historical_residuals = []
    if historical_data:
        for historical_week in historical_data:
            for player in historical_week.get("players", []):
                if "actual_points" in player and "projected_points" in player:
                    residual = player["actual_points"] - player["projected_points"]
                    historical_residuals.append(residual)

    projections = []
    for player_stats in weekly_stats:
        projection = calculate_projection(
            player_stats=player_stats,
            team_ratings=team_ratings,
            historical_residuals=historical_residuals,
            use_features=use_features,
        )

        player_with_projection = player_stats.copy()
        player_with_projection.update({
            "projected_points": projection["point_estimate"],
            "projection_lower": projection["lower_bound"],
            "projection_upper": projection["upper_bound"],
            "projection_width": projection["width"]
        })
        projections.append(player_with_projection)

    return projections