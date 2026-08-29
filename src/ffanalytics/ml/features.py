"""Feature engineering for ML ensemble — time-series clean training rows.

Time-series discipline: for each target week, only weeks < target_week are
used to compute history features (weighted averages, projections, trend).
No future leakage. PBP shares use same RECENT_N=5@2x as stat projector
to avoid single-week noise.

Rejected factors are NOT reintroduced (see AGENTS.md REJECTED list):
- opponent defense — correlation hurts, rho 0.05-0.34, no signal
- home/away — <0.1% impact
- rest days — negligible
- EWMA — weighted-recent wins
This module does NOT compute opponent positional ratings, home/away flags
or rest; grep for "defense" must be absent except in this comment about rejection.
"""

from collections import defaultdict
from typing import Dict, List, Optional, Any

# Do NOT import ffanalytics.config here — SLEEPER_LEAGUE_ID must not break import
try:
    from ffanalytics.scoring import calculate_fantasy_points, DEFAULT_SCORING
    try:
        from ffanalytics.scoring import SCORING
    except ImportError:
        SCORING = DEFAULT_SCORING
except Exception:
    # fallback for environments without scoring (should not happen in repo)
    SCORING = {
        "rec": 1.0, "rec_yd": 0.1, "rush_yd": 0.1, "pass_yd": 0.04,
        "pass_td": 5.0, "rush_td": 6.0, "rec_td": 6.0, "pass_int": -1.0,
        "fum_lost": -2.0,
    }

    def calculate_fantasy_points(stats: dict, scoring_settings=None):
        # minimal fallback — actual scoring.py provides full mapping
        return 0.0
    DEFAULT_SCORING = SCORING

from ffanalytics.stat_projector import (
    project_player_stats,
    weighted_recent_avg,
    build_game_context as _stat_build_ctx,
    RECENT_N,
    RECENT_WEIGHT,
    MIN_GAMES_FOR_SEASON,
    _get_projection_stats,
)

# All possible projection keys across positions (union)
ALL_PROJ_KEYS = [
    "passing_yards",
    "passing_tds",
    "passing_interceptions",
    "rushing_yards",
    "rushing_tds",
    "receiving_yards",
    "receiving_tds",
    "receptions",
    "fumbles_lost_total",
    # kicker
    "fg_made_0_19",
    "fg_made_20_29",
    "fg_made_30_39",
    "fg_made_40_49",
    "fg_made_50_59",
    "fg_missed",
    "pat_made",
]

# Mapping from stat keys to short aliases expected by spec
SHORT_ALIASES = {
    "passing_yards": "pass_yd_proj",
    "passing_tds": "pass_td_proj",
    "passing_interceptions": "pass_int_proj",
    "rushing_yards": "rush_yd_proj",
    "rushing_tds": "rush_td_proj",
    "receiving_yards": "rec_yd_proj",
    "receiving_tds": "rec_td_proj",
    "receptions": "rec_proj",
    "fumbles_lost_total": "fum_lost_proj",
}

# Expected feature keys (for test completeness) — includes all required by spec
EXPECTED_FEATURE_KEYS = [
    "target_share_wavg",
    "rush_share_wavg",
    "air_yards_wavg",
    "air_yards_share_wavg",
    "redzone_targets_wavg",
    "redzone_carries_wavg",
    "snap_share_wavg",
    # projected stat features (at least these 4 short names + long)
    "pass_yd_proj",
    "rush_yd_proj",
    "rec_yd_proj",
    "rec_proj",
    # also long names
    "passing_yards_proj",
    "rushing_yards_proj",
    "receiving_yards_proj",
    "receptions_proj",
    # Vegas / weather
    "implied_total",
    "spread",
    "wind",
    "temp",
    "is_dome",
    # context
    "games_played",
    "position_QB",
    "position_RB",
    "position_WR",
    "position_TE",
    "position_K",
    "recent_trend",
    "trend_slope",
    "team",
    "season",
    "week",
    "player_id",
    "target",
]


