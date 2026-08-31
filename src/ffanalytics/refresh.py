"""Refresh job: pulls from each adapter independently, logs per-source
success/failure to refresh_log, and never lets one source's failure abort
the others — matches design spec's stale-cache-fallback error handling."""

import sqlite3
import json
from datetime import datetime, timedelta

import logging

from ffanalytics import config
from ffanalytics.adapters import nflverse, sleeper, weather

logger = logging.getLogger(__name__)

STADIUM_COORDS: dict[str, tuple[float, float]] = {
    "ARI": (33.5276, -112.2626), "ATL": (33.7554, -84.4010),
    "BAL": (39.2780, -76.6227),  "BUF": (42.7738, -78.7870),
    "CAR": (35.2258, -80.8528),  "CHI": (41.8623, -87.6167),
    "CIN": (39.0955, -84.5160),  "CLE": (41.5061, -81.6995),
    "DAL": (32.7473, -97.0945),  "DEN": (39.7439, -105.0201),
    "DET": (42.3400, -83.0456),  "GB":  (44.5013, -88.0622),
    "HOU": (29.6847, -95.4107),  "IND": (39.7601, -86.1639),
    "JAX": (30.3239, -81.6373),  "KC":  (39.0489, -94.4839),
    "LAC": (33.9535, -118.3392), "LAR": (33.9535, -118.3392),
    "LV":  (36.0909, -115.1833), "MIA": (25.9580, -80.2389),
    "MIN": (44.9736, -93.2575),  "NE":  (42.0909, -71.2643),
    "NO":  (29.9511, -90.0812),  "NYG": (40.8128, -74.0742),
    "NYJ": (40.8128, -74.0742), "PHI": (39.9008, -75.1675),
    "PIT": (40.4468, -80.0158),  "SEA": (47.5952, -122.3316),
    "SF":  (37.4033, -121.9694), "TB":  (27.9759, -82.5033),
    "TEN": (36.1665, -86.7713),  "WAS": (38.9076, -76.8645),
}


def _compute_nfl_week(now: datetime | None = None) -> int:
    """Compute approximate NFL week number (1-18) given a date.
    Season starts on the weekend after Labor Day (first Monday in September).
    This is a simplification; for logging only."""
    if now is None:
        now = datetime.now()
    # Labor Day: first Monday in September
    september_first = datetime(now.year, 9, 1)
    # Find first Monday in September
    # weekday() where Monday is 0, Sunday is 6
    offset_to_monday = (0 - september_first.weekday()) % 7
    labor_day = september_first + timedelta(days=offset_to_monday)
    # Season starts on the Monday after Labor Day (the start of the first week).
    season_start = labor_day + timedelta(days=7)  # Monday of first week
    # If now is before season start, return 0 (preseason)
    if now < season_start:
        return 0
    # Compute days since season start
    days_since = (now - season_start).days
    week_num = days_since // 7 + 1
    # Clamp to 1-18
    if week_num < 1:
        return 1
    if week_num > 18:
        return 18
    return week_num


def _log(conn: sqlite3.Connection, source: str, success: bool, error_message: str | None, ran_at_iso: str) -> None:
    conn.execute(
        "INSERT INTO refresh_log (source, ran_at, success, error_message) VALUES (?, ?, ?, ?)",
        (source, ran_at_iso, 1 if success else 0, error_message),
    )
    conn.commit()


