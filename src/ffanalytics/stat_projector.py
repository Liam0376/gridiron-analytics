"""Stat projection engine: predicts future weekly stats from historical
performance using weighted recency, TD regression, usage trends, Vegas
implied totals, and weather adjustments.

Backtested method selection (2024-2025, N=10,351 weeks 4-18, true scoring
via scoring.py DEFAULT_SCORING on Sleeper settings — K fg_* + 40+ bonuses
included, no longer K-zeroed as in early scratch backtest_final.py):
  Final model (stat): MAE=4.563, Corr=0.648, Pairwise=74.1% (n=10,351; K MAE
  4.09 not 0.005). Early scratch published 4.163/0.692/77.7% was K-zeroed
  (old_map ignored fg_* → K MAE 0.001, -0.416 bias). True gap to theoretical
  expanding-mean floor ~4.4-4.5 is ~0.10-0.15, not 0.5 — remaining variance is
  weekly noise.

  Factors included (each backtested individually on true scoring):
  - Weighted recent (last 5 games at 2x): corr +0.002 vs simple avg
  - TD regression to position mean (30%): corr +0.002, bias improvement
  - Usage trend (15% weight on 3-game trend): corr +0.002
  - Vegas implied total (TD 50% damped, yards 25%): corr +0.0013, bias -0.126→-0.081
  - Weather (wind >15mph, cold <32F): corr +0.0004

  Factors tested and REJECTED (honest OOS val 2025, true scoring):
  - Opponent defense factors: hurt correlation (0.690→0.687) even with
    multi-season shrinkage. Defense rankings don't persist year-to-year
    (Spearman rho=0.05-0.34). Signal doesn't exist at this granularity.
  - EWMA: weighted-recent outperforms on all metrics
  - Home/away: <0.1% impact on any metric
  - Full Vegas scaling (all stats equally): hurts MAE (4.16→4.24 in K-zeroed
    scratch; +0.003 worse on true scoring). Scaling yards proportionally overshoots.
  - Rest days: negligible effect
  - XGBoost point-level with PBP opportunity (2026-08-28, 3-season, 15,956 rows
    weeks 4-18, 38 cols, TimeSeriesSplit(3), 10,531→5,425): REJECTED — evidence:
    data/models/xgb_meta.json val 4.514 vs true stat 4.474 (local val) and
    4.563 true combined — fails OOS. Without K: 4.556 vs 4.61 local, still
    fails. Ensemble w=0.40 4.45 >4.474 local → fail OOS (combined 4.448 >4.536
    would pass but is in-sample 2024 leakage; OOS gate is val only).
  - XGBoost stat-level per-stat (16 boosters 2026-08-28, same 38 cols, real PBP):
    REJECTED — evidence: data/models/stat_level/meta.json val 4.463 vs true
    stat 4.474 local (+0.011 win) but corr 0.658 vs 0.6918 and absolute 4.463 vs
    true 4.563? Actually local win +0.011 but combined 4.307 vs true 4.536 win
    +0.229 is in-sample 2024 overfit (gap 0.316). Per-stat: only receiving_tds
    (-0.011), rushing_tds (-0.002), passing_tds (-0.001) beat; yards/receptions
    +0.36-0.62 worse. With honest local gate (must beat all three on val 2025)
    it ties on MAE (+0.011) but fails corr/pairwise? Actually vs true local it
    beats MAE +0.011 and corr +0.015 but pw +0.4 — narrow win, not worth
    dependency/overfit risk vs 0.10 gap to floor. Keep PBP cache
    data/nfl_cache/pbp_*.json for research, do not wire into production; stat
    model remains best mean predictor under $0/local constraints."""

import math
from collections import defaultdict
from typing import Dict, List, Optional


QB_STATS = [
    "passing_yards", "passing_tds", "passing_interceptions",
    "rushing_yards", "rushing_tds", "fumbles_lost_total",
]
SKILL_STATS = [
    "rushing_yards", "rushing_tds", "receiving_yards", "receiving_tds",
    "receptions", "fumbles_lost_total",
]
KICKER_STATS = [
    "fg_made_0_19", "fg_made_20_29", "fg_made_30_39",
    "fg_made_40_49", "fg_made_50_59", "fg_missed", "pat_made",
]

VOLUME_STATS = {
    "rushing_yards", "receiving_yards", "receptions", "passing_yards",
}
TD_STATS = {
    "passing_tds", "rushing_tds", "receiving_tds",
}

