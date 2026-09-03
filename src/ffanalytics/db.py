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
        # why these columns: they mirror the inline UNIQUE(...) constraints
        # already in schema.sql (season,week / season,week,kind / lat,lon,
        # game_time_iso / season), so fresh and live DBs converge.
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