def run_refresh(
    conn: sqlite3.Connection,
    season: int,
    sleeper_session=None,
    nfl_module=None,
    ran_at_iso: str = "",
    stats_season: int | None = None,
) -> dict:
    if stats_season is None:
        stats_season = season
    result = {}

    try:
        sleeper.get_league_settings(config.LEAGUE_ID, session=sleeper_session)
        sleeper.get_rosters(config.LEAGUE_ID, session=sleeper_session)
        sleeper.get_injury_statuses(session=sleeper_session)
        _log(conn, "sleeper", True, None, ran_at_iso)
        result["sleeper"] = True
    except Exception as exc:
        _log(conn, "sleeper", False, str(exc), ran_at_iso)
        result["sleeper"] = False

    try:
        nflverse.get_weekly_player_stats(stats_season, nfl_module=nfl_module)
        _log(conn, "nflverse", True, None, ran_at_iso)
        result["nflverse"] = True
    except Exception as exc:
        _log(conn, "nflverse", False, str(exc), ran_at_iso)
        result["nflverse"] = False

    try:
        from ffanalytics.rating_updates import update_team_ratings_from_results
        current_week = _compute_nfl_week()
        # Preseason (week=0): backfill full prior season for baseline ratings
        rating_weeks = range(1, current_week + 1) if current_week > 0 else range(1, 19)
        for wk in rating_weeks:
            update_team_ratings_from_results(conn, stats_season, wk, nfl_module=nfl_module)
        _log(conn, "ratings", True, None, ran_at_iso)
        result["ratings"] = True
    except Exception as exc:
        _log(conn, "ratings", False, str(exc), ran_at_iso)
        result["ratings"] = False

    return result