def _map_to_scoring_stats(s: Dict[str, Any]) -> Dict[str, Any]:
    """Map raw nflverse stats dict to scoring.py expected keys for target calc."""
    return {
        "receptions": s.get("receptions", 0) or 0,
        "receiving_yards": s.get("receiving_yards", 0) or 0,
        "receiving_tds": s.get("receiving_tds", 0) or 0,
        "rushing_yards": s.get("rushing_yards", 0) or 0,
        "rushing_tds": s.get("rushing_tds", 0) or 0,
        "passing_yards": s.get("passing_yards", 0) or 0,
        "passing_tds": s.get("passing_tds", 0) or 0,
        "interceptions": s.get("passing_interceptions", 0) or s.get("interceptions", 0) or 0,
        "fumbles_lost": s.get("fumbles_lost_total", 0) or s.get("fumbles_lost", 0) or 0,
        "passing_2pt": s.get("passing_2pt_conversions", 0) or 0,
        "rushing_2pt": s.get("rushing_2pt_conversions", 0) or 0,
        "receiving_2pt": s.get("receiving_2pt_conversions", 0) or 0,
        "passing_40": s.get("passing_40", 0) or 0,
        "rushing_40": s.get("rushing_40", 0) or 0,
        "receiving_40": s.get("receiving_40", 0) or 0,
        "fg_made_0_19": s.get("fg_made_0_19", 0) or 0,
        "fg_made_20_29": s.get("fg_made_20_29", 0) or 0,
        "fg_made_30_39": s.get("fg_made_30_39", 0) or 0,
        "fg_made_40_49": s.get("fg_made_40_49", 0) or 0,
        "fg_made_50_59": s.get("fg_made_50_59", 0) or 0,
        "fg_made_60_": s.get("fg_made_60_", 0) or 0,
        "fg_missed": s.get("fg_missed", 0) or 0,
        "pat_made": s.get("pat_made", 0) or 0,
        "pat_missed": s.get("pat_missed", 0) or 0,
        "fumble_recovery": (s.get("fumble_recovery_opp", 0) or 0) + (s.get("fumble_recovery_own", 0) or 0),
        "fumble_recovery_td": s.get("fumble_recovery_tds", 0) or 0,
        "forced_fumble": s.get("def_fumbles_forced", 0) or 0,
    }


def _weighted_avg(values: List[float]) -> float:
    """Same RECENT_N=5@2x discipline as stat_projector.weighted_recent_avg."""
    if not values:
        return 0.0
    return weighted_recent_avg(values, recent_n=RECENT_N, recent_weight=RECENT_WEIGHT)


def _build_schedule_context_by_season(schedules: List[Dict]) -> Dict[int, Dict]:
    """Group schedules by season and build per-team-week context.

    Returns dict season -> dict[(team, week)] -> {implied_total, spread, wind, temp, is_dome}
    No opponent rating is stored (REJECTED — see header).
    """
    by_season: Dict[int, List[Dict]] = defaultdict(list)
    for g in schedules or []:
        season = g.get("season")
        if season is None:
            continue
        try:
            season = int(season)
        except Exception:
            continue
        by_season[season].append(g)

    ctx_by_season: Dict[int, Dict] = {}
    for season, games in by_season.items():
        ctx: Dict[tuple, Dict] = {}
        for g in games:
            week = g.get("week")
            if g.get("game_type") != "REG" or not week:
                continue
            try:
                week = int(week)
            except Exception:
                continue
            home = g.get("home_team", "") or ""
            away = g.get("away_team", "") or ""
            total_line = g.get("total_line")
            spread_line = g.get("spread_line")
            # handle None
            total_line = float(total_line) if total_line is not None else 0.0
            spread_line = float(spread_line) if spread_line is not None else 0.0
            temp = g.get("temp")
            wind = g.get("wind")
            roof = g.get("roof", "") or ""
            is_dome = 1 if roof in ("dome", "closed") else 0

            if total_line > 0:
                home_implied = (total_line + spread_line) / 2.0
                away_implied = (total_line - spread_line) / 2.0
            else:
                home_implied = 0.0
                away_implied = 0.0

            # wind/temp normalization: dome -> wind 0 temp 72; otherwise None -> 0 / 65
            if is_dome:
                norm_wind = 0.0
                norm_temp = 72.0
            else:
                try:
                    norm_wind = float(wind) if wind is not None else 0.0
                except Exception:
                    norm_wind = 0.0
                try:
                    norm_temp = float(temp) if temp is not None else 65.0
                except Exception:
                    norm_temp = 65.0

            # spread per team: home gets spread_line, away gets -spread_line
            # This keeps sign consistent: positive => team favored? (home favored if spread positive)
            if home:
                ctx[(home, week)] = {
                    "implied_total": float(home_implied),
                    "spread": float(spread_line),
                    "wind": float(norm_wind),
                    "temp": float(norm_temp),
                    "is_dome": int(is_dome),
                    "total_line": float(total_line) if total_line else 0.0,
                }
            if away:
                ctx[(away, week)] = {
                    "implied_total": float(away_implied),
                    "spread": float(-spread_line),
                    "wind": float(norm_wind),
                    "temp": float(norm_temp),
                    "is_dome": int(is_dome),
                    "total_line": float(total_line) if total_line else 0.0,
                }
        ctx_by_season[season] = ctx
    return ctx_by_season


