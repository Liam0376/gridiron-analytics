"""FastAPI app, run locally only (uvicorn on localhost — no public
hosting, see design spec's hosting decision). In-memory cache pattern
follows the reference repo's api.py: refresh populates a module-level
cache, request handlers read from it, never touching disk per-request."""

from fastapi import FastAPI, HTTPException, Query, Request, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, Field
from requests.exceptions import HTTPError
import datetime
import json
import logging
import re
import uuid
import contextvars
from contextlib import asynccontextmanager, contextmanager
from datetime import timedelta

import threading

from ffanalytics import config, db
from ffanalytics.config import compute_nfl_week, get_stats_season
from ffanalytics.refresh import run_refresh_with_data
from ffanalytics.decision import (
    get_start_sit_recommendations,
    get_waiver_priority,
    evaluate_trade,
    calculate_roster_value
)
from ffanalytics import shadow
from ffanalytics import props as props_math
from ffanalytics import game_predictions

logger = logging.getLogger("ffanalytics.api")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] rid=%(rid)s %(message)s")

# (app is constructed below, after lifespan/Error/handlers are defined.)

# Per-request id context — populated by request_id_middleware, read by
# _RequestIdLogFilter below so every log record made through `logger`
# includes `rid=<uuid>` automatically.
_request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")


class _RequestIdLogFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "rid"):
            record.rid = _request_id_var.get("-")
        return True


logger.addFilter(_RequestIdLogFilter())
# why record factory (not just logger/root filters): basicConfig's format
# demands rid=%(rid)s on EVERY record, but logger filters only run for
# records originating on that logger — httpx/refresh/adapter records handled
# by the root handler crashed the formatter with KeyError 'rid'. Stamping
# rid at record creation covers all loggers/handlers, present and future.
_old_record_factory = logging.getLogRecordFactory()


def _rid_record_factory(*args, **kwargs):
    record = _old_record_factory(*args, **kwargs)
    if not hasattr(record, "rid"):
        try:
            record.rid = _request_id_var.get("-")
        except Exception:
            record.rid = "-"
    return record


logging.setLogRecordFactory(_rid_record_factory)

# Audit 6.0: x-request-id allowlist — client-supplied ids are only echoed
# when they match [A-Za-z0-9-]{1,64}; anything missing/invalid gets a
# server-generated uuid4 so log injection / header reflection is impossible.
# why strict: rid lands in every log line + the response header; reflecting
# raw input would let a caller inject CR/LF into logs or poison caches.
_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9-]{1,64}$")


def _sanitize_log(value: object) -> str:
    # why: path/exc text is attacker-influenced (URL) or opaque (tracebacks);
    # strip CR/LF before it reaches log lines to block log forging.
    return str(value).replace("\r", "").replace("\n", "")


class Error(BaseModel):
    # why: hub + monitors parse 4xx/5xx programmatically; a typed
    # code/message/request_id envelope correlates client errors with
    # server logs. 2xx bodies stay byte-identical (hub compat) — only
    # error paths use this envelope.
    code: int
    message: str
    request_id: str


@asynccontextmanager
async def lifespan(app: FastAPI):
    # why: POST /refresh never calls init_schema (refresh.py lazy DDL is
    # owned by another crew) — without startup DDL a fresh-DB first refresh
    # fails on missing tables. init_schema is idempotent (IF NOT EXISTS +
    # version-gated migrations), safe to run on every boot.
    conn = None
    try:
        conn = db.get_connection()
        db.init_schema(conn)
    except Exception:
        logger.exception("api: lifespan init_schema failed")
    finally:
        try:
            if conn is not None:
                conn.close()
        except Exception:
            pass
    yield


app = FastAPI(title="Fantasy Football Analytics Engine", lifespan=lifespan)

# why regex not a fixed list: hub/start.sh picks ports per-invocation
# (8001/8002 by default, but --league/--force runs can shift them), and
# the hub is served only from 127.0.0.1/localhost — never 0.0.0.0. `null`
# origin (file://) intentionally NOT allowed; see docs/RUNBOOK.md known
# limitation.
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"^https?://(127\.0\.0\.1|localhost)(:\d+)?$",
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


@app.exception_handler(HTTPException)
async def _http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    # why: every raised 4xx/5xx (404 owner, 503 cold, 409 busy, 422
    # validation) shares one envelope so callers can rely on the shape.
    # 5xx details raised here are already generic ("internal error") —
    # real tracebacks stay server-side in logs only.
    rid = _request_id_var.get("-")
    return JSONResponse(
        status_code=exc.status_code,
        content=Error(code=exc.status_code, message=str(exc.detail), request_id=rid).model_dump(),
    )


@app.exception_handler(RequestValidationError)
async def _validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    # why: FastAPI's default 422 body echoes raw input; envelope it and keep
    # the message generic so over-long ids etc. aren't reflected.
    rid = _request_id_var.get("-")
    return JSONResponse(
        status_code=422,
        content=Error(code=422, message="validation error", request_id=rid).model_dump(),
    )


@app.exception_handler(Exception)
async def _unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    # why: last-resort guard — full detail goes to the server log, the
    # client only gets a correlation id (never str(exc): may contain paths,
    # keys, or SQL fragments).
    rid = _request_id_var.get("-")
    logger.exception(
        "!! %s %s unhandled: %s", request.method, _sanitize_log(request.url.path), _sanitize_log(exc)
    )
    return JSONResponse(
        status_code=500,
        content=Error(code=500, message="internal error", request_id=rid).model_dump(),
    )


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    """Generate (or accept) a UUID per request, attach to response header,
    include in all log lines, and release the thread-local DB connection
    when the request ends so connections don't leak across requests."""
    raw_rid = request.headers.get("x-request-id")
    # why: only echo allowlisted ids; missing/invalid -> server uuid4 so raw
    # attacker input is never reflected in headers/logs (see _REQUEST_ID_RE).
    rid = raw_rid if raw_rid and _REQUEST_ID_RE.match(raw_rid) else uuid.uuid4().hex
    path = _sanitize_log(request.url.path)
    token = _request_id_var.set(rid)
    try:
        logger.info("-> %s %s", request.method, path)
        response = await call_next(request)
        response.headers["x-request-id"] = rid
        logger.info("<- %s %s %s", request.method, path, response.status_code)
        return response
    except Exception as exc:
        logger.exception("!! %s %s crashed: %s", request.method, path, _sanitize_log(exc))
        raise
    finally:
        _request_id_var.reset(token)
        try:
            db.reset_conn()
        except Exception:
            pass


