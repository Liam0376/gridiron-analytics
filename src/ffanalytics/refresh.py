"""Refresh job: pulls from each adapter independently, logs per-source
success/failure to refresh_log, never lets one source's failure abort
the others."""

import sqlite3
import json
import math
from datetime import datetime, timedelta

import logging

from ffanalytics import config
from ffanalytics.config import compute_nfl_week
from ffanalytics.adapters import nflverse, sleeper, weather

logger = logging.getLogger(__name__)


def _sanitize_for_json(obj):
    """Recursively replace NaN/Inf floats with 0 so json.dumps never emits
    non-standard NaN/Infinity tokens (SQLite JSON + json.loads choke on them).
    why: nflverse Polars nulls surface as float('nan') in list[dict] rows.
    Mirrors scripts/seed_demo.py:61-65 logic.
    """
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return 0
        return obj
    if isinstance(obj, dict):
        return {k: _sanitize_for_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_sanitize_for_json(v) for v in obj]
    return obj


def _safe_dumps(obj) -> str:
    return json.dumps(_sanitize_for_json(obj))


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
        current_week = compute_nfl_week()
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
    # season: the league season (2026); stats_season: nflreadpy data season
    # (2025 in preseason). Falls back to season if not provided.
    if stats_season is None:
        stats_season = season
    data = {}
    status = {}

    # Get Sleeper data
    try:
        league_settings = sleeper.get_league_settings(config.LEAGUE_ID, session=sleeper_session)
        try:
            users = sleeper.get_users(config.LEAGUE_ID, session=sleeper_session)
            league_settings["users"] = users
        except Exception as u_exc:
            logger.warning(f"Failed to fetch sleeper users: {u_exc}")
            league_settings["users"] = []
        rosters = sleeper.get_rosters(config.LEAGUE_ID, session=sleeper_session)
        injury_status = sleeper.get_injury_statuses(session=sleeper_session)
        current_week = compute_nfl_week()
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
        data["league_settings"] = {"scoring_settings": {}, "roster_positions": [], "users": []}
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
            current_wk = compute_nfl_week()
            # Preseason (week=0): fall back to week 1 so projections don't target mid-season bye weeks.
            target_wk = max(1, current_wk)
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
            
            # Build enriched_player_stats WITHOUT mutating adapter outputs.
            # Adapters (nflverse.get_weekly_player_stats) may be reused across
            # calls or shared with callers; we copy each dict and attach the
            # model's projected_points from proj_map, then store the enriched
            # copy in the DB / cache. Original player_stats stays untouched.
            enriched_player_stats: list[dict] = []
            for s in player_stats:
                pid = str(s.get("player_id") or s.get("id") or "")
                enriched = dict(s)
                if pid in proj_map:
                    enriched["projected_points"] = proj_map[pid]["projected_points"]
                enriched_player_stats.append(enriched)
            _model_projs = projs
            data["model_projections"] = projs
            data["player_stats"] = enriched_player_stats
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

        current_wk_m = compute_nfl_week()
        target_wk_m = current_wk_m if current_wk_m > 0 else 1
        # Sleeper players map (gsis_id crosswalk) — cached fetch, okay to repeat
        try:
            sleeper_players_map = sleeper.get_sleeper_players(session=sleeper_session)
        except Exception:
            logger.exception("refresh: sleeper_players_map fetch failed")
            sleeper_players_map = {}
        # Market projections keyed by sleeper_id -> pts_ppr + stats
        try:
            market_raw = sleeper.get_sleeper_projections(season, target_wk_m, session=sleeper_session)
        except Exception:
            logger.exception("refresh: sleeper projections fetch failed")
            market_raw = {}
        market_by_gsis = {}
        try:
            if market_raw and sleeper_players_map:
                market_by_gsis = map_market_to_gsis(market_raw, sleeper_players_map)
        except Exception:
            logger.exception("refresh: map_market_to_gsis failed")
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
            logger.exception("refresh: fantasypros_players fetch failed")
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
            data["comparison"] = _build_comp(_model_projs, market_by_gsis, fpros_players_list, sleeper_players_map, fp_projections_map, statsguy_rows)
        except Exception as cmp_exc:
            logger.warning(f"Comparison build failed: {cmp_exc}")
            data["comparison"] = []

        _log(conn, "market", True, None, ran_at_iso)
        status["market"] = True
    except Exception as exc:
        _log(conn, "market", False, str(exc), ran_at_iso)
        status["market"] = False
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
        current_week = compute_nfl_week()
        rating_weeks = range(1, current_week + 1) if current_week > 0 else range(1, 19)
        for wk in rating_weeks:
            update_team_ratings_from_results(conn, stats_season, wk, nfl_module=nfl_module)
        _log(conn, "ratings", True, None, ran_at_iso)
        status["ratings"] = True
    except Exception as exc:
        _log(conn, "ratings", False, str(exc), ran_at_iso)
        status["ratings"] = False

    # Store fetched data in the database
    # STORE-ON-SUCCESS: skip INSERT for a source when its status=false to
    # preserve last-good snapshot (previously rosters=[] then INSERT OR REPLACE
    # clobbered last-good on source failure). Each block below checks
    # status.get(...) and logs skip instead of writing empty defaults.
    try:
        now = datetime.fromisoformat(ran_at_iso) if ran_at_iso else datetime.now()
        week = compute_nfl_week(now)
        # Stray 2026|10 finding (2026-09-03 audit): market_consensus 2026|10
        # (fetched 2026-08-30, 502 rows, BAL@LAC week-10 matchup) + player_stats
        # 2026|10 (452 rows) exist in local DB. Current compute_nfl_week returns
        # 1 preseason (never 10), so NOT caused by current compute; legacy
        # seed_demo week-10 inserts (docstring still says "2024 week 10") are the
        # likely source. Guard below forces preseason market week to min(week,1)
        # so future preseason runs never write week>1.
        # Preseason cross-season detection (mirror stat_projector.py C2): league
        # season (2026) != stats season (2025) → preseason, clamp market week.
        try:
            _is_preseason = (stats_season is not None and stats_season != season)
        except Exception:
            _is_preseason = False
        market_week = min(week, 1) if _is_preseason else week

        if status.get("sleeper"):
            conn.execute(
                """INSERT OR REPLACE INTO league_settings (season, data)
                   VALUES (?, ?)""",
                (season, _safe_dumps(data["league_settings"])),
            )
        else:
            logger.warning("refresh: sleeper status=false — skipping league_settings INSERT (preserve last-good)")
        # UNIQUE(season, week) on rosters — INSERT OR REPLACE so latest snapshot wins.
        if status.get("sleeper"):
            conn.execute(
                """INSERT OR REPLACE INTO rosters (season, week, data)
                   VALUES (?, ?, ?)""",
                (season, week, _safe_dumps(data["rosters"])),
            )
        else:
            logger.warning("refresh: sleeper status=false — skipping rosters INSERT (preserve last-good)")
        # keep ~2*current_week snapshots. Floor at 1 (per file max(1, ...) convention
        # like target_wk above): max(0, week-1) kept everything when week=1
        # (threshold 0, DELETE week<0 deletes nothing, week=0 blob never pruned);
        # max(1, week-1) drops week=0 when week=1 (threshold 1, DELETE week<1).
        try:
            prune_threshold = max(1, week - 1)
            conn.execute(
                """DELETE FROM rosters
                   WHERE season = ? AND week < ?""",
                (season, prune_threshold),
            )
        except Exception as _prune_exc:
            logger.warning(f"rosters retention prune failed: {_prune_exc}")
        # P0 idempotency: injury_status UNIQUE(season), player_stats
        # UNIQUE(season, week) — plain INSERT crashed on second refresh of the
        # same season/week (UNIQUE constraint failed); OR REPLACE matches
        # schema.sql so re-refresh overwrites instead of erroring.
        # STORE-ON-SUCCESS: skip when source failed (preserve last-good).
        if status.get("sleeper"):
            conn.execute(
                """INSERT OR REPLACE INTO injury_status (season, data)
                   VALUES (?, ?)""",
                (season, _safe_dumps(data["injury_status"])),
            )
        else:
            logger.warning("refresh: sleeper status=false — skipping injury_status INSERT (preserve last-good)")
        if status.get("nflverse"):
            conn.execute(
                """INSERT OR REPLACE INTO player_stats (season, week, data)
                   VALUES (?, ?, ?)""",
                (season, 0, _safe_dumps(data["player_stats"])),
            )
        else:
            logger.warning("refresh: nflverse status=false — skipping player_stats INSERT (preserve last-good)")

        if status.get("sleeper") and data.get("matchups"):
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
                        _safe_dumps(m.get("starters", [])),
                    ),
                )
        elif not status.get("sleeper"):
            logger.warning("refresh: sleeper status=false — skipping sleeper_matchups INSERT (preserve last-good)")

        # P0 idempotency: news_data UNIQUE(season, week, kind) — OR REPLACE so
        # re-refresh of the same week/kind overwrites instead of UNIQUE-fail.
        # STORE-ON-SUCCESS: skip news kinds when news source failed.
        if status.get("news") and data.get("trending"):
            conn.execute(
                """INSERT OR REPLACE INTO news_data (season, week, kind, data, fetched_at)
                   VALUES (?, ?, 'trending', ?, ?)""",
                (season, week, _safe_dumps(data["trending"]), now.isoformat()),
            )
        if status.get("news") and data.get("detailed_injuries"):
            conn.execute(
                """INSERT OR REPLACE INTO news_data (season, week, kind, data, fetched_at)
                   VALUES (?, ?, 'injuries', ?, ?)""",
                (season, week, _safe_dumps(data["detailed_injuries"]), now.isoformat()),
            )
        if status.get("news") and data.get("fantasypros_news"):
            conn.execute(
                """INSERT OR REPLACE INTO news_data (season, week, kind, data, fetched_at)
                   VALUES (?, ?, 'fantasypros_news', ?, ?)""",
                (season, week, _safe_dumps(data["fantasypros_news"]), now.isoformat()),
            )
        if not status.get("news"):
            logger.warning("refresh: news status=false — skipping news_data INSERTs (preserve last-good)")
        if status.get("market") and data.get("comparison"):
            try:
                # NOTE: market_consensus DDL intentionally left here as a lazy
                # safety net (api POST /refresh never calls init_schema, so a
                # fresh DB would lack the table). schema.sql is the canonical
                # DDL + db._apply_migrations v3 backfills pre-P0 DBs; this
                # IF NOT EXISTS is redundant-but-harmless. Insert is
                # OR REPLACE to match PRIMARY KEY(season, week).
                # Fixed: lazy DDL now includes PRIMARY KEY(season, week) matching
                # schema.sql (previously missing PK → duplicate week rows on fresh DBs).
                conn.execute(
                    """CREATE TABLE IF NOT EXISTS market_consensus (
                        season INTEGER NOT NULL,
                        week INTEGER NOT NULL,
                        data JSON NOT NULL,
                        fetched_at TEXT NOT NULL,
                        PRIMARY KEY (season, week)
                    )"""
                )
                conn.execute(
                    """INSERT OR REPLACE INTO market_consensus (season, week, data, fetched_at)
                       VALUES (?, ?, ?, ?)""",
                    (season, market_week, _safe_dumps(data["comparison"]), now.isoformat()),
                )
            except Exception as mc_exc:
                logger.warning(f"market_consensus store failed: {mc_exc}")
        elif not status.get("market"):
            logger.warning("refresh: market status=false — skipping market_consensus INSERT (preserve last-good)")
        # Also store FPros ranks + market stats raw for debugging (best-effort, optional)
        if status.get("market") and data.get("fpros_players"):
            try:
                conn.execute(
                    """INSERT OR REPLACE INTO news_data (season, week, kind, data, fetched_at)
                       VALUES (?, ?, 'fpros_ranks', ?, ?)""",
                    (season, week, _safe_dumps(data["fpros_players"][:800]), now.isoformat()),
                )
            except Exception:
                logger.exception("refresh: fpros_ranks insert failed")
        # Retention prunes mirroring rosters prune above — news/market rows are
        # per-(season, week, kind) snapshots; without pruning every refresh
        # week accumulates forever on this $0 local SQLite file.
        try:
            conn.execute(
                """DELETE FROM news_data WHERE season = ? AND week < ?""",
                (season, prune_threshold),
            )
            conn.execute(
                """DELETE FROM market_consensus WHERE season = ? AND week < ?""",
                (season, prune_threshold),
            )
            # player_stats retention: keep trailing 8 season-week blobs max,
            # mirror rosters style (DELETE week < threshold). 8-week window covers
            # ~half season of weekly snapshots on $0 local SQLite; older blobs
            # are reproducible from data/nfl_cache/. Threshold floor 1 per file
            # convention (see prune_threshold above).
            try:
                player_prune_threshold = max(1, week - 7)
                conn.execute(
                    """DELETE FROM player_stats WHERE season = ? AND week < ? AND week != 0""",
                    (season, player_prune_threshold),
                )
                # Cap total blobs across seasons to trailing 8 (week=0 baseline blobs
                # excluded above since production stores week=0 full-season cache).
                # Best-effort: keep latest 8 by (season, week) ordering.
                conn.execute(
                    """DELETE FROM player_stats WHERE rowid NOT IN (
                         SELECT rowid FROM player_stats ORDER BY season DESC, week DESC LIMIT 8
                       ) AND (SELECT COUNT(*) FROM player_stats) > 8"""
                )
            except Exception as _pps_exc:
                logger.warning(f"player_stats retention prune failed: {_pps_exc}")
            # refresh_log retention: 30-day TTL (audit history, not live data).
            # why 30 days: covers a full month of daily refresh_job runs for
            # debugging without unbounded growth; older runs are not queried
            # (hub refresh-log shows recent only).
            try:
                log_cutoff = (now - timedelta(days=30)).isoformat()
                conn.execute(
                    "DELETE FROM refresh_log WHERE ran_at < ?",
                    (log_cutoff,),
                )
            except Exception as _log_exc:
                logger.warning(f"refresh_log retention prune failed: {_log_exc}")
        except Exception as _prune_exc2:
            logger.warning(f"news/market retention prune failed: {_prune_exc2}")

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

        if data["player_stats"]:
            try:
                teams = set()
                for player in data["player_stats"]:
                    # nflverse quirk: prefer `team` (current abbreviation);
                    # `recent_team` is stale/lagged for traded players.
                    team_abbr = player.get("team") or player.get("recent_team")
                    if team_abbr:
                        teams.add(team_abbr)
                    if player.get("opponent_team"):
                        teams.add(player["opponent_team"])

                for team in teams:
                    coords = weather.STADIUM_COORDS.get(team)
                    if not coords:
                        continue
                    lat, lon = coords
                    # P0 append-leak note: game_time_iso was now.isoformat()
                    # with microsecond precision, so UNIQUE(lat,lon,
                    # game_time_iso) never hit and every refresh appended ~32
                    # rows (one per team). Normalize to noon of the fetch day
                    # so same-day refreshes dedup to one row per stadium per
                    # date via INSERT OR REPLACE; intraday forecast updates
                    # overwrite rather than accumulate.
                    # tested and REJECTED: keying on full now.isoformat() +
                    # periodic prune only — prune bounds growth but still
                    # inserts 32 rows per refresh instead of 0 extra.
                    game_time_iso = now.replace(
                        hour=12, minute=0, second=0, microsecond=0
                    ).isoformat()

                    forecast = weather.get_forecast(lat, lon, game_time_iso)
                    if forecast is not None:
                        conn.execute(
                            """INSERT OR REPLACE INTO weather (lat, lon, game_time_iso, temp_f, wind_mph, precip_prob, fetched_at)
                               VALUES (?, ?, ?, ?, ?, ?, ?)""",
                            (
                                lat,
                                lon,
                                game_time_iso,
                                _sanitize_for_json(forecast.get("temp_f")),
                                _sanitize_for_json(forecast.get("wind_mph")),
                                _sanitize_for_json(forecast.get("precip_prob")),
                                datetime.now().isoformat(),
                            ),
                        )
                # Retention: weather is daily snapshots; keep trailing 7 days.
                # why 7: covers a full game week + lookahead without unbounded
                # growth on local SQLite. tested and REJECTED: no prune (leak
                # above) and 30-day window (4x rows, no projection gain — model
                # only reads the latest row per stadium).
                try:
                    weather_cutoff = (now - timedelta(days=7)).isoformat()
                    conn.execute(
                        "DELETE FROM weather WHERE fetched_at < ?",
                        (weather_cutoff,),
                    )
                except Exception as _w_prune_exc:
                    logger.warning(f"weather retention prune failed: {_w_prune_exc}")
            except Exception:
                logger.exception("Weather fetch/store failed, continuing with other data")

        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.exception("Failed to store refresh data in DB")

    return status, data