"""Refresh job: pulls from each adapter independently, logs per-source
success/failure to refresh_log, never lets one source's failure abort
the others."""

import sqlite3
import json
import math
import re
from datetime import datetime, timedelta
from pathlib import Path

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
    # Audit 22.0: removed auto-commit here. refresh_log entries now commit
    # with the caller's transaction (run_refresh: explicit commit at end;
    # run_refresh_with_data: single commit at end). The prior auto-commit
    # meant refresh_log said "success=1" even when the main data write
    # rolled back — the audit trail lied.
    conn.execute(
        "INSERT INTO refresh_log (source, ran_at, success, error_message) VALUES (?, ?, ?, ?)",
        (source, ran_at_iso, 1 if success else 0, error_message),
    )


# why suffix strip (user-caught, generic — not one player): Sleeper stores
# "Kenneth Walker", nflverse stores "Kenneth Walker III" — the raw-lowercase
# key never matched, so the current-team patch below silently missed EVERY
# suffixed name (Jr./Sr./II-V), not just this one, leaving stale nflverse
# (prior-season) teams standing after a trade. Strip on both sides so the
# join works regardless of which source (if either) carries the suffix.
_NAME_SUFFIX_RE = re.compile(r"\s+(jr\.?|sr\.?|ii|iii|iv|v)$", re.IGNORECASE)


def _norm_name_pos(name, pos):
    n = _NAME_SUFFIX_RE.sub("", str(name or "").strip()).strip().lower()
    return (n, str(pos or "").upper())


def build_out_gsis_set(sleeper_players: dict, injury_status: dict | None) -> set[str]:
    """GSIS ids of confirmed-Out players (weekly projections zero these).

    Direct gsis_id mapping only — Sleeper entries with gsis_id=None
    (known data gap, cf. build_sleeper_xwalk) degrade to absent, i.e.
    today's behavior, never a crash. Statuses via config.OUT_STATUSES.
    """
    out: set[str] = set()
    try:
        for sid, status in (injury_status or {}).items():
            if not config.is_out_status(status):
                continue
            sp = (sleeper_players or {}).get(str(sid)) or {}
            gsis = sp.get("gsis_id")
            if gsis:
                out.add(str(gsis))
    except Exception:
        logger.warning("refresh: out-gsis build failed, projecting all as available")
    return out


def build_sleeper_team_map(sleeper_players: dict) -> dict:
    """(normalized name, POS) -> current team abbr from Sleeper /players/nfl.

    nflverse rows carry LAST season's team; Sleeper is current (trades, free
    agency). First-seen wins on (name, pos) collisions — documented limit
    (e.g. shared names across positions are split by pos; same-name same-pos
    collisions keep the first row).
    """
    out = {}
    for sp in (sleeper_players or {}).values():
        sp = sp or {}
        team, pos = sp.get("team"), sp.get("position")
        name = sp.get("full_name") or " ".join(
            x for x in (sp.get("first_name"), sp.get("last_name")) if x
        )
        if team and pos and name:
            out.setdefault(_norm_name_pos(name, pos), config.canonical_team(team))
    return out


def write_json_cache(path, rows: list) -> None:
    """Best-effort atomic cache write. default=str because nflverse rows
    carry non-JSON natives (roster birth_date is a datetime.date — caught
    live 2026-09-15: it killed the weekly-rosters cache write and silently
    disabled the gsis team patch). Never raises."""
    try:
        tmp = Path(str(path) + ".tmp")
        tmp.write_text(json.dumps(rows, default=str))
        tmp.replace(path)
    except Exception as exc:
        logger.warning("refresh: cache write failed for %s: %s", path, exc)


def build_gsis_team_map(weekly_rosters: list) -> dict:
    """gsis_id -> current canonical team from nflverse weekly rosters.

    History stat rows carry LAST season's team; this is current (trades,
    free agency) and needs zero name matching. Skips rows without
    gsis/team; latest-week wins on dupes (rosters are weekly snapshots).
    Never raises.
    """
    out = {}
    try:
        for r in weekly_rosters or []:
            r = r or {}
            gsis = str(r.get("gsis_id") or "").strip()
            team = r.get("team")
            if gsis and team:
                out[gsis] = config.canonical_team(team)
    except Exception:
        pass
    return out


def map_fpros_id_to_gsis(playerids_rows: list) -> dict:
    """fantasypros_id -> gsis_id from the nflverse cross-ID spine.

    Exact ECR join key (ecr-baseline spec) — no names involved. Strips
    whitespace (cf. the Sleeper gsis_id leading-space bug), skips rows
    missing either id, first-seen wins. Never raises.
    """
    out = {}
    try:
        for r in playerids_rows or []:
            r = r or {}
            fpid = str(r.get("fantasypros_id") or "").strip()
            gsis = str(r.get("gsis_id") or "").strip()
            if fpid and gsis and fpid not in out:
                out[fpid] = gsis
    except Exception:
        pass
    return out


