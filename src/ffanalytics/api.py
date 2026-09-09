"""FastAPI app, run locally only (uvicorn on localhost — no public
hosting, see design spec's hosting decision). In-memory cache pattern
follows the reference repo's api.py: refresh populates a module-level
cache, request handlers read from it, never touching disk per-request."""

from fastapi import FastAPI, HTTPException, Query, Request, BackgroundTasks
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
    "injury_status": None,    # dict mapping player_id to injury status
    "matchups": None,         # list of matchup dicts from Sleeper
    "trending": None,         # trending waiver adds
    "detailed_injuries": None, # practice participation status
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
        "injury_status": None,
        "matchups": None,
        "trending": None,
        "detailed_injuries": None,
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
    player: dict = {
        "player_id": player_id_str,
        "player_name": base_stats.get("short_name", f"Player {player_id_str}"),
        "position_group": (base_stats.get("position_group") or base_stats.get("position", "UNK")).upper(),
        "position": (base_stats.get("position") or base_stats.get("position_group", "UNK")).upper(),
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
    owner_id: str | None = None
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
            base_stats = stats_lookup.get(player_id_str, {})
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
        if data.get("injury_status"):
            new_cache["injury_status"] = data["injury_status"]
        if data.get("matchups"):
            new_cache["matchups"] = data["matchups"]
        if data.get("trending"):
            new_cache["trending"] = data["trending"]
        if data.get("detailed_injuries"):
            new_cache["detailed_injuries"] = data["detailed_injuries"]
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
        if pts == 0 and scoring:
            from ffanalytics.scoring import calculate_fantasy_points
            try:
                pts = calculate_fantasy_points(p, scoring)
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
            rosters, player_stats, injury_status, league_settings, owner_id=owner_id
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
            rosters, player_stats, injury_status, league_settings, owner_id=owner_id
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
        team_a_players = []
        team_b_players = []

        for roster in rosters:
            owner_id = str(roster.get("owner_id")) if roster.get("owner_id") is not None else None
            if owner_id is None:
                continue

            player_ids = roster.get("players", [])

            for player_id in player_ids:
                player_id_str = str(player_id)
                base_stats = stats_lookup.get(player_id_str, {})
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


# ---------------------------------------------------------------------------
# Player props (spec 2026-09-09): manual book-line entry + edges vs model
# fair lines. Separate from fantasy — never touches decision/comparison.
# Fair lines come from cached model_projections (real pipeline output with
# Vegas/weather ctx); sigmas from same-season history dispersion
# (props.sigma_for_stat, prior=None — conservative, floors bind sooner).
# Hub stays read-only: it GETs edges here; manual entry POSTs to :8000.
# ---------------------------------------------------------------------------

class PropLineIn(BaseModel):
    player_id: str = Field(..., min_length=1, max_length=64)
    season: int | None = Field(default=None, ge=2000, le=2100)
    week: int = Field(..., ge=1, le=18)
    market: str = Field(..., min_length=1, max_length=32)
    side: str = Field(..., min_length=1, max_length=8)
    line: float | None = None
    price: float
    book: str = Field(default="manual", min_length=1, max_length=32)


def _props_calibration() -> dict:
    """Best-effort per-market calibration info from the Task-4 backtest
    artifact: {market: {verdict, n, coverage_80|brier, ...}}. Missing
    artifact => {} (callers show 'unknown', never an edge claim). Read per
    request — 3KB, always fresh after backtest reruns."""
    try:
        from pathlib import Path as _Path

        root = _Path(__file__).resolve().parents[2]
        doc = json.loads((root / "data" / "props" / "backtest_props_results.json").read_text())
        out = {}
        for name, info in (doc.get("markets") or {}).items():
            entry = {"verdict": info.get("verdict", "unknown"), "n": info.get("n")}
            if info.get("kind") == "poisson":
                entry.update({
                    "brier": info.get("brier"),
                    "naive_brier": info.get("naive_brier"),
                    "base_rate": info.get("base_rate"),
                })
            else:
                entry.update({
                    "coverage_80": info.get("coverage_80"),
                    "pit_max_dev": info.get("pit_max_dev"),
                    "fair_mae": info.get("fair_mae"),
                })
            out[name] = entry
        return out
    except Exception:
        return {}


def _props_calibration_verdicts() -> dict:
    """Verdict-only projection of _props_calibration (kept for callers that
    need just the label)."""
    return {m: info.get("verdict", "unknown") for m, info in _props_calibration().items()}


def _prop_shadow_rec(edge: dict) -> dict:
    """Canonical shadow record for a VALUE edge. Single construction site for
    POST-time and GET-time logging so the dedupe JSON matches byte-for-byte
    (log_prop_edge_once also sort_keys, belt and suspenders)."""
    return {
        "player_id": edge["player_id"],
        "market": edge["market"],
        "side": edge["side"],
        "book_line": edge["book_line"],
        "book_price": edge["book_price"],
        "fair_line": edge["fair_line"],
        "p_model": edge["p_model"],
        "edge_pp": edge["edge_pp"],
        "ev_per_unit": edge["ev_per_unit"],
        "decision": edge["decision"],
        "calibration_verdict": edge["calibration_verdict"],
    }


def _validate_prop_line(body: PropLineIn) -> dict:
    """Semantic validation beyond Pydantic shape. Returns normalized dict.
    Raises HTTPException(422) with a user-facing reason."""
    market = (body.market or "").strip().lower()
    side = (body.side or "").strip().lower()
    all_markets = {
        m for _pos in props_math.PROP_MARKETS.values() for (m, _s, _model) in _pos
    }
    if market not in all_markets:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown market '{body.market}'. Allowed: {sorted(all_markets)}.",
        )
    # why any(), not a static set: anytime_td is poisson for every position
    # while normal markets differ per position — derive from PROP_MARKETS so
    # market adds flow through without a second allowlist.
    is_poisson = any(
        m == market and model == "poisson"
        for _pos in props_math.PROP_MARKETS.values()
        for (m, _s, model) in _pos
    )
    if is_poisson:
        if side not in ("yes", "no"):
            raise HTTPException(
                status_code=422, detail="anytime_td takes side 'yes' or 'no' (yes/no market)."
            )
        if body.line is not None:
            raise HTTPException(
                status_code=422, detail="anytime_td takes no line (yes/no market)."
            )
    else:
        if side not in ("over", "under"):
            raise HTTPException(
                status_code=422, detail=f"Market '{market}' takes side 'over' or 'under'."
            )
        if body.line is None or body.line != body.line or abs(body.line) == float("inf"):
            raise HTTPException(status_code=422, detail="Over/under requires a finite line.")
    try:
        props_math.american_to_prob(float(body.price))
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=422, detail=f"Invalid American price '{body.price}' (non-zero, finite)."
        )
    # why strip-then-check, not min_length: Pydantic sees "   " as length 3
    # and passes it; the stored row would be player_id="" — junk that always
    # evaluates unknown. Caught live by the api-tester agent sign-off.
    player_id = (body.player_id or "").strip()
    if not player_id:
        raise HTTPException(status_code=422, detail="player_id must not be blank.")
    book = (body.book or "manual").strip() or "manual"
    # why credential-shaped rejection (secrets sign-off): `book` is free text
    # stored verbatim in SQLite and served in JSON — one paste becomes a
    # persistent, retrievable compromise (CWE-312). Prefix-only list avoids
    # false positives on real book names (draftkings/fanduel/manual).
    lowered_book = book.lower()
    if any(t in lowered_book for t in (
        "sk-", "akia", "ghp_", "gho_", "xoxb", "xoxp", "xoxa", "xoxs",
        "-----begin",
    )):
        raise HTTPException(
            status_code=422, detail="book looks like a credential — use a bookmaker name."
        )
    return {
        "player_id": player_id,
        "market": market,
        "side": side,
        "line": None if body.line is None else float(body.line),
        "price": float(body.price),
        "book": book,
    }