# Audit C3: guard concurrent refresh (launchd + hub/start.sh + manual)
_REFRESH_LOCK = threading.Lock()


_CACHE: dict = {
    "league_settings": None,  # scoring_settings, roster_positions
    "rosters": None,          # list of roster dicts from Sleeper
    "player_stats": None,    # list of player stat dicts from nflverse
    "model_projections": None,  # weekly model fair-stat rows (props fair lines)
    "sleeper_xwalk": None,  # Sleeper id -> GSIS id (roster joins)
    "injury_status": None,    # dict mapping player_id to injury status
    "matchups": None,         # list of matchup dicts from Sleeper
    "trending": None,         # trending waiver adds
    "detailed_injuries": None, # practice participation status
    "schedule": None,         # full-season NFL schedule rows w/ market lines
    "last_updated": None,     # timestamp of last cache update
    "season": None,           # NFL season year
    "week": None,             # approximate NFL week (1-18)
}

def _league_query():
    # why helper (not a shared Query object): each signature needs its own
    # FieldInfo; convention here is inline Query(...) — this keeps the
    # league_id validation identical on every endpoint in one place.
    return Query(default=None, max_length=64, pattern=r"^\d+$")


def _blank_cache() -> dict:
    return {
        "league_settings": None,
        "rosters": None,
        "player_stats": None,
        "model_projections": None,
        "sleeper_xwalk": None,
        "injury_status": None,
        "matchups": None,
        "trending": None,
        "detailed_injuries": None,
        "schedule": None,
        "last_updated": None,
        "season": None,
        "week": None,
    }


_LEAGUE_CACHES: dict[str, dict] = {}


def _is_default_league(league_id: str | None) -> bool:
    # why: explicit league_id equal to the env default (or no id at all)
    # keeps legacy behavior; any other numeric id gets an isolated snapshot.
    lid = (league_id or "").strip()
    if not lid:
        return True
    default_lid = (config.LEAGUE_ID or "").strip()
    return bool(default_lid) and lid == default_lid


def _cache_for(league_id: str | None) -> dict:
    # why namespaced: multi-league — each league gets an isolated in-memory
    # snapshot so switching leagues in the UI never serves another league's
    # numbers. _CACHE stays the default league's dict (identity preserved:
    # update_cache and the test suite snapshot it directly).
    if _is_default_league(league_id):
        return _CACHE
    lid = str(league_id).strip()
    return _LEAGUE_CACHES.setdefault(lid, _blank_cache())


@contextmanager
def _league_conn(league_id: str | None):
    # why: read endpoints fall back to SQLite when the cache is cold — for a
    # non-default league that means that league's own DB file. Missing file
    # yields None (callers degrade to empty/503) instead of creating a stray
    # empty DB via get_connection's auto-create.
    if _is_default_league(league_id):
        yield db._get_conn()
        return
    from pathlib import Path

    path = config.db_path_for_league(league_id)
    if not Path(path).exists():
        yield None
        return
    conn = db.get_connection(path)
    try:
        yield conn
    finally:
        try:
            conn.close()
        except Exception:
            pass


def update_cache(
    league_settings: dict,
    rosters: list[dict],
    player_stats: list[dict],
    injury_status: dict[str, str | None],
    season: int | None = None,
    week: int | None = None,
    matchups: list[dict] | None = None,
    trending: list[dict] | None = None,
    detailed_injuries: list[dict] | None = None,
    league_id: str | None = None,
    model_projections: list[dict] | None = None,
) -> None:
    target = _cache_for(league_id)
    if league_settings:
        target["league_settings"] = league_settings
    if rosters:
        target["rosters"] = rosters
    if player_stats:
        target["player_stats"] = player_stats
    if model_projections:
        target["model_projections"] = model_projections
    if injury_status:
        target["injury_status"] = injury_status
    if matchups:
        target["matchups"] = matchups
    if trending:
        target["trending"] = trending
    if detailed_injuries:
        target["detailed_injuries"] = detailed_injuries
    target["last_updated"] = datetime.datetime.now().isoformat()
    if season is not None:
        target["season"] = season
    if week is not None:
        target["week"] = week


def _create_player_lookup(player_stats: list[dict]) -> dict[str, dict]:
    return {str(p.get("player_id")): p for p in player_stats}


def _sleeper_xwalk_for(cache: dict, league_id: str | None) -> dict:
    """Sleeper->GSIS map for roster joins: warm cache first, DB fallback.
    Missing everywhere => {} (callers degrade to direct-ID matching)."""
    xw = cache.get("sleeper_xwalk")
    if xw:
        return xw
    try:
        with _league_conn(league_id) as conn:
            if conn is None:
                return {}
            rows = conn.execute("SELECT sleeper_id, gsis_id FROM sleeper_xwalk").fetchall()
            # why str() both sides (code-reviewer sign-off): SQLite TEXT
            # usually returns str, but an int-typed legacy row would silently
            # miss the join and drop players. One type contract both sides.
            return {str(r["sleeper_id"]): str(r["gsis_id"]) for r in rows}
    except Exception:
        return {}


def _resolve_base_stats(stats_lookup: dict, xwalk: dict, player_id_str: str) -> dict:
    """Roster-id -> stats row. Direct match first (covers Sleeper-keyed rows
    like rookies and gsis-keyed fixtures), then the Sleeper->GSIS crosswalk
    (covers veterans: rosters carry Sleeper ids, stats carry GSIS — direct
    joins match nothing in production, verified live 169-vs-2025 zero
    overlap). Missing everywhere => {} (caller skips, as before)."""
    hit = stats_lookup.get(player_id_str)
    if hit:
        return hit
    gsis = (xwalk or {}).get(player_id_str)
    if gsis:
        return stats_lookup.get(gsis, {})
    return {}


