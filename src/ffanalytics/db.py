import sqlite3
from pathlib import Path

from ffanalytics import config

_SCHEMA_PATH = Path(__file__).parent / "schema.sql"


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
    conn.execute("PRAGMA user_version=1")
    conn.commit()