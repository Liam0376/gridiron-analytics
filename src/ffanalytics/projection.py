"""Projection engine: converts raw player stats into point projections
using features, ratings, and conformal calibration."""

from typing import Dict, List, Optional
from ffanalytics import config
from ffanalytics.rating import Rating, update, decay_for_inactivity
from ffanalytics.conformal import interval, qhat
import math


def calculate_target_share_feature(stats: Dict) -> float:
    """Calculate target share feature from raw stats."""
    targets = stats.get("targets", 0)
    receptions = stats.get("receptions", 0)
    # Simple approximation - in reality would need more sophisticated calculation
    if targets > 0:
        return receptions / targets
    return 0.0


def calculate_snap_pct_feature(stats: Dict) -> float:
    """Calculate snap percentage feature from raw stats."""
    snaps = stats.get("snaps", 0)
    # Would need total team snaps for proper calculation
    # For now, return a placeholder based on available data
    return min(snaps / 100.0, 1.0)  # Normalize to 0-1 range


def calculate_opponent_positional_rating_feature(
    team_ratings: Dict[str, Dict[str, Rating]],
    opponent_team: str,
    position_group: str
) -> float:
    """Get opponent positional matchup rating."""
    if not opponent_team or opponent_team not in team_ratings:
        return 1500.0  # Default rating

    # Try to get position-specific rating, fall back to overall
    position_key = f"vs_{position_group}"
    if position_key in team_ratings[opponent_team]:
        return team_ratings[opponent_team][position_key].value
    elif "overall" in team_ratings[opponent_team]:
        return team_ratings[opponent_team]["overall"].value
    else:
        return 1500.0  # Default


def calculate_projection(
    player_stats: Dict,
    team_ratings: Dict[str, Dict[str, Rating]],
    historical_residuals: List[float] = None,
    feature_weights: Dict[str, float] = None,
    weather: Dict = None,
    scoring_settings: Dict = None,
) -> Dict[str, float]:
    """
    Calculate point projection for a player.

    Returns:
        Dict with 'point_estimate', 'lower_bound', 'upper_bound', 'width'
    """
    if feature_weights is None:
        feature_weights = {
            "target_share": 0.4,
            "snap_pct": 0.3,
            "opponent_positional_rating": 0.3
        }

    # Extract basic stats
    base_points = (
        player_stats.get("pass_td", 0) * 4 +
        player_stats.get("pass_yd", 0) * 0.04 -
        player_stats.get("pass_int", 0) * 2 +
        player_stats.get("rush_td", 0) * 6 +
        player_stats.get("rush_yd", 0) * 0.1 +
        player_stats.get("rec_td", 0) * 6 +
        player_stats.get("rec_yd", 0) * 0.1 +
        player_stats.get("fum_lost", 0) * -2
    )

    # Calculate feature values
    target_share = calculate_target_share_feature(player_stats)
    snap_pct = calculate_snap_pct_feature(player_stats)

    opponent_team = player_stats.get("opponent_team")
    position_group = player_stats.get("position_group", "rb")

    opponent_rating = calculate_opponent_positional_rating_feature(
        team_ratings, opponent_team or "", position_group
    )

    # Apply feature adjustments (simplified linear model)
    # In reality, these would be learned weights from backtesting
    feature_adjustment = (
        feature_weights["target_share"] * (target_share - 0.5) * 20 +  # Center around 0.5
        feature_weights["snap_pct"] * (snap_pct - 0.5) * 15 +       # Center around 0.5
        feature_weights["opponent_positional_rating"] * ((opponent_rating - 1500) / 100)  # Normalize
    )

    point_estimate = base_points + feature_adjustment

    # Weather adjustment: high wind penalizes passing/kicking positions
    if weather and position_group.upper() in ("QB", "WR", "K"):
        wind_mph = weather.get("wind_mph", 0)
        if wind_mph > 15:
            point_estimate -= (wind_mph - 15) * config.WEATHER_WIND_PENALTY_PER_MPH

    # Apply conformal calibration if we have historical residuals
    if historical_residuals and len(historical_residuals) > 0:
        try:
            width = qhat(historical_residuals, alpha=0.2)  # 80% confidence interval
            lower_bound = point_estimate - width
            upper_bound = point_estimate + width
        except ValueError:
            # Fallback if residuals are invalid
            width = 5.0  # Default width
            lower_bound = point_estimate - width
            upper_bound = point_estimate + width
    else:
        # No calibration data - use default uncertainty
        width = 5.0
        lower_bound = point_estimate - width
        upper_bound = point_estimate + width

    return {
        "point_estimate": point_estimate,
        "lower_bound": lower_bound,
        "upper_bound": upper_bound,
        "width": width
    }


def calculate_weekly_projections(
    weekly_stats: List[Dict],
    team_ratings: Dict[str, Dict[str, Rating]],
    historical_data: List[Dict] = None
) -> List[Dict]:
    """
    Calculate projections for all players in a week.

    Args:
        weekly_stats: List of player stats dictionaries from nflverse adapter
        team_ratings: Dictionary of team ratings by team and position group
        historical_data: Optional historical data for conformal calibration

    Returns:
        List of player stats with added projection fields
    """
    # Extract historical residuals for calibration if available
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
            historical_residuals=historical_residuals
        )

        # Add projection fields to player stats
        player_with_projection = player_stats.copy()
        player_with_projection.update({
            "projected_points": projection["point_estimate"],
            "projection_lower": projection["lower_bound"],
            "projection_upper": projection["upper_bound"],
            "projection_width": projection["width"]
        })
        projections.append(player_with_projection)

    return projections