def _build_player_dict(
    player_id_str: str,
    base_stats: dict,
    injury_status: dict[str, str | None],
    owner_id: str | None = None,
) -> dict:
    """Build a single player dict from nflverse base_stats.

    Centralized so /start-sit, /waiver, /trade, and the all_league_players
    fallback all emit the same field set (incl. projection_lower/upper/width).
    """
    pts = float(base_stats.get("projected_points") or base_stats.get("fantasy_points", 0) or 0)
    # why guard here (code-review finding): nflverse/Polars can hand back NaN
    # for a missing stat instead of None — float(nan) survives the `or 0`
    # chain (NaN is truthy) and later json.dumps on a bare NaN raises,
    # 500ing the whole endpoint instead of quarantining one player.
    if pts != pts or abs(pts) == float("inf"):
        pts = 0.0
    player: dict = {
        "player_id": player_id_str,
        "player_name": base_stats.get("short_name", f"Player {player_id_str}"),
        # why `or ... or "UNK"`, not `.get(key, "UNK")` (user-caught live
        # bug): dict.get's default only fires when the KEY is missing, not
        # when its value is explicitly None — a row with both
        # position_group and position present-but-None (confirmed live,
        # /recommendations/start-sit 500ed on 'NoneType' has no attribute
        # 'upper') crashed the whole endpoint on one bad row instead of
        # falling back. This is also why shadow_recommendations had zero
        # start_sit/waiver/trade rows ever, despite the logging call being
        # correctly wired (api.py:874/932/1074) — the endpoint crashed
        # before it ever reached that line.
        "position_group": (base_stats.get("position_group") or base_stats.get("position") or "UNK").upper(),
        "position": (base_stats.get("position") or base_stats.get("position_group") or "UNK").upper(),
        "projected_points": pts,
        "projection_lower": base_stats.get("projection_lower"),
        "projection_upper": base_stats.get("projection_upper"),
        "width": base_stats.get("width"),
        "injury_status": injury_status.get(player_id_str),
        # why canonical `team` first: nflverse `recent_team` is stale/lagged
        # for traded players (see adapters quirk note in AGENTS.md).
        "team": base_stats.get("team") or base_stats.get("recent_team") or "",
        "opponent_team": base_stats.get("opponent_team", ""),
    }
    if owner_id is not None:
        player["owner_id"] = owner_id
    return player


def _process_roster_data(
    rosters: list[dict],
    player_stats: list[dict],
    injury_status: dict[str, str | None],
    league_settings: dict,
    owner_id: str | None = None,
    sleeper_xwalk: dict | None = None,
) -> tuple[list[dict], list[dict], list[dict]]:
    """
    Process raw Sleeper rosters and nflverse stats into roster_players,
    bench_players, and free_agents for decision layer functions.

    Returns:
        tuple of (roster_players, bench_players, free_agents)
    """
    if not player_stats:
        return [], [], []

    stats_lookup = _create_player_lookup(player_stats)
    scoring_settings = league_settings.get("scoring_settings", {})
    roster_positions = league_settings.get("roster_positions", [])

    from ffanalytics.decision import _optimal_lineup

    target_rosters = rosters
    if owner_id is not None:
        target_rosters = [r for r in rosters if str(r.get("owner_id")) == str(owner_id)]
        if not target_rosters:
            # P0: unknown owner must 404, never silently serve rosters[0]
            # (previous fallback leaked another team's lineup as your own).
            raise HTTPException(
                status_code=404,
                detail=f"owner_id={owner_id} not found",
            )

    roster_players = []
    bench_players = []

    for roster in target_rosters:
        current_owner = str(roster.get("owner_id")) if roster.get("owner_id") is not None else None
        player_ids = roster.get("players", [])
        team_players = []
        for player_id in player_ids:
            player_id_str = str(player_id)
            base_stats = _resolve_base_stats(stats_lookup, sleeper_xwalk, player_id_str)
            if not base_stats:
                continue
            team_players.append(
                _build_player_dict(player_id_str, base_stats, injury_status, owner_id=current_owner)
            )

        starters, bench = _optimal_lineup(team_players, roster_positions)
        roster_players.extend(starters)
        bench_players.extend(bench)

    # Free agents: players with stats but not on any roster
    rostered_player_ids = set()
    for roster in rosters:
        for player_id in roster.get("players", []):
            rostered_player_ids.add(str(player_id))

    free_agents = []
    for player_id_str, base_stats in stats_lookup.items():
        if player_id_str not in rostered_player_ids:
            free_agents.append(
                _build_player_dict(player_id_str, base_stats, injury_status)
            )

    return roster_players, bench_players, free_agents


def _batch_log_recommendations(kind: str, recommendations: list[dict], league_id: str | None = None) -> None:
    """Log a batch of recommendations to the shadow table using a single
    executemany + commit (best-effort). Uses the per-request thread-local
    DB connection (db._get_conn()) so all writes share one connection and
    don't repeatedly open/close SQLite handles."""
    if not recommendations:
        return
    try:
        logged_at = datetime.datetime.now().isoformat()
        cache = _cache_for(league_id)
        season = cache.get("season")
        week = cache.get("week")
        # why real fallbacks, never 0: season/week=0 rows pollute the shadow
        # log with an unqueryable season (shadow resolution joins on real
        # season/week), so fall back to the configured seasons instead.
        if season is None:
            season = get_stats_season()
        if week is None:
            week = compute_nfl_week()
        rows = [
            {
                "kind": kind,
                "season": season,
                "week": week,
                "player_id": rec.get("player_id"),
                "recommendation": rec,
                "logged_at": logged_at,
            }
            for rec in recommendations
        ]
        # why one target only: the thread-local conn serves the DEFAULT
        # league's DB — logging another league's rows there would pollute its
        # shadow outcomes. Non-default leagues log into their own DB file.
        if league_id is not None and not _is_default_league(league_id):
            import pathlib

            path = config.db_path_for_league(league_id)
            if not pathlib.Path(path).exists():
                return
            dedicated = db.get_connection(path)
            try:
                shadow.log_recommendations_batch(dedicated, rows)
            finally:
                try:
                    dedicated.close()
                except Exception:
                    pass
            return
        conn = db._get_conn()
        shadow.log_recommendations_batch(conn, rows)
    except Exception:
        logger.exception(
            "api: batch shadow log failed for kind=%s n=%d", kind, len(recommendations)
        )