def gsis_depth_rank(depth_charts: list,
                    positions: tuple = ("QB", "RB", "WR", "TE")) -> dict:
    """gsis_id -> {"team", "position", "rank"} from a depth snapshot.

    Positions restricted to fantasy scope — line depth is not a signal.
    Ranks are normalized to 0-based (starter = 0) to match the repo's
    existing convention (backtest depth arms check rank == 0 for the
    full-share starter); nflverse's native pos_rank is 1-based, converted
    here at the boundary so no caller re-derives it.
    First-seen wins per gsis (a snapshot should have one row per player;
    dedupe is defensive). Never raises.
    """
    out = {}
    try:
        for r in depth_charts or []:
            r = r or {}
            gsis = str(r.get("gsis_id") or "").strip()
            pos = str(r.get("pos_abb") or "").upper()
            if not gsis or pos not in positions or gsis in out:
                continue
            try:
                rank = int(r.get("pos_rank")) - 1
            except Exception:
                continue
            if rank < 0:
                continue
            out[gsis] = {"team": config.canonical_team(r.get("team")),
                         "position": pos, "rank": rank}
    except Exception:
        pass
    return out


def opportunity_features(opp_rows: list) -> dict:
    """Per-(gsis, week) opportunity features from nflverse opportunity rows.

    Returns {(gsis, week_int): {target_share, air_share, wopr, rush_share,
    rec_gap, rec_yd_gap, rec_td_gap, rush_yd_gap, rush_td_gap, rec_xfp,
    rec_exp, rec_yd_exp, rec_td_exp, rush_yd_exp, rush_td_exp,
    pass_yd_gap, pass_td_gap, pass_yd_exp, pass_td_exp}}.
    Team denominators come from the row's own _team columns (exact, no PBP
    parsing, no name matching — player_id IS gsis). WOPR = 1.5*target_share
    + 0.7*air_share (Hermsmeyer). Gaps are actual-minus-expected on the
    week (negative = underperformed expectation = positive-regression
    candidate). Zero denominators -> 0.0. Rows without gsis skipped.
    Week kept as-is (int); the feed includes playoffs (19-22, no
    season_type flag) so consumers filter week<=18 for REG work.
    Never raises.
    """
    def _f(v):
        try:
            f = float(v or 0)
            if f != f or f in (float("inf"), float("-inf")):
                return 0.0
            return f
        except Exception:
            return 0.0

    out = {}
    try:
        for r in opp_rows or []:
            r = r or {}
            gsis = str(r.get("player_id") or "").strip()
            if not gsis:
                continue
            try:
                wk = int(r.get("week"))
            except Exception:
                continue
            ts = _f(r.get("rec_attempt")) / _f(r.get("rec_attempt_team")) \
                if _f(r.get("rec_attempt_team")) > 0 else 0.0
            ash = _f(r.get("rec_air_yards")) / _f(r.get("rec_air_yards_team")) \
                if _f(r.get("rec_air_yards_team")) > 0 else 0.0
            rs = _f(r.get("rush_attempt")) / _f(r.get("rush_attempt_team")) \
                if _f(r.get("rush_attempt_team")) > 0 else 0.0
            out[(gsis, wk)] = {
                "target_share": ts,
                "air_share": ash,
                "wopr": 1.5 * ts + 0.7 * ash,
                "rush_share": rs,
                "rec_gap": _f(r.get("receptions")) - _f(r.get("receptions_exp")),
                "rec_yd_gap": _f(r.get("rec_yards_gained")) - _f(r.get("rec_yards_gained_exp")),
                "rec_td_gap": _f(r.get("rec_touchdown")) - _f(r.get("rec_touchdown_exp")),
                "rush_yd_gap": _f(r.get("rush_yards_gained")) - _f(r.get("rush_yards_gained_exp")),
                "rush_td_gap": _f(r.get("rush_touchdown")) - _f(r.get("rush_touchdown_exp")),
                "rec_xfp": _f(r.get("rec_fantasy_points_exp")),
                "rec_exp": _f(r.get("receptions_exp")),
                "rec_yd_exp": _f(r.get("rec_yards_gained_exp")),
                "rec_td_exp": _f(r.get("rec_touchdown_exp")),
                "rush_yd_exp": _f(r.get("rush_yards_gained_exp")),
                "rush_td_exp": _f(r.get("rush_touchdown_exp")),
                "pass_yd_gap": _f(r.get("pass_yards_gained")) - _f(r.get("pass_yards_gained_exp")),
                "pass_td_gap": _f(r.get("pass_touchdown")) - _f(r.get("pass_touchdown_exp")),
                "pass_yd_exp": _f(r.get("pass_yards_gained_exp")),
                "pass_td_exp": _f(r.get("pass_touchdown_exp")),
            }
    except Exception:
        pass
    return out


