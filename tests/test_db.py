import sqlite3
import tempfile
from pathlib import Path

from ffanalytics import db


def test_init_schema_creates_tables():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "test.db"
        conn = db.get_connection(path)
        db.init_schema(conn)
        tables = {
            row["name"]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        assert {"team_ratings", "refresh_log", "shadow_recommendations"} <= tables
        conn.close()


def test_get_connection_uses_wal_mode():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "test.db"
        conn = db.get_connection(path)
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert mode.lower() == "wal"
        conn.close()