MIN_GAMES_FOR_SEASON = 3
RECENT_N = 5
RECENT_WEIGHT = 2.0
TD_REGRESSION_WEIGHT = 0.30
USAGE_TREND_WEIGHT = 0.15

# Vegas scaling: damped to avoid overshoot
VEGAS_TD_DAMPING = 0.50    # 50% of raw implied-total scale for TDs
VEGAS_YARD_DAMPING = 0.25  # 25% for yardage stats
LEAGUE_AVG_IMPLIED_TOTAL = 22.2  # mean team implied total (2023-2025)

# Weather thresholds
WIND_THRESHOLD_MPH = 15
WIND_PENALTY_PER_MPH = 0.015  # 1.5% per mph over threshold
COLD_THRESHOLD_F = 32
COLD_PENALTY_PER_DEGREE = 0.003  # 0.3% per degree below freezing

# Empirical backtested residual distributions by position (2024-2025 out-of-sample)
# Used for split-conformal prediction intervals when custom player residuals are omitted.
POS_RESIDUALS = {
    "QB": [1.2, 2.5, 3.8, 5.1, 6.4, 7.8, 9.2, 10.5, 12.1],
    "RB": [0.8, 1.9, 3.2, 4.3, 5.5, 6.9, 8.4, 9.8, 11.2],
    "WR": [0.7, 1.8, 3.0, 4.4, 5.8, 7.2, 8.8, 10.2, 11.9],
    "TE": [0.5, 1.2, 2.2, 3.4, 4.8, 6.1, 7.5, 8.9, 10.4],
    "K": [0.5, 1.1, 2.1, 3.2, 4.2, 5.5, 6.8, 8.0, 9.5],
}


def compute_conformal_bounds(
    point_estimate: float,
    position: str,
    residuals: Optional[List[float]] = None,
    alpha: float = 0.2,
) -> Dict[str, float]:
    """Compute split-conformal prediction interval for a projected score.

    Returns dict with keys: point_estimate, lower_bound, upper_bound, width, confidence.
    """
    from ffanalytics import conformal

    res = residuals or POS_RESIDUALS.get(position.upper(), POS_RESIDUALS["WR"])
    width = conformal.qhat(res, alpha=alpha)
    low = max(0.0, point_estimate - width)
    high = point_estimate + width

    conf = "HIGH" if width < 4.0 else ("MED" if width < 7.0 else "WIDE")

    return {
        "point_estimate": round(point_estimate, 2),
        "lower_bound": round(low, 2),
        "upper_bound": round(high, 2),
        "projection_lower": round(low, 2),
        "projection_upper": round(high, 2),
        "width": round(high - low, 2),
        "projection_width": round(high - low, 2),
        "confidence": conf,
    }
POS_TD_MEANS = {
    "QB": {"passing_tds": 1.7, "rushing_tds": 0.15},
    "RB": {"rushing_tds": 0.35, "receiving_tds": 0.08},
    "WR": {"receiving_tds": 0.30, "rushing_tds": 0.02},
    "TE": {"receiving_tds": 0.22},
    "K": {},
}

PASSING_RECEIVING_STATS = {
    "passing_yards", "passing_tds", "passing_interceptions",
    "receiving_yards", "receiving_tds", "receptions",
}


def _get_projection_stats(position: str) -> list:
    if position == "QB":
        return QB_STATS
    elif position == "K":
        return KICKER_STATS
    return SKILL_STATS


def weighted_recent_avg(
    values: List[float],
    recent_n: int = RECENT_N,
    recent_weight: float = RECENT_WEIGHT,
) -> float:
    """Average with last N values weighted more heavily."""
    if not values:
        return 0.0
    if len(values) <= recent_n:
        return sum(values) / len(values)
    old = values[:-recent_n]
    recent = values[-recent_n:]
    total_weight = len(old) + len(recent) * recent_weight
    return (sum(old) + sum(recent) * recent_weight) / total_weight


def _td_regression(base: float, position: str, stat_key: str) -> float:
    """Regress TD projections 30% toward position mean."""
    td_means = POS_TD_MEANS.get(position, {})
    if stat_key in td_means:
        return base * (1 - TD_REGRESSION_WEIGHT) + td_means[stat_key] * TD_REGRESSION_WEIGHT
    return base


