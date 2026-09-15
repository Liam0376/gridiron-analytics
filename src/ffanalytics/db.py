import sqlite3
import threading
from pathlib import Path

from ffanalytics import config

_SCHEMA_PATH = Path(__file__).parent / "schema.sql"

# Per-request (thread-local) connection cache. FastAPI runs each request on
# its own thread under any sync worker model, so a thread-local connection
# is reused across db.get_connection() calls within one request without
# sharing connections across requests.
_tls = threading.local()


def _get_conn() -> sqlite3.Connection:
    # thread-local; reset_conn() releases at request teardown
    conn = getattr(_tls, "conn", None)
    if conn is None:
        conn = get_connection()
        _tls.conn = conn
    return conn


def reset_conn() -> None:
    conn = getattr(_tls, "conn", None)
    if conn is not None:
        try:
            conn.close()
        except Exception:
            pass
        _tls.conn = None


def get_connection(path: Path | None = None) -> sqlite3.Connection:
    db_path = path or config.DB_PATH
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    # Audit C3: verify WAL actually enabled (macOS temp DBs may fall back to DELETE)
    try:
        cur = conn.execute("PRAGMA journal_mode=WAL")
        mode = cur.fetchone()
        # mode may be tuple like ('wal',) or Row
        val = mode[0] if mode else ""
        if isinstance(val, str) and val.lower() != "wal":
            import warnings
            warnings.warn(f"journal_mode is {val!r} not WAL — concurrency degraded")
    except Exception:
        pass
    conn.execute("PRAGMA busy_timeout=5000")
    # Ensure foreign keys and synchronous=NORMAL for WAL
    try:
        conn.execute("PRAGMA synchronous=NORMAL")
    except Exception:
        pass
    try:
        conn.execute("PRAGMA foreign_keys=ON")
    except Exception:
        pass
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(_SCHEMA_PATH.read_text())
    _apply_migrations(conn)
    conn.commit()


