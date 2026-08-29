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


def evaluate_unresolved_shadow_recommendations(
    conn: sqlite3.Connection,
    player_stats: list[dict],
    scoring_settings: dict | None = None,
) -> int:
    """Find shadow recommendations awaiting outcome resolution and record their actual points.

    Returns count of updated shadow recommendation rows.
    """
    from ffanalytics.scoring import calculate_fantasy_points

    if not player_stats:
        return 0

    rows = conn.execute(
        "SELECT id, season, week, player_id FROM shadow_recommendations WHERE actual_outcome IS NULL AND player_id IS NOT NULL"
    ).fetchall()

    if not rows:
        return 0

    # Build lookup (player_id, week) -> actual_pts
    actuals = {}
    for p in player_stats:
        pid = str(p.get("player_id") or p.get("id") or "")
        wk = p.get("week")
        if pid and wk:
            fpts = p.get("fantasy_points")
            if fpts is None:
                fpts = calculate_fantasy_points(p, scoring_settings)
            actuals[(pid, int(wk))] = float(fpts)

    resolved = 0
    for r in rows:
        rec_id = r["id"]
        pid = str(r["player_id"])
        wk = r["week"]
        key = (pid, int(wk))
        if key in actuals:
            actual_pts = round(actuals[key], 2)
            record_outcome(conn, rec_id, {"actual_points": actual_pts, "week": wk})
            resolved += 1

    return resolved


def count_logged(conn: sqlite3.Connection, kind: str) -> int:
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM shadow_recommendations WHERE kind = ?", (kind,)
    ).fetchone()
    return row["n"]