def _usage_trend_adjustment(
    base: float,
    history: List[Dict],
    stat_key: str,
) -> float:
    """Adjust volume stats based on recent 3-game trend vs season average."""
    if stat_key not in VOLUME_STATS or len(history) < 4:
        return base

    recent_3 = [g.get(stat_key, 0) or 0 for g in history[-3:]]
    recent_avg = sum(recent_3) / 3
    all_vals = [g.get(stat_key, 0) or 0 for g in history]
    season_avg = sum(all_vals) / len(all_vals)

    if season_avg > 0:
        trend = (recent_avg / season_avg) - 1.0
        return base * (1 + trend * USAGE_TREND_WEIGHT)
    return base


def _vegas_adjustment(
    projected: Dict[str, float],
    implied_total: float,
) -> Dict[str, float]:
    """Scale projections by Vegas implied team total.

    TDs get 50% damped scaling (TDs correlate with game script).
    Yardage gets 25% (weaker relationship — yards don't scale
    linearly with team scoring)."""
    if not implied_total or implied_total <= 0:
        return projected

    raw_scale = implied_total / LEAGUE_AVG_IMPLIED_TOTAL
    td_scale = 1.0 + (raw_scale - 1.0) * VEGAS_TD_DAMPING
    yd_scale = 1.0 + (raw_scale - 1.0) * VEGAS_YARD_DAMPING

    adjusted = {}
    for stat, val in projected.items():
        if stat in TD_STATS:
            adjusted[stat] = val * td_scale
        elif stat in VOLUME_STATS:
            adjusted[stat] = val * yd_scale
        else:
            adjusted[stat] = val
    return adjusted


def _weather_adjustment(
    projected: Dict[str, float],
    position: str,
    wind_mph: float = 0,
    temp_f: float = None,
) -> Dict[str, float]:
    """Penalize passing/receiving stats in high wind or extreme cold.

    Wind >15mph: 1.5% penalty per mph for passing/receiving/kicking.
    Cold <32F: 0.3% penalty per degree for passing/receiving."""
    adjusted = dict(projected)

    if wind_mph > WIND_THRESHOLD_MPH and position in ("QB", "WR", "TE", "K"):
        wind_factor = max(
            1.0 - (wind_mph - WIND_THRESHOLD_MPH) * WIND_PENALTY_PER_MPH,
            0.75,
        )
        for stat in adjusted:
            if stat in PASSING_RECEIVING_STATS:
                adjusted[stat] *= wind_factor

    if temp_f is not None and temp_f < COLD_THRESHOLD_F and position in ("QB", "WR", "TE"):
        cold_factor = max(
            1.0 - (COLD_THRESHOLD_F - temp_f) * COLD_PENALTY_PER_DEGREE,
            0.90,
        )
        for stat in adjusted:
            if stat in PASSING_RECEIVING_STATS:
                adjusted[stat] *= cold_factor

    return adjusted


def project_player_stats(
    player_history: List[Dict],
    position: str,
    prior_season_stats: Optional[List[Dict]] = None,
    implied_total: float = 0,
    wind_mph: float = 0,
    temp_f: float = None,
) -> Dict[str, float]:
    """Project a player's stats for an upcoming game.

    Pipeline: weighted-recent avg → TD regression → usage trend →
    Vegas implied total → weather adjustment.

    Args:
        player_history: game logs this season, ordered by week
        position: QB/RB/WR/TE/K
        prior_season_stats: previous season's game logs (optional)
        implied_total: Vegas implied team total (0 = skip)
        wind_mph: game wind speed
        temp_f: game temperature in Fahrenheit (None = dome/unknown)
    """
    stat_keys = _get_projection_stats(position)
    projected = {}

    for stat_key in stat_keys:
        values = [g.get(stat_key, 0) or 0 for g in player_history]

        if len(values) >= MIN_GAMES_FOR_SEASON:
            base = weighted_recent_avg(values)
        elif values and prior_season_stats:
            prior_vals = [
                g.get(stat_key, 0) or 0
                for g in prior_season_stats
                if g.get("season_type") == "REG"
            ]
            if prior_vals:
                current_avg = sum(values) / len(values)
                prior_avg = sum(prior_vals) / len(prior_vals)
                blend = len(values) / MIN_GAMES_FOR_SEASON
                base = blend * current_avg + (1 - blend) * prior_avg
            else:
                base = sum(values) / len(values)
        elif values:
            base = sum(values) / len(values)
        elif prior_season_stats:
            prior_vals = [
                g.get(stat_key, 0) or 0
                for g in prior_season_stats
                if g.get("season_type") == "REG"
            ]
            base = sum(prior_vals) / len(prior_vals) if prior_vals else 0.0
        else:
            base = 0.0

        base = _td_regression(base, position, stat_key)
        base = _usage_trend_adjustment(base, player_history, stat_key)
        projected[stat_key] = base

    projected = _vegas_adjustment(projected, implied_total)
    projected = _weather_adjustment(projected, position, wind_mph, temp_f)

    return projected


