"""FastAPI app, run locally only (uvicorn on localhost — no public
hosting, see design spec's hosting decision). In-memory cache pattern
follows the reference repo's api.py: refresh populates a module-level
cache, request handlers read from it, never touching disk per-request."""

from fastapi import FastAPI, HTTPException, Query, Request, BackgroundTasks
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel
import datetime
import json
import logging
import re
import uuid
import contextvars
from contextlib import asynccontextmanager
from datetime import timedelta

import threading

from ffanalytics import db
from ffanalytics.config import compute_nfl_week, get_stats_season
from ffanalytics.refresh import run_refresh_with_data
from ffanalytics.decision import (
    get_start_sit_recommendations,
    get_waiver_priority,
    evaluate_trade,
    calculate_roster_value
)
from ffanalytics import shadow

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
    "player_stats": None,     # list of player stat dicts from nflverse
    "injury_status": None,    # dict mapping player_id to injury status
    "matchups": None,         # list of matchup dicts from Sleeper
    "trending": None,         # trending waiver adds
    "detailed_injuries": None, # practice participation status
    "last_updated": None,     # timestamp of last cache update
    "season": None,           # NFL season year
    "week": None,             # approximate NFL week (1-18)
}


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
) -> None:
    if league_settings:
        _CACHE["league_settings"] = league_settings
    if rosters:
        _CACHE["rosters"] = rosters
    if player_stats:
        _CACHE["player_stats"] = player_stats
    if injury_status:
        _CACHE["injury_status"] = injury_status
    if matchups:
        _CACHE["matchups"] = matchups
    if trending:
        _CACHE["trending"] = trending
    if detailed_injuries:
        _CACHE["detailed_injuries"] = detailed_injuries
    _CACHE["last_updated"] = datetime.datetime.now().isoformat()
    if season is not None:
        _CACHE["season"] = season
    if week is not None:
        _CACHE["week"] = week


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


def _batch_log_recommendations(kind: str, recommendations: list[dict]) -> None:
    """Log a batch of recommendations to the shadow table using a single
    executemany + commit (best-effort). Uses the per-request thread-local
    DB connection (db._get_conn()) so all writes share one connection and
    don't repeatedly open/close SQLite handles."""
    if not recommendations:
        return
    try:
        logged_at = datetime.datetime.now().isoformat()
        season = _CACHE.get("season")
        week = _CACHE.get("week")
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
def ready() -> dict:
    # Readiness — 503 until warmed via POST /refresh (same warmed predicate
    # as the /recommendations/* guards so load-balancers/monitors agree).
    if (
        not _CACHE.get("league_settings")
        or not _CACHE.get("rosters")
        or not _CACHE.get("player_stats")
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


def _do_refresh_job(season: int, stats_season: int, ran_at_iso: str, week: int) -> None:
    """Background refresh worker: owns its own long-lived DB connection and
    holds _REFRESH_LOCK until done (released here, not in the endpoint, so
    concurrent POSTs 409 while the job runs). Failures are per-source
    isolated inside run_refresh_with_data; a total crash is logged
    server-side — there is no request left to answer, so nothing is raised."""
    conn = db.get_connection()  # refresh is a long-running job; don't share
    try:
        status, data = run_refresh_with_data(
            conn,
            season=season,
            stats_season=stats_season,
            ran_at_iso=ran_at_iso
        )

        new_cache = dict(_CACHE)
        if data.get("league_settings"):
            new_cache["league_settings"] = data["league_settings"]
        if data.get("rosters"):
            new_cache["rosters"] = data["rosters"]
        if data.get("player_stats"):
            new_cache["player_stats"] = data["player_stats"]
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
        # starts as dict(_CACHE), so a single update() applies the delta
        # without an empty window while preserving _CACHE identity (update_cache
        # mutates in place, so rebinding _CACHE would orphan that path).
        _CACHE.update(new_cache)
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
def refresh(background_tasks: BackgroundTasks) -> dict:
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
        background_tasks.add_task(_do_refresh_job, season, stats_season, ran_at_iso, week)
    except Exception:
        try:
            _REFRESH_LOCK.release()
        except Exception:
            pass
        raise
    # why last-known sources: the job hasn't run yet, so per-source bools
    # can't be fresh; poll status_url for completion instead.
    try:
        sources = {s: v["success"] for s, v in _latest_source_status(db._get_conn()).items()}
    except Exception:
        sources = {}
    return {"status": "accepted", "sources": sources, "status_url": "/refresh/status"}


@app.get("/refresh/status")
@app.get("/v1/refresh/status")
def refresh_status() -> dict:
    # why: async POST returns before sources finish — hub/monitors poll here
    # for latest per-source success + ran_at instead of blocking on refresh.
    try:
        sources = _latest_source_status(db._get_conn())
    except Exception:
        sources = {}
    return {"sources": sources, "running": _REFRESH_LOCK.locked()}


@app.get("/news")
@app.get("/v1/news")
def get_news() -> dict:
    conn = db._get_conn()
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
) -> dict:
    # why limit/offset: hub fetchProjections already sends ?limit= (default
    # 800, up to 2000 for the auction board); previously the param was
    # silently ignored and the slice hardcoded to 800. Defaults preserve the
    # exact legacy body (players[0:800]) for hub compat.
    if _CACHE["player_stats"]:
        players = _CACHE["player_stats"]
        scoring = (_CACHE.get("league_settings") or {}).get("scoring_settings", {})
    else:
        conn = db._get_conn()
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
    for p in players[offset:offset + limit]:
        pid = str(p.get("player_id") or p.get("id") or "")
        pos = (p.get("position") or p.get("position_group") or "UNK").upper()
        pts = float(p.get("projected_points") or p.get("fantasy_points") or 0)
        if pts == 0 and scoring:
            from ffanalytics.scoring import calculate_fantasy_points
            try:
                pts = calculate_fantasy_points(p, scoring)
            except Exception:
                pass
        injury = (_CACHE.get("injury_status") or {}).get(pid)
        out.append({
            "player_id": pid,
            "player_name": p.get("player_display_name") or p.get("short_name") or p.get("player_name") or pid,
            "position": pos,
            "position_group": pos,
            # why canonical `team` first: `recent_team` lags for traded players.
            "team": p.get("team") or p.get("recent_team") or "",
            "opponent_team": p.get("opponent_team") or "",
            "projected_points": round(pts, 2),
            "injury_status": injury,
        })
    out.sort(key=lambda x: x["projected_points"], reverse=True)
    return {"players": out, "count": len(out), "meta": {"cached": bool(_CACHE["player_stats"])}}


