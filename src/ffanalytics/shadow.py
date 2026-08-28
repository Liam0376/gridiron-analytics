"""Shadow-mode logging — every recommendation the decision layer produces
is logged here with its inputs and (later) the actual outcome, so a new
heuristic can be backtested before it's trusted live. Mirrors the
reference repo's shadow.py / evaluacion.py discipline."""

import json
import sqlite3


def log_recommendation(
    conn: sqlite3.Connection,
    kind: str,
    season: int,
    week: int,
    player_id: str | None,
    recommendation: dict,
    logged_at_iso: str,
) -> int:
    cursor = conn.execute(
        """INSERT INTO shadow_recommendations
           (kind, season, week, player_id, recommendation, logged_at, actual_outcome)
           VALUES (?, ?, ?, ?, ?, ?, NULL)""",
        (kind, season, week, player_id, json.dumps(recommendation), logged_at_iso),
    )
    conn.commit()
    return cursor.lastrowid


def record_outcome(conn: sqlite3.Connection, recommendation_id: int, actual_outcome: dict) -> None:
    conn.execute(
        "UPDATE shadow_recommendations SET actual_outcome = ? WHERE id = ?",
        (json.dumps(actual_outcome), recommendation_id),
    )
    conn.commit()


def count_logged(conn: sqlite3.Connection, kind: str) -> int:
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM shadow_recommendations WHERE kind = ?", (kind,)
    ).fetchone()
    return row["n"]