def _evaluate_prop_edge(
    proj_row: dict | None,
    history_rows: list[dict],
    stored: dict,
    calibration: dict,
) -> dict:
    """Edge for one stored book line. Unknown-by-construction inputs
    (missing player, empty history, week 1, out-of-scope position, or
    non-finite numbers) => NO EDGE (unknown) with a note — unknown is never
    an edge, and one poisoned row never 500s the board (per-row quarantine)."""
    market, side = stored["market"], stored["side"]
    is_poisson = market == "anytime_td"
    # why full info, not just the label (analytics-reporter sign-off): a bare
    # "tracking" verdict is unauditable — the edge carries its n/coverage.
    info = calibration.get(market) or {}
    cal = info.get("verdict", "unknown")
    cal_detail = {k: v for k, v in info.items() if k != "verdict"}
    base = {
        "player_id": stored["player_id"],
        "market": market,
        "side": side,
        "book_line": stored["line"],
        "book_price": stored["price"],
        "book": stored["book"],
        "calibration_verdict": cal,
        "calibration": cal_detail,
    }

    def _unknown(note):
        return {**base, "fair_line": None, "sigma": None, "p_model": None,
                "book_prob": None, "edge_pp": None, "ev_per_unit": None,
                "decision": "NO EDGE (unknown)", "note": note}

    if proj_row is None:
        return _unknown("no model projection for player")
    is_empty = bool(proj_row.get("is_empty_projection", False))
    pos = (proj_row.get("position") or proj_row.get("position_group") or "").upper()
    # why position gate: markets are position-scoped (PROP_MARKETS) — a
    # kicker's passing_yards line must not grade as a confident edge.
    allowed = {m for (m, _s, _model)
               in props_math.PROP_MARKETS.get(pos, [])}
    if market not in allowed:
        return _unknown(f"market '{market}' out of scope for position '{pos or '?'}'")
    name = (proj_row.get("player_display_name") or proj_row.get("player_name")
            or stored["player_id"])
    if is_poisson:
        sources = next(
            (src.split("+") for _p, ms in props_math.PROP_MARKETS.items() if _p == pos
             for (m, src, model) in ms if m == market and model == "poisson"),
            ("rushing_tds", "receiving_tds"),
        )
        lam = 0.0
        for src in sources:
            try:
                lam += float(proj_row.get(src, 0) or 0)
            except (TypeError, ValueError):
                pass
        if lam != lam or abs(lam) == float("inf"):
            return _unknown("non-finite projected TD mean")
        p_yes = props_math.poisson_anytime_td(lam)
        p_model = p_yes if side == "yes" else 1.0 - p_yes
        fair, sigma = lam, None
    else:
        stat_key = market  # normal markets are 1:1 with stat keys by construction
        try:
            fair = float(proj_row.get(stat_key, 0) or 0)
        except (TypeError, ValueError):
            fair = 0.0
        # why quarantine, not 500: one NaN/inf projection must not take down
        # the whole edges board — the row vetoes itself with a note.
        line = stored["line"]
        if (fair != fair or abs(fair) == float("inf")
                or line is None or line != line or abs(line) == float("inf")):
            return _unknown("non-finite fair line or book line")
        sigma = props_math.sigma_for_stat(history_rows, None, stat_key)
        # why side-adjust here, not in props_math: prop_over_prob answers
        # P(over) only; the ticket side decides which tail the user holds.
        p_over = props_math.prop_over_prob(
            {"model": "normal", "fair_line": fair, "sigma": sigma}, line
        )
        p_model = p_over if side == "over" else 1.0 - p_over
    rule = props_math.apply_prop_edge_rule(
        p_model, stored["price"], is_empty=is_empty
    )
    if is_empty:
        return {**base, "player_name": name, "position": pos,
                "team": proj_row.get("team") or proj_row.get("recent_team") or "",
                "fair_line": round(fair, 2),
                "sigma": None if sigma is None else round(sigma, 3),
                "p_model": round(p_model, 4),
                "book_prob": round(rule["book_prob"], 4),
                "edge_pp": round(rule["edge_pp"], 4),
                "ev_per_unit": round(rule["ev_per_unit"], 4),
                "decision": rule["decision"],
                "note": "empty history: projection unknown"}
    return {
        **base,
        "player_name": name,
        "position": pos,
        "team": proj_row.get("team") or proj_row.get("recent_team") or "",
        "fair_line": round(fair, 2),
        "sigma": None if sigma is None else round(sigma, 3),
        "p_model": round(p_model, 4),
        "book_prob": round(rule["book_prob"], 4),
        "edge_pp": round(rule["edge_pp"], 4),
        "ev_per_unit": round(rule["ev_per_unit"], 4),
        "decision": rule["decision"],
    }