def _index_pbp(pbp_features: Optional[List[Dict]]) -> Dict[tuple, List[Dict]]:
    """Index PBP rows by (player_id, season) sorted by week.

    Handles bothseason-included rows and legacy rows without season (assumes 2024).
    """
    idx: Dict[tuple, List[Dict]] = defaultdict(list)
    if not pbp_features:
        return idx
    for r in pbp_features:
        pid = str(r.get("player_id", "")).strip()
        if not pid:
            continue
        wk = r.get("week")
        if wk is None:
            continue
        try:
            wk = int(wk)
        except Exception:
            continue
        season = r.get("season")
        if season is not None:
            try:
                season = int(season)
            except Exception:
                season = None
        # If season missing, we store with key None but will match any season fallback
        # For grouping we keep season-specific; missing season rows will be stored under (pid, None)
        idx[(pid, season)].append(r)
        # Also store under flexible key for missing season handling? We'll handle lookup with fallback
    # sort each list by week
    for k in idx:
        idx[k].sort(key=lambda x: int(x.get("week", 0) or 0))
    return idx


def _get_pbp_history(
    pbp_idx: Dict[tuple, List[Dict]],
    player_id: str,
    season: int,
    target_week: int,
) -> List[Dict]:
    """Return PBP rows for player/season with week < target_week, sorted."""
    # Direct season key
    rows = pbp_idx.get((player_id, season), [])
    # Also include rows with None season (legacy) if season-specific empty? But we should not mix seasons.
    # If season-specific has data, use it; otherwise try None season fallback
    if not rows and (player_id, None) in pbp_idx:
        rows = pbp_idx[(player_id, None)]
    # filter week < target
    out = [r for r in rows if int(r.get("week", 0) or 0) < int(target_week)]
    out.sort(key=lambda x: int(x.get("week", 0) or 0))
    return out


def _pbp_wavg_features(pbp_history: List[Dict]) -> Dict[str, float]:
    """Compute weighted avg for each opportunity metric from PBP history (< target)."""
    if not pbp_history:
        return {
            "target_share_wavg": 0.0,
            "rush_share_wavg": 0.0,
            "air_yards_wavg": 0.0,
            "air_yards_share_wavg": 0.0,
            "redzone_targets_wavg": 0.0,
            "redzone_carries_wavg": 0.0,
            "snap_share_wavg": 0.0,
            "route_share_wavg": 0.0,
        }
    def vals(key):
        lst = []
        for r in pbp_history:
            v = r.get(key, 0)
            if v is None:
                v = 0
            try:
                lst.append(float(v))
            except Exception:
                lst.append(0.0)
        return lst

    return {
        "target_share_wavg": _weighted_avg(vals("target_share")),
        "rush_share_wavg": _weighted_avg(vals("rush_share")),
        "air_yards_wavg": _weighted_avg(vals("air_yards")),
        "air_yards_share_wavg": _weighted_avg(vals("air_yards_share")),
        "redzone_targets_wavg": _weighted_avg(vals("redzone_targets")),
        "redzone_carries_wavg": _weighted_avg(vals("redzone_carries")),
        "snap_share_wavg": _weighted_avg(vals("snap_share")),
        "route_share_wavg": _weighted_avg(vals("route_share")),
    }