def _apply_migrations(conn: sqlite3.Connection) -> None:
    """Idempotent user_version-based migrations.

    Each ``if user_version < N`` block is responsible for advancing to ``N``
    via ``PRAGMA user_version=N`` after applying its DDL. Migrations must be
    additive (CREATE INDEX / CREATE TABLE — never DROP) to remain safe to
    re-run across schema.sql regenerations.
    """
    try:
        row = conn.execute("PRAGMA user_version").fetchone()
        cur_version = int(row[0]) if row else 0
    except Exception:
        cur_version = 0

    if cur_version < 2:
        # Index v2 — shadow outcome lookups + news feed queries
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_shadow_unresolved "
            "ON shadow_recommendations(actual_outcome) WHERE actual_outcome IS NULL"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_news_kind_time "
            "ON news_data(kind, fetched_at DESC)"
        )
        conn.execute("PRAGMA user_version=2")

    if cur_version < 3:
        # P0 audit v3 — refresh_log per-source history index (mirrors schema.sql;
        # why: existing DBs created before schema.sql gained the index need it
        # backfilled; additive CREATE INDEX only, safe to re-run).
        # tested and REJECTED: DROP+recreate refresh_log to add index — destroys
        # audit history for zero query gain; IF NOT EXISTS is sufficient.
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_refresh_log_src_time "
            "ON refresh_log(source, ran_at DESC)"
        )
        # Ensure market_consensus exists on pre-P0 DBs so refresh.py lazy DDL
        # stays redundant-but-harmless (api POST /refresh never calls
        # init_schema, so CREATE TABLE IF NOT EXISTS is kept on the store path).
        conn.execute(
            """CREATE TABLE IF NOT EXISTS market_consensus (
                season INTEGER NOT NULL,
                week INTEGER NOT NULL,
                data JSON NOT NULL,
                fetched_at TEXT NOT NULL,
                PRIMARY KEY (season, week)
            )"""
        )
        conn.execute("PRAGMA user_version=3")

    if cur_version < 4:
        # Audit 6.0 migration v4 — backfill 6 drift UNIQUE indexes present on
        # the live data/fantasy.db with no source DDL. Column defs derived
        # read-only from the live DB (sqlite_master sql + PRAGMA index_info
        # + PRAGMA index_list unique=1); equivalent CREATE UNIQUE INDEX
        # IF NOT EXISTS here, additive only (never DROP), then user_version=4.
        # why UNIQUE not plain: live sqlite_master shows CREATE UNIQUE INDEX
        # for all six — a plain index would permit dupes the live DB rejects.
        # Audit 22.0: these are now redundant with the composite PRIMARY KEYs
        # in schema.sql for rosters, player_stats, news_data, market_consensus,
        # injury_status. Kept for migration idempotency (additive only, never DROP).
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_rosters_sw "
            "ON rosters(season, week)"
        )
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_player_stats_sw "
            "ON player_stats(season, week)"
        )
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_news_data_swk "
            "ON news_data(season, week, kind)"
        )
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_market_consensus_sw "
            "ON market_consensus(season, week)"
        )
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_weather_llg "
            "ON weather(lat, lon, game_time_iso)"
        )
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_injury_status_s "
            "ON injury_status(season)"
        )
        conn.execute("PRAGMA user_version=4")

    if cur_version < 5:
        # Props section v5 — manual book-line store (spec 2026-09-09).
        # Mirrors schema.sql; additive CREATE TABLE only, safe to re-run.
        # why side in UNIQUE: over and under on the same market/book are
        # independent trackable positions.
        conn.execute(
            """CREATE TABLE IF NOT EXISTS prop_lines (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                player_id TEXT NOT NULL,
                season INTEGER NOT NULL,
                week INTEGER NOT NULL,
                market TEXT NOT NULL,
                side TEXT NOT NULL,
                line REAL,
                price REAL NOT NULL,
                book TEXT NOT NULL DEFAULT 'manual',
                created_at TEXT NOT NULL,
                UNIQUE(player_id, season, week, market, side, book)
            )"""
        )
        conn.execute("PRAGMA user_version=5")

    if cur_version < 6:
        # Props council vote v6 — dedupe index for idempotent shadow logging.
        # Partial (prop kinds only) + non-unique: legacy rows can never fail
        # creation. Additive only, safe to re-run.
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_shadow_prop_dedupe "
            "ON shadow_recommendations(kind, season, week, player_id) "
            "WHERE kind LIKE 'prop:%'"
        )
        conn.execute("PRAGMA user_version=6")

    if cur_version < 7:
        # Roster-join crosswalk v7 — Sleeper ids (rosters) to GSIS ids
        # (nflverse stats). Additive CREATE TABLE only, safe to re-run.
        conn.execute(
            """CREATE TABLE IF NOT EXISTS sleeper_xwalk (
                sleeper_id TEXT PRIMARY KEY,
                gsis_id TEXT NOT NULL
            )"""
        )
        conn.execute("PRAGMA user_version=7")

    if cur_version < 8:
        # Database-audit v8 — count_logged/count_resolved (shadow.py) and
        # rating_updates.py's season-scoped team_ratings read were full
        # table scans with no covering index. Additive only, safe to re-run.
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_shadow_kind "
            "ON shadow_recommendations(kind)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_shadow_resolved "
            "ON shadow_recommendations(kind, actual_outcome) "
            "WHERE actual_outcome IS NOT NULL"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_team_ratings_season "
            "ON team_ratings(season)"
        )
        conn.execute("PRAGMA user_version=8")

    if cur_version < 9:
        # Audit 22.0 — sleeper_matchups WHERE week=? scans all-season rows
        # without a dedicated week index. The player_stats rowid index was
        # dropped because rowid can't be referenced by name in indexes on
        # tables with composite (non-INTEGER) PKs. Additive only, safe to
        # re-run.
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_matchups_week "
            "ON sleeper_matchups(week)"
        )
        conn.execute("PRAGMA user_version=9")

    if cur_version < 10:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS projection_snapshots (
                season INTEGER NOT NULL,
                week INTEGER NOT NULL,
                player_id TEXT NOT NULL,
                position TEXT NOT NULL,
                projected_points REAL NOT NULL,
                projection_low REAL,
                projection_high REAL,
                snapped_at TEXT NOT NULL,
                PRIMARY KEY (season, week, player_id)
            )"""
        )
        conn.execute("PRAGMA user_version=10")

    if cur_version < 11:
        # Rest-of-season projections v11 — per-player sum of independent
        # per-week projections. Populated during refresh from
        # build_weekly_projections called for each remaining week. Additive only.
        conn.execute(
            """CREATE TABLE IF NOT EXISTS ros_projections (
                season INTEGER NOT NULL,
                player_id TEXT NOT NULL,
                player_name TEXT NOT NULL,
                position TEXT NOT NULL,
                team TEXT NOT NULL,
                ros_points REAL NOT NULL,
                remaining_games INTEGER NOT NULL,
                per_game_neutral REAL NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (season, player_id)
            )"""
        )
        conn.execute("PRAGMA user_version=11")

    if cur_version < 12:
        # Weekly projections v12 — independent per-week projections (not
        # summed) for every remaining week, keyed by (season, week,
        # player_id). Populated during refresh from the same
        # build_weekly_projections() calls compute_ros_projections already
        # makes per remaining week — no new model computation, just
        # persisting what was previously discarded after summing into
        # ros_points. Fixes: hub Matchups/Projections week pickers showed
        # identical points for every week because nothing stored a
        # per-week breakdown to read from. Additive only.
        conn.execute(
            """CREATE TABLE IF NOT EXISTS weekly_projections (
                season INTEGER NOT NULL,
                week INTEGER NOT NULL,
                player_id TEXT NOT NULL,
                player_name TEXT NOT NULL,
                position TEXT NOT NULL,
                team TEXT NOT NULL,
                opponent_team TEXT,
                projected_points REAL NOT NULL,
                projection_lower REAL,
                projection_upper REAL,
                width REAL,
                wind_mph REAL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (season, week, player_id)
            )"""
        )
        conn.execute("PRAGMA user_version=12")