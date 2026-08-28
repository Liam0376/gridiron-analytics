import sqlite3
from pathlib import Path

from ffanalytics import config

_SCHEMA_PATH = Path(__file__).parent / "schema.sql"


def get_connection(path: Path | None = None) -> sqlite3.Connection:
    db_path = path or config.DB_PATH
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(_SCHEMA_PATH.read_text())
    conn.commit()