def _props_history_lookup(player_stats: list[dict]) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    for s in player_stats or []:
        pid = str(s.get("player_id") or s.get("id") or "")
        if pid:
            grouped.setdefault(pid, []).append(s)
    return grouped


@app.post("/props/lines")
@app.post("/v1/props/lines")
def post_prop_line(
    body: PropLineIn,
    league_id: str | None = _league_query(),
) -> dict:
    cache = _cache_for(league_id)
    norm = _validate_prop_line(body)
    season = body.season if body.season is not None else (cache.get("season") or get_stats_season())
    stored = {**norm, "season": season, "week": body.week}
    # why lazy init_schema, not a migration-only path: POST /refresh never
    # calls init_schema (db.py documents this), so first props write on an
    # old DB would hit "no such table". init_schema is idempotent
    # (IF NOT EXISTS + versioned migrations) — schema.sql stays the source.
    with _league_conn(league_id) as conn:
        if conn is None:
            raise HTTPException(status_code=503, detail="DB not available.")
        db.init_schema(conn)
        import datetime as _dt

        # why RETURNING, not last_insert_rowid(): after ON CONFLICT DO UPDATE
        # SQLite leaves last_insert_rowid at the last actual INSERT — a
        # re-POST would return a stale id. RETURNING gives the real row.
        # why fetch-before-commit: the RETURNING cursor holds an open read;
        # committing first raises "cannot commit - statements in progress".
        cur = conn.execute(
            """INSERT INTO prop_lines
               (player_id, season, week, market, side, line, price, book, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(player_id, season, week, market, side, book)
               DO UPDATE SET line=excluded.line, price=excluded.price,
                             created_at=excluded.created_at
               RETURNING id""",
            (stored["player_id"], season, body.week, norm["market"], norm["side"],
             norm["line"], norm["price"], norm["book"], _dt.datetime.now().isoformat()),
        )
        row_id = cur.fetchone()[0]
        conn.commit()
    # Edge preview when the cache is warm; cold cache still stores (200).
    edge, note = None, None
    projs = (cache.get("model_projections") or [])
    if projs and cache.get("player_stats"):
        by_id = {str(p.get("player_id") or ""): p for p in projs}
        hist = _props_history_lookup(cache.get("player_stats")).get(stored["player_id"], [])
        # why same REG/week filter as GET (data-engineer sign-off): POST preview
        # and GET must compute identical sigmas or the dedupe JSON diverges and
        # one stored line logs twice.
        hist = [h for h in hist
                if (h.get("season_type") or "REG") == "REG"
                and (h.get("week") or 0) < body.week]
        edge = _evaluate_prop_edge(
            by_id.get(stored["player_id"]), hist, stored,
            _props_calibration(),
        )
        # why log at submit (explicit user action): GET-time logging alone
        # makes crawlers/page-views the experiment's authors. POST logs the
        # surfaced VALUE once; GET catch-up below dedupes to the same row.
        if edge is not None and edge.get("decision") == "VALUE":
            with _league_conn(league_id) as log_conn:
                if log_conn is not None:
                    try:
                        shadow.log_prop_edge_once(
                            log_conn, f"prop:{edge['market']}", season,
                            body.week, edge["player_id"],
                            _prop_shadow_rec(edge),
                            datetime.datetime.now().isoformat(),
                        )
                    except Exception:
                        logger.exception("api: prop shadow log failed")
    else:
        note = "Stored. Cache cold — run /refresh for the edge preview."
    return {"stored": {**stored, "id": row_id}, "edge": edge, "note": note}