@app.get("/health")
@app.get("/v1/health")
def health() -> dict:
    # Liveness only — always ok, even before first refresh. No DB/cache reads.
    return {"status": "ok"}


@app.get("/ready")
@app.get("/v1/ready")
def ready(league_id: str | None = _league_query()) -> dict:
    # Readiness — 503 until warmed via POST /refresh (same warmed predicate
    # as the /recommendations/* guards so load-balancers/monitors agree).
    # why per-league: a warmed default league must not mask a cold league B.
    cache = _cache_for(league_id)
    if (
        not cache.get("league_settings")
        or not cache.get("rosters")
        or not cache.get("player_stats")
    ):
        raise HTTPException(
            status_code=503,
            detail="Data not available. Run /refresh first to load data.",
        )
    return {"status": "ready"}


def _latest_source_status(conn) -> dict:
    """Latest refresh_log row per source: {source: {success, ran_at}}.

    Shared by POST /refresh (last-known `sources`) and GET /refresh/status.
    Missing table (fresh DB, startup DDL not yet run) -> {} instead of 500.
    """
    try:
        rows = conn.execute(
            "SELECT source, ran_at, success FROM refresh_log ORDER BY ran_at DESC LIMIT 50"
        ).fetchall()
    except Exception:
        return {}
    out: dict = {}
    for r in rows:
        try:
            src = r["source"]
        except Exception:
            src = r[0]
        if src in out:
            continue
        try:
            out[src] = {"success": bool(r["success"]), "ran_at": r["ran_at"]}
        except Exception:
            out[src] = {"success": bool(r[2]), "ran_at": r[1]}
    return out


class RefreshRequest(BaseModel):
    # why optional body (not required): legacy callers POST with no body
    # (curl, launchd, hub/start.sh) — they refresh the default league.
    # why validated: league ids are numeric; 422s surface via the envelope.
    league_id: str | None = Field(default=None, max_length=64, pattern=r"^\d+$")


def _do_refresh_job(season: int, stats_season: int, ran_at_iso: str, week: int, league_id: str | None = None) -> None:
    """Background refresh worker: owns its own long-lived DB connection and
    holds _REFRESH_LOCK until done (released here, not in the endpoint, so
    concurrent POSTs 409 while the job runs). Failures are per-source
    isolated inside run_refresh_with_data; a total crash is logged
    server-side — there is no request left to answer, so nothing is raised."""
    # why per-league conn: refresh writes into that league's own DB file
    # (default league keeps legacy data/fantasy.db). Lock stays global —
    # refreshes serialize across leagues (Sleeper courtesy + SQLite WAL).
    lid = config.require_league_id(league_id)
    conn = (
        db.get_connection()
        if _is_default_league(lid)
        else db.get_connection(config.db_path_for_league(lid))
    )
    try:
        status, data = run_refresh_with_data(
            conn,
            season=season,
            stats_season=stats_season,
            ran_at_iso=ran_at_iso,
            league_id=lid,
        )

        cache = _cache_for(lid)
        new_cache = dict(cache)
        if data.get("league_settings"):
            new_cache["league_settings"] = data["league_settings"]
        if data.get("rosters"):
            new_cache["rosters"] = data["rosters"]
        if data.get("player_stats"):
            new_cache["player_stats"] = data["player_stats"]
        if data.get("model_projections"):
            # why cached: props edges read fair stat lines + is_empty flags
            # from the real pipeline output (with Vegas/weather ctx) instead
            # of rebuilding without ctx. Small (~500 rows), same lifetime as
            # player_stats, same truthy-only overwrite (failed refresh keeps
            # last good).
            new_cache["model_projections"] = data["model_projections"]
        if data.get("sleeper_xwalk"):
            # why cached: roster joins need it per request without DB reads.
            new_cache["sleeper_xwalk"] = data["sleeper_xwalk"]
        if data.get("injury_status"):
            new_cache["injury_status"] = data["injury_status"]
        if data.get("matchups"):
            new_cache["matchups"] = data["matchups"]
        if data.get("trending"):
            new_cache["trending"] = data["trending"]
        if data.get("detailed_injuries"):
            new_cache["detailed_injuries"] = data["detailed_injuries"]
        if data.get("schedule"):
            new_cache["schedule"] = data["schedule"]
        new_cache["last_updated"] = datetime.datetime.now().isoformat()
        if season is not None:
            new_cache["season"] = season
        if week is not None:
            new_cache["week"] = week
        # P0: never _CACHE.clear()+update — readers on other threads could
        # observe an empty cache between the two calls. new_cache already
        # starts as dict(cache), so a single update() applies the delta
        # without an empty window while preserving _CACHE identity (update_cache
        # mutates in place, so rebinding _CACHE would orphan that path).
        cache.update(new_cache)
    except Exception:
        logger.exception("api: background refresh failed")
    finally:
        try:
            conn.close()
        except Exception:
            pass
        try:
            _REFRESH_LOCK.release()
        except Exception:
            pass


@app.post("/refresh", status_code=202)
@app.post("/v1/refresh", status_code=202)
def refresh(background_tasks: BackgroundTasks, body: RefreshRequest | None = None) -> dict:
    # Audit 6.0: truly async — the endpoint only snapshots season params and
    # queues the job, returning 202 immediately; _do_refresh_job holds the
    # lock until the multi-source run finishes (409 while running).
    # why BackgroundTasks not inline: the prior 202 lied — it ran the full
    # multi-source refresh on the request thread, so launchd + hub/start.sh
    # + manual callers all blocked for minutes behind a "202".
    if not _REFRESH_LOCK.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="Refresh already in progress")
    try:
        from ffanalytics.config import get_current_nfl_season, get_stats_season
        now = datetime.datetime.now()
        season = get_current_nfl_season()
        stats_season = get_stats_season()
        ran_at_iso = now.isoformat()
        week = compute_nfl_week(now)
        # why optional body: no body refreshes the default league (legacy
        # callers unchanged); {"league_id"} refreshes that league's own DB.
        lid = body.league_id if body and body.league_id else None
        background_tasks.add_task(_do_refresh_job, season, stats_season, ran_at_iso, week, lid)
    except Exception:
        try:
            _REFRESH_LOCK.release()
        except Exception:
            pass
        raise
    # why last-known sources: the job hasn't run yet, so per-source bools
    # can't be fresh; poll status_url for completion instead.
    try:
        with _league_conn(lid) as conn:
            sources = {s: v["success"] for s, v in _latest_source_status(conn).items()} if conn else {}
    except Exception:
        sources = {}
    out: dict = {"status": "accepted", "sources": sources, "status_url": "/refresh/status"}
    if lid and not _is_default_league(lid):
        out["league_id"] = lid
    return out