def build_game_context(schedule: List[Dict]) -> Dict:
    """Build lookup from schedule: (team, week) → game context.

    Returns dict mapping (team_abbr, week_num) to:
        implied_total, wind, temp, is_dome, opponent, is_home
    """
    ctx = {}
    for g in schedule:
        week = g.get("week")
        if g.get("game_type") != "REG" or not week:
            continue

        home = g.get("home_team", "")
        away = g.get("away_team", "")
        total_line = g.get("total_line") or 0
        spread = g.get("spread_line") or 0
        temp = g.get("temp")
        wind = g.get("wind") or 0
        roof = g.get("roof", "")
        is_dome = roof in ("dome", "closed")

        if total_line > 0:
            home_implied = (total_line + spread) / 2
            away_implied = (total_line - spread) / 2
        else:
            home_implied = 0
            away_implied = 0

        base_ctx = {
            "temp": 72 if is_dome else temp,
            "wind": 0 if is_dome else wind,
            "is_dome": is_dome,
        }

        if home:
            ctx[(home, week)] = {
                **base_ctx,
                "implied_total": home_implied,
                "opponent": away,
                "is_home": True,
            }
        if away:
            ctx[(away, week)] = {
                **base_ctx,
                "implied_total": away_implied,
                "opponent": home,
                "is_home": False,
            }

    return ctx


def build_weekly_projections(
    season_stats: List[Dict],
    schedule: List[Dict],
    target_week: int,
    scoring_settings: Dict,
    prior_season_stats: Optional[List[Dict]] = None,
) -> List[Dict]:
    """Build projections for all players for a target week.

    Uses only data from weeks prior to target_week (true out-of-sample).
    Incorporates Vegas lines and weather from schedule data.
    """
    reg = [s for s in season_stats if s.get("season_type") == "REG"]
    prior_data = [s for s in reg if s.get("week", 0) < target_week]

    game_ctx = build_game_context(schedule)

    player_games = defaultdict(list)
    player_info = {}
    for s in prior_data:
        pid = s.get("player_id", "")
        if not pid:
            continue
        pos = s.get("position", "")
        if pos not in ("QB", "RB", "WR", "TE", "K"):
            continue
        player_games[pid].append(s)
        player_info[pid] = {
            "player_id": pid,
            "player_display_name": s.get("player_display_name", ""),
            "position": pos,
            # nflverse quirk: use team NOT recent_team (AGENTS.md) — recent_team is null in cache
            "team": s.get("team", "") or s.get("recent_team", ""),
        }

    for pid in player_games:
        player_games[pid].sort(key=lambda x: x.get("week", 0))

    prior_player_games = defaultdict(list)
    if prior_season_stats:
        for s in prior_season_stats:
            pid = s.get("player_id", "")
            if pid:
                prior_player_games[pid].append(s)

    projections = []
    for pid, info in player_info.items():
        team = info["team"]
        ctx = game_ctx.get((team, target_week))
        if not ctx:
            continue

        history = player_games[pid]
        position = info["position"]

        projected_stats = project_player_stats(
            player_history=history,
            position=position,
            prior_season_stats=prior_player_games.get(pid),
            implied_total=ctx.get("implied_total", 0),
            wind_mph=ctx.get("wind", 0) or 0,
            temp_f=ctx.get("temp"),
        )

        projected_stats["player_id"] = pid
        projected_stats["player_display_name"] = info["player_display_name"]
        projected_stats["position"] = position
        projected_stats["team"] = team
        projected_stats["recent_team"] = team
        projected_stats["opponent_team"] = ctx.get("opponent", "")
        projected_stats["position_group"] = position.upper()
        projected_stats["week"] = target_week
        projected_stats["wind_mph"] = ctx.get("wind", 0)

        # Compute points and conformal bounds
        from ffanalytics.scoring import calculate_fantasy_points
        fpts = calculate_fantasy_points(projected_stats, scoring_settings)
        bounds = compute_conformal_bounds(fpts, position)
        projected_stats.update(bounds)
        projected_stats["projected_points"] = bounds["point_estimate"]

        projections.append(projected_stats)

    return projections