def patch_proj_teams(projs: list, team_by_np: dict, opp_map: dict,
                     team_by_gsis: dict | None = None) -> int:
    """Overwrite stale nflverse teams on projection rows with current
    Sleeper teams; remap opponent from the target-week schedule. Mutates rows.
    Returns patched count. Never raises on weird rows (soft-fail per row).

    gsis join first (exact, no name fragility), name map fallback for rows
    without GSIS (Sleeper-id rookie rows). team_by_gsis=None preserves the
    old 3-arg behavior exactly.
    """
    patched = 0
    for pr in projs or []:
        try:
            nt = (team_by_gsis or {}).get(str(pr.get("player_id") or ""))
            if not nt:
                key = _norm_name_pos(
                    pr.get("player_display_name") or pr.get("player_name"),
                    pr.get("position") or pr.get("position_group"),
                )
                nt = (team_by_np or {}).get(key)
            if nt and nt != (pr.get("team") or ""):
                pr["team"] = nt
                pr["recent_team"] = nt
                if opp_map:
                    pr["opponent_team"] = opp_map.get(nt, pr.get("opponent_team", ""))
                patched += 1
        except Exception as exc:
            logger.warning("patch_proj_teams: row failed — %s: %s",
                           pr.get("player_display_name"), exc)
            continue
    return patched


def nflverse_ecr_to_fpros(ecr_row: dict) -> dict:
    """Map a free-ECR row to the fpros shape comparison reads.

    Emits exactly the keys `comparison/_model._fpros_fields` and
    `build_fpros_lookup` consume: rank_ecr_ppr (overall ecr), rank_ecr_pos
    (pos_rank), player_name, team_id, position_id, plus fantasypros_id
    passthrough for the exact join. Weekly ECR has no ADP/tier — None
    (Sleeper ADP fallback downstream still applies). Never raises.
    """
    try:
        r = ecr_row or {}
        pos = str(r.get("pos") or "").upper()
        try:
            ecr = float(r.get("ecr")) if r.get("ecr") is not None else None
        except Exception:
            ecr = None
        try:
            ecr_pos = int(float(r.get("pos_rank"))) if r.get("pos_rank") is not None else None
        except Exception:
            ecr_pos = None
        return {
            "player_name": r.get("player_name") or "",
            "team_id": str(r.get("team") or "").upper(),
            "position_id": pos,
            "rank_ecr_ppr": ecr,
            "rank_ecr_pos": ecr_pos,
            "rank_adp_ppr": None,
            "rank_adp_pos": None,
            "tier": None,
            "fantasypros_id": str(r.get("fantasypros_id") or "").strip() or None,
        }
    except Exception:
        return {}


ROOKIE_SCOPE_POSITIONS = ("QB", "RB", "WR", "TE", "K")


def build_rookie_rows(sleeper_players: dict, have_keys: set, opp_map: dict, week: int) -> list:
    """Explicit-unknown rows for the incoming class (Sleeper years_exp == 0).

    nflverse has no rows for rookies — without this they are invisible
    (unknown) instead of identified. Zero stats + is_empty_projection=True;
    positional-mean imputation stays REJECTED (adds bias on OOS rookies).
    player_id is the Sleeper id (no GSIS exists yet) — hub avatars and roster
    joins resolve on it. have_keys skips anyone already projected.
    """
    rows = []
    for sid, sp in (sleeper_players or {}).items():
        try:
            sp = sp or {}
            pos = str(sp.get("position") or "").upper()
            if pos not in ROOKIE_SCOPE_POSITIONS:
                continue
            if sp.get("years_exp", 99) != 0:
                continue
            if sp.get("active") is False:
                continue
            team = sp.get("team")
            name = sp.get("full_name") or " ".join(
                x for x in (sp.get("first_name"), sp.get("last_name")) if x
            )
            if not team or not name:
                continue
            if _norm_name_pos(name, pos) in (have_keys or set()):
                continue
            rows.append({
                "player_id": str(sid),
                "player_display_name": name,
                "position": pos,
                "position_group": pos,
                "team": config.canonical_team(team),
                "recent_team": config.canonical_team(team),
                "opponent_team": (opp_map or {}).get(config.canonical_team(team), ""),
                "week": week,
                "projected_points": 0.0,
                "is_empty_projection": True,
                "is_rookie_unknown": True,
            })
        except Exception:
            continue
    return rows