def _trend_features(history: List[Dict], position: str) -> Dict[str, float]:
    """Recent trend slope features — time-series clean, only history (< target)."""
    if not history or len(history) < 2:
        return {"recent_trend": 0.0, "trend_slope": 0.0, "recent_trend_slope": 0.0}
    # Use fantasy points as generic trend signal (actual points history)
    # Build points history via scoring to be position-agnostic
    pts_hist = []
    for h in history:
        try:
            pts = calculate_fantasy_points(_map_to_scoring_stats(h), SCORING)
        except Exception:
            pts = 0.0
        pts_hist.append(float(pts))

    # recent_trend as (recent_3_avg / season_avg -1)
    if len(history) >= 4:
        recent_3 = pts_hist[-3:]
        recent_avg = sum(recent_3) / 3.0
        season_avg = sum(pts_hist) / len(pts_hist) if pts_hist else 0
        if season_avg > 1e-9:
            recent_trend = (recent_avg / season_avg) - 1.0
        else:
            recent_trend = 0.0
    else:
        recent_trend = 0.0

    # trend_slope via linear regression slope over pts_hist
    n = len(pts_hist)
    if n >= 2:
        xs = list(range(n))
        # slope = cov(x,y)/var(x)
        mx = sum(xs) / n
        my = sum(pts_hist) / n
        num = sum((x - mx) * (y - my) for x, y in zip(xs, pts_hist))
        den = sum((x - mx) ** 2 for x in xs)
        slope = num / den if den != 0 else 0.0
    else:
        slope = 0.0

    return {
        "recent_trend": float(recent_trend),
        "trend_slope": float(slope),
        "recent_trend_slope": float(slope),
    }


def _projected_features(
    history: List[Dict],
    position: str,
    prior_season_stats: Optional[List[Dict]],
    implied_total: float,
    wind_mph: float,
    temp_f: float,
) -> Dict[str, float]:
    """Call stat_projector pipeline and map to _proj features."""
    try:
        proj = project_player_stats(
            player_history=history,
            position=position,
            prior_season_stats=prior_season_stats,
            implied_total=implied_total or 0,
            wind_mph=wind_mph or 0,
            temp_f=temp_f,
        )
    except Exception:
        proj = {}

    out: Dict[str, float] = {}
    for k in ALL_PROJ_KEYS:
        v = proj.get(k, 0) or 0
        try:
            fv = float(v)
        except Exception:
            fv = 0.0
        out[f"{k}_proj"] = fv
        # also add short alias if exists
        if k in SHORT_ALIASES:
            out[SHORT_ALIASES[k]] = fv

    # Ensure at least the short aliases exist even if K stats missing
    for long_k, short_k in SHORT_ALIASES.items():
        if short_k not in out:
            out[short_k] = out.get(f"{long_k}_proj", 0.0)
    return out