def run_refresh_with_data(
    conn: sqlite3.Connection,
    season: int,
    sleeper_session=None,
    nfl_module=None,
    ran_at_iso: str = "",
    stats_season: int | None = None,
) -> tuple[dict, dict]:
    """Run refresh and return both status results and the actual data fetched.

    season: the league season (2026) — used for Sleeper, schedule, DB storage.
    stats_season: the season with completed nflreadpy data (2025 in preseason).
                  Falls back to season if not provided."""
    if stats_season is None:
        stats_season = season
    data = {}
    status = {}

    # Get Sleeper data
    try:
        league_settings = sleeper.get_league_settings(config.LEAGUE_ID, session=sleeper_session)
        rosters = sleeper.get_rosters(config.LEAGUE_ID, session=sleeper_session)
        injury_status = sleeper.get_injury_statuses(session=sleeper_session)
        current_week = _compute_nfl_week()
        matchups = sleeper.get_league_matchups(config.LEAGUE_ID, current_week, session=sleeper_session)
        data["league_settings"] = league_settings
        data["rosters"] = rosters
        data["injury_status"] = injury_status
        data["matchups"] = matchups
        _log(conn, "sleeper", True, None, ran_at_iso)
        status["sleeper"] = True
    except Exception as exc:
        _log(conn, "sleeper", False, str(exc), ran_at_iso)
        status["sleeper"] = False
        # Set empty defaults on failure
        data["league_settings"] = {"scoring_settings": {}, "roster_positions": []}
        data["rosters"] = []
        data["injury_status"] = {}
        data["matchups"] = []

    # Get NFLverse data
    try:
        player_stats = nflverse.get_weekly_player_stats(stats_season, nfl_module=nfl_module)
        data["player_stats"] = player_stats
        data["model_projections"] = []
        _model_projs: list[dict] = []
        
        # Build stat-level projections for target week using production stat_projector
        try:
            from ffanalytics.stat_projector import build_weekly_projections
            from ffanalytics.scoring import calculate_fantasy_points
            from ffanalytics.adapters import schedule as sched_adapter
            current_wk = _compute_nfl_week()
            target_wk = current_wk if current_wk > 0 else 10
            sched = sched_adapter.get_schedule(season, week=target_wk, nfl_module=nfl_module)
            projs = build_weekly_projections(
                player_stats,
                sched,
                target_week=target_wk,
                scoring_settings=data.get("league_settings", {}).get("scoring_settings", {})
            )
            scoring = data.get("league_settings", {}).get("scoring_settings", {})
            proj_map = {}
            for pr in projs:
                pid = str(pr.get("player_id", ""))
                if pid:
                    fpts = calculate_fantasy_points(pr, scoring)
                    pr["projected_points"] = round(fpts, 2)
                    proj_map[pid] = pr
            
            # Enrich player_stats entries with projected_points from model
            for s in player_stats:
                pid = str(s.get("player_id") or s.get("id") or "")
                if pid in proj_map:
                    s["projected_points"] = proj_map[pid]["projected_points"]
            _model_projs = projs
            data["model_projections"] = projs
        except Exception as p_exc:
            logger.warning(f"Projection model execution warning: {p_exc}")

        _log(conn, "nflverse", True, None, ran_at_iso)
        status["nflverse"] = True
    except Exception as exc:
        _log(conn, "nflverse", False, str(exc), ran_at_iso)
        status["nflverse"] = False
        # Set empty default on failure
        data["player_stats"] = []
        data["model_projections"] = []
        _model_projs = []

    # --- Market consensus: Sleeper projections (pts + stats) + FantasyPros ECR/ADP ---
    # Free, local, isolated — failures do not abort refresh; comparison degrades to model-only.
    try:
        from ffanalytics.adapters import fantasypros as fp_adapter
        from ffanalytics.comparison import build_comparison, map_market_to_gsis

        current_wk_m = _compute_nfl_week()
        target_wk_m = current_wk_m if current_wk_m > 0 else 1
        # Sleeper players map (gsis_id crosswalk) — cached fetch, okay to repeat
        try:
            sleeper_players_map = sleeper.get_sleeper_players(session=sleeper_session)
        except Exception:
            sleeper_players_map = {}
        # Market projections keyed by sleeper_id -> pts_ppr + stats
        try:
            market_raw = sleeper.get_sleeper_projections(season, target_wk_m, session=sleeper_session)
        except Exception:
            market_raw = {}
        market_by_gsis = {}
        try:
            if market_raw and sleeper_players_map:
                market_by_gsis = map_market_to_gsis(market_raw, sleeper_players_map)
        except Exception:
            market_by_gsis = {}
        # FantasyPros ECR/ADP ranks — prefer local CSV exports (full 519 ECR + 695 ADP)
        # over free API tier (10 DST limit). CSVs are checked at repo root / data.
        try:
            try:
                from ffanalytics.adapters.fantasypros_csv import get_fantasypros_csv_players
                csv_players = get_fantasypros_csv_players()
            except Exception as _csv_e:
                csv_players = []
                logger.info(f"FantasyPros CSV not loaded: {_csv_e}")
            if csv_players:
                fpros_players_list = csv_players
                logger.info(f"FantasyPros CSV loaded: {len(csv_players)} players (ECR+ADP full)")
            else:
                fpros_players_list = fp_adapter.get_fantasypros_players()
        except Exception:
            fpros_players_list = []
        # FantasyPros season projections CSVs — 596 players season totals (YDS/TDS etc) + FPTS
        # Provides full stat season market for Auction vs Sleeper weekly-only (98 starters).
        fp_projections_map = {}
        try:
            from ffanalytics.adapters.fantasypros_projections import get_fantasypros_projections_map
            fp_projections_map = get_fantasypros_projections_map() or {}
            if fp_projections_map:
                logger.info(f"FantasyPros projections CSV loaded: {len(fp_projections_map)} season entries")
        except Exception as _proj_e:
            logger.info(f"FantasyPros projections CSV not loaded: {_proj_e}")
            fp_projections_map = {}
        data["sleeper_players_map"] = sleeper_players_map  # not stored, used for comparison only
        data["market_by_gsis"] = market_by_gsis
        data["fpros_players"] = fpros_players_list if isinstance(fpros_players_list, list) else []
        data["fp_projections_map"] = fp_projections_map
        # StatsGuy real-trade market (free 500, non_sf_redraft) — true market value 0-10000 via name+team join
        statsguy_rows: list[dict] = []
        try:
            from ffanalytics.adapters.statsguy import get_statsguy_all
            statsguy_rows = get_statsguy_all(format="non_sf_redraft", limit=500) or []
            if statsguy_rows:
                logger.info(f"StatsGuy loaded: {len(statsguy_rows)} rows (non_sf_redraft 12-team PPR) — name+team join for full coverage")
        except Exception as _sg_e:
            logger.info(f"StatsGuy not loaded: {_sg_e}")
            statsguy_rows = []
        data["statsguy_rows"] = statsguy_rows
        # Build enriched comparison rows (model vs market + ranks)
        # Pass FP season projections map (596 season totals) for Auction season stats + StatsGuy real-trade values
        try:
            from ffanalytics.comparison import build_comparison as _build_comp
            data["comparison"] = _build_comp(_model_projs, market_by_gsis, fpros_players_list, None, fp_projections_map, statsguy_rows)
        except Exception as cmp_exc:
            logger.warning(f"Comparison build failed: {cmp_exc}")
            data["comparison"] = []

        _log(conn, "market", True, None, ran_at_iso)
        result["market"] = True
    except Exception as exc:
        _log(conn, "market", False, str(exc), ran_at_iso)
        result["market"] = False
        data["comparison"] = []
        data["market_by_gsis"] = {}
        data["fpros_players"] = []

    # Fetch news and trending
    try:
        from ffanalytics.adapters import news, fantasypros
        trending = news.get_trending_adds(session=sleeper_session)
        detailed_injuries = news.get_injury_with_practice(stats_season, nfl_module=nfl_module)
        fp_news = fantasypros.get_fantasypros_news(limit=25)
        data["trending"] = trending
        data["detailed_injuries"] = detailed_injuries
        data["fantasypros_news"] = fp_news
        _log(conn, "news", True, None, ran_at_iso)
        status["news"] = True
    except Exception as exc:
        _log(conn, "news", False, str(exc), ran_at_iso)
        status["news"] = False
        data["trending"] = []
        data["detailed_injuries"] = []
        data["fantasypros_news"] = []

    # Update team ratings from completed games
    try:
        from ffanalytics.rating_updates import update_team_ratings_from_results
        current_week = _compute_nfl_week()
        rating_weeks = range(1, current_week + 1) if current_week > 0 else range(1, 19)
        for wk in rating_weeks:
            update_team_ratings_from_results(conn, stats_season, wk, nfl_module=nfl_module)
        _log(conn, "ratings", True, None, ran_at_iso)
        status["ratings"] = True
    except Exception as exc:
        _log(conn, "ratings", False, str(exc), ran_at_iso)
        status["ratings"] = False

    # Store fetched data in the database
    try:
        # Compute week for rosters (based on run time)
        now = datetime.fromisoformat(ran_at_iso) if ran_at_iso else datetime.now()
        week = _compute_nfl_week(now)

        # Store league_settings (one row per season)
        conn.execute(
            """INSERT OR REPLACE INTO league_settings (season, data)
               VALUES (?, ?)""",
            (season, json.dumps(data["league_settings"])),
        )
        # Store rosters (one row per season per week)
        conn.execute(
            """INSERT INTO rosters (season, week, data)
               VALUES (?, ?, ?)""",
            (season, week, json.dumps(data["rosters"])),
        )
        # Store injury_status (one row per season)
        conn.execute(
            """INSERT INTO injury_status (season, data)
               VALUES (?, ?)""",
            (season, json.dumps(data["injury_status"])),
        )
        # Store player_stats (we store the entire list as JSON for the season, week=0)
        conn.execute(
            """INSERT INTO player_stats (season, week, data)
               VALUES (?, ?, ?)""",
            (season, 0, json.dumps(data["player_stats"])),
        )

        # Store matchups
        if data.get("matchups"):
            for m in data["matchups"]:
                conn.execute(
                    """INSERT OR REPLACE INTO sleeper_matchups
                       (season, week, roster_id, matchup_id, points, starters)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (
                        season, week,
                        m.get("roster_id"),
                        m.get("matchup_id"),
                        m.get("points"),
                        json.dumps(m.get("starters", [])),
                    ),
                )

        # Store news/trending data
        if data.get("trending"):
            conn.execute(
                """INSERT INTO news_data (season, week, kind, data, fetched_at)
                   VALUES (?, ?, 'trending', ?, ?)""",
                (season, week, json.dumps(data["trending"]), now.isoformat()),
            )
        if data.get("detailed_injuries"):
            conn.execute(
                """INSERT INTO news_data (season, week, kind, data, fetched_at)
                   VALUES (?, ?, 'injuries', ?, ?)""",
                (season, week, json.dumps(data["detailed_injuries"]), now.isoformat()),
            )
        if data.get("fantasypros_news"):
            conn.execute(
                """INSERT INTO news_data (season, week, kind, data, fetched_at)
                   VALUES (?, ?, 'fantasypros_news', ?, ?)""",
                (season, week, json.dumps(data["fantasypros_news"]), now.isoformat()),
            )
        # Market consensus (model vs Sleeper pts+stats vs FantasyPros ECR/ADP) — hub reads read-only
        if data.get("comparison"):
            try:
                conn.execute(
                    """CREATE TABLE IF NOT EXISTS market_consensus (
                        season INTEGER NOT NULL,
                        week INTEGER NOT NULL,
                        data JSON NOT NULL,
                        fetched_at TEXT NOT NULL
                    )"""
                )
                conn.execute(
                    """INSERT INTO market_consensus (season, week, data, fetched_at)
                       VALUES (?, ?, ?, ?)""",
                    (season, week, json.dumps(data["comparison"]), now.isoformat()),
                )
            except Exception as mc_exc:
                logger.warning(f"market_consensus store failed: {mc_exc}")
        # Also store FPros ranks + market stats raw for debugging (best-effort, optional)
        if data.get("fpros_players"):
            try:
                conn.execute(
                    """INSERT INTO news_data (season, week, kind, data, fetched_at)
                       VALUES (?, ?, 'fpros_ranks', ?, ?)""",
                    (season, week, json.dumps(data["fpros_players"][:800]), now.isoformat()),
                )
            except Exception:
                pass

        # Resolve outcomes for shadow recommendations using actual player stats
        try:
            from ffanalytics.shadow import evaluate_unresolved_shadow_recommendations
            resolved_count = evaluate_unresolved_shadow_recommendations(
                conn,
                data.get("player_stats", []),
                data.get("league_settings", {}).get("scoring_settings"),
            )
            if resolved_count > 0:
                logger.info(f"Resolved {resolved_count} pending shadow recommendation outcomes.")
        except Exception as shadow_exc:
            logger.warning(f"Shadow outcome resolution failed: {shadow_exc}")

        # Store weather data for games (if we have player stats with team info)
        if data["player_stats"]:
            try:
                # Extract unique team abbreviations from player stats
                teams = set()
                for player in data["player_stats"]:
                    if player.get("recent_team"):
                        teams.add(player["recent_team"])
                    if player.get("opponent_team"):
                        teams.add(player["opponent_team"])

                for team in teams:
                    coords = STADIUM_COORDS.get(team)
                    if not coords:
                        continue
                    lat, lon = coords
                    game_time_iso = now.isoformat()

                    forecast = weather.get_forecast(lat, lon, game_time_iso)
                    if forecast is not None:
                        conn.execute(
                            """INSERT INTO weather (lat, lon, game_time_iso, temp_f, wind_mph, precip_prob, fetched_at)
                               VALUES (?, ?, ?, ?, ?, ?, ?)""",
                            (
                                lat,
                                lon,
                                game_time_iso,
                                forecast.get("temp_f"),
                                forecast.get("wind_mph"),
                                forecast.get("precip_prob"),
                                datetime.now().isoformat(),
                            ),
                        )
            except Exception:
                logger.exception("Weather fetch/store failed, continuing with other data")

        conn.commit()
    except Exception:
        logger.exception("Failed to store refresh data in DB")

    return status, data