def build_sleeper_xwalk(sleeper_players: dict, name_pos_to_gsis: dict | None = None) -> dict:
    """Sleeper id -> GSIS id crosswalk for roster joins.

    League rosters carry Sleeper ids (e.g. "4046"); nflverse stats carry GSIS
    ids (e.g. "00-0033873") — direct dict joins match NOTHING in production
    (verified live: 169 rostered vs 2025 stats universe, 0 overlap), silently
    emptying start/sit, waiver and trade teams. Sleeper entries carry gsis_id;
    this maps it primarily.

    name_pos_to_gsis (optional, {(norm_name, POS): gsis_id} — build from
    nflverse rows via _norm_name_pos) is a fallback for the direct id join:
    user-caught live bug, Sleeper's own gsis_id field is None for some real,
    correctly-rostered players (Kenneth Walker III confirmed — not a code
    bug on either side, just a gap in Sleeper's dataset). Name+pos catches
    what the id join misses; same normalization patch_proj_teams already
    uses, so suffix mismatches (Jr./Sr./II-V) don't reopen this gap.
    """
    out = {}
    for sid, sp in (sleeper_players or {}).items():
        sp = sp or {}
        # why .strip() (user-caught live bug, 2026-09-11): Sleeper's own
        # gsis_id field carries a leading space for ~866/7483 players
        # (confirmed live, e.g. sleeper_id 5859 = A.J. Brown -> " 00-0035676")
        # — untouched, that value never matches nflverse's clean GSIS keys
        # anywhere downstream, so those players silently fell through both
        # the waiver free-agent exclusion (rostered stars leaked in as
        # "free agents") and headshot sleeper_id resolution.
        gsis = (sp.get("gsis_id") or "").strip() or None
        if not gsis and name_pos_to_gsis:
            name = sp.get("full_name") or " ".join(
                x for x in (sp.get("first_name"), sp.get("last_name")) if x
            )
            pos = sp.get("position")
            if name and pos:
                gsis = name_pos_to_gsis.get(_norm_name_pos(name, pos))
        if sid is not None and gsis:
            out[str(sid)] = str(gsis).strip()
    return out


PROPS_RETENTION_DAYS = 180


def prune_props_tables(conn, now_iso: str, ttl_days: int = PROPS_RETENTION_DAYS) -> dict:
    """Delete stale props experiment data. prop_lines past TTL go; RESOLVED
    shadow prop rows past TTL go; UNRESOLVED stay regardless of age (still
    awaiting outcomes — deleting them destroys pending experiment data;
    volume is bounded by manual entry anyway). Cutoff computed in Python
    (lexicographic ISO compare, no SQLite date-function dependence).
    Returns counts. Missing tables (old DBs) => zeros, no raise."""
    from datetime import datetime as _dt, timedelta as _td

    try:
        cutoff = (_dt.fromisoformat(now_iso) - _td(days=ttl_days)).isoformat()
    except Exception:
        return {"prop_lines": 0, "shadow_resolved": 0}
    counts = {"prop_lines": 0, "shadow_resolved": 0}
    try:
        cur = conn.execute("DELETE FROM prop_lines WHERE created_at < ?", (cutoff,))
        counts["prop_lines"] = cur.rowcount or 0
        cur = conn.execute(
            "DELETE FROM shadow_recommendations WHERE kind LIKE 'prop:%' "
            "AND actual_outcome IS NOT NULL AND logged_at < ?",
            (cutoff,),
        )
        counts["shadow_resolved"] = cur.rowcount or 0
        conn.commit()
    except Exception:
        return {"prop_lines": 0, "shadow_resolved": 0}
    return counts


def run_refresh(
    conn: sqlite3.Connection,
    season: int,
    sleeper_session=None,
    nfl_module=None,
    ran_at_iso: str = "",
    stats_season: int | None = None,
    league_id: str | None = None,
) -> dict:
    if stats_season is None:
        stats_season = season
    # why require at call time (not import): multi-league — the id arrives
    # per refresh (POST body / CLI), and config no longer raises at import.
    lid = config.require_league_id(league_id)
    result = {}

    try:
        sleeper.get_league_settings(lid, session=sleeper_session)
        sleeper.get_rosters(lid, session=sleeper_session)
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

    # Audit 22.0: commit refresh_log entries (previously auto-committed by
    # _log(), which caused the audit trail to lie on rollback).
    try:
        conn.commit()
    except Exception:
        pass
    return result