@app.get("/props/edges")
@app.get("/v1/props/edges")
def get_prop_edges(
    week: int | None = Query(default=None, ge=1, le=18),
    season: int | None = Query(default=None, ge=2000, le=2100),
    league_id: str | None = _league_query(),
) -> dict:
    cache = _cache_for(league_id)
    if not cache.get("model_projections") or not cache.get("player_stats"):
        raise HTTPException(
            status_code=503, detail="Data not available. Run /refresh first to load data."
        )
    season = season if season is not None else (cache.get("season") or get_stats_season())
    week = week if week is not None else (cache.get("week") or compute_nfl_week() or 1)
    calibration = _props_calibration()
    with _league_conn(league_id) as conn:
        if conn is None:
            raise HTTPException(status_code=503, detail="DB not available.")
        try:
            rows = conn.execute(
                "SELECT player_id, market, side, line, price, book FROM prop_lines "
                "WHERE season = ? AND week = ?",
                (season, week),
            ).fetchall()
        except Exception:
            # why retry-once, not unconditional init_schema per GET: old DBs
            # predate the table; pay the DDL cost once, only when missing.
            db.init_schema(conn)
            rows = conn.execute(
                "SELECT player_id, market, side, line, price, book FROM prop_lines "
                "WHERE season = ? AND week = ?",
                (season, week),
            ).fetchall()
        lines = [dict(r) for r in rows]
        by_id = {str(p.get("player_id") or ""): p for p in (cache.get("model_projections") or [])}
        hist_lookup = _props_history_lookup(cache.get("player_stats"))
        edges = []
        for ln in lines:
            stored = {
                "player_id": str(ln["player_id"]),
                "market": ln["market"],
                "side": ln["side"],
                "line": None if ln["line"] is None else float(ln["line"]),
                "price": float(ln["price"]),
                "book": ln["book"],
            }
            hist = [h for h in hist_lookup.get(stored["player_id"], [])
                    if (h.get("season_type") or "REG") == "REG"
                    and (h.get("week") or 0) < week]
            edge = _evaluate_prop_edge(by_id.get(stored["player_id"]), hist, stored, calibration)
            try:
                trusted = shadow.is_trusted(conn, f"prop:{stored['market']}")
            except Exception:
                trusted = False
            edge["shadow_status"] = "trusted" if trusted else "tracking"
            edges.append(edge)
        # why log-once, not batch: GETs poll — a bare INSERT duplicates every
        # view and inflates n, hit-rate, and the 20-resolved trust gate until
        # no calibration claim can stand (8-agent council vote). First serve
        # records the edge; re-polls are ignored. POST logs at submit time
        # (explicit action); both paths share _prop_shadow_rec + dedupe key.
        for e in edges:
            if e["decision"] == "VALUE":
                try:
                    shadow.log_prop_edge_once(
                        conn, f"prop:{e['market']}", season, week,
                        e["player_id"], _prop_shadow_rec(e),
                        datetime.datetime.now().isoformat(),
                    )
                except Exception:
                    logger.exception("api: prop shadow log failed")
    return {
        "edges": edges,
        "count": len(edges),
        "season": season,
        "week": week,
        "timestamp": cache["last_updated"],
    }