def _build_single_row_legacy(
    season: int,
    week: int,
    player_history: List[Dict],
    position: str,
    pbp_cache: Optional[List[Dict]],
    schedule: Optional[List[Dict]],
    prior_season_stats: Optional[List[Dict]],
    scoring_settings: Optional[Dict],
    actual_stats: Optional[Dict] = None,
) -> Dict[str, Any]:
    """Single-row builder for legacy signature: (season, week, player_history, pbp_cache, schedule) -> dict"""
    scoring = scoring_settings or SCORING
    pbp_idx = _index_pbp(pbp_cache)
    # Build schedule ctx for this season only
    ctx_by_season = _build_schedule_context_by_season(schedule or [])
    ctx = ctx_by_season.get(season, {}).get(
        # need team: infer from last history or actual_stats
        ( (player_history[-1].get("team") or player_history[-1].get("recent_team") or "") if player_history else (actual_stats.get("team") or actual_stats.get("recent_team") or "") if actual_stats else "", week),
        None,
    )
    # If we couldn't determine team, try any team lookup? fallback to first entry
    if ctx is None:
        # try to find team from history
        team_guess = ""
        if player_history:
            team_guess = player_history[-1].get("team") or player_history[-1].get("recent_team") or ""
        elif actual_stats:
            team_guess = actual_stats.get("team") or actual_stats.get("recent_team") or ""
        ctx = ctx_by_season.get(season, {}).get((team_guess, week), {"implied_total": 0.0, "spread": 0.0, "wind": 0.0, "temp": 65.0, "is_dome": 0})

    if ctx is None:
        ctx = {"implied_total": 0.0, "spread": 0.0, "wind": 0.0, "temp": 65.0, "is_dome": 0}

    # Determine player_id
    pid = ""
    if player_history and player_history[0].get("player_id"):
        pid = str(player_history[0].get("player_id"))
    elif actual_stats and actual_stats.get("player_id"):
        pid = str(actual_stats.get("player_id"))
    else:
        pid = "unknown"

    # history is already filtered < target; ensure it's sorted and filtered
    history = sorted([h for h in (player_history or []) if int(h.get("week", 0) or 0) < int(week)], key=lambda x: int(x.get("week", 0) or 0))
    games_played = len(history)

    # PBP wavg
    pbp_hist = _get_pbp_history(pbp_idx, pid, season, week)
    pbp_wavg = _pbp_wavg_features(pbp_hist)

    # trend
    trend = _trend_features(history, position)

    # projected
    proj_feats = _projected_features(history, position, prior_season_stats, ctx.get("implied_total", 0), ctx.get("wind", 0), ctx.get("temp"))

    # one-hot
    pos_onehot = {f"position_{p}": 1 if position == p else 0 for p in ("QB", "RB", "WR", "TE", "K")}

    # team
    team = ""
    if actual_stats:
        team = actual_stats.get("team") or actual_stats.get("recent_team") or ""
    elif history:
        team = history[-1].get("team") or history[-1].get("recent_team") or ""
    # if still empty try ctx team key? we already have team_guess
    if not team and player_history:
        team = player_history[-1].get("team") or player_history[-1].get("recent_team") or ""

    # target actual points if actual_stats provided
    target = 0.0
    if actual_stats:
        try:
            target = float(calculate_fantasy_points(_map_to_scoring_stats(actual_stats), scoring))
        except Exception:
            target = 0.0

    row = {
        "player_id": pid,
        "season": int(season) if season is not None else 0,
        "week": int(week),
        "team": team,
        "position": position,
        "games_played": int(games_played),
        "implied_total": float(ctx.get("implied_total", 0) or 0),
        "spread": float(ctx.get("spread", 0) or 0),
        "wind": float(ctx.get("wind", 0) or 0),
        "temp": float(ctx.get("temp", 65) or 65),
        "is_dome": int(ctx.get("is_dome", 0)),
        "target": float(target),
        "actual_points": float(target),
        **pbp_wavg,
        **trend,
        **proj_feats,
        **pos_onehot,
    }
    # Ensure expected keys exist
    for k in EXPECTED_FEATURE_KEYS:
        if k not in row:
            # default 0 for numeric, empty for team/position
            if k in ("team", "position", "player_id"):
                row[k] = ""
            else:
                row[k] = 0.0
    return row