@app.get("/recommendations/start-sit")
@app.get("/v1/recommendations/start-sit")
def get_start_sit(owner_id: str = Query(..., max_length=64, pattern=r"^\d+$")) -> dict:
    if not _CACHE["league_settings"] or not _CACHE["rosters"] or not _CACHE["player_stats"]:
        raise HTTPException(
            status_code=503,
            detail="Data not available. Run /refresh first to load data."
        )

    league_settings = _CACHE["league_settings"]
    rosters = _CACHE["rosters"]
    player_stats = _CACHE["player_stats"]
    injury_status = _CACHE["injury_status"] or {}

    scoring_settings = league_settings.get("scoring_settings", {})
    roster_positions = league_settings.get("roster_positions", [])

    try:
        roster_players, bench_players, _ = _process_roster_data(
            rosters, player_stats, injury_status, league_settings, owner_id=owner_id
        )

        recommendations = get_start_sit_recommendations(
            roster_players, bench_players, scoring_settings, roster_positions
        )

        _batch_log_recommendations("start_sit", recommendations)

        return {
            "recommendations": recommendations,
            "count": len(recommendations),
            "timestamp": _CACHE["last_updated"]
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("api: start-sit failed: %s", _sanitize_log(exc))
        raise HTTPException(status_code=500, detail="internal error")


@app.get("/recommendations/waiver")
@app.get("/v1/recommendations/waiver")
def get_waiver(owner_id: str = Query(..., max_length=64, pattern=r"^\d+$")) -> dict:
    if not _CACHE["league_settings"] or not _CACHE["rosters"] or not _CACHE["player_stats"]:
        raise HTTPException(
            status_code=503,
            detail="Data not available. Run /refresh first to load data."
        )

    league_settings = _CACHE["league_settings"]
    rosters = _CACHE["rosters"]
    player_stats = _CACHE["player_stats"]
    injury_status = _CACHE["injury_status"] or {}

    scoring_settings = league_settings.get("scoring_settings", {})
    roster_positions = league_settings.get("roster_positions", [])

    try:
        roster_players, _, free_agents = _process_roster_data(
            rosters, player_stats, injury_status, league_settings, owner_id=owner_id
        )

        recommendations = get_waiver_priority(
            roster_players, free_agents, scoring_settings, roster_positions
        )

        _batch_log_recommendations("waiver", recommendations)

        return {
            "recommendations": recommendations,
            "count": len(recommendations),
            "timestamp": _CACHE["last_updated"]
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
    team_b_id: str = Query(..., max_length=64, pattern=r"^\d+$")
) -> dict:
    if not _CACHE["league_settings"] or not _CACHE["rosters"] or not _CACHE["player_stats"]:
        raise HTTPException(
            status_code=503,
            detail="Data not available. Run /refresh first to load data."
        )

    league_settings = _CACHE["league_settings"]
    rosters = _CACHE["rosters"]
    player_stats = _CACHE["player_stats"]
    injury_status = _CACHE["injury_status"] or {}

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
            conn = db._get_conn()
            row = conn.execute("SELECT data FROM market_consensus ORDER BY fetched_at DESC LIMIT 1").fetchone()
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
        current_week = _CACHE.get("week") or compute_nfl_week()
        if current_week is None:
            current_week = 1

        result = evaluate_trade(
            team_a_players, team_b_players, scoring_settings, roster_positions,
            current_week=current_week,
            market_consensus=market_consensus,
            all_league_players=all_league_players,
        )

        _batch_log_recommendations("trade", [result])

        return {
            "trade_evaluation": result,
            "team_a_id": team_a_id,
            "team_b_id": team_b_id,
            "timestamp": _CACHE["last_updated"]
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("api: trade failed: %s", _sanitize_log(exc))
        raise HTTPException(status_code=500, detail="internal error")