@app.get("/refresh/status")
@app.get("/v1/refresh/status")
def refresh_status(league_id: str | None = _league_query()) -> dict:
    # why: async POST returns before sources finish — hub/monitors poll here
    # for latest per-source success + ran_at instead of blocking on refresh.
    try:
        with _league_conn(league_id) as conn:
            sources = _latest_source_status(conn) if conn else {}
    except Exception:
        sources = {}
    return {"sources": sources, "running": _REFRESH_LOCK.locked()}


@app.get("/news")
@app.get("/v1/news")
def get_news(league_id: str | None = _league_query()) -> dict:
    # why missing-file degrade: a freshly added league has no DB yet — empty
    # lists (not 500) so the UI shows "refresh needed" instead of an error.
    with _league_conn(league_id) as conn:
        if conn is None:
            return {"trending_adds": [], "detailed_injuries": []}
        return _read_news(conn)


def _read_news(conn) -> dict:
    try:
        trending_row = conn.execute(
            "SELECT data FROM news_data WHERE kind='trending' ORDER BY fetched_at DESC LIMIT 1"
        ).fetchone()
        injuries_row = conn.execute(
            "SELECT data FROM news_data WHERE kind='injuries' ORDER BY fetched_at DESC LIMIT 1"
        ).fetchone()
        return {
            "trending_adds": json.loads(trending_row["data"]) if trending_row else [],
            "detailed_injuries": json.loads(injuries_row["data"]) if injuries_row else [],
        }
    except Exception as exc:
        # why generic: str(exc) may carry SQL/paths; detail stays server-side.
        logger.exception("api: /news failed: %s", _sanitize_log(exc))
        raise HTTPException(status_code=500, detail="internal error")


@app.get("/projections")
@app.get("/v1/projections")
def get_projections(
    limit: int = Query(800, ge=1, le=2000),
    offset: int = Query(0, ge=0),
    league_id: str | None = _league_query(),
) -> dict:
    # why limit/offset: hub fetchProjections already sends ?limit= (default
    # 800, up to 2000 for the auction board); previously the param was
    # silently ignored and the slice hardcoded to 800. Defaults preserve the
    # exact legacy body (players[0:800]) for hub compat.
    cache = _cache_for(league_id)
    if cache["player_stats"]:
        players = cache["player_stats"]
        scoring = (cache.get("league_settings") or {}).get("scoring_settings", {})
    else:
        with _league_conn(league_id) as conn:
            if conn is None:
                return {"players": [], "count": 0, "meta": {"cached": False}}
            row = conn.execute(
                "SELECT data FROM player_stats WHERE data IS NOT NULL AND length(data) > 1000 ORDER BY rowid DESC LIMIT 1"
            ).fetchone()
            players = json.loads(row["data"]) if row else []
            # Load scoring settings from DB
            srow = conn.execute(
                "SELECT data FROM league_settings ORDER BY season DESC LIMIT 1"
            ).fetchone()
            scoring = json.loads(srow["data"]).get("scoring_settings", {}) if srow else {}

    out = []
    for p in players:
        pid = str(p.get("player_id") or p.get("id") or "")
        pos = (p.get("position") or p.get("position_group") or "UNK").upper()
        pts = float(p.get("projected_points") or p.get("fantasy_points") or 0)
        # why rescore-when-nonzero (backend sign-off): league scoring is live
        # truth and can change mid-season — a stale stored value (e.g. 4pt-era
        # pass TDs) must not survive. Rescore whenever raw stat keys exist;
        # keep the stored value only when rescoring yields 0 (stat-less rows
        # like market fallbacks would otherwise zero out).
        if scoring:
            from ffanalytics.scoring import calculate_fantasy_points
            try:
                rescored = calculate_fantasy_points(p, scoring)
                if rescored != 0:
                    pts = rescored
            except Exception:
                pass
        injury = (cache.get("injury_status") or {}).get(pid)
        out.append({
            "player_id": pid,
            "player_name": p.get("player_display_name") or p.get("short_name") or p.get("player_name") or pid,
            "position": pos,
            "position_group": pos,
            "team": p.get("team") or p.get("recent_team") or "",
            "opponent_team": p.get("opponent_team") or "",
            "projected_points": round(pts, 2),
            "injury_status": injury,
        })
    out.sort(key=lambda x: x["projected_points"], reverse=True)
    page = out[offset:offset + limit]
    return {"players": page, "count": len(page), "meta": {"cached": bool(cache["player_stats"]), "total": len(out)}}


@app.get("/league/draft")
@app.get("/v1/league/draft")
def get_league_draft(league_id: str | None = _league_query()) -> dict:
    # why: setup screen source — league identity + draft type, everything the
    # UI needs before any refresh exists (name, teams, snake vs auction).
    # why 400 when unconfigured: without any id there is nothing to look up;
    # message points at the setup flow, not internals.
    from ffanalytics.adapters import sleeper

    lid = (league_id or config.LEAGUE_ID or "").strip()
    if not lid:
        raise HTTPException(
            status_code=400,
            detail="league_id required — enter your Sleeper league ID first.",
        )
    try:
        return sleeper.get_draft_info(lid)
    except HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else 500
        if status == 404:
            raise HTTPException(status_code=404, detail="League not found on Sleeper — check the league ID.")
        logger.exception("api: /league/draft failed: %s", _sanitize_log(exc))
        raise HTTPException(status_code=500, detail="internal error")
    except Exception as exc:
        logger.exception("api: /league/draft failed: %s", _sanitize_log(exc))
        raise HTTPException(status_code=500, detail="internal error")