def build_training_rows(
    all_stats: Optional[List[Dict]] = None,
    all_schedules: Optional[List[Dict]] = None,
    pbp_features: Optional[List[Dict]] = None,
    scoring_settings: Optional[Dict] = None,
    seasons: Optional[List[int]] = None,
    min_week: int = 4,
    max_week: int = 18,
    *args,
    **kwargs,
) -> List[Dict]:
    """Build one dict per player-week for weeks 4-18, no leakage.

    Time-series clean: only weeks < target_week are used for history features
    (weighted avg, projections, trend). PBP shares use RECENT_N=5@2x.

    Supports two call patterns:
    1) Batch (used by scripts/build_ml_dataset.py):
       build_training_rows(all_stats, all_schedules, pbp_features, scoring_settings)
       -> List[Dict] each with features + target

    2) Legacy single-row (for backwards compat with plan description):
       build_training_rows(season=2024, week=5, player_history=[...],
                           pbp_cache=[...], schedule=[...], position="WR")
       -> List[Dict] with single row (still returns list for uniformity, but also
          handled if caller expects dict). If legacy kwargs detected, we build
          single row and return list with one dict (or dict if caller used positional season int).

    Args:
        all_stats: list of stats dicts with keys season, week, player_id, position, team, etc.
        all_schedules: list of schedule dicts with season, week, home_team, away_team, total_line, spread_line, temp, wind, roof
        pbp_features: list of pbp opportunity dicts per player-week (or None -> defaults 0)
        scoring_settings: scoring dict, defaults to SCORING
        seasons: optional filter of seasons to generate rows for
        min_week/max_week: inclusive week range (default 4-18)

    Returns:
        List[Dict] each row contains features + target + metadata.
        No opponent rating, no home/away, no rest, no EWMA features (REJECTED — see header).
    """
    # Legacy single-row detection: if caller passed player_history or pbp_cache or explicit season/week kwargs
    if (
        kwargs.get("player_history") is not None
        or kwargs.get("pbp_cache") is not None
        or kwargs.get("schedule") is not None
        or kwargs.get("position") is not None
        or kwargs.get("prior_season_stats") is not None
        or (all_stats is not None and isinstance(all_stats, int))
    ):
        # Handle legacy positional signature: build_training_rows(season, week, player_history, pbp_cache, schedule)
        # Detect positional args case where first arg is season int
        legacy_season = None
        legacy_week = None
        legacy_history = None
        legacy_pbp = None
        legacy_sched = None
        legacy_pos = None
        legacy_prior = None
        legacy_scoring = scoring_settings
        legacy_actual = None

        # args may contain positional legacy values
        # Signature from plan: build_training_rows(season, week, player_history, pbp_cache, schedule)
        # So all_stats could be season int, all_schedules could be week int, pbp_features could be history list
        if isinstance(all_stats, int) and isinstance(all_schedules, int):
            legacy_season = all_stats
            legacy_week = all_schedules
            # pbp_features in this position is actually player_history
            legacy_history = pbp_features
            # scoring_settings positional would be pbp_cache
            legacy_pbp = scoring_settings
            # seasons positional would be schedule
            legacy_sched = seasons
            # min_week positional would be prior? This is messy. Use kwargs for rest.
            legacy_pos = kwargs.get("position") or kwargs.get("pos") or "WR"
            legacy_prior = kwargs.get("prior_season_stats")
            legacy_scoring = kwargs.get("scoring_settings") or kwargs.get("scoring") or SCORING
            legacy_actual = kwargs.get("actual_stats") or kwargs.get("target_stats")
        else:
            legacy_season = kwargs.get("season", all_stats if isinstance(all_stats, int) else None)
            legacy_week = kwargs.get("week", all_schedules if isinstance(all_schedules, int) else None)
            legacy_history = kwargs.get("player_history", pbp_features if isinstance(pbp_features, list) and pbp_features and isinstance(pbp_features[0], dict) and "passing_yards" in pbp_features[0] else None)
            # pbp_cache handling
            legacy_pbp = kwargs.get("pbp_cache", kwargs.get("pbp_features"))
            if legacy_pbp is None and scoring_settings is not None and isinstance(scoring_settings, list):
                legacy_pbp = scoring_settings
            legacy_sched = kwargs.get("schedule", kwargs.get("all_schedules") or seasons if isinstance(seasons, list) and seasons and isinstance(seasons[0], dict) else None)
            # schedule may be passed as 'schedule'
            if legacy_sched is None:
                legacy_sched = kwargs.get("schedule")
            legacy_pos = kwargs.get("position") or kwargs.get("pos") or "WR"
            legacy_prior = kwargs.get("prior_season_stats")
            legacy_scoring = kwargs.get("scoring_settings") or scoring_settings or SCORING
            legacy_actual = kwargs.get("actual_stats")

            # If all_stats was not int but we still have legacy kwargs, use those
            if legacy_season is None:
                legacy_season = kwargs.get("season")
            if legacy_week is None:
                legacy_week = kwargs.get("week")

        # If we have enough to build single row, do it
        if legacy_season is not None and legacy_week is not None and legacy_history is not None:
            row = _build_single_row_legacy(
                season=int(legacy_season),
                week=int(legacy_week),
                player_history=legacy_history or [],
                position=str(legacy_pos),
                pbp_cache=legacy_pbp,
                schedule=legacy_sched,
                prior_season_stats=legacy_prior,
                scoring_settings=legacy_scoring,
                actual_stats=legacy_actual,
            )
            # For backwards compat, if caller expects dict, return dict wrapped in list but also allow dict handling
            # We return list with one dict; caller can do rows[0] if needed. To support `-> dict` expectation, we also allow returning dict when args positional indicates single.
            # Check if caller used legacy positional signature (all_stats is int) -> return dict directly for compatibility
            if isinstance(all_stats, int):
                return row  # type: ignore[return-value]
            return [row]

        # Fall through to batch if legacy detection was false positive
        # Reset to original values for batch processing
        # Need to recover original batch args if we mis-detected
        # If legacy_season etc were not fully resolved, treat original all_stats etc as batch lists
        if isinstance(all_stats, int):
            # Mis-detected, but we already returned. Should not reach here.
            return []

    # --- Batch path ---
    scoring = scoring_settings or SCORING

    if all_stats is None:
        # Try to get from kwargs alternative names
        all_stats = kwargs.get("stats") or kwargs.get("stats_list") or kwargs.get("all_stats") or []
    if all_schedules is None:
        all_schedules = kwargs.get("schedules") or kwargs.get("schedule") or kwargs.get("all_schedules") or []
    if pbp_features is None:
        pbp_features = kwargs.get("pbp_features") or kwargs.get("pbp_cache") or kwargs.get("pbp") or []

    # Allow pbp_features to be dict by season
    if isinstance(pbp_features, dict):
        # flatten dict values
        flat = []
        for v in pbp_features.values():
            if isinstance(v, list):
                flat.extend(v)
            else:
                flat.append(v)
        pbp_features = flat

    if seasons is not None:
        # filter stats/schedules to requested seasons
        try:
            seasons_set = set(int(s) for s in seasons)
            all_stats = [s for s in all_stats if int(s.get("season", 0) or 0) in seasons_set] if all_stats else []
            all_schedules = [g for g in all_schedules if int(g.get("season", 0) or 0) in seasons_set] if all_schedules else []
            # pbp: keep only those seasons if season field exists
            if pbp_features:
                filtered_pbp = []
                for r in pbp_features:
                    sec = r.get("season")
                    if sec is None:
                        filtered_pbp.append(r)
                    else:
                        try:
                            if int(sec) in seasons_set:
                                filtered_pbp.append(r)
                        except Exception:
                            filtered_pbp.append(r)
                pbp_features = filtered_pbp
        except Exception:
            pass

    # Build indexes
    ctx_by_season = _build_schedule_context_by_season(all_schedules or [])
    pbp_idx = _index_pbp(pbp_features)

    # Group stats by (player_id, season)
    player_season_games: Dict[tuple, List[Dict]] = defaultdict(list)
    # Keep all REG stats for history, but filter target weeks later
    reg_stats_all = []
    for s in all_stats or []:
        if s.get("season_type") != "REG":
            continue
        pos = s.get("position", "")
        if pos not in ("QB", "RB", "WR", "TE", "K"):
            continue
        # season must be int
        season = s.get("season")
        if season is None:
            continue
        try:
            season = int(season)
        except Exception:
            continue
        wk = s.get("week")
        if wk is None:
            continue
        try:
            wk = int(wk)
        except Exception:
            continue
        # Require player_id
        pid = s.get("player_id")
        if not pid:
            continue
        reg_stats_all.append(s)
        player_season_games[(str(pid), season)].append(s)

    # Sort each player's season games by week
    for k in player_season_games:
        player_season_games[k].sort(key=lambda x: int(x.get("week", 0) or 0))

    # Prior season index for blending (already in player_season_games)
    rows: List[Dict] = []

    # Filter target rows: weeks 4-18
    target_stats = [s for s in reg_stats_all if min_week <= int(s.get("week", 0) or 0) <= max_week]

    # For prior lookup we need quick access to season-1 list
    for target in target_stats:
        pid = str(target.get("player_id"))
        season = int(target.get("season"))
        week = int(target.get("week"))
        position = target.get("position", "")
        team = target.get("team") or target.get("recent_team") or ""
        if not team:
            # fallback to last history team if target team missing
            hist_key = (pid, season)
            hist_list = player_season_games.get(hist_key, [])
            # find most recent history before week
            prior_hist = [h for h in hist_list if int(h.get("week", 0) or 0) < week]
            if prior_hist:
                team = prior_hist[-1].get("team") or prior_hist[-1].get("recent_team") or ""
        if not team:
            # cannot determine team, skip? but we should still produce row with empty team and zero vegas
            team = ""

        # history < target_week for same season
        hist_key = (pid, season)
        all_games_for_player_season = player_season_games.get(hist_key, [])
        history = [g for g in all_games_for_player_season if int(g.get("week", 0) or 0) < week]
        history.sort(key=lambda x: int(x.get("week", 0) or 0))

        # prior season stats for early weeks
        prior = player_season_games.get((pid, season - 1), [])
        # prior should be only REG already
        prior_sorted = sorted(prior, key=lambda x: int(x.get("week", 0) or 0))

        # game context for this team/week/season
        ctx = ctx_by_season.get(season, {}).get((team, week))
        if ctx is None:
            # try to find context without season grouping if schedule was missing season?
            # fallback to any season's context with same team/week
            found = None
            for sev, cmap in ctx_by_season.items():
                if (team, week) in cmap:
                    found = cmap[(team, week)]
                    break
            ctx = found or {"implied_total": 0.0, "spread": 0.0, "wind": 0.0, "temp": 65.0, "is_dome": 0}

        # PBP history
        pbp_hist = _get_pbp_history(pbp_idx, pid, season, week)
        pbp_wavg = _pbp_wavg_features(pbp_hist)

        # trend
        trend = _trend_features(history, position)

        # projected features
        proj_feats = _projected_features(history, position, prior_sorted, ctx.get("implied_total", 0), ctx.get("wind", 0), ctx.get("temp"))

        # one-hot
        pos_onehot = {f"position_{p}": 1 if position == p else 0 for p in ("QB", "RB", "WR", "TE", "K")}

        # target actual points
        try:
            target_pts = float(calculate_fantasy_points(_map_to_scoring_stats(target), scoring))
        except Exception:
            target_pts = 0.0

        games_played = len(history)

        row = {
            "player_id": pid,
            "player_display_name": target.get("player_display_name", "") or target.get("player_name", ""),
            "season": season,
            "week": week,
            "team": team,
            "position": position,
            "games_played": int(games_played),
            "implied_total": float(ctx.get("implied_total", 0) or 0),
            "spread": float(ctx.get("spread", 0) or 0),
            "wind": float(ctx.get("wind", 0) or 0),
            "temp": float(ctx.get("temp", 65) or 65),
            "is_dome": int(ctx.get("is_dome", 0)),
            "target": float(target_pts),
            "actual_points": float(target_pts),
            # keep actual raw for debugging but not as feature
            "actual_stats": target,  # for debugging, not used as feature
            **pbp_wavg,
            **trend,
            **proj_feats,
            **pos_onehot,
        }
        # Ensure expected keys exist (fill missing)
        for k in EXPECTED_FEATURE_KEYS:
            if k not in row:
                if k in ("team", "position", "player_id", "player_display_name"):
                    row[k] = row.get(k, "")
                else:
                    row[k] = 0.0

        rows.append(row)

    # Sort rows by season, week, player_id for determinism
    rows.sort(key=lambda r: (r.get("season", 0), r.get("week", 0), r.get("player_id", "")))
    return rows