def run_refresh_with_data(
    conn: sqlite3.Connection,
    season: int,
    sleeper_session=None,
    nfl_module=None,
    ran_at_iso: str = "",
    stats_season: int | None = None,
    league_id: str | None = None,
) -> tuple[dict, dict]:
    # season: the league season (2026); stats_season: nflreadpy data season
    # (2025 in preseason). Falls back to season if not provided.
    if stats_season is None:
        stats_season = season
    lid = config.require_league_id(league_id)
    data = {}
    status = {}

    # Get Sleeper data
    try:
        league_settings = sleeper.get_league_settings(lid, session=sleeper_session)
        try:
            users = sleeper.get_users(lid, session=sleeper_session)
            league_settings["users"] = users
        except Exception as u_exc:
            logger.warning(f"Failed to fetch sleeper users: {u_exc}")
            league_settings["users"] = []
        # why draft info here: auction economics (budget, snake vs auction)
        # live in the draft object, not the league object — stash once per
        # refresh so readers (api/proxy) never add per-request Sleeper calls.
        # Additive key, soft-fail to {} (budget falls back to 200).
        try:
            league_settings["draft"] = sleeper.get_draft_info(lid, session=sleeper_session)
        except Exception as d_exc:
            logger.warning(f"Failed to fetch sleeper draft info: {d_exc}")
            league_settings["draft"] = {}
        rosters = sleeper.get_rosters(lid, session=sleeper_session)
        injury_status = sleeper.get_injury_statuses(session=sleeper_session)
        current_week = compute_nfl_week()
        all_matchups: list[dict] = []
        for wk in range(1, 19):
            try:
                wk_matchups = sleeper.get_league_matchups(lid, wk, session=sleeper_session)
                for m in wk_matchups:
                    m["week"] = wk
                all_matchups.extend(wk_matchups)
            except Exception:
                pass
        matchups = all_matchups
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

    # Sleeper players map (id crosswalk + current teams + rookie class) —
    # fetched once, reused by the team patch/rookies below and market
    # consensus further down (which keeps its own fallback if this fails).
    sleeper_players_map: dict = {}
    try:
        sleeper_players_map = sleeper.get_sleeper_players(session=sleeper_session) or {}
    except Exception:
        logger.exception("refresh: sleeper_players_map fetch failed")

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
            # why whole-season, not just target_wk: /games/predictions serves
            # any requested week from cache (api.py's no-network-per-request
            # rule) — one full-season fetch here covers every week, refetched
            # each refresh so upcoming games' lines update as books move them.
            try:
                data["schedule"] = sched_adapter.get_schedule(season, week=None, nfl_module=nfl_module)
                # why also write data/nfl_cache/schedule_<season>.json (user-
                # caught live bug, 2026-09-10): hub/server.py reads this exact
                # path for weather/opponent-map/NFL-slate display (it can't
                # call nflreadpy itself — isolation contract, no outbound
                # calls) — but nothing ever refreshed it. scripts/seed_demo.py
                # wrote it once, at initial DB bootstrap, and it was NEVER
                # updated after that: hub's slate/weather stayed frozen at
                # seed time (scores still null) while the model's own
                # /games/predictions correctly showed live final scores from
                # the same underlying schedule call. Same data, two
                # consumers, only one was being kept current. Atomic tmp->
                # rename so hub never reads a half-written file mid-refresh.
                try:
                    _repo_root = Path(__file__).resolve().parents[2]
                    _cache_dir = _repo_root / "data" / "nfl_cache"
                    _cache_dir.mkdir(parents=True, exist_ok=True)
                    _sched_path = _cache_dir / f"schedule_{season}.json"
                    _sched_tmp = _sched_path.with_suffix(".json.tmp")
                    _sched_tmp.write_text(_safe_dumps(data["schedule"]))
                    _sched_tmp.replace(_sched_path)
                except Exception as _sched_write_exc:
                    logger.warning(f"refresh: schedule cache write failed: {_sched_write_exc}")
            except Exception as _sched_exc:
                logger.warning(f"refresh: full-season schedule fetch failed: {_sched_exc}")
            # why a real prior-season fetch, not reuse of `player_stats`
            # (user-caught live bug, 2026-09-10): before MAX_STATS_SEASON was
            # bumped to match the live season, `player_stats` (stats_season)
            # WAS last year's data — build_weekly_projections's cross_season
            # branch used it as the prior-season baseline for free. Once
            # stats_season caught up to the real season (so /props/board's
            # "actual" stat stopped being last year's box score), that free
            # ride disappeared: cross_season went False, the week<target_week
            # filter correctly finds zero same-season history at week 1, and
            # projections silently went empty league-wide (fail-closed, no
            # crash — just nothing). Fetch season-1 explicitly so early-season
            # projections still have a real prior-season fallback all season,
            # independent of whatever `player_stats` happens to represent.
            try:
                prior_season_stats = nflverse.get_weekly_player_stats(season - 1, nfl_module=nfl_module)
            except Exception as _prior_exc:
                logger.warning(f"refresh: prior-season stats fetch failed: {_prior_exc}")
                prior_season_stats = []
            # why cached (not just passed through): /props/board projects
            # fair lines per requested week on demand; early weeks need the
            # prior-season blend and the board can't refetch per click.
            # ~19k rows, same lifetime as player_stats (memory is local-only
            # cheap; truthy-only overwrite in api.py keeps last good).
            data["prior_season_stats"] = prior_season_stats
            projs = build_weekly_projections(
                player_stats,
                sched,
                target_week=target_wk,
                scoring_settings=data.get("league_settings", {}).get("scoring_settings", {}),
                prior_season_stats=prior_season_stats,
                # why out-set here (backtested zero-Out-weekly, 2026-09-10):
                # an Out player's prior-starter average is pure staleness
                # (Darnold 163 yds while Out). Weekly path only — the
                # neutral season computation inside never sees it, so
                # ROS/auction values survive a 1-week absence. Soft-fail
                # to no-zeroing; injury_status may be {} on Sleeper failure.
                out_pids=build_out_gsis_set(
                    sleeper_players_map, data.get("injury_status")),
            )
            scoring = data.get("league_settings", {}).get("scoring_settings", {})
            proj_map = {}
            for pr in projs:
                pid = str(pr.get("player_id", ""))
                if pid:
                    fpts = calculate_fantasy_points(pr, scoring)
                    # Audit 22.0: guard against NaN/Inf from malformed rows —
                    # round(NaN) → NaN leaks into proj_map, then into
                    # enriched_player_stats JSON where _safe_dumps converts
                    # it to 0, but in-memory consumers see NaN.
                    import math
                    if not math.isfinite(fpts):
                        fpts = 0.0
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
            # why Sleeper team patch: nflverse rows carry LAST season's team;
            # without this, preseason boards show past teams (unacceptable).
            # Match on (name, pos); opponent remapped from the target schedule.
            # why rookie rows: the incoming class must be identified (name,
            # team, pos), never invisible — zeros + is_empty flag, never
            # imputed. Soft-fail each step; projections stand without them.
            # why gsis-first team patch (gsis-identity spec): weekly history
            # rows carry last season's team; nflverse weekly rosters are the
            # gsis-keyed current truth (trades/FA) with no name matching.
            # Snapshots cached to data/nfl_cache (last-good fallback, never
            # abort); the depth file is owned here for backtest consumers.
            # Name map stays as fallback for rows without GSIS (rookie rows).
            _gsis_map: dict = {}
            try:
                _repo_root = Path(__file__).resolve().parents[2]
                _cache_dir = _repo_root / "data" / "nfl_cache"
                _cache_dir.mkdir(parents=True, exist_ok=True)
                _rosters_path = _cache_dir / f"rosters_weekly_{season}.json"
                _depth_path = _cache_dir / f"depth_{season}.json"
                try:
                    _rosters = nflverse.get_weekly_rosters(season, nfl_module=nfl_module)
                    write_json_cache(_rosters_path, _rosters)
                except Exception as _rf_exc:
                    logger.warning(f"refresh: weekly-rosters fetch failed, last-good cache: {_rf_exc}")
                    try:
                        _rosters = json.loads(_rosters_path.read_text())
                    except Exception:
                        _rosters = []
                try:
                    _depth = nflverse.get_depth_charts(season, nfl_module=nfl_module)
                    write_json_cache(_depth_path, _depth)
                except Exception as _df_exc:
                    logger.warning(f"refresh: depth fetch failed, last-good cache: {_df_exc}")
                _gsis_map = build_gsis_team_map(_rosters or [])
                _log(conn, "identity", True, None, ran_at_iso)
            except Exception as _id_exc:
                _log(conn, "identity", False, str(_id_exc), ran_at_iso)
                logger.warning(f"refresh: gsis identity step skipped: {_id_exc}")
            # why cache opportunity/NGS here (opportunity spec): no refresh
            # math consumes them yet — backtests do. One owner for the files,
            # last-good fallback, refresh_log entry, never abort.
            try:
                _opp_path = _cache_dir / f"opportunity_{season}.json"
                _ngs_path = _cache_dir / f"ngs_receiving_{season}.json"
                try:
                    _opp_rows = nflverse.get_opportunity(season, nfl_module=nfl_module)
                    write_json_cache(_opp_path, _opp_rows)
                except Exception as _o_exc:
                    logger.warning(f"refresh: opportunity fetch failed, last-good cache: {_o_exc}")
                try:
                    _ngs_rows = nflverse.get_ngs_receiving(season, nfl_module=nfl_module)
                    write_json_cache(_ngs_path, _ngs_rows)
                except Exception as _n_exc:
                    logger.warning(f"refresh: NGS fetch failed, last-good cache: {_n_exc}")
                _log(conn, "opportunity", True, None, ran_at_iso)
            except Exception as _op_exc:
                _log(conn, "opportunity", False, str(_op_exc), ran_at_iso)
                logger.warning(f"refresh: opportunity cache step skipped: {_op_exc}")
            try:
                from ffanalytics.adapters.schedule import get_nfl_team_matchups
                _opp_map = get_nfl_team_matchups(sched, target_wk)
                _team_map = build_sleeper_team_map(sleeper_players_map)
                _n_patched = patch_proj_teams(projs, _team_map, _opp_map,
                                              team_by_gsis=_gsis_map)
                if _n_patched:
                    logger.info(f"refresh: Sleeper team patch applied to {_n_patched} rows")
                _have = {
                    ((pr.get("player_display_name") or pr.get("player_name") or "").strip().lower(),
                     str(pr.get("position") or pr.get("position_group") or "").upper())
                    for pr in projs
                }
                _rookies = build_rookie_rows(sleeper_players_map, _have, _opp_map, target_wk)
                if _rookies:
                    projs.extend(_rookies)
                    enriched_player_stats.extend(dict(r) for r in _rookies)
                    logger.info(f"refresh: {len(_rookies)} rookie rows added as explicit unknowns")
            except Exception as _patch_exc:
                logger.warning(f"refresh: team-patch/rookie step skipped: {_patch_exc}")
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
        # Sleeper players map (gsis_id crosswalk) — hoisted fetch above;
        # reuse it, refetch only if the hoist failed (keeps old fallback).
        if not sleeper_players_map:
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
        # FantasyPros ECR ranks — free weekly ECR first (fresh through the
        # season), local CSV exports second (preseason-frozen fallback),
        # paid API last (returns [] under $0 anyway). fpros_id->gsis map
        # rides along for the comparison's exact join.
        fpros_players_list = []
        data["fpros_id_to_gsis"] = {}
        try:
            _er_root = Path(__file__).resolve().parents[2]
            _er_cache = _er_root / "data" / "nfl_cache"
            _er_cache.mkdir(parents=True, exist_ok=True)
            _ecr_path = _er_cache / f"ecr_weekly_{season}.json"
            _pid_path = _er_cache / "ff_playerids.json"
            try:
                _ecr_rows = nflverse.get_ecr_weekly(nfl_module=nfl_module)
                write_json_cache(_ecr_path, _ecr_rows)
            except Exception as _e_exc:
                logger.warning(f"refresh: free ECR fetch failed, last-good cache: {_e_exc}")
                try:
                    _ecr_rows = json.loads(_ecr_path.read_text())
                except Exception:
                    _ecr_rows = []
            try:
                _pids = nflverse.get_ff_playerids(nfl_module=nfl_module)
                write_json_cache(_pid_path, _pids)
            except Exception as _p_exc:
                logger.warning(f"refresh: playerids fetch failed, last-good cache: {_p_exc}")
                try:
                    _pids = json.loads(_pid_path.read_text())
                except Exception:
                    _pids = []
            data["fpros_id_to_gsis"] = map_fpros_id_to_gsis(_pids or [])
            if _ecr_rows:
                fpros_players_list = [nflverse_ecr_to_fpros(r) for r in _ecr_rows]
                logger.info(f"refresh: free weekly ECR loaded: {len(fpros_players_list)} players")
            _log(conn, "ecr", True, None, ran_at_iso)
        except Exception as _ecr_outer:
            _log(conn, "ecr", False, str(_ecr_outer), ran_at_iso)
            logger.warning(f"refresh: free ECR step skipped: {_ecr_outer}")
        if not fpros_players_list:
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
                try:
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
            # why econ here: auction $ must divide over THIS league's teams,
            # budget (draft API, stored above), and roster shape — not the
            # 12x$200 defaults. Falls back to defaults when unknown.
            _ls = data.get("league_settings") or {}
            _draft = _ls.get("draft") or {}
            _econ = config.league_economics(
                total_rosters=_ls.get("total_rosters", 12),
                roster_positions=_ls.get("roster_positions"),
                auction_budget=_draft.get("auction_budget") or 200,
            )
            data["comparison"] = _build_comp(_model_projs, market_by_gsis, fpros_players_list, sleeper_players_map, fp_projections_map, statsguy_rows, league_econ=_econ,
                                             gsis_to_fpid={g: f for f, g in (data.get("fpros_id_to_gsis") or {}).items()})
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
        # Sleeper->GSIS crosswalk store (derived cache for roster joins).
        # Whole-table replace per refresh; lazy DDL mirrors market_consensus
        # (POST /refresh never calls init_schema).
        if sleeper_players_map:
            try:
                conn.execute(
                    """CREATE TABLE IF NOT EXISTS sleeper_xwalk (
                        sleeper_id TEXT PRIMARY KEY,
                        gsis_id TEXT NOT NULL
                    )"""
                )
                name_pos_to_gsis = {}
                # why load_players() first, not just player_stats (user-caught
                # live bug, 2026-09-10): player_stats only has rows for
                # players with a stat line THIS week — a real starter who
                # simply didn't play (bye, injury, backup) had no row to
                # match against, even though their gsis_id is a stable
                # identity unrelated to weekly participation. Confirmed
                # live: Brock Purdy (real SF starter) failed to resolve for
                # exactly this reason. load_players() is nflverse's full
                # ~25k-player identity master list, not filtered to any
                # week — covers the gap. Kept as its own try/except (per-
                # source isolation): if this fetch fails, fall through to
                # the smaller player_stats-derived map exactly as before,
                # never abort the whole xwalk build over it.
                try:
                    for s in nflverse.get_player_ids(nfl_module=nfl_module):
                        nm = s.get("display_name")
                        pos = s.get("position")
                        gsis_id = s.get("gsis_id")
                        if nm and pos and gsis_id:
                            name_pos_to_gsis.setdefault(_norm_name_pos(nm, pos), str(gsis_id))
                except Exception as _pid_exc:
                    logger.warning(f"refresh: load_players() fetch failed, xwalk fallback degraded to player_stats-only: {_pid_exc}")
                for s in (data.get("player_stats") or []):
                    nm = s.get("player_display_name") or s.get("player_name")
                    pos = s.get("position") or s.get("position_group")
                    gsis_id = s.get("player_id")
                    if nm and pos and gsis_id:
                        name_pos_to_gsis.setdefault(_norm_name_pos(nm, pos), str(gsis_id))
                xwalk = build_sleeper_xwalk(sleeper_players_map, name_pos_to_gsis)
                conn.execute("DELETE FROM sleeper_xwalk")
                conn.executemany(
                    "INSERT OR REPLACE INTO sleeper_xwalk (sleeper_id, gsis_id) VALUES (?, ?)",
                    list(xwalk.items()),
                )
                data["sleeper_xwalk"] = xwalk
            except Exception as xw_exc:
                logger.warning(f"sleeper_xwalk store failed: {xw_exc}")
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
            # Snapshot per-player projections for accuracy grading (DB1 fix).
            snap_at = now.isoformat()
            for ps in data["player_stats"]:
                pp = ps.get("projected_points")
                pid = ps.get("player_id") or ps.get("id") or ""
                pos = (ps.get("position") or "").upper()
                if pp is not None and pid and pos:
                    conn.execute(
                        """INSERT OR REPLACE INTO projection_snapshots
                           (season, week, player_id, position, projected_points,
                            projection_low, projection_high, snapped_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                        (season, market_week, str(pid), pos, pp,
                         ps.get("projection_low"), ps.get("projection_high"),
                         snap_at),
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
                        season, m["week"],
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
            # Props experiment retention (council vote): prop_lines snapshots
            # and resolved shadow rows age out at 180d (a full season); pending
            # rows never auto-delete. Manual-entry volume is tiny, but an
            # unbounded table on a $0 local file is still a leak.
            try:
                _pruned = prune_props_tables(conn, now.isoformat())
                if _pruned["prop_lines"] or _pruned["shadow_resolved"]:
                    logger.info(f"props retention pruned: {_pruned}")
            except Exception as _prune_props_exc:
                logger.warning(f"props retention prune failed: {_prune_props_exc}")
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
                # Audit 22.0: exclude week=0 from the global cap — it's the
                # full-season baseline cache and must not be evicted by the
                # trailing-8 limit.
                conn.execute(
                    """DELETE FROM player_stats WHERE rowid NOT IN (
                         SELECT rowid FROM player_stats
                         WHERE week != 0
                         ORDER BY season DESC, week DESC LIMIT 8
                       ) AND week != 0
                       AND (SELECT COUNT(*) FROM player_stats WHERE week != 0) > 8"""
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

        # Game prediction shadow resolution (additive, same shape — resolves
        # kind='game:<season>:<week>' against real final scores from the
        # schedule feed, not player_stats).
        try:
            from ffanalytics.shadow import evaluate_unresolved_game_predictions
            game_resolved = evaluate_unresolved_game_predictions(
                conn, data.get("schedule", [])
            )
            if game_resolved > 0:
                logger.info(f"Resolved {game_resolved} pending game prediction outcomes.")
        except Exception as shadow_exc:
            logger.warning(f"Game prediction shadow outcome resolution failed: {shadow_exc}")

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

        # Integrity assertion: every (season, week) must have exactly 12 rows
        # in sleeper_matchups (12-team league). Catches clobber regressions.
        if status.get("sleeper") and data.get("matchups"):
            integrity_rows = conn.execute(
                """SELECT week, COUNT(*) as cnt, SUM(COALESCE(points, 0)) as pts
                   FROM sleeper_matchups WHERE season = ?
                   GROUP BY week ORDER BY week""",
                (season,),
            ).fetchall()
            for row in integrity_rows:
                wk, cnt, pts = row[0], row[1], row[2]
                if cnt != 12:
                    logger.critical(
                        f"INTEGRITY: sleeper_matchups season={season} week={wk} "
                        f"has {cnt} rows (expected 12)"
                    )
                # Past weeks with real scores must retain non-zero points
                if wk < week and pts is not None and pts > 0:
                    pass  # healthy
                elif wk < week and (pts is None or pts == 0):
                    logger.warning(
                        f"INTEGRITY: sleeper_matchups season={season} week={wk} "
                        f"has pts_sum={pts} (past week, expected >0)"
                    )

        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.exception("Failed to store refresh data in DB")

    return status, data