@app.get("/recommendations/start-sit")
@app.get("/v1/recommendations/start-sit")
def get_start_sit(owner_id: str = Query(..., max_length=64, pattern=r"^\d+$"), league_id: str | None = _league_query()) -> dict:
    cache = _cache_for(league_id)
    if not cache["league_settings"] or not cache["rosters"] or not cache["player_stats"]:
        raise HTTPException(
            status_code=503,
            detail="Data not available. Run /refresh first to load data."
        )

    league_settings = cache["league_settings"]
    rosters = cache["rosters"]
    player_stats = cache["player_stats"]
    injury_status = cache["injury_status"] or {}

    scoring_settings = league_settings.get("scoring_settings", {})
    roster_positions = league_settings.get("roster_positions", [])

    try:
        roster_players, bench_players, _ = _process_roster_data(
            rosters, player_stats, injury_status, league_settings, owner_id=owner_id,
            sleeper_xwalk=_sleeper_xwalk_for(cache, league_id),
        )

        recommendations = get_start_sit_recommendations(
            roster_players, bench_players, scoring_settings, roster_positions
        )

        _batch_log_recommendations("start_sit", recommendations, league_id)

        return {
            "recommendations": recommendations,
            "count": len(recommendations),
            "timestamp": cache["last_updated"]
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("api: start-sit failed: %s", _sanitize_log(exc))
        raise HTTPException(status_code=500, detail="internal error")


def _league_econ_from_settings(league_settings: dict) -> dict:
    # why: auction $/VOR math scales with league size, roster shape, and draft
    # budget — all live per league (settings + draft info stashed at refresh).
    # Falls back to the 12x$200 reference league when unknown.
    from ffanalytics.config import league_economics

    draft = (league_settings.get("draft") or {}) if isinstance(league_settings, dict) else {}
    return league_economics(
        total_rosters=league_settings.get("total_rosters", 12),
        roster_positions=league_settings.get("roster_positions"),
        auction_budget=(draft.get("auction_budget") if isinstance(draft, dict) else None) or 200,
    )


@app.get("/recommendations/waiver")
@app.get("/v1/recommendations/waiver")
def get_waiver(owner_id: str = Query(..., max_length=64, pattern=r"^\d+$"), league_id: str | None = _league_query()) -> dict:
    cache = _cache_for(league_id)
    if not cache["league_settings"] or not cache["rosters"] or not cache["player_stats"]:
        raise HTTPException(
            status_code=503,
            detail="Data not available. Run /refresh first to load data."
        )

    league_settings = cache["league_settings"]
    rosters = cache["rosters"]
    player_stats = cache["player_stats"]
    injury_status = cache["injury_status"] or {}

    scoring_settings = league_settings.get("scoring_settings", {})
    roster_positions = league_settings.get("roster_positions", [])

    try:
        roster_players, _, free_agents = _process_roster_data(
            rosters, player_stats, injury_status, league_settings, owner_id=owner_id,
            sleeper_xwalk=_sleeper_xwalk_for(cache, league_id),
        )

        econ = _league_econ_from_settings(league_settings)
        recommendations = get_waiver_priority(
            roster_players, free_agents, scoring_settings, roster_positions,
            num_teams=econ["teams"],
        )

        _batch_log_recommendations("waiver", recommendations, league_id)

        return {
            "recommendations": recommendations,
            "count": len(recommendations),
            "timestamp": cache["last_updated"]
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("api: waiver failed: %s", _sanitize_log(exc))
        raise HTTPException(status_code=500, detail="internal error")


@app.get("/recommendations/trade")
@app.get("/v1/recommendations/trade")
def get_trade_evaluation(
    team_a_id: str = Query(..., max_length=64, pattern=r"^\d+$"),
    team_b_id: str = Query(..., max_length=64, pattern=r"^\d+$"),
    league_id: str | None = _league_query(),
) -> dict:
    cache = _cache_for(league_id)
    if not cache["league_settings"] or not cache["rosters"] or not cache["player_stats"]:
        raise HTTPException(
            status_code=503,
            detail="Data not available. Run /refresh first to load data."
        )

    league_settings = cache["league_settings"]
    rosters = cache["rosters"]
    player_stats = cache["player_stats"]
    injury_status = cache["injury_status"] or {}

    scoring_settings = league_settings.get("scoring_settings", {})
    roster_positions = league_settings.get("roster_positions", [])

    try:
        stats_lookup = _create_player_lookup(player_stats)
        xwalk = _sleeper_xwalk_for(cache, league_id)
        team_a_players = []
        team_b_players = []

        for roster in rosters:
            owner_id = str(roster.get("owner_id")) if roster.get("owner_id") is not None else None
            if owner_id is None:
                continue

            player_ids = roster.get("players", [])

            for player_id in player_ids:
                player_id_str = str(player_id)
                base_stats = _resolve_base_stats(stats_lookup, xwalk, player_id_str)
                if not base_stats:
                    continue

                if owner_id == team_a_id:
                    team_a_players.append(
                        _build_player_dict(player_id_str, base_stats, injury_status)
                    )
                elif owner_id == team_b_id:
                    team_b_players.append(
                        _build_player_dict(player_id_str, base_stats, injury_status)
                    )

        if not team_a_players:
            raise HTTPException(status_code=404, detail=f"Team A (owner_id={team_a_id}) not found or has no players")
        if not team_b_players:
            raise HTTPException(status_code=404, detail=f"Team B (owner_id={team_b_id}) not found or has no players")

        # Load market_consensus from DB for VBD auction params
        market_consensus = None
        try:
            with _league_conn(league_id) as conn:
                row = conn.execute("SELECT data FROM market_consensus ORDER BY fetched_at DESC LIMIT 1").fetchone() if conn else None
            if row is not None:
                try:
                    data_str = row["data"]
                except Exception:
                    try:
                        data_str = row[0]
                    except Exception:
                        data_str = None
                if data_str:
                    try:
                        market_consensus = json.loads(data_str)
                    except Exception:
                        market_consensus = None
        except Exception:
            market_consensus = None

        # Fallback to all_league_players if no market_consensus
        all_league_players = None
        if not market_consensus or not isinstance(market_consensus, list) or len(market_consensus) < 20:
            all_league_players = []
            # Primary fallback: build from player_stats (full pool, ensures >=20 when DB populated)
            if player_stats and len(player_stats) >= 20:
                for p in player_stats:
                    pid = str(p.get("player_id") or p.get("id") or "")
                    if not pid:
                        continue
                    base = {
                        "short_name": p.get("short_name") or p.get("player_name") or p.get("player_display_name"),
                        "position_group": p.get("position_group"),
                        "position": p.get("position"),
                        "projected_points": p.get("projected_points") or p.get("fantasy_points") or 0,
                        # why canonical `team` first: `recent_team` lags for traded players.
                        "recent_team": p.get("team") or p.get("recent_team"),
                        "opponent_team": p.get("opponent_team"),
                    }
                    all_league_players.append(
                        _build_player_dict(pid, base, injury_status)
                    )
            else:
                for roster in rosters:
                    owner_id_tmp = str(roster.get("owner_id")) if roster.get("owner_id") is not None else None
                    if owner_id_tmp is None:
                        continue
                    for pid in roster.get("players", []) or []:
                        pid_str = str(pid)
                        base = stats_lookup.get(pid_str, {})
                        if not base:
                            continue
                        all_league_players.append(
                            _build_player_dict(pid_str, base, injury_status)
                        )
            # Ensure list not empty; decision.py will fallback to team_a+team_b if still <20
            if not all_league_players:
                all_league_players = None

        # current_week from cache or compute_nfl_week()
        current_week = cache.get("week") or compute_nfl_week()
        if current_week is None:
            current_week = 1

        result = evaluate_trade(
            team_a_players, team_b_players, scoring_settings, roster_positions,
            current_week=current_week,
            market_consensus=market_consensus,
            all_league_players=all_league_players,
            league_econ=_league_econ_from_settings(league_settings),
        )

        _batch_log_recommendations("trade", [result], league_id)

        return {
            "trade_evaluation": result,
            "team_a_id": team_a_id,
            "team_b_id": team_b_id,
            "timestamp": cache["last_updated"]
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("api: trade failed: %s", _sanitize_log(exc))
        raise HTTPException(status_code=500, detail="internal error")


# Sleeper injury_status vocabulary (see adapters/sleeper.py:get_injury_statuses)
# that means "not going to play" — mirrors hub/src/components/badges.js's
# injuryBadge() /out|ir|injured reserve/i test so backend "available" and
# frontend badge color never disagree. Questionable/Doubtful stay available
# (flagged, not hidden) — only these mean the projection is stale-by-default.
_UNAVAILABLE_STATUSES = {"out", "ir", "injured reserve", "pup", "nfi", "suspended", "na"}


def _is_unavailable(injury_status: str | None) -> bool:
    if not injury_status:
        return False
    s = str(injury_status).strip().lower()
    return s in _UNAVAILABLE_STATUSES


def _fair_board_rows(
    proj_row: dict,
    history_rows: list[dict],
    prior_rows: list[dict] | None,
    sleeper_id: str | None = None,
    injury_status: str | None = None,
    actual_row: dict | None = None,
) -> list[dict]:
    """Fair-line rows for EVERY market at a player's position — no book line
    required. This is what makes a game clickable into "browse this game's
    props": the earlier manual book-line/edge system (POST /props/lines,
    GET /props/edges, _evaluate_prop_edge — removed 2026-09-10, no odds
    feed exists and no UI reached them once the edge board was dropped
    per user request) only ever returned rows for a *stored* book line, so
    a game with no manually-entered lines showed nothing. This reads
    straight off model_projections + history directly — same fair/sigma
    math the old edge system used, just without the book-line comparison
    half (no p_model/edge/EV — there's no price to compare against, by
    design now, not by omission). Empty-history players are skipped (fair
    0.0 would be noise).

    injury_status/sleeper_id are attached per row (not filtered out here —
    the caller decides whether to exclude; showing an OUT player's stale
    projection WITHOUT the status would be the actual dishonesty, per this
    repo's calibration-honesty rule elsewhere). actual_row, when the target
    week's real box score has landed (game played), adds an "actual" value
    per market for predicted-vs-actual comparison — same market->stat-key
    mapping as the fair side, just read off the real row instead."""
    if proj_row is None or bool(proj_row.get("is_empty_projection", False)):
        return []
    pos = (proj_row.get("position") or proj_row.get("position_group") or "").upper()
    market_defs = props_math.PROP_MARKETS.get(pos, [])
    if not market_defs:
        return []
    # why appended, not in PROP_MARKETS: carries isn't a bettable prop
    # market (no edge/EV/calibration machinery applies) — it's volume
    # context the user asked to see on an RB's card. Same fair/sigma/actual
    # computation as every other "normal" row below, just not wired into
    # the edges/calibration system.
    if pos == "RB":
        market_defs = market_defs + [("carries", "carries", "normal")]
    name = proj_row.get("player_display_name") or proj_row.get("player_name") or ""
    team = proj_row.get("team") or proj_row.get("recent_team") or ""
    unavailable = _is_unavailable(injury_status)
    rows = []
    for market, source, model in market_defs:
        if model == "poisson":
            lam = 0.0
            for src in source.split("+"):
                try:
                    lam += float(proj_row.get(src, 0) or 0)
                except (TypeError, ValueError):
                    pass
            if lam != lam or abs(lam) == float("inf"):
                continue
            actual_p_yes = None
            if actual_row is not None and not actual_row.get("is_empty_projection"):
                actual_lam = 0.0
                for src in source.split("+"):
                    try:
                        actual_lam += float(actual_row.get(src, 0) or 0)
                    except (TypeError, ValueError):
                        pass
                actual_p_yes = 1.0 if actual_lam > 0 else 0.0
            rows.append({
                "player_id": str(proj_row.get("player_id", "")),
                "sleeper_id": sleeper_id, "injury_status": injury_status,
                "available": not unavailable,
                "player_name": name, "position": pos, "team": team,
                "market": market, "fair_line": round(lam, 3), "sigma": None,
                "p_yes": round(props_math.poisson_anytime_td(lam), 4),
                "actual_p_yes": actual_p_yes,
            })
        else:
            try:
                fair = float(proj_row.get(source, 0) or 0)
            except (TypeError, ValueError):
                continue
            if fair != fair or abs(fair) == float("inf"):
                continue
            sigma = props_math.sigma_for_stat(history_rows, prior_rows, source)
            actual = None
            if actual_row is not None and not actual_row.get("is_empty_projection"):
                try:
                    actual = round(float(actual_row.get(source, 0) or 0), 2)
                except (TypeError, ValueError):
                    actual = None
            rows.append({
                "player_id": str(proj_row.get("player_id", "")),
                "sleeper_id": sleeper_id, "injury_status": injury_status,
                "available": not unavailable,
                "player_name": name, "position": pos, "team": team,
                "market": market, "fair_line": round(fair, 2),
                "sigma": round(sigma, 3), "actual": actual,
            })
    return rows


def _props_history_lookup(player_stats: list[dict]) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    for s in player_stats or []:
        pid = str(s.get("player_id") or s.get("id") or "")
        if pid:
            grouped.setdefault(pid, []).append(s)
    return grouped


def _split_history_prior(rows: list[dict], season, week: int) -> tuple[list, list]:
    """Split player rows into same-season history (weeks < target) and prior
    seasons. Preseason caches hold the prior season under the league season,
    so history is empty and prior carries the full baseline — exactly the
    Task-4 backtest's pooling (without this, week-1 sigmas collapse to the
    floor and P(over) reads ~0.96 instead of ~0.70). Mid-season caches hold
    one season, so prior is empty and behavior is byte-identical to before.
    Rows without a season field fall back to the week filter (backward
    compatible with old blobs and fixtures)."""
    try:
        season_int = int(season) if season is not None else None
    except (TypeError, ValueError):
        season_int = None
    hist, prior = [], []
    for r in rows or []:
        if (r.get("season_type") or "REG") != "REG":
            continue
        try:
            rs = int(r.get("season")) if r.get("season") is not None else None
        except (TypeError, ValueError):
            rs = None
        if rs is not None and season_int is not None and rs < season_int:
            prior.append(r)
        elif (r.get("week") or 0) < week:
            hist.append(r)
    return hist, prior




@app.get("/props/board")
@app.get("/v1/props/board")
def get_props_board(
    teams: str = Query(..., min_length=1, max_length=16, pattern=r"^[A-Z]{2,4}(,[A-Z]{2,4})?$"),
    week: int | None = Query(default=None, ge=1, le=18),
    season: int | None = Query(default=None, ge=2000, le=2100),
    league_id: str | None = _league_query(),
) -> dict:
    # This browses every rosterable player in the given game's two teams via
    # model fair lines directly, no book line required (see _fair_board_rows;
    # the manual book-line/edge system this replaced is gone — no free
    # player-prop odds feed exists, see PropLineIn's removal note in git log).
    cache = _cache_for(league_id)
    if not cache.get("model_projections") or not cache.get("player_stats"):
        raise HTTPException(
            status_code=503, detail="Data not available. Run /refresh first to load data."
        )
    season = season if season is not None else (cache.get("season") or get_stats_season())
    week = week if week is not None else (cache.get("week") or compute_nfl_week() or 1)
    team_set = {t.strip().upper() for t in teams.split(",") if t.strip()}

    # gsis (model_projections' player_id) -> sleeper_id: injury_status and
    # headshots are both sleeper_id-keyed (adapters/sleeper.py), but
    # model_projections carries nflverse's gsis id. Same xwalk direction
    # _resolve_base_stats uses elsewhere, just inverted for this lookup.
    xwalk = _sleeper_xwalk_for(cache, league_id)  # {sleeper_id: gsis_id}
    gsis_to_sleeper = {gsis: sid for sid, gsis in xwalk.items()}
    injury_by_sleeper = cache.get("injury_status") or {}

    # hist_lookup groups player_stats by player_id once; actual_by_pid (this
    # target week's real box score, if the game's been played) is derived
    # from it rather than a second scan over the same list.
    hist_lookup = _props_history_lookup(cache.get("player_stats"))
    actual_by_pid: dict[str, dict] = {}
    for pid, player_rows in hist_lookup.items():
        for s in player_rows:
            if s.get("week") == week and (s.get("season_type") or "REG") == "REG":
                actual_by_pid[pid] = s
                break
    rows: list[dict] = []
    for proj_row in cache.get("model_projections") or []:
        team = proj_row.get("team") or proj_row.get("recent_team") or ""
        if team not in team_set:
            continue
        pid = str(proj_row.get("player_id", ""))
        hist, prior = _split_history_prior(hist_lookup.get(pid, []), season, week)
        sleeper_id = gsis_to_sleeper.get(pid)
        injury_status = injury_by_sleeper.get(sleeper_id) if sleeper_id else None
        rows.extend(_fair_board_rows(
            proj_row, hist, prior, sleeper_id=sleeper_id,
            injury_status=injury_status, actual_row=actual_by_pid.get(pid),
        ))

    return {
        "players": rows,
        "count": len(rows),
        "teams": sorted(team_set),
        "season": season,
        "week": week,
        "timestamp": cache["last_updated"],
    }


@app.get("/games/predictions")
@app.get("/v1/games/predictions")
def get_game_predictions(
    week: int | None = Query(default=None, ge=1, le=18),
    season: int | None = Query(default=None, ge=2000, le=2100),
    league_id: str | None = _league_query(),
) -> dict:
    # why market_consensus, never "our prediction": these are real Vegas
    # lines (spread/total/moneyline) off the schedule feed, devigged —
    # game_predictions.py's docstring/spec explain the source. Mislabeling
    # this as a model call would misrepresent where the number comes from.
    cache = _cache_for(league_id)
    schedule = cache.get("schedule")
    if not schedule:
        raise HTTPException(
            status_code=503, detail="Data not available. Run /refresh first to load data."
        )
    season = season if season is not None else (cache.get("season") or get_stats_season())
    week = week if week is not None else (cache.get("week") or compute_nfl_week() or 1)

    games = [g for g in schedule if g.get("season") == season and g.get("week") == week]
    predictions = [p for p in (game_predictions.game_prediction(g) for g in games) if p is not None]

    with _league_conn(league_id) as conn:
        if conn is not None:
            for pred in predictions:
                try:
                    shadow.log_game_prediction_once(
                        conn, season, week, pred["game_id"], pred,
                        datetime.datetime.now().isoformat(),
                    )
                except Exception:
                    logger.exception("api: game prediction shadow log failed")

    return {
        "games": predictions,
        "count": len(predictions),
        "season": season,
        "week": week,
        "timestamp": cache["last_updated"],
    }